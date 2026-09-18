"""Servidor de comandos para banco de pruebas, CircuitPython + IdeaBoard.

Ejecutar main() desde code.py. No inicializa hardware al importar.

Configuración local en config_robot.json; ver robots/CORRECCIONES.md.
"""

import json
import time

from control_movimiento import MotionController, calibrate_drift
from sesion_comandos import CommandSession, would_block
from wifi_config import obtener_credenciales_wifi


def conectar_wifi(ssid, password):
    import wifi

    for intento in range(5):
        try:
            print("Intentando conectar Wi-Fi...", intento + 1)

            if wifi.radio.ipv4_address is not None:
                print("Ya conectado:", wifi.radio.ipv4_address)
                return True

            wifi.radio.connect(ssid, password)

            print("Conectado:", wifi.radio.ipv4_address)
            return True

        except ConnectionError as error:
            print("Error Wi-Fi:", error)

            try:
                wifi.radio.enabled = False
                time.sleep(1)

                wifi.radio.enabled = True
                time.sleep(2)

            except Exception as radio_error:
                print("Error reiniciando Wi-Fi:", radio_error)

    print("No se pudo conectar al Wi-Fi")
    return False


def serve_client(
    client,
    controller,
    watchdog=0.5,
    clock=time.monotonic,
    sleep=time.sleep
):
    try:
        client.setblocking(False)

        session = CommandSession(
            controller,
            watchdog,
            clock
        )

        while session.poll(client):
            sleep(0.01)

    finally:
        try:
            controller.stop("conexion_cerrada")
        finally:
            client.close()


def main(config_path="config_robot.json"):
    import board
    import socketpool
    import wifi

    from ideaboard import IdeaBoard

    robot = IdeaBoard()

    controller = MotionController(robot)

    server = None

    try:
        # ---------------------------------
        # Cargar configuración
        # ---------------------------------

        with open(config_path) as source:
            config = json.load(source)

        use_imu = config.get("use_imu", True)

        if not isinstance(use_imu, bool):
            raise ValueError(
                "use_imu debe ser true o false"
            )

        # ---------------------------------
        # IMU
        # ---------------------------------

        sensor = None
        drift = 0

        if use_imu:
            from adafruit_lsm6ds.lsm6ds3trc import LSM6DS3TRC

            sensor = LSM6DS3TRC(
                board.I2C(),
                config["imu_address"]
            )

            drift = calibrate_drift(sensor)

        # ---------------------------------
        # Movimiento
        # ---------------------------------

        controller = MotionController(
            robot,
            sensor,
            drift,
            **config["control"]
        )

        # Validar watchdog
        CommandSession(
            controller,
            config["watchdog_seconds"]
        )

        # ---------------------------------
        # Wi-Fi
        # ---------------------------------

        time.sleep(2)

        ssid, password = obtener_credenciales_wifi(config)

        conectado = conectar_wifi(
            ssid,
            password
        )

        if not conectado:
            raise RuntimeError(
                "No se pudo conectar al Wi-Fi"
            )

        # ---------------------------------
        # Servidor TCP
        # ---------------------------------

        pool = socketpool.SocketPool(wifi.radio)

        server = pool.socket(
            pool.AF_INET,
            pool.SOCK_STREAM
        )

        server.setsockopt(
            pool.SOL_SOCKET,
            pool.SO_REUSEADDR,
            1
        )

        server.bind(
            (
                "0.0.0.0",
                config["command_port"]
            )
        )

        server.listen(1)

        print(
            "Comandos de prueba:",
            wifi.radio.ipv4_address,
            config["command_port"]
        )

        # ---------------------------------
        # Esperar clientes
        # ---------------------------------

        while True:
            controller.stop(
                "esperando_cliente"
            )

            try:
                client, address = server.accept()

            except OSError as error:
                if would_block(error):
                    time.sleep(0.05)
                    continue
                raise

            print(
                "Cliente conectado:",
                address
            )

            try:
                serve_client(
                    client,
                    controller,
                    config["watchdog_seconds"]
                )

            except Exception as error:
                print(
                    "Sesion cerrada:",
                    error
                )

    finally:
        try:
            controller.stop(
                "servidor_detenido"
            )

        finally:
            if server is not None:
                server.close()


if __name__ == "__main__":
    main()
