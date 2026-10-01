"""Prueba física de desarrollo: empujar un cubo hacia un destino indicado.

Usa la telemetría de visión como realimentación y el receptor TCP de comandos
del rover. Es una herramienta de puesta a punto en PC; no es el programa de
misión autónoma que se ejecutará en los rovers durante una ronda.
"""

import argparse
import copy
import ipaddress
import json
import math
from pathlib import Path
import socket
import sys
import time

ROOT_ROBOTS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT_ROBOTS / "codigos"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from command_protocol import cmd_motor, cmd_stop
from cliente_vision import VisionClient
from pasos_visuales import VisualSteps
from rutas import RoutePlanner, point_segment_distance
from telemetria import TelemetryState
from transporte import (
    decidir_movimiento_hacia,
    destino_valido_para_cubo,
    distancia_mm,
    objetivo_deposito,
    punto_detras_del_cubo,
)


COLORS = ("red", "green", "blue")


class DevelopmentTelemetryState(TelemetryState):
    """Permiso de datos para banco con un solo rover y sin fase RUNNING."""

    def reason(self, target_color=None):
        if not self.connected:
            return self.fault or "sin_conexion"
        if self.fault:
            return self.fault
        if self.message is None:
            return "esperando_datos"
        age = self.capture_age_ms()
        if age >= self.max_age_ms:
            return "captura_vieja"
        required = [("robot_propio", self.rover(self.robot_id))]
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


class RobotClient:
    def __init__(self, host, port=5000, timeout=1.5, connect_timeout=6.0, wait_seconds=0):
        self.host, self.port, self.timeout = host, port, timeout
        self.connect_timeout = connect_timeout
        # Tras una caida el rover tarda en reiniciar y volver al Wi-Fi.
        self.wait_seconds = wait_seconds
        self.sock = None
        self.last = None

    def connect(self):
        self.close(send_stop=False)
        deadline = time.monotonic() + self.wait_seconds
        while True:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            sock.settimeout(self.connect_timeout)
            try:
                sock.connect((self.host, self.port))
                break
            except OSError as error:
                sock.close()
                last_error = error
            if time.monotonic() >= deadline:
                raise ConnectionError(
                    "No se pudo conectar TCP a {}:{}: {}. Conecta PC y rover al mismo "
                    "Wi-Fi y usa la IP que anuncia el rover al conectar."
                    .format(self.host, self.port, last_error)
                ) from last_error
            print("Rover sin respuesta; reintentando (puede estar reiniciando)...", flush=True)
            time.sleep(1)
        sock.settimeout(self.timeout)
        self.sock = sock
        self.buffer = b""
        try:
            self.send("STOP", force=True)
        except OSError as error:
            self.close(send_stop=False)
            raise ConnectionError(
                "TCP conectado a {}:{}, pero el rover no confirmo STOP. "
                "Cierra prueba_robot.py u otro cliente y revisa el receptor de comandos. ({})"
                .format(self.host, self.port, error)
            ) from error

    def _exchange(self, command):
        if self.sock is None:
            raise ConnectionError("Robot no conectado")
        self.sock.sendall((command + "\n").encode("ascii"))
        while b"\n" not in self.buffer:
            chunk = self.sock.recv(64)
            if not chunk:
                raise ConnectionError("El robot cerro la conexion")
            self.buffer += chunk
            if len(self.buffer) > 8192:
                raise ConnectionError("Respuesta del robot demasiado larga")
        line, self.buffer = self.buffer.split(b"\n", 1)
        response = line.decode("ascii", "replace").strip()
        return response

    def send(self, command, force=False):
        # Un ACK perdido nunca conserva un STOP anterior como confirmado.
        self.last = None
        response = self._exchange(command)
        if response != "OK":
            raise ConnectionError("Respuesta del robot: {!r}".format(response))
        self.last = command

    def sensors(self):
        response = self._exchange("SENSORS")
        try:
            status = json.loads(response)
        except (ValueError, TypeError) as exc:
            raise ConnectionError("El firmware no devuelve sensores. Sube el paquete completo actualizado.") from exc
        if not isinstance(status, dict) or status.get("v") != 1 or status.get("enabled") is not True:
            raise ConnectionError("Sensores locales no disponibles/activados en el rover")
        return status

    def stop(self):
        if self.sock is not None:
            if self.last == cmd_stop():
                return True
            try:
                self.send(cmd_stop(), force=True)
                return True
            except OSError:
                pass
        return False

    def close(self, send_stop=True):
        confirmed = False
        if self.sock is not None:
            if send_stop:
                confirmed = self.stop()
            try:
                self.sock.close()
            except OSError:
                pass
        self.sock = None
        return confirmed


_RESET_HINTS = {
    "BROWNOUT": "cayo el voltaje (bateria baja o pico de los motores)",
    "WATCHDOG": "el programa se colgo y el watchdog reinicio la placa",
}
_FAILURE_LABELS = {
    "modo_seguro": "la placa entro en modo seguro",
    "error_fatal": "el programa del rover fallo",
    "sesion": "ultima sesion cortada por error",
}


def _print_reset_reason(status):
    """Sin cable USB, esta es la unica pista de por que se cayo el rover."""
    reason = status.get("reset_reason")
    if reason is None:
        print("Rover sin diagnostico de reinicio: sube el firmware actualizado.")
        return
    print("Rover encendido hace {} s; ultimo reinicio: {}".format(status.get("uptime_s"), reason))
    if reason in _RESET_HINTS:
        print("AVISO: el rover se reinicio solo: " + _RESET_HINTS[reason])
    for key, text in sorted((status.get("fallos") or {}).items()):
        print("Registro de fallos del rover: {} -> {}".format(_FAILURE_LABELS.get(key, key), text))


def _finite(value, name):
    if value is None or not math.isfinite(value):
        raise ValueError(name + " debe ser finito")
    return float(value)


