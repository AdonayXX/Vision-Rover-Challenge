"""Mide los falsos positivos del detector de ArUco sobre la cancha real.

Cómo se corre:

    python -m vision.tools.diagnostico_falsos_positivos
    python -m vision.tools.diagnostico_falsos_positivos --minutos 5
    python -m vision.tools.diagnostico_falsos_positivos --indice 1

⚠️ **La cancha tiene que estar despejada**: los cuatro marcadores de esquina y,
si se quiere medir el caso de la colisión, el rover. Nada más: sin cubos, sin
manos. Todo marcador que aparezca que no sea una esquina ni el marcador legítimo
de un rover es, por definición, un falso positivo.

Primero medir, después corregir
-------------------------------
El detector de ArUco encuentra marcadores donde no los hay. Es esperable: el
tablero es una cuadrícula fina de blanco y negro, que es exactamente la clase de
textura con la que se construye un código ArUco, y `DICT_4X4_50` tiene poca
distancia entre códigos.

Esta herramienta **no corrige nada**. Mide, para que las correcciones se elijan
con números en vez de con intuición:

- **qué IDs** aparecen, y si alguno cae en los IDs declarados de rover, que es
  el caso grave: un fantasma con el ID de un rover **no se suma**, **colisiona**;
- **cuántas veces colisiona de verdad**: cuántos cuadros traen el mismo ID dos
  veces, que es el evento que pisa a un marcador real;
- **de qué tamaño** son, medidos en milímetros sobre el plano del tablero con la
  homografía;
- **cuán cuadrados** son. En el espacio de celdas un marcador real vuelve a ser
  un cuadrado —la homografía deshace la perspectiva— así que sus cuatro lados y
  sus dos diagonales tienen que coincidir entre sí;
- **cuánto duran**. Un falso positivo suele vivir uno o dos cuadros y saltar a
  otro lado; un marcador de verdad está ahí cuadro tras cuadro;
- **dónde caen**. Si un ID se concentra en una o dos zonas de la cancha, no es
  azar: es un rasgo físico de la escena —un reflejo, una sombra, un borde— y se
  puede ir a taparlo.

Se mide sobre la salida CRUDA del detector
------------------------------------------
`detectar_marcadores` arma un diccionario por ID, y un diccionario **colapsa los
duplicados antes de que nadie pueda contarlos**: si dos marcadores dicen ser el
10, al armarlo ya no hay forma de saber que hubo dos. Por eso acá se parte de
`detectar_marcadores_crudo`, que devuelve todas las detecciones tal cual. La
primera versión de esta herramienta medía después del colapso, y por eso sus
números eran una cota inferior.

Los marcadores legítimos son el control
---------------------------------------
Los cuatro de esquina y el del rover se miden también, y con la misma vara: sin
saber cuánto se desvía un marcador legítimo no hay forma de elegir una
tolerancia para rechazar a los falsos. El del rover está a 80 mm de altura, así
que el paralaje lo infla `H/(H−h)`; la herramienta calcula ese factor con la
pose de cámara —deducida de los cuatro marcadores, sin declarar nada— y lo
informa.
"""

from __future__ import annotations

import argparse
import datetime
import json
import math
import os
import sys
import time

import numpy as np

try:  # como paquete
    from ..configuracion import cargar_config
    from ..geometry.coordenadas import (
        AnclajeCancha, ErrorDuplicado, ErrorGeometria, centro_de,
        detectar_marcadores_crudo, pose_camara, resolver_duplicados,
    )
    from ..sistema import abrir_fuente
except ImportError:  # como script suelto
    from vision.configuracion import cargar_config  # type: ignore[no-redef]
    from vision.geometry.coordenadas import (  # type: ignore[no-redef]
        AnclajeCancha, ErrorDuplicado, ErrorGeometria, centro_de,
        detectar_marcadores_crudo, pose_camara, resolver_duplicados,
    )
    from vision.sistema import abrir_fuente  # type: ignore[no-redef]


#: Banda dentro de la cual una detección con ID de rover se considera el
#: marcador legítimo y no un fantasma, SOLO para separar las filas del informe.
#: No es un umbral del sistema: acá nada se rechaza, todo se cuenta.
BANDA_REPORTE = 0.20

