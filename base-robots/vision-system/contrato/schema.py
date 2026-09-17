"""Esquema del contrato de telemetría del Vision-Rover-Challenge.

Este módulo es la ÚNICA fuente de verdad sobre la forma del mensaje que el
sistema de visión publica por TCP/NDJSON y que los equipos consumen.

¿Por qué vive acá y no en `vision/`?
    Porque el contrato se entrega a los equipos POR SÍ SOLO. Depende únicamente
    de la biblioteca estándar de Python: nada de OpenCV, cámara ni del paquete
    `vision`. La dependencia va en un solo sentido: `vision` puede importar
    `contrato`, nunca al revés.

¿Por qué las estructuras son inmutables (`frozen=True`)?
    Porque el "estado del mundo" no se muta en el lugar: se produce uno nuevo en
    cada cuadro. Así el lado productor (cámara, detectores) y el lado consumidor
    (publicación, grabación) nunca se pisan, aunque corran en relojes distintos.

Piso de versión: Python 3.9
    El contrato corre en **3.9 en adelante**, a diferencia del sistema de visión
    (`vision/`), que exige 3.10+. La distinción es deliberada y la explica quién
    pone el intérprete: `vision/` se instala con un instalador que trae su propio
    Python embebido, así que su versión no depende de la máquina. El contrato se
    entrega suelto y sin instalador: cada equipo lo corre con el Python que ya
    tiene, y el de fábrica de macOS es 3.9. Excluir a un equipo por una mejora
    cosmética no vale la pena.

    En la práctica esto significa: NO usar `slots=True` en estas dataclasses
    (es 3.10+), ni `match`, ni nada que rompa en 3.9. Las anotaciones modernas
    (`X | None`, `dict[str, Any]`) sí se pueden, porque `from __future__ import
    annotations` hace que no se evalúen en tiempo de ejecución.

El contrato es sagrado: ningún campo cambia de nombre, unidad o semántica sin
subir `PROTOCOL_VERSION` y avisar a los equipos.
"""

# Este import NO es un resto de compatibilidad con versiones viejas: hace que
# las anotaciones no se evalúen en tiempo de definición, y es lo que permite
# escribir `-> Grid` dentro de la propia clase `Grid` sin comillas.
from __future__ import annotations

import json
import math
import time
from dataclasses import dataclass
from typing import Any

# --------------------------------------------------------------------------
# Constantes del contrato
#
# Los equipos deben importar estas constantes en vez de escribir los literales
# a mano: si algo cambia, cambia acá y con un salto de versión.
# --------------------------------------------------------------------------

#: Versión del protocolo. Sube de a uno ante CUALQUIER cambio de forma, nombre
#: de campo, unidad o semántica. Un cliente que ve una versión que no conoce
#: debe rechazar el mensaje, no adivinar.
#:
#: v2 (sep-2026): las zonas de acopio pasan a ser rectángulos al centro de los
#: lados, la salida pasa al centro del lado 0–3, y el mensaje suma `depot_size`
#: y `cube_side`. El detalle y la nota de migración están en CONTRATO.md.
PROTOCOL_VERSION = 2

#: Puerto oficial del sistema de visión. El simulador y la cancha real publican
#: en el MISMO puerto, para que un equipo pase de uno a otra sin tocar su código.
#: Es el único lugar donde se define: quien lo necesite lo lee de acá.
DEFAULT_PORT = 2026

#: Fases de la ronda. La visión es árbitro: ella dice en qué fase se está.
#:
#: Cada nombre se define UNA sola vez y `PHASES` se arma con ellos. Si estuvieran
#: la tupla por un lado y los literales sueltos por otro, un día se
#: desincronizarían y el productor emitiría una fase que su propio validador
#: rechaza. Se evita a propósito derivarlos al revés (`A, B, C, D = PHASES`):
#: eso ataría los nombres al ORDEN de la tupla, y reordenarla intercambiaría los
#: significados en silencio.
FASE_IDLE = "IDLE"
FASE_READY = "READY"
FASE_RUNNING = "RUNNING"
FASE_FINISHED = "FINISHED"

PHASES: tuple[str, ...] = (FASE_IDLE, FASE_READY, FASE_RUNNING, FASE_FINISHED)

#: Colores válidos de cubo. El color ES la identidad del cubo: no hay dos cubos
#: del mismo color, por eso no llevan `id`.
CUBE_COLORS: tuple[str, ...] = ("green", "blue", "red")

#: Lado de una celda en milímetros. Las posiciones se expresan en celdas con
#: decimales; multiplicar por este valor da milímetros.
CELL_MM = 20.0