def _prompt_color(prompt, default=None):
    suffix = " [{}]".format(default) if default else ""
    while True:
        value = input(prompt + suffix + ": ").strip().lower() or default
        if value in COLORS:
            return value
        print("Opciones: red, green, blue")


def _resolve_selection(args, message):
    cube_color = args.cube or _prompt_color("Cubo")
    if args.depot is not None:
        target = objetivo_deposito(message, args.depot)
        label = "deposito_" + args.depot
    elif args.dest_col is not None:
        target = {"col": args.dest_col, "row": args.dest_row}
        label = "coordenada"
    else:
        text = input(
            "Destino [mismo/red/green/blue/coordenadas] [mismo]: "
        ).strip().lower() or "mismo"
        if text == "mismo":
            text = cube_color
        if text in COLORS:
            target = objetivo_deposito(message, text)
            label = "deposito_" + text
        elif text == "coordenadas":
            target = {
                "col": float(input("col: ").strip()),
                "row": float(input("row: ").strip()),
            }
            label = "coordenada"
        else:
            raise ValueError("Destino inválido")
    return cube_color, target, label


def _motor_pair(speed, correction, turn_sign):
    """Adapta el giro de visión al montaje; no invierte avance ni retroceso.

    En el rover 10, MOTOR negativo/positivo hizo DISMINUIR theta. Por eso
    su signo medido es -1. Las coordenadas y los ángulos de visión no cambian.
    """
    if turn_sign not in (-1, 1):
        raise ValueError("turn_sign debe ser -1 o 1")
    correction *= turn_sign
    left = max(-1.0, min(1.0, speed - correction))
    right = max(-1.0, min(1.0, speed + correction))
    return cmd_motor(left, right)


def _motor_command(action, angle_error, speed, turn_speed, steering_gain,
                   turn_memory=None, turn_sign=-1):
    if action == "ALCANZADO":
        return cmd_stop()
    if action == "GIRAR":
        sign = turn_memory.direction(angle_error) if turn_memory else (1.0 if angle_error > 0 else -1.0)
        return _motor_pair(0, sign * turn_speed, turn_sign)
    correction = max(-0.18, min(0.18, steering_gain * angle_error))
    return _motor_pair(speed, correction, turn_sign)


def _wait_for_vision(client, state, color=None, timeout=15):
    limit = time.monotonic() + timeout
    last_reason = None
    while time.monotonic() < limit:
        client.poll()
        reason = state.reason(color)
        if reason is None:
            return
        if reason != last_reason:
            print("Esperando vision:", _vision_hint(reason, state), flush=True)
            last_reason = reason
        time.sleep(0.02)
    raise RuntimeError("Visión no lista: " + _vision_hint(state.reason(color), state))


def _vision_hint(reason, state):
    if reason == "captura_vieja":
        return ("captura_vieja: imagen con mas de {:g} ms. Reinicia vision.sistema "
                "para cargar las mejoras; revisa que las cuatro esquinas sean visibles.").format(state.max_age_ms)
    if reason == "robot_propio_ausente":
        return "robot_propio_ausente: la vision no publica el rover {}. Revisa su marcador.".format(state.robot_id)
    return str(reason)


def _mission_reason(state, color, all_cubes=False):
    for required in COLORS if all_cubes else (color,):
        reason = state.reason(required)
        if reason is not None:
            return reason
    return None


def _goal_reached(message, cube, target, label, tolerance_mm):
    if distancia_mm(cube, target, message["grid"]["cell_mm"]) > tolerance_mm:
        return False
    if not label.startswith("deposito_"):
        return True
    # Contrato v2: cube_side y depot_size vienen en CELDAS.
    grid, size = message["grid"], message["depot_size"]
    horizontal = min(target["row"], grid["rows"] - target["row"]) < min(
        target["col"], grid["cols"] - target["col"])
    width, height = (size["length"], size["depth"]) if horizontal else (size["depth"], size["length"])
    margin = message["cube_side"] * math.sqrt(2) / 2
    return (abs(cube["col"] - target["col"]) + margin <= width / 2 and
            abs(cube["row"] - target["row"]) + margin <= height / 2)


def _without_target(state, color):
    other = copy.copy(state)
    other.message = dict(state.message, cubes=[c for c in state.message["cubes"] if c["color"] != color])
    return other


def _transient_vision_reason(reason):
    """Una observacion vencida se reintenta; no es un obstaculo fisico."""
    return reason in ("captura_vieja", "robot_propio_viejo", "cubo_objetivo_viejo",
                      "companero_viejo", "observacion_cambio_durante_calculo") or str(reason).startswith("entidad_vieja:")


def _fresh_scene(planner, state):
    try:
        return planner.scene(state)
    except ValueError as error:
        if _transient_vision_reason(str(error)):
            return None
        raise


def _position_conflicts(state, point, planner):
    """Explica los mismos margenes geometricos que comprueba RoutePlanner."""
    msg = state.message
    grid = msg["grid"]
    scale = grid["cell_mm"]
    margin = planner.radius + planner.clearance
    conflicts = []
    for name, distance in (("col=0", point["col"] * scale),
                           ("col=max", (grid["cols"] - point["col"]) * scale),
                           ("row=0", point["row"] * scale),
                           ("row=max", (grid["rows"] - point["row"]) * scale)):
        if distance < margin:
            conflicts.append("borde {}: centro a {:.1f} mm, minimo {:.1f} mm".format(name, distance, margin))
    for group in ("rovers", "cubes", "obstacles"):
        for item in msg[group]:
            if group == "rovers":
                if item["id"] == state.robot_id:
                    continue
                label, radius = "rover {}".format(item["id"]), planner.peer_radius
            elif group == "cubes":
                label = "cubo " + item["color"]
                radius = msg["cube_side"] * scale * math.sqrt(2) / 2
            else:
                label, radius = "obstaculo", planner.obstacle_side * math.sqrt(2) / 2
            distance = distancia_mm(point, item, scale)
            if distance <= radius + margin + 1e-8:
                conflicts.append("{}: centros a {:.1f} mm, minimo {:.1f} mm".format(label, distance, radius + margin))
    return conflicts


