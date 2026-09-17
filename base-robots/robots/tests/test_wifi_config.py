"""Pruebas de la configuracion Wi-Fi sin hardware."""
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "codigos"))

from wifi_config import obtener_credenciales_wifi


class WifiConfigTests(unittest.TestCase):
    def test_uses_saved_credentials_when_prompt_is_disabled(self):
        config = {
            "wifi_ssid": "Casa",
            "wifi_password": "secreto",
            "ask_wifi_on_boot": False,
        }

        def unexpected_input(prompt):
            self.fail("No debio solicitar entrada: " + prompt)

        self.assertEqual(
            obtener_credenciales_wifi(config, unexpected_input),
            ("Casa", "secreto"),
        )

    def test_prompts_when_enabled(self):
        answers = iter(("RedNueva", "clave-nueva"))
        config = {
            "wifi_ssid": "Casa",
            "wifi_password": "secreto",
            "ask_wifi_on_boot": True,
        }

        self.assertEqual(
            obtener_credenciales_wifi(config, lambda prompt: next(answers)),
            ("RedNueva", "clave-nueva"),
        )

    def test_placeholders_trigger_prompt(self):
        answers = iter(("Hotspot", "12345678"))
        config = {
            "wifi_ssid": "TU_RED_WIFI",
            "wifi_password": "TU_PASSWORD",
            "ask_wifi_on_boot": False,
        }

        self.assertEqual(
            obtener_credenciales_wifi(config, lambda prompt: next(answers)),
            ("Hotspot", "12345678"),
        )

    def test_rejects_invalid_prompt_flag(self):
        with self.assertRaises(ValueError):
            obtener_credenciales_wifi({"ask_wifi_on_boot": "si"})


if __name__ == "__main__":
    unittest.main()