#: El amarillo está RESERVADO para los obstáculos. Nunca es un cubo. Por eso los
#: obstáculos no llevan campo `color`: su color se conoce de antemano.
COLOR_RESERVADO_OBSTACULO = "yellow"

#: Lado del cubo, en milímetros. Es un cubo, así que es también su altura.
#:
#: Viaja además en cada mensaje (`cube_side`, en celdas), y los equipos lo
#: tienen que leer de ahí: el veredicto de "cubo en su zona" depende del lado
#: del cubo tanto como del tamaño de la zona, y un número copiado de un
#: documento no se puede verificar contra lo que publica la cancha.
CUBE_SIDE_MM = 60.0

#: Tamaño de una zona de acopio, en celdas. `LENGTH` es el lado LARGO, que va
#: PARALELO al borde de la cancha donde está apoyada la zona; `DEPTH` es el
#: FONDO, que entra desde ese borde hacia adentro. 10 x 7,5 celdas = 200 x 150 mm.
#:
#: Es UN solo tamaño para las tres zonas, y por eso viaja una sola vez en el
#: mensaje (`depot_size`) y no repetido en cada depot: tres copias del mismo
#: número son tres oportunidades de que un día digan cosas distintas.
#:
#: Estos números son DATOS, no forma: viajan en cada mensaje y los equipos los
#: leen de ahí, así que cambiarlos NO sube la versión del protocolo. El fondo
#: pasó de 100 a 150 mm en sep-2026, después de ver en la cancha real que con
#: 100 la ventana de aceptación quedaba de 15 mm y un cubo bien puesto podía no
#: contar. El criterio conservador no se tocó: se agrandó la zona.
DEPOT_LENGTH_CELLS = 10.0
DEPOT_DEPTH_CELLS = 7.5

#: Los cuatro lados de la cancha, mirándola desde arriba con el marcador 0
#: arriba a la izquierda. Son nombres internos: NO viajan en el mensaje, porque
#: el lado de una zona se DEDUCE de su posición (ver `lado_mas_cercano`).
LADO_ARRIBA = "arriba"        # row = 0,    del marcador 0 al 1
LADO_DERECHA = "derecha"      # col = cols, del marcador 1 al 2
LADO_ABAJO = "abajo"          # row = rows, del marcador 2 al 3
LADO_IZQUIERDA = "izquierda"  # col = 0,    del marcador 3 al 0

# Campos exactos de cada objeto. La validación es estricta —rechaza faltantes y
# sobrantes— porque un campo de más suele ser un typo o un productor de otra
# versión, y es mejor que falle fuerte y temprano que en medio de una ronda.
_CAMPOS_MENSAJE = frozenset(
    ("v", "seq", "ts_ms", "phase", "clock", "grid", "rovers", "cubes", "obstacles", "start",
     "depots", "depot_size", "cube_side")
)
_CAMPOS_GRID = frozenset(("cols", "rows", "cell_mm"))
_CAMPOS_DEPOT_SIZE = frozenset(("length", "depth"))
_CAMPOS_CLOCK = frozenset(("elapsed_ms", "remaining_ms", "total_ms"))
_CAMPOS_ROVER = frozenset(("id", "col", "row", "theta", "age_ms"))
_CAMPOS_CUBE = frozenset(("color", "col", "row", "age_ms"))
_CAMPOS_OBSTACLE = frozenset(("col", "row", "age_ms"))
_CAMPOS_START = frozenset(("col", "row"))
_CAMPOS_DEPOT = frozenset(("color", "col", "row"))


# --------------------------------------------------------------------------
# Base de tiempo del protocolo
# --------------------------------------------------------------------------


def ahora_ms() -> int:
    """Reloj de pared en milisegundos desde época.

    Es de pared y no monótono a propósito: el cliente mide latencia como
    `ahora - ts_ms`, y para eso ambos extremos tienen que hablar del mismo
    origen de tiempo.

    Vive acá —y no en cada productor— porque quien escribe `ts_ms` y quien lo
    interpreta tienen que usar la misma base de tiempo, siempre.
    """
    return int(time.time() * 1000.0)


# --------------------------------------------------------------------------
# Estructuras del mensaje
#
# Todas son `frozen`: representan una foto del mundo en un instante, y una foto
# no se retoca. Para "cambiar" algo se construye una foto nueva
# (`dataclasses.replace` sirve para eso).
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class Grid:
    """Dimensiones de la cancha, en celdas.

    La cancha efectiva es el área encerrada por los cuatro marcadores ArUco de
    esquina, por eso `cols`/`rows` se leen del mensaje y no se asumen fijos.
    """

    cols: int
    rows: int
    cell_mm: float = CELL_MM

    def a_dict(self) -> dict[str, Any]:
        return {"cols": self.cols, "rows": self.rows, "cell_mm": self.cell_mm}

    @staticmethod
    def desde_dict(d: dict[str, Any]) -> Grid:
        return Grid(cols=d["cols"], rows=d["rows"], cell_mm=d["cell_mm"])


