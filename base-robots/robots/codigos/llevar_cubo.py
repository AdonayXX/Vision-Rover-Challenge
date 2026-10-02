"""Incremento 2: llevar un cubo a la zona de su color, todo EN la placa.

Cada 50 ms, como autonomia.IrAPunto, decide sobre la pose PREDICHA:
  PLANIFICAR  parado: ruta A* (rutas.py, paso 2, ~0,4 s en la placa) hasta
              un punto detrás del cubo, en la línea cubo -> zona
  SALIR       si el rover arranca pegado a un borde u objeto: unos cm rectos
  APROXIMAR   sigue los puntos de la ruta sin parar en los intermedios
  ALINEAR     gira en el sitio hasta mirar en la dirección cubo -> zona
  EMPUJAR     avanza con el cubo; el rumbo lleva el cubo al centro de la zona
              y se para cuando el cubo PREDICHO llega
  VERIFICAR   parado, con una imagen posterior a la parada: ¿alineado? /
              ¿cubo entero en su zona? (regla exacta del contrato v2)
  RETROCEDER  el cubo se desvió: marcha atrás y se vuelve a planificar
  RETIRAR     entregado: marcha atrás para soltar el cubo
Terminan en ENTREGADO o ABORTADO (con motivo).

Qué cubo es cuál lo dice la telemetría (reglamento 12.4); el sensor de color
no se usa aquí.
"""
import math

from autonomia import (Adaptador, _norma, distancia_a_segmento, giro_corto,
                       hacia_punto, obstaculo_en_camino)
from cliente_vision_rover import ahora_ms
from modelo_rover import Predictor

INACTIVO = "INACTIVO"
PLANIFICAR = "PLANIFICAR"
SALIR = "SALIR"
APROXIMAR = "APROXIMAR"
ALINEAR = "ALINEAR"
EMPUJAR = "EMPUJAR"
VERIFICAR = "VERIFICAR"
RETROCEDER = "RETROCEDER"
RETIRAR = "RETIRAR"
ENTREGADO = "ENTREGADO"
ABORTADO = "ABORTADO"
ACTIVAS = (PLANIFICAR, SALIR, APROXIMAR, ALINEAR, EMPUJAR, VERIFICAR, RETROCEDER, RETIRAR)


# ------------------------------------------------------------------ geometría
def buscar(lista, clave, valor):
    for item in lista:
        if item.get(clave) == valor:
            return item
    return None


def rumbo(desde, hacia):
    """Ángulo del contrato (0 = derecha, antihorario) para ir de un punto a otro."""
    return math.degrees(math.atan2(-(hacia["row"] - desde["row"]), hacia["col"] - desde["col"]))


def relativo(pose, punto, cell_mm):
    """(adelante, izquierda) en mm del punto, visto desde la pose."""
    th = math.radians(pose["theta"])
    dc = (punto["col"] - pose["col"]) * cell_mm
    dr = (punto["row"] - pose["row"]) * cell_mm
    return dc * math.cos(th) - dr * math.sin(th), -dc * math.sin(th) - dr * math.cos(th)


def desplazar(pose, adelante_mm, cell_mm):
    th = math.radians(pose["theta"])
    return {"col": pose["col"] + adelante_mm * math.cos(th) / cell_mm,
            "row": pose["row"] - adelante_mm * math.sin(th) / cell_mm,
            "theta": pose["theta"]}


def punto_relativo(pose, adelante_mm, izquierda_mm, cell_mm):
    """Inversa de relativo(): el punto a (adelante, izquierda) mm de la pose."""
    th = math.radians(pose["theta"])
    return {"col": pose["col"] + (adelante_mm * math.cos(th) - izquierda_mm * math.sin(th)) / cell_mm,
            "row": pose["row"] - (adelante_mm * math.sin(th) + izquierda_mm * math.cos(th)) / cell_mm}


def punto_detras(cubo, meta, distancia_mm, cell_mm):
    """Centro del rover detrás del cubo, en la línea cubo -> meta. None si coinciden."""
    dc, dr = meta["col"] - cubo["col"], meta["row"] - cubo["row"]
    largo = _norma(dc, dr)
    if largo < 1e-6:
        return None
    d = distancia_mm / cell_mm
    return {"col": cubo["col"] - dc / largo * d, "row": cubo["row"] - dr / largo * d}


