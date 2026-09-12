"""Cliente de referencia del Vision-Rover-Challenge.

Hace tres cosas, y a propósito nada más:

1. Muestra a los equipos **cómo se consume el stream**: conectarse, leer línea
   por línea, parsear, y sacar los datos del mensaje sin suponer nada.
2. **Valida** cada mensaje contra el contrato, así sirve de autochequeo: si el
   productor (simulador o visión real) se sale del contrato, esto lo canta.
3. **Mide** latencia (`ahora - ts_ms`) y saltos de secuencia, que son las dos
   señales que le dicen a un equipo si sus datos sirven o están viejos.

    python -m contrato.test_client --host 127.0.0.1 --port 2026

Sale con código 0 si todos los mensajes cumplieron el contrato, y 1 si hubo
alguno inválido.
"""

from __future__ import annotations

import argparse
import math
import socket
import sys
import time
from collections.abc import Iterator
from typing import Any

# `cubo_en_depot` y `geometria_depot` se importan SOLO para el autochequeo del
# final de este archivo, que compara el veredicto del contrato contra el que se
# calcula acá a mano. NO son parte del camino que sigue un equipo: el ejemplo
# que hay que copiar es `cubo_en_su_zona`, escrito sobre el JSON crudo y sin
# importar nada.
try:  # como paquete: python -m contrato.test_client
    from .schema import (
        DEFAULT_PORT, ahora_ms, cubo_en_depot, decodificar_ndjson, geometria_depot,
        validate_message,
    )
except ImportError:  # como script suelto: python contrato/test_client.py
    from schema import (  # type: ignore[no-redef]
        DEFAULT_PORT, ahora_ms, cubo_en_depot, decodificar_ndjson, geometria_depot,
        validate_message,
    )


# --------------------------------------------------------------------------
# Lectura del stream
# --------------------------------------------------------------------------


def leer_lineas(conexion: socket.socket) -> Iterator[str]:
    """Devuelve una línea NDJSON completa por vez.

    ESTE ES EL ERROR CLÁSICO al consumir el stream: TCP no respeta los límites
    de los mensajes. Un `recv()` puede traer media línea, o dos líneas y media.
    Por eso hay que acumular en un buffer y cortar por `\\n`, nunca asumir que
    "lo que llegó" es un mensaje entero.

    Está escrito con un buffer explícito, en vez de `socket.makefile()`, porque
    esta es la versión que se puede traducir a CircuitPython casi tal cual.
    """
    buffer = b""
    while True:
        trozo = conexion.recv(65536)
        if not trozo:
            return  # el productor cerró la conexión
        buffer += trozo
        while b"\n" in buffer:
            linea, buffer = buffer.split(b"\n", 1)
            if linea.strip():
                yield linea.decode("utf-8")


# ==========================================================================
# ▼▼▼  EJEMPLO PARA COPIAR  ▼▼▼
#
# Todo lo que sigue hasta el próximo cartel trabaja sobre el JSON crudo, con la
# biblioteca estándar y nada más. Es lo que un equipo copia a su rover.
# ==========================================================================


def lado_de_la_zona(depot: dict[str, Any], grid: dict[str, Any]) -> str:
    """A qué borde de la cancha apoya una zona de acopio.

    La orientación NO viene en el mensaje: se deduce. Cada zona apoya su lado
    largo sobre el borde más cercano a su centro, y está a 3,75 celdas de ese
    borde contra 21,5 de los otros, así que no hay ambigüedad.
    """
    distancias = {
        "arriba": depot["row"],
        "abajo": grid["rows"] - depot["row"],
        "izquierda": depot["col"],
        "derecha": grid["cols"] - depot["col"],
    }
    return min(distancias, key=lambda lado: distancias[lado])


