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

# Horquillas: dos puntas que salen del frente (foto del rover), en mm desde el
# centro de giro: hacia adelante y a cada lado. Girando barren un círculo de
# ~137 mm, no los ~92 mm de la cara del frente: el 11 sacó de su zona el verde
# (girando a 11 cm) y el rojo (pasando al lado) ya entregados (cancha 5-oct).
PUNTAS_MM, PUNTAS_LADO_MM = 120.0, 65.0
ALCANCE_GIRO_MM = math.sqrt(PUNTAS_MM * PUNTAS_MM + PUNTAS_LADO_MM * PUNTAS_LADO_MM)


def _norma(x, y):
    # math.hypot no esta garantizado en CircuitPython.
    return math.sqrt(x * x + y * y)


def distancia_a_segmento(p, a, b):
    dx, dy = b[0] - a[0], b[1] - a[1]
    largo = dx * dx + dy * dy
    t = 0.0 if largo == 0 else max(0.0, min(1.0, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / largo))
    dx, dy = p[0] - a[0] - t * dx, p[1] - a[1] - t * dy
    # La raíz aquí y no con _norma: un marco menos en la pila de la placa,
    # que se llena en lo más hondo de la planificación (cancha 3-oct).
    return math.sqrt(dx * dx + dy * dy)


def obstaculo_en_camino(mensaje, desde, hasta, radio_rover_mm=85.0, holgura_mm=10.0,
                        excluir=None, propio=None, ancho_mm=None, margen_rover_mm=0.0):
    """Primer cubo u obstaculo que el CUERPO del rover tocaria en el tramo recto.

    Es la red de seguridad: si algo estorba, el rover se detiene en vez de
    empujarlo. `excluir`: color del cubo que se empuja a proposito. Con
    `propio` (id de este rover) tambien cuenta el otro rover. `ancho_mm`:
    medio ancho de ESTE rover yendo recto (sin girar) contra cubos y
    obstáculos; contra el otro rover vale siempre el radio completo de los dos.
    """
    propio_mm = radio_rover_mm if ancho_mm is None else ancho_mm
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
            libre = (radio_rover_mm + margen_rover_mm if grupo == "rovers" else propio_mm) + holgura_mm + medio
            punto = (item["col"], item["row"])
            cerca = distancia_a_segmento(punto, a, b) * cell
            if cerca < libre:
                # Ya estaba así de cerca (salen juntos de la salida, o quedó
                # pegado a un cubo) y el tramo no lo acerca más: alejarse no
                # estorba. Con los cubos también: el 11 cedía el paso pero no
                # podía apartarse de su propio cubo (generador oficial, 0,8).
                if cerca >= distancia_a_segmento(punto, a, a) * cell - 5:
                    continue
                return nombre + (" " + item["color"] if "color" in item else "")
    return None


