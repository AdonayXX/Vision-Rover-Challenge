"""Configuracion amigable de Wi-Fi para CircuitPython."""


_SSID_PLACEHOLDERS = ("", "TU_RED_WIFI")
_PASSWORD_PLACEHOLDERS = ("TU_PASSWORD",)


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
    Una contraseña guardada como "" es valida para una red abierta; no debe
    bloquear el arranque autonomo esperando una respuesta por USB.
    """

    ask_on_boot = config.get("ask_wifi_on_boot", False)
    if not isinstance(ask_on_boot, bool):
        raise ValueError("ask_wifi_on_boot debe ser true o false")

    configured_ssid = str(config.get("wifi_ssid", "")).strip()
    configured_password = str(config.get("wifi_password", ""))

    needs_ssid = ask_on_boot or configured_ssid in _SSID_PLACEHOLDERS
    needs_password = (needs_ssid or config.get("wifi_password") is None or
                      configured_password in _PASSWORD_PLACEHOLDERS)

    if needs_ssid or needs_password:
        print("\n=== Configuracion Wi-Fi del rover ===")

    ssid = configured_ssid
    password = configured_password

    if needs_ssid:
        ssid = _pedir_no_vacio("SSID: ", input_fn)

    if needs_password:
        password = input_fn("Password: ")

    return ssid, password


def elegir_ap(redes, ssid, umbral_dbm=-70):
    """Antena (bssid, canal) de la red a la que conectarse: la MISMA en los dos rovers.

    ESP-NOW sólo cruza entre rovers en el mismo canal, y en una red con varias
    antenas cada uno se colgaba de la que oía mejor (cancha 3-oct: el 10 en el
    canal 11 y el 11 en el 1; ninguno oyó al otro en toda la ronda). Regla que
    da lo mismo en los dos aunque midan distinto: entre las antenas con señal
    >= umbral, el canal más bajo y, en él, la más fuerte. Si ninguna llega al
    umbral, la más fuerte. None si la red no aparece (se conecta sin elegir).
    """
    vistas = {}
    for red in redes:
        try:
            if red.ssid != ssid:
                continue
            bssid = bytes(red.bssid)
            if bssid not in vistas or red.rssi > vistas[bssid][0]:
                vistas[bssid] = (red.rssi, red.channel)
        except (AttributeError, TypeError):
            continue
    if not vistas:
        return None
    buenas = [(canal, -rssi, bssid) for bssid, (rssi, canal) in vistas.items() if rssi >= umbral_dbm]
    if buenas:
        canal, _, bssid = min(buenas)
        return bssid, canal
    bssid = max(vistas, key=lambda b: vistas[b][0])
    return bssid, vistas[bssid][1]