def _route_error(route, state, target, planner):
    reason = route["motivo"]
    point = state.rover(state.robot_id) if reason == "origen_sin_espacio" else target
    if reason in ("origen_sin_espacio", "destino_sin_espacio"):
        details = _position_conflicts(state, point, planner)
        if details:
            return reason + ": " + "; ".join(details)
    return str(reason)


def _segment_conflicts(state, scene, start, end):
    """Explica exactamente los círculos y límites usados por free_segment."""
    scale, margin = scene["cell_mm"], scene["margin"]
    details = []
    for name, (x, y) in (("inicio", start), ("final", end)):
        if not (margin <= x <= scene["cols"] - margin and margin <= y <= scene["rows"] - margin):
            details.append("{} junto al borde: centro ({:.2f}, {:.2f}), margen {:.1f} mm".format(
                name, x, y, margin * scale))
    labels = []
    for group in ("rovers", "cubes", "obstacles"):
        for item in state.message[group]:
            if group == "rovers" and item["id"] == state.robot_id:
                continue
            labels.append("rover {}".format(item["id"]) if group == "rovers" else
                          "cubo " + item["color"] if group == "cubes" else "obstaculo")
    for label, (x, y, radius) in zip(labels, scene["circles"]):
        distance = point_segment_distance((x, y), start, end)
        if distance <= radius + 1e-9:
            details.append("{}: centro a {:.1f} mm del trayecto, minimo {:.1f} mm".format(
                label, distance * scale, radius * scale))
    return "; ".join(details)


def _push_clear(state, color, target, planner, args, details=None, robot_start=None):
    """Comprueba el corredor recto del cubo y del cuerpo del rover."""
    cube, rover = state.cube(color), state.rover(state.robot_id)
    scene_state = _without_target(state, color)
    scale = state.message["grid"]["cell_mm"]
    cube_radius = state.message["cube_side"] * scale * math.sqrt(2) / 2
    cube_planner = RoutePlanner(cube_radius, args.robot_radius_mm, args.clearance_mm, required_colors=())
    cube_scene = _fresh_scene(cube_planner, scene_state)
    if cube_scene is None:
        return None
    start, end = (cube["col"], cube["row"]), (target["col"], target["row"])
    if not cube_planner.free_segment(cube_scene, start, end):
        if details is not None:
            details.append("trayecto del cubo: " + _segment_conflicts(scene_state, cube_scene, start, end))
        return False
    length = math.hypot(end[0] - start[0], end[1] - start[1])
    if length < 1e-9:
        return True
    contact = (args.robot_radius_mm + state.message["cube_side"] * scale / 2) / scale
    robot_end = (end[0] - contact * (end[0] - start[0]) / length,
                 end[1] - contact * (end[1] - start[1]) / length)
    robot_scene = _fresh_scene(planner, scene_state)
    if robot_scene is None:
        return None
    origin = rover if robot_start is None else robot_start
    robot_begin = (origin["col"], origin["row"])
    clear = planner.free_segment(robot_scene, robot_begin, robot_end)
    if not clear and details is not None:
        details.append("trayecto del cuerpo del rover: " + _segment_conflicts(
            scene_state, robot_scene, robot_begin, robot_end))
    return clear


def _resuming_push(state, color, target, args):
    """True si el rover ya esta detras del cubo, en la linea cubo->destino.

    Pasa al relanzar tras un corte (BROWNOUT) a mitad del empuje: el rover
    esta pegado al cubo a proposito y no debe exigirse empezar lejos de el.
    """
    rover, cube = state.rover(state.robot_id), state.cube(color)
    if rover is None or cube is None:
        return False
    scale = state.message["grid"]["cell_mm"]
    # Solo mas cerca que el punto de aproximacion: desde ahi el flujo normal
    # (APROXIMAR) ya funciona.
    if distancia_mm(rover, cube, scale) >= args.approach_center_distance_mm - args.approach_tolerance_mm:
        return False
    to_cube = (cube["col"] - rover["col"], cube["row"] - rover["row"])
    to_goal = (target["col"] - cube["col"], target["row"] - cube["row"])
    norms = math.hypot(*to_cube) * math.hypot(*to_goal)
    if norms == 0:
        return False
    cos = (to_cube[0] * to_goal[0] + to_cube[1] * to_goal[1]) / norms
    return cos >= math.cos(math.radians(args.abort_push_angle_deg))


def _verify_approach_and_push(vision, state, color, target, planner, args, resume=False):
    """Reintenta observaciones vencidas; nunca autoriza un bloqueo geométrico."""
    deadline = time.monotonic() + args.vision_timeout
    last_reason = "captura_vieja"
    while time.monotonic() < deadline:
        vision.poll()
        reason = _mission_reason(state, color, args.todos)
        if reason is None and resume:
            details = []
            clear = _push_clear(state, color, target, planner, args, details=details)
            if clear is False:
                raise RuntimeError("Corredor de empuje bloqueado: " + "; ".join(details))
            if clear is True:
                print("Corredor de empuje: libre para cubo y cuerpo del rover.")
                return
            reason = "captura_vieja"
        elif reason is None:
            behind = punto_detras_del_cubo(state.cube(color), target,
                                          args.approach_center_distance_mm,
                                          state.message["grid"]["cell_mm"])
            route = planner.plan(state, behind)
            if route["estado"] != "RUTA":
                if not _transient_vision_reason(route["motivo"]):
                    raise RuntimeError("Aproximacion bloqueada: " + _route_error(route, state, behind, planner))
                reason = route["motivo"]
            else:
                details = []
                # El empuje comienza DESPUÉS de llegar detrás del cubo.
                # La aproximación desde la pose actual ya fue validada arriba.
                clear = _push_clear(state, color, target, planner, args,
                                    details=details, robot_start=behind)
                if clear is False:
                    raise RuntimeError("Corredor de empuje bloqueado: " + "; ".join(details))
                if clear is True:
                    print("Ruta de aproximacion:", route["motivo"])
                    print("Corredor de empuje: libre para cubo y cuerpo del rover.")
                    return
                reason = "captura_vieja"
        if reason != last_reason:
            print("Esperando vision para verificar:", reason, flush=True)
        last_reason = reason
        time.sleep(args.loop_seconds)
    raise RuntimeError("Verificacion sin imagen fresca: " + str(last_reason))


