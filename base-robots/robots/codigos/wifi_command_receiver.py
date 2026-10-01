"""Servidor de comandos para banco de pruebas, CircuitPython + IdeaBoard.

Ejecutar main() desde code.py. No inicializa hardware al importar.

Configuración local en config_robot.json; ver robots/CORRECCIONES.md.
"""

import json
import time

from control_movimiento import MotionController, calibrate_drift
from sesion_comandos import CommandSession, would_block
from wifi_config import obtener_credenciales_wifi
import registro_fallos


def _nada():
    pass


def conectar_wifi(ssid, password, alimentar=_nada):
    import wifi

    for intento in range(5):
        alimentar()
        try:
            print("Intentando conectar Wi-Fi...", intento + 1)

            if wifi.radio.ipv4_address is not None:
                print("Ya conectado:", wifi.radio.ipv4_address)
                return True

            wifi.radio.connect(ssid, password)

            print("Conectado:", wifi.radio.ipv4_address)
            _sin_ahorro_energia(wifi)
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


def _sin_ahorro_energia(wifi):
    # El ahorro de energia del Wi-Fi mete retrasos de cientos de ms en los ACK.
    try:
        wifi.radio.power_management = wifi.PowerManagement.NONE
        print("Wi-Fi sin ahorro de energia")
    except (AttributeError, NotImplementedError, ValueError) as error:
        print("AVISO: no se pudo quitar el ahorro de energia del Wi-Fi:", error)


def activar_watchdog(segundos):
    """Reinicia la placa si el programa se cuelga (p. ej. I2C bloqueado).

    Sin esto un cuelgue deja el rover mudo hasta un reset manual. Devuelve la
    funcion que hay que llamar en cada vuelta del bucle.
    """
    try:
        import microcontroller
        from watchdog import WatchDogMode
        dog = microcontroller.watchdog
        dog.timeout = segundos
        dog.mode = WatchDogMode.RESET
        print("Watchdog de placa activo:", segundos, "s")
        return dog.feed
    except Exception as error:
        print("AVISO: watchdog de placa no disponible:", error)
        return _nada


def motivo_reinicio():
    try:
        import microcontroller
        return str(microcontroller.cpu.reset_reason).split(".")[-1]
    except Exception:
        return "DESCONOCIDO"


def aceptar(server):
    """Devuelve (cliente, direccion) o None si nadie espera conexion."""
    try:
        return server.accept()
    except OSError as error:
        if would_block(error):
            return None
        raise


def serve_client(
    client,
    controller,
    watchdog=0.5,
    clock=time.monotonic,
    sleep=time.sleep,
    sensors=None,
    server=None,
    red_ok=None,
    alimentar=_nada,
    info=None
):
    """Atiende un cliente. Devuelve el cliente que lo reemplaza, o None.

    Una conexion nueva desplaza a la actual: si la PC se fue sin cerrar
    (Wi-Fi caido, proceso matado), el rover no queda atado a un socket
    fantasma y la siguiente prueba puede entrar sin reiniciar la placa.
    """
    replacement = None
    try:
        client.setblocking(False)

        session = CommandSession(
            controller,
            watchdog,
            clock,
            sensors=sensors,
            info=info
        )

        revisado = clock()
        while session.poll(client):
            alimentar()
            if server is not None:
                replacement = aceptar(server)
                if replacement is not None:
                    print("Nuevo cliente reemplaza la sesion:", replacement[1])
                    break
            if red_ok is not None and clock() - revisado >= 1:
                revisado = clock()
                if not red_ok():
                    raise ConnectionError("Wi-Fi perdido durante la sesion")
            sleep(0.01)

    finally:
        try:
            controller.stop("conexion_cerrada")
        finally:
            client.close()
    return replacement


def abrir_servidor(pool, port):
    server = pool.socket(
        pool.AF_INET,
        pool.SOCK_STREAM
    )
    server.setsockopt(
        pool.SOL_SOCKET,
        pool.SO_REUSEADDR,
        1
    )
    server.bind(("0.0.0.0", port))
    server.listen(1)
    # No bloqueante: el bucle debe poder revisar el Wi-Fi mientras espera.
    server.setblocking(False)
    return server


