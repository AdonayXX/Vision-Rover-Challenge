"""Verifica el árbitro: el mapa de transiciones y el cronómetro oficial.

    python -m vision.tools.verificar_ronda

Por qué con un reloj inyectado y no durmiendo
---------------------------------------------
Una ronda dura diez minutos y la preparación uno. Verificar el cierre por tiempo
agotado durmiendo esos minutos haría que nadie corriera nunca esta herramienta, y
una verificación que no se corre no verifica nada. `Arbitro` acepta el reloj como
argumento justamente para esto: acá se le pasa uno falso que avanza cuando se le
dice, y las transiciones se prueban en el instante exacto del límite en vez de
"cerca".

Qué se comprueba, y por qué cada caso
-------------------------------------
Las transiciones que NO se pueden hacer importan tanto como las que sí:

- que `start` **no exista** como comando es la regla que sostiene que todos los
  equipos preparen con el mismo tiempo;
- que `ready` **se rechace desde READY** impide estirar la preparación
  apretando una tecla;
- que arrancar en `RUNNING` **lance**, porque una ronda sin preparación ni
  cronómetro desde cero parece válida y no lo es;
- que el cierre por reto cumplido **no dispare** si los cubos ya estaban puestos
  al arrancar, que es lo que pasa cuando nadie los sacó de la ronda anterior;
- que el tiempo del reto sea el de la **entrada** del último cubo y no el de la
  confirmación de la permanencia, que llega un segundo más tarde.
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import os
import sys
import tempfile

try:  # como paquete
    from ..configuracion import Ronda, cargar_config
    from ..mundo import CuboEnMundo, EstadoMundo
    from ..record.acta import escribir_acta
    from ..reglas.acopio import ContadorAcopio
    from ..sistema import (
        MOTIVO_ABORTADA, MOTIVO_GEOMETRIA, MOTIVO_OPERADOR, MOTIVO_RETO, MOTIVO_TIEMPO,
        Arbitro, _TRANSICIONES,
    )
except ImportError:  # como script suelto
    from vision.configuracion import Ronda, cargar_config  # type: ignore[no-redef]
    from vision.mundo import CuboEnMundo, EstadoMundo  # type: ignore[no-redef]
    from vision.record.acta import escribir_acta  # type: ignore[no-redef]
    from vision.reglas.acopio import ContadorAcopio  # type: ignore[no-redef]
    from vision.sistema import (  # type: ignore[no-redef]
        MOTIVO_ABORTADA, MOTIVO_GEOMETRIA, MOTIVO_OPERADOR, MOTIVO_RETO, MOTIVO_TIEMPO,
        Arbitro, _TRANSICIONES,
    )

PREPARACION_MS = 60_000
DURACION_MS = 600_000
CEGUERA_MS = 2_000


class RelojFalso:
    """Un reloj monótono que solo avanza cuando se lo pide."""

    def __init__(self, t0: float = 1000.0):
        self.t = t0

    def __call__(self) -> float:
        return self.t

    def avanzar(self, ms: float) -> None:
        self.t += ms / 1000.0


def _config():
    cfg = cargar_config()
    return dataclasses.replace(
        cfg, ronda=Ronda(preparacion_ms=PREPARACION_MS, duracion_ms=DURACION_MS,
                         geometria_perdida_ms=CEGUERA_MS))


def _arbitro(cfg, inicial="IDLE"):
    reloj = RelojFalso()
    return Arbitro(cfg, inicial, reloj=reloj), reloj


def verificar_transiciones(cfg) -> bool:
    print("=" * 78)
    print("TRANSICIONES: quién puede mover la ronda, y quién no")
    print("=" * 78)
    print("  {:<52} {:>10} {:>10}  {}".format("situación", "queda en", "se esperaba", "estado"))
    print("  " + "-" * 88)

    casos = []

    # --- las que hace una persona ---------------------------------------
    # Con geometría: se prepara. Sin geometría es otro caso, y vive en el
    # bloque de guardas, porque ahí es una regla y no un trámite.
    a, _ = _arbitro(cfg)
    a.tictac(True)
    a.intentar("ready")
    casos.append(("IDLE + ready (viendo la cancha)", a.fase, "READY"))

    a, _ = _arbitro(cfg, "READY")
    a.intentar("ready")
    casos.append(("READY + ready (reiniciar la preparación)", a.fase, "READY"))

    a, _ = _arbitro(cfg, "READY")
    a.intentar("abort")
    casos.append(("READY + abort", a.fase, "IDLE"))

    a, reloj = _arbitro(cfg, "READY")
    reloj.avanzar(PREPARACION_MS)
    a.tictac()
    a.intentar("stop")
    casos.append(("RUNNING + stop", a.fase, "FINISHED"))

    a, _ = _arbitro(cfg)
    a.intentar("stop")
    casos.append(("IDLE + stop (sin ronda en juego)", a.fase, "IDLE"))

    a, reloj = _arbitro(cfg, "READY")
    reloj.avanzar(PREPARACION_MS)
    a.tictac()
    a.intentar("stop")
    a.intentar("ready")
    casos.append(("FINISHED + ready (ronda siguiente)", a.fase, "READY"))

    a, reloj = _arbitro(cfg, "READY")
    reloj.avanzar(PREPARACION_MS)
    a.tictac()
    a.intentar("stop")
    a.intentar("abort")
    casos.append(("FINISHED + abort (resetear la cancha)", a.fase, "IDLE"))

    # --- las que hace el reloj ------------------------------------------
    a, reloj = _arbitro(cfg, "READY")
    reloj.avanzar(PREPARACION_MS - 1)
    a.tictac()
    casos.append(("READY, un milisegundo ANTES del límite", a.fase, "READY"))

    a, reloj = _arbitro(cfg, "READY")
    reloj.avanzar(PREPARACION_MS)
    a.tictac()
    casos.append(("READY, justo en el límite", a.fase, "RUNNING"))

    a, reloj = _arbitro(cfg, "READY")
    reloj.avanzar(PREPARACION_MS)
    a.tictac()
    reloj.avanzar(DURACION_MS - 1)
    a.tictac()
    casos.append(("RUNNING, un milisegundo ANTES del límite", a.fase, "RUNNING"))

    a, reloj = _arbitro(cfg, "READY")
    reloj.avanzar(PREPARACION_MS)
    a.tictac()
    reloj.avanzar(DURACION_MS)
    a.tictac()
    casos.append(("RUNNING, justo en el límite", a.fase, "FINISHED"))

    todo_bien = True
    for nombre, obtenido, esperado in casos:
        paso = obtenido == esperado
        todo_bien = todo_bien and paso
        print("  {:<52} {:>10} {:>10}  {}".format(
            nombre, obtenido, esperado, "OK" if paso else "FALLA"))

    # --- lo que NO tiene que existir -------------------------------------
    print()
    sin_start = "start" not in _TRANSICIONES
    print("  {:<52} {:>10} {:>10}  {}".format(
        "'start' NO es un comando", "ausente" if sin_start else "existe", "ausente",
        "OK" if sin_start else "FALLA"))
    todo_bien = todo_bien and sin_start

    try:
        Arbitro(cfg, "RUNNING")
        arranca_en_running = True
    except ValueError:
        arranca_en_running = False
    print("  {:<52} {:>10} {:>10}  {}".format(
        "arrancar en RUNNING", "lanza" if not arranca_en_running else "acepta", "lanza",
        "OK" if not arranca_en_running else "FALLA"))
    todo_bien = todo_bien and not arranca_en_running

    # --- los motivos del cierre ------------------------------------------
    print()
    print("  {:<52} {:>24}  {}".format("motivo del cierre", "se esperaba", "estado"))
    print("  " + "-" * 88)
    motivos = []

    a, reloj = _arbitro(cfg, "READY")
    reloj.avanzar(PREPARACION_MS)
    a.tictac()
    reloj.avanzar(DURACION_MS)
    a.tictac()
    motivos.append(("se agotó la ronda", a.motivo, MOTIVO_TIEMPO))

    a, reloj = _arbitro(cfg, "READY")
    reloj.avanzar(PREPARACION_MS)
    a.tictac()
    a.intentar("stop")
    motivos.append(("la cerró el operador", a.motivo, MOTIVO_OPERADOR))

    a, _ = _arbitro(cfg, "READY")
    a.intentar("abort")
    motivos.append(("abortada en preparación", a.motivo, MOTIVO_ABORTADA))

    for nombre, obtenido, esperado in motivos:
        paso = obtenido == esperado
        todo_bien = todo_bien and paso
        print("  {:<52} {:>24}  {}".format(
            nombre, esperado, "OK" if paso else "FALLA: {}".format(obtenido)))

    print("\n  resultado: {}\n".format("TODO OK" if todo_bien else "HAY FALLAS"))
    return todo_bien


def verificar_reloj(cfg) -> bool:
    print("=" * 78)
    print("CRONÓMETRO: los tres valores que viajan en el mensaje")
    print("=" * 78)
    print("  {:<44} {:>11} {:>11} {:>11}  {}".format(
        "situación", "transcurr.", "restante", "total", "estado"))
    print("  " + "-" * 92)

    casos = []

    a, _ = _arbitro(cfg)
    casos.append(("IDLE: no se cuenta nada", a.reloj(), (0, 0, 0)))

    a, reloj = _arbitro(cfg, "READY")
    reloj.avanzar(20_000)
    casos.append(("READY a los 20 s", a.reloj(), (20_000, 40_000, PREPARACION_MS)))

    a, reloj = _arbitro(cfg, "READY")
    reloj.avanzar(PREPARACION_MS)
    a.tictac()
    casos.append(("RUNNING recién empezada", a.reloj(), (0, DURACION_MS, DURACION_MS)))

    a, reloj = _arbitro(cfg, "READY")
    reloj.avanzar(PREPARACION_MS)
    a.tictac()
    reloj.avanzar(90_000)
    casos.append(("RUNNING al minuto y medio", a.reloj(),
                  (90_000, DURACION_MS - 90_000, DURACION_MS)))

    a, reloj = _arbitro(cfg, "READY")
    reloj.avanzar(PREPARACION_MS)
    a.tictac()
    reloj.avanzar(DURACION_MS)
    a.tictac()
    reloj.avanzar(30_000)  # el reloj sigue, el cronómetro NO
    casos.append(("FINISHED por tiempo, 30 s después", a.reloj(),
                  (DURACION_MS, 0, DURACION_MS)))

    # El caso que SIEMPRE ocurre en la realidad y que la primera versión de esta
    # herramienta no probaba: `tictac` no se entera en el instante exacto del
    # vencimiento, sino en el cuadro siguiente. El transcurrido real se pasa, y
    # sin recortar al total el mensaje viola el invariante que el contrato
    # valida. Se descubrió en el simulador: 5019 ms sobre una ronda de 5000.
    a, reloj = _arbitro(cfg, "READY")
    reloj.avanzar(PREPARACION_MS + 19)
    a.tictac()
    reloj.avanzar(DURACION_MS + 347)   # el bucle se entera 347 ms tarde
    a.tictac()
    casos.append(("FINISHED habiéndose PASADO 347 ms", a.reloj(),
                  (DURACION_MS, 0, DURACION_MS)))

    # Lo mismo cerrando a mano, donde el recorte no tiene que hacer nada.
    a, reloj = _arbitro(cfg, "READY")
    reloj.avanzar(PREPARACION_MS)
    a.tictac()
    reloj.avanzar(72_500)
    a.intentar("stop")
    casos.append(("FINISHED por el operador a los 72,5 s", a.reloj(),
                  (72_500, DURACION_MS - 72_500, DURACION_MS)))

    todo_bien = True
    for nombre, r, esperado in casos:
        obtenido = (r.transcurrido_ms, r.restante_ms, r.total_ms)
        paso = obtenido == esperado
        todo_bien = todo_bien and paso
        print("  {:<44} {:>11} {:>11} {:>11}  {}".format(
            nombre, r.transcurrido_ms, r.restante_ms, r.total_ms,
            "OK" if paso else "FALLA, se esperaba {}".format(esperado)))

    print("\n  resultado: {}\n".format("TODO OK" if todo_bien else "HAY FALLAS"))
    return todo_bien


def verificar_reto_cumplido(cfg) -> bool:
    """El cierre por reto cumplido: cuándo dispara y con qué tiempo."""
    print("=" * 78)
    print("RETO CUMPLIDO: el cierre automático y el instante que se registra")
    print("=" * 78)

    todo_bien = True

    # Caso 1: los tres cubos YA estaban puestos al arrancar.
    a, reloj = _arbitro(cfg, "READY")
    reloj.avanzar(PREPARACION_MS)
    a.tictac()
    reloj.avanzar(5_000)
    a.observar_reto(True, reloj())          # completo desde el primer cuadro
    reloj.avanzar(5_000)
    a.observar_reto(True, reloj())
    paso = a.fase == "RUNNING"
    todo_bien = todo_bien and paso
    print("  {:<58} {:>8}  {}".format(
        "arranca con los tres cubos ya adentro: NO cierra", a.fase, "OK" if paso else "FALLA"))

    # Caso 2: incompleto y después completo. El tiempo es el de la ENTRADA.
    a, reloj = _arbitro(cfg, "READY")
    reloj.avanzar(PREPARACION_MS)
    a.tictac()
    reloj.avanzar(120_000)
    a.observar_reto(False, None)            # todavía faltan cubos
    reloj.avanzar(60_000)
    entrada = reloj()                       # entra el último cubo: 180 s de ronda
    reloj.avanzar(1_000)                    # se cumple la permanencia un segundo después
    a.observar_reto(True, entrada)
    cerro = a.fase == "FINISHED" and a.motivo == MOTIVO_RETO
    tiempo = a.tiempo_final_ms
    paso = cerro and tiempo == 180_000
    todo_bien = todo_bien and paso
    print("  {:<58} {:>8}  {}".format(
        "cumplido a los 180 s, confirmado a los 181: registra",
        "{} s".format(tiempo / 1000.0 if tiempo is not None else "—"),
        "OK" if paso else "FALLA: esperaba 180.0 s"))

    # Caso 3: el cronómetro queda detenido a la vista.
    reloj.avanzar(45_000)
    r = a.reloj()
    paso = r.transcurrido_ms == 180_000 and r.restante_ms == DURACION_MS - 180_000
    todo_bien = todo_bien and paso
    print("  {:<58} {:>8}  {}".format(
        "el cronómetro queda detenido, y sobra lo que sobró",
        "{} s".format(r.transcurrido_ms / 1000.0), "OK" if paso else "FALLA"))

    print("\n  resultado: {}\n".format("TODO OK" if todo_bien else "HAY FALLAS"))
    return todo_bien


def verificar_cierre_por_reto(cfg) -> bool:
    """El contador y el árbitro JUNTOS: quién cuenta, quién cierra, con qué hora.

    Los dos bloques anteriores prueban al árbitro solo, con el reto informado a
    mano. Este arma la cadena completa —cubos en el estado del mundo, contador,
    permanencia, árbitro— porque el defecto que importa vive justo en la unión:
    el contador da por contado un cubo **un segundo después** de que entró, y si
    el cierre se fechara ahí, todos los equipos perderían ese segundo.

    Las dos marcas de tiempo se inyectan para que el caso sea exacto y no
    dependa de lo que tarde la máquina en correr esto.
    """
    print("=" * 78)
    print("CIERRE POR RETO CUMPLIDO: la cadena completa")
    print("=" * 78)

    permanencia = cfg.conteo_acopio.permanencia_minima_ms
    centros = {d.color: (d.col, d.row) for d in cfg.lugares.depositos}
    lejos = (1.0, 1.0)  # junto al marcador 0: afuera de las tres zonas

    def estado_con(colores_adentro, ts_ms):
        cubos = tuple(
            CuboEnMundo(color=color,
                        col=centros[color][0] if color in colores_adentro else lejos[0],
                        row=centros[color][1] if color in colores_adentro else lejos[1])
            for color in sorted(centros)
        )
        return EstadoMundo(ts_ms=ts_ms, fase="RUNNING", cubos=cubos)

    contador = ContadorAcopio(cfg)
    arbitro, reloj = _arbitro(cfg, "READY")
    reloj.avanzar(PREPARACION_MS)
    arbitro.tictac()                      # empieza la ronda
    t0_mono, ts0 = reloj(), 1_700_000_000_000

    filas = []

    def paso(ms_de_ronda, colores_adentro, etiqueta):
        """Un cuadro: avanza los dos relojes a la par y encadena las dos piezas."""
        reloj.t = t0_mono + ms_de_ronda / 1000.0
        estado = estado_con(colores_adentro, ts0 + ms_de_ronda)
        r = contador.actualizar(estado, estado.ts_ms, mono=reloj())
        aviso = arbitro.observar_reto(r.completo, r.instante_completo)
        filas.append((etiqueta, r.en_posicion, arbitro.fase, aviso))
        return r

    todos = sorted(centros)
    paso(10_000, (), "10 s: los tres cubos afuera")
    paso(120_000, todos[:2], "120 s: entran dos")
    paso(200_000, todos, "200 s: entra el ÚLTIMO cubo")
    paso(200_000 + permanencia - 1, todos, "200,999 s: falta 1 ms de permanencia")
    paso(200_000 + permanencia, todos, "201 s: se cumple la permanencia")

    print("  {:<38} {:>10} {:>10}  {}".format("cuadro", "contados", "fase", "cierre"))
    print("  " + "-" * 84)
    for etiqueta, contados, fase, aviso in filas:
        print("  {:<38} {:>10} {:>10}  {}".format(
            etiqueta, "{}/3".format(contados), fase, "—" if not aviso else "SÍ"))

    tiempo = arbitro.tiempo_final_ms
    comprobaciones = [
        ("la ronda quedó cerrada", arbitro.fase == "FINISHED"),
        ("el motivo es reto_cumplido", arbitro.motivo == MOTIVO_RETO),
        ("el tiempo es el de la ENTRADA (200 s), no el de la permanencia (201 s)",
         tiempo == 200_000),
    ]
    print()
    todo_bien = True
    for nombre, ok in comprobaciones:
        todo_bien = todo_bien and ok
        print("  {:<70} {}".format(nombre, "OK" if ok else "FALLA"))
    if tiempo is not None:
        print("\n  tiempo oficial registrado: {:.3f} s".format(tiempo / 1000.0))

    print("\n  resultado: {}\n".format("TODO OK" if todo_bien else "HAY FALLAS"))
    return todo_bien


def verificar_guardas_de_geometria(cfg) -> bool:
    """Un árbitro no puede juzgar lo que no ve.

    Este bloque existe por una ronda real: el sistema corrió doce segundos con la
    cámara mirando una habitación —la USB no estaba conectada y abrió la
    integrada—, pasó de READY a RUNNING a FINISHED solo, publicó telemetría y
    escribió un acta de 0:08. Todo el mecanismo funcionó. Lo que faltaba era que
    se negara.

    Las tres puertas que se comprueban acá son las tres por las que una ronda
    puede empezar o seguir a ciegas: la tecla, el vencimiento de la preparación,
    y el apagón en medio del juego.
    """
    print("=" * 78)
    print("GUARDAS DE GEOMETRÍA: sin ver la cancha no se arbitra")
    print("=" * 78)

    filas = []

    # --- la puerta de adelante: la tecla ---------------------------------
    a, _ = _arbitro(cfg)
    a.tictac(False)
    a.intentar("ready")
    filas.append(("IDLE + ready SIN coordenadas", a.fase, "IDLE"))

    a, _ = _arbitro(cfg)
    a.tictac(True)
    a.intentar("ready")
    filas.append(("IDLE + ready CON coordenadas", a.fase, "READY"))

    b = Arbitro(cfg, "IDLE", reloj=RelojFalso(), perfil_bloquea=True)
    b.tictac(True)
    b.intentar("ready")
    filas.append(("ready con un perfil que DEFORMA", b.fase, "IDLE"))

    # --- la puerta de atrás: el vencimiento de la preparación ------------
    a, reloj = _arbitro(cfg, "READY")
    reloj.avanzar(PREPARACION_MS)
    a.tictac(False)
    filas.append(("preparación vencida SIN coordenadas", a.fase, "READY"))
    espera = a.reloj()
    a.tictac(True)
    filas.append(("...y cuando vuelven, arranca", a.fase, "RUNNING"))

    # --- el apagón en medio del juego ------------------------------------
    a, reloj = _arbitro(cfg, "READY")
    reloj.avanzar(PREPARACION_MS)
    a.tictac(True)
    reloj.avanzar(30_000)
    a.tictac(False)
    reloj.avanzar(CEGUERA_MS - 1)
    a.tictac(False)
    filas.append(("ceguera de {} ms: aguanta".format(CEGUERA_MS - 1), a.fase, "RUNNING"))
    a.tictac(True)                                   # parpadeo que se recupera
    reloj.avanzar(10_000)
    a.tictac(True)
    filas.append(("recuperada: la ronda sigue", a.fase, "RUNNING"))

    ciega, reloj_c = _arbitro(cfg, "READY")
    reloj_c.avanzar(PREPARACION_MS)
    ciega.tictac(True)
    reloj_c.avanzar(30_000)
    ciega.tictac(False)
    reloj_c.avanzar(CEGUERA_MS + 1)
    ciega.tictac(False)
    filas.append(("ceguera de {} ms: cierra".format(CEGUERA_MS + 1), ciega.fase, "FINISHED"))

    print("  {:<44} {:>10} {:>12}  {}".format("situación", "queda en", "se esperaba", "estado"))
    print("  " + "-" * 84)
    todo_bien = True
    for nombre, obtenido, esperado in filas:
        paso = obtenido == esperado
        todo_bien = todo_bien and paso
        print("  {:<44} {:>10} {:>12}  {}".format(
            nombre, obtenido, esperado, "OK" if paso else "FALLA"))

    # --- lo que no se ve en la tabla -------------------------------------
    print()
    comprobaciones = [
        ("el motivo del cierre es geometria_perdida", ciega.motivo == MOTIVO_GEOMETRIA),
        ("esperando, la preparación ya está consumida: no se devuelve tiempo",
         espera.restante_ms == 0 and espera.total_ms == PREPARACION_MS),
        ("el cronómetro NO se pausa durante el apagón",
         ciega.tiempo_final_ms is not None
         and ciega.tiempo_final_ms >= 30_000 + CEGUERA_MS),
        ("las pérdidas se cuentan", a.perdidas_geometria == 1),
        ("y se registra cuánto duró la peor", a.peor_ceguera_ms == CEGUERA_MS - 1),
    ]

    # El reto no se da por cumplido a ciegas: el falla-abierto conserva el
    # último estado bueno, así que un cubo "en posición" podría completarlo
    # durante un apagón.
    ciego2, reloj2 = _arbitro(cfg, "READY")
    reloj2.avanzar(PREPARACION_MS)
    ciego2.tictac(True)
    reloj2.avanzar(10_000)
    ciego2.observar_reto(False, None)      # se vio incompleto: la regla se cumple
    ciego2.tictac(False)                   # y ahora está ciego
    reloj2.avanzar(500)
    ciego2.observar_reto(True, reloj2())
    comprobaciones.append(
        ("a ciegas no se da por cumplido el reto", ciego2.fase == "RUNNING"))

    # Y sin geometría no hay acta, ni aunque se la pidan directamente.
    try:
        escribir_acta(cfg, motivo=MOTIVO_GEOMETRIA, tiempo_final_ms=1000,
                      tuvo_geometria=False, carpeta=tempfile.mkdtemp())
        se_nego = False
    except ValueError:
        se_nego = True
    comprobaciones.append(("sin geometría, el acta se niega a escribirse", se_nego))

    for nombre, ok in comprobaciones:
        todo_bien = todo_bien and ok
        print("  {:<70} {}".format(nombre, "OK" if ok else "FALLA"))

    print("\n  resultado: {}\n".format("TODO OK" if todo_bien else "HAY FALLAS"))
    return todo_bien


def verificar_acta(cfg) -> bool:
    """El acta: que se escriba, que se lea, y que diga lo que pasó.

    Se comprueba sobre un archivo de verdad, en una carpeta temporal, y no sobre
    el diccionario antes de serializar: el modo de falla que importa es que el
    acta **no se pueda escribir**, y eso solo aparece al escribirla. Un cubo
    ausente tiene `falta_celdas` en infinito, que no es JSON válido; si ese caso
    no estuviera contemplado, el acta reventaría justo en la ronda donde un cubo
    se salió de la cancha, que es cuando más falta hace.
    """
    print("=" * 78)
    print("ACTA: el registro de la ronda")
    print("=" * 78)

    centros = {d.color: (d.col, d.row) for d in cfg.lugares.depositos}
    colores = sorted(centros)
    carpeta = tempfile.mkdtemp(prefix="actas_prueba_")
    contador = ContadorAcopio(cfg)
    permanencia = cfg.conteo_acopio.permanencia_minima_ms

    # Tres cubos adentro y sostenidos: una ronda cumplida.
    cubos = tuple(CuboEnMundo(color=c, col=centros[c][0], row=centros[c][1]) for c in colores)
    contador.actualizar(EstadoMundo(ts_ms=0, fase="RUNNING", cubos=cubos), 0, mono=0.0)
    completo = contador.actualizar(
        EstadoMundo(ts_ms=permanencia, fase="RUNNING", cubos=cubos), permanencia,
        mono=permanencia / 1000.0)
    estado = EstadoMundo(ts_ms=permanencia, fase="FINISHED", cubos=cubos)

    ruta = escribir_acta(cfg, motivo=MOTIVO_RETO, tiempo_final_ms=200_000,
                         tuvo_geometria=True, acopio=completo, estado=estado,
                         perfil={"camara": "Logitech C270", "nivel": "compatible",
                                 "motivo": "", "deforma": False},
                         perdidas_geometria=2, peor_ceguera_ms=740,
                         carpeta=carpeta)
    with open(ruta, encoding="utf-8") as f:
        acta = json.load(f)

    # Y una ronda abortada, sin cubos en la cancha: el caso del infinito.
    vacio = contador.actualizar(EstadoMundo(ts_ms=0, fase="READY"), 0, mono=0.0)
    ruta2 = escribir_acta(cfg, motivo=MOTIVO_ABORTADA, tiempo_final_ms=None,
                          tuvo_geometria=True, acopio=vacio, estado=None,
                          arranque=("green",), carpeta=carpeta)
    with open(ruta2, encoding="utf-8") as f:
        acta2 = json.load(f)

    comprobaciones = [
        ("el archivo existe", os.path.exists(ruta)),
        ("el motivo quedó escrito", acta["motivo"] == MOTIVO_RETO),
        ("el tiempo final, en ms y en m:ss", acta["tiempo_final_ms"] == 200_000
         and acta["tiempo_final"] == "3:20"),
        ("los tres cubos contados", acta["cubos_en_posicion"] == 3),
        ("cada cubo con su color y veredicto",
         sorted(c["color"] for c in acta["cubos"]) == colores
         and all(c["contado"] for c in acta["cubos"])),
        ("las posiciones finales", len(acta["posiciones_finales"]["cubos"]) == 3),
        ("arranque regular", acta["arranque"]["irregular"] is False),
        ("la ronda abortada también deja acta", os.path.exists(ruta2)),
        ("sin cubos, falta_celdas es null y no infinito",
         all(c["falta_celdas"] is None for c in acta2["cubos"])),
        ("el arranque irregular queda marcado",
         acta2["arranque"]["irregular"] is True
         and acta2["arranque"]["cubos_ya_en_zona"] == ["green"]),
        ("sin tiempo, el acta no inventa uno", acta2["tiempo_final"] == "—"),
    ]

    todo_bien = True
    for nombre, ok in comprobaciones:
        todo_bien = todo_bien and ok
        print("  {:<56} {}".format(nombre, "OK" if ok else "FALLA"))

    print("\n  acta de ejemplo: {}".format(os.path.basename(ruta)))
    print("\n  resultado: {}\n".format("TODO OK" if todo_bien else "HAY FALLAS"))
    return todo_bien


def main(argv: list[str] | None = None) -> int:
    argparse.ArgumentParser(
        description="Verifica el árbitro de la ronda: transiciones y cronómetro."
    ).parse_args(argv)

    cfg = _config()
    print()
    print("  preparación: {} s   ·   ronda: {} s   (valores de prueba)".format(
        PREPARACION_MS / 1000, DURACION_MS / 1000))
    print()
    resultados = [
        verificar_transiciones(cfg),
        verificar_reloj(cfg),
        verificar_reto_cumplido(cfg),
        verificar_cierre_por_reto(cfg),
        verificar_guardas_de_geometria(cfg),
        verificar_acta(cfg),
    ]
    print("=" * 78)
    print("RESULTADO GENERAL: {}".format("TODO OK" if all(resultados) else "HAY FALLAS"))
    print("=" * 78)
    return 0 if all(resultados) else 1


if __name__ == "__main__":
    sys.exit(main())