def _check_local_sensors(status, action, color):
    if status.get("diagnostic_only") is not False:
        raise RuntimeError("Modo diagnostico: motores bloqueados. Usa leer_sensores.py")
    if status.get("errors"):
        raise RuntimeError("Sensores locales: " + str(status["errors"]))
    fields = ["ir_age_ms"]
    if status.get("ultrasonic_blocks", True):
        fields.append("distance_age_ms")
    for field in fields:
        age = status.get(field)
        if not isinstance(age, (float, int)) or not math.isfinite(age) or not 0 <= age < 400:
            raise RuntimeError("Sensor local sin lectura fresca: " + field)
    if action == "EMPUJAR":
        if not status.get("color_calibrated"):
            raise RuntimeError("Calibra red, green y blue con leer_sensores.py antes de empujar")
        age = status.get("color_age_ms")
        if not isinstance(age, (float, int)) or not math.isfinite(age) or not 0 <= age < 400:
            raise RuntimeError("Color local sin lectura fresca; rover detenido")
        if status.get("color") != color:
            raise RuntimeError("Color local no confirma cubo {}: {}. Revisa orientacion del sensor y calibracion".format(
                color, status.get("color")))


_COLOR_STALE_GRACE_S = 2.0


def _wait_new_color(robot, vision, state, color, args, mission_deadline=None):
    """Solo STOP/SENSORS: dos intentos completos, cada uno de hasta 15 s.

    La edad del INICIO de los siete barridos prueba que ninguno precede al
    STOP confirmado. Un firmware sin ese dato no autoriza el empuje.
    """
    try:
        robot.send(cmd_stop(), force=True)  # No reutilizar el ACK almacenado.
        stopped_at = time.monotonic()
        baseline = robot.sensors()
        _check_local_sensors(baseline, "PREPARAR", color)
        if "color_started_age_ms" not in baseline:
            raise RuntimeError("Actualizar sensores_rover.py: falta inicio verificable del barrido RGB")
        seq = baseline.get("color_seq")
        if type(seq) is not int or seq < 0:
            raise RuntimeError("color_seq invalido")
        if not baseline.get("color_calibrated"):
            raise RuntimeError("Color sin calibrar")
        stale_since = None
        for attempt in range(args.color_attempts):
            deadline = time.monotonic() + args.color_timeout_seconds
            if mission_deadline is not None:
                deadline = min(deadline, mission_deadline)
            while time.monotonic() < deadline:
                vision.poll()
                reason = _mission_reason(state, color, args.todos)
                # El rover esta parado midiendo color. Pegado al rover, el cubo
                # parpadea en la camara: un parpadeo breve se espera (nunca
                # autoriza movimiento); una perdida prolongada cancela.
                if reason and _transient_vision_reason(reason):
                    if stale_since is None:
                        stale_since = time.monotonic()
                    if time.monotonic() - stale_since > _COLOR_STALE_GRACE_S:
                        raise RuntimeError("STOP durante color: " + reason)
                    time.sleep(.05)
                    continue
                if reason:
                    raise RuntimeError("STOP durante color: " + reason)
                stale_since = None
                requested_at = time.monotonic()
                status = robot.sensors()
                received_at = time.monotonic()
                _check_local_sensors(status, "PREPARAR", color)
                current = status.get("color_seq")
                if type(current) is not int or current < seq:
                    raise RuntimeError("color_seq invalido o reinicio del rover")
                if current > seq:
                    seq = current
                    age, start_age = status.get("color_age_ms"), status.get("color_started_age_ms")
                    valid_age = lambda v: type(v) in (int, float) and math.isfinite(v) and v >= 0
                    # El instante de solicitud es una cota conservadora del
                    # reloj remoto; incluir red y redondeo impide rejuvenecer.
                    if not (valid_age(age) and valid_age(start_age) and start_age >= age):
                        raise RuntimeError("Inicio/fin de color no verificable")
                    if start_age + 1 > (requested_at - stopped_at) * 1000:
                        print("STOP: descartado barrido iniciado antes de confirmar parada", flush=True)
                    elif age + (received_at - requested_at) * 1000 >= 400:
                        print("Color descartado: llego vencido; esperando otra lectura", flush=True)
                    elif received_at >= deadline:
                        raise RuntimeError("Timeout de color; rover detenido")
                    else:
                        print("Color esperado={} detectado={} seq={} edad_ms={} firma={} intento={}".format(
                            color, status.get("color"), seq, age,
                            status.get("color_signature"), attempt + 1), flush=True)
                        detected = status.get("color")
                        if detected is not None and detected != color:
                            raise RuntimeError("Color incorrecto: esperado {}, detectado {}".format(color, detected))
                        if detected == color:
                            return {"seq": seq, "expires": requested_at + (400 - age) / 1000,
                                    "status": status, "used": False}
                        break  # Desconocido: otro resultado completo, nunca reclasificar.
                time.sleep(.05)
            else:
                raise RuntimeError("Timeout esperando una medicion completa de color; rover detenido")
        raise RuntimeError("Color desconocido persistente; rover detenido")
    except BaseException:
        robot.stop()
        raise


