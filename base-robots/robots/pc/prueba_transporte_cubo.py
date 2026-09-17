"""Prueba física de desarrollo: empujar un cubo hacia un destino indicado.

Usa la telemetría de visión como realimentación y el receptor TCP de comandos
del rover. Es una herramienta de puesta a punto en PC; no es el programa de
misión autónoma que se ejecutará en los rovers durante una ronda.
"""

import argparse
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
from rutas import RoutePlanner
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
    def __init__(self, host, port=5000, timeout=1.5):
        self.host, self.port, self.timeout = host, port, timeout
        self.sock = None
        self.last = None

    def connect(self):
        self.close(send_stop=False)
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(self.timeout)
        sock.connect((self.host, self.port))
        self.sock = sock
        self.send("STOP", force=True)

    def send(self, command, force=False):
        if self.sock is None:
            raise ConnectionError("Robot no conectado")
        if not force and command == self.last:
            # Igual se renueva el watchdog: no omitir el envío físico.
            pass
        self.sock.sendall((command + "\n").encode("ascii"))
        response = self.sock.recv(64).decode("ascii", "replace").strip()
        if response != "OK":
            raise ConnectionError("Respuesta del robot: {!r}".format(response))
        self.last = command

    def stop(self):
        if self.sock is not None:
            try:
                self.send(cmd_stop(), force=True)
            except OSError:
                pass
        self.last = cmd_stop()

    def close(self, send_stop=True):
        if self.sock is not None:
            if send_stop:
                self.stop()
            try:
                self.sock.close()
            except OSError:
                pass
        self.sock = None


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


def _motor_command(action, angle_error, speed, turn_speed, steering_gain):
    if action == "GIRAR":
        sign = 1.0 if angle_error > 0 else -1.0
        # Giro antihorario positivo: rueda izquierda atrás, derecha adelante.
        return cmd_motor(-sign * turn_speed, sign * turn_speed)
    correction = max(-0.18, min(0.18, steering_gain * angle_error))
    left = max(-1.0, min(1.0, speed - correction))
    right = max(-1.0, min(1.0, speed + correction))
    return cmd_motor(left, right)


def _wait_for_vision(client, state, color=None, timeout=15):
    limit = time.monotonic() + timeout
    while time.monotonic() < limit:
        client.poll()
        if state.reason(color) is None:
            return
        time.sleep(0.02)
    raise RuntimeError("Visión no lista: " + str(state.reason(color)))


