"""Escenarios estáticos de rutas, sin motores ni afirmaciones de precisión física."""
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "codigos"))
from rutas import RoutePlanner
from telemetria import TelemetryState


def scenario():
    """Cancha de prueba reproducible; todos los tamaños son hipótesis."""
    return {
        "v": 2, "seq": 1, "ts_ms": 1000000, "phase": "RUNNING",
        "clock": {"elapsed_ms": 0, "remaining_ms": 60000, "total_ms": 60000},
        "grid": {"cols": 43, "rows": 43, "cell_mm": 20},
        "start": {"col": 5, "row": 21}, "depot_size": {"length": 10, "depth": 7.5}, "cube_side": 3,
        "rovers": [{"id": 10, "col": 7, "row": 21, "theta": 0, "age_ms": 0},
                   {"id": 11, "col": 35, "row": 34, "theta": 180, "age_ms": 0}],
        "cubes": [{"color": "red", "col": 21, "row": 21, "age_ms": 0},
                  {"color": "green", "col": 10, "row": 34, "age_ms": 0},
                  {"color": "blue", "col": 30, "row": 10, "age_ms": 0}],
        "depots": [{"color": "red", "col": 39.25, "row": 21.5},
                   {"color": "green", "col": 21.5, "row": 3.75},
                   {"color": "blue", "col": 21.5, "row": 39.25}],
        "obstacles": [],
    }


def run_demo(announce=print):
    config = json.loads(Path(__file__).with_name("rutas.example.json").read_text(encoding="utf-8"))
    planner = RoutePlanner(**config)
    state = TelemetryState(monotonic=lambda: 0, wall=lambda: 1000)
    state.connect()
    msg = scenario()

    def observe():
        msg["seq"] += 1
        if not state.accept_line(json.dumps(msg)):
            raise AssertionError(state.fault)

    observe()
    goal = {"col": 36, "row": 21}
    route = planner.plan(state, goal)
    if route["estado"] != "RUTA" or len(route["puntos"]) < 3:
        raise AssertionError("No encontro un desvio: " + str(route))
    announce("RUTA alrededor del cubo rojo: " + str(route["puntos"]))
    announce("Longitud prevista: {:.1f} mm (recta bloqueada: 580 mm).".format(route["distancia_mm"]))
    # El compañero ocupa un punto interior de la ruta anterior.
    msg["rovers"][1].update(route["puntos"][1])
    observe()
    changed = planner.plan(state, goal)
    if changed["estado"] == "RUTA" and changed["puntos"] == route["puntos"]:
        raise AssertionError("Conservo una ruta ocupada")
    announce("Nueva posicion del compañero: " + changed["estado"] + " / " + changed["motivo"])
    # El centro de un cubo no es un destino libre para navegación ordinaria.
    occupied = planner.plan(state, {"col": 21, "row": 21})
    if occupied["estado"] != "ESPERAR":
        raise AssertionError("Acepto destino dentro de un cubo")
    announce("Destino ocupado: ESPERAR.")
    msg["cubes"][0]["age_ms"] = 600
    observe()
    stale = planner.plan(state, goal)
    if stale["estado"] != "ESPERAR":
        raise AssertionError("Planifico con cubo viejo")
    announce("Cubo sin observacion reciente: ESPERAR.")
    return {"resultado": "OK", "ruta_inicial": route,
            "tras_mover_companero": changed["estado"],
            "destino_ocupado": occupied["estado"], "dato_viejo": stale["estado"],
            "alcance": "geometria_estatica_con_dimensiones_supuestas"}


if __name__ == "__main__":
    print("Tamaños de ejemplo: radios de 85 mm y margen de 15 mm. Falta medir hardware.")
    print(json.dumps(run_demo(), ensure_ascii=False, indent=2))