def _send_motion(robot, state, color, args, command, motion=None, action="AVANZAR", error=None,
                 color_ticket=None, color_latched=False):
    if args.usar_sensores:
        status = robot.sensors()
        # Con el color ya confirmado en este empuje, el sensor pegado al cubo
        # no puede volver a medir (lee gris); no se le exige otra lectura.
        _check_local_sensors(status, "AVANZAR" if color_latched else action, color)
        if action == "EMPUJAR" and not color_latched and (color_ticket is None or
                color_ticket.get("used", False) or
                status.get("color_seq") != color_ticket["seq"] or
                time.monotonic() >= color_ticket["expires"]):
            robot.stop()
            raise RuntimeError("Empuje sin una medicion nueva posterior a STOP")
        if action == "EMPUJAR" and not color_latched:
            color_ticket["used"] = True
    # El calculo de rutas puede consumir el plazo de frescura del cuadro.
    if _mission_reason(state, color, args.todos) is not None:
        robot.stop()
    elif motion is not None:
        print("Movimiento objetivo={} rover={} cubo={} destinos={} comando={} color={}".format(
            color, state.rover(state.robot_id), state.cube(color), state.message["depots"],
            command, None if color_ticket is None else color_ticket.get("status")), flush=True)
        return motion.execute(robot, state, command,
                              lambda: _mission_reason(state, color, args.todos) is None,
                              action, error)
    else:
        robot.send(command, force=True)


