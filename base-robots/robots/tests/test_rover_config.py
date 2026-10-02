"""Dos rovers con el mismo paquete: lo común en config_robot.json, lo propio en rover.json."""
import json
from pathlib import Path
import sys
import tempfile
import unittest

CODIGOS = Path(__file__).resolve().parents[1] / "codigos"
sys.path.insert(0, str(CODIGOS))
from wifi_command_receiver import aplicar_rover


class RoverConfigTests(unittest.TestCase):
    def setUp(self):
        self.comun = {"wifi_ssid": "red", "vision_host": "10.0.0.8",
                      "control": {"left_gain": 1.0, "right_gain": 1.0, "kp": 0.015}}

    def test_rover_file_overrides_id_and_motor_settings_only(self):
        with tempfile.TemporaryDirectory() as carpeta:
            ruta = Path(carpeta) / "rover.json"
            ruta.write_text(json.dumps({"robot_id": 11, "control": {"right_gain": 0.9, "left_sign": -1}}))
            config = aplicar_rover(self.comun, str(ruta))
        self.assertEqual(config["robot_id"], 11)
        self.assertEqual(config["control"], {"left_gain": 1.0, "right_gain": 0.9, "kp": 0.015, "left_sign": -1})
        self.assertEqual(config["vision_host"], "10.0.0.8")

    def test_missing_rover_file_keeps_common_config(self):
        config = aplicar_rover(dict(self.comun), str(Path(tempfile.gettempdir()) / "no_existe_rover.json"))
        self.assertNotIn("robot_id", config)
        self.assertEqual(config["control"]["right_gain"], 1.0)

    def test_each_rover_has_its_own_valid_file(self):
        for archivo in CODIGOS.glob("rover_*.json"):
            datos = json.loads(archivo.read_text(encoding="utf-8"))
            self.assertEqual(archivo.stem, "rover_{}".format(datos["robot_id"]))
            self.assertNotIn("wifi_password", json.dumps(datos))   # va a git: sin secretos


if __name__ == "__main__":
    unittest.main()