def run(args):
    state = DevelopmentTelemetryState(
        robot_id=args.robot_id,
        peer_id=args.peer_id,
        max_age_ms=args.max_age_ms,
    )
    vision = VisionClient(state, args.vision_host, args.vision_port)
    robot = RobotClient(args.robot_ip, args.robot_port)
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

    try:
        print("Esperando telemetría de visión...")
        _wait_for_vision(vision, state, timeout=args.vision_timeout)
        cube_color, target, target_label = _resolve_selection(args, state.message)
        _wait_for_vision(vision, state, cube_color, timeout=args.vision_timeout)
        selection = cube_color
        if not destino_valido_para_cubo(target, state.message["grid"], state.message["cube_side"]):
            raise ValueError("El cubo no cabe completo en ese destino")
        print(
            "Prueba: cubo {} -> {} ({:.2f}, {:.2f})".format(
                cube_color, target_label, target["col"], target["row"]
            )
        )
        print("Conectando robot {}:{}...".format(args.robot_ip, args.robot_port))
        robot.connect()
        print("Robot conectado. Inicio en 2 s; Ctrl+C detiene.")
        time.sleep(2)
        started = time.monotonic()
        stage = "APROXIMAR"

        while time.monotonic() - started < args.max_seconds:
            vision.poll()
            reason = state.reason(cube_color)
            if reason is not None:
                robot.stop()
                if last_status != reason:
                    print("STOP por telemetría:", reason)
                    last_status = reason
                time.sleep(0.02)
                continue
            last_status = None
            msg = state.message
            grid = msg["grid"]
            cell_mm = grid["cell_mm"]
            rover = state.rover(args.robot_id)
            cube = state.cube(cube_color)
            cube_to_goal = distancia_mm(cube, target, cell_mm)
            if cube_to_goal <= args.goal_tolerance_mm:
                robot.stop()
                print("OBJETIVO ALCANZADO: cubo a {:.1f} mm del destino".format(cube_to_goal))
                return 0

            behind = punto_detras_del_cubo(
                cube, target, args.approach_center_distance_mm, cell_mm
            )
            if not (0 <= behind["col"] <= grid["cols"] and 0 <= behind["row"] <= grid["rows"]):
                robot.stop()
                raise RuntimeError("No hay espacio detrás del cubo para esta maniobra")

            if stage == "APROXIMAR":
                route = planner.plan(state, behind)
                if route["estado"] != "RUTA" or len(route["puntos"]) < 1:
                    robot.stop()
                    raise RuntimeError("No hay ruta segura detrás del cubo: " + str(route["motivo"]))
                waypoint = route["puntos"][1] if len(route["puntos"]) > 1 else behind
                decision = decidir_movimiento_hacia(
                    rover, waypoint, cell_mm,
                    tolerancia_mm=args.approach_tolerance_mm,
                    tolerancia_angular_deg=args.angle_tolerance_deg,
                )
                # El último waypoint es la posición detrás del cubo. Sólo ahí
                # se cambia a alineación de empuje.
                if distancia_mm(rover, behind, cell_mm) <= args.approach_tolerance_mm:
                    robot.stop()
                    stage = "ALINEAR"
                    print("Detrás del cubo; alineando con el destino...")
                    continue
                command = _motor_command(
                    decision["accion"], decision["medidas"]["giro_grados"],
                    args.approach_speed, args.turn_speed, args.steering_gain,
                )
                robot.send(command, force=True)

            elif stage == "ALINEAR":
                decision = decidir_movimiento_hacia(
                    rover, target, cell_mm,
                    tolerancia_mm=0,
                    tolerancia_angular_deg=args.push_angle_tolerance_deg,
                )
                angle = decision["medidas"]["giro_grados"]
                if abs(angle) <= args.push_angle_tolerance_deg:
                    robot.stop()
                    stage = "EMPUJAR"
                    print("Alineado; iniciando empuje...")
                    continue
                robot.send(
                    _motor_command("GIRAR", angle, args.approach_speed,
                                   args.turn_speed, args.steering_gain),
                    force=True,
                )

            elif stage == "EMPUJAR":
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
                    stage = "ALINEAR"
                    print("Se perdió alineación ({:.1f}°); realineando...".format(angle))
                    continue
                robot.send(
                    _motor_command("AVANZAR", angle, args.push_speed,
                                   args.turn_speed, args.push_steering_gain),
                    force=True,
                )

            time.sleep(args.loop_seconds)

        robot.stop()
        raise RuntimeError("Tiempo máximo de prueba agotado")
    except KeyboardInterrupt:
        print("Prueba detenida por usuario")
        return 130
    finally:
        robot.close()
        vision.close()
        if selection:
            print("STOP enviado; prueba cerrada.")


def build_parser():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--robot-ip", default="192.168.40.18")
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
    p.add_argument("--robot-radius-mm", type=float, default=85)
    p.add_argument("--clearance-mm", type=float, default=10)
    p.add_argument("--approach-center-distance-mm", type=float, default=150,
                   help="Centro rover-cubo en el punto previo al empuje")
    p.add_argument("--approach-tolerance-mm", type=float, default=25)
    p.add_argument("--goal-tolerance-mm", type=float, default=20)
    p.add_argument("--angle-tolerance-deg", type=float, default=7)
    p.add_argument("--push-angle-tolerance-deg", type=float, default=5)
    p.add_argument("--abort-push-angle-deg", type=float, default=18)
    p.add_argument("--approach-speed", type=float, default=0.24)
    p.add_argument("--push-speed", type=float, default=0.20)
    p.add_argument("--turn-speed", type=float, default=0.18)
    p.add_argument("--steering-gain", type=float, default=0.008)
    p.add_argument("--push-steering-gain", type=float, default=0.006)
    p.add_argument("--loop-seconds", type=float, default=0.10)
    return p


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    if (args.dest_col is None) != (args.dest_row is None):
        parser.error("--dest-col y --dest-row deben indicarse juntos")
    if args.depot is not None and args.dest_col is not None:
        parser.error("Use --depot o coordenadas, no ambos")
    for name in (
        "max_age_ms", "vision_timeout", "max_seconds", "robot_radius_mm",
        "clearance_mm", "approach_center_distance_mm", "approach_tolerance_mm",
        "goal_tolerance_mm", "angle_tolerance_deg", "push_angle_tolerance_deg",
        "abort_push_angle_deg", "approach_speed", "push_speed", "turn_speed",
        "steering_gain", "push_steering_gain", "loop_seconds",
    ):
        try:
            value = _finite(getattr(args, name), name)
        except ValueError as error:
            parser.error(str(error))
        if value < 0:
            parser.error(name + " no puede ser negativo")
    if not all(0 < getattr(args, name) <= 1 for name in
               ("approach_speed", "push_speed", "turn_speed")):
        parser.error("Las velocidades deben estar en (0, 1]")
    try:
        return run(args)
    except (OSError, ValueError, RuntimeError, ConnectionError) as error:
        print("ERROR:", error, file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
