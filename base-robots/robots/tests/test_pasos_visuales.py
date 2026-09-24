"""Ensaya latencia de cámara, ACK y cambio de sentido sin motores reales."""
from pathlib import Path
import sys
import unittest
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "pc"))
from pasos_visuales import VisualSteps


class Clock:
    def __init__(self):
        self.now = 100.

    def sleep(self, seconds):
        self.now += seconds


class Robot:
    def __init__(self, clock, ack_delay=0):
        self.clock, self.ack_delay = clock, ack_delay
        self.sent = []
        self.stopped_at = None

    def send(self, command, force=False):
        self.sent.append(command)
        self.clock.sleep(self.ack_delay)

    def stop(self):
        self.stopped_at = self.clock.now
        return True


class VisualStepTests(unittest.TestCase):
    def setUp(self):
        self.clock = Clock()
        self.vision = SimpleNamespace(poll=lambda: None)
        self.motion = VisualSteps(self.vision, monotonic=lambda: self.clock.now,
                                  wall=lambda: self.clock.now, sleep=self.clock.sleep)
        self.robot = Robot(self.clock)
        self.rover = {"theta": 0, "age_ms": 0}
        self.state = SimpleNamespace(robot_id=10, message={"ts_ms": 99900},
                                     rover=lambda _: self.rover, capture_age_ms=lambda: 100)

    def test_no_new_movement_until_capture_after_stop(self):
        self.motion.execute(self.robot, self.state, "MOTOR|-0.18|0.18", lambda: True, "GIRAR", 60)
        self.assertAlmostEqual(self.robot.stopped_at, 100.1)
        self.assertFalse(self.motion.ready(self.state))
        self.state.message["ts_ms"] = 100150  # Cuadro demasiado cercano a la parada.
        self.assertFalse(self.motion.ready(self.state))
        self.state.message["ts_ms"] = 100200
        self.assertTrue(self.motion.ready(self.state))
        self.rover["age_ms"] = 300  # Timestamp nuevo, pero pose recordada del pasado.
        self.assertFalse(self.motion.ready(self.state))

    def test_repeated_frames_do_not_repeat_motor_commands(self):
        for _ in range(5):
            self.motion.execute(self.robot, self.state, "MOTOR|.2|.2", lambda: True, "AVANZAR")
        self.assertEqual(len(self.robot.sent), 1)

    def test_ack_delay_is_part_of_pulse(self):
        self.robot.ack_delay = .3
        self.motion.execute(self.robot, self.state, "MOTOR|.2|.2", lambda: True, "AVANZAR")
        self.assertAlmostEqual(self.robot.stopped_at, 100.3)  # Sin sumar otro pulso tras el ACK.

    def test_opposite_heading_noise_does_not_alternate_turns(self):
        self.assertEqual([self.motion.direction(e) for e in (179, -179, 178, -178)], [1] * 4)
        self.assertEqual(self.motion.direction(-30), -1)

    def test_shorter_pulse_near_heading_target(self):
        self.motion.execute(self.robot, self.state, "MOTOR|-.18|.18", lambda: True, "GIRAR", 8)
        self.assertAlmostEqual(self.robot.stopped_at, 100.04)

    def test_failed_command_still_attempts_stop(self):
        def fail(*args, **kwargs):
            raise TimeoutError("sin ACK")
        self.robot.send = fail
        with self.assertRaisesRegex(ConnectionError, "no confirmo AVANZAR"):
            self.motion.execute(self.robot, self.state, "MOTOR|.2|.2", lambda: True, "AVANZAR")
        self.assertIsNotNone(self.robot.stopped_at)


if __name__ == "__main__":
    unittest.main()
