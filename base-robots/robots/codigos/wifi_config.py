"""Configuracion amigable de Wi-Fi para CircuitPython."""


_SSID_PLACEHOLDERS = ("", "TU_RED_WIFI")
_PASSWORD_PLACEHOLDERS = ("", "TU_PASSWORD")


def _pedir_no_vacio(prompt, input_fn):
    while True:
        value = input_fn(prompt).strip()
        if value:
            return value
        print("El valor no puede quedar vacio.")


def obtener_credenciales_wifi(config, input_fn=input):
    """Devuelve (ssid, password), preguntando por serial cuando corresponde.

    Si ``ask_wifi_on_boot`` es true se preguntan siempre las credenciales.
    Tambien se preguntan automaticamente cuando el JSON conserva los valores
    de ejemplo, para evitar intentar conectarse a ``TU_RED_WIFI``.
    """

    ask_on_boot = config.get("ask_wifi_on_boot", False)
    if not isinstance(ask_on_boot, bool):
        raise ValueError("ask_wifi_on_boot debe ser true o false")

    configured_ssid = str(config.get("wifi_ssid", "")).strip()
    configured_password = str(config.get("wifi_password", ""))

    needs_ssid = ask_on_boot or configured_ssid in _SSID_PLACEHOLDERS
    needs_password = ask_on_boot or configured_password in _PASSWORD_PLACEHOLDERS

    if needs_ssid or needs_password:
        print("\n=== Configuracion Wi-Fi del rover ===")

    ssid = configured_ssid
    password = configured_password

    if needs_ssid:
        ssid = _pedir_no_vacio("SSID: ", input_fn)

    if needs_password:
        password = input_fn("Password: ")

    return ssid, password
