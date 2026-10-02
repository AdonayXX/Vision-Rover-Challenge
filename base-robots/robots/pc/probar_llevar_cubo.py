"""Prueba del incremento 2: el ROVER lleva solo un cubo a su zona (todo en la placa).

La laptop solo hace tres cosas, todas de desarrollo:
  1. manda `LLEVAR|color`,
  2. pregunta el estado (SENSORS) y lo muestra cuando cambia,
  3. al final comprueba con SU visión si el cubo quedó entero en su zona.
Ctrl+C o cerrar el script detiene al rover: la misión no sobrevive a la conexión.
"""
import argparse
import json
from pathlib import Path
import sys
import time

from cliente_vision import VisionClient
from prueba_transporte_cubo import DevelopmentTelemetryState, RobotClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "codigos"))
from llevar_cubo import cubo_en_su_zona

CAMPOS = ("d_mm", "err_deg", "resto_mm", "falta_mm", "linea_mm", "us_mm", "edad_ms")
AVISOS = ("retroceso", "estorbo", "reubicar", "submeta", "espera", "cubo_estimado", "error_carga")


def esperar_escena(vision, state, robot_id, color, segundos=10):
    fin = time.monotonic() + segundos
    while time.monotonic() < fin:
        vision.poll()
        if state.message and state.rover(robot_id) and state.cube(color):
            return state.message
        time.sleep(.02)
    raise RuntimeError("La vision no muestra al rover {} y al cubo {}".format(robot_id, color))


def estado_cubo(mensaje, color):
    cubo = next(c for c in mensaje["cubes"] if c["color"] == color)
    zona = next(d for d in mensaje["depots"] if d["color"] == color)
    adentro, falta = cubo_en_su_zona(cubo, zona, mensaje["depot_size"], mensaje["grid"], mensaje["cube_side"])
    return cubo, zona, adentro, falta * mensaje["grid"]["cell_mm"]


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--robot-ip", required=True)
    p.add_argument("--color", required=True, choices=("red", "green", "blue"))
    p.add_argument("--robot-id", type=int, default=10)
    p.add_argument("--vision-host", default="127.0.0.1")
    p.add_argument("--segundos", type=float, default=160)
    args = p.parse_args()

    state = DevelopmentTelemetryState(robot_id=args.robot_id, peer_id=args.robot_id + 1, max_age_ms=900)
    vision = VisionClient(state, args.vision_host)
    robot = RobotClient(args.robot_ip, wait_seconds=30)
    resultado = None
    try:
        mensaje = esperar_escena(vision, state, args.robot_id, args.color)
        cubo, zona, adentro, falta = estado_cubo(mensaje, args.color)
        print("Cubo {} en ({:.2f}, {:.2f}); su zona en ({:.2f}, {:.2f}); le faltan {:.0f} mm.".format(
            args.color, cubo["col"], cubo["row"], zona["col"], zona["row"], falta), flush=True)

        robot.connect()
        robot.sock.settimeout(10)    # planificar bloquea la placa ~0,4-2 s
        estado = robot.confirmar_identidad(args.robot_id)
        print("Placa encendida hace {} s; ultimo reinicio: {}; fallos: {}".format(
            estado.get("uptime_s"), estado.get("reset_reason"), estado.get("fallos")), flush=True)
        respuesta = robot._exchange("LLEVAR|" + args.color)
        if respuesta != "OK":
            mision = json.loads(robot._exchange("SENSORS")).get("mision") or {}
            raise RuntimeError("La placa rechazo LLEVAR ({}). {}".format(
                respuesta, mision.get("error_carga") or "Sube llevar_cubo.py, autonomia.py, "
                "sesion_comandos.py, command_protocol.py y wifi_command_receiver.py"))
        print("Mision enviada; el rover decide solo. Ctrl+C lo detiene.\n", flush=True)

        inicio = time.monotonic()
        anterior, ultimo_print = None, 0
        while time.monotonic() - inicio < args.segundos:
            vision.poll()
            mision = json.loads(robot._exchange("SENSORS")).get("mision") or {}
            clave = (mision.get("estado"), mision.get("motivo"), mision.get("replanes"), mision.get("empujes"))
            if clave != anterior or time.monotonic() - ultimo_print > 2:
                datos = " ".join("{}={}".format(k, mision[k]) for k in CAMPOS if mision.get(k) is not None)
                avisos = " ".join("{}={}".format(k, mision[k]) for k in AVISOS if mision.get(k))
                print("{:5.1f}s {:11s} {} | intentos={} empujes={} paradas={} {} {}".format(
                    time.monotonic() - inicio, str(mision.get("estado")), datos, mision.get("replanes"),
                    mision.get("empujes"), mision.get("esperas"), avisos, mision.get("motivo") or ""), flush=True)
                anterior, ultimo_print = clave, time.monotonic()
            if mision.get("estado") in ("ENTREGADO", "ABORTADO", "INACTIVO"):
                resultado = mision
                break
            time.sleep(.25)
        else:
            print("Tiempo agotado; STOP.")
    except KeyboardInterrupt:
        print("Detenido por usuario.")
    finally:
        print("STOP confirmado." if robot.close() else "Sin confirmacion de STOP.", flush=True)

    # Comprobación independiente con la visión de la laptop.
    time.sleep(1.0)
    try:
        mensaje = esperar_escena(vision, state, args.robot_id, args.color, 3)
        cubo, _, adentro, falta = estado_cubo(mensaje, args.color)
        print("Medido por la vision: cubo en ({:.2f}, {:.2f}) -> {}".format(
            cubo["col"], cubo["row"], "DENTRO de su zona" if adentro else "le faltan {:.0f} mm".format(falta)))
        if resultado:
            print("Tiempo de la mision: {:.1f} s".format(resultado.get("t_ms", 0) / 1000))
    except RuntimeError as error:
        print(error)
    finally:
        vision.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
