"""Sesión TCP de pruebas, independiente del hardware y con memoria acotada."""
import time
from command_protocol import parse_command, MAX_LINE


def would_block(error):
    # EAGAIN/EWOULDBLOCK en ESP32 y hosts usados para probar.
    return bool(error.args) and error.args[0] in (11, 35, 10035)


class CommandSession:
    def __init__(self, controller, watchdog=0.5, clock=time.monotonic):
        from command_protocol import finite
        if finite(watchdog) <= 0:
            raise ValueError("Watchdog debe ser positivo")
        self.controller, self.watchdog, self.clock = controller, watchdog, clock
        self.last_motion = None
        self.buffer = b""
        self.pending = b""
        self.rx = bytearray(128)
        self.controller.stop("nueva_conexion")

    def tick(self):
        if self.last_motion is not None and self.clock() - self.last_motion >= self.watchdog:
            self.controller.stop("watchdog")
            self.last_motion = None
        self.controller.update()

    def process_command(self, text):
        # Cobrar el vencimiento ANTES de aceptar una renovación tardía.
        self.tick()
        parsed = parse_command(text)
        if not parsed["valid"]:
            self.controller.stop("comando_invalido")
            self.last_motion = None
            return False
        command = parsed["command"]
        try:
            if command == "STOP":
                self.controller.stop()
                self.last_motion = None
            elif command == "PING":
                pass
            elif command == "KEEPALIVE":
                if self.controller.mode is None:
                    return False
                self.last_motion = self.clock()
            else:
                if command == "MOTOR":
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
            self.buffer += bytes(self.rx[:count])
            while b"\n" in self.buffer:
                raw, self.buffer = self.buffer.split(b"\n", 1)
                if len(raw) > MAX_LINE:
                    raise ValueError("Linea demasiado larga")
                valid = self.process_command(raw.decode("ascii"))
                self.pending += b"OK\n" if valid else b"ERROR\n"
                if len(self.pending) > 512:
                    raise ValueError("Cliente no lee respuestas")
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
