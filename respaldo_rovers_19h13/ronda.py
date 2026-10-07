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


def _dist_segmento(p, a, b):
    dc, dr = b["col"] - a["col"], b["row"] - a["row"]
    largo2 = dc * dc + dr * dr
    t = 0.0 if largo2 == 0 else max(0.0, min(1.0, ((p["col"] - a["col"]) * dc + (p["row"] - a["row"]) * dr) / largo2))
    return math.sqrt((p["col"] - a["col"] - t * dc) ** 2 + (p["row"] - a["row"] - t * dr) ** 2)


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
                 companero_cerca_mm=200, sin_dueno_ms=30000, reintento_ms=15000, reloj=ahora_ms,
                 enlace=None, latido_ms=200, plan_espera_ms=600, robar=False, apartarse_ms=8000,
                 turnos=True, turno_max_ms=120000, tarde_ms=3000, tarde_espera_ms=1500):
        self.vision, self.misiones, self.robot_id = vision, misiones, robot_id
        self.fase_inicio, self.estrategia, self.companero = fase_inicio, estrategia, companero
        self.intentos_por_cubo, self.ayuda_ms, self.max_edad_ms = intentos_por_cubo, ayuda_ms, max_edad_ms
        self.reloj = reloj
        self.companero_cerca_mm, self.sin_dueno_ms = companero_cerca_mm, sin_dueno_ms
        self.reintento_ms = reintento_ms
        self.salida_cerca_mm, self.salida_ms = 230, 5000   # arranque escalonado (_esperar_salida)
        # ESP-NOW con el compañero (enlace.py). Sin él, o si calla, todo sigue
        # como antes: cada uno calcula el mismo reparto por su cuenta.
        self.enlace, self.latido_ms, self.plan_espera_ms = enlace, latido_ms, plan_espera_ms
        # Tomar cubos del compañero al quedarse sin trabajo. Apagado: en el
        # simulador estorbaba más de lo que ayudaba (dos rovers en la misma
        # zona): 57/90 cubos con robos, 63/90 sin ellos (3-oct).
        self.robar = robar
        self.apartarse_ms = apartarse_ms      # cuánto se aparta al cederle el paso al otro
        # Por turnos: el de ID mayor espera, apartado, a que el otro termine
        # sus cubos (ver _esperar_turno). turno_max_ms: si el otro no termina
        # nunca (roto en la cancha), igual sale.
        self.turnos, self.turno_max_ms = turnos, turno_max_ms
        # Placa reiniciada en plena ronda: el cronómetro oficial (clock) ya pasó
        # de tarde_ms. Antes de decidir, espera hasta tarde_espera_ms a oír al
        # compañero, que sabe qué cubos le quedan (ver _comenzar).
        self.tarde_ms, self.tarde_espera_ms = tarde_ms, tarde_espera_ms
        self.proximo_latido = 0
        self.estado, self.motivo, self.fase = ESPERANDO, None, None
        self.preparada = False                # LLEVAR y el planificador ya cargados
        self.error_preparar = None
        # Último error que tick() lanzó y la placa atrapó (lo anota quien la
        # maneja). Antes sólo se imprimía por USB: en la cancha era invisible.
        self.error, self.errores = None, 0
        # Registro de la ronda: qué hizo y por qué, con el segundo desde RUNNING.
        # Se entrega en SENSORS sólo con la ronda terminada (ver informe): en
        # competencia no hay ver_ronda en vivo (cancha 4-oct: el 11 quieto 13 s
        # sin saber por qué). ~50 bytes cada uno; los más viejos se descartan.
        self.max_eventos = 60
        self._reiniciar()

    def _reiniciar(self):
        self.mis_cubos, self.hechos, self.intentos, self.fallos = [], [], {}, {}
        self.actual = None
        self.inicio_ms = None
        self.pausa_hasta = 0
        self.pedir_reinicio = getattr(self, "pedir_reinicio", False)
        self.atendido = {}                    # color -> último momento con un rover cerca
        self.mem = None                       # bytes libres al lanzar el último cubo
        self.reintentar_en = None             # cuándo volver a probar los que fallaron
        self.plan_listo = False               # el reparto ya se acordó (o no hay radio)
        self.plan_del_lider = False           # se adoptó el reparto del líder por radio
        self.cedido = False                   # la misión actual se cortó para cederle el cubo
        self.cedidos, self.robados = 0, []
        self.propios = 0                      # cubos entregados por este rover
        self.aparcado = False                 # ya se estacionó fuera del camino
        self.ruta_aparcar = []                # puntos que faltan para estacionarse
        self.sitios, self.sitios_desde = [], None   # dónde estacionarse; el A* lo hace tick
        self.reaparcar_en = 0                 # cuándo volver a mirar si estorba donde está
        self.apartandose = False              # cedió el paso: estacionado un rato
        self.turno_mio = False                # ya le tocó (o no hay turnos): lleva lo suyo
        self.esperando_turno = False
        self.tarde_desde = None               # desde cuándo espera oír al compañero (_esperar_compa_tarde)
        self.reincorporado = False            # volvió en plena ronda y tomó lo que el compañero no tiene
        self.eventos = []
        # Lo último anotado, para anotar sólo los cambios (ver _vigilar).
        self._v_mision = self._v_estado = self._v_vision = self._v_turno = self._v_compa = None
        self._v_conexiones = getattr(self.vision, "conexiones", 0)
        cubo = getattr(self.misiones, "cubo", None)
        if cubo is not None and hasattr(cubo, "cesiones"):
            cubo.cesiones = {}                # lo cedido al compañero era de la ronda anterior

    @property
    def autonoma(self):
        """True mientras la ronda manda: la PC no debe pararla al conectarse o irse."""
        return self.estado in (CORRIENDO, COMPLETA)

    def detener(self, motivo):
        if self.autonoma:
            self.estado, self.motivo = DETENIDA, motivo
            self.actual = None
            self.misiones.detener_mision(motivo)

    def _anotar(self, texto):
        """Una línea al registro: segundos desde RUNNING ("pre" antes) y qué pasó."""
        t = "pre" if self.inicio_ms is None else "{:.1f}".format((self.reloj() - self.inicio_ms) / 1000)
        self.eventos.append(t + " " + texto)
        if len(self.eventos) > self.max_eventos:
            self.eventos.pop(0)

    def _vigilar(self):
        """Anota lo que cambió: la misión (estado, motivo, por qué espera o
        retrocede), la conexión con la visión y el estado de la ronda."""
        m = getattr(self.misiones, "actual", None)
        if m is not None:
            u = getattr(m, "ultimo", None) or {}
            extra = u.get("espera") or u.get("atasco") or u.get("retroceso") or u.get("estorbo")
            v = self._v_mision
            # Se compara campo a campo: armar el texto en cada vuelta sería
            # basura de memoria en la placa (el bucle corre decenas de veces/s).
            if v is None or v[0] is not m or v[1] != m.estado or v[2] != m.motivo or v[3] != extra:
                self._v_mision = (m, m.estado, m.motivo, extra)
                self._anotar("{} {}{}{}".format(getattr(m, "color", None) or "ir", m.estado,
                                                " " + str(m.motivo) if m.motivo else "",
                                                " [" + str(extra) + "]" if extra else ""))
        conexiones = getattr(self.vision, "conexiones", 0)
        if conexiones != self._v_conexiones:
            if self._v_conexiones:
                self._anotar("vision reconectada ({})".format(conexiones))
            self._v_conexiones = conexiones
        vision = getattr(self.vision, "estado", None)
        if vision != self._v_vision:
            self._v_vision = vision
            if vision not in (None, "ok", "conectado"):
                self._anotar("vision: " + str(vision))
        if self.estado != self._v_estado:
            self._v_estado = self.estado
            self._anotar("ronda " + self.estado + (" " + str(self.motivo) if self.motivo else ""))

    def tick(self):
        self._vigilar()
        if self.enlace is not None:
            self._radio()
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
                self._v_estado = TERMINADA
                self._anotar("fin de la ronda: " + self.motivo)
                self.actual = None
                self.misiones.detener_mision(self.motivo)
            elif self.fase in ("IDLE", "READY") and self.estado != ESPERANDO:
                if self.estado == TERMINADA:
                    # Ya jugó una ronda: la placa pide reiniciarse antes de la
                    # siguiente (cancha 3-oct: en rondas seguidas sin apagar el
                    # 10 quedó con ~10 KB menos de RAM y sin red, y los dos se
                    # quedaron 34 s quietos al arrancar). Lo hace quien maneja
                    # la placa; en la PC no pasa nada.
                    self.pedir_reinicio = True
                self.estado, self.motivo = ESPERANDO, None   # lista para otra ronda
                self._reiniciar()
            return
        if self.estado == ESPERANDO:
            if not self._fresca(mensaje) or self._esperar_compa_tarde(mensaje):
                return
            self._comenzar(mensaje)
        if self.estado in (CORRIENDO, COMPLETA):
            self._avanzar(mensaje)
            if self.sitios:
                self._ir_a_aparcar(mensaje)

    # ------------------------------------------------------------ radio
    def _radio(self):
        self.enlace.recibir()
        ahora = self.reloj()
        if ahora >= self.proximo_latido:
            self.proximo_latido = ahora + self.latido_ms
            self.enlace.enviar({"e": self.estado, "a": self.actual, "m": self.mis_cubos,
                                "h": self.propios, "r": self.robados})

    def _compa(self):
        """Estado reciente del compañero por radio, sólo si está jugando la ronda."""
        if self.enlace is None:
            return None
        compa = self.enlace.companero()
        if compa is None or compa.get("e") not in (CORRIENDO, COMPLETA):
            return None
        return compa

    def _acordar_plan(self, compa, afuera, ahora):
        """El de menor ID decide el reparto y el otro lo adopta: con ruido de
        cámara cada uno podía calcular uno distinto (1-3 % de las canchas)."""
        vivo = self.enlace.companero() if self.enlace is not None else None
        if vivo is None or self.robot_id < vivo.get("id", 0):
            self.plan_listo = True            # sin radio, o soy el líder: vale mi reparto
            return True
        lider = compa.get("m") if compa is not None else None
        if not isinstance(lider, list):
            if ahora - self.inicio_ms < self.plan_espera_ms:
                return False                  # el líder todavía no empezó la ronda
            self.plan_listo = True            # no llegó: sigue con el propio
            return True
        propios = [c for c in COLORES if c in afuera and c not in lider]
        if propios:                           # si el líder se quedó con todo, sigue el propio
            self.mis_cubos = [c for c in self.mis_cubos if c in propios] + \
                             [c for c in propios if c not in self.mis_cubos]
            self.plan_del_lider = True
            print("Ronda: reparto del lider", lider, "-> mis cubos", self.mis_cubos)
        self.plan_listo = True
        return True

    def _robar(self, mensaje, afuera, compa):
        """Con lo suyo hecho, toma un cubo que el compañero no empezó, para que
        nadie quede quieto. Cada rover conserva al menos un cubo (12.2.13): el
        compañero ya entregó uno o está llevando otro."""
        actual = compa.get("a")
        ajenos = [c for c in afuera if c not in self.mis_cubos]
        # Sólo si al compañero le queda otro cubo, o ya entregó alguno: si no,
        # podría terminar la ronda sin haber llevado ninguno (simulador: pasó).
        if compa.get("h", 0) < 1 and len(ajenos) < 2:
            return False
        libres = [c for c in ajenos if c != actual]
        yo = _buscar(mensaje["rovers"], "id", self.robot_id)
        if not libres or yo is None:
            return False
        cubos, zonas = {}, {}
        for color in libres:
            cubos[color] = _buscar(mensaje["cubes"], "color", color)
            zonas[color] = _buscar(mensaje["depots"], "color", color)
        color = min(libres, key=lambda c: (_carga(yo, (c,), cubos, zonas), c))
        self.mis_cubos.append(color)
        self.robados.append(color)
        self.estado = CORRIENDO
        return True

    # ------------------------------------------------------------ interno
    def _esperar_salida(self, mensaje, yo, ahora):
        """Al arrancar juntos cada uno ve al otro encima y ninguno encuentra
        ruta: se bloqueaban los dos (simulador, rovers a 16 cm). Sale primero
        el de menor ID; el otro espera a que se aleje (como mucho unos s)."""
        if self.propios or self.hechos or self.intentos or ahora - self.inicio_ms > self.salida_ms:
            return False
        cell = mensaje["grid"]["cell_mm"]
        for r in mensaje["rovers"]:
            if r["id"] < self.robot_id and _dist(r, yo) * cell < self.salida_cerca_mm:
                return True
        return False

    def _fresca(self, mensaje):
        desfase = getattr(self.vision, "desfase_reloj", None)
        if desfase is None:
            return False
        return self.reloj() - (mensaje["ts_ms"] + desfase) <= self.max_edad_ms

    def _tarde(self, mensaje):
        """True si la ronda ya llevaba rato al empezar: la placa se reinició
        (o se encendió) en plena ronda. Lo dice el cronómetro oficial."""
        reloj = mensaje.get("clock") or {}
        return reloj.get("elapsed_ms", 0) > self.tarde_ms

    def _esperar_compa_tarde(self, mensaje):
        """True mientras espera oír al compañero antes de empezar tarde."""
        if self.enlace is None or not self._tarde(mensaje) or self.enlace.companero() is not None:
            return False
        ahora = self.reloj()
        if self.tarde_desde is None:
            self.tarde_desde = ahora
        return ahora - self.tarde_desde < self.tarde_espera_ms

    def _comenzar(self, mensaje):
        compa = self._compa() if self._tarde(mensaje) else None
        suyos = compa.get("m") if compa is not None else None
        if isinstance(suyos, list):
            # Volvió de un reinicio en plena ronda (cancha 5-oct: el flujo de la
            # visión se trababa y la placa se reiniciaba). Repartir de nuevo con
            # la cancha a medio jugar chocaba con el reparto del compañero: los
            # dos con el mismo cubo y otro sin dueño (simulador, D=0,5, el 10
            # reiniciado a los 15 s: 13/24 rondas completas contra 22/24). El
            # compañero sigue con lo suyo; éste lleva el resto, después de él.
            solo = dict(mensaje)
            solo["rovers"] = [r for r in mensaje["rovers"] if r["id"] == self.robot_id]
            ocupados = suyos + [compa.get("a")]
            self.mis_cubos = [c for c in repartir(solo, self.robot_id) if c not in ocupados]
            self.plan_listo = self.reincorporado = True
        elif self.estrategia == "todos":
            solo = dict(mensaje)                  # el compañero no cuenta: todos para mí
            solo["rovers"] = [r for r in mensaje["rovers"] if r["id"] == self.robot_id]
            self.mis_cubos = repartir(solo, self.robot_id)
        else:
            self.mis_cubos = repartir(mensaje, self.robot_id, self.companero)
        self.estado, self.motivo = CORRIENDO, None
        self.inicio_ms = self.reloj()
        self._anotar(("reincorporado: mis cubos " if self.reincorporado else "RUNNING: mis cubos ")
                     + str(self.mis_cubos))
        self.proximo_latido = 0               # que el compañero sepa ya
        print("Ronda: mis cubos", self.mis_cubos)

    def _esperar_turno(self, mensaje, ahora):
        """True mientras le toque esperar: por turnos, el de ID mayor espera a
        que el otro termine sus cubos (radio: COMPLETA) y después lleva los
        suyos. Cada uno sigue llevando al menos uno (12.2.13).

        Moviéndose los dos a la vez se estorbaban: uno cedía el paso, el otro
        lo esperaba y quedaban los dos quietos (cancha 4-oct 15:01, 15:54 y
        17:06). Simulador, canchas oficiales: 106/108 cubos y 34/36 rondas
        por turnos, 97/108 y 29/36 a la vez; tarda unos 5-15 s más cuando
        todo sale bien. Sin radio no hay turnos: cada uno va por lo suyo.
        """
        if self.turno_mio or not self.turnos or self.enlace is None:
            return False
        otros = [r["id"] for r in mensaje["rovers"] if r["id"] != self.robot_id]
        # El reincorporado espera aunque tenga el ID menor: el otro ya está
        # llevando lo suyo y moverse los dos a la vez los trababa.
        if not otros or (self.robot_id < min(otros) and not self.reincorporado):
            self.turno_mio = True                 # va primero, o está solo en la cancha
            return False
        compa = self.enlace.companero()
        estado = compa.get("e") if compa is not None else None
        if estado == CORRIENDO and ahora - self.inicio_ms < self.turno_max_ms:
            return True                           # el otro todavía lleva lo suyo
        if estado in (None, ESPERANDO) and ahora - self.inicio_ms < 3000:
            return True                           # todavía no se lo oyó empezar
        self.turno_mio = True                     # terminó, se calló o se trabó: me toca
        return False

    def _avanzar(self, mensaje):
        ahora = self.reloj()
        compa = self._compa()
        cubo = getattr(self.misiones, "cubo", None)
        if cubo is not None:
            # Al que ya terminó no se le cede el paso: no va a pasar nunca
            # (cancha 4-oct 15:54: el 11 le cedió el rojo 10 veces al 10 quieto).
            cubo.compa_quieto = compa is not None and compa.get("e") == COMPLETA and not compa.get("a")
        if self.enlace is not None and (compa is None) != (self._v_compa is None):
            self._anotar("radio: companero " + ("visto" if compa is not None else "callado"))
        self._v_compa = compa
        self.esperando_turno = (self.estado == CORRIENDO and self.actual is None
                                and not self.misiones.activa and self._esperar_turno(mensaje, ahora))
        if self.turnos and self.enlace is not None and self.turno_mio != self._v_turno:
            self._v_turno = self.turno_mio
            self._anotar("turno: me toca" if self.turno_mio else "turno: espero al companero")
        if self.esperando_turno:
            if self._fresca(mensaje):
                self._aparcar(mensaje, pendientes(mensaje))   # mientras, fuera de los caminos
            return
        if self.misiones.activa:
            # Los dos tomaron el mismo cubo a la vez: cede el de mayor ID.
            if compa is not None and self.actual is not None and compa.get("a") == self.actual \
                    and self.robot_id > compa.get("id", 0):
                self.cedido = True
                self.cedidos += 1
                self.misiones.detener_mision("cedido")
            return                                # la misión en curso sigue
        if self.actual is not None:
            resultado = self.misiones.informe()
            motivo = str(resultado.get("motivo"))
            pausa = 500                           # que la visión muestre cómo quedó todo
            if self.cedido:
                self.cedido = False               # no fue un fallo: no cuenta como intento
            elif resultado.get("estado") == "ENTREGADO":
                self.hechos.append(self.actual)
                self.propios += 1                 # los que llevó ESTE rover (12.2.13)
            elif motivo in ("wifi_perdido", "vision_vieja", "rover_no_visible"):
                # Se cortó la red o la visión, no falló el cubo: no cuenta como
                # intento (cancha 4-oct: con dos cortes en el mismo cubo la
                # ronda lo daba por perdido). Se vuelve a probar al volver.
                self.fallos[self.actual] = motivo
                pausa = 1000
            elif "rover" in motivo:
                # El compañero se cruzó (en el corredor o en el camino): no es
                # un fallo del cubo. Se espera a que pase y se vuelve a probar.
                self.fallos[self.actual] = motivo
                pausa = 2000
                if "cede_paso" in motivo:
                    # Le cedió el paso: apartarse unos segundos (estacionarse
                    # lejos de los caminos) para que el otro pueda empujar.
                    pausa = self.apartarse_ms
                    self.apartandose = True
                    self.aparcado = False
            else:
                self.intentos[self.actual] = self.intentos.get(self.actual, 0) + 1
                self.fallos[self.actual] = motivo
            self.actual = None
            self.pausa_hasta = ahora + pausa
        if ahora < self.pausa_hasta or not self._fresca(mensaje):
            if self.apartandose and ahora < self.pausa_hasta and self._fresca(mensaje):
                self._aparcar(mensaje, pendientes(mensaje))
            return
        if self.apartandose:
            self.apartandose = False
            self.misiones.detener_mision("aparcar")
        afuera = pendientes(mensaje)
        for color in self.mis_cubos:              # entregados por el compañero, o empujados dentro
            if color not in afuera and color not in self.hechos:
                self.hechos.append(color)
        if not self.plan_listo and not self._acordar_plan(compa, afuera, ahora):
            return                                # esperando el reparto del líder
        if self.estado == COMPLETA:
            # Los suyos que fallaron: la cancha pudo cambiar (el compañero movió
            # algo, el cubo se corrió). Quieto no gana nada; se vuelve a probar.
            fallidos = [c for c in self.mis_cubos if c in afuera]
            if fallidos and self.reintentar_en is not None and ahora >= self.reintentar_en:
                for color in fallidos:
                    self.intentos[color] = self.intentos_por_cubo - 1
                self.reintentar_en = None
                self.estado = CORRIENDO
            elif compa is not None:
                if not (self.robar and self._robar(mensaje, afuera, compa)):
                    self._aparcar(mensaje, afuera)
                    return
            else:
                self._ayudar(mensaje, afuera, ahora)
                if self.estado == COMPLETA:
                    self._aparcar(mensaje, afuera)
                return
        # Los que el compañero tomó al quedarse sin trabajo ya son suyos: soltarlos
        # (si no, los dos se lo disputaban y uno cedía una y otra vez).
        tomados = (compa.get("r") or []) if compa is not None else []
        candidatos = [c for c in self.mis_cubos if c in afuera and c not in tomados
                      and self.intentos.get(c, 0) < self.intentos_por_cubo]
        if not candidatos:
            self.estado = COMPLETA
            self.reintentar_en = ahora + self.reintento_ms
            return
        yo = _buscar(mensaje["rovers"], "id", self.robot_id)
        if yo is None:
            return
        if self._esperar_salida(mensaje, yo, ahora):
            return
        cubos, zonas = {}, {}
        for color in candidatos:
            cubos[color] = _buscar(mensaje["cubes"], "color", color)
            zonas[color] = _buscar(mensaje["depots"], "color", color)
        # Si el compañero ya está encima de uno (el reparto salió distinto en
        # su placa, o lo está ayudando), ése se deja para después.
        otros = [r for r in mensaje["rovers"] if r["id"] != self.robot_id]
        ocupado = compa.get("a") if compa is not None else None   # lo lleva el compañero
        # Con radio se sabe qué cubo lleva el otro; sin ella, "está encima" es
        # la única pista (y con radio trababa: el otro quieto junto a mi cubo).
        otros = otros if compa is None else []
        libres = [c for c in candidatos if c != ocupado
                  and not any(_dist(r, cubos[c]) * mensaje["grid"]["cell_mm"] < self.companero_cerca_mm
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
        self._anotar("lleva {} (ram {})".format(self.actual, self.mem))
        self.misiones.llevar_en_ronda(self.actual)
        self.proximo_latido = 0                   # anunciarlo ya: evita que el otro lo tome
        self.aparcado = False                     # al terminar, volver a estacionarse
        self.ruta_aparcar = []                    # la de antes (esperando turno) ya no vale

    def _aparcar(self, mensaje, afuera):
        """Sin nada que hacer (o esperando su turno), no estorbar: ir a un
        sitio lejos de los cubos que faltan, de por dónde se los empuja y del
        compañero (simulador: el que terminaba se quedaba parado en el
        corredor del cubo del otro).

        Va por una ruta del planificador, punto a punto: en línea recta casi
        siempre había un cubo en medio y se quedaba donde estaba (cancha 3-oct).
        Cada 5 s vuelve a mirar si sigue bien puesto; si algo cortó el camino,
        lo reintenta en 3 s (antes se quedaba ahí para siempre).
        """
        if not afuera or not hasattr(self.misiones, "ir_en_ronda"):
            return
        ahora = self.reloj()
        if self.ruta_aparcar:
            if self.misiones.informe().get("estado") == "ABORTADO":
                self.ruta_aparcar = []            # algo se cruzó: volver a mirar en un rato
                self.reaparcar_en = ahora + 3000
                return
            siguiente = self.ruta_aparcar.pop(0)
            try:
                self.misiones.ir_en_ronda(siguiente["col"], siguiente["row"])
            except ValueError:
                self.ruta_aparcar = []
            return
        if self.aparcado and ahora < self.reaparcar_en:
            return
        self.aparcado = True
        self.reaparcar_en = ahora + 5000
        yo = _buscar(mensaje["rovers"], "id", self.robot_id)
        if yo is None:
            return
        grid = mensaje["grid"]
        cell = grid["cell_mm"]
        modelo = getattr(getattr(self.misiones, "ir", None), "modelo", None)
        if modelo is not None:
            # El centro de giro, como la misión que va a moverlo: desde el
            # marcador (3 cm adelante) la ruta pasaba demasiado cerca del cubo
            # recién entregado y la red de seguridad la cortaba en el acto
            # (camino_bloqueado: el 10 se quedaba en el medio, cancha 4-oct).
            yo = modelo.centro_desde_marcador(yo, cell)
        borde = 7.0                               # celdas: sin tapar marcadores de esquina
        puntos = [{"col": c, "row": r} for c in (borde, grid["cols"] - borde)
                  for r in (borde, grid["rows"] - borde)]
        if mensaje.get("start"):
            puntos.append(mensaje["start"])
        from llevar_cubo import punto_detras
        llevar = getattr(self.misiones, "cubo", None)
        # Desde el punto previo de ataque (detrás del cubo, donde se pone el
        # rover para empujar) hasta la zona: no sólo de cubo a zona.
        atras = getattr(llevar, "aproximacion_mm", 160.0) + getattr(llevar, "previo_mm", 70.0)
        estorbos = []                             # segmentos (ataque -> zona) y el compañero
        for color in afuera:
            cubo = _buscar(mensaje["cubes"], "color", color)
            zona = _buscar(mensaje["depots"], "color", color)
            if cubo is not None and zona is not None:
                estorbos.append((punto_detras(cubo, zona, atras, cell) or cubo, zona))
        compa = self._compa()
        lleva = compa.get("a") if compa is not None else None
        for r in mensaje["rovers"]:
            if r["id"] != self.robot_id:
                estorbos.append((r, r))
                cubo = _buscar(mensaje["cubes"], "color", lleva) if lleva in afuera else None
                zona = _buscar(mensaje["depots"], "color", lleva) if cubo is not None else None
                if zona is not None:              # y su camino hasta el punto de ataque
                    estorbos.append((r, punto_detras(cubo, zona, atras, cell) or cubo))

        def holgura(p):
            return min([_dist_segmento(p, a, b) for a, b in estorbos] or [99.0])

        actual = holgura(yo)
        # Los sitios bastante más apartados que donde está, del mejor al peor.
        # La ruta la busca _ir_a_aparcar en este mismo tick (ver ahí por qué).
        self.sitios = [p for p in sorted(puntos, key=holgura, reverse=True) if holgura(p) - actual >= 3.0]
        self.sitios_desde = yo

    def _ir_a_aparcar(self, mensaje):
        """Va al primer sitio de `sitios` al que haya ruta.

        El A* se llama desde aquí, que lo llama tick, y no desde _aparcar: en
        la placa la pila de Python es de ~1,5 KB y por tick > _avanzar >
        _aparcar > _ruta > A* pesaba 201 (la misión, 169). tick() en la placa
        atrapaba el error sin avisar y el rover nunca se apartaba (cancha
        4-oct 15:54: el 10 terminó y quedó en el camino del 11, que le cedió
        el paso una y otra vez sin moverse).
        """
        sitios, self.sitios = self.sitios, []
        yo = self.sitios_desde
        planner = getattr(getattr(self.misiones, "cubo", None), "planner", None)
        from llevar_cubo import entregados
        hechos = entregados(mensaje)              # el planificador les deja más margen
        for p in sitios:
            if planner is None:
                from autonomia import obstaculo_en_camino
                ruta = None if obstaculo_en_camino(mensaje, yo, p, propio=self.robot_id) else [p]
            else:
                from llevar_cubo import _Escena
                planner.clearance = 25.0          # holgado: el rover recorta las esquinas
                planner.escapar = True            # recién retirado de un cubo: alejarse vale
                try:
                    ruta = planner.plan(_Escena(mensaje, self.robot_id, yo, hechos), p)
                finally:
                    planner.escapar = False
                ruta = (ruta["puntos"][1:] or [p]) if ruta["estado"] == "RUTA" else None
            if ruta:
                self.ruta_aparcar = ruta[1:]
                self._anotar("se estaciona en ({:.0f}, {:.0f})".format(p["col"], p["row"]))
                try:
                    self.misiones.ir_en_ronda(ruta[0]["col"], ruta[0]["row"])
                except ValueError:
                    self.ruta_aparcar = []
                    continue
                return

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
        if self.error:
            datos["error"], datos["errores"] = self.error, self.errores
        if self.esperando_turno:
            datos["turno"] = "esperando"
        if self.eventos and self.estado not in (CORRIENDO, COMPLETA):
            datos["eventos"] = self.eventos      # sólo con la ronda terminada: es grande
        if self.enlace is not None:
            radio = self.enlace.informe()
            if self.plan_del_lider:
                radio["plan"] = "lider"
            if self.reincorporado:
                radio["plan"] = "reincorporado"
            if self.cedidos:
                radio["cedidos"] = self.cedidos
            if self.robados:
                radio["robados"] = self.robados
            datos["radio"] = radio
        if self.inicio_ms is not None:
            datos["t_s"] = round((self.reloj() - self.inicio_ms) / 1000, 1)
        return datos
