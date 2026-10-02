"""Control autónomo EN la placa: ir a un punto con control continuo.

Incremento 1 del rover autónomo. Cada 50 ms:
  1. toma la última pose que publicó la visión (cliente_vision_rover),
  2. la adelanta con las órdenes ya emitidas (modelo_rover.Predictor),
  3. calcula potencias continuas hacia el objetivo y las aplica.
No hay pulsos ni esperas por imagen nueva: la visión corrige la predicción.

Seguridad: si la imagen pasa de `max_edad_ms` el rover se detiene y espera;
si no vuelve en `espera_max_ms`, la misión se aborta. Al llegar, se detiene y
VERIFICA con una imagen tomada después de parar antes de darse por llegado.
"""
import math

from cliente_vision_rover import ahora_ms
from modelo_rover import Predictor

INACTIVO = "INACTIVO"
EN_CAMINO = "EN_CAMINO"
ESPERANDO_VISION = "ESPERANDO_VISION"
VERIFICANDO = "VERIFICANDO"
LLEGO = "LLEGO"
ABORTADO = "ABORTADO"


def _norma(x, y):
    # math.hypot no esta garantizado en CircuitPython.
    return math.sqrt(x * x + y * y)


def distancia_a_segmento(p, a, b):
    dx, dy = b[0] - a[0], b[1] - a[1]
    largo = dx * dx + dy * dy
    t = 0.0 if largo == 0 else max(0.0, min(1.0, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / largo))
    return _norma(p[0] - a[0] - t * dx, p[1] - a[1] - t * dy)


def obstaculo_en_camino(mensaje, desde, hasta, radio_rover_mm=85.0, holgura_mm=10.0,
                        excluir=None, propio=None):
    """Primer cubo u obstaculo que el CUERPO del rover tocaria en el tramo recto.

    Es la red de seguridad: si algo estorba, el rover se detiene en vez de
    empujarlo. `excluir`: color del cubo que se empuja a proposito. Con
    `propio` (id de este rover) tambien cuenta el otro rover.
    """
    cell = mensaje["grid"]["cell_mm"]
    a, b = (desde["col"], desde["row"]), (hasta["col"], hasta["row"])
    medio_cubo = mensaje["cube_side"] * cell * 0.7072
    grupos = (("cubes", "cubo", medio_cubo), ("obstacles", "obstaculo", medio_cubo))
    if propio is not None:
        grupos += (("rovers", "rover", radio_rover_mm),)
    for grupo, nombre, medio in grupos:
        for item in mensaje.get(grupo, ()):
            if grupo == "cubes" and item["color"] == excluir:
                continue
            if grupo == "rovers" and item["id"] == propio:
                continue
            libre = radio_rover_mm + holgura_mm + medio
            if distancia_a_segmento((item["col"], item["row"]), a, b) * cell < libre:
                return nombre + (" " + item["color"] if "color" in item else "")
    return None


def giro_corto(grados):
    return (grados + 180) % 360 - 180


def hacia_punto(pose, objetivo, cell_mm, modelo, v_max=170.0, v_min=90.0, w_max=120.0,
                kp_giro=2.5, k_distancia=1.6, giro_en_sitio=40.0, tolerancia_mm=25.0,
                cerca_mm=80.0, limite=0.35):
    """Ley de control sobre el CENTRO de giro. Devuelve (llego, izq, der, d_mm, error_deg).

    v_min: por debajo de ~0,15 de potencia el roce no deja avanzar (medido
    1-oct); acercarse "muy despacio" en realidad es no moverse.
    Cerca del objetivo (`cerca_mm`) un desvio lateral pequeño se vuelve un
    error de angulo grande: si el punto quedo detras, se llega marcha atras en
    vez de dar la vuelta. Pero con mas de `giro_en_sitio` de error se gira
    primero en el sitio: avanzar en curva lenta (v·cos del error, casi en la
    zona muerta) con el giro al maximo hacia orbitar el punto sin alcanzarlo
    (cancha 1-oct: 6 s girando a 3-6 cm del punto).
    """
    dc = (objetivo["col"] - pose["col"]) * cell_mm
    dr = (objetivo["row"] - pose["row"]) * cell_mm
    distancia = _norma(dc, dr)
    if distancia <= tolerancia_mm:
        return True, 0.0, 0.0, distancia, 0.0
    error = giro_corto(math.degrees(math.atan2(-dr, dc)) - pose["theta"])
    rapidez = max(v_min, min(v_max, k_distancia * distancia))
    sentido = 1
    if distancia < cerca_mm and abs(error) > 90:
        sentido, error = -1, giro_corto(error - 180)   # marcha atras
    w = max(-w_max, min(w_max, kp_giro * error))
    if abs(error) > giro_en_sitio:
        v = 0.0                               # primero orientarse, sin avanzar
    elif distancia < cerca_mm:
        v = sentido * rapidez * math.cos(math.radians(error))
    elif abs(error) > giro_en_sitio:
        v = 0.0                               # primero orientarse, sin avanzar
    else:
        v = rapidez * math.cos(math.radians(error))
    izquierda, derecha = modelo.potencias(v, w, limite)
    return False, izquierda, derecha, distancia, error


