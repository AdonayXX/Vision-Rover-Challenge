"""Sesión TCP de pruebas, independiente del hardware y con memoria acotada."""
import time
import json
from command_protocol import parse_command, MAX_LINE


def would_block(error):
    # EAGAIN/EWOULDBLOCK en ESP32 y hosts usados para probar.
    return bool(error.args) and error.args[0] in (11, 35, 10035)


class CommandSession:
    def __init__(self, controller, watchdog=0.5, clock=time.monotonic, sensors=None, info=None,
                 mission=None):
        from command_protocol import finite
        if finite(watchdog) <= 0:
            raise ValueError("Watchdog debe ser positivo")
        self.controller, self.watchdog, self.clock = controller, watchdog, clock
        self.sensors = sensors
        self.info = info  # callable -> dict: motivo del ultimo reinicio, uptime
        self.mission = mission  # mision autonoma en la placa (autonomia.IrAPunto)
        self.reply = b"OK\n"
        self.last_motion = None
        self.buffer = b""
        self.pending = b""
        self.rx = bytearray(128)
        self.ultimo_rx = clock()  # la PC habló por última vez (o se conectó)
        # Durante una ronda autonoma la PC solo puede mirar: conectarse no
        # para el rover (un STOP explicito si).
        if not getattr(mission, "autonoma", False):
            self.controller.stop("nueva_conexion")

    def tick(self):
        if self.last_motion is not None and self.clock() - self.last_motion >= self.watchdog:
            self.controller.stop("watchdog")
            self.last_motion = None
        if self.sensors is not None:
            # Con una mision activa el LED del sensor de color no barre: sus
            # destellos rojo/verde/azul sobre el cubo pueden confundir a la
            # camara, y la mision no usa ese sensor (reglamento 12.4).
            ocupado = self.controller.mode is not None or (
                self.mission is not None and self.mission.activa)
            self.sensors.update(moving=ocupado)
        self.controller.update()

    def process_command(self, text):
        # Cobrar el vencimiento ANTES de aceptar una renovación tardía.
        self.tick()
        self.reply = b"OK\n"
        parsed = parse_command(text)
        if not parsed["valid"]:
            self.controller.stop("comando_invalido")
            self.last_motion = None
            return False
        command = parsed["command"]
        if self.mission is not None and command in ("STOP", "MOTOR", "TURN", "HEADING"):
            # Una orden manual siempre le quita el control a la mision.
            self.mission.detener("orden_" + command.lower())
        try:
            if command == "RUTA":
                if self.mission is None:
                    return False
                # Planificar bloquea el bucle: solo con los motores parados.
                self.mission.detener("medicion_ruta")
                self.controller.stop("medicion_ruta")
                self.last_motion = None
                try:
                    from rutas_placa import medir_ruta
                    resultado = medir_ruta(self.mission.vision.mensaje, self.mission.robot_id,
                                           parsed["col"], parsed["row"], int(parsed["paso"]))
                except Exception as error:
                    # Una medicion que falla se informa; no tumba la sesion.
                    resultado = {"error": "{}: {}".format(type(error).__name__, error)}
                self.reply = (json.dumps(resultado) + "\n").encode("ascii")
            elif command == "IR":
                if self.mission is None:
                    return False
                self.controller.stop("mision")
                self.last_motion = None
                self.mission.iniciar(parsed["col"], parsed["row"])
            elif command == "LLEVAR":
                if self.mission is None or not hasattr(self.mission, "llevar"):
                    return False
                self.controller.stop("mision")
                self.last_motion = None
                self.mission.llevar(parsed["color"])
            elif command == "STOP":
                self.controller.stop()
                self.last_motion = None
            elif command == "PING":
                pass
            elif command == "SENSORS":
                status = self.sensors.snapshot() if self.sensors is not None else {"v": 1, "enabled": False}
                status["motion_reason"] = self.controller.reason
                if self.info is not None:
                    status.update(self.info())
                if self.mission is not None:
                    status["mision"] = self.mission.informe()
                # Compacto: es la respuesta más grande (2-3 KB, una por segundo
                # con ver_ronda) y cada copia pide un bloque seguido de memoria.
                self.reply = (json.dumps(status, separators=(",", ":")) + "\n").encode("ascii")
            elif command == "KEEPALIVE":
                if self.controller.mode is None:
                    return False
                self.last_motion = self.clock()
            else:
                if command == "MOTOR":
                    if self.sensors is not None:
                        reason = self.sensors.reason(parsed["left"], parsed["right"])
                        if reason:
                            self.controller.stop(reason)
                            self.last_motion = None
                            return False
                    self.controller.start_motor(parsed["left"], parsed["right"])
                elif command == "TURN":
                    self.controller.start_turn(parsed["angle"], parsed["speed"])
                elif command == "HEADING":
                    self.controller.start_heading(parsed["heading"], parsed["speed"], parsed["duration"])
                self.last_motion = self.clock()
            return True
        except (ValueError, TypeError):
            self.controller.stop("comando_invalido")
            self.last_motion = None
            return False

    def poll(self, client):
        """Una lectura y una escritura por ciclo; EOF/errores detienen y cierran."""
        try:
            return self._poll(client)
        except BaseException:
            self.controller.stop("error_sesion")
            raise

    def _poll(self, client):
        self.tick()
        try:
            count = client.recv_into(self.rx)
        except OSError as error:
            if not would_block(error):
                raise
            count = None
        if count == 0:
            self.controller.stop("desconexion")
            return False
        if count:
            self.ultimo_rx = self.clock()
            self.buffer += bytes(self.rx[:count])
            while b"\n" in self.buffer:
                raw, self.buffer = self.buffer.split(b"\n", 1)
                if len(raw) > MAX_LINE:
                    raise ValueError("Linea demasiado larga")
                valid = self.process_command(raw.decode("ascii"))
                response = self.reply if valid else b"ERROR\n"
                if len(response) > 8192 or len(self.pending) + len(response) > max(512, len(response)):
                    raise ValueError("Cliente no lee respuestas")
                self.pending += response
                if not valid:
                    # Descartar las órdenes que llegaron detrás de una inválida.
                    self.buffer = b""
                    break
            if len(self.buffer) > MAX_LINE:
                raise ValueError("Linea incompleta demasiado larga")
        if self.pending:
            try:
                sent = client.send(self.pending)
                if sent == 0:
                    raise OSError("Conexion sin progreso de escritura")
                self.pending = self.pending[sent:]
            except OSError as error:
                if not would_block(error):
                    raise
        self.tick()
        return True
