"""Tiempo real simulado: siete barridos, STOP, red y resultados desconocidos."""
import copy
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "pc"))
import prueba_transporte_cubo as trial


class ColorWaitTests(unittest.TestCase):
    def setUp(self):
        self.now = 0.0
        self.args = trial.build_parser().parse_args(["--usar-sensores", "--sensor-mira-cubo"])
        self.state, self.vision, self.robot = Mock(), Mock(), Mock()
        self.state.reason.return_value = None
        self.base = dict(diagnostic_only=False, errors={}, ir_age_ms=0, distance_age_ms=0,
                         color_calibrated=True, color_seq=4, color=None,
                         color_age_ms=None, color_started_age_ms=None)
        self.events = [(10., "red")]
        self.robot.sensors.side_effect = self.status
        self.robot.stop.return_value = True

    def status(self):
        status = copy.deepcopy(self.base)
        for index, (at, color) in enumerate(self.events):
            if self.now >= at:
                status.update(color_seq=5 + index, color=color,
                              color_age_ms=(self.now - at) * 1000,
                              color_started_age_ms=(self.now - at + 9.9) * 1000,
                              color_signature=[.8, .1, .1])
        return status

    def sleep(self, duration):
        self.now += duration

    def wait(self, mission_deadline=None):
        with patch.object(trial.time, "monotonic", side_effect=lambda: self.now), \
             patch.object(trial.time, "sleep", side_effect=self.sleep):
            return trial._wait_new_color(self.robot, self.vision, self.state, "red", self.args,
                                         mission_deadline)

    def test_waits_ten_seconds_then_accepts_new_complete_sequence(self):
        ticket = self.wait()
        self.assertEqual(ticket["seq"], 5)
        self.assertGreaterEqual(self.now, 10)
        self.assertLess(self.now, 10.1)
        self.robot.send.assert_called_once_with("STOP", force=True)
        self.assertGreater(self.vision.poll.call_count, 100)

    def test_unknown_allows_only_another_complete_sequence(self):
        self.events = [(10., None), (20., "red")]
        self.assertEqual(self.wait()["seq"], 6)
        self.assertGreaterEqual(self.now, 20)

    def test_wrong_color_aborts_without_retry(self):
        self.events = [(10., "green"), (20., "red")]
        with self.assertRaisesRegex(RuntimeError, "Color incorrecto"):
            self.wait()
        self.assertLess(self.now, 10.1)
        self.robot.stop.assert_called()

    def test_persistent_unknown_stops_at_defined_attempt_limit(self):
        self.events = [(10., None), (20., None), (30., "red")]
        with self.assertRaisesRegex(RuntimeError, "desconocido persistente"):
            self.wait()
        self.assertLess(self.now, 20.1)
        self.robot.stop.assert_called()

    def test_old_sequence_never_authorizes_even_if_color_and_age_match(self):
        self.base.update(color="red", color_age_ms=0, color_started_age_ms=0)
        self.events = []
        with self.assertRaisesRegex(RuntimeError, "Timeout"):
            self.wait()
        self.assertLess(self.now, 15.1)

    def test_result_started_before_stop_is_discarded(self):
        self.events = [(1., "red"), (11., "red")]
        self.assertEqual(self.wait()["seq"], 6)
        self.assertGreaterEqual(self.now, 11)

    def test_firmware_without_start_timestamp_fails_closed(self):
        del self.base["color_started_age_ms"]
        with self.assertRaisesRegex(RuntimeError, "Actualizar sensores_rover"):
            self.wait()
        self.robot.stop.assert_called()

    def test_expired_vision_aborts_while_waiting(self):
        self.state.reason.return_value = "captura_vieja"
        with self.assertRaisesRegex(RuntimeError, "captura_vieja"):
            self.wait()
        self.robot.stop.assert_called()

    def test_brief_cube_flicker_does_not_abort_color_wait(self):
        # Pegado al rover el cubo parpadea en la camara: 1 s vencido se espera.
        self.state.reason.side_effect = lambda *a, **k: "cubo_objetivo_viejo" if 2 <= self.now < 3 else None
        self.assertEqual(self.wait()["status"]["color"], "red")

    def test_latched_red_pushes_while_sensor_reads_grey_against_cube(self):
        # Pegado al cubo el sensor lee gris (color=None): con el rojo ya
        # confirmado en este empuje, el pulso se envia igual.
        self.robot.sensors.side_effect = None
        self.robot.sensors.return_value = copy.deepcopy(self.base)
        trial._send_motion(self.robot, self.state, "red", self.args, "MOTOR|0.2|0.2",
                           action="EMPUJAR", color_latched=True)
        self.robot.send.assert_called_with("MOTOR|0.2|0.2", force=True)

    def test_unlatched_push_still_requires_fresh_color(self):
        self.robot.sensors.side_effect = None
        self.robot.sensors.return_value = copy.deepcopy(self.base)
        with self.assertRaises(RuntimeError):
            trial._send_motion(self.robot, self.state, "red", self.args, "MOTOR|0.2|0.2",
                               action="EMPUJAR")
        self.robot.send.assert_not_called()

    def test_sensor_disconnect_attempts_stop(self):
        self.robot.sensors.side_effect = [self.base, ConnectionError("desconexion")]
        with self.assertRaises(ConnectionError):
            self.wait()
        self.robot.stop.assert_called()

    def test_keyboard_interrupt_attempts_stop(self):
        self.vision.poll.side_effect = KeyboardInterrupt
        with self.assertRaises(KeyboardInterrupt):
            self.wait()
        self.robot.stop.assert_called()

    def test_failed_stop_ack_prevents_any_sensor_measurement(self):
        self.robot.send.side_effect = TimeoutError("STOP sin ACK")
        with self.assertRaises(TimeoutError):
            self.wait()
        self.robot.sensors.assert_not_called()
        self.robot.stop.assert_called()

    def test_sensor_fault_aborts(self):
        self.base["errors"] = {"ultrasonic": "sin_eco_valido"}
        with self.assertRaisesRegex(RuntimeError, "sin_eco_valido"):
            self.wait()
        self.robot.stop.assert_called()

    def test_mission_deadline_caps_color_wait(self):
        with self.assertRaisesRegex(RuntimeError, "Timeout"):
            self.wait(mission_deadline=2)
        self.assertLess(self.now, 2.1)

    def test_cli_cannot_start_motion_without_sensors(self):
        with patch.object(trial, "run") as run, self.assertRaises(SystemExit):
            trial.main(["--robot-ip", "127.0.0.1", "--cube", "red", "--depot", "red"])
        run.assert_not_called()

    def test_reboot_during_wait_aborts(self):
        other = dict(self.base, color_seq=0)
        self.robot.sensors.side_effect = [self.base, other]
        with self.assertRaisesRegex(RuntimeError, "reinicio"):
            self.wait()

    def test_push_requires_ticket_even_with_fresh_matching_color(self):
        self.robot.sensors.side_effect = None
        self.robot.sensors.return_value = dict(self.base, color="red", color_age_ms=0)
        with self.assertRaisesRegex(RuntimeError, "posterior a STOP"):
            trial._send_motion(self.robot, self.state, "red", self.args,
                               "MOTOR|.2|.2", action="EMPUJAR")
        self.robot.send.assert_not_called()

    def test_missing_diagnostic_flag_cannot_authorize_motion(self):
        status = dict(self.base)
        del status["diagnostic_only"]
        with self.assertRaisesRegex(RuntimeError, "bloqueados"):
            trial._check_local_sensors(status, "PREPARAR", "red")


if __name__ == "__main__":
    unittest.main()
