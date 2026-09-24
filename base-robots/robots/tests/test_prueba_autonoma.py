"""Regresiones de la prueba de un rover, sin hardware ni sockets reales."""
import copy
from pathlib import Path
import sys
import time
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "pc"))
import prueba_transporte_cubo as trial
from command_protocol import parse_command


def scene():
    state = trial.DevelopmentTelemetryState(max_age_ms=600)
    state.connected = True
    state.fault = None
    state.capture_age_ms = lambda: 10
    state.message = {
        "ts_ms": int(time.time() * 1000),
        "grid": {"cols": 43, "rows": 43, "cell_mm": 20},
        "cube_side": 3,
        "depot_size": {"length": 10, "depth": 7.5},
        "rovers": [{"id": 10, "col": 20, "row": 20, "theta": 0, "age_ms": 0}],
        "cubes": [{"color": c, "col": col, "row": row, "age_ms": 0}
                  for c, col, row in (("red", 28, 20), ("green", 10, 8), ("blue", 10, 35))],
        "obstacles": [],
        "depots": [{"color": "red", "col": 39.25, "row": 21.5}],
    }
    return state


class TurnPolarityTests(unittest.TestCase):
    def motor(self, action, error, speed=.24, sign=-1):
        return parse_command(trial._motor_command(
            action, error, speed, .18, .008, turn_sign=sign))

    def test_positive_error_uses_observed_positive_theta_direction(self):
        command = self.motor("GIRAR", 170.7)
        self.assertAlmostEqual(command["left"], .18)
        self.assertAlmostEqual(command["right"], -.18)

    def test_negative_error_reverses_both_turn_channels(self):
        command = self.motor("GIRAR", -40)
        self.assertAlmostEqual(command["left"], -.18)
        self.assertAlmostEqual(command["right"], .18)

    def test_forward_steering_has_same_yaw_sign_as_turning(self):
        for error in (-5, 5):
            command = self.motor("AVANZAR", error)
            self.assertGreater((command["left"] - command["right"]) * error, 0)
            self.assertGreater(min(command["left"], command["right"]), 0)

    def test_reverse_steering_keeps_reverse_and_correct_yaw(self):
        for error in (-5, 5):
            command = parse_command(trial._motor_pair(-.24, .008 * error, -1))
            self.assertGreater((command["left"] - command["right"]) * error, 0)
            self.assertLess(max(command["left"], command["right"]), 0)

    def test_straight_and_stop_do_not_change(self):
        for speed in (-.24, .24):
            command = self.motor("AVANZAR", 0, speed)
            self.assertEqual((command["left"], command["right"]), (speed, speed))
        self.assertEqual(trial._motor_command("ALCANZADO", 170, .24, .18, .008), "STOP")

    def test_sign_is_configurable_and_rover10_is_default(self):
        self.assertEqual(trial.build_parser().parse_args([]).turn_sign, -1)
        args = trial.build_parser().parse_args(["--turn-sign", "1"])
        command = self.motor("GIRAR", 90, sign=args.turn_sign)
        self.assertLess(command["left"], command["right"])
        with self.assertRaises(ValueError):
            trial._motor_pair(.24, .05, 0)

    def test_observed_motor_polarity_converges_instead_of_oscillating(self):
        # Modelo SOLO del signo observado: con left < right, theta disminuye.
        # No pretende calibrar la velocidad ni sustituir la prueba física.
        for initial, target in ((126.8, 297.5), (5, 350), (350, 5), (0, 179)):
            theta = initial
            memory = trial.VisualSteps(Mock())
            for _ in range(60):
                error = (target - theta + 180) % 360 - 180
                if abs(error) <= 7:
                    break
                command = parse_command(trial._motor_command(
                    "GIRAR", error, .24, .18, .008, memory, turn_sign=-1))
                theta = (theta + 30 * (command["left"] - command["right"])) % 360
            self.assertLessEqual(abs((target - theta + 180) % 360 - 180), 7)


