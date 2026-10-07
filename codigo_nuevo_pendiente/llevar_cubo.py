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

from autonomia import (ALCANCE_GIRO_MM, Adaptador, _norma, _sentido_para_girar, distancia_a_segmento,
                       girar_por_el_otro_lado, giro_corto, hacia_punto, obstaculo_en_camino)
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


def memoria_libre():
    """En la placa: junta la basura y devuelve los bytes libres. En la PC: None."""
    import gc
    if not hasattr(gc, "mem_free"):
        return None
    gc.collect()
    return gc.mem_free()


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


def entregado(cubo, depot, mensaje):
    """¿Ya cuenta? Manda el árbitro (`in_depot`, protocolo v3); la cuenta propia
    es un poco más estricta que la suya, así que si dice adentro, él también."""
    if cubo.get("in_depot") is True:
        return True
    if "in_depot" in cubo and cubo.get("age_ms", 0) > 500:
        # Tapado (un rover al lado lo oculta): su posición es la última vista
        # y el árbitro no lo cuenta. La cuenta propia con esa posición vieja
        # lo daba por entregado y nadie volvía a buscarlo (cancha 3-oct).
        return False
    return cubo_en_su_zona(cubo, depot, mensaje["depot_size"], mensaje["grid"], mensaje["cube_side"])[0]


def entregados(mensaje, excluir=None):
    """Colores de los cubos que ya están dentro de su zona (menos `excluir`)."""
    salida = []
    for cubo in mensaje.get("cubes", ()):
        if cubo["color"] != excluir:
            zona = buscar(mensaje.get("depots", ()), "color", cubo["color"])
            if zona is not None and entregado(cubo, zona, mensaje):
                salida.append(cubo["color"])
    return salida