@dataclass(frozen=True)
class Rover:
    """Un robot. Su identidad es el ID de su marcador ArUco.

    Los dos robots son negros e idénticos: lo único que los distingue es el
    marcador. Por eso `id` nunca se infiere de la posición ni del orden en la
    lista.
    """

    id: int
    col: float
    row: float
    theta: float  # grados, 0 = derecha, sentido antihorario
    age_ms: int  # 0 = recién visto; creciente = ocluido o no detectado

    def a_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "col": self.col,
            "row": self.row,
            "theta": self.theta,
            "age_ms": self.age_ms,
        }

    @staticmethod
    def desde_dict(d: dict[str, Any]) -> Rover:
        return Rover(
            id=d["id"], col=d["col"], row=d["row"], theta=d["theta"], age_ms=d["age_ms"]
        )


@dataclass(frozen=True)
class Cube:
    """Un cubo de 6 cm. El color es la identidad: no hay dos del mismo color."""

    color: str
    col: float
    row: float
    age_ms: int

    def a_dict(self) -> dict[str, Any]:
        return {"color": self.color, "col": self.col, "row": self.row, "age_ms": self.age_ms}

    @staticmethod
    def desde_dict(d: dict[str, Any]) -> Cube:
        return Cube(color=d["color"], col=d["col"], row=d["row"], age_ms=d["age_ms"])


@dataclass(frozen=True)
class Obstacle:
    """Un bloque amarillo de 10 cm.

    No lleva `color` porque el amarillo está reservado para obstáculos, ni `id`
    porque son intercambiables entre sí: lo único que importa es dónde están.
    """

    col: float
    row: float
    age_ms: int

    def a_dict(self) -> dict[str, Any]:
        return {"col": self.col, "row": self.row, "age_ms": self.age_ms}

    @staticmethod
    def desde_dict(d: dict[str, Any]) -> Obstacle:
        return Obstacle(col=d["col"], row=d["row"], age_ms=d["age_ms"])


@dataclass(frozen=True)
class Start:
    """Punto de salida de los robots, compartido por los dos.

    Desde v2 está al CENTRO del lado que va del marcador 0 al 3 —el lado
    izquierdo mirando la cancha desde arriba—, ya no en la esquina del marcador
    0. El origen de coordenadas NO se movió: sigue siendo el centro del marcador
    0. Lo que cambió es dónde arrancan los robots, no desde dónde se mide.

    Es un lugar FIJO: se declara por configuración, no se detecta. Por eso no
    lleva `age_ms`: nunca envejece ni se ocluye.
    """

    col: float
    row: float

    def a_dict(self) -> dict[str, Any]:
        return {"col": self.col, "row": self.row}

    @staticmethod
    def desde_dict(d: dict[str, Any]) -> Start:
        return Start(col=d["col"], row=d["row"])


@dataclass(frozen=True)
class Depot:
    """Zona de acopio de un color. Cada cubo va al depot de SU color.

    Desde v2 la zona es un RECTÁNGULO, y `col`/`row` son su CENTRO. Su tamaño no
    está acá sino en `DepotSize`, que viaja una sola vez en el mensaje porque es
    el mismo para las tres.

    La orientación NO se declara: se deduce. La zona apoya su lado largo sobre
    el borde de la cancha más cercano a su centro (`lado_mas_cercano`). Con los
    números de esta edición el centro queda a 3,75 celdas de su borde y a 21,5
    de los dos perpendiculares, así que la deducción no admite duda. Declararla
    aparte sería un segundo dato que puede contradecir al primero.

    Va en una lista separada de `cubes` aunque compartan el color, porque los
    cubos se DETECTAN (se mueven, se ocluyen, envejecen) y los depots se
    DECLARAN (son fijos y siempre están).
    """

    color: str
    col: float
    row: float

    def a_dict(self) -> dict[str, Any]:
        return {"color": self.color, "col": self.col, "row": self.row}

    @staticmethod
    def desde_dict(d: dict[str, Any]) -> Depot:
        return Depot(color=d["color"], col=d["col"], row=d["row"])