class Adaptador:
    """Ajusta las escalas del modelo comparando lo predicho con lo observado.

    Cada `ventana_ms` de observaciones se integra el modelo desde la pose vista
    al inicio de la ventana y se compara con la vista al final. Ventanas cortas
    serían ruido de la visión (unos mm); 400 ms a 150 mm/s son 6 cm.
    """

    def __init__(self, modelo, ventana_ms=400, alfa=0.3, minimo=0.4, maximo=2.0):
        self.modelo, self.ventana_ms, self.alfa = modelo, ventana_ms, alfa
        self.minimo, self.maximo = minimo, maximo
        self.referencia = None
        self.actualizaciones = 0

    def reiniciar(self):
        self.referencia = None

    def _mover(self, escala, razon):
        nueva = escala * ((1 - self.alfa) + self.alfa * razon)
        return max(self.minimo, min(self.maximo, nueva))

    def observar(self, predictor, t_obs, centro, cell_mm):
        if self.referencia is None or t_obs < self.referencia[0]:
            self.referencia = (t_obs, centro)
            return
        t0, inicio = self.referencia
        if t_obs - t0 < self.ventana_ms:
            return
        self.referencia = (t_obs, centro)
        retraso = self.modelo.retraso_ms
        predicho = predictor.predecir(inicio, t0 - retraso, t_obs - retraso, cell_mm)
        d_pred = _norma(predicho["col"] - inicio["col"], predicho["row"] - inicio["row"]) * cell_mm
        d_obs = _norma(centro["col"] - inicio["col"], centro["row"] - inicio["row"]) * cell_mm
        g_pred = giro_corto(predicho["theta"] - inicio["theta"])
        g_obs = giro_corto(centro["theta"] - inicio["theta"])
        if d_pred > 20:
            self.modelo.escala_lineal = self._mover(self.modelo.escala_lineal, d_obs / d_pred)
            self.actualizaciones += 1
        if abs(g_pred) > 8 and g_obs * g_pred > 0:
            self.modelo.escala_giro = self._mover(self.modelo.escala_giro, g_obs / g_pred)
            self.actualizaciones += 1


