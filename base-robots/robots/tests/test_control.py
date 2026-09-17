"""Regresiones de seguridad con reloj, IMU, motores y socket simulados."""
import math
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "codigos"))
import command_protocol as protocol
from control_movimiento import MotionController, calibrate_drift
from sesion_comandos import CommandSession
from wifi_command_receiver import serve_client
from robot_state import RobotState


class Clock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


class Motor:
    throttle = 0


class Robot:
    def __init__(self):
        self.motor_1, self.motor_2 = Motor(), Motor()


class Sensor:
    gyro = (0, 0, 0)


class Socket:
    def __init__(self, chunks=(), send_limit=512):
        self.chunks = list(chunks)
        self.sent = b""
        self.send_limit = send_limit
        self.closed = False

    def setblocking(self, value):
        assert value is False

    def recv_into(self, buffer):
        if not self.chunks:
            raise OSError(11, "sin datos")
        item = self.chunks.pop(0)
        if isinstance(item, Exception):
            raise item
        chunk, rest = item[:len(buffer)], item[len(buffer):]
        if rest:
            self.chunks.insert(0, rest)
        buffer[:len(chunk)] = chunk
        return len(chunk)

    def send(self, data):
        count = min(len(data), self.send_limit)
        self.sent += data[:count]
        return count

    def close(self):
        self.closed = True


