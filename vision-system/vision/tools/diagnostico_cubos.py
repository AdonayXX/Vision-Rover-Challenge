"""Diagnóstico de cubos: qué ve el detector, qué descarta y por qué.

Cómo se corre:

    python -m vision.tools.diagnostico_cubos                 # cámara, 3 segundos
    python -m vision.tools.diagnostico_cubos --indice 1
    python -m vision.tools.diagnostico_cubos --exposicion -8   # probar con menos luz
    python -m vision.tools.diagnostico_cubos --imagen diagnostico_cubos_123.png
    python -m vision.tools.diagnostico_cubos --sintetico     # para probar la herramienta

Para qué existe
---------------
Cuando un cubo no aparece en la pantalla, o aparece con la edad creciendo lejos
de donde está, desde afuera hay **una sola cara para cuatro causas distintas**:
el color no supera el umbral de croma, la mancha queda chica, el matiz no es el
de ninguno de los tres, o el contorno no encaja con el modelo del cubo. Cada una
se arregla en un lugar diferente —la luz, la exposición, un umbral, el modelo—
y elegir sin saber cuál es termina moviendo el umbral equivocado.

Esta herramienta **no corrige nada**. Mira un cuadro y contesta, con números:

1. **¿La imagen está quemada?** Qué fracción de la cancha tiene algún canal
   recortado en el máximo. Lo que el sensor recortó no lo recupera ningún
   programa: se arregla bajando la exposición o la luz.
2. **¿Cuánto color tiene el tablero?** El detector vive de que el tablero sea
   acromático. Si la luz lo tiñe, su croma sube, y esa cifra es la que dice
   cuánto se puede bajar el umbral de los cubos sin que el tablero se cuele.
3. **¿Qué cubos se detectaron**, con qué residuo y con cuánto margen de croma?
4. **¿Qué manchas se descartaron**, y en qué compuerta?
5. **Alrededor de cada mancha descartada por chica**, ¿hay color débil —una
   tapa lavada por un reflejo— o no hay nada? Es la diferencia entre un cubo
   recuperable bajando el umbral y uno que el sensor ya no registró.

Y guarda dos imágenes: el **cuadro crudo**, tal cual lo recibe el detector, y el
mismo cuadro **anotado**. El crudo es lo que hay que mandar para analizar un
problema a distancia: una foto de la pantalla no sirve, porque trae el color de
la pantalla y el del celular, no el de la cámara.

Por qué reusa el detector de `detectors/`
-----------------------------------------
No reimplementa la segmentación ni el ajuste: llama a `detectar_cubos` y le pide
que anote sus descartes. Dos implementaciones pueden divergir, y entonces el
diagnóstico dejaría de decir nada sobre el sistema real.
"""

from __future__ import annotations

import argparse
import os
import sys
import time

import cv2
import numpy as np

try:  # como paquete
    from ..configuracion import cargar_config, con_exposicion
    from ..detectors.cubos import RechazoCubo, detectar_cubos, mascara_de_color
    from ..geometry.coordenadas import (
        ErrorGeometria, construir_sistema, detectar_marcadores, pose_camara,
    )
    from ..geometry.distorsion import Rectificador, elegir_perfil
    from ..sistema import BASE_VISION, abrir_fuente
except ImportError:  # como script suelto
    from vision.configuracion import cargar_config, con_exposicion  # type: ignore[no-redef]
    from vision.detectors.cubos import (  # type: ignore[no-redef]
        RechazoCubo, detectar_cubos, mascara_de_color,
    )
    from vision.geometry.coordenadas import (  # type: ignore[no-redef]
        ErrorGeometria, construir_sistema, detectar_marcadores, pose_camara,
    )
    from vision.geometry.distorsion import Rectificador, elegir_perfil  # type: ignore[no-redef]
    from vision.sistema import BASE_VISION, abrir_fuente  # type: ignore[no-redef]


#: A partir de qué nivel un canal se da por recortado. No es 255 exacto porque
#: la compresión MJPG de la cámara ensucia el tope en un par de niveles.
NIVEL_RECORTE = 250

_MOTIVOS = {
    "area_chica": "mancha más chica que un cubo",
    "area_grande": "mancha más grande que un cubo",
    "matiz": "el matiz no es de ningún cubo",
    "duplicado": "había otra más grande del mismo color",
}


def _croma(lab: np.ndarray) -> np.ndarray:
    a = lab[:, :, 1].astype(np.float32) - 128.0
    b = lab[:, :, 2].astype(np.float32) - 128.0
    return np.hypot(a, b)