def cubo_en_su_zona(cubo, depot, depot_size, grid, cube_side):
    """Regla del contrato v2 (CONTRATO.md, sección 3). Devuelve (adentro, falta en celdas)."""
    distancias = (depot["row"], grid["rows"] - depot["row"],
                  depot["col"], grid["cols"] - depot["col"])
    if min(distancias) in distancias[:2]:          # apoya en el borde de arriba o de abajo
        semi_col, semi_row = depot_size["length"] / 2, depot_size["depth"] / 2
    else:
        semi_col, semi_row = depot_size["depth"] / 2, depot_size["length"] / 2
    margen = cube_side * math.sqrt(2) / 2
    exceso_col = max(0.0, abs(cubo["col"] - depot["col"]) - (semi_col - margen))
    exceso_row = max(0.0, abs(cubo["row"] - depot["row"]) - (semi_row - margen))
    falta = _norma(exceso_col, exceso_row)
    return falta == 0.0, falta


def corredor_bloqueado(mensaje, color, cubo, meta, rover, robot_id, contacto_mm,
                       radio_rover_mm=85.0, holgura_mm=10.0):
    """Lo que estorba el empuje recto: el tramo del cubo y el del cuerpo del rover."""
    cell = mensaje["grid"]["cell_mm"]
    medio_cubo = mensaje["cube_side"] * cell * 0.7072
    dc, dr = meta["col"] - cubo["col"], meta["row"] - cubo["row"]
    largo = _norma(dc, dr)
    if largo < 1e-6:
        return None
    fin_rover = (meta["col"] - dc / largo * contacto_mm / cell,
                 meta["row"] - dr / largo * contacto_mm / cell)
    tramos = (((cubo["col"], cubo["row"]), (meta["col"], meta["row"]), medio_cubo),
              ((rover["col"], rover["row"]), fin_rover, radio_rover_mm))
    for grupo, nombre in (("cubes", "cubo"), ("obstacles", "obstaculo"), ("rovers", "rover")):
        for item in mensaje.get(grupo, ()):
            if grupo == "cubes" and item["color"] == color:
                continue
            if grupo == "rovers" and item["id"] == robot_id:
                continue
            medio = radio_rover_mm if grupo == "rovers" else medio_cubo
            for a, b, tamano in tramos:
                if distancia_a_segmento((item["col"], item["row"]), a, b) * cell < tamano + holgura_mm + medio:
                    return nombre + " " + str(item.get("color", item.get("id", "")))
    return None


def salida_sin_acercarse(mensaje, desde, hasta, robot_id, radio_rover_mm=85.0):
    """Para despegarse: el tramo no se acerca a nada más de lo que ya está."""
    cell = mensaje["grid"]["cell_mm"]
    medio_cubo = mensaje["cube_side"] * cell * 0.7072
    a, b = (desde["col"], desde["row"]), (hasta["col"], hasta["row"])
    for grupo in ("cubes", "obstacles", "rovers"):
        for item in mensaje.get(grupo, ()):
            if grupo == "rovers" and item["id"] == robot_id:
                continue
            medio = radio_rover_mm if grupo == "rovers" else medio_cubo
            p = (item["col"], item["row"])
            ahora = _norma(p[0] - a[0], p[1] - a[1]) * cell
            if distancia_a_segmento(p, a, b) * cell < min(radio_rover_mm + medio, ahora) - 1:
                return False
    return True


class _Escena:
    """Lo que RoutePlanner lee de un estado. El rover propio va en su centro de giro.

    La frescura la controla la misión; aquí no se vuelve a exigir.
    """
    max_age_ms = 10 ** 9

    def __init__(self, mensaje, robot_id, centro):
        self.message, self.robot_id, self.centro = mensaje, robot_id, centro
        self.seq = mensaje["seq"]

    def reason(self, color=None):
        return None

    def capture_age_ms(self):
        return 0

    def rover(self, identidad):
        if identidad == self.robot_id:
            return {"col": self.centro["col"], "row": self.centro["row"]}
        return buscar(self.message["rovers"], "id", identidad)

    def cube(self, color):
        return buscar(self.message["cubes"], "color", color)


