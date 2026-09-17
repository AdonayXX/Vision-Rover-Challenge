"""Acuerdos de tareas con coordinador fijo en el rover de menor ID.

Transporte independiente: los paquetes son diccionarios, no sockets. La demo
simula su entrega. No hay elección de líder, cambio automático de dueño ni
recuperación de reinicio. Un reinicio exige detener y establecer otra sesión.
"""
import math
import time

COLORS = ("blue", "green", "red")
STATES = ("LIBRE", "RESERVADO", "EN_TRASLADO", "ENTREGADO")
OPS = ("PING", "RESERVAR", "INICIAR", "LIBERAR", "ENTREGAR")


def delivery_seen(vision, color):
    """Cubo entero dentro según media diagonal del contrato; observación local.

    No sustituye la permanencia ni el veredicto del árbitro oficial.
    FINISHED permite registrar una entrega final, nunca iniciar movimiento.
    """
    if not vision.connected or vision.fault or vision.message is None:
        return False
    if vision.message["phase"] not in ("RUNNING", "FINISHED"):
        return False
    cube, depot = vision.cube(color), vision.depot(color)
    if cube is None or depot is None or cube["age_ms"] + vision.capture_age_ms() >= vision.max_age_ms:
        return False
    grid, size = vision.message["grid"], vision.message["depot_size"]
    distances = (depot["row"], grid["rows"] - depot["row"], depot["col"], grid["cols"] - depot["col"])
    side = min(range(4), key=lambda i: distances[i])
    half_col, half_row = (size["length"] / 2, size["depth"] / 2) if side < 2 else (size["depth"] / 2, size["length"] / 2)
    margin = vision.message["cube_side"] * math.sqrt(2) / 2
    return (abs(cube["col"] - depot["col"]) <= half_col - margin and
            abs(cube["row"] - depot["row"]) <= half_row - margin)


class TaskCoordinator:
    def __init__(self, round_id, orders, timeout=0.5, clock=time.monotonic):
        if not isinstance(round_id, str) or not round_id or len(round_id) > 64:
            raise ValueError("Sesion invalida")
        if len(orders) != 2 or any(type(i) is not int or i < 0 for i in orders):
            raise ValueError("Se requieren dos IDs distintos")
        if sorted(c for tasks in orders.values() for c in tasks) != list(COLORS):
            raise ValueError("Cada cubo debe asignarse exactamente una vez")
        if not all(orders.values()):
            raise ValueError("Ambos rovers deben recibir tareas")
        if not math.isfinite(timeout) or timeout <= 0:
            raise ValueError("Timeout invalido")
        self.round_id, self.clock, self.timeout = round_id, clock, timeout
        self.ids = tuple(sorted(orders))
        self.leader_id = self.ids[0]
        self.orders = {i: tuple(orders[i]) for i in self.ids}
        self.tasks = {c: {"estado": "LIBRE", "owner": None} for c in COLORS}
        self.revision = 0
        self.last_seen, self.last_request = {}, {}

    def online(self):
        return all(i in self.last_seen and self.clock() - self.last_seen[i] < self.timeout for i in self.ids)

    def _response(self, request, ok, reason):
        return {"v": 1, "ronda": self.round_id, "solicitud": request["solicitud"],
                "ok": ok, "motivo": reason, "revision": self.revision,
                "equipo_online": self.online(),
                "tareas": {c: dict(t) for c, t in self.tasks.items()}}

    def handle(self, request, sender_id, vision):
        """sender_id debe proceder del transporte verificado, no del texto remoto."""
        fields = {"v", "ronda", "emisor", "solicitud", "revision", "tipo", "color"}
        if not isinstance(request, dict) or set(request) != fields:
            return None
        if (type(request["v"]) is not int or request["v"] != 1 or
                request["ronda"] != self.round_id or sender_id not in self.ids or
                type(request["emisor"]) is not int or request["emisor"] != sender_id or
                type(request["solicitud"]) is not int or request["solicitud"] <= 0 or
                type(request["revision"]) is not int or request["revision"] < 0 or
                request["tipo"] not in OPS or
                (request["tipo"] != "PING" and request["color"] not in COLORS) or
                (request["tipo"] == "PING" and request["color"] is not None)):
            return None
        prior = self.last_request.get(sender_id)
        if prior and request["solicitud"] <= prior[0]["solicitud"]:
            # Una repetición no vuelve a mutar ni renueva la presencia.
            if request == prior[0]:
                return prior[1]
            return self._response(request, False, "solicitud_antigua_o_reutilizada")
        self.last_seen[sender_id] = self.clock()
        op, color = request["tipo"], request["color"]
        reason = None
        if op != "PING":
            if request["revision"] != self.revision:
                reason = "revision_desactualizada"
            elif not self.online():
                reason = "esperando_companero"
            elif op != "ENTREGAR" and vision.reason(color) is not None:
                reason = "telemetria_no_habilitada"
            else:
                reason = self._apply(sender_id, op, color, vision)
        response = self._response(request, reason is None, reason or "confirmado")
        self.last_request[sender_id] = (dict(request), response)
        return response

    def _apply(self, identity, op, color, vision):
        task = self.tasks[color]
        if op == "RESERVAR":
            if color not in self.orders[identity]:
                return "cubo_asignado_a_otro_rover"
            if task["estado"] != "LIBRE":
                return "cubo_no_libre"
            if any(t["owner"] == identity and t["estado"] in ("RESERVADO", "EN_TRASLADO") for t in self.tasks.values()):
                return "rover_ocupado"
            next_color = next((c for c in self.orders[identity] if self.tasks[c]["estado"] != "ENTREGADO"), None)
            if color != next_color:
                return "respetar_orden_de_tareas"
            task.update(estado="RESERVADO", owner=identity)
        else:
            if task["owner"] != identity:
                return "no_es_dueno"
            if op == "INICIAR" and task["estado"] == "RESERVADO":
                task["estado"] = "EN_TRASLADO"
            elif op == "LIBERAR" and task["estado"] == "RESERVADO":
                task.update(estado="LIBRE", owner=None)
            elif op == "ENTREGAR" and task["estado"] == "EN_TRASLADO":
                if not delivery_seen(vision, color):
                    return "entrega_no_observada"
                task["estado"] = "ENTREGADO"
            else:
                return "transicion_no_permitida"
        self.revision += 1
        return None