def run(args):
    state = DevelopmentTelemetryState(
        robot_id=args.robot_id,
        peer_id=args.peer_id,
        max_age_ms=args.max_age_ms,
    )
    vision = VisionClient(state, args.vision_host, args.vision_port)
    robot = RobotClient(args.robot_ip, args.robot_port, wait_seconds=60)
    motion = VisualSteps(vision, args.motion_pulse_seconds, args.turn_pulse_seconds,
                         monotonic=time.monotonic, wall=time.time, sleep=time.sleep,
                         max_steps=args.max_pulses)
    planner = RoutePlanner(
        robot_radius_mm=args.robot_radius_mm,
        peer_radius_mm=args.robot_radius_mm,
        clearance_mm=args.clearance_mm,
        required_colors=(),
    )
    stage = "ESPERANDO"
    selection = None
    last_status = None
    started = None
    goal_since = None
    retreat_target = None
    color_ticket = None
    # Rojo confirmado para el empuje en curso; vale mientras el cubo siga
    # pegado al rover segun la vision.
    color_confirmed = False
    retreats = 0
    previous_rover = None
    traveled_mm = 0
    push_origin = None
    stale_since = None

    try:
        print("Esperando telemetría de visión...")
        _wait_for_vision(vision, state, timeout=args.vision_timeout)
        cube_color, target, target_label = _resolve_selection(args, state.message)
        _wait_for_vision(vision, state, cube_color, timeout=args.vision_timeout)
        selection = cube_color
        if not destino_valido_para_cubo(target, state.message["grid"],
                                       state.message["cube_side"] * state.message["grid"]["cell_mm"]):
            raise ValueError("El cubo no cabe completo en ese destino")
        print(
            "Prueba: cubo {} -> {} ({:.2f}, {:.2f})".format(
                cube_color, target_label, target["col"], target["row"]
            )
        )
        resume = _resuming_push(state, cube_color, target, args)
        conflicts = _position_conflicts(state, state.rover(args.robot_id), planner)
        if resume:
            # Pegado al cubo objetivo a proposito: solo cuentan los demas.
            conflicts = [c for c in conflicts if not c.startswith("cubo {}:".format(cube_color))]
            print("Rover detras del cubo y en linea con el destino: se retoma el empuje.")
        if conflicts:
            raise RuntimeError("Recoloca el rover antes de iniciar: " + "; ".join(conflicts))
        if args.solo_verificar:
            reason = _mission_reason(state, cube_color, args.todos)
            if reason:
                raise RuntimeError("Vision no lista: " + reason)
            cube = state.cube(cube_color)
            if _goal_reached(state.message, cube, target, target_label, args.goal_tolerance_mm):
                print("El cubo ya esta dentro de su destino.")
                return 0
            _verify_approach_and_push(vision, state, cube_color, target, planner, args, resume)
            print("Verificacion lista; no se abrio conexion de motores.")
            if args.usar_sensores:
                print("Esta verificacion solo revisa vision/rutas. Sensores de placa: comprobar con leer_sensores.py.")
            return 0
        print("Conectando robot {}:{}...".format(args.robot_ip, args.robot_port))
        robot.connect()
        print("Robot conectado. Inicio en 2 s; Ctrl+C detiene.")
        print("Signo de giro: {} (adaptacion de motores; theta de vision sin modificar)".format(args.turn_sign))
        countdown = time.monotonic() + 2
        while time.monotonic() < countdown:
            vision.poll()
            time.sleep(0.02)
        if args.usar_sensores:
            if not args.sensor_mira_cubo:
                raise RuntimeError("Confirma fisicamente sensor frente al cubo; requiere --sensor-mira-cubo")
            status = robot.sensors()
            _check_local_sensors(status, "PREPARAR", cube_color)
            print("Sensores locales: distancia={} mm, IR={}, color={}".format(
                status.get("distance_mm"), status.get("ir"), status.get("color")))
            _print_reset_reason(status)
            if not status.get("color_calibrated"):
                raise RuntimeError("Falta calibrar el sensor de color. Ejecuta leer_sensores.py antes de la mision")
        started = time.monotonic()
        stage = "ALINEAR" if resume else "APROXIMAR"

        while time.monotonic() - started < args.max_seconds:
            vision.poll()
            reason = _mission_reason(state, cube_color, args.todos)
            if reason is not None:
                goal_since = None
                stopped = robot.stop()
                if last_status != reason:
                    print("STOP por telemetría:", reason)
                    last_status = reason
                # Entre pulsos los motores ya deben estar detenidos. Una
                # captura vencida puede esperar su reemplazo, sin autorizar
                # movimiento ni aumentar el limite de edad. Durante un pulso
                # VisualSteps sigue abortando de inmediato por datos viejos.
                if _transient_vision_reason(reason) and stopped:
                    # Un permiso de color no sobrevive a una espera de vision.
                    color_ticket = None
                    if stale_since is None:
                        stale_since = time.monotonic()
                    if time.monotonic() - stale_since < args.vision_timeout:
                        time.sleep(.02)
                        continue
                raise RuntimeError("Prueba cancelada por telemetria: " + reason)
            stale_since = None
            if not motion.ready(state):
                # El paso anterior ya confirmo STOP. Drenar telemetria sin
                # volver a mandar giros ni repetir STOP por cada republicacion.
                time.sleep(0.01)
                continue
            last_status = None
            msg = state.message
            grid = msg["grid"]
            cell_mm = grid["cell_mm"]
            rover = state.rover(args.robot_id)
            cube = state.cube(cube_color)
            if previous_rover is not None:
                traveled_mm += distancia_mm(rover, previous_rover, cell_mm)
            previous_rover = dict(rover)
            if traveled_mm >= args.max_travel_mm:
                raise RuntimeError("Limite de desplazamiento acumulado alcanzado")
            cube_to_goal = distancia_mm(cube, target, cell_mm)
            if stage == "RETIRAR":
                # Retrocede por el corredor de llegada, sin girar junto al cubo.
                if not _goal_reached(msg, cube, target, target_label, args.goal_tolerance_mm):
                    raise RuntimeError("El cubo salio del destino durante la retirada")
                if distancia_mm(rover, retreat_target, cell_mm) <= args.approach_tolerance_mm:
                    robot.stop()
                    print("Retirada terminada; siguiente cubo.")
                    return 0
                decision = decidir_movimiento_hacia(
                    dict(rover, theta=(rover["theta"] + 180) % 360), retreat_target,
                    cell_mm, tolerancia_mm=args.approach_tolerance_mm,
                    tolerancia_angular_deg=args.abort_push_angle_deg)
                if decision["accion"] == "GIRAR":
                    raise RuntimeError("Retirada desalineada; recoloca el rover")
                scene = _fresh_scene(planner, _without_target(state, cube_color))
                if scene is None:
                    robot.stop()
                    time.sleep(args.loop_seconds)
                    continue
                if not planner.free_segment(scene, (rover["col"], rover["row"]),
                                            (retreat_target["col"], retreat_target["row"])):
                    raise RuntimeError("Retirada bloqueada")
                correction = max(-.08, min(.08, args.steering_gain * decision["medidas"]["giro_grados"]))
                _send_motion(robot, state, cube_color, args,
                             _motor_pair(-args.approach_speed, correction, args.turn_sign),
                             motion, "RETIRAR")
                time.sleep(args.loop_seconds)
                continue
            if _goal_reached(msg, cube, target, target_label, args.goal_tolerance_mm):
                robot.stop()
                if goal_since is None:
                    goal_since = time.monotonic()
                if time.monotonic() - goal_since < args.goal_hold_seconds:
                    time.sleep(args.loop_seconds)
                    continue
                print("OBJETIVO ALCANZADO: cubo a {:.1f} mm del destino".format(cube_to_goal))
                if args.todos and distancia_mm(rover, cube, cell_mm) < args.approach_center_distance_mm:
                    angle = math.radians(rover["theta"])
                    distance = args.approach_center_distance_mm / cell_mm
                    retreat_target = {"col": rover["col"] - distance * math.cos(angle),
                                      "row": rover["row"] + distance * math.sin(angle)}
                    stage = "RETIRAR"
                    continue
                return 0
            goal_since = None

            behind = punto_detras_del_cubo(
                cube, target, args.approach_center_distance_mm, cell_mm
            )
            if not (0 <= behind["col"] <= grid["cols"] and 0 <= behind["row"] <= grid["rows"]):
                robot.stop()
                raise RuntimeError("No hay espacio detrás del cubo para esta maniobra")

            if stage == "APROXIMAR":
                if distancia_mm(rover, behind, cell_mm) <= args.approach_tolerance_mm:
                    robot.stop()
                    stage = "ALINEAR"
                    print("Detras del cubo; alineando con el destino...")
                    continue
                route = planner.plan(state, behind)
                if route["estado"] != "RUTA" or len(route["puntos"]) < 1:
                    robot.stop()
                    if _transient_vision_reason(route["motivo"]):
                        print("STOP: la observacion caduco al calcular la ruta; esperando otro cuadro.")
                        time.sleep(args.loop_seconds)
                        continue
                    raise RuntimeError("No hay ruta segura detrás del cubo: " + _route_error(route, state, behind, planner))
                waypoint = route["puntos"][1] if len(route["puntos"]) > 1 else behind
                decision = decidir_movimiento_hacia(
                    rover, waypoint, cell_mm,
                    tolerancia_mm=args.approach_tolerance_mm,
                    tolerancia_angular_deg=args.angle_tolerance_deg,
                )
                # El último waypoint es la posición detrás del cubo. Sólo ahí
                # se cambia a alineación de empuje.
                command = _motor_command(
                    decision["accion"], decision["medidas"]["giro_grados"],
                    args.approach_speed, args.turn_speed, args.steering_gain,
                    motion, turn_sign=args.turn_sign,
                )
                _send_motion(robot, state, cube_color, args, command, motion,
                             decision["accion"], decision["medidas"]["giro_grados"])

            elif stage == "ALINEAR":
                corridor = _push_clear(state, cube_color, target, planner, args)
                if corridor is None:
                    robot.stop()
                    time.sleep(args.loop_seconds)
                    continue
                if not corridor:
                    raise RuntimeError("Corredor de empuje bloqueado por otro objeto o el borde")
                decision = decidir_movimiento_hacia(
                    rover, target, cell_mm,
                    tolerancia_mm=0,
                    tolerancia_angular_deg=args.push_angle_tolerance_deg,
                )
                angle = decision["medidas"]["giro_grados"]
                if abs(angle) <= args.push_angle_tolerance_deg:
                    robot.stop()
                    stage = "EMPUJAR"
                    push_origin = (cube["col"], cube["row"])
                    print("Alineado; iniciando empuje...")
                    continue
                _send_motion(robot, state, cube_color, args,
                    _motor_command("GIRAR", angle, args.approach_speed,
                                   args.turn_speed, args.steering_gain, motion,
                                   turn_sign=args.turn_sign),
                    motion, "GIRAR", angle,
                )

            elif stage == "EMPUJAR":
                deviation_mm = point_segment_distance(
                    (cube["col"], cube["row"]), push_origin,
                    (target["col"], target["row"])) * cell_mm
                if deviation_mm > args.max_cube_deviation_mm:
                    raise RuntimeError("Cubo desviado {:.1f} mm del corredor inicial".format(deviation_mm))
                in_contact = (distancia_mm(rover, cube, cell_mm) <
                              args.approach_center_distance_mm - args.approach_tolerance_mm)
                if color_confirmed and not in_contact:
                    print("El cubo se separo del rover; se vuelve a confirmar el color.", flush=True)
                    color_confirmed = False
                if args.usar_sensores and not color_confirmed and color_ticket is None:
                    # El color se calibra a ~1 cm: desde la posicion de
                    # alineado (~8 cm) el sensor solo ve luz ambiente. Cerrar
                    # la distancia con avances normales, sin permiso de empuje.
                    distance = robot.sensors().get("distance_mm")
                    if distance is None and retreats < 3:
                        # <20 mm: aplastado contra el cubo, el LED no tiene
                        # hueco para reflejar y el color sale gris.
                        retreats += 1
                        print("Sensor pegado al cubo; retrocediendo para medir color.", flush=True)
                        _send_motion(robot, state, cube_color, args,
                                     _motor_pair(-args.push_speed, 0, args.turn_sign),
                                     motion, "RETROCEDER")
                        time.sleep(args.loop_seconds)
                        continue
                    if distance is not None and distance > args.contact_mm:
                        decision = decidir_movimiento_hacia(
                            rover, target, cell_mm,
                            tolerancia_mm=0,
                            tolerancia_angular_deg=args.push_angle_tolerance_deg,
                        )
                        angle = decision["medidas"]["giro_grados"]
                        print("Acercando al cubo: {:.0f} mm > contacto {:.0f} mm".format(
                            distance, args.contact_mm), flush=True)
                        _send_motion(robot, state, cube_color, args,
                            _motor_command("AVANZAR", angle, args.push_speed,
                                           args.turn_speed, args.push_steering_gain,
                                           turn_sign=args.turn_sign),
                            motion, "AVANZAR", angle,
                        )
                        time.sleep(args.loop_seconds)
                        continue
                    color_ticket = _wait_new_color(robot, vision, state, cube_color, args,
                                                   started + args.max_seconds)
                    # Descartar TODA geometria previa a los ~10 s de barrido.
                    # El siguiente ciclo calcula corredor y rumbo nuevamente.
                    continue
                corridor = _push_clear(state, cube_color, target, planner, args)
                if corridor is None:
                    robot.stop()
                    time.sleep(args.loop_seconds)
                    continue
                if not corridor:
                    raise RuntimeError("Corredor de empuje bloqueado por otro objeto o el borde")
                # El rumbo se corrige contra el destino final. Si el cubo se
                # desvía lateralmente, el rover vuelve a orientar el empuje
                # hacia donde realmente debe llevarlo.
                decision = decidir_movimiento_hacia(
                    rover, target, cell_mm,
                    tolerancia_mm=0,
                    tolerancia_angular_deg=args.push_angle_tolerance_deg,
                )
                angle = decision["medidas"]["giro_grados"]
                if abs(angle) > args.abort_push_angle_deg:
                    robot.stop()
                    raise RuntimeError("Se perdio alineacion durante empuje ({:.1f} grados)".format(angle))
                _send_motion(robot, state, cube_color, args,
                    _motor_command("AVANZAR", angle, args.push_speed,
                                   args.turn_speed, args.push_steering_gain,
                                   turn_sign=args.turn_sign),
                    motion, "EMPUJAR", angle, color_ticket=color_ticket,
                    color_latched=color_confirmed,
                )
                if args.usar_sensores and not color_confirmed:
                    print("Rojo confirmado: se empuja sin volver a medir mientras el cubo siga pegado.",
                          flush=True)
                color_confirmed = args.usar_sensores
                retreats = 0
                color_ticket = None

            time.sleep(args.loop_seconds)

        robot.stop()
        raise RuntimeError("Tiempo máximo de prueba agotado")
    except KeyboardInterrupt:
        print("Prueba detenida por usuario")
        return 130
    finally:
        was_connected = robot.sock is not None
        stopped = robot.close()
        vision.close()
        if selection and not args.solo_verificar:
            if stopped:
                print("STOP confirmado por el rover; prueba cerrada.")
            elif was_connected:
                print("Conexion cerrada sin confirmacion de STOP; el rover depende de su watchdog.")
            else:
                print("Prueba cerrada; no habia conexion con el rover para enviar STOP.")


