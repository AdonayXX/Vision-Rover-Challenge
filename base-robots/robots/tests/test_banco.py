"""El cliente de banco contra el controlador real con motores y reloj falsos."""
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "pc"))
from prueba_banco import Client, exercise
from test_control import Clock, Robot
from control_movimiento import MotionController
from sesion_comandos import CommandSession


class BenchSocket:
    def __init__(self, session):
        self.session = session
        self.response = b""
        self.closed = False

    def sendall(self, data):
        if self.closed:
            raise OSError("cerrado")
        self.response += b"OK\n" if self.session.process_command(data.decode().strip()) else b"ERROR\n"
        self.session.tick()

    def recv(self, size):
        # Respuestas fragmentadas para ejercitar el protocolo TCP del cliente.
        part, self.response = self.response[:1], self.response[1:]
        return part

    def close(self):
        self.closed = True


class BenchTests(unittest.TestCase):
    def setUp(self):
        self.clock, self.robot = Clock(), Robot()
        self.controller = MotionController(self.robot, clock=self.clock)
        self.session = CommandSession(self.controller, clock=self.clock)
        self.socket = BenchSocket(self.session)
        self.client = Client(self.socket)

    def sleep(self, duration):
        for _ in range(10):
            self.clock.advance(duration / 10)
            self.session.tick()

    def test_connection_does_not_move(self):
        exercise(self.client)
        self.assertIsNone(self.controller.mode)

    def test_individual_motor_and_stop(self):
        for motor, expected in ((1, (0.2, 0)), (2, (0, 0.2))):
            def observe(duration):
                self.assertEqual((self.robot.motor_1.throttle, self.robot.motor_2.throttle), expected)
                self.sleep(duration)
            exercise(self.client, "pulso", motor=motor, sleep=observe)
            self.assertEqual((self.robot.motor_1.throttle, self.robot.motor_2.throttle), (0, 0))

    def test_watchdog_stops_before_final_stop_despite_ping(self):
        def observe(duration):
            self.sleep(duration)
            if self.clock.now >= 0.5:
                self.assertIsNone(self.controller.mode)
        exercise(self.client, "watchdog", sleep=observe)
        self.assertGreaterEqual(self.clock.now, 0.9)

    def test_interruption_stops(self):
        def interrupt(duration):
            raise KeyboardInterrupt()
        with self.assertRaises(KeyboardInterrupt):
            exercise(self.client, "pulso", sleep=interrupt)
        self.assertIsNone(self.controller.mode)

    def test_limits_reject_without_motion(self):
        for kwargs in ({"power": float("nan")}, {"power": 0.31}, {"duration": 1}):
            with self.assertRaises(ValueError):
                exercise(self.client, "pulso", **kwargs)
            self.assertIsNone(self.controller.mode)

    def test_without_imu_rejects_turn(self):
        with self.assertRaises(ValueError):
            self.client.command("TURN|90|0.2")
        self.assertIsNone(self.controller.mode)

    def test_disconnect_closes_socket(self):
        exercise(self.client, "desconexion")
        self.assertTrue(self.socket.closed)
        # Este doble no simula EOF: la parada del receptor se prueba en test_control.


if __name__ == "__main__":
    unittest.main()