class ControlTests(unittest.TestCase):
    def setUp(self):
        self.clock, self.robot, self.sensor = Clock(), Robot(), Sensor()
        self.control = MotionController(self.robot, self.sensor, clock=self.clock)
        self.session = CommandSession(self.control, clock=self.clock)

    def step(self, count=1, seconds=0.1):
        for _ in range(count):
            self.clock.advance(seconds)
            self.session.tick()

    def assert_stopped(self):
        self.assertIsNone(self.control.mode)
        self.assertEqual((self.robot.motor_1.throttle, self.robot.motor_2.throttle), (0, 0))

    def test_builders_and_legacy_share_parser(self):
        messages = [protocol.cmd_ping(), protocol.cmd_stop(), protocol.cmd_keepalive(),
                    protocol.cmd_motor(.2, -.2), protocol.cmd_turn(-90), protocol.cmd_heading(10)]
        for message in messages:
            self.assertTrue(protocol.parse_command(message)["valid"])
        self.assertEqual(protocol.parse_command("MOTOR .2 -.2"), protocol.parse_command("MOTOR|.2|-.2"))

    def test_nonfinite_and_malformed_rejected(self):
        for message in (None, "", "STOP|1", "PING junk", "MOTOR|2|0", "TURN|90|0",
                        "HEADING|0|.5|0", "MOTOR|nan|0", "TURN|inf|.3",
                        "TURN|90|nan", "HEADING|0|.5|nan", "X" * 129):
            with self.subTest(message=message):
                self.assertFalse(protocol.parse_command(message)["valid"])
        for value in (float("nan"), float("inf"), 2):
            with self.assertRaises(ValueError):
                protocol.cmd_motor(value, 0)

    def test_ping_cannot_keep_motors_alive(self):
        self.session.process_command("MOTOR|.5|.5")
        for _ in range(6):
            self.clock.advance(.1)
            self.session.process_command("PING")
        self.assert_stopped()

    def test_keepalive_does_not_restart_heading_timer(self):
        self.session.process_command("HEADING|0|.5|1")
        for _ in range(12):
            self.clock.advance(.1)
            self.session.process_command("KEEPALIVE")
        self.assert_stopped()
        self.assertEqual(self.control.reason, "completado")

    def test_late_keepalive_cannot_restart(self):
        self.session.process_command("MOTOR|.5|.5")
        self.step(6)
        self.assertFalse(self.session.process_command("KEEPALIVE"))
        self.assert_stopped()

    def test_stop_interrupts_turn(self):
        self.session.process_command("TURN|90|.3")
        self.step()
        self.assertNotEqual(self.robot.motor_1.throttle, 0)
        self.session.process_command("STOP")
        self.assert_stopped()

    def test_turn_uses_signed_progress_both_directions(self):
        for direction in (-1, 1):
            self.control.start_turn(20 * direction)
            self.sensor.gyro = (0, 0, math.radians(-100 * direction))
            self.clock.advance(.2)
            self.control.update()
            self.assertEqual(self.control.mode, "TURN")
            self.sensor.gyro = (0, 0, math.radians(100 * direction))
            for _ in range(2):
                self.clock.advance(.2)
                self.control.update()
            self.assert_stopped()

    def test_frozen_gyro_has_timeout_even_with_keepalive(self):
        self.control.turn_timeout = .7
        self.session.process_command("TURN|90|.3")
        for _ in range(8):
            self.clock.advance(.1)
            self.session.process_command("KEEPALIVE")
        self.assert_stopped()
        self.assertEqual(self.control.reason, "timeout_giro")

    def test_delayed_loop_stops(self):
        self.control.start_motor(.5, .5)
        self.control.update()
        self.clock.advance(.3)
        self.control.update()
        self.assert_stopped()

    def test_invalid_gyro_stops(self):
        self.control.start_turn(90)
        self.sensor.gyro = (0, 0, float("nan"))
        self.clock.advance(.1)
        with self.assertRaises(ValueError):
            self.control.update()
        self.assert_stopped()

    def test_invalid_command_stops_active_motion(self):
        self.session.process_command("MOTOR|.5|.5")
        self.step()
        self.assertFalse(self.session.process_command("TURN|nan|.3"))
        self.assert_stopped()

    def test_heading_corrects_towards_positive_angle(self):
        self.control.start_heading(20, .5, 1)
        self.clock.advance(.1)
        self.control.update()
        self.assertGreater(self.robot.motor_2.throttle, self.robot.motor_1.throttle)

    def test_heading_wraps_at_180(self):
        self.control.start_heading(-179, .5, 1)
        self.control.angle = 179
        self.clock.advance(.1)
        self.control.update()
        self.assertGreater(self.robot.motor_2.throttle, self.robot.motor_1.throttle)
        self.assertLess(self.robot.motor_2.throttle - self.robot.motor_1.throttle, .1)

    def test_direct_calls_reject_invalid_and_stop(self):
        self.control.start_motor(.3, .3)
        self.control.update()
        with self.assertRaises(ValueError):
            self.control.start_heading(0, .5, float("inf"))
        self.assert_stopped()

    def test_missing_imu_rejects_turn(self):
        self.control.sensor = None
        self.assertFalse(self.session.process_command("TURN|90|.3"))
        self.assert_stopped()

    def test_calibration_fails_when_moving(self):
        self.sensor.gyro = (0, 0, 1)
        with self.assertRaises(ValueError):
            calibrate_drift(self.sensor, clock=self.clock, sleep=self.clock.advance)

    def test_fragmented_tcp_and_partial_responses(self):
        sock = Socket([b"MOT", b"OR|.5|.5\nPING\n"], send_limit=1)
        self.session.poll(sock)
        self.assert_stopped()
        self.session.poll(sock)
        for _ in range(5):
            self.session.poll(sock)
        self.assertEqual(sock.sent, b"OK\nOK\n")
        self.assertEqual(self.robot.motor_1.throttle, .5)

    def test_disconnect_stops(self):
        self.session.process_command("MOTOR|.5|.5")
        self.assertFalse(self.session.poll(Socket([b""])))
        self.assert_stopped()

    def test_socket_error_is_not_hidden(self):
        self.session.process_command("MOTOR|.5|.5")
        with self.assertRaises(OSError):
            self.session.poll(Socket([OSError(104, "reset")]))
        self.assert_stopped()

    def test_overlong_and_nonascii_stop(self):
        for data in (b"x" * 129, b"x" * 129 + b"\n", b"\xff\n"):
            self.session = CommandSession(self.control, clock=self.clock)
            self.session.process_command("MOTOR|.5|.5")
            sock = Socket([data])
            with self.assertRaises((ValueError, UnicodeError)):
                for _ in range(3):
                    self.session.poll(sock)
            self.assert_stopped()

    def test_slow_reader_does_not_grow_without_bound(self):
        class SlowSocket(Socket):
            def send(self, data):
                raise OSError(11, "lleno")
        sock = SlowSocket([b"PING\n" * 25] * 8)
        with self.assertRaises(ValueError):
            for _ in range(8):
                self.session.poll(sock)
        self.assert_stopped()

    def test_invalid_command_discards_rest_of_batch(self):
        self.session.poll(Socket([b"BAD\nMOTOR|.5|.5\n"]))
        self.assert_stopped()

    def test_server_closes_client_on_error(self):
        sock = Socket([b"MOTOR|.5|.5\n", OSError(104, "reset")])
        with self.assertRaises(OSError):
            serve_client(sock, self.control, clock=self.clock, sleep=self.clock.advance)
        self.assertTrue(sock.closed)
        self.assert_stopped()

    def test_repeated_error_updates_message_and_clear_on_recovery(self):
        state = RobotState(10)
        state.error("A", "primero")
        state.error("B", "segundo")
        self.assertEqual(state.message, "segundo")
        state.moving()
        self.assertIsNone(state.error_code)


if __name__ == "__main__":
    unittest.main()
