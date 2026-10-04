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
from cliente_vision_rover import ClienteVision
from autonomia import IrAPunto, Misiones
from ronda import Ronda
from modelo_rover import ModeloRover


def _nada():
    pass


_memoria_red_vista = [False]


def _memoria_red():
    import gc
    gc.collect()
    if not _memoria_red_vista[0]:             # una vez por arranque: el registro va a la flash
        _memoria_red_vista[0] = True
        registro_fallos.guardar("memoria", "red_o_sesion")
    time.sleep(0.05)                          # si se repite, que no gire en vacío


def _sin_memoria(mision):
    """Sin RAM: juntar basura y cancelar lo que se movía, con un motivo fijo
    (armar un texto también pide memoria). La ronda sigue con otro cubo; antes
    esto tumbaba la placa entera (cancha 2-oct: MemoryError fatal en bucle)."""
    import gc
    gc.collect()
    mision.detener_mision("sin_memoria")


def _buscar_ap(wifi, ssid, alimentar):
    """(bssid, canal) elegido con elegir_ap, o None si no se pudo buscar."""
    from wifi_config import elegir_ap
    alimentar()
    try:
        redes = wifi.radio.start_scanning_networks()
        try:
            return elegir_ap(redes, ssid)
        finally:
            wifi.radio.stop_scanning_networks()
    except Exception as error:
        print("AVISO: no se pudo buscar antenas:", error)
        return None


def conectar_wifi(ssid, password, alimentar=_nada, forzar=False, elegir=True):
    import wifi

    if forzar:
        # La IP puede seguir puesta con el enlace caído: apagar y prender la
        # radio es la única forma segura de volver a asociarse.
        try:
            wifi.radio.enabled = False
            time.sleep(1)
            alimentar()
            wifi.radio.enabled = True
            time.sleep(1)
        except Exception as error:
            print("Error reiniciando Wi-Fi:", error)
    for intento in range(5):
        alimentar()
        try:
            print("Intentando conectar Wi-Fi...", intento + 1)

            if wifi.radio.ipv4_address is not None:
                print("Ya conectado:", wifi.radio.ipv4_address)
                return True

            # Los dos rovers en la misma antena (canal) para que ESP-NOW cruce.
            # Los dos últimos intentos, sin elegir: mejor conectado a
            # cualquiera que sin red.
            ap = _buscar_ap(wifi, ssid, alimentar) if elegir and intento < 3 else None
            if ap is None:
                wifi.radio.connect(ssid, password)
            else:
                print("Antena elegida:", ":".join("{:02x}".format(b) for b in ap[0]), "canal", ap[1])
                alimentar()
                wifi.radio.connect(ssid, password, channel=ap[1], bssid=ap[0])

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


def aplicar_rover(config, ruta="rover.json"):
    """Mezcla lo propio de ESTE rover (ID, ganancias, signos) sobre la config comun.

    config_robot.json lleva lo comun a los dos rovers (Wi-Fi, vision);
    rover.json, lo que cambia de uno a otro. La herramienta de subida copia
    rover_<id>.json como rover.json. Sin el archivo, todo queda como estaba.
    """
    try:
        with open(ruta) as fuente:
            propio = json.load(fuente)
    except OSError:
        print("AVISO: sin rover.json; ID", config.get("robot_id", 10), "por defecto")
        return config
    control = dict(config.get("control", {}))
    control.update(propio.get("control", {}))
    config.update(propio)
    config["control"] = control
    print("Rover", config.get("robot_id"), "(rover.json)")
    return config


def cargar_modelo(ruta="modelo_movimiento.json"):
    try:
        with open(ruta) as fuente:
            modelo = ModeloRover.desde_resumen(json.load(fuente)["resumen"])
        print("Modelo de movimiento cargado:", ruta)
        return modelo
    except (OSError, ValueError, KeyError) as error:
        print("AVISO: sin modelo calibrado ({}); valores por defecto".format(error))
        return ModeloRover()