@dataclass(frozen=True)
class DepotSize:
    """Tamaño de las zonas de acopio, en celdas. Uno solo para las tres.

    `length` es el lado largo, PARALELO al borde donde apoya la zona; `depth` es
    el fondo, que entra desde ese borde hacia adentro de la cancha. Se expresa
    así —y no como ancho y alto— porque la zona gira con su lado: "largo sobre
    el borde" vale igual para la de arriba que para la de la derecha, y "ancho"
    querría decir cosas distintas en cada una.
    """

    length: float
    depth: float

    def a_dict(self) -> dict[str, Any]:
        return {"length": self.length, "depth": self.depth}

    @staticmethod
    def desde_dict(d: dict[str, Any]) -> DepotSize:
        return DepotSize(length=d["length"], depth=d["depth"])


@dataclass(frozen=True)
class Clock:
    """El cronómetro oficial de la ronda, en milisegundos.

    Los tres valores son del **mismo instante** que el `ts_ms` del mensaje que
    los lleva. Eso es lo que permite resolver con **un** mensaje y sin memoria en
    qué punto de la ronda está la cancha: un robot no puede llevar su propio
    reloj, porque se desvía del oficial, y uno que se conecta tarde no sabría en
    qué momento entró.

    Por qué tres valores y no uno
    -----------------------------
    Porque cada fase tiene una pregunta distinta. En `READY` interesa cuánto
    falta para poder moverse; en `RUNNING`, cuánto queda de ronda; al terminar,
    **cuánto tardó**, que es `elapsed_ms`. Un solo campo obligaría a saber de qué
    fase es el total para interpretarlo, y un campo cuyo significado depende de
    otro campo se lee mal una vez y se lee mal para siempre.

    Tampoco viaja un instante absoluto de vencimiento: eso obligaría a tener el
    reloj sincronizado con el nuestro, que es exactamente el reloj propio que
    esto viene a evitar.

    `total_ms` en cero significa que **no se está contando nada**. Es lo que
    distingue "esta fase no cuenta" de "cuenta y va en cero".

    Vale siempre `elapsed_ms + remaining_ms == total_ms`.
    """

    elapsed_ms: int
    remaining_ms: int
    total_ms: int

    def a_dict(self) -> dict[str, Any]:
        return {"elapsed_ms": self.elapsed_ms, "remaining_ms": self.remaining_ms,
                "total_ms": self.total_ms}

    @staticmethod
    def desde_dict(d: dict[str, Any]) -> Clock:
        return Clock(elapsed_ms=d["elapsed_ms"], remaining_ms=d["remaining_ms"],
                     total_ms=d["total_ms"])


@dataclass(frozen=True)
class Mensaje:
    """Un mensaje completo de telemetría: la foto del mundo en un instante.

    `seq` y `ts_ms` los pone el publicador, no el detector: sirven para que el
    consumidor detecte pérdidas (saltos de `seq`) y mida latencia real
    (`ahora - ts_ms`, con `ts_ms` = instante de CAPTURA del cuadro, no de envío).
    """

    seq: int
    ts_ms: int
    phase: str
    grid: Grid
    start: Start
    # Sin valor por defecto a propósito: un productor que se olvida de declarar
    # el tamaño de las zonas o del cubo tiene que fallar al armar el mensaje, no
    # publicar un número inventado por esta clase.
    depot_size: DepotSize
    cube_side: float  # en celdas, como toda longitud del mensaje
    clock: Clock      # el cronómetro oficial, del mismo instante que ts_ms
    depots: tuple[Depot, ...] = ()
    rovers: tuple[Rover, ...] = ()
    cubes: tuple[Cube, ...] = ()
    obstacles: tuple[Obstacle, ...] = ()
    v: int = PROTOCOL_VERSION

    def a_dict(self) -> dict[str, Any]:
        return {
            "v": self.v,
            "seq": self.seq,
            "ts_ms": self.ts_ms,
            "phase": self.phase,
            "grid": self.grid.a_dict(),
            "rovers": [r.a_dict() for r in self.rovers],
            "cubes": [c.a_dict() for c in self.cubes],
            "obstacles": [o.a_dict() for o in self.obstacles],
            "start": self.start.a_dict(),
            "depots": [d.a_dict() for d in self.depots],
            "depot_size": self.depot_size.a_dict(),
            "cube_side": self.cube_side,
            "clock": self.clock.a_dict(),
        }

    @staticmethod
    def desde_dict(d: dict[str, Any]) -> Mensaje:
        """Construye un `Mensaje` a partir de un dict ya parseado.

        Valida primero: preferimos fallar con un mensaje claro antes que
        construir un objeto a medias que reviente más adelante.
        """
        error = validate_message(d)
        if error is not None:
            raise ValueError(error)
        return Mensaje(
            v=d["v"],
            seq=d["seq"],
            ts_ms=d["ts_ms"],
            phase=d["phase"],
            grid=Grid.desde_dict(d["grid"]),
            start=Start.desde_dict(d["start"]),
            depot_size=DepotSize.desde_dict(d["depot_size"]),
            cube_side=d["cube_side"],
            clock=Clock.desde_dict(d["clock"]),
            depots=tuple(Depot.desde_dict(x) for x in d["depots"]),
            rovers=tuple(Rover.desde_dict(x) for x in d["rovers"]),
            cubes=tuple(Cube.desde_dict(x) for x in d["cubes"]),
            obstacles=tuple(Obstacle.desde_dict(x) for x in d["obstacles"]),
        )


