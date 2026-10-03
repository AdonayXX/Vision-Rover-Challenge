"""Incremento 3: la ronda completa, sola, sin PC (reglamento 4.3, 11.1-11.3).

La placa mira `phase` en la telemetría:
  - hasta que la fase sea `fase_inicio` (RUNNING por defecto): quieta (8.5);
  - al empezar reparte los cubos con el compañero y lleva los suyos de a uno,
    el más barato primero; el que falla se reintenta después de los demás;
  - si la fase deja de ser `fase_inicio` (FINISHED, abort): para todo;
  - un IDLE o READY posterior la deja lista para la ronda siguiente.

El reparto lo calculan IGUAL los dos rovers a partir de la misma cancha, así
que no necesitan hablarse para no ir al mismo cubo (12.2.6), y cada uno se
lleva al menos uno (12.2.13). Es la regla de asignacion.py (carga máxima más
chica, después distancia total) en versión para la placa.

Duda abierta con la organización: el reglamento dice que se arranca en
"READY" y el contrato llama READY a la preparación y RUNNING a la ronda;
por eso `fase_inicio` es configurable (config: "fase_inicio").
"""
import math

from cliente_vision_rover import ahora_ms

COLORES = ("blue", "green", "red")
ESPERANDO = "ESPERANDO"      # fase previa: quieta
CORRIENDO = "CORRIENDO"      # llevando sus cubos
COMPLETA = "COMPLETA"        # sus cubos entregados; quieta (o ayuda)
TERMINADA = "TERMINADA"      # la fase de juego terminó
DETENIDA = "DETENIDA"        # una orden manual la paró (STOP desde la PC)


def _dist(a, b):
    return math.sqrt((a["col"] - b["col"]) ** 2 + (a["row"] - b["row"]) ** 2)


def _buscar(lista, clave, valor):
    for item in lista:
        if item.get(clave) == valor:
            return item
    return None


_ORDENES = {0: ((),), 1: ((0,),), 2: ((0, 1), (1, 0)),
            3: ((0, 1, 2), (0, 2, 1), (1, 0, 2), (1, 2, 0), (2, 0, 1), (2, 1, 0))}


def _permutaciones(items):
    """Sin recursión: en la placa cada llamada anidada gasta pila (pystack)."""
    return [tuple(items[i] for i in orden) for orden in _ORDENES[len(items)]]


def _carga(pos, orden, cubos, zonas):
    """Distancia recta (celdas) de ir a cada cubo y llevarlo a su zona, en orden."""
    total = 0.0
    for color in orden:
        total += _dist(pos, cubos[color]) + _dist(cubos[color], zonas[color])
        pos = zonas[color]
    return total


def pendientes(mensaje):
    """Colores con cubo visible, zona conocida y todavía fuera de ella."""
    from llevar_cubo import entregado
    salida = []
    for color in COLORES:
        cubo = _buscar(mensaje["cubes"], "color", color)
        zona = _buscar(mensaje.get("depots", ()), "color", color)
        if cubo is None or zona is None:
            continue
        if not entregado(cubo, zona, mensaje):
            salida.append(color)
    return salida


def repartir(mensaje, propio, companero=None):
    """Colores para `propio`, en el orden en que conviene llevarlos.

    Sin compañero visible: todos para `propio`. Con él: el reparto de carga
    máxima más chica (desempate: distancia total, luego el orden de colores),
    con al menos un cubo por rover si hay dos o más.
    """
    rovers = {}
    for r in mensaje["rovers"]:
        rovers[r["id"]] = r
    if companero is None:
        otros = sorted(i for i in rovers if i != propio)
        companero = otros[0] if otros else None
    yo = rovers.get(propio)
    otro = rovers.get(companero)
    colores = pendientes(mensaje)
    if yo is None or not colores:
        return []
    # Distancias exactas: redondear posiciones o costos a celdas crea bordes
    # donde 1 mm de ruido cambia la decisión (medido: 4-7 % de repartos
    # incompatibles frente a 1-3 % sin redondear). El resto lo cubren la
    # guardia "compañero encima del cubo" y la ayuda a cubos sin dueño.
    cubos, zonas = {}, {}
    for color in colores:
        cubos[color] = _buscar(mensaje["cubes"], "color", color)
        zonas[color] = _buscar(mensaje["depots"], "color", color)
    if otro is None:
        mejor = min(_permutaciones(colores), key=lambda o: (_carga(yo, o, cubos, zonas), o))
        return list(mejor)
    ids = sorted((propio, companero))
    pos = {propio: yo, companero: otro}
    cortes = range(1, len(colores)) if len(colores) >= 2 else (0, 1)
    mejor = None
    for orden in _permutaciones(colores):
        for corte in cortes:
            ordenes = (orden[:corte], orden[corte:])
            cargas = [_carga(pos[ids[i]], ordenes[i], cubos, zonas) for i in (0, 1)]
            clave = (max(cargas), sum(cargas), ordenes)
            if mejor is None or clave < mejor:
                mejor = clave
    return list(mejor[2][ids.index(propio)])