#: En cuántas zonas por lado se divide la cancha para el mapa de calor.
ZONAS_POR_LADO = 10


# --------------------------------------------------------------------------
# La medición de un marcador
# --------------------------------------------------------------------------


def medir(esquinas_px: np.ndarray, sistema) -> dict:
    """Mide un marcador detectado **sobre el plano del tablero**, no en píxeles.

    Los píxeles no sirven para juzgar tamaños: un marcador en un borde de la
    imagen se ve más chico que el mismo marcador en el centro, y con la cámara
    inclinada la diferencia crece. La homografía deshace exactamente eso, así
    que en celdas un cuadrado vuelve a ser un cuadrado del tamaño que es.
    """
    celdas = sistema.a_celdas(np.asarray(esquinas_px, dtype=np.float64).reshape(4, 2))
    cell_mm = sistema.cell_mm

    lados = [float(np.linalg.norm(celdas[(i + 1) % 4] - celdas[i])) * cell_mm for i in range(4)]
    diagonales = [
        float(np.linalg.norm(celdas[2] - celdas[0])) * cell_mm,
        float(np.linalg.norm(celdas[3] - celdas[1])) * cell_mm,
    ]
    lado_medio = sum(lados) / 4.0
    diagonal_media = sum(diagonales) / 2.0

    # Tres formas de no ser un cuadrado, y se toma la peor:
    #   1. los cuatro lados no miden lo mismo (es un rectángulo o un rombo);
    #   2. las dos diagonales no miden lo mismo (está torcido);
    #   3. la diagonal no es el lado por raíz de dos (no tiene ángulos rectos).
    disp_lados = (max(lados) - min(lados)) / lado_medio * 100.0 if lado_medio else float("inf")
    disp_diag = (abs(diagonales[0] - diagonales[1]) / diagonal_media * 100.0
                 if diagonal_media else float("inf"))
    relacion = (abs(diagonal_media / (lado_medio * math.sqrt(2.0)) - 1.0) * 100.0
                if lado_medio else float("inf"))

    col, row = centro_de(celdas)
    return {
        "lado_mm": lado_medio,
        "cuadratura_pct": max(disp_lados, disp_diag, relacion),
        "col": col,
        "row": row,
    }


# --------------------------------------------------------------------------
# Acumulación
# --------------------------------------------------------------------------


class Registro:
    """Lo que se vio de un ID a lo largo de la corrida.

    La **racha** es lo que separa un fantasma de un marcador: se cuenta cuántos
    cuadros CONSECUTIVOS apareció, y se guarda la más larga. Un marcador pegado
    al tablero tiene una racha tan larga como la corrida; un recorte afortunado
    de la cuadrícula dura uno o dos cuadros y desaparece.
    """

    def __init__(self, id_aruco: int):
        self.id = id_aruco
        self.apariciones = 0
        self.eventos = 0            # rachas distintas: cuántas VECES apareció
        self.racha = 0
        self.mejor_racha = 0
        self._ultimo_cuadro = -10
        self.lados_mm: list[float] = []
        self.cuadratura: list[float] = []
        self.celdas: list[tuple[float, float]] = []

    def registrar(self, cuadro: int, medida: dict) -> None:
        if cuadro == self._ultimo_cuadro + 1:
            self.racha += 1
        elif cuadro != self._ultimo_cuadro:
            self.racha = 1
            self.eventos += 1
        self._ultimo_cuadro = cuadro
        self.mejor_racha = max(self.mejor_racha, self.racha)
        self.apariciones += 1
        self.lados_mm.append(medida["lado_mm"])
        self.cuadratura.append(medida["cuadratura_pct"])
        self.celdas.append((medida["col"], medida["row"]))


def _resumen(valores: list[float]) -> str:
    if not valores:
        return "—"
    v = np.array(valores, dtype=np.float64)
    return "{:.1f} / {:.1f} / {:.1f}".format(v.min(), float(np.median(v)), v.max())