# --------------------------------------------------------------------------
# Validación
# --------------------------------------------------------------------------


def _es_entero(valor: Any) -> bool:
    """True si es un entero de verdad.

    `bool` es subclase de `int` en Python, así que `True` pasaría como entero.
    Lo excluimos a mano: un `True` en `seq` es un bug, no un dato.
    """
    return isinstance(valor, int) and not isinstance(valor, bool)


def _es_numero(valor: Any) -> bool:
    """True si es un número finito.

    Aceptamos `int` donde el contrato dice `float` porque JSON serializa `2.0`
    como `2`: rechazarlo tiraría mensajes perfectamente válidos. La regla de
    "nunca redondear a entero" es del PRODUCTOR, no del validador.
    """
    if isinstance(valor, bool):
        return False
    if not isinstance(valor, (int, float)):
        return False
    return math.isfinite(valor)


def _revisar_campos(obj: Any, esperados: frozenset, donde: str) -> str | None:
    """Verifica que `obj` sea un dict con exactamente los campos esperados."""
    if not isinstance(obj, dict):
        return "{}: se esperaba un objeto, llegó {}".format(donde, type(obj).__name__)
    presentes = set(obj.keys())
    faltantes = esperados - presentes
    if faltantes:
        return "{}: faltan campos {}".format(donde, sorted(faltantes))
    sobrantes = presentes - esperados
    if sobrantes:
        return "{}: campos no reconocidos {}".format(donde, sorted(sobrantes))
    return None


def _revisar_posicion(obj: dict[str, Any], donde: str) -> str | None:
    """Valida `col`/`row`.

    NO se exige que caigan dentro de la grilla: la corrección de paralaje puede
    dejar un objeto apenas afuera del borde, y eso es un dato válido, no un
    error de contrato. Solo se exige que sean números finitos.
    """
    for campo in ("col", "row"):
        if not _es_numero(obj[campo]):
            return "{}: '{}' debe ser un número finito, llegó {!r}".format(
                donde, campo, obj[campo]
            )
    return None


def _revisar_edad(obj: dict[str, Any], donde: str) -> str | None:
    if not _es_entero(obj["age_ms"]) or obj["age_ms"] < 0:
        return "{}: 'age_ms' debe ser un entero >= 0, llegó {!r}".format(donde, obj["age_ms"])
    return None


def _revisar_lista(msg: dict[str, Any], nombre: str) -> str | None:
    if not isinstance(msg[nombre], list):
        return "'{}' debe ser una lista, llegó {}".format(nombre, type(msg[nombre]).__name__)
    return None