def cubo_en_su_zona(cubo, depot, depot_size, grid, cube_side):
    """¿El cubo entero está dentro de su zona? Devuelve `(adentro, falta)`.

    `falta` es cuántas celdas hay que moverlo para que entre, y vale 0 si ya
    está adentro.

    El criterio es **conservador por media diagonal**: el centro del cubo tiene
    que estar a `cube_side * raíz(2) / 2` de cada borde del rectángulo. Con eso
    el cubo entero queda adentro **con cualquier rotación**, y por eso alcanza
    con el centro, que es lo único que el contrato publica: la rotación del cubo
    no viaja en el mensaje y no hace falta.

    Ojo con el largo y el fondo: `length` es el lado que va PARALELO al borde y
    `depth` el que entra hacia adentro, así que cuál de los dos corresponde a
    `col` y cuál a `row` depende del lado donde esté la zona.
    """
    lado = lado_de_la_zona(depot, grid)
    if lado in ("arriba", "abajo"):
        semi_col = depot_size["length"] / 2.0
        semi_row = depot_size["depth"] / 2.0
    else:
        semi_col = depot_size["depth"] / 2.0
        semi_row = depot_size["length"] / 2.0

    margen = cube_side * math.sqrt(2.0) / 2.0
    ventana_col = semi_col - margen
    ventana_row = semi_row - margen

    exceso_col = max(0.0, abs(cubo["col"] - depot["col"]) - ventana_col)
    exceso_row = max(0.0, abs(cubo["row"] - depot["row"]) - ventana_row)
    falta = math.hypot(exceso_col, exceso_row)
    return falta == 0.0, falta


def _reloj(clock: dict[str, Any]) -> str:
    """El cronómetro del mensaje, en texto.

    `total_ms` en cero significa que no se está contando nada, y por eso no se
    imprime un "0:00 de 0:00" que parecería una ronda a punto de terminar.

    El tiempo NO se calcula con el reloj de esta máquina: sale tal cual del
    mensaje, que es el punto del campo. Un cliente que llevara su propio reloj
    se desviaría del oficial, y uno que se conecta tarde no sabría en qué
    momento entró.
    """
    if not clock["total_ms"]:
        return "sin cuenta"
    return "{}  (quedan {})".format(
        _mmss(clock["elapsed_ms"]), _mmss(clock["remaining_ms"]))