def _sentido_para_girar(mensaje, pose, colores, alcance_mm):
    """0 si girando en `pose` las horquillas no tocan ninguno de esos cubos;
    si no, -1 (marcha atrás) o 1 (adelante): hacia donde se aleja del más cercano."""
    cell = mensaje["grid"]["cell_mm"]
    limite = alcance_mm + mensaje["cube_side"] * cell * 0.7072 + 10.0
    th = math.radians(pose["theta"])
    mejor, sentido = None, 0
    for item in mensaje["cubes"]:
        if item["color"] not in colores:
            continue
        dc, dr = (item["col"] - pose["col"]) * cell, (item["row"] - pose["row"]) * cell
        d = _norma(dc, dr)
        if d < limite and (mejor is None or d < mejor):
            mejor = d
            sentido = -1 if dc * math.cos(th) - dr * math.sin(th) > 0 else 1
    return sentido


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
    MARGEN_ROVER_MM = 0.0

    def __init__(self, vision, modelo, motores, robot_id, reloj=ahora_ms,
                 max_edad_ms=800, espera_max_ms=3000, reintentos=3,
                 alcance_giro_mm=ALCANCE_GIRO_MM, **control):
        self.vision, self.modelo, self.motores = vision, modelo, motores
        self.robot_id, self.reloj = robot_id, reloj
        self.max_edad_ms, self.espera_max_ms = max_edad_ms, espera_max_ms
        self.reintentos_max = reintentos
        # Hasta dónde llegan las horquillas girando (cubos ya entregados).
        self.alcance_giro_mm = alcance_giro_mm
        # Margen extra contra el otro rover al estacionarse o apartarse, sobre
        # los 180 mm entre centros (de frente se tocan a ~160 mm). Simulador
        # 6-oct, 144 rondas: con 40 mm 0 choques pero 8 rondas completas menos;
        # con 0, 1 choque. Subirlo a 40 si en la cancha se siguen rozando.
        self.margen_rover_mm = IrAPunto.MARGEN_ROVER_MM
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
        # Con propio también frena ante el otro rover. Sin él sólo miraba
        # cubos: al estacionarse se le iba encima al compañero (cancha 6-oct
        # 17:46; simulador: 19 choques en 72 rondas, todos estacionándose).
        estorbo = obstaculo_en_camino(mensaje, prediccion, self.objetivo, propio=self.robot_id,
                                      margen_rover_mm=self.margen_rover_mm)
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
        if abs(error) > self.control.get("giro_en_sitio", 40.0):
            # Va a girar en el sitio: si las horquillas alcanzan un cubo ya
            # entregado, primero alejarse en recto (cancha 5-oct: el 11 giró a
            # 11 cm del verde y lo barrió fuera de la zona). La ruta ya les deja
            # ese margen (RoutePlanner.entregado_mm); frenar aquí también con
            # él cortaba rutas por nada (simulador: +6 s por ronda).
            from llevar_cubo import entregados
            hechos = entregados(mensaje)
            sentido = _sentido_para_girar(mensaje, prediccion, hechos, self.alcance_giro_mm) if hechos else 0
            if sentido:
                izquierda, derecha = self.modelo.potencias(sentido * self.control.get("v_min", 90.0), 0.0,
                                                           self.control.get("limite", 0.35))
                self.ultimo["despeje"] = sentido
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

    Con una `ronda` (incremento 3) las misiones las lanza ella; una orden
    manual (STOP, MOTOR, IR, LLEVAR... desde la PC) la detiene, pero que la PC
    se conecte o se vaya no la toca.
    """

    def __init__(self, ir, llevar=None, fabrica_llevar=None):
        # fabrica_llevar: crea LlevarCubo al primer LLEVAR. Asi un modulo grande
        # que no cabe en RAM da un error a la orden, no un arranque en bucle.
        self.ir, self.cubo, self.fabrica = ir, llevar, fabrica_llevar
        self.error_carga = None
        self.ronda = None
        self.vision, self.robot_id = ir.vision, ir.robot_id
        self._activar(ir)

    def _activar(self, mision):
        self.actual = mision
        self.tick = mision.tick

    @property
    def activa(self):
        return self.actual.activa

    @property
    def autonoma(self):
        """La ronda manda: conectarse o desconectarse desde la PC no la detiene."""
        return self.ronda is not None and self.ronda.autonoma

    def iniciar(self, col, row):
        self.detener("nueva_mision")
        self._activar(self.ir)
        self.ir.iniciar(col, row)

    def _mision_cubo(self):
        if self.cubo is None and self.fabrica is not None:
            try:
                self.cubo = self.fabrica()
                self.error_carga = None
            except Exception as error:      # MemoryError, ImportError...
                self.error_carga = "{}: {}".format(type(error).__name__, error)
                raise ValueError(self.error_carga)
        if self.cubo is None:
            raise ValueError("Firmware sin mision de cubo")
        return self.cubo

    def preparar(self):
        """Carga LLEVAR y su planificador ANTES de la ronda, con el rover quieto:
        en el primer segundo de la ronda la RAM ya está ocupada y fragmentada."""
        cubo = self._mision_cubo()
        if hasattr(cubo, "preparar"):
            cubo.preparar()

    def llevar(self, color):
        """LLEVAR manual (desde la PC): le quita el control a la ronda."""
        cubo = self._mision_cubo()
        self.detener("nueva_mision")
        self._activar(cubo)
        cubo.iniciar(color)

    def llevar_en_ronda(self, color):
        """La ronda lanza el siguiente cubo: no se detiene a si misma."""
        cubo = self._mision_cubo()
        self.detener_mision("siguiente_cubo")
        self._activar(cubo)
        cubo.iniciar(color)

    def ir_en_ronda(self, col, row):
        """La ronda manda al rover a estacionarse (IR), sin detenerse a sí misma."""
        self.detener_mision("aparcar")
        self._activar(self.ir)
        self.ir.iniciar(col, row)

    def detener_mision(self, motivo="stop"):
        """Para el movimiento en curso; la ronda (si hay) sigue decidiendo."""
        self.ir.detener(motivo)
        if self.cubo is not None:
            self.cubo.detener(motivo)

    def detener(self, motivo="stop"):
        """Una orden manual: para la mision y tambien la ronda."""
        self.detener_mision(motivo)
        if self.ronda is not None:
            self.ronda.detener(motivo)

    def informe(self):
        datos = self.actual.informe()
        if self.error_carga is not None:
            datos["error_carga"] = self.error_carga
        if self.ronda is not None:
            datos["ronda"] = self.ronda.informe()
        return datos