class TaskReplica:
    def __init__(self, robot_id, leader_id, round_id, timeout=0.5, clock=time.monotonic):
        if not math.isfinite(timeout) or timeout <= 0:
            raise ValueError("Timeout invalido")
        self.robot_id, self.leader_id, self.round_id = robot_id, leader_id, round_id
        self.timeout, self.clock = timeout, clock
        self.counter = 0
        self.revision = 0
        self.tasks = None
        self.pending = None
        self.fresh_since = None
        self.team_online = False

    def request(self, op="PING", color=None):
        if op not in OPS or (op == "PING" and color is not None) or (op != "PING" and color not in COLORS):
            raise ValueError("Operacion invalida")
        if self.pending and self.clock() - self.pending[1] < self.timeout:
            raise ValueError("Hay una solicitud pendiente; reenviar el mismo paquete")
        self.counter += 1
        packet = {"v": 1, "ronda": self.round_id, "emisor": self.robot_id,
                  "solicitud": self.counter, "revision": self.revision, "tipo": op, "color": color}
        self.pending = (dict(packet), self.clock())
        return packet

    def receive(self, response, sender_id):
        if self.pending is None or sender_id != self.leader_id or not isinstance(response, dict):
            return False
        packet, sent_at = self.pending
        if (self.clock() - sent_at >= self.timeout or response.get("ronda") != self.round_id or
                response.get("solicitud") != packet["solicitud"]):
            return False
        if (type(response.get("v")) is not int or response["v"] != 1 or
                type(response.get("revision")) is not int or response["revision"] < self.revision or
                type(response.get("ok")) is not bool or type(response.get("equipo_online")) is not bool):
            return False
        tasks = response.get("tareas")
        if not isinstance(tasks, dict) or set(tasks) != set(COLORS):
            return False
        for task in tasks.values():
            if not isinstance(task, dict) or set(task) != {"estado", "owner"} or task["estado"] not in STATES:
                return False
            if (task["estado"] == "LIBRE" and task["owner"] is not None) or (task["estado"] != "LIBRE" and type(task["owner"]) is not int):
                return False
        self.revision = response["revision"]
        self.tasks = {c: dict(t) for c, t in tasks.items()}
        # El plazo empieza al ENVIAR la petición; una respuesta demorada no
        # concede otros 500 ms como si fuera una observación recién nacida.
        self.fresh_since = sent_at
        self.team_online = response["equipo_online"]
        self.pending = None
        return True

    def can_work(self, color, vision):
        """Permiso de TAREA, no validación de ruta ni señal directa a motores."""
        if (self.tasks is None or self.fresh_since is None or not self.team_online or
                self.clock() - self.fresh_since >= self.timeout or vision.reason(color) is not None):
            return False
        # Una operación de cambio pendiente exige esperar su confirmación.
        if self.pending and self.pending[0]["tipo"] != "PING":
            return False
        task = self.tasks.get(color)
        return bool(task and task["owner"] == self.robot_id and task["estado"] == "EN_TRASLADO")