def _tabla(titulo: str, registros: dict[int, Registro], cuadros: int) -> None:
    if not registros:
        return
    print("\n  {}".format(titulo))
    print("  {:>4} {:>7} {:>8} {:>9} {:>24} {:>22}".format(
        "ID", "aparic", "rachas", "racha máx", "lado mm (mín/med/máx)", "cuadratura % (m/m/M)"))
    print("  " + "-" * 80)
    for id_aruco in sorted(registros, key=lambda i: -registros[i].apariciones):
        r = registros[id_aruco]
        print("  {:>4} {:>7} {:>8} {:>9} {:>24} {:>22}".format(
            r.id, r.apariciones, r.eventos, r.mejor_racha,
            _resumen(r.lados_mm), _resumen(r.cuadratura)))


# --------------------------------------------------------------------------
# Análisis espacial
# --------------------------------------------------------------------------


def _zona(col: float, row: float, cols: int, rows: int) -> tuple[int, int]:
    """En qué zona del mapa cae una celda. Las de afuera se pegan al borde."""
    zc = min(ZONAS_POR_LADO - 1, max(0, int(col / cols * ZONAS_POR_LADO)))
    zr = min(ZONAS_POR_LADO - 1, max(0, int(row / rows * ZONAS_POR_LADO)))
    return zc, zr


def analisis_espacial(falsos: dict[int, Registro], cols: int, rows: int) -> None:
    """Dónde caen los fantasmas sobre la cancha.

    Responde una pregunta que los promedios esconden: si un ID se lleva la mitad
    de las detecciones, ¿es azar repartido por todo el tablero, o hay **un lugar**
    que las produce? Ya se descartó que sea el código —los IDs que aparecen no
    están más cerca del ajedrez que los que no—, así que si hay concentración,
    la causa es física y se puede ir a taparla.
    """
    print("\n  DÓNDE CAEN — mapa de la cancha, {} x {} zonas".format(
        ZONAS_POR_LADO, ZONAS_POR_LADO))
    mapa = np.zeros((ZONAS_POR_LADO, ZONAS_POR_LADO), dtype=int)
    for r in falsos.values():
        for col, row in r.celdas:
            zc, zr = _zona(col, row, cols, rows)
            mapa[zr, zc] += 1

    print("       col ->")
    for zr in range(ZONAS_POR_LADO):
        fila = "".join(
            "." if n == 0 else (str(n) if n < 10 else "#") for n in mapa[zr]
        )
        print("   {:>4} |{}|".format(int(zr * rows / ZONAS_POR_LADO), fila))
    print("        (. = ninguno · 1-9 = cuántos · # = diez o más)")

    print("\n  CONCENTRACIÓN por ID: cuánto de cada ID cae en su zona más cargada")
    print("  {:>4} {:>8} {:>14} {:>26}".format(
        "ID", "aparic", "en una zona", "zona (col, row) en celdas"))
    print("  " + "-" * 60)
    for id_aruco in sorted(falsos, key=lambda i: -falsos[i].apariciones):
        r = falsos[id_aruco]
        cuenta: dict[tuple[int, int], int] = {}
        for col, row in r.celdas:
            z = _zona(col, row, cols, rows)
            cuenta[z] = cuenta.get(z, 0) + 1
        zona, n = max(cuenta.items(), key=lambda kv: kv[1])
        print("  {:>4} {:>8} {:>13.0f}% {:>26}".format(
            r.id, r.apariciones, 100.0 * n / r.apariciones,
            "({:.0f}-{:.0f}, {:.0f}-{:.0f})".format(
                zona[0] * cols / ZONAS_POR_LADO, (zona[0] + 1) * cols / ZONAS_POR_LADO,
                zona[1] * rows / ZONAS_POR_LADO, (zona[1] + 1) * rows / ZONAS_POR_LADO)))


