"""Consumo de JSON crudo v2, sin imports del sistema oficial ni de hardware.

El permiso sólo describe disponibilidad de datos; no garantiza ruta libre.
El adaptador de red para computadora vive en robots/pc/cliente_vision.py.
"""
import json
import math
import time


def _fields(value, names):
    if not isinstance(value, dict) or set(value) != set(names.split()):
        raise ValueError("Campos faltantes, desconocidos o estructura invalida")


def _number(value, minimum=None):
    if type(value) not in (int, float) or not math.isfinite(value):
        raise ValueError("Numero no finito o tipo invalido")
    if minimum is not None and value < minimum:
        raise ValueError("Numero fuera de rango")


def _integer(value, minimum=0):
    if type(value) is not int or value < minimum:
        raise ValueError("Entero fuera de rango")


def _position(value):
    _number(value["col"])
    _number(value["row"])


def validate(message):
    """Valida el formato publicado; no importa schema.py en el consumidor."""
    _fields(message, "v seq ts_ms phase clock grid rovers cubes obstacles start depots depot_size cube_side")
    _integer(message["v"])
    if message["v"] != 2:
        raise ValueError("Version de telemetria desconocida")
    _integer(message["seq"])
    _integer(message["ts_ms"])
    if message["phase"] not in ("IDLE", "READY", "RUNNING", "FINISHED"):
        raise ValueError("Fase desconocida")
    _fields(message["clock"], "elapsed_ms remaining_ms total_ms")
    for value in message["clock"].values():
        _integer(value)
    clock = message["clock"]
    if clock["elapsed_ms"] + clock["remaining_ms"] != clock["total_ms"]:
        raise ValueError("Cronometro inconsistente")
    _fields(message["grid"], "cols rows cell_mm")
    _integer(message["grid"]["cols"], 1)
    _integer(message["grid"]["rows"], 1)
    _fields(message["depot_size"], "length depth")
    for value in (message["grid"]["cell_mm"], message["cube_side"],
                  message["depot_size"]["length"], message["depot_size"]["depth"]):
        _number(value, 0)
        if value == 0:
            raise ValueError("Dimension debe ser positiva")
    _fields(message["start"], "col row")
    _position(message["start"])
    seen = {}
    for name, fields, key in (
        ("rovers", "id col row theta age_ms", "id"),
        ("cubes", "color col row age_ms", "color"),
        ("depots", "color col row", "color"),
        ("obstacles", "col row age_ms", None),
    ):
        values = message[name]
        if not isinstance(values, list):
            raise ValueError("Se esperaba una lista")
        identities = []
        for value in values:
            _fields(value, fields)
            _position(value)
            if name != "depots":
                _integer(value["age_ms"])
            if name == "rovers":
                _integer(value["id"])
                _number(value["theta"], 0)
                if value["theta"] > 360:
                    raise ValueError("Angulo fuera de rango")
            if key == "color" and value[key] not in ("red", "green", "blue"):
                raise ValueError("Color desconocido")
            if key:
                if value[key] in identities:
                    raise ValueError("Identidad duplicada")
                identities.append(value[key])
        seen[name] = identities
    if any(color not in seen["depots"] for color in seen["cubes"]):
        raise ValueError("Cubo sin destino")