def main(config_path="config_robot.json"):
    import board
    import socketpool
    import wifi

    from ideaboard import IdeaBoard

    robot = IdeaBoard()

    # Se envia a la PC en SENSORS: sin cable USB es la unica forma de saber
    # si el rover se reinicio por voltaje (BROWNOUT) o por cuelgue (WATCHDOG).
    reinicio = motivo_reinicio()
    arranque = time.monotonic()
    print("Motivo del ultimo reinicio:", reinicio)
    # Lo de antes de este arranque se informa una vez y se borra, para que
    # un BROWNOUT viejo no aparezca en todas las pruebas siguientes.
    fallos_previos = registro_fallos.leer()
    registro_fallos.borrar()

    def info():
        return {"reset_reason": reinicio,
                "uptime_s": round(time.monotonic() - arranque, 1),
                "fallos": dict(fallos_previos, **registro_fallos.leer())}

    controller = MotionController(robot)

    server = None
    hardware = None

    try:
        # ---------------------------------
        # Cargar configuración
        # ---------------------------------

        with open(config_path) as source:
            config = json.load(source)

        # Configuración separada: no sobrescribe Wi-Fi ni calibración de motores.
        from sensores_rover import SensoresRover, validar_config
        from hardware_sensores import HardwareSensores
        with open("config_sensores.json") as source:
            sensor_config = json.load(source)
        sensors = None
        if sensor_config.get("enabled", False):
            validar_config(sensor_config)
            hardware = HardwareSensores(sensor_config)
            sensors = SensoresRover(hardware, sensor_config)
            print("Sensores locales activos; errores de cableado/configuracion:", hardware.errors)
            if sensors.motion_inhibited:
                print("DIAGNOSTICO: motores bloqueados; solo lectura de sensores")
            for warning in hardware.warnings:
                print("AVISO:", warning)
        else:
            print("AVISO: sensores locales DESACTIVADOS por configuracion")

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
            safety=sensors,
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

        port = config["command_port"]
        # Un solo pool por radio; sigue valido tras reconectar el Wi-Fi.
        pool = socketpool.SocketPool(wifi.radio)

        def red_ok():
            return wifi.radio.ipv4_address is not None

        pending = None
        revisado = -1e9
        alimentar = activar_watchdog(15)

        # ---------------------------------
        # Esperar clientes
        # ---------------------------------

        while True:
            alimentar()
            if pending is None:
                controller.stop(
                    "esperando_cliente"
                )

                # Cada 2 s: si se cayo el Wi-Fi, reconectar y reabrir el puerto.
                if server is None or time.monotonic() - revisado >= 2:
                    revisado = time.monotonic()
                    if server is None or not red_ok():
                        if server is not None:
                            print("Wi-Fi perdido; reconectando...")
                            server.close()
                            server = None
                        if not conectar_wifi(ssid, password, alimentar):
                            time.sleep(2)
                            continue
                        server = abrir_servidor(pool, port)
                        print(
                            "Comandos de prueba:",
                            wifi.radio.ipv4_address,
                            port
                        )

                pending = aceptar(server)
                if pending is None:
                    time.sleep(0.05)
                    continue

            client, address = pending
            pending = None

            print(
                "Cliente conectado:",
                address
            )

            try:
                pending = serve_client(
                    client,
                    controller,
                    config["watchdog_seconds"],
                    sensors=sensors,
                    server=server,
                    red_ok=red_ok,
                    alimentar=alimentar,
                    info=info
                )

            except Exception as error:
                print(
                    "Sesion cerrada:",
                    error
                )
                registro_fallos.guardar(
                    "sesion", "{}: {}".format(type(error).__name__, error))

    finally:
        try:
            controller.stop(
                "servidor_detenido"
            )

        finally:
            if server is not None:
                server.close()
            try:
                # Para que un Ctrl+C por serial no acabe en reset a los 15 s.
                import microcontroller
                microcontroller.watchdog.deinit()
            except Exception:
                pass
            if hardware is not None:
                hardware.deinit()


if __name__ == "__main__":
    main()
