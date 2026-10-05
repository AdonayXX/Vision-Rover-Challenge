"""Cliente de telemetria de vision que corre EN la placa (CircuitPython).

Reglamento 6.3 y 7.8: tras READY ninguna computadora externa puede decidir ni
mandar movimiento, asi que el rover lee la vision oficial directamente.

Contrato 6.3 y reglamento 7.9: se lee todo lo disponible, se conserva SOLO la
linea completa mas nueva y se descartan las anteriores; nunca se decodifica
una cola de estados viejos.

Reloj: el ESP32 no tiene la hora de la computadora de vision, asi que
`ahora - ts_ms` no da la edad absoluta (contrato 6.4). Se estima el desfase
con el minimo de (llegada local - ts_ms) y se informa la edad RELATIVA a la
entrega mas rapida observada: su variacion si es fiable.

El pool se inyecta; no importa nada de CircuitPython y se prueba en la PC.
"""
import json
import time

from telemetria import validate

_EAGAIN = (11, 35, 10035)
_BUFFER_MAX = 8192


def ahora_ms():
    try:
        return time.monotonic_ns() // 1000000
    except AttributeError:
        return int(time.monotonic() * 1000)


class ClienteVision:
    def __init__(self, pool, host, port=2026, reconectar_s=1.0, conexion_s=0.5,
                 validar=True, reloj=ahora_ms, sin_datos_s=3.0):
        self.pool, self.host, self.port = pool, host, port
        self.reconectar_ms = int(reconectar_s * 1000)
        self.conexion_s = conexion_s
        self.validar, self.reloj = validar, reloj
        # La visión publica a 20 Hz: varios segundos callada es una conexión
        # muerta aunque el socket no dé error (Wi-Fi caído sin aviso).
        self.sin_datos_ms = int(sin_datos_s * 1000)
        self.ultimo_dato_ms = None       # último byte recibido (o conexión abierta)
        # Último byte de verdad: el silencio que decide reiniciar el Wi-Fi.
        # Con ultimo_dato_ms, cada reconexión sin datos lo ponía en cero y la
        # placa nunca reiniciaba el Wi-Fi (cancha 4-oct: cortes de 1 minuto).
        self.ultimo_byte_ms = None
        self.alguna_vez = False          # ya recibió algo: la visión existe
        self.sock = None
        self.buffer = b""
        self.rx = bytearray(1024)
        self.proximo_intento = 0
        self.mensaje = None
        self.recibido_ms = None
        self.estado = "sin_conexion"
        # Desfase local - ts_ms de la entrega mas rapida. A diferencia del de
        # las estadisticas, no se reinicia por ventana: lo usa el control.
        self.desfase_reloj = None
        self.reiniciar_estadisticas()
        self.conexiones = 0

    # ------------------------------------------------------------ red
    def _cerrar(self, motivo):
        if self.sock is not None:
            try:
                self.sock.close()
            except Exception:
                pass
        self.sock = None
        self.buffer = b""
        self.mensaje = None
        self.desfase_reloj = None
        self.estado = motivo
        self.proximo_intento = self.reloj() + self.reconectar_ms

    def _conectar(self):
        sock = self.pool.socket(self.pool.AF_INET, self.pool.SOCK_STREAM)
        try:
            # Bloquea como mucho conexion_s: solo se llama con motores parados.
            sock.settimeout(self.conexion_s)
            sock.connect((self.host, self.port))
            sock.setblocking(False)
        except Exception as error:
            try:
                sock.close()
            except Exception:
                pass
            self.errores_conexion += 1
            self.estado = "conexion_fallida: {}".format(error)
            self.proximo_intento = self.reloj() + self.reconectar_ms
            return False
        self.sock = sock
        self.conexiones += 1
        self.estado = "conectado"
        self.ultimo_dato_ms = self.reloj()
        return True

    def poll(self, puede_bloquear=True):
        """Devuelve True si se decodifico un mensaje nuevo en esta llamada.

        puede_bloquear=False impide (re)conectar: conectar bloquea hasta
        conexion_s y, con motores en marcha, frenaria el bucle de control.
        """
        if self.sock is None:
            if not puede_bloquear or self.reloj() < self.proximo_intento:
                return False
            if not self._conectar():
                return False
        ultima = None
        for _ in range(8):
            try:
                n = self.sock.recv_into(self.rx)
            except OSError as error:
                if error.args and error.args[0] in _EAGAIN:
                    if self.reloj() - self.ultimo_dato_ms > self.sin_datos_ms:
                        self._cerrar("vision_sin_datos")
                        return False
                    break
                self._cerrar("error_red: {}".format(error))
                return False
            if n == 0:
                self._cerrar("vision_cerro_conexion")
                return False
            self.bytes += n
            self.ultimo_dato_ms = self.ultimo_byte_ms = self.reloj()
            self.alguna_vez = True
            self.buffer += bytes(self.rx[:n])
            fin = self.buffer.rfind(b"\n")
            if fin >= 0:
                completas = self.buffer[:fin]
                self.buffer = self.buffer[fin + 1:]
                inicio = completas.rfind(b"\n")
                # Las lineas anteriores a la ultima se descartan sin decodificar.
                self.descartadas += completas.count(b"\n") + (ultima is not None)
                ultima = completas[inicio + 1:] if inicio >= 0 else completas
            if len(self.buffer) > _BUFFER_MAX:
                self.buffer = b""
                self.errores_mensaje += 1
        if ultima is None:
            return False
        return self._decodificar(ultima)

    # ------------------------------------------------------------ datos
    def _decodificar(self, linea):
        t0 = self.reloj()
        try:
            mensaje = json.loads(linea.decode("utf-8"))
            t1 = self.reloj()
            if self.validar:
                validate(mensaje)
        except Exception as error:
            self.errores_mensaje += 1
            self.estado = "mensaje_invalido: {}".format(error)
            return False
        t2 = self.reloj()
        if self.mensaje is not None and mensaje["seq"] <= self.mensaje["seq"]:
            self.errores_mensaje += 1
            return False
        if self.mensaje is not None:
            self.saltos_seq += mensaje["seq"] - self.mensaje["seq"] - 1
        self.mensaje, self.recibido_ms = mensaje, t2
        self.estado = "ok"
        self.decodificados += 1
        self.json_ms_total += t1 - t0
        self.json_ms_max = max(self.json_ms_max, t1 - t0)
        self.validar_ms_total += t2 - t1
        self.validar_ms_max = max(self.validar_ms_max, t2 - t1)
        desfase = t2 - mensaje["ts_ms"]
        if self.desfase_reloj is None or desfase < self.desfase_reloj:
            self.desfase_reloj = desfase
        if self.desfase_min is None or desfase < self.desfase_min:
            self.desfase_min = desfase
        edad = desfase - self.desfase_min
        self.edad_total += edad
        self.edad_max = max(self.edad_max, edad)
        return True

    def silencio_ms(self):
        """Hace cuánto no llega nada de la visión (None si nunca llegó nada)."""
        if not self.alguna_vez or self.ultimo_byte_ms is None:
            return None
        return self.reloj() - self.ultimo_byte_ms

    def reiniciar_silencio(self):
        self.ultimo_dato_ms = self.ultimo_byte_ms = self.reloj()
        if self.sock is not None:
            self._cerrar("wifi_reconectado")     # ese socket era de la red anterior

    def edad_relativa_ms(self):
        """Edad del ultimo mensaje respecto de la entrega mas rapida vista."""
        if self.mensaje is None or self.desfase_min is None:
            return None
        return self.reloj() - self.mensaje["ts_ms"] - self.desfase_min

    # ------------------------------------------------------------ medida
    def reiniciar_estadisticas(self):
        self.desde_ms = self.reloj()
        self.bytes = self.decodificados = self.descartadas = self.saltos_seq = 0
        self.errores_mensaje = self.errores_conexion = 0
        self.json_ms_total = self.json_ms_max = 0
        self.validar_ms_total = self.validar_ms_max = 0
        self.edad_total = self.edad_max = 0
        # Se reinicia por ventana: corrige la deriva entre ambos relojes.
        self.desfase_min = None

    def estadisticas(self, memoria_libre=None):
        segundos = max(.001, (self.reloj() - self.desde_ms) / 1000)
        n = max(1, self.decodificados)
        datos = {
            # Con host: un vision_host viejo en la config se ve en ver_ronda
            # (cancha 4-oct: fase=None dos rondas, sin saber por qué).
            "host": self.host, "estado": self.estado, "conexiones": self.conexiones,
            "segundos": round(segundos, 1),
            "hz_decodificados": round(self.decodificados / segundos, 1),
            "descartadas": self.descartadas, "saltos_seq": self.saltos_seq,
            "kb_s": round(self.bytes / 1024 / segundos, 1),
            "json_ms": [round(self.json_ms_total / n, 1), self.json_ms_max],
            "validar_ms": [round(self.validar_ms_total / n, 1), self.validar_ms_max],
            "edad_rel_ms": [round(self.edad_total / n), self.edad_max],
            "errores": [self.errores_mensaje, self.errores_conexion],
        }
        if memoria_libre is not None:
            datos["mem_libre"] = memoria_libre
        return datos