# --------------------------------------------------------------------------
# Programa
# --------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Mide los falsos positivos del detector de ArUco sobre la cancha real."
    )
    parser.add_argument("--config", default=None)
    parser.add_argument("--minutos", type=float, default=2.0, help="cuánto medir")
    parser.add_argument("--indice", type=int, default=None, help="índice de cámara")
    parser.add_argument("--camara", default=None, help="nombre del perfil de calibración")
    parser.add_argument("--sintetico", action="store_true",
                        help="correr sobre imágenes generadas (para probar la herramienta)")
    parser.add_argument("--guardar", action="store_true",
                        help="guardar TODAS las detecciones crudas en vision/mediciones/")
    parser.add_argument("--nota", default="",
                        help="qué escena se midió, para que la sesión guardada se entienda sola")
    args = parser.parse_args(argv)

    cfg = cargar_config(args.config) if args.config else cargar_config()

    print("=" * 78)
    print("DIAGNÓSTICO DE FALSOS POSITIVOS DEL DETECTOR DE ArUco")
    print("=" * 78)
    print("  La cancha tiene que estar despejada: los cuatro marcadores de esquina y,")
    print("  si se quiere medir la colisión, el rover. Nada más.")
    print("  Diccionario: {}  ·  midiendo {:.0f} s".format(
        cfg.marcadores_esquina.nombre_diccionario, args.minutos * 60.0))

    fuente, descripcion = abrir_fuente(cfg, args)
    matriz = getattr(fuente, "matriz_camara", None)
    if matriz is None:  # fuente sintética
        matriz = fuente.verdad.camara.matriz
    print("  Entrada: {}".format(descripcion))
    print("=" * 78)

    ids_esquina = cfg.marcadores_esquina.ids_esperados
    ids_rover = cfg.deteccion_rovers.ids_rover
    anclaje = AnclajeCancha(cfg)

    control: dict[int, Registro] = {}
    rovers: dict[int, Registro] = {}
    falsos: dict[int, Registro] = {}
    duplicados: dict[int, int] = {}
    #: Cada detección, tal cual se midió. Se guarda aparte de los resúmenes
    #: porque un promedio no se puede volver a analizar: si mañana aparece otra
    #: pregunta —adentro o afuera de la cancha, agrupada o repartida— hay que
    #: poder responderla sobre los mismos datos sin volver a montar la escena.
    crudos_medidos: list[dict] = []
    cuadros = sin_geometria = cuadros_con_duplicado = ambiguos = 0
    factores = []

    inicio = time.monotonic()
    fin = inicio + args.minutos * 60.0
    proximo_aviso = inicio + 15.0

    try:
        while time.monotonic() < fin:
            cuadro = fuente.leer()
            if cuadro is None:
                time.sleep(0.005)
                continue
            cuadros += 1

            # CRUDO: sin colapsar por ID. Lo que se pierde al armar el
            # diccionario es justamente el caso peligroso.
            crudos = detectar_marcadores_crudo(
                cuadro.imagen, cfg.marcadores_esquina.nombre_diccionario,
                cfg.deteccion_marcadores.refinamiento_esquinas)

            repetidos = {}
            for id_aruco, _ in crudos:
                repetidos[id_aruco] = repetidos.get(id_aruco, 0) + 1
            hubo_duplicado = False
            for id_aruco, veces in repetidos.items():
                if veces > 1:
                    duplicados[id_aruco] = duplicados.get(id_aruco, 0) + 1
                    hubo_duplicado = True
            cuadros_con_duplicado += int(hubo_duplicado)

            try:
                marcadores, _ = resolver_duplicados(crudos, cfg, anclaje.sistema)
            except ErrorDuplicado:
                ambiguos += 1
                marcadores = {}
            try:
                sistema = anclaje.actualizar(cuadro.imagen, marcadores)
            except ErrorGeometria:
                # Sin homografía no hay plano del tablero sobre el cual medir.
                sin_geometria += 1
                continue

            if anclaje.esquinas_visibles == 4:
                try:
                    pose = pose_camara(sistema, matriz)
                    factores.append(pose.factor_paralaje(
                        cfg.paralaje.altura_marcador_rover_mm))
                except ErrorGeometria:
                    pass
            factor = float(np.median(factores)) if factores else 1.0
            lado_rover = cfg.elementos.marcador_rover.lado_mm * factor

            for id_aruco, esquinas in crudos:
                medida = medir(esquinas, sistema)
                if id_aruco in ids_esquina:
                    destino = control
                elif (id_aruco in ids_rover
                      and abs(medida["lado_mm"] - lado_rover) <= BANDA_REPORTE * lado_rover):
                    destino = rovers
                else:
                    destino = falsos
                destino.setdefault(id_aruco, Registro(id_aruco)).registrar(cuadros, medida)
                crudos_medidos.append({
                    "cuadro": cuadros,
                    "id": int(id_aruco),
                    "grupo": ("esquina" if destino is control else
                              "rover" if destino is rovers else "falso"),
                    "col": round(medida["col"], 4),
                    "row": round(medida["row"], 4),
                    "lado_mm": round(medida["lado_mm"], 3),
                    "cuadratura_pct": round(medida["cuadratura_pct"], 3),
                })

            if time.monotonic() >= proximo_aviso:
                proximo_aviso += 15.0
                print("  [{:>4.0f} s] cuadros={} · falsos={} en {} IDs · cuadros con ID "
                      "duplicado={}".format(
                          time.monotonic() - inicio, cuadros,
                          sum(r.apariciones for r in falsos.values()), len(falsos),
                          cuadros_con_duplicado), flush=True)
    except KeyboardInterrupt:
        print("\n  (interrumpido: se informa lo medido hasta acá)")
    finally:
        fuente.cerrar()

    duracion = time.monotonic() - inicio
    informe(cfg, duracion, cuadros, sin_geometria, control, rovers,
            falsos, duplicados, cuadros_con_duplicado, ambiguos, ids_rover, factores)
    if args.guardar:
        guardar_sesion(cfg, args, duracion, cuadros, sin_geometria, factores, crudos_medidos)
    return 0


