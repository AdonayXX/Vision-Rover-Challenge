"""Monitor y calibración de color SIN órdenes de movimiento."""
import argparse
import json
import math
from pathlib import Path
import statistics
import time

from prueba_transporte_cubo import RobotClient


COLOR_INDEX = {"red": 0, "green": 1, "blue": 2}


def firma_aceptable_para(color, signature, margin=.08):
    if color not in COLOR_INDEX or not isinstance(signature, list) or len(signature) != 3:
        return False
    if any(not isinstance(value, (int, float)) or not math.isfinite(value)
           or not 0 <= value <= 1 for value in signature):
        return False
    if abs(sum(signature) - 1) > .01:
        return False
    ordered = sorted(signature, reverse=True)
    return signature[COLOR_INDEX[color]] == ordered[0] and ordered[0] - ordered[1] >= margin


def distancia(a, b):
    return math.sqrt(sum((x - y) ** 2 for x, y in zip(a, b)))


def agrupar_firmas(signatures, radius=.10, max_profiles=4):
    """Extrae grupos densos y descarta como ruido hasta 30 % de las firmas."""
    remaining = list(enumerate(signatures))
    clusters = []
    covered = 0
    while len(remaining) >= 3 and len(clusters) < max_profiles:
        seed = max(
            remaining,
            key=lambda item: sum(distancia(item[1], other[1]) <= radius
                                 for other in remaining)
        )[1]
        members = [item for item in remaining if distancia(item[1], seed) <= radius]
        mean = [statistics.mean(item[1][i] for item in members) for i in range(3)]
        members = [item for item in remaining if distancia(item[1], mean) <= radius]
        if len(members) < 3:
            break
        mean = [statistics.mean(item[1][i] for item in members) for i in range(3)]
        clusters.append(mean)
        used = {item[0] for item in members}
        covered += len(used)
        remaining = [item for item in remaining if item[0] not in used]
    required = max(6, math.ceil(len(signatures) * .70))
    if covered < required:
        raise ValueError(
            "Las firmas no forman grupos estables suficientes: {}/{} cubiertas"
            .format(covered, len(signatures))
        )
    return clusters, len(signatures) - covered


def guardar_perfil(path, color, signatures, escenario="default"):
    if not escenario or len(escenario) > 32 or any(
            not (char.isalnum() or char in "_-") for char in escenario):
        raise ValueError("El escenario solo admite letras, numeros, _ y -")
    if len(signatures) < 6:
        raise ValueError("Hacen falta 6 resultados RGB consolidados distintos")
    if any(not firma_aceptable_para(color, signature) for signature in signatures):
        raise ValueError("Hay firmas que no distinguen el canal del color presentado")
    means, discarded = agrupar_firmas(signatures)
    cfg = json.loads(path.read_text(encoding="utf-8"))
    configured = cfg["color"]["profiles"].get(color, {})
    if isinstance(configured, list):
        configured = {"legacy": configured}
    for label in list(configured):
        if label == escenario or label.startswith(escenario + "_"):
            del configured[label]
    for index, mean in enumerate(means, 1):
        label = escenario if len(means) == 1 else "{}_{}".format(escenario, index)
        configured[label] = mean
    cfg["color"]["profiles"][color] = configured
    from sensores_rover import clasificar_color, perfiles_completos, validar_config
    validar_config(cfg)
    profiles = cfg["color"]["profiles"]
    if perfiles_completos(profiles):
        for expected, scenarios in profiles.items():
            values = scenarios.values() if isinstance(scenarios, dict) else (scenarios,)
            for signature in values:
                actual = clasificar_color(
                    signature, profiles,
                    cfg["color"]["tolerance"], cfg["color"]["margin"]
                )
                if actual != expected:
                    raise ValueError(
                        "El perfil {} de {} se confunde con otro color; perfil NO guardado"
                        .format(escenario, color)
                    )
    path.write_text(json.dumps(cfg, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return means, discarded


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--robot-ip", required=True)
    p.add_argument("--robot-port", type=int, default=5000)
    p.add_argument("--segundos", type=float)
    p.add_argument("--calibrar-color", choices=("red", "green", "blue"))
    p.add_argument("--escenario", default="default",
                   help="Nombre de la condicion de luz, por ejemplo artificial, tenue o natural")
    p.add_argument("--config", type=Path,
                   default=Path(__file__).resolve().parents[1] / "codigos/config_sensores.json")
    args = p.parse_args(argv)
    if args.segundos is None:
        args.segundos = 100 if args.calibrar_color else 10
    if not 0 < args.segundos <= 180:
        p.error("--segundos debe estar entre 0 y 180")
    client = RobotClient(args.robot_ip, args.robot_port, timeout=5.0)
    signatures, seen = [], set()
    rejected = 0
    consecutive_errors = 0
    try:
        client.connect()  # STOP confirmado. Nunca se envía MOTOR, TURN ni HEADING.
        print("Motores detenidos. No abrir otro cliente TCP simultaneamente.")
        if args.calibrar_color:
            print("Midiendo {} en escenario {}: colocar ese cubo quieto a 1 cm del sensor.".format(
                args.calibrar_color, args.escenario))
        end = time.monotonic() + args.segundos
        while time.monotonic() < end:
            try:
                status = client.sensors()
                consecutive_errors = 0
            except OSError as exc:
                consecutive_errors += 1
                if consecutive_errors >= 4:
                    raise
                print("Pausa de enlace ({}/3): {}. Reconectando sin perder muestras...".format(
                    consecutive_errors, exc), flush=True)
                client.close(send_stop=False)
                time.sleep(1)
                client.connect()
                continue
            signature = status.get("color_signature")
            seq, age = status.get("color_seq"), status.get("color_age_ms")
            if seq not in seen and age is not None and age < 1000:
                seen.add(seq)
                if args.calibrar_color:
                    candidates = status.get("color_sweep_signatures") or (
                        [signature] if signature is not None else []
                    )
                    for candidate in candidates:
                        if firma_aceptable_para(args.calibrar_color, candidate):
                            signatures.append(candidate)
                        else:
                            rejected += 1
                    print("Resultado {}: {} firmas aceptadas, {} rechazadas".format(
                        seq, len(signatures), rejected), flush=True)
                else:
                    print(json.dumps(status, ensure_ascii=False), flush=True)
            elif not args.calibrar_color:
                print(json.dumps(status, ensure_ascii=False), flush=True)
            time.sleep(.25)
        if args.calibrar_color:
            print("Resultados frescos: {}; firmas aceptadas: {}; rechazadas: {}.".format(
                len(seen), len(signatures), rejected))
            profiles, discarded = guardar_perfil(
                args.config, args.calibrar_color, signatures, args.escenario
            )
            print("Escenario {} guardado SOLO EN PC para {}: {} perfiles; {} atipicos descartados".format(
                args.escenario, args.calibrar_color, len(profiles), discarded))
            for index, profile in enumerate(profiles, 1):
                print("  perfil {}: {}".format(
                    index, [round(value, 5) for value in profile]))
            print("Tras calibrar los tres colores y escenarios, sube config_sensores.json y reinicia la placa.")
        return 0
    except (OSError, ValueError) as exc:
        print("ERROR:", exc)
        return 1
    except KeyboardInterrupt:
        return 130
    finally:
        client.close()


if __name__ == "__main__":
    raise SystemExit(main())