def validate_message(msg: Any) -> str | None:
    """Valida un mensaje contra el contrato.

    Devuelve `None` si el mensaje cumple, o un texto claro con el PRIMER error
    encontrado si no. Devolver texto en vez de lanzar excepción es a propósito:
    un cliente debe poder descartar un mensaje malo y seguir andando, sin
    envolver todo en try/except.

    Rechaza, entre otras cosas: versión desconocida, campos faltantes o
    sobrantes, fase inválida, `theta` fuera de rango, colores fuera del
    contrato, colores de cubo duplicados (el color es la identidad), IDs de
    rover duplicados, y cubos sin un depot de su color.
    """
    # --- raíz -------------------------------------------------------------
    error = _revisar_campos(msg, _CAMPOS_MENSAJE, "mensaje")
    if error:
        return error

    # La versión se revisa primero: si no la conocemos, el resto de la forma no
    # es confiable y cualquier otro error sería ruido.
    if not _es_entero(msg["v"]):
        return "'v' debe ser un entero, llegó {!r}".format(msg["v"])
    if msg["v"] != PROTOCOL_VERSION:
        return "versión de protocolo desconocida: {} (esta implementación entiende {})".format(
            msg["v"], PROTOCOL_VERSION
        )

    if not _es_entero(msg["seq"]) or msg["seq"] < 0:
        return "'seq' debe ser un entero >= 0, llegó {!r}".format(msg["seq"])
    if not _es_entero(msg["ts_ms"]) or msg["ts_ms"] < 0:
        return "'ts_ms' debe ser un entero >= 0, llegó {!r}".format(msg["ts_ms"])
    if msg["phase"] not in PHASES:
        return "'phase' inválida: {!r} (válidas: {})".format(msg["phase"], list(PHASES))

    # --- clock ------------------------------------------------------------
    error = _revisar_campos(msg["clock"], _CAMPOS_CLOCK, "clock")
    if error:
        return error
    reloj = msg["clock"]
    for campo in ("elapsed_ms", "remaining_ms", "total_ms"):
        if not _es_entero(reloj[campo]) or reloj[campo] < 0:
            return "clock: '{}' debe ser un entero >= 0, llegó {!r}".format(
                campo, reloj[campo])
    # La suma no es un capricho: es lo que hace que los tres valores sean el
    # mismo instante y no tres lecturas de momentos distintos. Si no cierra, el
    # productor está armando el reloj a mano en algún lado.
    if reloj["elapsed_ms"] + reloj["remaining_ms"] != reloj["total_ms"]:
        return (
            "clock: elapsed_ms + remaining_ms debe ser igual a total_ms, llegó "
            "{} + {} = {} contra {}".format(
                reloj["elapsed_ms"], reloj["remaining_ms"],
                reloj["elapsed_ms"] + reloj["remaining_ms"], reloj["total_ms"])
        )

    # --- grid -------------------------------------------------------------
    error = _revisar_campos(msg["grid"], _CAMPOS_GRID, "grid")
    if error:
        return error
    grid = msg["grid"]
    for campo in ("cols", "rows"):
        if not _es_entero(grid[campo]) or grid[campo] <= 0:
            return "grid: '{}' debe ser un entero > 0, llegó {!r}".format(campo, grid[campo])
    if not _es_numero(grid["cell_mm"]) or grid["cell_mm"] <= 0:
        return "grid: 'cell_mm' debe ser un número > 0, llegó {!r}".format(grid["cell_mm"])

    # --- depot_size y cube_side -------------------------------------------
    error = _revisar_campos(msg["depot_size"], _CAMPOS_DEPOT_SIZE, "depot_size")
    if error:
        return error
    for campo in ("length", "depth"):
        valor = msg["depot_size"][campo]
        if not _es_numero(valor) or valor <= 0:
            return "depot_size: '{}' debe ser un número > 0, llegó {!r}".format(campo, valor)
    if not _es_numero(msg["cube_side"]) or msg["cube_side"] <= 0:
        return "'cube_side' debe ser un número > 0, llegó {!r}".format(msg["cube_side"])

    # --- listas dinámicas -------------------------------------------------
    for nombre in ("rovers", "cubes", "obstacles", "depots"):
        error = _revisar_lista(msg, nombre)
        if error:
            return error

    # --- rovers -----------------------------------------------------------
    ids_vistos = set()
    for i, rover in enumerate(msg["rovers"]):
        donde = "rovers[{}]".format(i)
        error = _revisar_campos(rover, _CAMPOS_ROVER, donde)
        if error:
            return error
        if not _es_entero(rover["id"]) or rover["id"] < 0:
            return "{}: 'id' debe ser un entero >= 0 (ID del marcador ArUco), llegó {!r}".format(
                donde, rover["id"]
            )
        if rover["id"] in ids_vistos:
            return "{}: 'id' duplicado {} — cada rover aparece una sola vez".format(
                donde, rover["id"]
            )
        ids_vistos.add(rover["id"])
        error = _revisar_posicion(rover, donde) or _revisar_edad(rover, donde)
        if error:
            return error
        if not _es_numero(rover["theta"]) or not (0.0 <= rover["theta"] <= 360.0):
            return "{}: 'theta' debe estar en grados dentro de [0, 360], llegó {!r}".format(
                donde, rover["theta"]
            )

    # --- depots (se validan antes que los cubos porque los cubos dependen) --
    colores_depot = set()
    for i, depot in enumerate(msg["depots"]):
        donde = "depots[{}]".format(i)
        error = _revisar_campos(depot, _CAMPOS_DEPOT, donde)
        if error:
            return error
        if depot["color"] not in CUBE_COLORS:
            return "{}: color fuera del contrato: {!r} (válidos: {})".format(
                donde, depot["color"], list(CUBE_COLORS)
            )
        if depot["color"] in colores_depot:
            return "{}: hay más de un depot de color {!r} — debe haber uno por color".format(
                donde, depot["color"]
            )
        colores_depot.add(depot["color"])
        error = _revisar_posicion(depot, donde)
        if error:
            return error

    # --- cubes ------------------------------------------------------------
    colores_cubo = set()
    for i, cubo in enumerate(msg["cubes"]):
        donde = "cubes[{}]".format(i)
        error = _revisar_campos(cubo, _CAMPOS_CUBE, donde)
        if error:
            return error
        if cubo["color"] not in CUBE_COLORS:
            return "{}: color fuera del contrato: {!r} (válidos: {}; el {} está reservado " \
                   "para obstáculos)".format(
                       donde, cubo["color"], list(CUBE_COLORS), COLOR_RESERVADO_OBSTACULO
                   )
        if cubo["color"] in colores_cubo:
            return "{}: color de cubo duplicado {!r} — el color ES la identidad del cubo".format(
                donde, cubo["color"]
            )
        colores_cubo.add(cubo["color"])
        error = _revisar_posicion(cubo, donde) or _revisar_edad(cubo, donde)
        if error:
            return error

    # Invariante de juego: todo cubo tiene a dónde ir. Un cubo sin depot de su
    # color dejaría a los equipos con una tarea imposible.
    sin_destino = sorted(colores_cubo - colores_depot)
    if sin_destino:
        return "hay cubos sin depot de su color: {} (depots presentes: {})".format(
            sin_destino, sorted(colores_depot)
        )

    # --- obstacles --------------------------------------------------------
    for i, obst in enumerate(msg["obstacles"]):
        donde = "obstacles[{}]".format(i)
        error = _revisar_campos(obst, _CAMPOS_OBSTACLE, donde)
        if error:
            return error
        error = _revisar_posicion(obst, donde) or _revisar_edad(obst, donde)
        if error:
            return error

    # --- start ------------------------------------------------------------
    error = _revisar_campos(msg["start"], _CAMPOS_START, "start")
    if error:
        return error
    error = _revisar_posicion(msg["start"], "start")
    if error:
        return error

    return None