def _distribucion(valores) -> dict:
    """Mínimo, mediana y máximo: con eso alcanza para una vara."""
    v = np.asarray(valores, dtype=float)
    return {"min": round(float(v.min()), 3),
            "mediana": round(float(np.median(v)), 3),
            "max": round(float(v.max()), 3)}


def guardar_sesion(cfg, args, duracion, cuadros, sin_geometria, factores, crudos) -> None:
    """Guarda la sesión cruda, no el resumen.

    Un promedio no se puede volver a analizar. Si mañana hay otra pregunta
    —¿caían dentro de la cancha?, ¿se agrupaban?, ¿cambió el tamaño con la
    posición?— hay que poder contestarla sobre los mismos datos, sin volver a
    montar la escena ni a esperar a que el detector tenga ganas de equivocarse.

    Va en `vision/mediciones/`, con las otras: es el resultado de medir un
    aparato concreto en una cancha concreta, no configuración del sistema.

    Qué se guarda entero y qué no
    -----------------------------
    Las detecciones de **fantasmas** y del **marcador del rover** van completas:
    ahí vive toda pregunta que se le haya hecho o se le pueda hacer a estos
    datos. Las de los cuatro marcadores de **esquina** van resumidas por ID —n,
    lado y cuadratura—, porque son decenas de miles de filas que repiten cuadro
    tras cuadro casi lo mismo y se usan como **vara**, no como dato: de una vara
    alcanza con su distribución. Medido sobre las dos sesiones que ya existían,
    eso baja el archivo de **3,7 MB a 437 KB** sin perder una sola respuesta, en
    una carpeta donde el resto de las mediciones pesa 3 o 4 KB.
    """
    base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    carpeta = os.path.join(base, cfg.precision.carpeta_mediciones)
    os.makedirs(carpeta, exist_ok=True)
    sello = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    ruta = os.path.join(carpeta, "falsos_positivos_{}.json".format(sello))

    enteras = [d for d in crudos if d["grupo"] != "esquina"]
    resumen = {}
    for id_esquina in sorted({d["id"] for d in crudos if d["grupo"] == "esquina"}):
        filas = [d for d in crudos if d["grupo"] == "esquina" and d["id"] == id_esquina]
        resumen[str(id_esquina)] = {
            "n": len(filas),
            "lado_mm": _distribucion([d["lado_mm"] for d in filas]),
            "cuadratura_pct": _distribucion([d["cuadratura_pct"] for d in filas]),
        }

    datos = {
        "cuando": datetime.datetime.now().isoformat(timespec="seconds"),
        "nota": args.nota,
        "sintetico": bool(args.sintetico),
        "duracion_s": round(duracion, 1),
        "cuadros": cuadros,
        "cuadros_sin_geometria": sin_geometria,
        "diccionario": cfg.marcadores_esquina.nombre_diccionario,
        "cancha": {"cols": cfg.tablero.cols, "rows": cfg.tablero.rows,
                   "cell_mm": cfg.tablero.cell_mm},
        "esperado_mm": {
            "esquina": cfg.marcadores_esquina.lado_mm,
            "rover_nominal": cfg.elementos.marcador_rover.lado_mm,
            "factor_paralaje_mediano": round(float(np.median(factores)), 4) if factores else None,
        },
        "detecciones": enteras,
        "esquinas_resumen": resumen,
        "_QUE_SE_GUARDA_Y_QUE_NO": (
            "Las detecciones de FANTASMAS y del marcador del ROVER están completas. Las "
            "de los cuatro marcadores de ESQUINA están resumidas por ID —n, lado y "
            "cuadratura— porque se usan como VARA y no como dato: repiten casi lo mismo "
            "cuadro tras cuadro, y de una vara alcanza con su distribución."),
    }
    with open(ruta, "w", encoding="utf-8") as f:
        json.dump(datos, f, indent=1, ensure_ascii=False)
    print("\n  Sesión cruda guardada en: {}".format(ruta))
    print("  {} detecciones enteras (fantasmas y rover), con su cuadro, ID, grupo, celda, "
          "lado y cuadratura.".format(len(enteras)))
    if resumen:
        print("  {} detecciones de marcadores de esquina, resumidas por ID: se usan como "
              "vara, no como dato.".format(len(crudos) - len(enteras)))


