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

_EAGAIN = (11, 35, 10035)
# Búfer fijo de recepción: la última línea completa (un mensaje compacto son
# ~770 bytes), la que viene a medias y una lectura de _TROZO encima.
_TAMANO = 3072
_TROZO = 1024


def ahora_ms():
    try:
        return time.monotonic_ns() // 1000000
    except AttributeError:
        return int(time.monotonic() * 1000)


def _cargar(vista):
    """json.loads sin copiar la línea (CircuitPython acepta memoryview)."""
    try:
        return json.loads(vista)
    except TypeError:
        return json.loads(bytes(vista))       # CPython (pruebas en la PC)


class ClienteVision:
    def __init__(self, pool, host, port=2026, reconectar_s=1.0, conexion_s=0.5,
                 validar=True, reloj=ahora_ms, sin_datos_s=3.0):
        self.pool, self.host, self.port = pool, host, port
        self.reconectar_ms = int(reconectar_s * 1000)
        self.conexion_s = conexion_s
        self.validar, self.reloj = validar, reloj
        # telemetria.py son 4 KB de código en la RAM de Python, que crece
        # quitándole memoria al Wi-Fi (cancha 6-oct): sólo se carga si se pide.
        self._validate = None
        if validar:
            from telemetria import validate
            self._validate = validate
        # La visión publica a 20 Hz: varios segundos callada es una conexión
        # muerta aunque el socket no dé error (Wi-Fi caído sin aviso).
        self.sin_datos_ms = int(sin_datos_s * 1000)
        self.ultimo_dato_ms = None       # último byte recibido (o conexión abierta)
        # Último byte de verdad: el silencio que decide reiniciar el Wi-Fi.
        # Con ultimo_dato_ms, cada reconexión sin datos lo ponía en cero y la
        # placa nunca reiniciaba el Wi-Fi (cancha 4-oct: cortes de 1 minuto).
        self.ultimo_byte_ms = None
        # Cortes del flujo (sin datos o error) de los últimos segundos. Cancha
        # 5-oct, router y pilas nuevas: en plena ronda la placa deja de recibir
        # el flujo de la visión; cada conexión nueva trae unos pocos mensajes y
        # se vuelve a trabar (el 10 encadenó 10 conexiones en 55 s sin
        # reiniciarse, porque cada ráfaga reiniciaba el silencio). Sólo un
        # reinicio de la placa lo destraba: dos cortes seguidos bastan.
        self.cortes = []
        self.alguna_vez = False          # ya recibió algo: la visión existe
        self.sock = None
        # Búfer reservado una sola vez: [última línea completa][línea a medias].
        # Antes cada lectura armaba bytes nuevos (copia, concatenación, cortes
        # y decode): varios bloques de 1-3 KB por mensaje, 20 por segundo. Con
        # el montón fragmentado alguno no entraba, Python crecía y le quitaba
        # al Wi-Fi la memoria con la que recibe (cancha 6-oct: 8 KB libres).
        self.buf = bytearray(_TAMANO)
        self.vista = memoryview(self.buf)
        self.lleno = 0                   # bytes válidos en buf
        self.linea = None                # largo de la línea completa en buf[0:linea], sin usar
        self.cola = 0                    # dónde empieza la línea a medias
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
        self.lleno, self.linea, self.cola = 0, None, 0
        self.mensaje = None
        self.desfase_reloj = None
        self.estado = motivo
        if motivo != "wifi_reconectado":
            ahora = self.reloj()
            self.cortes = [t for t in self.cortes if ahora - t < 60000] + [ahora]
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
        for _ in range(8):
            try:
                n = self._recibir()
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
        if self.linea is None:
            return False
        # Sólo la línea completa más nueva (también la que dejó drenar()
        # mientras calculaba el A*); las anteriores ya se descartaron.
        return self._decodificar()

    def drenar(self):
        """Sólo vacía el socket, sin decodificar: lo llama el A* (rutas.ESPERA)
        en los cálculos largos para que el flujo de la visión no se trabe.
        Guarda la última línea completa y lo que venga después; poll() la usa."""
        if self.sock is None:
            return
        try:
            self._recibir()
        except OSError:
            return                                # nada nuevo o error: lo ve poll()

    def _recibir(self):
        """Lee un trozo directo al búfer fijo. Devuelve los bytes (0 = cerró)."""
        if _TAMANO - self.lleno < _TROZO:
            self._hacer_lugar()
        n = self.sock.recv_into(self.vista[self.lleno:self.lleno + _TROZO])
        if n:
            self.bytes += n
            self.ultimo_dato_ms = self.ultimo_byte_ms = self.reloj()
            self.alguna_vez = True
            self._agregar(n)
        return n

    def _agregar(self, n):
        """Llegaron n bytes al final: si cierran líneas, queda sólo la más nueva."""
        inicio = self.lleno
        self.lleno += n
        fin = self.buf.rfind(b"\n", inicio, self.lleno)
        if fin < 0:
            return
        previo = self.buf.rfind(b"\n", self.cola, fin)
        comienzo = previo + 1 if previo >= 0 else self.cola
        # Las completas anteriores a la más nueva se descartan sin decodificar.
        self.descartadas += self.buf.count(b"\n", self.cola, comienzo) + (self.linea is not None)
        largo = self.lleno - comienzo
        if comienzo:
            self.vista[0:largo] = self.vista[comienzo:self.lleno]
        self.linea, self.lleno = fin - comienzo, largo
        self.cola = self.linea + 1

    def _consumir(self):
        """La línea ya se usó: queda sólo la que viene a medias, al principio."""
        resto = self.lleno - self.cola
        if resto:
            self.vista[0:resto] = self.vista[self.cola:self.lleno]
        self.lleno, self.linea, self.cola = resto, None, 0

    def _hacer_lugar(self):
        if self.linea is not None:
            self.descartadas += 1             # detrás viene otra más nueva
            self._consumir()
        if _TAMANO - self.lleno < _TROZO:
            # Una línea a medias de más de 2 KB no es telemetría: se tira.
            self.lleno, self.cola = 0, 0
            self.errores_mensaje += 1

    # ------------------------------------------------------------ datos
    def _decodificar(self):
        t0 = self.reloj()
        try:
            mensaje = _cargar(self.vista[0:self.linea])
            t1 = self.reloj()
            if self._validate is not None:
                self._validate(mensaje)
        except Exception as error:
            self._consumir()
            self.errores_mensaje += 1
            self.estado = "mensaje_invalido: {}".format(error)
            return False
        self._consumir()
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

    def cortes_recientes(self, ventana_ms):
        """Cuántas veces se cortó el flujo en los últimos ventana_ms."""
        ahora = self.reloj()
        return sum(1 for t in self.cortes if ahora - t < ventana_ms)

    def reiniciar_silencio(self):
        self.ultimo_dato_ms = self.ultimo_byte_ms = self.reloj()
        self.cortes = []
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