# --------------------------------------------------------------------------
# Geometría de las zonas de acopio
#
# Vive en el contrato —y no en `vision/`— porque el veredicto que muestra la
# pantalla del sistema de visión y el que calcula el equipo en su rover tienen
# que ser EL MISMO. Si cada lado escribiera su propia versión, un cubo podría
# estar "adentro" para la visión y "afuera" para el equipo, y no habría forma de
# decidir quién tiene razón.
#
# Todo entra y sale como FLOTANTES, no como objetos: el contrato se consume como
# JSON crudo, así que pedir atributos obligaría a envolver los diccionarios del
# mensaje, y pedir claves obligaría a lo contrario del lado de la visión. Con
# números sueltos sirve igual a un diccionario, a estas dataclases y al estado
# del mundo, sin adaptadores.
# --------------------------------------------------------------------------


def lado_mas_cercano(*, col: float, row: float, cols: float, rows: float) -> str:
    """A qué borde de la cancha está más cerca un punto.

    Es la regla con la que se deduce la orientación de una zona de acopio, en
    vez de declararla: la zona apoya su lado largo sobre este borde.

    Lanza `ValueError` si hay empate, en vez de elegir uno. Un empate significa
    que el punto está sobre una diagonal de la cancha —el caso de las zonas en
    las esquinas del protocolo v1— y ahí la orientación es genuinamente
    ambigua: elegir a ciegas daría un rectángulo girado 90 grados sin que nadie
    se entere.
    """
    distancias = (
        (row, LADO_ARRIBA),
        (cols - col, LADO_DERECHA),
        (rows - row, LADO_ABAJO),
        (col, LADO_IZQUIERDA),
    )
    ordenadas = sorted(distancias, key=lambda x: x[0])
    if abs(ordenadas[0][0] - ordenadas[1][0]) < 1e-9:
        raise ValueError(
            "no se puede deducir el lado de ({:.3f}, {:.3f}) en una cancha de {}x{}: "
            "está a la misma distancia del borde {} que del {}".format(
                col, row, cols, rows, ordenadas[0][1], ordenadas[1][1])
        )
    return ordenadas[0][1]


@dataclass(frozen=True)
class GeometriaDepot:
    """El rectángulo de una zona y la ventana donde tiene que caer el cubo.

    `semi_col` y `semi_row` son las medias extensiones del RECTÁNGULO de la
    zona; `margen` es la media diagonal del cubo, y restándolo se obtiene la
    VENTANA: dónde puede estar el centro del cubo para que el cubo entero quede
    adentro, sea cual sea su rotación.

    Con la zona de 200 x 150 mm y un cubo de 60 mm, la ventana mide
    115,2 x 65,1 mm: el centro del cubo tiene 32,6 mm de tolerancia a cada lado
    del eje de la zona sobre el fondo, y 57,6 mm a lo largo.

    Esa holgura es la razón por la que el fondo pasó de 100 a 150 mm. Con 100,
    la ventana del fondo medía 15,2 mm —7,6 mm a cada lado— y en la cancha real
    se vio que un cubo bien puesto oscilaba a través de ese límite entre cuadro
    y cuadro. La media diagonal se lleva 42,4 mm de cada lado y no se negocia:
    es lo que hace que el veredicto valga para cualquier rotación. Lo que se
    agranda es la zona.
    """

    col: float
    row: float
    lado: str
    semi_col: float
    semi_row: float
    margen: float

    @property
    def ventana_col(self) -> float:
        """Media ventana sobre `col`. Negativa = el cubo no entra nunca."""
        return self.semi_col - self.margen

    @property
    def ventana_row(self) -> float:
        return self.semi_row - self.margen