def informe(cfg, duracion, cuadros, sin_geometria, control, rovers, falsos,
            duplicados, cuadros_con_duplicado, ambiguos, ids_rover, factores) -> None:
    minutos = duracion / 60.0 if duracion > 0 else 1.0
    apariciones = sum(r.apariciones for r in falsos.values())
    eventos = sum(r.eventos for r in falsos.values())

    print("\n" + "=" * 78)
    print("LO QUE SE MIDIÓ")
    print("=" * 78)
    print("  {:.0f} s · {} cuadros procesados · {:.1f} por segundo".format(
        duracion, cuadros, cuadros / duracion if duracion else 0.0))
    if sin_geometria:
        print("  {} cuadros sin geometría (no se pudo medir nada en ellos)".format(sin_geometria))

    print("\n  CONTROL — marcadores LEGÍTIMOS, medidos con la misma vara")
    print("  Es la referencia: así de bien se porta un marcador de verdad.")
    _tabla("esquinas (esperado: {:.0f} mm)".format(cfg.marcadores_esquina.lado_mm),
           control, cuadros)
    if factores:
        f = float(np.median(factores))
        esperado = cfg.elementos.marcador_rover.lado_mm * f
        _tabla("rover (esperado: {:.0f} mm x {:.4f} de paralaje = {:.1f} mm)".format(
            cfg.elementos.marcador_rover.lado_mm, f, esperado), rovers, cuadros)
        if not rovers:
            print("\n  (no se vio ningún marcador de rover legítimo en esta corrida)")

    print("\n" + "=" * 78)
    print("IDS DUPLICADOS EN UN MISMO CUADRO — el caso que pisa un marcador real")
    print("=" * 78)
    if not duplicados:
        print("  Ninguno en {:.0f} s.".format(duracion))
    else:
        print("  {} cuadros con al menos un ID duplicado: {:.1f} % de los cuadros, "
              "{:.1f} por minuto".format(
                  cuadros_con_duplicado, 100.0 * cuadros_con_duplicado / cuadros if cuadros else 0,
                  cuadros_con_duplicado / minutos))
        print("  {} cuadros se descartaron por no poder decidir cuál era el bueno".format(ambiguos))
        print("  {:>4} {:>12} {:>14}  {}".format("ID", "cuadros", "por minuto", "qué es ese ID"))
        print("  " + "-" * 62)
        for id_aruco in sorted(duplicados, key=lambda i: -duplicados[i]):
            que = ("MARCADOR DE ESQUINA: pisa la geometría"
                   if id_aruco in cfg.marcadores_esquina.ids_esperados else
                   "ID DE ROVER: pisa la posición del robot" if id_aruco in ids_rover else
                   "no declarado: no lo usa nadie")
            print("  {:>4} {:>12} {:>14.1f}  {}".format(
                id_aruco, duplicados[id_aruco], duplicados[id_aruco] / minutos, que))

    print("\n" + "=" * 78)
    print("FALSOS POSITIVOS")
    print("=" * 78)
    if not falsos:
        print("  Ninguno en {:.0f} s. El detector no inventó un solo marcador.".format(duracion))
        return

    print("  {} detecciones falsas en {:.1f} min  ->  {:.1f} por minuto".format(
        apariciones, minutos, apariciones / minutos))
    print("  {} apariciones distintas (rachas)   ->  {:.1f} por minuto".format(
        eventos, eventos / minutos))
    print("  {} IDs distintos: {}".format(len(falsos), sorted(falsos)))

    chocan = sorted(set(falsos) & set(ids_rover))
    if chocan:
        print("\n  ⚠️  Los IDs {} son IDs DECLARADOS DE ROVER. Un fantasma con ese ID no".format(
            chocan))
        print("      se suma: COLISIONA con el marcador real, y antes lo pisaba en silencio.")

    _tabla("por ID, ordenados por cuántas veces aparecieron", falsos, cuadros)

    todos_lados = [v for r in falsos.values() for v in r.lados_mm]
    todas_cuad = [v for r in falsos.values() for v in r.cuadratura]
    rachas = [r.mejor_racha for r in falsos.values()]
    lados = np.array(todos_lados, dtype=np.float64)

    print("\n  DISTRIBUCIÓN DE TAMAÑOS de los falsos positivos")
    print("  mín {:.1f} · p25 {:.1f} · mediana {:.1f} · p75 {:.1f} · máx {:.1f} mm".format(
        lados.min(), float(np.percentile(lados, 25)), float(np.median(lados)),
        float(np.percentile(lados, 75)), lados.max()))
    factor = float(np.median(factores)) if factores else 1.0
    esperados = (
        ("esquina", cfg.marcadores_esquina.lado_mm),
        ("rover con paralaje", cfg.elementos.marcador_rover.lado_mm * factor),
    )
    for nombre, lado in esperados:
        cerca = int(np.sum(np.abs(lados - lado) <= BANDA_REPORTE * lado))
        print("  a menos de {:.0f} % del lado de un marcador de {} ({:.1f} mm): {} de {}".format(
            BANDA_REPORTE * 100, nombre, lado, cerca, len(lados)))

    # ¿Caen DENTRO de la cancha o en el borde muerto? Importa porque un filtro
    # por posición —rechazar lo que caiga fuera de la cancha efectiva— mata sin
    # ningún falso negativo posible a todo lo que esté afuera: ahí no puede
    # haber un marcador legítimo, por definición.
    cols, rows = cfg.tablero.cols, cfg.tablero.rows
    adentro = fuera = 0
    fuera_por_id: dict[int, int] = {}
    for r in falsos.values():
        for col, row in r.celdas:
            if 0.0 <= col <= cols and 0.0 <= row <= rows:
                adentro += 1
            else:
                fuera += 1
                fuera_por_id[r.id] = fuera_por_id.get(r.id, 0) + 1
    print("\n  DENTRO O FUERA de la cancha de {}x{} celdas".format(cols, rows))
    print("  dentro: {} de {} ({:.0f} %)   ·   fuera, en el borde muerto: {} ({:.0f} %)".format(
        adentro, adentro + fuera, 100.0 * adentro / max(1, adentro + fuera),
        fuera, 100.0 * fuera / max(1, adentro + fuera)))
    if fuera_por_id:
        print("  los de afuera, por ID: {}".format(
            ", ".join("{}: {}".format(i, n) for i, n in sorted(fuera_por_id.items()))))

    print("\n  CUADRATURA de los falsos positivos: mín/mediana/máx = {} %".format(
        _resumen(todas_cuad)))
    print("  PERSISTENCIA: racha más larga por ID: mín {} · mediana {:.0f} · máx {} cuadros".format(
        min(rachas), float(np.median(rachas)), max(rachas)))

    analisis_espacial(falsos, cfg.tablero.cols, cfg.tablero.rows)

    print("\n" + "=" * 78)
    print("Esta herramienta NO corrige nada: los números de arriba son para decidir")
    print("con qué criterio rechazar, y con qué tolerancia, sin adivinar umbrales.")
    print("=" * 78)


if __name__ == "__main__":
    sys.exit(main())
