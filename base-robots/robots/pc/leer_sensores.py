"""Monitor y calibración de color SIN órdenes de movimiento."""
import argparse
import json
from pathlib import Path
import statistics
import time

from prueba_transporte_cubo import RobotClient


def guardar_perfil(path, color, signatures):
    if len(signatures) < 12:
        raise ValueError("Hacen falta 12 barridos RGB completos distintos")
    mean = [statistics.mean(s[i] for s in signatures) for i in range(3)]
    if any(sum((a - b) ** 2 for a, b in zip(s, mean)) ** .5 > .08 for s in signatures):
        raise ValueError("Firmas RGB inconsistentes entre barridos; perfil NO guardado. "
                         "Esto no demuestra movimiento del cubo. Revisar muestreo y respuesta optica.")
    cfg = json.loads(path.read_text(encoding="utf-8"))
    cfg["color"]["profiles"][color] = mean
    from sensores_rover import validar_config
    validar_config(cfg)
    path.write_text(json.dumps(cfg, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--robot-ip", required=True)
    p.add_argument("--robot-port", type=int, default=5000)
    p.add_argument("--segundos", type=float, default=10)
    p.add_argument("--calibrar-color", choices=("red", "green", "blue"))
    p.add_argument("--config", type=Path,
                   default=Path(__file__).resolve().parents[1] / "codigos/config_sensores.json")
    args = p.parse_args(argv)
    if not 0 < args.segundos <= 120:
        p.error("--segundos debe estar entre 0 y 120")
    client = RobotClient(args.robot_ip, args.robot_port)
    signatures, seen = [], set()
    try:
        client.connect()  # STOP confirmado. Nunca se envía MOTOR, TURN ni HEADING.
        print("Motores detenidos. No abrir otro cliente TCP simultaneamente.")
        if args.calibrar_color:
            print("Midiendo {}: colocar ese cubo ante el sensor, quieto y a distancia de trabajo.".format(args.calibrar_color))
        end = time.monotonic() + args.segundos
        while time.monotonic() < end:
            status = client.sensors()
            print(json.dumps(status, ensure_ascii=False), flush=True)
            signature = status.get("color_signature")
            seq, age = status.get("color_seq"), status.get("color_age_ms")
            if seq not in seen and age is not None and age < 400:
                seen.add(seq)
                if signature is not None:
                    signatures.append(signature)
            time.sleep(.25)
        if args.calibrar_color:
            print("Barridos frescos distintos: {}; con firma: {}; sin senal suficiente: {}.".format(
                len(seen), len(signatures), len(seen) - len(signatures)))
            guardar_perfil(args.config, args.calibrar_color, signatures)
            print("Perfil guardado SOLO EN PC: {}. Tras calibrar los tres colores, sube config_sensores.json y reinicia la placa.".format(args.config))
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