def _mascara_cancha(forma, sistema, cfg) -> np.ndarray:
    """Los píxeles que caen dentro de la cancha efectiva."""
    t = cfg.tablero
    esquinas = sistema.a_pixeles(np.array(
        [[0.0, 0.0], [t.cols, 0.0], [t.cols, t.rows], [0.0, t.rows]], dtype=np.float64))
    m = np.zeros(forma[:2], np.uint8)
    cv2.fillConvexPoly(m, esquinas.astype(np.int32), 1)
    return m


def _ventana(forma, centro_px, radio_px: float) -> tuple[slice, slice]:
    x, y = centro_px
    r = int(round(radio_px))
    return (slice(max(0, int(y) - r), min(forma[0], int(y) + r + 1)),
            slice(max(0, int(x) - r), min(forma[1], int(x) + r + 1)))


def analizar(imagen: np.ndarray, cfg, matriz_camara) -> dict | None:
    """Mide un cuadro. Devuelve `None` si no se pudo armar la geometría."""
    marcadores = detectar_marcadores(
        imagen, cfg.marcadores_esquina.nombre_diccionario,
        cfg.deteccion_marcadores.refinamiento_esquinas)
    try:
        sistema = construir_sistema(imagen, cfg, marcadores)
        pose = pose_camara(sistema, matriz_camara)
    except ErrorGeometria as exc:
        print("\n  ✗ No se pudo armar la geometría: {}".format(exc))
        print("    Sin los cuatro marcadores de esquina no hay cancha donde medir.")
        return None

    rechazos: list[RechazoCubo] = []
    cubos = detectar_cubos(imagen, sistema, cfg, pose, rechazos)
    mascara, lab = mascara_de_color(imagen, cfg)
    croma = _croma(lab)
    cancha = _mascara_cancha(imagen.shape, sistema, cfg)
    recortado = (imagen.max(axis=2) >= NIVEL_RECORTE)

    lado_celdas = cfg.elementos.cubos.lado_mm / cfg.tablero.cell_mm
    px = sistema.a_pixeles(np.array([[0.0, 0.0], [lado_celdas, 0.0]], dtype=np.float64))
    lado_px = float(np.hypot(px[1, 0] - px[0, 0], px[1, 1] - px[0, 1]))

    # El tablero: la cancha sin lo coloreado, agrandado un poco para no contar
    # el borde difuso de los cubos como si fuera tablero.
    nucleo = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (9, 9))
    tablero = (cancha == 1) & (cv2.dilate(mascara, nucleo) == 0)
    croma_tablero = croma[tablero]
    gris = cv2.cvtColor(imagen, cv2.COLOR_BGR2GRAY)

    return {
        "sistema": sistema, "cubos": cubos, "rechazos": rechazos, "mascara": mascara,
        "croma": croma, "recortado": recortado, "lado_px": lado_px, "lab": lab,
        "brillo_medio": float(gris[cancha == 1].mean()),
        "recorte_cancha": float(recortado[cancha == 1].mean()),
        "croma_tablero": (
            tuple(float(v) for v in np.percentile(croma_tablero, (50, 95, 99, 99.9)))
            if croma_tablero.size else (0.0, 0.0, 0.0, 0.0)),
    }


