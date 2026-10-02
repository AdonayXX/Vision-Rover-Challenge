"""Mide si la PLACA puede planificar rutas con rutas.py. Nunca envía movimiento.

Casos, calculados con lo que ve la cámara ahora:
  directa      - 20 cm al frente del rover (tramo libre: no busca)
  rodear       - punto libre detrás del cubo más cercano (obliga al A*)
  lejos tapado - el punto libre más lejano sin línea recta (búsqueda más larga)
Cada caso se planifica en la placa con paso de grilla 2 y luego 1, y en la PC
con el mismo planificador para comparar tiempos y rutas.
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
from rutas_placa import EstadoPlaca
from rutas import RoutePlanner

MARGEN = 6.0        # celdas desde el borde: el planificador exige ~4,75


def casos(mensaje, robot_id):
    """Elige destinos LIBRES; los dos últimos además tapados en línea recta (fuerzan el A*)."""
    grid = mensaje["grid"]
    cell = grid["cell_mm"]
    rover = next(r for r in mensaje["rovers"] if r["id"] == robot_id)
    planner = RoutePlanner(85, 85, 10, required_colors=())
    escena = planner.scene(EstadoPlaca(mensaje, robot_id))
    inicio = (rover["col"], rover["row"])

    def dentro(col, row):
        return {"col": round(min(grid["cols"] - MARGEN, max(MARGEN, col)), 2),
                "row": round(min(grid["rows"] - MARGEN, max(MARGEN, row)), 2)}

    # Directa: hasta 20 cm al frente, acortando si hay un cubo delante.
    th = math.radians(rover["theta"])
    resultado = []
    for mm in range(200, 0, -20):
        p = dentro(rover["col"] + mm / cell * math.cos(th), rover["row"] - mm / cell * math.sin(th))
        if planner.free_segment(escena, inicio, (p["col"], p["row"])):
            resultado.append(("directa {} mm".format(mm), p))
            break
    # Candidatos cada media celda: libres para el cuerpo y sin línea recta desde el rover.
    tapados = []
    for i in range(int(grid["cols"] * 2) + 1):
        for j in range(int(grid["rows"] * 2) + 1):
            p = (i / 2, j / 2)
            if planner.free_segment(escena, p, p) and not planner.free_segment(escena, inicio, p):
                tapados.append(p)
    if not tapados:
        print("Ningun cubo tapa el camino a un punto libre: acerca un cubo al frente del rover.")
        return resultado
    if mensaje["cubes"]:
        cubo = min(mensaje["cubes"], key=lambda c: math.hypot(c["col"] - inicio[0], c["row"] - inicio[1]))
        dc, dr = cubo["col"] - inicio[0], cubo["row"] - inicio[1]
        largo = math.hypot(dc, dr) or 1
        ideal = (cubo["col"] + dc / largo * 230 / cell, cubo["row"] + dr / largo * 230 / cell)
        p = min(tapados, key=lambda q: math.hypot(q[0] - ideal[0], q[1] - ideal[1]))
        resultado.append(("rodear " + cubo["color"], {"col": p[0], "row": p[1]}))
    p = max(tapados, key=lambda q: math.hypot(q[0] - inicio[0], q[1] - inicio[1]))
    resultado.append(("lejos tapado", {"col": p[0], "row": p[1]}))
    return resultado


def en_pc(mensaje, robot_id, objetivo, paso):
    planner = RoutePlanner(85, 85, 10, step_cells=paso, required_colors=())
    t0 = time.perf_counter()
    ruta = planner.plan(EstadoPlaca(mensaje, robot_id), objetivo)
    return (time.perf_counter() - t0) * 1000, ruta


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--robot-ip", required=True)
    p.add_argument("--robot-id", type=int, default=10)
    p.add_argument("--vision-host", default="127.0.0.1")
    p.add_argument("--pasos", default="2,1", help="pasos de grilla a probar, en orden")
    args = p.parse_args()

    state = DevelopmentTelemetryState(robot_id=args.robot_id, peer_id=args.robot_id + 1, max_age_ms=900)
    vision = VisionClient(state, args.vision_host)
    fin = time.monotonic() + 10
    while (state.message is None or state.rover(args.robot_id) is None) and time.monotonic() < fin:
        vision.poll()
        time.sleep(.02)
    if state.message is None or state.rover(args.robot_id) is None:
        print("La vision no muestra al rover", args.robot_id)
        return 1
    mensaje = state.message
    vision.close()

    robot = RobotClient(args.robot_ip, wait_seconds=30)
    robot.connect()                 # STOP confirmado; despues solo RUTA
    robot.sock.settimeout(90)       # una ruta en la placa puede tardar segundos
    estado = json.loads(robot._exchange("SENSORS"))
    print("Placa encendida hace {} s; ultimo reinicio: {}; fallos: {}".format(
        estado.get("uptime_s"), estado.get("reset_reason"), estado.get("fallos")))
    print("Cubos vistos:", [(c["color"], round(c["col"], 1), round(c["row"], 1)) for c in mensaje["cubes"]])
    try:
        for nombre, objetivo in casos(mensaje, args.robot_id):
            for paso in [int(x) for x in args.pasos.split(",")]:
                ms_pc, ruta_pc = en_pc(mensaje, args.robot_id, objetivo, paso)
                try:
                    respuesta = robot._exchange("RUTA|{}|{}|{}".format(objetivo["col"], objetivo["row"], paso))
                except (ConnectionError, OSError) as error:
                    print("\nLa placa corto la conexion durante RUTA ({}).".format(error))
                    robot.connect()
                    estado = json.loads(robot._exchange("SENSORS"))
                    print("Registro de fallos del rover:", estado.get("fallos"))
                    print("Encendido hace {} s (si es poco, se reinicio).".format(estado.get("uptime_s")))
                    return 1
                try:
                    placa = json.loads(respuesta)
                except ValueError:
                    print("Respuesta no valida (¿firmware sin RUTA?):", respuesta)
                    return 1
                print("\n== {} -> ({}, {})  paso {}".format(nombre, objetivo["col"], objetivo["row"], paso))
                print("   PC   : {:7.1f} ms  {}  {} puntos{}  {} mm".format(
                    ms_pc, ruta_pc["estado"], len(ruta_pc["puntos"]),
                    " (rodea con A*)" if len(ruta_pc["puntos"]) > 2 else "",
                    None if ruta_pc["distancia_mm"] is None else round(ruta_pc["distancia_mm"])))
                print("   placa: {}".format(json.dumps(placa)))
                if placa.get("error") or (placa.get("plan_ms") or 0) > 30000:
                    print("   (se omiten pasos mas finos para este caso)")
                    break
    finally:
        robot.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
