"""Prueba del incremento 1: el ROVER va solo a un punto (control en la placa).

La laptop solo hace tres cosas, todas de desarrollo:
  1. calcula el punto (relativo a donde está el rover ahora),
  2. manda `IR|col|row` y luego solo pregunta el estado (SENSORS),
  3. al final mide con la visión dónde quedó de verdad.
Ctrl+C o cerrar el script detiene al rover: la misión no sobrevive a la conexión.
"""
import argparse
import json
import math
from pathlib import Path
import sys
import time

from cliente_vision import VisionClient
from prueba_transporte_cubo import DevelopmentTelemetryState, RobotClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "codigos"))
from modelo_rover import ModeloRover

CODIGOS = Path(__file__).resolve().parents[1] / "codigos"   # modelo_movimiento_<id>.json
MARGEN_BORDE_MM = 120


def esperar_rover(vision, state, robot_id, segundos=10):
    fin = time.monotonic() + segundos
    while time.monotonic() < fin:
        vision.poll()
        if state.reason() is None and state.rover(robot_id) is not None:
            return state.rover(robot_id)
        time.sleep(.02)
    raise RuntimeError("Vision no lista: {}".format(state.reason()))


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--robot-ip", required=True)
    p.add_argument("--robot-id", type=int, default=10)
    p.add_argument("--vision-host", default="127.0.0.1")
    p.add_argument("--adelante", type=float, default=300, help="mm hacia donde mira el rover")
    p.add_argument("--izquierda", type=float, default=0, help="mm a su izquierda (negativo: derecha)")
    p.add_argument("--col", type=float, help="objetivo absoluto (en lugar de relativo)")
    p.add_argument("--row", type=float)
    p.add_argument("--segundos", type=float, default=20)
    args = p.parse_args()

    archivo = CODIGOS / "modelo_movimiento_{}.json".format(args.robot_id)
    modelo = ModeloRover.desde_resumen(json.loads(archivo.read_text(encoding="utf-8"))["resumen"])
    state = DevelopmentTelemetryState(robot_id=args.robot_id, peer_id=args.robot_id + 1, max_age_ms=900)
    vision = VisionClient(state, args.vision_host)
    robot = RobotClient(args.robot_ip, wait_seconds=30)
    try:
        marcador = esperar_rover(vision, state, args.robot_id)
        grid = state.message["grid"]
        cell = grid["cell_mm"]
        centro = modelo.centro_desde_marcador(marcador, cell)
        if args.col is not None:
            objetivo = {"col": args.col, "row": args.row}
        else:
            th = math.radians(centro["theta"])
            objetivo = {"col": centro["col"] + (args.adelante * math.cos(th) - args.izquierda * math.sin(th)) / cell,
                        "row": centro["row"] - (args.adelante * math.sin(th) + args.izquierda * math.cos(th)) / cell}
        bordes = (objetivo["col"] * cell, (grid["cols"] - objetivo["col"]) * cell,
                  objetivo["row"] * cell, (grid["rows"] - objetivo["row"]) * cell)
        if min(bordes) < MARGEN_BORDE_MM:
            raise RuntimeError("Objetivo a menos de {} mm de un borde".format(MARGEN_BORDE_MM))
        print("Centro del rover: col={:.2f} row={:.2f} theta={:.0f}  ->  objetivo col={:.2f} row={:.2f}".format(
            centro["col"], centro["row"], centro["theta"], objetivo["col"], objetivo["row"]), flush=True)

        robot.connect()
        robot.confirmar_identidad(args.robot_id)
        robot.send("IR|{:.3f}|{:.3f}".format(objetivo["col"], objetivo["row"]), force=True)
        print("Mision enviada; el rover decide solo. Ctrl+C lo detiene.", flush=True)
        inicio = time.monotonic()
        ultimo = None
        while time.monotonic() - inicio < args.segundos:
            vision.poll()
            mision = json.loads(robot._exchange("SENSORS")).get("mision")
            if mision is None:
                raise RuntimeError("El firmware no tiene mision: sube autonomia.py y wifi_command_receiver.py")
            linea = "{:5.1f}s {:16s} d={}mm err={}° cmd={} edad={}ms adelanto={}mm escalas={} {}".format(
                time.monotonic() - inicio, mision["estado"], mision.get("d_mm"), mision.get("err_deg"),
                mision.get("cmd"), mision.get("edad_ms"), mision.get("adelanto_mm"),
                mision.get("escalas"), mision.get("motivo") or "")
            if linea[7:] != ultimo:
                print(linea, flush=True)
                ultimo = linea[7:]
            if mision["estado"] in ("LLEGO", "ABORTADO"):
                break
            time.sleep(.2)
        else:
            print("Tiempo agotado; STOP.")
    except KeyboardInterrupt:
        print("Detenido por usuario.")
    finally:
        print("STOP confirmado." if robot.close() else "Sin confirmacion de STOP.", flush=True)

    # Comprobación independiente con la visión de la laptop.
    time.sleep(1.0)
    try:
        final = modelo.centro_desde_marcador(esperar_rover(vision, state, args.robot_id, 3), cell)
        error = math.hypot(final["col"] - objetivo["col"], final["row"] - objetivo["row"]) * cell
        print("Medido por la vision: el centro quedo a {:.0f} mm del objetivo.".format(error))
    except (RuntimeError, NameError, UnboundLocalError):
        pass
    finally:
        vision.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