class IrAPunto:
    PERIODO_MS = 50

    def __init__(self, vision, modelo, motores, robot_id, reloj=ahora_ms,
                 max_edad_ms=800, espera_max_ms=3000, reintentos=3, **control):
        self.vision, self.modelo, self.motores = vision, modelo, motores
        self.robot_id, self.reloj = robot_id, reloj
        self.max_edad_ms, self.espera_max_ms = max_edad_ms, espera_max_ms
        self.reintentos_max = reintentos
        self.control = control
        self.predictor = Predictor(modelo)
        self.adaptador = Adaptador(modelo)
        self.estado, self.motivo = INACTIVO, None
        self.objetivo = None
        self.proximo = 0
        self.ultimo = {}

    @property
    def activa(self):
        return self.estado in (EN_CAMINO, ESPERANDO_VISION, VERIFICANDO)

    def iniciar(self, col, row):
        mensaje = self.vision.mensaje
        if mensaje is not None:
            grid = mensaje["grid"]
            if not (0 <= col <= grid["cols"] and 0 <= row <= grid["rows"]):
                raise ValueError("Objetivo fuera de la cancha")
        self.objetivo = {"col": col, "row": row}
        self.adaptador.reiniciar()
        self.ultimo = {}
        self.estado, self.motivo = EN_CAMINO, None
        self.reintentos = 0
        self.espera_desde = None
        self.inicio_ms = self.reloj()
        self.proximo = 0

    def detener(self, motivo="stop"):
        if self.activa:
            self._parar()
            self.estado, self.motivo = ABORTADO, motivo

    # ------------------------------------------------------------ bucle
    def tick(self):
        if not self.activa:
            return
        ahora = self.reloj()
        if ahora < self.proximo:
            return
        self.proximo = ahora + self.PERIODO_MS
        mensaje = self.vision.mensaje
        rover = None
        if mensaje is not None:
            for item in mensaje["rovers"]:
                if item["id"] == self.robot_id:
                    rover = item
        desfase = getattr(self.vision, "desfase_reloj", None)
        if rover is None or desfase is None:
            return self._esperar(ahora, "rover_no_visible")
        # Instante local de la captura: la entrega mas rapida vista se toma
        # como latencia minima (el ESP32 no tiene la hora de la vision).
        t_obs = mensaje["ts_ms"] + desfase - self.modelo.latencia_minima_ms - rover["age_ms"]
        edad = ahora - t_obs
        if edad > self.max_edad_ms:
            return self._esperar(ahora, "vision_vieja")
        self.espera_desde = None
        cell = mensaje["grid"]["cell_mm"]
        centro = self.modelo.centro_desde_marcador(rover, cell)

        self.adaptador.observar(self.predictor, t_obs, centro, cell)

        if self.estado == VERIFICANDO:
            if t_obs - self.modelo.retraso_ms < self.parada_ms:
                return                        # imagen anterior a la parada
            llego, _, _, distancia, _ = hacia_punto(
                centro, self.objetivo, cell, self.modelo, **self._tolerancia(1.6))
            if llego:
                self.estado = LLEGO
                self.ultimo.update(d_mm=round(distancia), real=True)
                return
            self.reintentos += 1
            if self.reintentos > self.reintentos_max:
                self.estado, self.motivo = ABORTADO, "no_converge"
                return
            self.estado = EN_CAMINO

        prediccion = self.predictor.predecir(centro, t_obs - self.modelo.retraso_ms, ahora, cell)
        estorbo = obstaculo_en_camino(mensaje, prediccion, self.objetivo)
        if estorbo is not None:
            self._parar()
            self.estado, self.motivo = ABORTADO, "camino_bloqueado: " + estorbo
            return
        llego, izquierda, derecha, distancia, error = hacia_punto(
            prediccion, self.objetivo, cell, self.modelo, **self.control)
        self.ultimo = {"d_mm": round(distancia), "err_deg": round(error, 1),
                       "cmd": [round(izquierda, 3), round(derecha, 3)], "edad_ms": round(edad),
                       "escalas": [round(self.modelo.escala_lineal, 2), round(self.modelo.escala_giro, 2)],
                       "adelanto_mm": round(_norma(prediccion["col"] - centro["col"],
                                                     prediccion["row"] - centro["row"]) * cell)}
        if llego:
            self._parar()
            self.parada_ms = ahora
            self.estado = VERIFICANDO
            return
        self.estado = EN_CAMINO
        try:
            self.motores.set_motor(izquierda, derecha)
        except ValueError as error:
            self._parar()
            self.estado, self.motivo = ABORTADO, "motores: {}".format(error)
            return
        self.predictor.registrar(ahora, izquierda, derecha)

    def _tolerancia(self, factor):
        datos = dict(self.control)
        datos["tolerancia_mm"] = datos.get("tolerancia_mm", 25.0) * factor
        return datos

    def _esperar(self, ahora, motivo):
        self._parar()
        if self.espera_desde is None:
            self.espera_desde = ahora
        if self.estado != VERIFICANDO:
            self.estado = ESPERANDO_VISION
        self.motivo = motivo
        if ahora - self.espera_desde > self.espera_max_ms:
            self.estado = ABORTADO

    def _parar(self):
        self.motores.stop("mision")
        self.predictor.registrar(self.reloj(), 0.0, 0.0)

    def informe(self):
        datos = {"estado": self.estado, "motivo": self.motivo, "objetivo": self.objetivo}
        if self.activa or self.estado in (LLEGO, ABORTADO):
            datos.update(self.ultimo)
            datos["t_ms"] = self.reloj() - getattr(self, "inicio_ms", self.reloj())
        return datos


class Misiones:
    """Una sola mision activa a la vez (IR o LLEVAR); la sesion habla con esto.

    `tick` es el metodo de la mision activa, no un envoltorio: en la placa
    cada llamada anidada gasta pila (pystack) y planificar ya va muy hondo.
    """

    def __init__(self, ir, llevar=None, fabrica_llevar=None):
        # fabrica_llevar: crea LlevarCubo al primer LLEVAR. Asi un modulo grande
        # que no cabe en RAM da un error a la orden, no un arranque en bucle.
        self.ir, self.cubo, self.fabrica = ir, llevar, fabrica_llevar
        self.error_carga = None
        self.vision, self.robot_id = ir.vision, ir.robot_id
        self._activar(ir)

    def _activar(self, mision):
        self.actual = mision
        self.tick = mision.tick

    @property
    def activa(self):
        return self.actual.activa

    def iniciar(self, col, row):
        self.detener("nueva_mision")
        self._activar(self.ir)
        self.ir.iniciar(col, row)

    def llevar(self, color):
        if self.cubo is None and self.fabrica is not None:
            try:
                self.cubo = self.fabrica()
                self.error_carga = None
            except Exception as error:      # MemoryError, ImportError...
                self.error_carga = "{}: {}".format(type(error).__name__, error)
                raise ValueError(self.error_carga)
        if self.cubo is None:
            raise ValueError("Firmware sin mision de cubo")
        self.detener("nueva_mision")
        self._activar(self.cubo)
        self.cubo.iniciar(color)

    def detener(self, motivo="stop"):
        self.ir.detener(motivo)
        if self.cubo is not None:
            self.cubo.detener(motivo)

    def informe(self):
        datos = self.actual.informe()
        if self.error_carga is not None:
            datos["error_carga"] = self.error_carga
        return datos