def informar(r: dict, cfg) -> None:
    dc = cfg.deteccion_cubos
    cell = cfg.tablero.cell_mm
    sistema, croma, recortado, lado_px = r["sistema"], r["croma"], r["recortado"], r["lado_px"]

    print("\n  1. LA IMAGEN")
    print("     brillo medio de la cancha ........ {:.0f} de 255".format(r["brillo_medio"]))
    print("     píxeles recortados en la cancha .. {:.1%}".format(r["recorte_cancha"]))
    if r["recorte_cancha"] > 0.25:
        print("     ⚠ Más de un cuarto de la cancha está en el tope del sensor. El blanco")
        print("       del tablero no debería llegar ahí: la exposición está alta para esta luz.")

    p50, p95, p99, p999 = r["croma_tablero"]
    print("\n  2. EL TABLERO (tiene que ser acromático)")
    print("     croma: mediana {:.1f} · p95 {:.1f} · p99 {:.1f} · p99,9 {:.1f}".format(
        p50, p95, p99, p999))
    print("     umbral de cubo (croma_minimo) .... {:.1f}".format(dc.croma_minimo))
    print("     margen entre el tablero (p95) y el umbral: {:.1f}".format(dc.croma_minimo - p95))
    print("     (del p99 para arriba pueden colarse tapas de cubo lavadas, que están en la")
    print("      cancha y bajo el umbral: el tinte del tablero lo dicen la mediana y el p95)")

    print("\n  3. CUBOS DETECTADOS: {}".format(len(r["cubos"])))
    if r["cubos"]:
        print("     {:<6} {:>14} {:>7} {:>8} {:>11}  {:>9} {:>9}".format(
            "color", "celda", "área", "residuo", "estado", "croma p10", "recortado"))
    for c in r["cubos"]:
        centro = sistema.a_pixeles(np.array([[c.col, c.row]], dtype=np.float64))[0]
        v = _ventana(croma.shape, centro, lado_px * 0.9)
        dentro = r["mascara"][v] > 0
        p10 = float(np.percentile(croma[v][dentro], 10)) if dentro.any() else 0.0
        print("     {:<6} ({:>5.2f},{:>5.2f}) {:>7.2f} {:>8.3f} {:>11}  {:>9.1f} {:>9.0%}".format(
            c.color, c.col, c.row, c.area_px / lado_px ** 2, c.residuo_celdas,
            "confiable" if c.confiable else "NO CONFIA.", p10, float(recortado[v].mean())))
    print("     área: en caras de cubo (admisible {}–{}) · residuo máximo {} celdas".format(
        dc.area_minima_relativa, dc.area_maxima_relativa, dc.residuo_maximo_celdas))
    faltan = sorted(set(cfg.elementos.cubos.colores) - {c.color for c in r["cubos"]})
    if faltan:
        print("     NO se detectó: {}".format(", ".join(faltan)))

    print("\n  4. MANCHAS DESCARTADAS: {}".format(len(r["rechazos"])))
    if r["rechazos"]:
        print("     {:<38} {:>11} {:>6} {:>7} {:>6}  {}".format(
            "motivo", "píxel", "área", "matiz", "croma", "se parece a"))
    for x in sorted(r["rechazos"], key=lambda x: -x.area_relativa):
        print("     {:<38} ({:>4.0f},{:>4.0f}) {:>6.2f} {:>6.0f}° {:>6.1f}  {}".format(
            _MOTIVOS.get(x.motivo, x.motivo), x.centro_px[0], x.centro_px[1],
            x.area_relativa, x.matiz_grados, x.croma, x.color or "—"))

    chicas = [x for x in r["rechazos"] if x.motivo == "area_chica" and x.color]
    if chicas:
        print("\n  5. ALREDEDOR DE LAS MANCHAS CHICAS CON COLOR DE CUBO")
        print("     ¿Hay color débil al lado —una tapa lavada— o ya no hay nada?")
        print("     {:<6} {:>11} {:>22} {:>12} {:>10}".format(
            "color", "píxel", "croma entre 8 y umbral", "sobre umbral", "recortado"))
        for x in sorted(chicas, key=lambda x: -x.area_relativa):
            v = _ventana(croma.shape, x.centro_px, lado_px * 1.2)
            cr = croma[v]
            debil = float(((cr >= 8.0) & (cr < dc.croma_minimo)).mean())
            print("     {:<6} ({:>4.0f},{:>4.0f}) {:>22.0%} {:>12.0%} {:>10.0%}".format(
                x.color, x.centro_px[0], x.centro_px[1], debil,
                float((cr >= dc.croma_minimo).mean()), float(recortado[v].mean())))
        print("     Mucho 'croma débil': el color está, por debajo del umbral. Es recuperable.")
        print("     Mucho 'recortado': el sensor lo quemó. Hay que bajar exposición o luz.")
    print("\n  Una celda = {:.0f} mm.".format(cell))