class SingleRoverTests(unittest.TestCase):
    def test_measured_border_conflict_is_reported_before_connecting(self):
        state = scene()
        state.message["rovers"][0].update(col=33.44, row=4.465)
        args = trial.build_parser().parse_args(["--cube", "red", "--depot", "red"])
        with patch.object(trial, "DevelopmentTelemetryState", return_value=state), \
             patch.object(trial, "VisionClient"), patch.object(trial, "RobotClient") as robot:
            with self.assertRaisesRegex(RuntimeError, "borde row=0: centro a 89.3 mm, minimo 95.0 mm"):
                trial.run(args)
            robot.return_value.connect.assert_not_called()
        state.message["rovers"][0]["row"] += 5  # 10 cm hacia dentro.
        planner = trial.RoutePlanner(85, 85, 10, required_colors=())
        self.assertEqual(trial._position_conflicts(state, state.rover(10), planner), [])

    def test_single_rover_permitted_but_missing_cube_stops(self):
        state = scene()
        self.assertIsNone(trial._mission_reason(state, "red", True))
        state.message["cubes"].pop()
        self.assertEqual(trial._mission_reason(state, "red", True), "cubo_objetivo_ausente")

    def test_stale_data_cannot_send_motion(self):
        state, robot = scene(), Mock()
        state.capture_age_ms = lambda: 601
        args = trial.build_parser().parse_args(["--todos"])
        trial._send_motion(robot, state, "red", args, "MOTOR 0.2 0.2")
        robot.stop.assert_called_once()
        robot.send.assert_not_called()

    def test_delivery_requires_entire_cube_inside_not_just_center(self):
        msg = scene().message
        target = {"col": 39.25, "row": 21.5}
        self.assertTrue(trial._goal_reached(msg, target, target, "deposito_red", 20))
        outside = {"col": 41, "row": 21.5}
        self.assertFalse(trial._goal_reached(msg, outside, target, "deposito_red", 60))

    def test_push_corridor_rejects_another_cube(self):
        state = scene()
        args = trial.build_parser().parse_args([])
        planner = trial.RoutePlanner(85, 85, 10, required_colors=())
        target = {"col": 39.25, "row": 20}
        self.assertTrue(trial._push_clear(state, "red", target, planner, args))
        state.message["cubes"][1].update(col=34, row=20)
        self.assertFalse(trial._push_clear(state, "red", target, planner, args))

    def test_removing_target_does_not_mutate_telemetry(self):
        state = scene()
        original = copy.deepcopy(state.message)
        self.assertEqual(len(trial._without_target(state, "red").message["cubes"]), 2)
        self.assertEqual(state.message, original)

    def test_reports_green_near_rover_corridor_from_screenshot(self):
        state = scene()
        state.message["rovers"][0].update(col=22.13, row=21.59)
        for cube, position in zip(state.message["cubes"], ((13.73, 21.74), (26.41, 28.14), (15.75, 34.23))):
            cube.update(col=position[0], row=position[1])
        args = trial.build_parser().parse_args([])
        planner = trial.RoutePlanner(85, 85, 10, required_colors=())
        target = state.message["depots"][0]
        behind = trial.punto_detras_del_cubo(state.cube("red"), target, 150, 20)
        details = []
        self.assertFalse(trial._push_clear(state, "red", target, planner, args,
                                          details=details, robot_start=behind))
        self.assertIn("cuerpo del rover", details[0])
        self.assertIn("cubo green", details[0])
        self.assertIn("minimo 137.4 mm", details[0])
        state.message["cubes"][1]["row"] = 31
        self.assertTrue(trial._push_clear(state, "red", target, planner, args,
                                         robot_start=behind))

    def test_verification_retries_expired_corridor_without_motor_connection(self):
        state = scene()
        args = trial.build_parser().parse_args(["--solo-verificar", "--cube", "red", "--depot", "red"])
        with patch.object(trial, "DevelopmentTelemetryState", return_value=state), \
             patch.object(trial, "VisionClient"), patch.object(trial, "RobotClient") as robot, \
             patch.object(trial, "_push_clear", side_effect=[None, True]) as corridor, \
             patch.object(trial.time, "sleep"):
            self.assertEqual(trial.run(args), 0)
        self.assertEqual(corridor.call_count, 2)
        self.assertIn("robot_start", corridor.call_args.kwargs)
        robot.return_value.connect.assert_not_called()

    def test_expired_corridor_times_out_as_freshness_not_obstacle(self):
        args = trial.build_parser().parse_args(["--vision-timeout", "0.3"])
        clock = [0.0]
        planner = trial.RoutePlanner(85, 85, 10, required_colors=())
        state = scene()
        with patch.object(trial, "_push_clear", return_value=None), \
             patch.object(trial.time, "monotonic", side_effect=lambda: clock[0]), \
             patch.object(trial.time, "sleep", side_effect=lambda seconds: clock.__setitem__(0, clock[0] + seconds)):
            with self.assertRaisesRegex(RuntimeError, "Verificacion sin imagen fresca"):
                trial._verify_approach_and_push(Mock(), state, "red", state.message["depots"][0], planner, args)

    def test_tcp_response_may_arrive_in_fragments(self):
        robot = trial.RobotClient("127.0.0.1")
        robot.sock = Mock()
        robot.buffer = b""
        robot.sock.recv.side_effect = [b"O", b"K", b"\n"]
        robot.send("STOP")
        self.assertEqual(robot.last, "STOP")

    def test_tcp_timeout_is_distinct_from_missing_stop_ack(self):
        sock = Mock()
        sock.connect.side_effect = TimeoutError("timed out")
        robot = trial.RobotClient("10.50.42.138")
        with patch.object(trial.socket, "socket", return_value=sock):
            with self.assertRaisesRegex(ConnectionError, "No se pudo conectar TCP"):
                robot.connect()
        self.assertIsNone(robot.sock)
        self.assertFalse(robot.close())
        sock.sendall.assert_not_called()
        sock.close.assert_called_once()

    def test_missing_stop_ack_closes_connection_without_claiming_success(self):
        sock = Mock()
        sock.recv.side_effect = TimeoutError("timed out")
        robot = trial.RobotClient("10.50.42.138")
        with patch.object(trial.socket, "socket", return_value=sock):
            with self.assertRaisesRegex(ConnectionError, "TCP conectado.*no confirmo STOP"):
                robot.connect()
        self.assertIsNone(robot.sock)
        sock.close.assert_called_once()

    def test_three_colors_sequentially_on_the_same_robot(self):
        with patch.object(trial, "run", return_value=0) as run:
            self.assertEqual(trial.main(["--todos", "--robot-ip", "127.0.0.1"]), 0)
        self.assertEqual([(c.args[0].robot_id, c.args[0].cube, c.args[0].depot)
                          for c in run.call_args_list],
                         [(10, color, color) for color in trial.COLORS])

    def test_failed_task_prevents_starting_next_cube(self):
        with patch.object(trial, "run", return_value=1) as run:
            self.assertEqual(trial.main(["--todos", "--robot-ip", "127.0.0.1"]), 1)
            run.assert_called_once()

    def test_verification_never_connects_robot(self):
        state = scene()
        args = trial.build_parser().parse_args(["--solo-verificar", "--cube", "red", "--depot", "red"])
        with patch.object(trial, "DevelopmentTelemetryState", return_value=state), \
             patch.object(trial, "VisionClient"), patch.object(trial, "RobotClient") as robot:
            self.assertEqual(trial.run(args), 0)
            robot.return_value.connect.assert_not_called()
            robot.return_value.send.assert_not_called()

    def test_reached_waypoint_does_not_advance(self):
        self.assertEqual(trial._motor_command("ALCANZADO", 0, .2, .2, .01), "STOP")

    def test_loss_of_cube_during_run_stops_and_closes_connections(self):
        state = scene()
        args = trial.build_parser().parse_args([
            "--cube", "red", "--depot", "red", "--robot-ip", "127.0.0.1", "--max-seconds", "3"])
        clock = [0.0]
        def sleep(seconds):
            clock[0] += seconds
        def poll():
            if clock[0] >= 2.3:
                state.message["cubes"] = []
        robot = Mock()
        commands = []
        def send(command, **kwargs):
            commands.append(command)
            self.assertIsNotNone(state.cube("red"), "No debe enviar MOTOR sin cubo")
        robot.send.side_effect = send
        vision = Mock()
        vision.poll.side_effect = poll
        with patch.object(trial, "DevelopmentTelemetryState", return_value=state), \
             patch.object(trial, "VisionClient", return_value=vision), \
             patch.object(trial, "RobotClient", return_value=robot), \
             patch.object(trial.time, "monotonic", side_effect=lambda: clock[0]), \
             patch.object(trial.time, "sleep", side_effect=sleep):
            with self.assertRaisesRegex(RuntimeError, "Tiempo máximo"):
                trial.run(args)
        self.assertTrue(commands)
        self.assertGreater(robot.stop.call_count, 0)
        robot.close.assert_called_once()
        vision.close.assert_called_once()

    def test_expired_route_is_retried_without_motion_or_fatal_error(self):
        state = scene()
        state.message["rovers"][0]["col"] = 10  # Lejos del punto de aproximacion.
        args = trial.build_parser().parse_args([
            "--cube", "red", "--depot", "red", "--robot-ip", "127.0.0.1", "--max-seconds", "1"])
        clock = [0.0]
        planner, robot, vision = Mock(), Mock(), Mock()
        planner.radius = planner.peer_radius = 85
        planner.clearance = 10
        planner.obstacle_side = 100
        planner.plan.return_value = {"estado": "ESPERAR", "motivo": "captura_vieja", "puntos": []}
        def sleep(seconds):
            clock[0] += seconds
        with patch.object(trial, "DevelopmentTelemetryState", return_value=state), \
             patch.object(trial, "VisionClient", return_value=vision), \
             patch.object(trial, "RobotClient", return_value=robot), \
             patch.object(trial, "RoutePlanner", return_value=planner), \
             patch.object(trial.time, "monotonic", side_effect=lambda: clock[0]), \
             patch.object(trial.time, "sleep", side_effect=sleep):
            with self.assertRaisesRegex(RuntimeError, "Tiempo máximo"):
                trial.run(args)
        self.assertGreater(planner.plan.call_count, 1)
        robot.send.assert_not_called()
        self.assertGreater(robot.stop.call_count, 0)
        self.assertGreater(vision.poll.call_count, 90)  # Tambien drena durante los 2 s iniciales.

    def test_stale_scene_is_not_reported_as_blocked_corridor(self):
        state = scene()
        state.capture_age_ms = lambda: 601
        args = trial.build_parser().parse_args([])
        planner = trial.RoutePlanner(85, 85, 10, required_colors=())
        self.assertIsNone(trial._push_clear(state, "red", {"col": 39.25, "row": 20}, planner, args))

    def test_live_tcp_stream_with_old_frames_does_not_reconnect(self):
        state = scene()
        clock = [0.0]
        state.monotonic = lambda: clock[0]
        state.received_at = None
        client = trial.VisionClient(state)
        client.socket = Mock()
        client._connected()
        client.receiver = Mock()
        state.fault = "captura_vieja"
        clock[0] = 3  # No hubo ningun cuadro aceptado durante tres segundos.
        client.socket.recv.side_effect = [b'cuadro viejo\n', BlockingIOError()]
        client.poll()
        self.assertIsNotNone(client.socket)
        self.assertTrue(state.connected)
        self.assertEqual(state.fault, "captura_vieja")  # Sigue sin autorizar motores.
        clock[0] = 4.1
        client.socket.recv.side_effect = BlockingIOError()
        client.poll()
        self.assertIsNone(client.socket)  # Silencio real si provoca reconexion.
        self.assertFalse(state.connected)


if __name__ == "__main__":
    unittest.main()
