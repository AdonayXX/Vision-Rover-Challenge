"""ESP-NOW entre los dos rovers (reglamento 4.2.6, 7.2-7.6; robot.md).

Cada rover difunde unas veces por segundo un mensaje corto con su estado (qué
cubo lleva, su lista, cuántos entregó). No hay pregunta-respuesta ni
coordinador: si un mensaje se pierde llega el siguiente, y si la radio calla
la ronda sigue como sin ella (reparto calculado por cada uno).

Va por difusión en el canal del router de la visión: así no hace falta
conocer la MAC del otro ni sacar la radio de la red (el ejemplo de la U fija
el canal con un punto de acceso, que desconectaría el Wi-Fi). La MAC del
compañero se aprende con su primer mensaje válido y después sólo se le cree
a esa: otros equipos pueden tener rovers encendidos cerca con los mismos IDs.
"""
import json

ETIQUETA = "VRC-AD1"            # distingue nuestros mensajes de cualquier otro
_DIFUSION = bytes([255] * 6)


class Enlace:
    def __init__(self, robot_id, reloj, radio=None, buffer=1536):
        self.robot_id, self.reloj = robot_id, reloj
        # El de fábrica (526 bytes) son tres mensajes nuestros: con el bucle
        # ocupado un rato (A*, red) se llenaba.
        self.buffer = buffer
        self.reaperturas = 0            # veces que se reabrió por "Invalid buffer"
        self._reabierta_ms = None
        self.tx = self.rx = self.errores = 0
        self.ajenos = 0                 # paquetes ESP-NOW que no son nuestros (otro equipo)
        self.ultimo_error = None        # para saber QUÉ falla, no sólo cuántas veces
        self.compa = None               # último estado válido del compañero
        self.compa_ms = None            # cuándo llegó (reloj de esta placa)
        self.mac = None
        self.error = None
        self._esp = self._peer = None
        if radio is not None:           # pruebas: una radio simulada
            self._esp = radio
        else:
            self._abrir()

    def _abrir(self):
        try:
            import espnow
            self._esp = espnow.ESPNow(buffer_size=self.buffer)
            # Canal 0 = el actual: el del router al que está conectado el Wi-Fi.
            self._peer = espnow.Peer(mac=_DIFUSION, channel=0)
            self._esp.peers.append(self._peer)
            self.error = None
        except Exception as error:      # sin espnow (PC) o radio ocupada
            self._esp = None
            self.error = "{}: {}".format(type(error).__name__, error)

    def reiniciar(self):
        """Tras apagar y prender la radio Wi-Fi, ESP-NOW se vuelve a abrir."""
        if self._esp is not None and self._peer is None:
            reabrir = getattr(self._esp, "reabrir", None)   # radio simulada
            if reabrir is not None:
                reabrir()
            return
        if self._esp is not None:
            try:
                self._esp.deinit()
            except Exception:
                pass
            self._esp = None
        self._abrir()

    @property
    def activo(self):
        return self._esp is not None

    def enviar(self, datos):
        if self._esp is None:
            return
        datos["t"], datos["id"] = ETIQUETA, self.robot_id
        try:
            self._esp.send(json.dumps(datos).encode("utf-8"), self._peer)
            self.tx += 1
        except Exception as error:
            self.errores += 1
            self.ultimo_error = "envio {}: {}".format(type(error).__name__, error)

    def recibir(self):
        """Vacía lo recibido; se queda con el último mensaje del compañero."""
        if self._esp is None:
            return
        for _ in range(8):
            try:
                paquete = self._esp.read()
            except Exception as error:
                self.errores += 1
                self.ultimo_error = "{}: {}".format(type(error).__name__, error)
                if isinstance(error, ValueError):
                    # CircuitPython 9: el búfer circular de ESP-NOW queda
                    # desalineado ("Invalid buffer") y desde ahí casi todo
                    # read() falla: radio muda el resto de la ronda (cancha
                    # 3-oct, los dos rovers). Reabrirlo lo vacía.
                    ahora = self.reloj()
                    if self._reabierta_ms is None or ahora - self._reabierta_ms >= 2000:
                        self._reabierta_ms = ahora
                        self.reaperturas += 1
                        self.reiniciar()
                return
            if paquete is None:
                return
            try:
                datos = json.loads(bytes(paquete.msg).decode("utf-8"))
            except Exception:
                self.ajenos += 1
                continue
            if not isinstance(datos, dict) or datos.get("t") != ETIQUETA:
                self.ajenos += 1
                continue
            if datos.get("id") == self.robot_id:
                continue
            mac = bytes(paquete.mac)
            if self.mac is None:
                self.mac = mac
            elif mac != self.mac:
                continue                # mismo protocolo pero otro aparato
            self.compa, self.compa_ms = datos, self.reloj()
            self.rx += 1

    def companero(self, max_edad_ms=1500):
        """Estado del compañero si es reciente; si no, None (radio caída)."""
        if self.compa is None or self.reloj() - self.compa_ms > max_edad_ms:
            return None
        return self.compa

    def informe(self):
        datos = {"tx": self.tx, "rx": self.rx}
        if self.compa_ms is not None:
            datos["edad_ms"] = self.reloj() - self.compa_ms
            datos["compa"] = self.compa.get("id")
        if self.errores:
            datos["errores"] = self.errores
            datos["ultimo_error"] = self.ultimo_error
        if self.ajenos:
            datos["ajenos"] = self.ajenos
        if self.reaperturas:
            datos["reaperturas"] = self.reaperturas
        if self.error:
            datos["error"] = self.error
        # ESP-NOW sólo cruza si los dos están en el mismo canal: en una red
        # con varios puntos de acceso cada rover puede quedar en uno distinto.
        try:
            import wifi
            datos["canal"] = wifi.radio.ap_info.channel
        except Exception:
            pass
        return datos