def build_parser():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--robot-ip", help="IP del rover; se pregunta si no se indica")
    p.add_argument("--todos", action="store_true", help="Un solo rover: red, green y blue a sus zonas")
    p.add_argument("--solo-verificar", action="store_true", help="Comprobar vision y rutas sin conectar motores")
    p.add_argument("--usar-sensores", action="store_true",
                   help="Exigir sensores del rover y confirmacion local de color antes del empuje")
    p.add_argument("--sensor-mira-cubo", action="store_true",
                   help="Confirmacion fisica: sensor orientado a la cara del cubo a distancia calibrada")
    p.add_argument("--color-timeout-seconds", type=float, default=15)
    p.add_argument("--color-attempts", type=int, default=2,
                   help="Resultados completos permitidos si el color es desconocido (1 a 3)")
    p.add_argument("--goal-hold-seconds", type=float, default=0.5)
    p.add_argument("--motion-pulse-seconds", type=float, default=0.12,
                   help="Duracion maxima solicitada de avance antes de STOP y nueva observacion")
    p.add_argument("--turn-pulse-seconds", type=float, default=0.10,
                   help="Duracion maxima solicitada de giro antes de STOP y nueva observacion")
    p.add_argument("--robot-port", type=int, default=5000)
    p.add_argument("--vision-host", default="127.0.0.1")
    p.add_argument("--vision-port", type=int, default=2026)
    p.add_argument("--robot-id", type=int, default=10)
    p.add_argument("--peer-id", type=int, default=11)
    p.add_argument("--cube", choices=COLORS)
    p.add_argument("--depot", choices=COLORS,
                   help="Destino: centro del depósito indicado")
    p.add_argument("--dest-col", type=float)
    p.add_argument("--dest-row", type=float)
    p.add_argument("--max-age-ms", type=float, default=600)
    p.add_argument("--vision-timeout", type=float, default=15)
    p.add_argument("--max-seconds", type=float, default=120)
    p.add_argument("--max-pulses", type=int, default=60)
    p.add_argument("--max-travel-mm", type=float, default=1000)
    p.add_argument("--max-cube-deviation-mm", type=float, default=25)
    p.add_argument("--robot-radius-mm", type=float, default=85)
    p.add_argument("--clearance-mm", type=float, default=10)
    p.add_argument("--approach-center-distance-mm", type=float, default=150,
                   help="Centro rover-cubo en el punto previo al empuje")
    p.add_argument("--approach-tolerance-mm", type=float, default=25)
    p.add_argument("--goal-tolerance-mm", type=float, default=20)
    p.add_argument("--angle-tolerance-deg", type=float, default=7)
    p.add_argument("--contact-mm", type=float, default=35,
                   help="Distancia del ultrasonido a la que el sensor de color ya ve el cubo")
    p.add_argument("--push-angle-tolerance-deg", type=float, default=5)
    p.add_argument("--abort-push-angle-deg", type=float, default=18)
    p.add_argument("--approach-speed", type=float, default=0.24)
    p.add_argument("--push-speed", type=float, default=0.20)
    p.add_argument("--turn-speed", type=float, default=0.18)
    p.add_argument("--turn-sign", type=int, choices=(-1, 1), default=-1,
                   help="Signo del giro: -1 medido en rover 10; +1 para montaje convencional")
    p.add_argument("--steering-gain", type=float, default=0.008)
    p.add_argument("--push-steering-gain", type=float, default=0.006)
    p.add_argument("--loop-seconds", type=float, default=0.10)
    return p


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    if not args.solo_verificar and not args.usar_sensores:
        parser.error("Movimiento requiere --usar-sensores; para diagnostico sin motores usa --solo-verificar")
    if args.todos and any(v is not None for v in (args.cube, args.depot, args.dest_col, args.dest_row)):
        parser.error("--todos ya selecciona cada cubo y su zona del mismo color")
    if (args.dest_col is None) != (args.dest_row is None):
        parser.error("--dest-col y --dest-row deben indicarse juntos")
    if args.depot is not None and args.dest_col is not None:
        parser.error("Use --depot o coordenadas, no ambos")
    for name in (
        "max_age_ms", "vision_timeout", "max_seconds", "robot_radius_mm",
        "clearance_mm", "approach_center_distance_mm", "approach_tolerance_mm",
        "goal_tolerance_mm", "angle_tolerance_deg", "push_angle_tolerance_deg", "contact_mm",
        "abort_push_angle_deg", "approach_speed", "push_speed", "turn_speed",
        "steering_gain", "push_steering_gain", "loop_seconds", "goal_hold_seconds",
        "color_timeout_seconds",
        "max_travel_mm", "max_cube_deviation_mm",
    ):
        try:
            value = _finite(getattr(args, name), name)
        except ValueError as error:
            parser.error(str(error))
        if value < 0:
            parser.error(name + " no puede ser negativo")
    if not 0 < args.color_timeout_seconds <= 30 or not 1 <= args.color_attempts <= 3:
        parser.error("Color requiere timeout en (0, 30] e intentos entre 1 y 3")
    if args.max_pulses < 1 or min(args.max_travel_mm, args.max_cube_deviation_mm) <= 0:
        parser.error("Limites de pulsos y desplazamiento deben ser positivos")
    if not all(0 < getattr(args, name) <= 1 for name in
               ("approach_speed", "push_speed", "turn_speed")):
        parser.error("Las velocidades deben estar en (0, 1]")
    for name in ("motion_pulse_seconds", "turn_pulse_seconds"):
        if not math.isfinite(getattr(args, name)) or not 0 < getattr(args, name) <= .2:
            parser.error(name + " debe estar en (0, 0.2]")
    try:
        if not args.solo_verificar:
            args.robot_ip = str(ipaddress.IPv4Address(args.robot_ip or input(
                "IP del rover {} (mostrada al conectar Wi-Fi): ".format(args.robot_id)).strip()))
        if args.todos:
            for color in COLORS:
                task = copy.copy(args)
                task.cube = task.depot = color
                print("\n--- ROVER {}: {} -> zona {} ---".format(args.robot_id, color, color))
                result = run(task)
                if result != 0:
                    return result
            print("Verificacion completa." if args.solo_verificar else "Mision completada: los tres cubos en sus zonas.")
            return 0
        return run(args)
    except (OSError, ValueError, RuntimeError, ConnectionError) as error:
        print("ERROR:", error, file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
