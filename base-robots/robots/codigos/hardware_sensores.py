"""Pines del montaje del usuario. Nada se inicializa al importar."""
import math
import time


class Sonar:
    """Captura Echo por PulseIn; poll nunca espera un eco en un bucle."""
    def __init__(self, trigger, echo, timeout_ms=60, ping_interval_ms=80):
        import digitalio
        import microcontroller
        import pulseio
        if (isinstance(timeout_ms, bool) or not isinstance(timeout_ms, (int, float)) or
                isinstance(ping_interval_ms, bool) or
                not isinstance(ping_interval_ms, (int, float)) or
                not math.isfinite(timeout_ms) or not math.isfinite(ping_interval_ms) or
                timeout_ms <= 0 or ping_interval_ms <= 0):
            raise ValueError("Tiempos del ultrasonido deben ser positivos")
        self.trigger = digitalio.DigitalInOut(trigger)
        self.trigger.switch_to_output(value=False)
        try:
            self.echo = pulseio.PulseIn(echo, maxlen=2, idle_state=False)
        except Exception:
            self.trigger.deinit()
            raise
        self.echo.pause()
        self.delay_us = microcontroller.delay_us
        self.timeout_seconds = timeout_ms / 1000
        self.ping_interval_seconds = ping_interval_ms / 1000
        self.pending, self.started, self.next_ping = False, 0, 0

    def poll(self):
        now = time.monotonic()
        if self.pending:
            if len(self.echo):
                duration = self.echo[0]
                self.echo.pause()
                self.pending = False
                distance = duration * .1715
                return (True, distance) if 20 <= distance <= 4000 else (True, None)
            if now - self.started >= self.timeout_seconds:
                self.echo.pause()
                self.pending = False
                return True, None
        elif now >= self.next_ping:
            self.echo.clear()
            self.echo.resume()
            self.trigger.value = False
            self.delay_us(2)
            self.trigger.value = True
            self.delay_us(10)
            self.trigger.value = False
            self.pending = True
            self.started = now
            self.next_ping = now + self.ping_interval_seconds
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
            self.sonar = Sonar(
                getattr(board, u["trigger"]),
                getattr(board, u["echo"]),
                timeout_ms=u.get("timeout_ms", 60),
                ping_interval_ms=u.get("ping_interval_ms", 80),
            )
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
        # El LED primero y por separado: guarda el último color mientras tenga
        # corriente, aunque la placa se reinicie. Si algo del sensor fallaba
        # antes de apagarlo, quedaba encendido con el color de un barrido
        # viejo, y la cámara lo puede tomar por un cubo (rover 10, 3-oct).
        try:
            self.pixel = neopixel.NeoPixel(
                getattr(board, c["led"]), 1,
                brightness=c.get("brightness", 1), auto_write=False
            )
            self.pixel[0] = (0, 0, 0)
            self.pixel.show()
        except Exception as exc:
            self.pixel = None
            self.errors["color"] = str(exc)
        try:
            if c["analog"] != "IO33":
                raise ValueError("AO en IO4 usa ADC2 y no funciona con Wi-Fi en ESP32; confirmar AO a IO33 libre")
            self.light = analogio.AnalogIn(getattr(board, c["analog"]))
        except Exception as exc:
            self.light = None
            self.errors["color"] = str(exc)

    def deinit(self):
        if self.pixel is not None:
            self.pixel[0] = (0, 0, 0)
            self.pixel.show()
        for device in [self.sonar, self.light, self.pixel] + (self.ir or []):
            if device is not None:
                device.deinit()
