"""Intercambio simulado de acuerdos; no hay red ni transporte físico de cubos."""
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "codigos"))
from asignacion import compare_assignments
from coordinacion import TaskCoordinator, TaskReplica
from telemetria import TelemetryState
from demo_rutas import scenario


class LocalMission:
    def __init__(self):
        self.now = 0.0
        self.message = scenario()
        self.vision = TelemetryState(monotonic=lambda: self.now, wall=lambda: 1000 + self.now)
        self.vision.connect()
        self.observe()
        proposal = compare_assignments(self.vision)
        self.orders = {p["robot_id"]: p["cubos"] for p in proposal["equilibrado"]["robots"]}
        self.leader = TaskCoordinator("demo-1", self.orders, clock=lambda: self.now)
        self.replicas = {i: TaskReplica(i, self.leader.leader_id, "demo-1", clock=lambda: self.now) for i in self.orders}
        self.heartbeat()

    def observe(self):
        self.message["seq"] += 1
        self.message["ts_ms"] = int((1000 + self.now) * 1000)
        if not self.vision.accept_line(json.dumps(self.message)):
            raise AssertionError(self.vision.fault)

    def exchange(self, identity, op="PING", color=None):
        replica = self.replicas[identity]
        request = replica.request(op, color)
        # Copias JSON equivalentes a serializar y deserializar por la radio.
        response = self.leader.handle(json.loads(json.dumps(request)), identity, self.vision)
        if response is None or not replica.receive(json.loads(json.dumps(response)), self.leader.leader_id):
            raise AssertionError("Intercambio no confirmado")
        return response

    def heartbeat(self):
        for identity in self.orders:
            self.exchange(identity)
        self.exchange(self.leader.leader_id)

    def change(self, identity, op, color):
        self.exchange(identity)  # obtener la última revisión antes de cambiar
        response = self.exchange(identity, op, color)
        if not response["ok"]:
            raise AssertionError(response["motivo"])
        return response

    def place_cube_for_test(self, color):
        depot = self.vision.depot(color)
        cube = next(c for c in self.message["cubes"] if c["color"] == color)
        cube.update(col=depot["col"], row=depot["row"], age_ms=0)
        self.observe()


def run_demo(announce=print):
    mission = LocalMission()
    announce("Plan inicial: " + str(mission.orders))
    active = {}
    for identity, order in mission.orders.items():
        color = order[0]
        mission.change(identity, "RESERVAR", color)
        mission.change(identity, "INICIAR", color)
        active[identity] = color
        announce("Robot {}: {} -> EN_TRASLADO (estado simulado)".format(identity, color))
    mission.heartbeat()
    if not all(mission.replicas[i].can_work(c, mission.vision) for i, c in active.items()):
        raise AssertionError("No se habilitaron las tareas confirmadas")
    # Dejar pasar el plazo sin mensajes del otro rover; las poses sí se renuevan.
    mission.now += .6
    mission.observe()
    mission.exchange(mission.leader.leader_id)
    if any(mission.replicas[i].can_work(c, mission.vision) for i, c in active.items()):
        raise AssertionError("Continuo tras perder comunicacion")
    if any(mission.leader.tasks[c]["owner"] != i for i, c in active.items()):
        raise AssertionError("Se transfirio una tarea por timeout")
    announce("Sin comunicacion: ambos esperan; las reservas conservan sus dueños.")
    mission.heartbeat()
    if not all(mission.replicas[i].can_work(c, mission.vision) for i, c in active.items()):
        raise AssertionError("No recupero permisos tras sincronizar")
    # Evidencia artificial: inyectar posiciones en destino, no simular empuje.
    for identity, order in mission.orders.items():
        for index, color in enumerate(order):
            if index:
                mission.change(identity, "RESERVAR", color)
                mission.change(identity, "INICIAR", color)
            mission.place_cube_for_test(color)
            mission.change(identity, "ENTREGAR", color)
            announce("{} -> ENTREGADO, tras inyectar su posicion en destino.".format(color))
    mission.heartbeat()
    if not all(t["estado"] == "ENTREGADO" for t in mission.leader.tasks.values()):
        raise AssertionError("Quedaron tareas incompletas")
    return {"resultado": "OK", "tareas": mission.leader.tasks,
            "revision": mission.leader.revision,
            "alcance": "acuerdos_simulados_con_evidencia_de_entrega_inyectada"}


if __name__ == "__main__":
    print(json.dumps(run_demo(), ensure_ascii=False, indent=2))