def anotar(imagen: np.ndarray, r: dict) -> np.ndarray:
    """El cuadro con la máscara de color, los cubos y los descartes dibujados."""
    lienzo = imagen.copy()
    contornos, _ = cv2.findContours(r["mascara"], cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    cv2.drawContours(lienzo, contornos, -1, (255, 0, 255), 1, cv2.LINE_AA)
    lienzo[r["recortado"]] = (0.5 * lienzo[r["recortado"]] + (0, 128, 128)).astype(np.uint8)
    for c in r["cubos"]:
        p = r["sistema"].a_pixeles(np.array([[c.col, c.row]], dtype=np.float64))[0]
        color = (0, 220, 0) if c.confiable else (0, 160, 255)
        cv2.drawMarker(lienzo, (int(p[0]), int(p[1])), color, cv2.MARKER_CROSS, 16, 2)
        cv2.putText(lienzo, "{} res={:.2f}".format(c.color, c.residuo_celdas),
                    (int(p[0]) + 10, int(p[1]) - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 1,
                    cv2.LINE_AA)
    for x in r["rechazos"]:
        p = (int(x.centro_px[0]), int(x.centro_px[1]))
        cv2.drawMarker(lienzo, p, (0, 0, 255), cv2.MARKER_TILTED_CROSS, 12, 2)
        cv2.putText(lienzo, "{} {:.2f}".format(x.motivo, x.area_relativa), (p[0] + 8, p[1] + 14),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 0, 255), 1, cv2.LINE_AA)
    return lienzo


def _cuadro_de_camara(cfg, args):
    """Abre la fuente igual que el sistema y devuelve `(imagen, matriz de cámara)`."""
    fuente, descripcion, _ = abrir_fuente(cfg, args)
    matriz = getattr(fuente, "matriz_camara", None)
    if matriz is None:  # fuente sintética
        matriz = fuente.verdad.camara.matriz
    print("  Entrada: {} · mirando {:.0f} s para que la imagen se asiente".format(
        descripcion, args.segundos))
    ultimo = None
    fin = time.monotonic() + args.segundos
    try:
        while time.monotonic() < fin or ultimo is None:
            cuadro = fuente.leer()
            if cuadro is None:
                if time.monotonic() > fin + 10.0:
                    break
                time.sleep(0.005)
                continue
            ultimo = cuadro.imagen
    finally:
        fuente.cerrar()
    return ultimo, matriz


def _cuadro_de_archivo(cfg, args):
    """Lee un cuadro crudo guardado antes. Ya viene sin distorsión."""
    imagen = cv2.imread(args.imagen)
    if imagen is None:
        return None, None
    alto, ancho = imagen.shape[:2]
    perfil = elegir_perfil(cfg.calibracion, BASE_VISION, ancho, alto, nombre=args.camara)
    rectificador = Rectificador(perfil, alpha=cfg.calibracion.alpha, tamano=(ancho, alto))
    print("  Entrada: archivo {} ({}x{}) · perfil {}".format(
        args.imagen, ancho, alto, perfil.camara))
    return imagen, rectificador.matriz_nueva


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Dice qué cubos ve el detector, cuáles descarta y por qué.")
    parser.add_argument("--config", default=None)
    parser.add_argument("--indice", type=int, default=None, help="índice de cámara")
    parser.add_argument("--camara", default=None, help="nombre del perfil de calibración")
    parser.add_argument("--sintetico", action="store_true",
                        help="correr sobre una imagen generada (para probar la herramienta)")
    parser.add_argument("--imagen", default=None,
                        help="analizar un cuadro crudo guardado, en vez de abrir la cámara")
    parser.add_argument("--segundos", type=float, default=3.0,
                        help="cuánto mirar antes de tomar el cuadro")
    parser.add_argument("--exposicion", type=float, default=None,
                        help="exposición fija a probar, en lugar de la del archivo "
                             "(más negativo = menos luz)")
    parser.add_argument("--sin-guardar", action="store_true",
                        help="no escribir las imágenes de diagnóstico")
    args = parser.parse_args(argv)
    cfg = cargar_config(args.config) if args.config else cargar_config()
    if args.exposicion is not None:
        cfg = con_exposicion(cfg, args.exposicion)

    print("=" * 78)
    print("DIAGNÓSTICO DE CUBOS — qué ve el detector, qué descarta y por qué")
    print("=" * 78)

    if args.imagen:
        imagen, matriz = _cuadro_de_archivo(cfg, args)
    else:
        imagen, matriz = _cuadro_de_camara(cfg, args)
    if imagen is None:
        print("  ✗ No se consiguió ninguna imagen.")
        return 1

    # El crudo se guarda ANTES de analizar: si la geometría falla, el cuadro que
    # la hizo fallar es justamente el que hace falta mirar.
    base = "diagnostico_cubos_{}".format(int(time.time()))
    if not args.sin_guardar and not args.imagen:
        cv2.imwrite(base + ".png", imagen)
        print("  cuadro crudo guardado: {}".format(os.path.abspath(base + ".png")))

    r = analizar(imagen, cfg, matriz)
    if r is None:
        return 1
    informar(r, cfg)
    if not args.sin_guardar:
        cv2.imwrite(base + "_anotado.png", anotar(imagen, r))
        print("  cuadro anotado guardado: {}".format(os.path.abspath(base + "_anotado.png")))
        print("  (magenta: lo que el detector considera coloreado · tinte amarillo: recortado)")
    print("=" * 78)
    return 0


if __name__ == "__main__":
    sys.exit(main())