class TelemetryState:
    def __init__(self, robot_id=10, peer_id=11, max_age_ms=500,
                 future_tolerance_ms=100, monotonic=time.monotonic, wall=time.time):
        _integer(robot_id)
        _integer(peer_id)
        if robot_id == peer_id:
            raise ValueError("Los IDs de los dos robots deben ser diferentes")
        _number(max_age_ms, 0)
        _number(future_tolerance_ms, 0)
        if max_age_ms == 0:
            raise ValueError("La edad maxima debe ser positiva")
        self.robot_id, self.peer_id = robot_id, peer_id
        self.max_age_ms, self.future_tolerance_ms = max_age_ms, future_tolerance_ms
        self.monotonic, self.wall = monotonic, wall
        self.message = None
        self.received_at = None
        self.seq = None
        self.connected = False
        self.fault = "sin_conexion"
        self.accepted = self.rejected = 0

    def connect(self):
        self.connected = True
        self.seq = None
        self.received_at = None
        self.fault = "esperando_datos"

    def disconnect(self, reason="sin_conexion"):
        self.connected = False
        self.fault = reason

    def reject(self, reason):
        self.rejected += 1
        self.fault = reason

    def accept_line(self, line):
        if not self.connected:
            return False
        try:
            message = json.loads(line)
            validate(message)
            lag = self.wall() * 1000 - message["ts_ms"]
            if lag < -self.future_tolerance_ms:
                raise ValueError("reloj_desincronizado")
            if lag >= self.max_age_ms:
                raise ValueError("captura_vieja")
            if self.seq is not None and message["seq"] <= self.seq:
                raise ValueError("secuencia_repetida_o_atrasada")
        except (ValueError, TypeError, OverflowError, RecursionError) as error:
            self.reject(str(error))
            return False
        self.message = message
        self.seq = message["seq"]
        self.received_at = self.monotonic()
        self.lag_at_receive = max(0, lag)
        self.accepted += 1
        self.fault = None
        return True

    def capture_age_ms(self):
        if self.received_at is None:
            return float("inf")
        # El reloj monótono impide rejuvenecer datos si se atrasa el reloj de PC.
        elapsed = max(0, (self.monotonic() - self.received_at) * 1000)
        return max(self.lag_at_receive + elapsed, self.wall() * 1000 - self.message["ts_ms"])

    def rover(self, identity):
        return self._find("rovers", "id", identity)

    def cube(self, color):
        return self._find("cubes", "color", color)

    def depot(self, color):
        return self._find("depots", "color", color)

    def _find(self, group, key, identity):
        if self.message:
            for item in self.message[group]:
                if item[key] == identity:
                    return item
        return None

    def reason(self, target_color=None):
        """None = datos habilitados; cualquier texto exige mantener parada."""
        if not self.connected:
            return self.fault or "sin_conexion"
        if self.fault:
            return self.fault
        age = self.capture_age_ms()
        if age >= self.max_age_ms:
            return "captura_vieja"
        if self.message["phase"] != "RUNNING":
            return "fase_" + self.message["phase"]
        required = [("robot_propio", self.rover(self.robot_id)),
                    ("companero", self.rover(self.peer_id))]
        if target_color is not None:
            required.append(("cubo_objetivo", self.cube(target_color)))
        for name, item in required:
            if item is None:
                return name + "_ausente"
            if item["age_ms"] + age >= self.max_age_ms:
                return name + "_viejo"
            if not (0 <= item["col"] <= self.message["grid"]["cols"] and
                    0 <= item["row"] <= self.message["grid"]["rows"]):
                return name + "_fuera_de_cancha"
        return None


class NDJSONReceiver:
    def __init__(self, state, max_line_bytes=8192):
        _integer(max_line_bytes, 1)
        self.state, self.max_line_bytes = state, max_line_bytes
        self.buffer = b""

    def feed(self, chunk):
        # El adaptador limita cada lectura. Nunca acumular líneas sin límite.
        self.buffer += chunk
        while b"\n" in self.buffer:
            line, self.buffer = self.buffer.split(b"\n", 1)
            if len(line) > self.max_line_bytes:
                self.buffer = b""
                self.state.reject("linea_demasiado_larga")
                raise ValueError("linea_demasiado_larga")
            try:
                self.state.accept_line(line.decode("utf-8"))
            except UnicodeError:
                self.state.reject("codificacion_invalida")
        if len(self.buffer) > self.max_line_bytes:
            self.buffer = b""
            self.state.reject("linea_incompleta_demasiado_larga")
            raise ValueError("linea_incompleta_demasiado_larga")
