"""Ensayo numérico de llegada a un punto, con movimiento ideal sin fricción."""
import copy
import json
import math
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "codigos"))
from navegacion import PointNavigator
from telemetria import TelemetryState


def run_demo(announce=print):
    base = Path(__file__).resolve().parents[2]
    config = json.loads((base / "vision-system/contrato/config_simulador.json").read_text(encoding="utf-8"),
                        object_hook=lambda d: {k: v for k, v in d.items() if not k.startswith("_")})
    message = {key: copy.deepcopy(config[key]) for key in
               ("grid", "start", "depots", "depot_size", "cube_side", "cubes", "rovers", "obstacles")}
    for key in ("rovers", "cubes", "obstacles"):
        for entity in message[key]:
            entity["age_ms"] = 0
    message.update(v=2, phase="RUNNING", seq=0, ts_ms=1000000,
                   clock={"elapsed_ms": 0, "remaining_ms": 60000, "total_ms": 60000})
    virtual_time = [0.0]
    state = TelemetryState(monotonic=lambda: virtual_time[0], wall=lambda: 1000 + virtual_time[0])
    state.connect()
    navigator = PointNavigator(position_tolerance_mm=20, angle_tolerance_deg=5)
    target = {"col": 15.0, "row": 10.0}
    own = next(r for r in message["rovers"] if r["id"] == state.robot_id)
    previous = None
    paused = False
    announce("Modelo ideal: no representa friccion, inercia, colisiones ni motores reales.")
    announce("Objetivo: col=15, row=10; tolerancia de posicion=20 mm.")
    for step in range(300):
        message["seq"] += 1
        message["ts_ms"] = int((1000 + virtual_time[0]) * 1000)
        if not state.accept_line(json.dumps(message)):
            raise AssertionError(state.fault)
        decision = navigator.decide(state, target)
        action, metrics = decision["accion"], decision["medidas"]
        if action != previous:
            announce("{}: distancia={:.1f} mm; giro={:.1f} grados".format(
                action, metrics["distancia_mm"], metrics["giro_grados"]))
            previous = action
        if step == 3:
            # La ceguera debe impedir recomendar movimiento aunque quede una pose.
            virtual_time[0] += .6
            pause = navigator.decide(state, target)
            if pause["accion"] != "ESPERAR":
                raise AssertionError("No espero al vencer los datos")
            announce("ESPERAR: captura vieja; se reanuda con una observacion nueva.")
            paused = True
            continue
        if action == "ALCANZADO":
            return {"resultado": "OK", "pasos": step + 1,
                    "error_final_mm": round(metrics["distancia_mm"], 3),
                    "espera_por_datos_viejos": paused,
                    "modelo": "movimiento_ideal_sin_colisiones"}
        if action == "GIRAR":
            # Actuador ideal limitado a diez grados por paso, sin leer el destino.
            turn = max(-10, min(10, metrics["giro_grados"]))
            own["theta"] = (own["theta"] + turn) % 360
        elif action == "AVANZAR":
            # Medio cuadro por paso en el rumbo ACTUAL, no teletransporte al punto.
            angle = math.radians(own["theta"])
            own["col"] += .5 * math.cos(angle)
            own["row"] -= .5 * math.sin(angle)
        else:
            raise AssertionError("Espera inesperada: " + decision["motivo"])
        virtual_time[0] += .1
    raise AssertionError("El modelo no alcanzo el punto en 300 pasos")


if __name__ == "__main__":
    print(json.dumps(run_demo(), ensure_ascii=False, indent=2))