def memoria_libre():
    try:
        import gc
        gc.collect()
        return gc.mem_free()
    except (ImportError, AttributeError):
        return None


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
    info=None,
    mission=None
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
            info=info,
            mission=mission
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
            # Una mision lanzada desde la PC no sobrevive a esa conexion; la
            # ronda autonoma no depende de ninguna PC (reglamento 11.2).
            if not getattr(mission, "autonoma", False):
                if mission is not None:
                    mission.detener("conexion_cerrada")
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

    vision = []  # se rellena al tener red; info() lo lee por referencia
    identidad = {}  # robot_id, al leer la config; la PC comprueba que es el rover que cree

    def info():
        datos = {"reset_reason": reinicio, "robot_id": identidad.get("robot_id"),
                 "uptime_s": round(time.monotonic() - arranque, 1),
                 "fallos": dict(fallos_previos, **registro_fallos.leer())}
        if vision:
            datos["vision"] = vision[0].estadisticas(memoria_libre())
        return datos

    controller = MotionController(robot)

    server = None
    hardware = None

    try:
        # ---------------------------------
        # Cargar configuración
        # ---------------------------------

        with open(config_path) as source:
            config = aplicar_rover(json.load(source))
        identidad["robot_id"] = config.get("robot_id", 10)

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
            password,
            elegir=config.get("wifi_elegir_antena", True)
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

        motivo_red = [None]

        def red_ok():
            if wifi.radio.ipv4_address is None:
                motivo_red[0] = "sin_ip"
                return False
            # Asociado al router (CircuitPython 9: None si se cayó el enlace).
            try:
                if wifi.radio.ap_info is None:
                    motivo_red[0] = "sin_router"
                    return False
            except (AttributeError, NotImplementedError):
                pass
            # La visión calla 20 s sin que ninguna PC esté conectada: lo más
            # probable es que el Wi-Fi se haya caído sin avisar (cancha 2-oct:
            # la placa quedó muda hasta apagarla y prenderla).
            if vision and not en_sesion[0]:
                silencio = vision[0].silencio_ms()
                if silencio is not None and silencio > 20000:
                    motivo_red[0] = "vision_callada"
                    return False
            return True

        pending = None
        revisado = -1e9
        alimentar = activar_watchdog(15)

        # Paso 1 del rover autonomo: leer la vision oficial desde la placa.
        # Solo mide; todavia no decide movimiento con lo que lee.
        if config.get("vision_host"):
            vision.append(ClienteVision(pool, config["vision_host"],
                                        config.get("vision_port", 2026)))
            print("Vision:", config["vision_host"], config.get("vision_port", 2026))
        informe = [time.monotonic() + 10]
        mision = None
        ronda = None
        en_sesion = [False]       # con la PC conectada, la sesion ya mueve sensores y motores
        if vision:
            # Un solo modelo: lo que una mision aprende (escalas) lo usa la otra.
            modelo = cargar_modelo()
            robot_id = config.get("robot_id", 10)

            def fabrica_llevar():
                # Al primer LLEVAR, no al arrancar: llevar_cubo.py es grande.
                import gc
                gc.collect()
                from llevar_cubo import LlevarCubo
                return LlevarCubo(vision[0], modelo, controller, robot_id, sensores=sensors)

            mision = Misiones(IrAPunto(vision[0], modelo, controller, robot_id),
                              fabrica_llevar=fabrica_llevar)
            # Incremento 3: la ronda arranca sola con la fase de la vision.
            ronda = Ronda(vision[0], mision, robot_id,
                          fase_inicio=config.get("fase_inicio", "RUNNING"),
                          estrategia=config.get("estrategia", "reparto"),
                          companero=config.get("companero_id"),
                          robar=config.get("robar", False))
            mision.ronda = ronda
            print("Ronda: arranca en fase", ronda.fase_inicio, "estrategia", ronda.estrategia)

        def tick():
            alimentar()
            if not en_sesion[0]:
                # Sin PC (la competencia): nadie mas actualiza sensores ni la
                # rampa de los motores. Con PC lo hace CommandSession.tick.
                if sensors is not None:
                    sensors.update(moving=controller.mode is not None or (
                        mision is not None and mision.activa))
                controller.update()
            if not vision:
                return
            try:
                vision[0].poll(puede_bloquear=controller.mode is None)
            except MemoryError:
                _sin_memoria(mision)
            except Exception as error:
                print("Error vision:", error)
            try:
                ronda.tick()
            except MemoryError:
                _sin_memoria(mision)
            except Exception as error:
                mision.detener_mision("error_ronda: {}".format(error))
                print("Error ronda:", error)
            try:
                mision.tick()
            except MemoryError:
                _sin_memoria(mision)
            except Exception as error:
                # Falla este cubo; la ronda sigue con el siguiente.
                mision.detener_mision("error: {}".format(error))
                print("Error mision:", error)
            if time.monotonic() >= informe[0]:
                informe[0] = time.monotonic() + 10
                print("Vision:", vision[0].estadisticas(memoria_libre()))
                vision[0].reiniciar_estadisticas()

        # ---------------------------------
        # Esperar clientes
        # ---------------------------------

        while True:
            try:
                tick()
                if pending is None:
                    if mision is None or not mision.activa:
                        controller.stop(
                            "esperando_cliente"
                        )

                    # Cada 2 s: si se cayo el Wi-Fi, reconectar y reabrir el puerto.
                    if server is None or time.monotonic() - revisado >= 2:
                        revisado = time.monotonic()
                        if server is None or not red_ok():
                            caida = server is not None
                            if server is not None:
                                print("Wi-Fi perdido; reconectando...", motivo_red[0])
                                try:
                                    registro_fallos.guardar("wifi", "perdido: {} a los {} s".format(
                                        motivo_red[0], round(time.monotonic() - arranque)))
                                except Exception:
                                    pass
                                # Sin red no hay vision: que nada se mueva a ciegas
                                # mientras se reconecta (la ronda sigue despues).
                                controller.stop("wifi_perdido")
                                if mision is not None:
                                    mision.detener_mision("wifi_perdido")
                                server.close()
                                server = None
                            if not conectar_wifi(ssid, password, alimentar, forzar=caida,
                                                 elegir=config.get("wifi_elegir_antena", True)):
                                time.sleep(2)
                                continue
                            if vision:
                                vision[0].reiniciar_silencio()    # 20 s más antes de volver a sospechar
                            if ronda is not None and config.get("espnow", True):
                                # ESP-NOW con el compañero, en el canal de este router.
                                if ronda.enlace is None:
                                    from enlace import Enlace
                                    from cliente_vision_rover import ahora_ms
                                    ronda.enlace = Enlace(ronda.robot_id, ahora_ms)
                                    print("ESP-NOW:", "activo" if ronda.enlace.activo else ronda.enlace.error)
                                elif caida:
                                    ronda.enlace.reiniciar()
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

                en_sesion[0] = True
                try:
                    pending = serve_client(
                        client,
                        controller,
                        config["watchdog_seconds"],
                        sensors=sensors,
                        server=server,
                        red_ok=red_ok,
                        alimentar=tick,
                        info=info,
                        mission=mision
                    )

                except MemoryError:
                    raise                 # lo atiende el bucle, sin armar textos
                except Exception as error:
                    print(
                        "Sesion cerrada:",
                        error
                    )
                    registro_fallos.guardar(
                        "sesion", "{}: {}".format(type(error).__name__, error))
                finally:
                    en_sesion[0] = False

            except MemoryError:
                # Sin RAM en la red (sockets, Wi-Fi: "Out of memory") o en la
                # sesion de la PC. Antes salia de main() y la placa se reiniciaba
                # a mitad de la ronda (cancha 2-oct). Se corta la conexion de la
                # PC y se sigue: la mision y la ronda no se tocan.
                pending = None
                en_sesion[0] = False
                _memoria_red()

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