class Ronda:
    """Decide qué cubo llevar y cuándo. Mueve el rover sólo a través de `misiones`."""

    def __init__(self, vision, misiones, robot_id, fase_inicio="RUNNING", estrategia="reparto",
                 companero=None, intentos_por_cubo=2, ayuda_ms=300000, max_edad_ms=1500,
                 companero_cerca_mm=200, sin_dueno_ms=30000, reintento_ms=15000, reloj=ahora_ms):
        self.vision, self.misiones, self.robot_id = vision, misiones, robot_id
        self.fase_inicio, self.estrategia, self.companero = fase_inicio, estrategia, companero
        self.intentos_por_cubo, self.ayuda_ms, self.max_edad_ms = intentos_por_cubo, ayuda_ms, max_edad_ms
        self.reloj = reloj
        self.companero_cerca_mm, self.sin_dueno_ms = companero_cerca_mm, sin_dueno_ms
        self.reintento_ms = reintento_ms
        self.estado, self.motivo, self.fase = ESPERANDO, None, None
        self.preparada = False                # LLEVAR y el planificador ya cargados
        self.error_preparar = None
        self._reiniciar()

    def _reiniciar(self):
        self.mis_cubos, self.hechos, self.intentos, self.fallos = [], [], {}, {}
        self.actual = None
        self.inicio_ms = None
        self.pausa_hasta = 0
        self.atendido = {}                    # color -> último momento con un rover cerca
        self.mem = None                       # bytes libres al lanzar el último cubo
        self.reintentar_en = None             # cuándo volver a probar los que fallaron

    @property
    def autonoma(self):
        """True mientras la ronda manda: la PC no debe pararla al conectarse o irse."""
        return self.estado in (CORRIENDO, COMPLETA)

    def detener(self, motivo):
        if self.autonoma:
            self.estado, self.motivo = DETENIDA, motivo
            self.actual = None
            self.misiones.detener_mision(motivo)

    def tick(self):
        mensaje = self.vision.mensaje
        if mensaje is None:
            return
        self.fase = mensaje.get("phase")
        if not self.preparada:
            # Con la primera telemetría, antes de la ronda y con el rover quieto.
            self.preparada = True
            try:
                self.misiones.preparar()
            except Exception as error:        # MemoryError incluido: se reintenta al llevar
                self.error_preparar = "{}: {}".format(type(error).__name__, error)
        if self.fase != self.fase_inicio:
            if self.autonoma:
                self.estado, self.motivo = TERMINADA, "fase_" + str(self.fase)
                self.actual = None
                self.misiones.detener_mision(self.motivo)
            elif self.fase in ("IDLE", "READY") and self.estado != ESPERANDO:
                self.estado, self.motivo = ESPERANDO, None   # lista para otra ronda
                self._reiniciar()
            return
        if self.estado == ESPERANDO:
            if not self._fresca(mensaje):
                return
            self._comenzar(mensaje)
        if self.estado in (CORRIENDO, COMPLETA):
            self._avanzar(mensaje)

    # ------------------------------------------------------------ interno
    def _fresca(self, mensaje):
        desfase = getattr(self.vision, "desfase_reloj", None)
        if desfase is None:
            return False
        return self.reloj() - (mensaje["ts_ms"] + desfase) <= self.max_edad_ms

    def _comenzar(self, mensaje):
        if self.estrategia == "todos":
            solo = dict(mensaje)                  # el compañero no cuenta: todos para mí
            solo["rovers"] = [r for r in mensaje["rovers"] if r["id"] == self.robot_id]
            self.mis_cubos = repartir(solo, self.robot_id)
        else:
            self.mis_cubos = repartir(mensaje, self.robot_id, self.companero)
        self.estado, self.motivo = CORRIENDO, None
        self.inicio_ms = self.reloj()
        print("Ronda: mis cubos", self.mis_cubos)

    def _avanzar(self, mensaje):
        ahora = self.reloj()
        if self.misiones.activa:
            return                                # la misión en curso sigue
        if self.actual is not None:
            resultado = self.misiones.informe()
            if resultado.get("estado") == "ENTREGADO":
                self.hechos.append(self.actual)
            else:
                self.intentos[self.actual] = self.intentos.get(self.actual, 0) + 1
                self.fallos[self.actual] = resultado.get("motivo")
            self.actual = None
            self.pausa_hasta = ahora + 500        # que la visión muestre cómo quedó todo
        if ahora < self.pausa_hasta or not self._fresca(mensaje):
            return
        afuera = pendientes(mensaje)
        for color in self.mis_cubos:              # entregados por el compañero, o empujados dentro
            if color not in afuera and color not in self.hechos:
                self.hechos.append(color)
        if self.estado == COMPLETA:
            # Los suyos que fallaron: la cancha pudo cambiar (el compañero movió
            # algo, el cubo se corrió). Quieto no gana nada; se vuelve a probar.
            fallidos = [c for c in self.mis_cubos if c in afuera]
            if fallidos and self.reintentar_en is not None and ahora >= self.reintentar_en:
                for color in fallidos:
                    self.intentos[color] = self.intentos_por_cubo - 1
                self.reintentar_en = None
                self.estado = CORRIENDO
            else:
                self._ayudar(mensaje, afuera, ahora)
                return
        candidatos = [c for c in self.mis_cubos if c in afuera
                      and self.intentos.get(c, 0) < self.intentos_por_cubo]
        if not candidatos:
            self.estado = COMPLETA
            self.reintentar_en = ahora + self.reintento_ms
            return
        yo = _buscar(mensaje["rovers"], "id", self.robot_id)
        if yo is None:
            return
        cubos, zonas = {}, {}
        for color in candidatos:
            cubos[color] = _buscar(mensaje["cubes"], "color", color)
            zonas[color] = _buscar(mensaje["depots"], "color", color)
        # Si el compañero ya está encima de uno (el reparto salió distinto en
        # su placa, o lo está ayudando), ése se deja para después.
        otros = [r for r in mensaje["rovers"] if r["id"] != self.robot_id]
        libres = [c for c in candidatos
                  if not any(_dist(r, cubos[c]) * mensaje["grid"]["cell_mm"] < self.companero_cerca_mm
                             for r in otros)]
        if not libres:
            self.pausa_hasta = ahora + 1000
            return
        candidatos = libres
        # Primero los que menos fallaron; entre ellos, el más barato desde aquí.
        self.actual = min(candidatos, key=lambda c: (self.intentos.get(c, 0),
                                                     _carga(yo, (c,), cubos, zonas), c))
        from llevar_cubo import memoria_libre
        self.mem = memoria_libre()
        self.misiones.llevar_en_ronda(self.actual)

    def _ayudar(self, mensaje, afuera, ahora):
        """Con lo suyo hecho, toma lo que quede sin dueño.

        Sin dueño: el compañero no está, o nadie se le acercó en `sin_dueno_ms`
        (los dos rovers calcularon repartos distintos y ninguno lo tomó), o
        ya pasó `ayuda_ms` desde el inicio.
        """
        cell = mensaje["grid"]["cell_mm"]
        for color in afuera:
            cubo = _buscar(mensaje["cubes"], "color", color)
            if any(_dist(r, cubo) * cell < 220 for r in mensaje["rovers"]):   # preparando o empujando
                self.atendido[color] = ahora
            else:
                self.atendido.setdefault(color, ahora)
        abandonados = [c for c in afuera if ahora - self.atendido[c] > self.sin_dueno_ms]
        sin_companero = len(mensaje["rovers"]) < 2
        if afuera and (sin_companero or abandonados or ahora - self.inicio_ms > self.ayuda_ms):
            if abandonados and not sin_companero and ahora - self.inicio_ms <= self.ayuda_ms:
                afuera = abandonados
            nuevos = [c for c in afuera if c not in self.mis_cubos]
            reintentos = [c for c in afuera if c in self.mis_cubos
                          and self.intentos.get(c, 0) < self.intentos_por_cubo]
            if nuevos or reintentos:
                self.mis_cubos.extend(nuevos)
                self.estado = CORRIENDO

    def informe(self):
        datos = {"estado": self.estado, "fase": self.fase, "mis_cubos": self.mis_cubos,
                 "hechos": self.hechos, "actual": self.actual}
        if self.intentos:
            datos["intentos"] = self.intentos
        if self.fallos:
            datos["fallos"] = self.fallos
        if self.motivo:
            datos["motivo"] = self.motivo
        if self.mem is not None:
            datos["mem"] = self.mem
        if self.error_preparar:
            datos["error_preparar"] = self.error_preparar
        if self.inicio_ms is not None:
            datos["t_s"] = round((self.reloj() - self.inicio_ms) / 1000, 1)
        return datos