def corredor_bloqueado(mensaje, color, cubo, meta, rover, robot_id, contacto_mm,
                       radio_rover_mm=85.0, holgura_mm=10.0, ancho_mm=None):
    """Lo que estorba el empuje recto: el tramo del cubo y el del cuerpo del rover.

    Empujando el rover va recto: de costado ocupa su medio ancho (`ancho_mm`),
    no el radio del círculo en que gira (cancha 3-oct y generador oficial: con
    cubos a 5-6 casillas el radio trababa todo y nadie entregaba nada).
    """
    cell = mensaje["grid"]["cell_mm"]
    medio_cubo = mensaje["cube_side"] * cell * 0.7072
    dc, dr = meta["col"] - cubo["col"], meta["row"] - cubo["row"]
    largo = _norma(dc, dr)
    if largo < 1e-6:
        return None
    fin_rover = (meta["col"] - dc / largo * contacto_mm / cell,
                 meta["row"] - dr / largo * contacto_mm / cell)
    ancho = radio_rover_mm if ancho_mm is None else ancho_mm
    tramos = (((cubo["col"], cubo["row"]), (meta["col"], meta["row"]), medio_cubo),
              ((rover["col"], rover["row"]), fin_rover, ancho))
    for grupo, nombre in (("cubes", "cubo"), ("obstacles", "obstaculo"), ("rovers", "rover")):
        for item in mensaje.get(grupo, ()):
            if grupo == "cubes" and item["color"] == color:
                continue
            if grupo == "rovers" and item["id"] == robot_id:
                continue
            medio = radio_rover_mm if grupo == "rovers" else medio_cubo
            for a, b, tamano in tramos:
                if grupo == "rovers" and tamano == ancho:
                    tamano = radio_rover_mm       # contra el otro rover, círculo completo
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

    def __init__(self, mensaje, robot_id, centro, hechos=()):
        self.message, self.robot_id, self.centro = mensaje, robot_id, centro
        self.seq = mensaje["seq"]
        # Los ya entregados (menos el que se lleva): el planificador les deja
        # el alcance de las horquillas (RoutePlanner.entregado_mm). Los calcula
        # quien la crea: aquí dentro la pila de la placa pasaba de 173 a 181.
        self.entregados = hechos

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
                 espera_max_ms=3000, max_ms=150000, max_replanes=10, max_empujes=8, atasco_ms=2000,
                 aproximacion_mm=160.0, contacto_mm=110.0, radio_mm=85.0, holgura_mm=10.0,
                 holgura_ruta_mm=25.0, paso_ruta=2, borde_mm=25.0, retroceso_mm=80.0, v_empuje=120.0, w_empuje=35.0, kp_empuje=2.0,
                 lateral_max_mm=40.0, linea_ok_mm=25.0, linea_max_mm=40.0, desvio_max_deg=30.0,
                 alinear_deg=4.0, tolerancia_empuje_mm=6.0, sesgo_mm=30.0, cubo_ciego_ms=3500,
                 previo_mm=70.0, sensores=None, us_contacto_mm=45.0, us_libre_mm=None,
                 espera_compa_ms=3000, max_cesiones=10, borde_arriba_mm=60.0,
                 frente_mm=80.0, cola_mm=20.0, medio_ancho_mm=45.0, ceder_paso=True,
                 retiro_mm=200.0, alcance_giro_mm=ALCANCE_GIRO_MM, **control):
        self.vision, self.modelo, self.motores = vision, modelo, motores
        self.robot_id, self.reloj = robot_id, reloj
        self.max_edad_ms, self.espera_max_ms, self.max_ms = max_edad_ms, espera_max_ms, max_ms
        self.max_replanes, self.max_empujes = max_replanes, max_empujes
        self.atasco_ms = atasco_ms
        self.aproximacion_mm, self.contacto_inicial_mm = aproximacion_mm, contacto_mm
        self.radio_mm, self.holgura_mm, self.paso_ruta = radio_mm, holgura_mm, paso_ruta
        # El centro puede llegar a 25 mm del borde: el rover se asoma fuera para
        # empujar un cubo pegado a la orilla (cancha 2-oct: dos cubos en rincones
        # sin sitio detras con el margen de un objeto, 95 mm). Con 10 mm el
        # rover 11 se salió de la vista de la cámara (3-oct); con 25 el
        # marcador queda dentro aunque se pase ~30 mm al frenar (simulador:
        # 102/120 cubos con 25 mm, 103 con 10, 98 con 40).
        self.borde_mm = borde_mm
        # El borde de arriba (lado 0-1, el de la zona verde) es el más lejano
        # a la cámara: ahí el marcador deja de verse a ~40 mm de la línea. Tres
        # rovers perdidos en la fila 1,7-1,8 (3-oct, 16:50, 19:25 y antes);
        # con 60 mm el centro queda en la fila 3 y, aun pasándose, se ve.
        self.borde_arriba_mm = borde_arriba_mm
        # Forma real alrededor del centro de giro (paletas a 9 cm de la cola,
        # 8 cm de rueda a rueda; tocando, el centro del cubo queda a 110 mm):
        # las paletas a frente_mm delante, la cola a cola_mm detrás y
        # medio_ancho_mm a cada lado. El radio (85 mm) es sólo para girar.
        self.frente_mm, self.cola_mm, self.medio_ancho_mm = frente_mm, cola_mm, medio_ancho_mm
        self.ceder_paso = ceder_paso          # el de ID mayor se aparta si los dos se estorban
        self.holgura_ruta_mm = holgura_ruta_mm
        self.retroceso_mm = retroceso_mm
        # Tras entregar, marcha atrás hasta que el centro quede a retiro_mm del
        # cubo, medido por la cámara, y recién ahí puede girar: con 80 mm fijos
        # el 11 quedó a ~13-16 cm, giró y barrió el rojo fuera de la zona
        # (cancha 4-oct 18:58). Girando, las paletas llegan a ~92 mm del centro.
        # Girando, las horquillas llegan a alcance_giro_mm del centro (no los
        # ~92 mm de la cara del frente): el retiro deja al cubo fuera de ese
        # círculo, y las rutas, a los ya entregados (cancha 5-oct).
        self.alcance_giro_mm = alcance_giro_mm
        self.retiro_mm = max(retiro_mm, alcance_giro_mm + 42.4 + 10.0)   # + media diagonal del cubo
        self.v_empuje, self.w_empuje, self.kp_empuje = v_empuje, w_empuje, kp_empuje
        self.lateral_max_mm, self.linea_max_mm = lateral_max_mm, linea_max_mm
        # Fuera de la línea de empuje: hasta linea_ok se alinea con la línea;
        # hasta linea_max se mira al centro del cubo y se empuja igual (el
        # rumbo se corrige empujando); más, se replanifica.
        self.linea_ok_mm = linea_ok_mm
        self.mirar_cubo = False
        self.desvio_max_deg, self.alinear_deg = desvio_max_deg, alinear_deg
        self.tolerancia_empuje_mm = tolerancia_empuje_mm
        # Pasarse de la zona no tiene arreglo (no se puede tirar del cubo) y
        # quedarse corto sí (VERIFICAR lo vuelve a empujar): el empuje para
        # antes del centro. Con 5 mm el 11 dejó el azul 56 mm más allá del
        # centro, fuera (cancha 4-oct 18:58, a ~170 mm/s); la zona da ±45 mm.
        self.sesgo_mm = sesgo_mm
        # Empujando, la cámara a veces pierde el cubo pegado al rover: se
        # sigue con el cubo estimado en el frente hasta este tiempo.
        self.cubo_ciego_ms = cubo_ciego_ms
        # Punto de paso `previo_mm` antes del de ataque, en la misma línea:
        # el último tramo llega ya alineado y sin rodear el punto final.
        self.previo_mm = previo_mm
        # Si lo único que impide el empuje es el OTRO rover, esperar a que pase
        # hasta este tiempo en vez de reubicar el cubo: cancha 3-oct, el 11
        # cruzó por debajo del verde, el 10 lo rodeó por el borde de arriba
        # y la cámara lo perdió (sin el 11 entregaba en 7 s). Si no se va,
        # se suelta el cubo (la ronda espera 2 s y sigue con otro): reubicarlo
        # por culpa del compañero sacó el verde de la cancha (3-oct 17:18).
        # Tras max_cesiones seguidas con el mismo cubo (~50 s: el otro roto
        # ahí) se vuelve a reubicar como antes. Con 3 (~15 s) bastó que el 10
        # se quedara atascado 20 s para que el 11 reubicara el azul y lo
        # paseara por media cancha (3-oct 19:01).
        self.espera_compa_ms = espera_compa_ms
        self.max_cesiones = max_cesiones
        self.cesiones = {}                    # color -> veces que se soltó por el compañero
        # El compañero ya terminó y no lleva nada (lo dice la ronda, por radio):
        # cederle el paso no sirve, no va a pasar; se lo espera mientras se aparta.
        self.compa_quieto = False
        # Ultrasonido frontal (opcional, nunca bloquea): <= us_contacto_mm
        # confirma que toca el cubo. La alarma "el cubo se escapó" (lejos de
        # golpe, us_libre_mm) está APAGADA por defecto: en la cancha (1-oct)
        # el sensor en marcha saltaba de 32-44 mm a 1,7-1,9 m con el cubo
        # todavía delante y provocaba retrocesos en falso.
        self.sensores = sensores
        self.us_contacto_mm, self.us_libre_mm = us_contacto_mm, us_libre_mm
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
        self.historial = []                   # (t_obs, centro) de los últimos ~2,5 s
        self.destapes = 0
        self.ref_atasco = None                # (ms, pose) desde que no se mueve
        self.atascos = 0
        self.orden = (0.0, 0.0)               # última potencia mandada a los motores
        self.us_lejos = 0
        self.us_vio_cubo = False              # en este empuje lo vio pegado
        self.correccion = False               # [previo, detrás] sin A*: llegar por la línea
        self.estrecho = False                 # último tramo de una entrada lateral (ancho real)
        self.espera_compa_desde = None        # esperando que el compañero despeje
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
        cell = mensaje["grid"]["cell_mm"]
        centro = self.modelo.centro_desde_marcador(rover, cell)
        if not self.historial or self.historial[-1][0] != t_obs:
            self.historial.append((t_obs, centro))
            while self.historial[0][0] < t_obs - 2500:
                self.historial.pop(0)
        cubo = buscar(mensaje["cubes"], "color", self.color)
        if cubo is None:
            return self._esperar(ahora, "cubo_no_visible")
        # Un cubo que la cámara dejó de ver llega con su ÚLTIMA posición y la
        # edad creciendo (contrato, sección 6): >0 = posición más vieja que
        # la del rover en la misma imagen.
        self.cubo_viejo_ms = cubo["age_ms"] - rover["age_ms"]
        if cubo["age_ms"] > self.max_edad_ms and self.estado in (PLANIFICAR, APROXIMAR, ALINEAR,
                                                                 VERIFICAR, EMPUJAR):
            if self.estado == EMPUJAR and self.en_contacto and cubo["age_ms"] <= self.cubo_ciego_ms:
                pass                          # se sigue con el cubo estimado en el frente
            elif self.estado == EMPUJAR and self.en_contacto:
                # Demasiado a ciegas: parar y mirar (VERIFICAR destapa si hace falta).
                self.tras = EMPUJAR
                return self._parar_y_pasar(VERIFICAR)
            elif self.estado == VERIFICAR and cubo["age_ms"] > 1200 and self.destapes < 4:
                # Parado pegado al cubo, el propio rover puede taparlo ante la
                # cámara: retroceder un poco para que vuelva a verse.
                self.destapes += 1
                self.espera_desde = None
                return self._retroceder(centro, cell, "cubo_tapado")
            else:
                return self._esperar(ahora, "cubo_no_visible")
        deposito = buscar(mensaje.get("depots", ()), "color", self.color)
        if deposito is None:
            return self._abortar("sin_zona_" + self.color)
        meta = self.submeta or deposito       # submeta: reubicar un cubo pegado a la pared
        self.espera_desde = None
        self.ultimo.pop("espera", None)
        self.adaptador.observar(self.predictor, t_obs, centro, cell)
        self.ultimo["edad_ms"] = round(ahora - t_obs)
        if self._atascado(ahora, centro, cell):
            return
        if self.estado == PLANIFICAR:
            return self._planificar(mensaje, centro, t_obs, cubo, deposito, cell)
        if self.estado == VERIFICAR:
            return self._verificar(mensaje, centro, t_obs, cubo, deposito, cell)
        pred = self.predictor.predecir(centro, t_obs - self.modelo.retraso_ms, ahora, cell)
        if self.estado == EMPUJAR:
            return self._empujar(ahora, mensaje, centro, t_obs, pred, cubo, meta, cell)
        if self.estado == ALINEAR:
            return self._alinear(ahora, pred, cubo, meta)
        self._seguir(ahora, mensaje, pred, cubo, cell)

    # ------------------------------------------------------------ fases
    def _planificar(self, mensaje, centro, t_obs, cubo, deposito, cell):
        if not self._tras_parada(t_obs - max(0, self.cubo_viejo_ms)):
            return                            # rover Y cubo vistos ya parado
        if entregado(cubo, deposito, mensaje):
            return self._retirar(centro, cubo, cell)
        meta = self.submeta or deposito
        if self.replanes >= self.max_replanes:
            return self._abortar("demasiados_intentos")
        self.replanes += 1
        self.ultimo["mem"] = memoria_libre()    # parado: buen momento para juntar basura
        detras = punto_detras(cubo, meta, self.aproximacion_mm, cell)
        if detras is None:
            return self._abortar("cubo_sobre_el_centro_de_la_zona")
        self.preparar()
        escena = _Escena(mensaje, self.robot_id, centro)
        estorbo = corredor_bloqueado(mensaje, self.color, cubo, meta, detras, self.robot_id,
                                     self.contacto_mm, self.radio_mm, self.holgura_mm,
                                     self.medio_ancho_mm)
        self.correccion = False
        self.estrecho = False
        cerca = _norma(detras["col"] - centro["col"], detras["row"] - centro["row"]) * cell
        if estorbo is None and cerca < 120:
            # Ya está junto al punto de ataque pero fuera de la línea: una
            # ruta A* llegaría de lado y lo que el rover desliza al parar
            # (rover 11: ~30 mm) lo dejaría otra vez fuera (cancha 2-oct, tres
            # veces seguidas). Marcha atrás hasta el punto previo y recto,
            # por la línea, hasta el de ataque.
            previo = punto_detras(cubo, meta, self.aproximacion_mm + self.previo_mm, cell)
            libre = self.planner.scene(escena)
            q = (previo["col"], previo["row"])
            if self.planner.free_segment(libre, q, q) and salida_sin_acercarse(
                    mensaje, centro, previo, self.robot_id, self.radio_mm):
                self.puntos = [previo, detras]
                self.correccion = True
                self.estado = APROXIMAR
                self.espera_compa_desde = None
                return
        if estorbo is not None:
            motivo = "corredor_bloqueado: " + estorbo
        else:
            # Primero con margen holgado: el rover real se aparta unos cm de la
            # línea y recorta las esquinas, y la red de seguridad lo pararía.
            # Si así no cabe (cubos juntos), con el margen justo.
            previo = punto_detras(cubo, meta, self.aproximacion_mm + self.previo_mm, cell)
            self.planner.clearance = self.holgura_ruta_mm
            ruta = self.planner.plan(escena, previo)
            if ruta["estado"] == "RUTA":
                # Último tramo por la línea de empuje: llega alineado.
                self.puntos = ruta["puntos"][1:] + [detras]
                self.estado = APROXIMAR
                self.espera_compa_desde = None
                return
            for holgura in (self.holgura_ruta_mm, self.holgura_mm):
                self.planner.clearance = holgura
                ruta = self.planner.plan(escena, detras)
                if ruta["estado"] == "RUTA":
                    self.puntos = ruta["puntos"][1:] or [detras]
                    self.estado = APROXIMAR
                    self.espera_compa_desde = None
                    return
            if ruta["motivo"] == "origen_sin_espacio":
                return self._salir(mensaje, escena, centro, cell)
            motivo = "sin_ruta: " + str(ruta["motivo"])
            # El punto de ataque cabe con la forma real pero no con el círculo
            # (otro cubo detrás o al lado): llegar de costado a un punto libre,
            # recto hasta él y girar ahí donde las paletas no tocan nada. El
            # A* se llama desde aquí y no desde un método aparte: en la placa
            # la pila de Python es de ~1,5 KB (cancha 3-oct: "pystack exhausted").
            for p in self._entradas(mensaje, escena, cubo, meta, detras, centro, cell):
                self.planner.clearance = self.holgura_mm
                ruta = self.planner.plan(escena, p)
                if ruta["estado"] == "RUTA":
                    self.ultimo["entrada"] = [round(p["col"], 1), round(p["row"], 1)]
                    self.puntos = ruta["puntos"][1:] + [{"col": detras["col"], "row": detras["row"]}]
                    self.estrecho = True
                    self.estado = APROXIMAR
                    self.espera_compa_desde = None
                    return
        # ¿Estorba sólo el otro rover? Sin él, ¿se llegaría? (A* desde aquí, ver arriba)
        p = self._sin_compa(mensaje, cubo, meta, detras)
        if p is not None:
            p = _Escena(p, self.robot_id, centro, escena.entregados)
            self.planner.clearance = self.holgura_ruta_mm
            ruta = self.planner.plan(p, punto_detras(cubo, meta, self.aproximacion_mm + self.previo_mm, cell))
            # Pegado a algo al arrancar no es "no cabe": de ahí se sale (SALIR).
            if ruta["estado"] != "RUTA" and ruta["motivo"] != "origen_sin_espacio":
                # Cancha 3-oct 19:25: el previo caía junto a otro cubo y sólo el
                # punto de ataque estaba libre (lo ocupaba el 10): reubicó en
                # vez de esperar y terminó perdido en el borde de arriba.
                self.planner.clearance = self.holgura_mm
                ruta = self.planner.plan(p, detras)
            if (ruta["estado"] == "RUTA" or ruta["motivo"] == "origen_sin_espacio") and self._esperar_compa(mensaje):
                return
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
        if self.estado == APROXIMAR and len(self.puntos) > 1 and not self.correccion:
            # Si ya está más cerca del siguiente punto que el actual, éste ya
            # quedó atrás: no volver a buscarlo (daba vueltas a su alrededor).
            a, b = self.puntos[0], self.puntos[1]
            if (_norma(b["col"] - pred["col"], b["row"] - pred["row"])
                    <= _norma(b["col"] - a["col"], b["row"] - a["row"])):
                self.puntos.pop(0)
        destino = self.puntos[0]
        if self.estado == APROXIMAR:
            estrecho = self.estrecho and len(self.puntos) == 1
            estorbo = obstaculo_en_camino(mensaje, pred, destino, self.radio_mm, 0.0,
                                          excluir=self.color, propio=self.robot_id,
                                          ancho_mm=self.medio_ancho_mm if estrecho else None)
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
        if intermedio and self.correccion:
            # El previo de una corrección: justo (queda sobre la línea) y, si
            # está detrás, marcha atrás en vez de dar la vuelta.
            control["tolerancia_mm"] = 20.0
            control["cerca_mm"] = 200.0
        elif intermedio:
            # De paso: margen amplio y, si hay que girar mucho, girar en el
            # sitio en vez de avanzar en curva cerrada alrededor del punto.
            control["tolerancia_mm"] = 40.0
            control["cerca_mm"] = 0.0
        elif self.estado == APROXIMAR:
            control["k_distancia"] = 1.0      # llegada suave: el cubo está 16 cm más allá
        if self.estado in (SALIR, RETROCEDER, RETIRAR):
            control["cerca_mm"] = 200.0       # punto detrás: marcha atrás, sin dar la vuelta
        llego, izquierda, derecha, distancia, error = hacia_punto(
            pred, destino, cell, self.modelo, **control)
        if not llego and abs(error) > control.get("giro_en_sitio", 40.0):
            # Va a girar en el sitio: si las horquillas alcanzan un cubo ya
            # entregado, primero alejarse en recto. Simulador con horquillas:
            # el retiro se cortaba (otro cubo detrás) y la misión siguiente
            # giraba a 10 cm del rojo y lo sacaba de la zona (cancha 5-oct, igual).
            hechos = entregados(mensaje, self.color)
            sentido = _sentido_para_girar(mensaje, pred, hechos, self.alcance_giro_mm) if hechos else 0
            if sentido:
                izquierda, derecha = self.modelo.potencias(sentido * control.get("v_min", 90.0), 0.0,
                                                           control.get("limite", 0.35))
                self.ultimo["despeje"] = sentido
            else:
                # Los demás cubos, y el propio mientras va de paso (en el último
                # tramo se le llega de frente): girar por el lado que no los toca.
                propio = self.color if self.estado == APROXIMAR and len(self.puntos) == 1 else None
                otro_lado = girar_por_el_otro_lado(mensaje, pred, error, self.modelo, control, propio)
                if otro_lado is not None:
                    izquierda, derecha = otro_lado
                    self.ultimo["giro"] = "otro_lado"
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

    def _rumbo_empuje(self, pose, cubo, meta):
        """Hacia dónde mirar para empujar: la línea cubo->zona, o el centro del cubo."""
        return rumbo(pose, cubo) if self.mirar_cubo else rumbo(cubo, meta)

    def _alinear(self, ahora, pred, cubo, meta):
        error = giro_corto(self._rumbo_empuje(pred, cubo, meta) - pred["theta"])
        self._informar(None, error, 0.0, 0.0)
        if abs(error) <= self.alinear_deg:
            self.tras = ALINEAR
            return self._parar_y_pasar(VERIFICAR)
        w_max = self.control.get("w_max", 120.0)
        w = max(-w_max, min(w_max, self.control.get("kp_giro", 2.5) * error))
        izquierda, derecha = self.modelo.potencias(0.0, w, self.control.get("limite", 0.35))
        self._mover(ahora, izquierda, derecha)

    def _empujar(self, ahora, mensaje, centro, t_obs, pred, cubo, meta, cell):
        # El cubo se compara con la pose del rover del MISMO instante en que
        # la cámara lo vio: con una posición vieja contra la pose actual
        # parecería más cerca y centrado (el rover ya avanzó con él).
        visto = self._pose_en(t_obs - self.cubo_viejo_ms)
        fresco = visto is not None
        base = visto if fresco else centro    # pose del rover cuando se vio el cubo
        adelante, lateral = relativo(base, cubo, cell)
        # Lo que el rover avanzó desde que se vio el cubo hasta la última
        # imagen (recorrido) y hasta ahora, predicho (avance).
        recorrido = relativo(base, centro, cell)[0]
        avance = relativo(base, pred, cell)[0]
        en_contacto = adelante - recorrido < self.contacto_mm + 15.0
        if not fresco:
            en_contacto = en_contacto or self.en_contacto
        if fresco:
            if 60.0 < adelante < self.contacto_mm and abs(lateral) < 40.0:
                self.contacto_mm = adelante   # toca más cerca de lo supuesto
            if en_contacto:
                # Antes de tocarlo, un desvío lateral es sobre todo ruido del
                # ángulo (5° a 16 cm son 14 mm); pegado, es el cubo resbalando.
                if abs(lateral) > self.lateral_max_mm:
                    return self._retroceder(pred, cell, "cubo_desviado")
                self.lateral_contacto = lateral
        distancia_us = self._ultrasonido()
        if distancia_us is not None and distancia_us <= self.us_contacto_mm:
            en_contacto = True                # el sensor lo ve pegado a las paletas
            self.us_vio_cubo = True
        # Sólo cuenta "no hay nada" si en ESTE empuje el sensor ya lo vio pegado:
        # en marcha el eco puede pasar por encima del cubo (cancha 1-oct: tres
        # retrocesos en falso con el cubo avanzando delante).
        if (self.us_libre_mm is not None and en_contacto and self.us_vio_cubo
                and distancia_us is not None and distancia_us > self.us_libre_mm):
            # Creía empujarlo pero delante no hay nada: el cubo se escapó.
            self.us_lejos += 1
            if self.us_lejos >= 4:            # 200 ms seguidos: no es un eco suelto
                self.us_lejos = 0
                self.en_contacto = False
                return self._retroceder(pred, cell, "ultrasonido_sin_cubo")
        else:
            self.us_lejos = 0
        self.en_contacto = en_contacto
        self.ultimo["cubo_estimado"] = not fresco
        # Lo que el rover avanzó y la visión aún no muestra empuja al cubo.
        if en_contacto:
            # Pegado al frente: el cubo está donde está el frente del rover,
            # aunque la cámara lo haya visto hace rato o lo esté perdiendo.
            cubo_pred = punto_relativo(centro, self.contacto_mm + max(0.0, relativo(centro, pred, cell)[0]),
                                       self.lateral_contacto, cell)
        else:
            # Aún no lo toca: primero se come el hueco que quedaba hasta él.
            empujado = max(0.0, avance - (adelante - self.contacto_mm))
            cubo_pred = desplazar({"col": cubo["col"], "row": cubo["row"], "theta": base["theta"]},
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
        # El margen, sólo en el primer empuje (el largo, el que se pasa): si
        # quedó corto, los siguientes son cortos y suaves y van al centro.
        sesgo = 0.0 if self.submeta is not None or self.empujes else self.sesgo_mm
        if resto <= self.tolerancia_empuje_mm + sesgo:
            self.tras = EMPUJAR
            return self._parar_y_pasar(VERIFICAR)
        estorbo = obstaculo_en_camino(mensaje, pred, desplazar(pred, resto, cell), self.radio_mm,
                                      0.0, excluir=self.color, propio=self.robot_id,
                                      ancho_mm=self.medio_ancho_mm)
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
        # El cubo también tiene que verse DESPUÉS de parar: una posición
        # vieja del cubo es de antes de que el rover terminara de empujarlo.
        if not self._tras_parada(t_obs - max(0, self.cubo_viejo_ms)):
            return
        adentro, falta = cubo_en_su_zona(cubo, deposito, mensaje["depot_size"], mensaje["grid"],
                                         mensaje["cube_side"])
        self.ultimo["falta_mm"] = round(falta * cell)
        if adentro or cubo.get("in_depot") is True:   # el árbitro tiene 2,5 mm de holgura
            return self._retirar(centro, cubo, cell)
        meta = self.submeta or deposito
        error = giro_corto(rumbo(cubo, meta) - centro["theta"])
        if self.tras == ALINEAR:
            # Dónde quedó el rover respecto de la línea de empuje.
            linea = {"col": cubo["col"], "row": cubo["row"], "theta": rumbo(cubo, meta)}
            atras, desvio = relativo(linea, centro, cell)
            self.ultimo["linea_mm"] = round(desvio)
            if abs(desvio) > self.linea_max_mm or atras > -self.contacto_mm:
                self.mirar_cubo = False
                return self._parar_y_pasar(PLANIFICAR)
            if abs(desvio) > self.linea_ok_mm and not self.mirar_cubo:
                # Unos cm fuera de la línea (cancha 1-oct: 39-44 mm, y cada
                # replanificación costaba ~3 s): mirar al centro del cubo,
                # empujarlo centrado y corregir el rumbo empujando.
                self.mirar_cubo = True
                self.estado = ALINEAR
                return
            if abs(giro_corto(self._rumbo_empuje(centro, cubo, meta) - centro["theta"])) > 3 * self.alinear_deg:  # empujando se corrige el resto
                self.alineaciones += 1
                if self.alineaciones > 6:
                    return self._abortar("no_alinea")
                self.estado = ALINEAR
                return
            estorbo = corredor_bloqueado(mensaje, self.color, cubo, meta, centro, self.robot_id,
                                         self.contacto_mm, self.radio_mm, self.holgura_mm,
                                         self.medio_ancho_mm)
            if estorbo is not None:
                self.ultimo["estorbo"] = estorbo  # algo se movió: buscar otro empuje
                return self._parar_y_pasar(PLANIFICAR)
            self.en_contacto, self.lateral_contacto = False, 0.0   # empieza a 16 cm
            self.us_vio_cubo, self.us_lejos = False, 0
            self.mirar_cubo = False
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
    def preparar(self):
        """Crea el planificador y reserva sus búferes (una vez)."""
        if self.planner is None:
            from rutas import RoutePlanner
            self.planner = RoutePlanner(self.radio_mm, self.radio_mm, self.holgura_mm,
                                        step_cells=self.paso_ruta, required_colors=(),
                                        edge_mm=self._bordes())
            self.planner.entregado_mm = self.alcance_giro_mm - self.radio_mm
            mensaje = self.vision.mensaje
            if mensaje is not None:
                grid = mensaje["grid"]
                self.planner._buffers((int(grid["cols"] // self.paso_ruta) + 1)
                                      * (int(grid["rows"] // self.paso_ruta) + 1))

    def _bordes(self):
        """Margen del centro a cada orilla, mm: (izquierda, arriba, derecha, abajo).

        La derecha, como arriba: cancha 6-oct 20:58, la cámara perdió al 10
        dos veces en la columna 40,6-41,1 (hasta 8 s). Simulador: igual."""
        lejos = max(self.borde_mm, self.borde_arriba_mm)
        return (self.borde_mm, lejos, lejos, self.borde_mm)

    def _objetos(self, mensaje, excluir=None):
        """(col, row, medio_mm, es_rover) de lo que el cuerpo no puede tocar."""
        cell = mensaje["grid"]["cell_mm"]
        medio_cubo = mensaje["cube_side"] * cell * 0.7072
        for c in mensaje.get("cubes", ()):
            if c["color"] != excluir:
                yield c["col"], c["row"], medio_cubo, False
        for o in mensaje.get("obstacles", ()):
            yield o["col"], o["row"], medio_cubo, False
        for r in mensaje.get("rovers", ()):
            if r["id"] != self.robot_id:
                yield r["col"], r["row"], self.radio_mm, True

    def _dentro_de_bordes(self, p, mensaje):
        g = mensaje["grid"]
        cell = g["cell_mm"]
        el, et, er, eb = (b / cell for b in self._bordes())
        return el <= p["col"] <= g["cols"] - er and et <= p["row"] <= g["rows"] - eb

    def _recto_libre(self, objetos, cell, a, b):
        """Yendo recto de a a b (mirando hacia b), el cuerpo no toca nada."""
        dc, dr = b["col"] - a["col"], b["row"] - a["row"]
        largo = _norma(dc, dr)
        if largo < 1e-6:
            return True
        uc, ur = dc / largo, dr / largo
        ini = (a["col"] - uc * self.cola_mm / cell, a["row"] - ur * self.cola_mm / cell)
        fin = (b["col"] + uc * self.frente_mm / cell, b["row"] + ur * self.frente_mm / cell)
        for col, row, medio, es_rover in objetos:
            propio = self.radio_mm if es_rover else self.medio_ancho_mm
            if distancia_a_segmento((col, row), ini, fin) * cell < propio + self.holgura_mm + medio:
                return False
        return True

    def _giro_libre(self, objetos, cell, punto, desde_deg, hasta_deg):
        """Girando en `punto` por el lado corto, ni paletas ni cola tocan nada."""
        error = giro_corto(hasta_deg - desde_deg)
        pasos = int(abs(error) // 10) + 1
        for i in range(pasos + 1):
            th = math.radians(desde_deg + error * i / pasos)
            c, s = math.cos(th) / cell, math.sin(th) / cell
            for adelante, izquierda in ((self.frente_mm, self.medio_ancho_mm), (self.frente_mm, 0.0),
                                        (self.frente_mm, -self.medio_ancho_mm), (30.0, self.medio_ancho_mm),
                                        (30.0, -self.medio_ancho_mm), (-self.cola_mm, self.medio_ancho_mm),
                                        (-self.cola_mm, -self.medio_ancho_mm)):
                qc = punto["col"] + adelante * c - izquierda * s
                qr = punto["row"] - adelante * s - izquierda * c
                for col, row, medio, es_rover in objetos:
                    if _norma(qc - col, qr - row) * cell < medio + self.holgura_mm:
                        return False
        return True

    def _entradas(self, mensaje, escena, cubo, meta, detras, centro, cell):
        """Hasta 4 puntos de entrada lateral al de ataque, del más cercano al rover.

        Al costado (o en diagonal hacia atrás) del punto de ataque, donde el
        círculo del rover cabe y puede girar; de ahí recto al de ataque (con
        su ancho real) y girar para empujar sin tocar nada. Sin A*: lo llama
        _planificar (pila de la placa).
        """
        if not self._dentro_de_bordes(detras, mensaje):
            return []
        empuje = rumbo(cubo, meta)
        libre = self.planner.scene(escena)
        todos = list(self._objetos(mensaje))
        sin_propio = [o for o in todos if not (not o[3] and o[0] == cubo["col"] and o[1] == cubo["row"])]
        candidatos = []
        for lado in (90, -90, 135, -135, 180):
            for mm in (100, 150, 200):
                e = desplazar({"col": detras["col"], "row": detras["row"], "theta": empuje + lado}, mm, cell)
                if (self.planner.free_segment(libre, (e["col"], e["row"]), (e["col"], e["row"]))
                        and self._recto_libre(sin_propio, cell, e, detras)
                        and self._giro_libre(todos, cell, detras, rumbo(e, detras), empuje)):
                    candidatos.append((_norma(e["col"] - centro["col"], e["row"] - centro["row"]), e))
        candidatos.sort(key=lambda c: c[0])
        return [e for _, e in candidatos[:4]]

    def _salir(self, mensaje, escena, centro, cell):
        """Pegado a un borde (la salida está a 75 mm) o a un objeto: despegarse sin acercarse a nada.

        Primero recto (sin girar pegado a nada); si no alcanza, en un abanico
        alrededor del rumbo que aleja del objeto más cercano: pegado de costado
        a un cubo, ni avanzando ni retrocediendo 14 cm salía de su margen, y
        justo detrás estaba el otro rover (cancha 3-oct, rover 11).
        """
        libre = self.planner.scene(escena)
        candidatos = [(mm, None) for mm in (60, 100, 140, -60, -100, -140)]
        lejos = self._direccion_salida(mensaje, centro)
        if lejos is not None:
            candidatos += [(mm, lejos + giro) for giro in (0, 30, -30, 60, -60, 90, -90)
                           for mm in (80, 120, 160, 200)]
        for mm, rumbo_salida in candidatos:
            if rumbo_salida is None:
                p = desplazar(centro, mm, cell)
            else:
                p = desplazar({"col": centro["col"], "row": centro["row"], "theta": rumbo_salida}, mm, cell)
                p["theta"] = centro["theta"]
            q = (p["col"], p["row"])
            if self.planner.free_segment(libre, q, q) and salida_sin_acercarse(
                    mensaje, centro, p, self.robot_id, self.radio_mm):
                self.puntos = [p]
                self.estado = SALIR
                return
        self._abortar("sin_ruta: origen_sin_espacio")

    def _direccion_salida(self, mensaje, centro):
        """Rumbo (grados) que aleja del objeto más cercano, o None si no hay ninguno."""
        mejor, rumbo_salida = None, None
        for grupo in ("cubes", "obstacles", "rovers"):
            for item in mensaje.get(grupo, ()):
                if grupo == "rovers" and item["id"] == self.robot_id:
                    continue
                dc, dr = centro["col"] - item["col"], centro["row"] - item["row"]
                d = _norma(dc, dr)
                if d > 1e-6 and (mejor is None or d < mejor):
                    mejor, rumbo_salida = d, math.degrees(math.atan2(-dr, dc))
        return rumbo_salida

    def _sin_compa(self, mensaje, cubo, meta, detras):
        """El mensaje sin el otro rover si lo único que tapa el empuje es él; si no, None."""
        if self.cesiones.get(self.color, 0) >= self.max_cesiones:
            return None                       # aparcado ahí: se reubica como antes
        solo = dict(mensaje)
        solo["rovers"] = [r for r in mensaje["rovers"] if r["id"] == self.robot_id]
        if len(solo["rovers"]) == len(mensaje["rovers"]):
            return None                       # no hay compañero: es otra cosa
        if corredor_bloqueado(solo, self.color, cubo, meta, detras, self.robot_id,
                              self.contacto_mm, self.radio_mm, self.holgura_mm,
                              self.medio_ancho_mm) is not None:
            return None
        return solo

    def _esperar_compa(self, mensaje):
        """Sin el otro rover cabría: cederle el paso, esperarlo o soltar el cubo. True si hizo algo."""
        otros = [r["id"] for r in mensaje["rovers"] if r["id"] != self.robot_id]
        if self.ceder_paso and otros and self.robot_id > min(otros) and not self.compa_quieto:
            # Cede el paso el de ID mayor: se aparta y deja empujar al otro.
            # Esperando los dos a la vez (cada uno en el camino del otro) se
            # trababan para siempre (generador oficial, dificultad 0,8). Es la
            # misma regla con o sin radio. Al que ya terminó no se le cede
            # (cancha 4-oct 15:54: 10 cesiones al 10 quieto, ~85 s perdidos).
            self.cesiones[self.color] = self.cesiones.get(self.color, 0) + 1
            self._abortar("cede_paso_rover")
            return True
        ahora = self.reloj()
        if self.espera_compa_desde is None:
            self.espera_compa_desde = ahora
        if ahora - self.espera_compa_desde >= self.espera_compa_ms:
            # No se va (o nos espera a nosotros): soltar el cubo. "rover" en
            # el motivo = la ronda no lo cuenta como intento fallido.
            self.cesiones[self.color] = self.cesiones.get(self.color, 0) + 1
            self._abortar("espera_rover")
            return True
        self.replanes -= 1                    # esperar no es un intento
        self.ultimo["espera"] = "companero"
        self.proximo = ahora + 500            # no rehacer el A* en cada vuelta
        return True

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
        despejado = self.planner.scene(_Escena(sin_cubo, self.robot_id, escena.centro, escena.entregados))
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
                                      self.contacto_mm, self.radio_mm, self.holgura_mm,
                                      self.medio_ancho_mm) is not None:
                    continue
                q = (despues["col"], despues["row"])
                listo = self.planner.free_segment(despejado, q, q) and corredor_bloqueado(
                    mensaje, self.color, nuevo, deposito, despues, self.robot_id,
                    self.contacto_mm, self.radio_mm, self.holgura_mm, self.medio_ancho_mm) is None
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
        self.en_contacto, self.lateral_contacto = False, 0.0   # ya no lo toca
        self.us_vio_cubo, self.us_lejos = False, 0
        self.puntos = [self._dentro(pose, -self.retroceso_mm, cell)]
        self.estado = RETROCEDER

    def _dentro(self, pose, mm, cell):
        """Punto a `mm` (negativo: marcha atrás) que no saque al rover de la
        vista de la cámara: se acorta hasta quedar a borde_mm de la orilla
        (cancha 3-oct: el rover 11 se salió, la visión lo perdió y quedó ahí)."""
        mensaje = self.vision.mensaje
        if mensaje is None:
            return desplazar(pose, mm, cell)
        g = mensaje["grid"]
        el, et, er, eb = (b / cell for b in self._bordes())
        for parte in (1.0, 0.75, 0.5, 0.25, 0.0):
            p = desplazar(pose, mm * parte, cell)
            if el <= p["col"] <= g["cols"] - er and et <= p["row"] <= g["rows"] - eb:
                return p
        return desplazar(pose, 0.0, cell)

    def _retirar(self, centro, cubo, cell):
        cerca = _norma(cubo["col"] - centro["col"], cubo["row"] - centro["row"]) * cell
        if cerca >= self.retiro_mm:
            return self._parar_y_pasar(ENTREGADO)
        # +25: el control da por llegado a 25 mm del punto.
        self.puntos = [self._dentro(centro, -(self.retiro_mm + 25.0 - cerca), cell)]
        self.estado = RETIRAR

    def _ultrasonido(self):
        """Distancia frontal reciente en mm, o None (sin sensor, vieja o sin eco)."""
        s = self.sensores
        if s is None:
            return None
        try:
            if s.distance is None or s.age(s.distance_at) > 300:
                return None
            self.ultimo["us_mm"] = round(s.distance)
            return s.distance
        except Exception:                     # el sensor nunca detiene la misión
            return None

    def _pose_en(self, t):
        """Centro del rover observado en el instante t (±120 ms), o None."""
        mejor, error = None, 120
        for momento, pose in self.historial:
            if abs(momento - t) <= error:
                mejor, error = pose, abs(momento - t)
        return mejor

    def _tras_parada(self, t_obs):
        """¿La imagen refleja al rover ya detenido?"""
        return t_obs - self.modelo.retraso_ms >= self.parada_ms

    def _informar(self, distancia, error, izquierda, derecha):
        self.ultimo.update(d_mm=None if distancia is None else round(distancia),
                           err_deg=round(error, 1), cmd=[round(izquierda, 3), round(derecha, 3)],
                           escalas=[round(self.modelo.escala_lineal, 2),
                                    round(self.modelo.escala_giro, 2)])

    def _atascado(self, ahora, centro, cell):
        """Motores con potencia y el rover quieto en la cámara = ruedas
        patinando (contra un cubo trabado, el borde u otro rover). Seguir así
        sólo gasta batería: el 3-oct el rover 11 patinó hasta reiniciarse por
        bajo voltaje (BROWNOUT), una y otra vez. Se retrocede y se replanifica."""
        v, w = self.modelo.velocidades(*self.orden)
        if self.motores.mode is None or (abs(v) < 40 and abs(w) < 15):
            self.ref_atasco = None            # parado, o una orden que no debe mover
            return False
        if self.ref_atasco is None:
            self.ref_atasco = (ahora, centro)
            return False
        desde, pose = self.ref_atasco
        movido = _norma(centro["col"] - pose["col"], centro["row"] - pose["row"]) * cell
        if movido > 15 or abs(giro_corto(centro["theta"] - pose["theta"])) > 8:
            self.ref_atasco = (ahora, centro)
            return False
        if ahora - desde < self.atasco_ms:
            return False
        self.ref_atasco = None
        self.atascos += 1
        self.ultimo["atasco"] = self.estado
        if self.atascos > 3:
            self._abortar("atascado")
        elif self.estado in (RETROCEDER, RETIRAR):
            self._parar_y_pasar(PLANIFICAR)   # trabado hacia atrás: pensar otra cosa
        else:
            self._parar()
            self._retroceder(centro, cell, "atasco")
        return True

    def _mover(self, ahora, izquierda, derecha):
        self.orden = (izquierda, derecha)
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
        self.orden = (0.0, 0.0)
        self.motores.stop("mision")
        self.predictor.registrar(self.reloj(), 0.0, 0.0)

    def _parar_y_pasar(self, estado):
        self._parar()
        self.parada_ms = self.reloj()
        self.estado = estado

    def _abortar(self, motivo):
        self._parar()
        self.estado, self.motivo = ABORTADO, motivo