@dataclass(frozen=True)
class VeredictoDepot:
    """Si el cubo está completamente adentro, y cuánto le falta si no.

    `falta_celdas` es la distancia del centro del cubo a la ventana: 0 cuando
    está adentro, y cuánto hay que moverlo cuando no. Sirve para depurar —y para
    que un rover sepa si le falta un milímetro o media cancha— en vez de tener
    que deducirlo de un booleano.
    """

    adentro: bool
    falta_celdas: float


def geometria_depot(
    *,
    col: float,
    row: float,
    length: float,
    depth: float,
    cols: float,
    rows: float,
    cube_side: float,
) -> GeometriaDepot:
    """Arma la geometría de una zona a partir de lo que viaja en el mensaje.

    `col`/`row` son el centro de la zona (`depots[i]`), `length`/`depth` su
    tamaño (`depot_size`), `cols`/`rows` la cancha (`grid`) y `cube_side` el
    lado del cubo, todo en celdas.

    El lado largo va paralelo al borde donde apoya la zona, así que cuál de las
    dos medidas corresponde a `col` y cuál a `row` depende del lado deducido.
    """
    lado = lado_mas_cercano(col=col, row=row, cols=cols, rows=rows)
    if lado in (LADO_ARRIBA, LADO_ABAJO):
        semi_col, semi_row = length / 2.0, depth / 2.0
    else:
        semi_col, semi_row = depth / 2.0, length / 2.0
    # Media diagonal del cubo: el radio del círculo que lo contiene entero. Es
    # el margen conservador que hace que el veredicto valga para CUALQUIER
    # rotación del cubo, y que el equipo pueda calcularlo con el puro centro,
    # que es lo único que el contrato publica.
    margen = cube_side * math.sqrt(2.0) / 2.0
    return GeometriaDepot(col=col, row=row, lado=lado, semi_col=semi_col,
                          semi_row=semi_row, margen=margen)


def cubo_en_depot(*, col: float, row: float, geometria: GeometriaDepot) -> VeredictoDepot:
    """¿El cubo entero está dentro de la zona? `col`/`row` son su centro.

    El criterio es CONSERVADOR por media diagonal: el centro del cubo tiene que
    estar a media diagonal de cada borde del rectángulo. Con eso, el cubo entero
    queda adentro con cualquier rotación, y no hace falta conocerla —el contrato
    no publica la rotación del cubo—.
    """
    exceso_col = max(0.0, abs(col - geometria.col) - geometria.ventana_col)
    exceso_row = max(0.0, abs(row - geometria.row) - geometria.ventana_row)
    falta = math.hypot(exceso_col, exceso_row)
    return VeredictoDepot(adentro=falta == 0.0, falta_celdas=falta)


# --------------------------------------------------------------------------
# Formato de cable (NDJSON)
#
# Vive en el contrato para que el simulador, el cliente de referencia y el
# sistema de visión real usen exactamente el mismo código de serialización. Si
# el formato de cable estuviera duplicado, tarde o temprano divergiría.
# --------------------------------------------------------------------------


def codificar_ndjson(msg: Any) -> str:
    """Serializa un mensaje (dict o `Mensaje`) a una línea NDJSON con `\\n`.

    `separators` sin espacios para no gastar ancho de banda, y `ensure_ascii`
    en False porque no hay razón para escapar: el contrato es ASCII puro.
    """
    if isinstance(msg, Mensaje):
        msg = msg.a_dict()
    return json.dumps(msg, separators=(",", ":"), ensure_ascii=False) + "\n"


def decodificar_ndjson(linea: str) -> dict[str, Any]:
    """Parsea una línea NDJSON a dict. Lanza `ValueError` si no es JSON válido.

    No valida el contrato: eso es trabajo de `validate_message`. Separar
    "parsear" de "validar" permite reportar los dos errores por separado.
    """
    dato = json.loads(linea)
    if not isinstance(dato, dict):
        raise ValueError("la línea no contiene un objeto JSON")
    return dato