def _mmss(ms: int) -> str:
    segundos = ms // 1000
    return "{}:{:02d}".format(segundos // 60, segundos % 60)


# --------------------------------------------------------------------------
# Ejemplo de consumo — lo que un equipo haría de verdad
# --------------------------------------------------------------------------


def ejemplo_de_consumo(msg: dict[str, Any]) -> list[str]:
    """Saca del mensaje lo que le importaría a un rover, y explica el porqué.

    Se llama una sola vez (con el primer mensaje) porque es didáctico, no
    funcional. Fijate en dos cosas:

    - Se ITERA sobre las listas y se busca por identidad (`id` del rover,
      `color` del cubo). NUNCA se indexa por posición fija: la cantidad de
      objetos cambia entre cuadros, y `rovers[0]` hoy puede ser otro robot
      mañana.
    - Las dimensiones salen de `grid`, no de una constante. La cancha efectiva
      es el área entre los cuatro marcadores ArUco y puede no ser exactamente
      la nominal.
    """
    lineas = []
    grid = msg["grid"]
    lineas.append(
        "cancha: {}x{} celdas de {} mm  |  fase: {}  |  {}".format(
            grid["cols"], grid["rows"], grid["cell_mm"], msg["phase"],
            _reloj(msg["clock"]),
        )
    )

    # Mi rover es el del ID de MI marcador ArUco. Se busca, no se indexa.
    MI_ID = None
    for rover in msg["rovers"]:
        if MI_ID is None:
            MI_ID = rover["id"]  # en un equipo real, esto es una constante suya
        lineas.append(
            "rover id={}  col={:.2f} row={:.2f} theta={:.1f}°  age={} ms".format(
                rover["id"], rover["col"], rover["row"], rover["theta"], rover["age_ms"]
            )
        )

    # Los TAMAÑOS se leen del mensaje, igual que la grilla: no se asumen. El
    # veredicto de "cubo en su zona" depende de los dos.
    lineas.append(
        "zona de acopio: {} x {} celdas (largo x fondo)  |  cubo: {} celdas de lado".format(
            msg["depot_size"]["length"], msg["depot_size"]["depth"], msg["cube_side"]
        )
    )

    # Cada cubo va al depot de SU color: se cruzan las dos listas por color.
    depots_por_color = {d["color"]: d for d in msg["depots"]}
    for cubo in msg["cubes"]:
        destino = depots_por_color[cubo["color"]]
        adentro, falta = cubo_en_su_zona(
            cubo, destino, msg["depot_size"], msg["grid"], msg["cube_side"]
        )
        veredicto = "EN POSICIÓN" if adentro else "le falta {:.2f} celdas".format(falta)
        lineas.append(
            "cubo {:<5} en ({:.2f}, {:.2f}) -> zona {} ({:.2f}, {:.2f})  age={} ms  [{}]".format(
                cubo["color"], cubo["col"], cubo["row"],
                lado_de_la_zona(destino, msg["grid"]), destino["col"], destino["row"],
                cubo["age_ms"], veredicto,
            )
        )

    for obst in msg["obstacles"]:
        lineas.append("obstáculo amarillo en ({:.2f}, {:.2f})".format(obst["col"], obst["row"]))

    lineas.append(
        "salida en ({:.2f}, {:.2f})".format(msg["start"]["col"], msg["start"]["row"])
    )
    return lineas


# ==========================================================================
# ▲▲▲  FIN DEL EJEMPLO PARA COPIAR  ▲▲▲
#
# Lo que sigue es AUTOCHEQUEO de esta herramienta, no ejemplo para el rover.
# ==========================================================================


def discrepancias_de_acopio(msg: dict[str, Any]) -> list[str]:
    """Compara el veredicto escrito acá contra el de `schema.py`.

    Son dos implementaciones independientes de la misma regla: la de arriba, que
    los equipos copian, y la del contrato, que usan el simulador y el sistema de
    visión. Que coincidan sobre datos reales, mensaje tras mensaje, vale más que
    cualquier prueba escrita a mano, porque las ejercita justo en los casos que
    de verdad ocurren —incluido el cubo parado en el borde del criterio—.

    Si alguna vez difieren, el que está mal es el DOCUMENTO además del código:
    los equipos habrían copiado una regla distinta de la que decide la ronda.
    """
    problemas = []
    depots_por_color = {d["color"]: d for d in msg["depots"]}
    for cubo in msg["cubes"]:
        destino = depots_por_color[cubo["color"]]
        adentro, falta = cubo_en_su_zona(
            cubo, destino, msg["depot_size"], msg["grid"], msg["cube_side"]
        )
        geometria = geometria_depot(
            col=destino["col"], row=destino["row"],
            length=msg["depot_size"]["length"], depth=msg["depot_size"]["depth"],
            cols=msg["grid"]["cols"], rows=msg["grid"]["rows"], cube_side=msg["cube_side"],
        )
        veredicto = cubo_en_depot(col=cubo["col"], row=cubo["row"], geometria=geometria)
        if adentro != veredicto.adentro or abs(falta - veredicto.falta_celdas) > 1e-9:
            problemas.append(
                "cubo {}: el ejemplo dice adentro={} falta={:.6f} y el contrato dice "
                "adentro={} falta={:.6f}".format(
                    cubo["color"], adentro, falta, veredicto.adentro, veredicto.falta_celdas)
            )
    return problemas


# --------------------------------------------------------------------------
# Estadísticas
# --------------------------------------------------------------------------


class Estadisticas:
    """Acumula lo que un equipo necesita mirar para saber si confía en sus datos."""

    def __init__(self) -> None:
        self.recibidos = 0
        self.invalidos = 0
        self.no_parseables = 0
        #: Veces que el ejemplo de consumo y el contrato dieron veredictos
        #: distintos sobre el mismo cubo. Tiene que ser 0 siempre.
        self.discrepancias = 0
        self.seq_anterior: int | None = None
        self.saltos = 0
        self.mensajes_perdidos = 0
        self.lat_min = float("inf")
        self.lat_max = float("-inf")
        self.lat_suma = 0.0
        self.edad_max = 0
        self.primeros_errores: list[str] = []

    def registrar(self, msg: dict[str, Any], latencia_ms: float) -> None:
        self.recibidos += 1
        self.lat_min = min(self.lat_min, latencia_ms)
        self.lat_max = max(self.lat_max, latencia_ms)
        self.lat_suma += latencia_ms

        seq = msg["seq"]
        if self.seq_anterior is not None and seq != self.seq_anterior + 1:
            # Un salto NO es un error del productor: es telemetría vieja que se
            # pisó porque este cliente no drenó a tiempo. Es la política de
            # "el último valor gana" funcionando. Que sea normal no quiere
            # decir que no haya que medirlo: muchos saltos = cliente lento.
            self.saltos += 1
            self.mensajes_perdidos += max(0, seq - self.seq_anterior - 1)
        self.seq_anterior = seq

        for lista in ("rovers", "cubes", "obstacles"):
            for obj in msg[lista]:
                self.edad_max = max(self.edad_max, obj["age_ms"])

    def registrar_error(self, texto: str) -> None:
        if len(self.primeros_errores) < 5:
            self.primeros_errores.append(texto)

    @property
    def lat_prom(self) -> float:
        return self.lat_suma / self.recibidos if self.recibidos else 0.0

    def linea_resumen(self) -> str:
        if not self.recibidos:
            return "sin mensajes todavía"
        return (
            "recibidos={} invalidos={} saltos={} (perdidos={})  "
            "latencia min/prom/max = {:.0f}/{:.0f}/{:.0f} ms  age_max={} ms".format(
                self.recibidos,
                self.invalidos,
                self.saltos,
                self.mensajes_perdidos,
                self.lat_min,
                self.lat_prom,
                self.lat_max,
                self.edad_max,
            )
        )


# --------------------------------------------------------------------------
# Programa principal
# --------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Cliente de referencia: consume, valida y mide el stream de visión."
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument(
        "--duracion", type=float, default=0.0, help="segundos a escuchar (0 = hasta Ctrl-C)"
    )
    parser.add_argument(
        "--resumen-cada", type=float, default=2.0, help="segundos entre líneas de resumen"
    )
    parser.add_argument("--silencioso", action="store_true", help="solo el resumen final")
    args = parser.parse_args(argv)

    stats = Estadisticas()
    print("Conectando a {}:{} ...".format(args.host, args.port))
    try:
        conexion = socket.create_connection((args.host, args.port), timeout=5.0)
    except OSError as exc:
        print("No se pudo conectar: {}".format(exc), file=sys.stderr)
        return 2
    conexion.settimeout(5.0)
    print("Conectado. Ctrl-C para cortar.\n")

    inicio = time.monotonic()
    ultimo_resumen = inicio
    primero = True

    try:
        for linea in leer_lineas(conexion):
            recepcion = ahora_ms()

            # Parsear y validar son dos pasos distintos, y los dos pueden
            # fallar por motivos distintos. Un mensaje malo se DESCARTA y se
            # sigue: nunca se corta el consumo por un mensaje suelto.
            try:
                msg = decodificar_ndjson(linea)
            except ValueError as exc:
                stats.no_parseables += 1
                stats.registrar_error("JSON inválido: {}".format(exc))
                continue

            error = validate_message(msg)
            if error is not None:
                stats.invalidos += 1
                stats.registrar_error(error)
                if not args.silencioso:
                    print("  [CONTRATO VIOLADO] {}".format(error))
                continue

            stats.registrar(msg, recepcion - msg["ts_ms"])

            for problema in discrepancias_de_acopio(msg):
                stats.discrepancias += 1
                stats.registrar_error("veredicto de acopio: " + problema)
                if not args.silencioso:
                    print("  [ACOPIO DISCREPA] {}".format(problema))

            if primero:
                primero = False
                if not args.silencioso:
                    print("--- primer mensaje: ejemplo de consumo -------------------------")
                    for texto in ejemplo_de_consumo(msg):
                        print("  " + texto)
                    print("---------------------------------------------------------------\n")

            ahora = time.monotonic()
            if not args.silencioso and ahora - ultimo_resumen >= args.resumen_cada:
                ultimo_resumen = ahora
                print("[{:5.1f}s] {}".format(ahora - inicio, stats.linea_resumen()))
            if args.duracion > 0 and ahora - inicio >= args.duracion:
                break
    except KeyboardInterrupt:
        pass
    except socket.timeout:
        print("Se cortó el flujo: 5 s sin recibir nada.", file=sys.stderr)
    except OSError as exc:
        print("Error de red: {}".format(exc), file=sys.stderr)
    finally:
        conexion.close()

    print("\n=== resumen final =============================================")
    print("  " + stats.linea_resumen())
    print("  no parseables: {}".format(stats.no_parseables))
    print("  veredictos de acopio que discrepan del contrato: {}".format(stats.discrepancias))
    if stats.primeros_errores:
        print("  primeros errores:")
        for texto in stats.primeros_errores:
            print("    - {}".format(texto))
    fallo = stats.invalidos > 0 or stats.no_parseables > 0 or stats.discrepancias > 0
    print("  contrato: {}".format("CON ERRORES" if fallo else "OK, sin errores"))
    print("===============================================================")
    return 1 if fallo else 0


if __name__ == "__main__":
    sys.exit(main())
