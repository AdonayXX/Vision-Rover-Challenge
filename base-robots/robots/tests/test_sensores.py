"""Sensores, parada local y protocolo sin conectar ni mover hardware."""
import copy
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

BASE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE / "codigos"))
sys.path.insert(0, str(BASE / "pc"))
from sensores_rover import SensoresRover, firma_color, clasificar_color, validar_config
from sesion_comandos import CommandSession
from control_movimiento import MotionController
from prueba_transporte_cubo import RobotClient, _check_local_sensors
from leer_sensores import guardar_perfil
from hardware_sensores import Sonar, HardwareSensores
from test_control import Clock, Robot, Socket


class SensorTests(unittest.TestCase):
    def setUp(self):
        self.cfg = json.loads((BASE / "codigos/config_sensores.json").read_text())
        # El hardware simulado sí está verificado. La configuración real sigue
        # en diagnóstico y NO se habilita como efecto secundario de las pruebas.
        self.cfg["diagnostic_only"] = False
        self.cfg["ultrasonic"]["echo_3v3_confirmed"] = True
        self.clock, self.robot = Clock(), Robot()
        self.hw = SimpleNamespace(errors={}, sonar=Mock(),
                                  ir=[SimpleNamespace(value=12000) for _ in range(4)],
                                  light=SimpleNamespace(value=40000), pixel=[(0, 0, 0)])
        self.hw.sonar.poll.return_value = (True, 250)
        self.sensors = SensoresRover(self.hw, self.cfg, self.clock)
        self.controller = MotionController(self.robot, clock=self.clock, safety=self.sensors)
        self.session = CommandSession(self.controller, clock=self.clock, sensors=self.sensors)

    def test_forward_requires_fresh_readings(self):
        self.assertIsNotNone(self.sensors.reason(.2, .2))
        self.sensors.update()
        self.assertIsNone(self.sensors.reason(.2, .2))
        self.clock.advance(.5)
        self.assertIsNotNone(self.sensors.reason(.2, .2))

    def test_obstacle_stops_locally_without_new_pc_command(self):
        self.assertTrue(self.session.process_command("MOTOR|.2|.2"))
        self.session.tick()
        self.assertGreater(self.robot.motor_1.throttle, 0)
        self.hw.sonar.poll.return_value = (True, 50)
        self.clock.advance(.05)
        self.session.tick()
        self.assertEqual(self.controller.reason, "obstaculo_frontal")
        self.assertEqual((self.robot.motor_1.throttle, self.robot.motor_2.throttle), (0, 0))

    def test_obstacle_rejects_new_forward_command(self):
        self.hw.sonar.poll.return_value = (True, 30)
        self.assertFalse(self.session.process_command("MOTOR|.2|.2"))
        self.assertIsNone(self.controller.mode)

    def test_echo_timeout_is_not_infinite_clear_distance(self):
        self.sensors.update()
        self.hw.sonar.poll.return_value = (True, None)
        self.sensors.update()
        self.assertIsNone(self.sensors.snapshot()["distance_mm"])
        self.assertIsNotNone(self.sensors.reason(.2, .2))

    def test_sensor_error_does_not_prevent_stop(self):
        self.hw.sonar.poll.side_effect = OSError("desconectado")
        self.assertTrue(self.session.process_command("STOP"))
        self.assertIsNone(self.controller.mode)

    def test_ir_is_not_a_black_square_edge_detector(self):
        self.sensors.update()
        self.sensors.ir = [0, 65535, 100, 64000]
        self.assertIsNone(self.sensors.reason(.2, .2))
        self.assertFalse(self.sensors.snapshot()["ir_calibrated"])

    def test_calibrated_ir_outside_range_stops(self):
        self.cfg["ir"]["floor_ranges"] = [[1000, 62000]] * 4
        self.sensors.update()
        self.sensors.ir[0] = 100
        self.assertEqual(self.sensors.reason(.2, .2), "ir_fuera_del_suelo_calibrado")

    def test_color_scan_is_cooperative_and_resets_on_motion(self):
        self.sensors.update()
        for value in (4000, 20000, 7000, 8000):
            self.clock.advance(self.cfg["color"]["settle_seconds"] + .001)
            # Un pico aislado no debe convertirse en la lectura del canal.
            for sample in (value, value, 65000, value, value):
                self.hw.light.value = sample
                self.sensors.update()
                self.clock.advance(self.cfg["color"]["sample_interval_seconds"] + .001)
        result = self.sensors.snapshot()
        self.assertEqual(result["color_seq"], 1)
        self.assertEqual(result["color_raw"], [4000, 20000, 7000, 8000])
        self.assertIsNone(result["color"])
        self.assertAlmostEqual(sum(result["color_signature"]), 1)
        self.sensors.update()
        self.sensors.update(moving=True)
        self.assertFalse(self.sensors.scanning)
        self.assertEqual(self.hw.pixel[0], (0, 0, 0))

    def test_color_waits_and_does_not_reuse_partial_phase_after_motion(self):
        self.sensors.update()
        self.clock.advance(.1)
        self.sensors.update()
        self.assertEqual(self.sensors.phase_samples, [])
        self.clock.advance(.101)
        self.sensors.update()
        self.assertEqual(len(self.sensors.phase_samples), 1)
        self.sensors.update()  # Mismo instante: no duplicar muestra.
        self.assertEqual(len(self.sensors.phase_samples), 1)
        self.assertEqual(self.sensors.color_seq, 0)
        self.sensors.update(moving=True)
        self.sensors.update()
        self.assertEqual(self.sensors.phase_samples, [])
        self.assertEqual(self.sensors.samples, [])
        self.assertEqual(self.sensors.phase, 0)

    def test_legacy_color_config_keeps_single_sample_scanning(self):
        self.cfg["color"].pop("samples_per_phase")
        self.cfg["color"].pop("sample_interval_seconds")
        validar_config(self.cfg)
        self.sensors.update()
        for value in (4000, 20000, 7000, 8000):
            self.clock.advance(.201)
            self.hw.light.value = value
            self.sensors.update()
        self.assertEqual(self.sensors.snapshot()["color_raw"], [4000, 20000, 7000, 8000])

    def test_color_sampling_config_is_bounded(self):
        for key, value in (("samples_per_phase", 2), ("samples_per_phase", True),
                           ("samples_per_phase", 100), ("sample_interval_seconds", 0),
                           ("sample_interval_seconds", float("nan")),
                           ("sample_interval_seconds", True)):
            cfg = copy.deepcopy(self.cfg)
            cfg["color"][key] = value
            with self.assertRaises(ValueError):
                validar_config(cfg)

    def test_inconsistent_color_does_not_overwrite_config(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            original = json.dumps(self.cfg)
            path.write_text(original, encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "no demuestra movimiento"):
                guardar_perfil(path, "red", [[1, 0, 0], [0, 0, 1]] * 6)
            self.assertEqual(path.read_text(encoding="utf-8"), original)

    def test_color_signature_supports_both_sensor_polarities(self):
        positive = [4000, 20000, 7000, 8000]
        negative = [40000, 24000, 37000, 36000]
        expected = [16 / 23, 3 / 23, 4 / 23]
        self.assertEqual(firma_color(positive, polarity=1), expected)
        self.assertEqual(firma_color(negative, polarity=-1), expected)
        self.assertIsNone(firma_color(positive, polarity=-1))
        self.assertIsNone(firma_color(negative, polarity=1))
        self.assertIsNone(firma_color([2819] * 4, polarity=1))

    def test_color_rejects_unknown_ambiguous_and_dark(self):
        profiles = {"red": [1, 0, 0], "green": [0, 1, 0], "blue": [0, 0, 1]}
        self.assertEqual(clasificar_color([.95, .03, .02], profiles), "red")
        self.assertIsNone(clasificar_color([.33, .33, .34], profiles))
        self.assertIsNone(firma_color([40000] * 4))
        self.assertIsNone(clasificar_color([1, 0, 0], {"red": [1, 0, 0]}))
        profiles["green"] = [1, 0, 0]
        self.assertIsNone(clasificar_color([1, 0, 0], profiles))

    def test_sensor_queries_do_not_renew_motor_watchdog(self):
        self.session.process_command("MOTOR|.2|.2")
        for _ in range(6):
            self.clock.advance(.1)
            self.session.process_command("SENSORS")
        self.assertIsNone(self.controller.mode)
        self.assertEqual(self.controller.reason, "watchdog")
        self.assertTrue(json.loads(self.session.reply)["enabled"])

    def test_sensor_json_survives_partial_tcp_writes(self):
        sock = Socket([b"SENSORS\n"], send_limit=17)
        for _ in range(100):
            self.session.poll(sock)
            if sock.sent.endswith(b"\n"):
                break
        result = json.loads(sock.sent)
        self.assertEqual(result["distance_mm"], 250)
        self.assertIsNone(self.controller.mode)

    def test_pc_reads_fragmented_sensor_json(self):
        self.sensors.update()
        data = json.dumps(self.sensors.snapshot()).encode() + b"\n"
        client = RobotClient("127.0.0.1")
        client.sock, client.buffer = Mock(), b""
        client.sock.recv.side_effect = [data[i:i + 13] for i in range(0, len(data), 13)]
        self.assertEqual(client.sensors()["distance_mm"], 250)

    def test_pc_refuses_uncalibrated_or_wrong_color_push(self):
        self.sensors.update()
        result = self.sensors.snapshot()
        _check_local_sensors(result, "AVANZAR", "red")
        with self.assertRaisesRegex(RuntimeError, "Calibra"):
            _check_local_sensors(result, "EMPUJAR", "red")
        result.update(color_calibrated=True, color="green", color_age_ms=0)
        with self.assertRaisesRegex(RuntimeError, "no confirma"):
            _check_local_sensors(result, "EMPUJAR", "red")
        result["color"] = "red"
        _check_local_sensors(result, "EMPUJAR", "red")

    def test_invalid_config_is_rejected(self):
        for key, value in (("stop_mm", -1), ("stop_mm", float("nan")), ("echo_3v3_confirmed", "false")):
            cfg = copy.deepcopy(self.cfg)
            cfg["ultrasonic"][key] = value
            with self.assertRaises(ValueError):
                validar_config(cfg)

    def test_calibration_saves_only_profile_and_preserves_pins(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            path.write_text(json.dumps(self.cfg), encoding="utf-8")
            guardar_perfil(path, "red", [[.8, .1, .1]] * 12)
            result = json.loads(path.read_text())
            self.assertEqual(result["color"]["analog"], self.cfg["color"]["analog"])
            self.assertEqual(result["color"]["profiles"]["red"], [.8, .1, .1])
            self.assertEqual(result["ultrasonic"]["echo_3v3_confirmed"],
                             self.cfg["ultrasonic"]["echo_3v3_confirmed"])

    def test_hardware_does_not_activate_unconfirmed_echo_or_adc2(self):
        self.cfg["color"]["analog"] = "IO4"
        self.cfg["ultrasonic"]["echo_3v3_confirmed"] = False
        board = SimpleNamespace(**{name: name for name in ("IO25", "IO26", "IO32", "IO33", "IO4", "IO36", "IO39", "IO34", "IO35")})
        analog = Mock()
        with patch.dict(sys.modules, {"board": board, "analogio": analog, "neopixel": Mock()}), \
             patch("hardware_sensores.Sonar") as sonar:
            hw = HardwareSensores(self.cfg)
        sonar.assert_not_called()
        self.assertIsNone(hw.light)
        self.assertEqual(set(hw.errors), {"ultrasonic", "color"})
        self.assertEqual([c.args[0] for c in analog.AnalogIn.call_args_list], ["IO36", "IO39", "IO34", "IO35"])

    def test_sonar_poll_has_bounded_timeout_and_no_wait_loop(self):
        sonar = Sonar.__new__(Sonar)
        sonar.trigger = SimpleNamespace(value=False)
        echo = Mock()
        from unittest.mock import MagicMock
        sonar.echo = MagicMock()
        sonar.echo.__len__.return_value = 0
        sonar.pending, sonar.started, sonar.next_ping = False, 0, 0
        with patch("hardware_sensores.time.monotonic", self.clock), patch("hardware_sensores.time.sleep") as sleep:
            self.assertEqual(sonar.poll(), (False, None))
            sleep.assert_called_once_with(.00001)
            self.assertFalse(sonar.trigger.value)
            self.clock.advance(.031)
            self.assertEqual(sonar.poll(), (True, None))
            self.assertFalse(sonar.pending)

    def test_valid_echo_is_converted_to_mm(self):
        from unittest.mock import MagicMock
        sonar = Sonar.__new__(Sonar)
        sonar.echo = MagicMock()
        sonar.echo.__len__.return_value = 1
        sonar.echo.__getitem__.return_value = 1000
        sonar.pending, sonar.started, sonar.next_ping = True, 0, .08
        with patch("hardware_sensores.time.monotonic", self.clock):
            self.assertEqual(sonar.poll(), (True, 171.5))

    def test_monitor_only_queries_sensors_and_stops(self):
        import leer_sensores
        client = Mock()
        client.sensors.return_value = {"color_signature": None}
        with patch.object(leer_sensores, "RobotClient", return_value=client), \
             patch.object(leer_sensores.time, "monotonic", self.clock), \
             patch.object(leer_sensores.time, "sleep", self.clock.advance), \
             patch("builtins.print"):
            self.assertEqual(leer_sensores.main(["--robot-ip", "127.0.0.1", "--segundos", "1"]), 0)
        self.assertGreater(client.sensors.call_count, 0)
        client.send.assert_not_called()
        client.close.assert_called_once()

    def test_diagnostic_mode_blocks_all_motion_but_allows_readings(self):
        self.cfg["diagnostic_only"] = True
        self.cfg["ultrasonic"]["echo_3v3_confirmed"] = False
        for command in ("MOTOR|.2|.2", "MOTOR|-.2|-.2", "MOTOR|.2|-.2",
                        "TURN|30|.2", "HEADING|0|.2|1"):
            self.assertFalse(self.session.process_command(command), command)
            self.session.tick()
            self.assertEqual((self.robot.motor_1.throttle, self.robot.motor_2.throttle), (0, 0))
            self.assertIsNone(self.controller.mode)
        self.assertTrue(self.session.process_command("SENSORS"))
        status = json.loads(self.session.reply)
        self.assertEqual(status["distance_mm"], 250)
        self.assertFalse(status["echo_3v3_confirmed"])
        self.assertTrue(status["diagnostic_only"])
        self.assertTrue(self.session.process_command("STOP"))

    def test_leaving_diagnostics_does_not_confirm_echo(self):
        self.cfg["ultrasonic"]["echo_3v3_confirmed"] = False
        self.sensors.update()
        self.assertEqual(self.sensors.reason(.2, -.2), "echo_electrico_sin_verificar")

    def test_explicit_diagnostic_echo_reading_preserves_warning(self):
        self.cfg["diagnostic_only"] = True
        self.cfg["ultrasonic"]["echo_3v3_confirmed"] = False
        self.cfg["ultrasonic"]["allow_unverified_echo_diagnostic"] = True
        board = SimpleNamespace(**{name: name for name in ("IO25", "IO26", "IO32", "IO33", "IO36", "IO39", "IO34", "IO35")})
        neopixel = SimpleNamespace(NeoPixel=Mock(return_value=[(0, 0, 0)]))
        with patch.dict(sys.modules, {"board": board, "analogio": Mock(), "neopixel": neopixel}), \
             patch("hardware_sensores.Sonar") as sonar:
            hw = HardwareSensores(self.cfg)
        sonar.assert_called_once_with("IO25", "IO26")
        self.assertTrue(hw.warnings)
        self.assertFalse(self.cfg["ultrasonic"]["echo_3v3_confirmed"])
        self.assertIsNone(self.controller.mode)


if __name__ == "__main__":
    unittest.main()