# ------------------------------------------------------------------ misión
class LlevarCubo:
    PERIODO_MS = 50

    def __init__(self, vision, modelo, motores, robot_id, reloj=ahora_ms, max_edad_ms=800,
                 espera_max_ms=3000, max_ms=150000, max_replanes=10, max_empujes=8,
                 aproximacion_mm=160.0, contacto_mm=110.0, radio_mm=85.0, holgura_mm=10.0,
                 holgura_ruta_mm=25.0, paso_ruta=2, retroceso_mm=80.0, v_empuje=120.0, w_empuje=35.0, kp_empuje=2.0,
                 lateral_max_mm=30.0, linea_max_mm=25.0, desvio_max_deg=30.0,
                 alinear_deg=4.0, tolerancia_empuje_mm=6.0, sesgo_mm=15.0, cubo_ciego_ms=2500,
                 **control):
        self.vision, self.modelo, self.motores = vision, modelo, motores
        self.robot_id, self.reloj = robot_id, reloj
        self.max_edad_ms, self.espera_max_ms, self.max_ms = max_edad_ms, espera_max_ms, max_ms
        self.max_replanes, self.max_empujes = max_replanes, max_empujes
        self.aproximacion_mm, self.contacto_inicial_mm = aproximacion_mm, contacto_mm
        self.radio_mm, self.holgura_mm, self.paso_ruta = radio_mm, holgura_mm, paso_ruta
        self.holgura_ruta_mm = holgura_ruta_mm
        self.retroceso_mm = retroceso_mm
        self.v_empuje, self.w_empuje, self.kp_empuje = v_empuje, w_empuje, kp_empuje
        self.lateral_max_mm, self.linea_max_mm = lateral_max_mm, linea_max_mm
        self.desvio_max_deg, self.alinear_deg = desvio_max_deg, alinear_deg
        self.tolerancia_empuje_mm = tolerancia_empuje_mm
        # Pasarse de la zona no tiene arreglo (no se puede tirar del cubo) y
        # quedarse corto sí: el empuje para un poco antes del centro.
        self.sesgo_mm = sesgo_mm
        # Empujando, la cámara a veces pierde el cubo pegado al rover: se
        # sigue con el cubo estimado en el frente hasta este tiempo.
        self.cubo_ciego_ms = cubo_ciego_ms
        self.control = control
        self.predictor = Predictor(modelo)
        self.adaptador = Adaptador(modelo)
        self.planner = None                 # rutas.py se importa al primer uso
        self.estado, self.motivo, self.color = INACTIVO, None, None
        self.ultimo = {}
        self.proximo = 0

    @property
    def activa(self):
        return self.estado in ACTIVAS

    def iniciar(self, color):
        if color not in ("red", "green", "blue"):
            raise ValueError("Color invalido")
        self.color, self.motivo = color, None
        self.adaptador.reiniciar()
        self.ultimo = {}
        self.replanes = self.empujes = self.alineaciones = 0
        self.contacto_mm = self.contacto_inicial_mm
        self.inicio_ms = self.reloj()
        self.espera_desde = None
        self.proximo = 0
        self.puntos = []
        self.tras = None
        self.submeta = None
        self.descartadas = []
        self.en_contacto, self.lateral_contacto = False, 0.0
        self.cubo_viejo_ms = 0
        self.esperas = 0
        self._parar_y_pasar(PLANIFICAR)

    def detener(self, motivo="stop"):
        if self.activa:
            self._abortar(motivo)

    def informe(self):
        datos = {"estado": self.estado, "motivo": self.motivo, "color": self.color}
        if self.estado != INACTIVO:
            datos.update(self.ultimo)
            datos["t_ms"] = self.reloj() - self.inicio_ms
            datos["replanes"], datos["empujes"] = self.replanes, self.empujes
            datos["esperas"] = self.esperas
            if self.submeta is not None:
                datos["submeta"] = [round(self.submeta["col"], 2), round(self.submeta["row"], 2)]
        return datos

    # ------------------------------------------------------------ bucle
    def tick(self):
        if not self.activa:
            return
        ahora = self.reloj()
        if ahora < self.proximo:
            return
        self.proximo = ahora + self.PERIODO_MS
        if ahora - self.inicio_ms > self.max_ms:
            return self._abortar("tiempo_agotado")
        mensaje = self.vision.mensaje
        desfase = getattr(self.vision, "desfase_reloj", None)
        rover = None if mensaje is None else buscar(mensaje["rovers"], "id", self.robot_id)
        if rover is None or desfase is None:
            return self._esperar(ahora, "rover_no_visible")
        t_obs = mensaje["ts_ms"] + desfase - self.modelo.latencia_minima_ms - rover["age_ms"]
        if ahora - t_obs > self.max_edad_ms:
            return self._esperar(ahora, "vision_vieja")
        cubo = buscar(mensaje["cubes"], "color", self.color)
        if cubo is None:
            return self._esperar(ahora, "cubo_no_visible")
        # Un cubo que la cámara dejó de ver llega con su ÚLTIMA posición y la
        # edad creciendo (contrato, sección 6): >0 = posición más vieja que
        # la del rover en la misma imagen.
        self.cubo_viejo_ms = cubo["age_ms"] - rover["age_ms"]
        if cubo["age_ms"] > self.max_edad_ms and not (
                self.estado == EMPUJAR and self.en_contacto and cubo["age_ms"] <= self.cubo_ciego_ms):
            return self._esperar(ahora, "cubo_no_visible")
        deposito = buscar(mensaje.get("depots", ()), "color", self.color)
        if deposito is None:
            return self._abortar("sin_zona_" + self.color)
        meta = self.submeta or deposito       # submeta: reubicar un cubo pegado a la pared
        self.espera_desde = None
        self.ultimo.pop("espera", None)
        cell = mensaje["grid"]["cell_mm"]
        centro = self.modelo.centro_desde_marcador(rover, cell)
        self.adaptador.observar(self.predictor, t_obs, centro, cell)
        self.ultimo["edad_ms"] = round(ahora - t_obs)
        if self.estado == PLANIFICAR:
            return self._planificar(mensaje, centro, t_obs, cubo, deposito, cell)
        if self.estado == VERIFICAR:
            return self._verificar(mensaje, centro, t_obs, cubo, deposito, cell)
        pred = self.predictor.predecir(centro, t_obs - self.modelo.retraso_ms, ahora, cell)
        if self.estado == EMPUJAR:
            return self._empujar(ahora, mensaje, centro, pred, cubo, meta, cell)
        if self.estado == ALINEAR:
            return self._alinear(ahora, pred, cubo, meta)
        self._seguir(ahora, mensaje, pred, cubo, cell)

    # ------------------------------------------------------------ fases
    def _planificar(self, mensaje, centro, t_obs, cubo, deposito, cell):
        if not self._tras_parada(t_obs):
            return                            # la ruta sale de una imagen ya parado
        if cubo_en_su_zona(cubo, deposito, mensaje["depot_size"], mensaje["grid"], mensaje["cube_side"])[0]:
            return self._retirar(centro, cubo, cell)
        meta = self.submeta or deposito
        if self.replanes >= self.max_replanes:
            return self._abortar("demasiados_intentos")
        self.replanes += 1
        detras = punto_detras(cubo, meta, self.aproximacion_mm, cell)
        if detras is None:
            return self._abortar("cubo_sobre_el_centro_de_la_zona")
        if self.planner is None:
            from rutas import RoutePlanner
            self.planner = RoutePlanner(self.radio_mm, self.radio_mm, self.holgura_mm,
                                        step_cells=self.paso_ruta, required_colors=())
        escena = _Escena(mensaje, self.robot_id, centro)
        estorbo = corredor_bloqueado(mensaje, self.color, cubo, meta, detras, self.robot_id,
                                     self.contacto_mm, self.radio_mm, self.holgura_mm)
        if estorbo is not None:
            motivo = "corredor_bloqueado: " + estorbo
        else:
            # Primero con margen holgado: el rover real se aparta unos cm de la
            # línea y recorta las esquinas, y la red de seguridad lo pararía.
            # Si así no cabe (cubos juntos), con el margen justo.
            for holgura in (self.holgura_ruta_mm, self.holgura_mm):
                self.planner.clearance = holgura
                ruta = self.planner.plan(escena, detras)
                if ruta["estado"] == "RUTA":
                    self.puntos = ruta["puntos"][1:] or [detras]
                    self.estado = APROXIMAR
                    return
            if ruta["motivo"] == "origen_sin_espacio":
                # Pegado a un borde (la salida está a 75 mm) o a un objeto:
                # primero despegarse en línea recta, sin acercarse a nada.
                libre = self.planner.scene(escena)
                for mm in (60, 100, 140, -60, -100, -140):
                    p = desplazar(centro, mm, cell)
                    q = (p["col"], p["row"])
                    if self.planner.free_segment(libre, q, q) and salida_sin_acercarse(
                            mensaje, centro, p, self.robot_id, self.radio_mm):
                        self.puntos = [p]
                        self.estado = SALIR
                        return
                return self._abortar("sin_ruta: origen_sin_espacio")
            motivo = "sin_ruta: " + str(ruta["motivo"])
        # No cabe, no se llega o algo tapa el empuje recto (cubo pegado a la
        # pared opuesta a su zona, en un rincón o con otro cubo delante):
        # primero se lo empuja a un sitio desde donde sí se pueda. Si
        # tampoco se llega a ese, se descarta esa dirección y se busca otra.
        if self.submeta is not None:
            self.descartadas.append(self.angulo_submeta)
        self.submeta = self._reubicacion(mensaje, escena, cubo, deposito, cell)
        if self.submeta is not None:
            self.ultimo["reubicar"] = [round(self.submeta["col"], 2), round(self.submeta["row"], 2)]
            return                            # el próximo tick planifica hacia ahí
        self._abortar(motivo)

    def _seguir(self, ahora, mensaje, pred, cubo, cell):
        """SALIR, APROXIMAR, RETROCEDER y RETIRAR: ir al siguiente punto."""
        destino = self.puntos[0]
        if self.estado == APROXIMAR:
            estorbo = obstaculo_en_camino(mensaje, pred, destino, self.radio_mm, 0.0,
                                          excluir=self.color, propio=self.robot_id)
            # Al cubo que se va a empujar se le llega de frente a 16 cm: sólo
            # estorba si de verdad se lo tocaría (el radio de 85 mm es el de
            # las esquinas; de frente toca a contacto_mm).
            if estorbo is None and distancia_a_segmento(
                    (cubo["col"], cubo["row"]), (pred["col"], pred["row"]),
                    (destino["col"], destino["row"])) * cell < self.contacto_mm:
                estorbo = "cubo " + self.color
        elif self.estado == SALIR:
            estorbo = None                    # ya verificado al elegir el punto
        else:
            estorbo = obstaculo_en_camino(mensaje, pred, destino, self.radio_mm, 0.0,
                                          excluir=self.color, propio=self.robot_id)
        if estorbo is not None:
            self.ultimo["estorbo"] = estorbo
            if self.estado == RETIRAR:
                return self._parar_y_pasar(ENTREGADO)   # el cubo ya está entregado
            return self._parar_y_pasar(PLANIFICAR)
        control = dict(self.control)
        intermedio = self.estado == APROXIMAR and len(self.puntos) > 1
        if intermedio:
            control["tolerancia_mm"] = 30.0
        elif self.estado == APROXIMAR:
            control["k_distancia"] = 1.0      # llegada suave: el cubo está 16 cm más allá
        if self.estado in (SALIR, RETROCEDER, RETIRAR):
            control["cerca_mm"] = 200.0       # punto detrás: marcha atrás, sin dar la vuelta
        llego, izquierda, derecha, distancia, error = hacia_punto(
            pred, destino, cell, self.modelo, **control)
        self._informar(distancia, error, izquierda, derecha)
        if not llego:
            return self._mover(ahora, izquierda, derecha)
        if intermedio:
            self.puntos.pop(0)
            return
        siguiente = {APROXIMAR: ALINEAR, RETIRAR: ENTREGADO}.get(self.estado, PLANIFICAR)
        if siguiente == ALINEAR:
            self.estado = ALINEAR             # gira enseguida; verifica al terminar
        else:
            self._parar_y_pasar(siguiente)

    def _alinear(self, ahora, pred, cubo, meta):
        error = giro_corto(rumbo(cubo, meta) - pred["theta"])
        self._informar(None, error, 0.0, 0.0)
        if abs(error) <= self.alinear_deg:
            self.tras = ALINEAR
            return self._parar_y_pasar(VERIFICAR)
        w_max = self.control.get("w_max", 120.0)
        w = max(-w_max, min(w_max, self.control.get("kp_giro", 2.5) * error))
        izquierda, derecha = self.modelo.potencias(0.0, w, self.control.get("limite", 0.35))
        self._mover(ahora, izquierda, derecha)

    def _empujar(self, ahora, mensaje, centro, pred, cubo, meta, cell):
        adelante, lateral = relativo(centro, cubo, cell)        # visto: cubo frente al rover
        # Sólo un cubo visto en la MISMA imagen que el rover dice dónde toca;
        # uno viejo parece más cerca (el rover ya avanzó con él).
        fresco = self.cubo_viejo_ms <= 100
        en_contacto = adelante < self.contacto_mm + 15.0
        if fresco:
            if 60.0 < adelante < self.contacto_mm and abs(lateral) < 40.0:
                self.contacto_mm = adelante   # toca más cerca de lo supuesto
            if en_contacto:
                # Antes de tocarlo, un desvío lateral es sobre todo ruido del
                # ángulo (5° a 16 cm son 14 mm); pegado, es el cubo resbalando.
                if abs(lateral) > self.lateral_max_mm:
                    return self._retroceder(pred, cell, "cubo_desviado")
                self.lateral_contacto = lateral
        self.en_contacto = en_contacto
        self.ultimo["cubo_estimado"] = not fresco
        # Lo que el rover avanzó y la visión aún no muestra empuja al cubo.
        avance = relativo(centro, pred, cell)[0]
        if en_contacto:
            # Pegado al frente: el cubo está donde está el frente del rover,
            # aunque la cámara lo haya visto hace rato o lo esté perdiendo.
            cubo_pred = punto_relativo(centro, self.contacto_mm + max(0.0, avance),
                                       self.lateral_contacto, cell)
        else:
            # Aún no lo toca: primero se come el hueco que queda hasta él.
            empujado = max(0.0, avance - (adelante - self.contacto_mm))
            cubo_pred = desplazar({"col": cubo["col"], "row": cubo["row"], "theta": centro["theta"]},
                                  empujado, cell)
        resto = relativo(pred, meta, cell)[0] - relativo(pred, cubo_pred, cell)[0]
        lejos = _norma(meta["col"] - cubo_pred["col"], meta["row"] - cubo_pred["row"]) * cell
        # Cerca del centro de la zona el rumbo hacia él salta con un mm de
        # desvío lateral: ahí se sigue derecho (la zona tolera ±57 mm de lado).
        error = giro_corto(rumbo(cubo_pred, meta) - pred["theta"]) if lejos > 50 else 0.0
        self._informar(None, error, 0.0, 0.0)
        self.ultimo["resto_mm"] = round(resto)
        if abs(error) > self.desvio_max_deg:
            return self._retroceder(pred, cell, "desalineado")
        sesgo = 0.0 if self.submeta is not None else self.sesgo_mm
        if resto <= self.tolerancia_empuje_mm + sesgo:
            self.tras = EMPUJAR
            return self._parar_y_pasar(VERIFICAR)
        estorbo = obstaculo_en_camino(mensaje, pred, desplazar(pred, resto, cell), self.radio_mm,
                                      0.0, excluir=self.color, propio=self.robot_id)
        if estorbo is not None:
            self.ultimo["estorbo"] = estorbo
            return self._retroceder(pred, cell, "estorbo")
        v = max(self.control.get("v_min", 90.0), min(self.v_empuje, 1.6 * resto))
        v *= max(0.0, math.cos(math.radians(error)))
        w = max(-self.w_empuje, min(self.w_empuje, self.kp_empuje * error))
        izquierda, derecha = self.modelo.potencias(v, w, self.control.get("limite", 0.35))
        self.ultimo["cmd"] = [round(izquierda, 3), round(derecha, 3)]
        self._mover(ahora, izquierda, derecha)

    def _verificar(self, mensaje, centro, t_obs, cubo, deposito, cell):
        if not self._tras_parada(t_obs):
            return
        adentro, falta = cubo_en_su_zona(cubo, deposito, mensaje["depot_size"], mensaje["grid"],
                                         mensaje["cube_side"])
        self.ultimo["falta_mm"] = round(falta * cell)
        if adentro:
            return self._retirar(centro, cubo, cell)
        meta = self.submeta or deposito
        error = giro_corto(rumbo(cubo, meta) - centro["theta"])
        if self.tras == ALINEAR:
            # Dónde quedó el rover respecto de la línea de empuje.
            linea = {"col": cubo["col"], "row": cubo["row"], "theta": rumbo(cubo, meta)}
            atras, desvio = relativo(linea, centro, cell)
            self.ultimo["linea_mm"] = round(desvio)
            if abs(desvio) > self.linea_max_mm or atras > -self.contacto_mm:
                return self._parar_y_pasar(PLANIFICAR)
            if abs(error) > 2 * self.alinear_deg:
                self.alineaciones += 1
                if self.alineaciones > 6:
                    return self._abortar("no_alinea")
                self.estado = ALINEAR
                return
            estorbo = corredor_bloqueado(mensaje, self.color, cubo, meta, centro, self.robot_id,
                                         self.contacto_mm, self.radio_mm, self.holgura_mm)
            if estorbo is not None:
                self.ultimo["estorbo"] = estorbo  # algo se movió: buscar otro empuje
                return self._parar_y_pasar(PLANIFICAR)
            self.estado = EMPUJAR
            return
        # Tras un empuje que no dejó el cubo dentro: seguir si sigue en línea.
        adelante, lateral = relativo(centro, cubo, cell)
        resto = relativo(centro, meta, cell)[0] - adelante
        if self.submeta is not None and resto <= 30:
            # Reubicado: ahora sí hay sitio detrás para ir a la zona.
            self.submeta = None
            self.descartadas = []
            return self._retroceder(centro, cell, "reubicado")
        self.empujes += 1
        if (resto > self.tolerancia_empuje_mm and abs(lateral) <= self.lateral_max_mm
                and abs(error) <= self.desvio_max_deg and self.empujes < self.max_empujes):
            self.estado = EMPUJAR
            return
        self._retroceder(centro, cell, "cubo_fuera_de_zona")

    # ------------------------------------------------------------ auxiliares
    def _reubicacion(self, mensaje, escena, cubo, deposito, cell):
        """Dónde dejar el cubo para que después quepa el rover detrás, rumbo a su zona.

        Se prueban direcciones cada 15°, primero las más parecidas a la de la
        zona, y empujes de 10 a 50 cm. Mismos márgenes que el planificador
        (scene con la holgura justa). Pegado a una pared el único empuje
        posible es casi paralelo a ella: si ninguno deja sitio detrás de una
        vez, se acepta el que deja al cubo con más direcciones de empuje
        posibles (lejos de paredes y rincones) y se repite desde ahí.
        """
        libre = self.planner.scene(escena)
        # Para el "después" el cubo ya no está donde está ahora.
        sin_cubo = dict(mensaje)
        sin_cubo["cubes"] = [c for c in mensaje["cubes"] if c["color"] != self.color]
        despejado = self.planner.scene(_Escena(sin_cubo, self.robot_id, escena.centro))
        grid = mensaje["grid"]
        borde = mensaje["cube_side"] * 0.7072 + 10.0 / cell

        def libertad(p):
            """Direcciones (cada 15°) desde las que cabe el rover para empujarlo."""
            cuenta = 0
            for a in range(0, 360, 15):
                q = desplazar({"col": p["col"], "row": p["row"], "theta": a}, -self.aproximacion_mm, cell)
                if self.planner.free_segment(despejado, (q["col"], q["row"]), (q["col"], q["row"])):
                    cuenta += 1
            return cuenta

        mejor, mejor_libertad = None, libertad(cubo)
        hacia = rumbo(cubo, deposito)
        for angulo in sorted(range(0, 360, 15), key=lambda a: abs(giro_corto(a - hacia))):
            if angulo in self.descartadas:
                continue
            linea = {"col": cubo["col"], "row": cubo["row"], "theta": angulo}
            atras = desplazar(linea, -self.aproximacion_mm, cell)
            if not self.planner.free_segment(libre, (atras["col"], atras["row"]), (atras["col"], atras["row"])):
                continue
            for largo in (100.0, 150.0, 200.0, 300.0, 400.0, 500.0):
                nuevo = desplazar(linea, largo, cell)
                if not (borde <= nuevo["col"] <= grid["cols"] - borde
                        and borde <= nuevo["row"] <= grid["rows"] - borde):
                    break
                despues = punto_detras(nuevo, deposito, self.aproximacion_mm, cell)
                if despues is None:
                    continue
                if corredor_bloqueado(mensaje, self.color, cubo, nuevo, atras, self.robot_id,
                                      self.contacto_mm, self.radio_mm, self.holgura_mm) is not None:
                    continue
                q = (despues["col"], despues["row"])
                listo = self.planner.free_segment(despejado, q, q) and corredor_bloqueado(
                    mensaje, self.color, nuevo, deposito, despues, self.robot_id,
                    self.contacto_mm, self.radio_mm, self.holgura_mm) is None
                if listo:
                    self.angulo_submeta = angulo
                    return {"col": nuevo["col"], "row": nuevo["row"]}
                margen = libertad(nuevo)
                if margen > mejor_libertad:
                    mejor, mejor_libertad = ({"col": nuevo["col"], "row": nuevo["row"]}, angulo), margen
        if mejor is None:
            return None
        self.angulo_submeta = mejor[1]
        return mejor[0]

    def _retroceder(self, pose, cell, motivo):
        self.ultimo["retroceso"] = motivo
        self.puntos = [desplazar(pose, -self.retroceso_mm, cell)]
        self.estado = RETROCEDER

    def _retirar(self, centro, cubo, cell):
        cerca = _norma(cubo["col"] - centro["col"], cubo["row"] - centro["row"]) * cell
        if cerca >= self.aproximacion_mm:
            return self._parar_y_pasar(ENTREGADO)
        self.puntos = [desplazar(centro, -self.retroceso_mm, cell)]
        self.estado = RETIRAR

    def _tras_parada(self, t_obs):
        """¿La imagen refleja al rover ya detenido?"""
        return t_obs - self.modelo.retraso_ms >= self.parada_ms

    def _informar(self, distancia, error, izquierda, derecha):
        self.ultimo.update(d_mm=None if distancia is None else round(distancia),
                           err_deg=round(error, 1), cmd=[round(izquierda, 3), round(derecha, 3)],
                           escalas=[round(self.modelo.escala_lineal, 2),
                                    round(self.modelo.escala_giro, 2)])

    def _mover(self, ahora, izquierda, derecha):
        try:
            self.motores.set_motor(izquierda, derecha)
        except ValueError as error:
            return self._abortar("motores: {}".format(error))
        self.predictor.registrar(ahora, izquierda, derecha)

    def _esperar(self, ahora, motivo):
        self._parar()
        if self.espera_desde is None:
            self.espera_desde = ahora
            if self.estado not in (PLANIFICAR, VERIFICAR):
                self.esperas += 1             # paradas en marcha (las que se notan)
        self.ultimo["espera"] = motivo
        if ahora - self.espera_desde > self.espera_max_ms:
            self._abortar(motivo)

    def _parar(self):
        self.motores.stop("mision")
        self.predictor.registrar(self.reloj(), 0.0, 0.0)

    def _parar_y_pasar(self, estado):
        self._parar()
        self.parada_ms = self.reloj()
        self.estado = estado

    def _abortar(self, motivo):
        self._parar()
        self.estado, self.motivo = ABORTADO, motivo
