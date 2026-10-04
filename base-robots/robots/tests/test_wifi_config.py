"""Pruebas de la configuracion Wi-Fi sin hardware."""
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "codigos"))

from wifi_config import elegir_ap, obtener_credenciales_wifi


class Red:
    def __init__(self, ssid, bssid, rssi, channel):
        self.ssid, self.bssid, self.rssi, self.channel = ssid, bytes(bssid), rssi, channel


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

    def test_saved_open_network_boots_without_serial_input(self):
        config = {"wifi_ssid": "RedAbierta", "wifi_password": "",
                  "ask_wifi_on_boot": False}
        def unexpected_input(prompt):
            self.fail("Una red abierta no debe esperar USB: " + prompt)
        self.assertEqual(obtener_credenciales_wifi(config, unexpected_input),
                         ("RedAbierta", ""))

    def test_missing_or_null_password_still_requests_configuration(self):
        for config in ({"wifi_ssid": "Casa"},
                       {"wifi_ssid": "Casa", "wifi_password": None}):
            prompts = []
            def answer(prompt):
                prompts.append(prompt)
                return "clave-prueba"
            self.assertEqual(obtener_credenciales_wifi(config, answer),
                             ("Casa", "clave-prueba"))
            self.assertEqual(prompts, ["Password: "])

    def test_new_ssid_requests_password_even_if_previous_password_is_empty(self):
        answers = iter(("RedNueva", "clave-nueva"))
        config = {"wifi_ssid": "TU_RED_WIFI", "wifi_password": "",
                  "ask_wifi_on_boot": False}
        self.assertEqual(obtener_credenciales_wifi(config, lambda _: next(answers)),
                         ("RedNueva", "clave-nueva"))

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


class ElegirAntenaTests(unittest.TestCase):
    # Cancha 3-oct: la red de la U tiene varias antenas; el 10 quedó en el
    # canal 11 y el 11 en el 1, y ESP-NOW no cruzó en toda la ronda.
    A = bytes([1, 2, 3, 4, 5, 6])
    B = bytes([9, 9, 9, 9, 9, 9])
    C = bytes([5, 5, 5, 5, 5, 5])

    def test_both_rovers_pick_the_same_antenna_even_if_they_hear_them_differently(self):
        rover10 = [Red("U", self.A, -48, 11), Red("U", self.B, -66, 1), Red("Otra", self.C, -30, 6)]
        rover11 = [Red("U", self.A, -61, 11), Red("U", self.B, -52, 1)]
        self.assertEqual(elegir_ap(rover10, "U"), (self.B, 1))
        self.assertEqual(elegir_ap(rover11, "U"), (self.B, 1))

    def test_weak_antennas_are_ignored_and_strongest_wins_on_the_same_channel(self):
        redes = [Red("U", self.A, -85, 1), Red("U", self.B, -60, 6), Red("U", self.C, -50, 6),
                 Red("U", self.C, -70, 6)]                     # la misma vista dos veces
        self.assertEqual(elegir_ap(redes, "U"), (self.C, 6))

    def test_only_weak_antennas_takes_the_strongest_and_missing_network_gives_none(self):
        self.assertEqual(elegir_ap([Red("U", self.A, -85, 1), Red("U", self.B, -78, 11)], "U"), (self.B, 11))
        self.assertIsNone(elegir_ap([Red("Otra", self.A, -40, 1)], "U"))
        self.assertIsNone(elegir_ap([], "U"))
