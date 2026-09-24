"""Pines del montaje del usuario. Nada se inicializa al importar."""
import time


class Sonar:
    """Captura Echo por PulseIn; poll nunca espera un eco en un bucle."""
    def __init__(self, trigger, echo):
        import digitalio
        import pulseio
        self.trigger = digitalio.DigitalInOut(trigger)
        self.trigger.switch_to_output(value=False)
        try:
            self.echo = pulseio.PulseIn(echo, maxlen=2, idle_state=False)
        except Exception:
            self.trigger.deinit()
            raise
        self.echo.pause()
        self.pending, self.started, self.next_ping = False, 0, 0

    def poll(self):
        now = time.monotonic()
        if self.pending:
            if len(self.echo):
                duration = self.echo[0]
                self.echo.pause()
                self.pending = False
                return True, duration * .1715
            if now - self.started >= .03:
                self.echo.pause()
                self.pending = False
                return True, None
        elif now >= self.next_ping:
            self.echo.clear()
            self.echo.resume()
            self.trigger.value = True
            time.sleep(.00001)
            self.trigger.value = False
            self.pending, self.started, self.next_ping = True, now, now + .08
        return False, None

    def deinit(self):
        self.echo.deinit()
        self.trigger.deinit()


class HardwareSensores:
    def __init__(self, cfg):
        import board
        import analogio
        import neopixel
        self.errors = {}
        self.warnings = []
        self.sonar = self.ir = self.light = self.pixel = None
        u, c = cfg["ultrasonic"], cfg["color"]
        try:
            diagnostic_override = (cfg.get("diagnostic_only") is True and
                                   u.get("allow_unverified_echo_diagnostic") is True)
            if u.get("echo_3v3_confirmed") is not True and not diagnostic_override:
                raise ValueError("Confirmar alimentacion HC-SR04 y adaptacion Echo a 3.3 V antes de activarlo")
            if u.get("echo_3v3_confirmed") is not True:
                self.warnings.append("Lectura de Echo solicitada con cableado sin verificar; el software NO protege de sobretension. Motores bloqueados.")
            self.sonar = Sonar(getattr(board, u["trigger"]), getattr(board, u["echo"]))
        except Exception as exc:
            self.errors["ultrasonic"] = str(exc)
        allocated = []
        try:
            for pin in cfg["ir"]["pins"]:
                allocated.append(analogio.AnalogIn(getattr(board, pin)))
            self.ir = allocated
        except Exception as exc:
            for item in allocated:
                item.deinit()
            self.errors["ir"] = str(exc)
        try:
            if c["analog"] != "IO33":
                raise ValueError("AO en IO4 usa ADC2 y no funciona con Wi-Fi en ESP32; confirmar AO a IO33 libre")
            self.light = analogio.AnalogIn(getattr(board, c["analog"]))
            self.pixel = neopixel.NeoPixel(getattr(board, c["led"]), 1, brightness=.3, auto_write=True)
            self.pixel[0] = (0, 0, 0)
        except Exception as exc:
            if self.light is not None:
                self.light.deinit()
                self.light = None
            self.errors["color"] = str(exc)

    def deinit(self):
        if self.pixel is not None:
            self.pixel[0] = (0, 0, 0)
        for device in [self.sonar, self.light, self.pixel] + (self.ir or []):
            if device is not None:
                device.deinit()
