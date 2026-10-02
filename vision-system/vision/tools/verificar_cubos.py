"""Verifica la detección de cubos contra la verdad del generador sintético.

Cómo se corre:

    python -m vision.tools.verificar_cubos
    python -m vision.tools.verificar_cubos --salida /tmp/cubos.png --anotar

Por qué la prueba está armada así
---------------------------------
El generador dibuja cada cubo como la caja que es —base en el piso, tapa a 60 mm
corrida hacia afuera, caras laterales— **sabiendo exactamente** dónde apoya. Esa
verdad es lo que permite decir "está bien" en vez de "no explotó".

El escenario que decide es el del **cubo empujado**. En el juego, los rovers
llevan los cubos a las zonas de acopio, que están en las esquinas: empujan hacia
**afuera**, con su chasis del lado del centro de la cancha. Y ahí el chasis le
esconde al cubo justo la arista de la base, que es la parte que uno querría usar
para ubicarlo. No es un caso raro: es la maniobra más frecuente de la ronda.

Por eso cada escenario reporta el ajuste **al lado del centroide ingenuo**: para
que la diferencia entre los dos métodos se vea, en vez de haber que creerla.
"""

from __future__ import annotations

import argparse
import math
import sys

import cv2
import numpy as np

try:  # como paquete
    from ..configuracion import CuboDemo, Perspectiva, RoverDemo, cargar_config, con_matices
    from ..detectors.cubos import (
        asignar_matices, cuadrado, detectar_cubos, mascara_de_color, medir_matices,
    )
    from ..geometry.coordenadas import (
        ErrorGeometria, construir_sistema, detectar_marcadores, pose_camara,
    )
    from ..sources.generador_sintetico import generar
except ImportError:  # como script suelto
    from vision.configuracion import (  # type: ignore[no-redef]
        CuboDemo, Perspectiva, RoverDemo, cargar_config, con_matices,
    )
    from vision.detectors.cubos import (  # type: ignore[no-redef]
        asignar_matices, cuadrado, detectar_cubos, mascara_de_color, medir_matices,
    )
    from vision.geometry.coordenadas import (  # type: ignore[no-redef]
        ErrorGeometria, construir_sistema, detectar_marcadores, pose_camara,
    )
    from vision.sources.generador_sintetico import generar  # type: ignore[no-redef]


# --------------------------------------------------------------------------
# Escenarios
# --------------------------------------------------------------------------


def escenarios(cfg):
    """Los casos a probar: `(nombre, cubos, rovers)`."""
    tres = cfg.cubos_demo
    verde = CuboDemo(color="green", col=34.0, row=9.0, theta=15.0)

    # Cubos en las cuatro esquinas y el centro: el paralaje y la perspectiva
    # pegan distinto según dónde caiga el cubo, y en el centro casi no pegan.
    repartidos = (
        CuboDemo(color="red", col=8.0, row=8.0, theta=0.0),
        CuboDemo(color="green", col=35.0, row=8.0, theta=30.0),
        CuboDemo(color="blue", col=8.0, row=35.0, theta=60.0),
    )
    # Rotaciones distintas del mismo cubo: la silueta cambia de forma y el
    # detector tiene que dar igual, porque el contrato no publica rotación.
    rotados = tuple(
        CuboDemo(color=c, col=col, row=21.5, theta=t)
        for c, col, t in (("red", 10.0, 0.0), ("green", 21.5, 22.5), ("blue", 33.0, 45.0))
    )
    return [
        ("los tres cubos de la configuración", tres, ()),
        ("cubos repartidos por la cancha", repartidos, ()),
        ("rotaciones de 0°, 22,5° y 45°", rotados, ()),
        ("un rover EMPUJANDO el cubo", (verde,), (RoverDemo(id=10, col=29.6, row=11.6, theta=30.0),)),
        ("un rover tapando MÁS del cubo", (verde,), (RoverDemo(id=10, col=30.8, row=10.6, theta=30.0),)),
    ]


# Escenarios donde NO se exige acertar, sino ADMITIR que no se sabe. Con el 70 %
# del cubo tapado el ajuste llega a errar más que tomar el centro de la mancha:
# lo que no puede hacer es errar en silencio. Acá se verifica que el detector se
# marque como no confiable, que es lo que después deja al seguimiento conservar
# la última posición buena con la edad creciendo, como manda el contrato.
LIMITES_CONOCIDOS = ("un rover tapando MÁS del cubo",)


def centroide_ingenuo(imagen, sistema, cfg, color_objetivo=None):
    """Dónde caería el centro de la mancha más grande, sin modelo ni paralaje.

    Es el método que descartamos, y se calcula igual para poder mostrar al lado
    cuánto se gana. No usa la altura del cubo ni la pose de la cámara: toma la
    mancha y devuelve su centro, que es lo que uno haría sin pensarlo mucho.
    """
    mascara, _ = mascara_de_color(imagen, cfg)
    cantidad, _, stats, centros = cv2.connectedComponentsWithStats(mascara, 8)
    if cantidad < 2:
        return None
    k = 1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA]))
    return sistema.celda_de(float(centros[k][0]), float(centros[k][1]))


# --------------------------------------------------------------------------
# Salida
# --------------------------------------------------------------------------


def anotar(imagen, sistema, cubos, verdad, lado_celdas):
    """Dibuja la base ajustada de cada cubo sobre la imagen."""
    lienzo = imagen.copy() if imagen.ndim == 3 else cv2.cvtColor(imagen, cv2.COLOR_GRAY2BGR)
    for c in cubos:
        base = cuadrado(c.col, c.row, lado_celdas, c.theta_grados)
        px = sistema.a_pixeles(base).astype(np.int32)
        cv2.polylines(lienzo, [px.reshape(-1, 1, 2)], True, (0, 0, 255), 2, cv2.LINE_AA)
        centro = sistema.a_pixeles(np.array([[c.col, c.row]]))[0]
        cv2.drawMarker(lienzo, (int(centro[0]), int(centro[1])), (0, 0, 255),
                       cv2.MARKER_CROSS, 12, 2)
        cv2.putText(lienzo, c.color, (int(centro[0]) + 12, int(centro[1]) - 10),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 255), 1, cv2.LINE_AA)
    for cv_ in verdad.cubos:
        centro = sistema.a_pixeles(np.array([[cv_.col, cv_.row]]))[0]
        cv2.drawMarker(lienzo, (int(centro[0]), int(centro[1])), (0, 200, 0),
                       cv2.MARKER_TILTED_CROSS, 12, 2)
    return lienzo


def correr_modo(cfg, con_perspectiva, umbral_mm, salida, quiere_anotar) -> bool:
    persp = Perspectiva(activa=con_perspectiva,
                        inclinacion_grados=cfg.sintetico.perspectiva.inclinacion_grados)
    titulo = ("CON perspectiva (cámara inclinada {:.1f}°)".format(persp.inclinacion_grados)
              if con_perspectiva else "SIN perspectiva (cenital perfecta)")
    print("=" * 78)
    print("MODO: {}".format(titulo))
    print("=" * 78)
    print("  {:<36} {:>3} {:>9} {:>12} {:>9}  {}".format(
        "escenario", "n", "AJUSTE mm", "centroide mm", "residuo", "estado"))
    print("  " + "-" * 92)

    cell = cfg.tablero.cell_mm
    todo_bien = True
    for nombre, cubos_demo, rovers_demo in escenarios(cfg):
        imagen, verdad = generar(cfg, rovers=rovers_demo, cubos=cubos_demo, perspectiva=persp)
        detectados_aruco = detectar_marcadores(
            imagen, cfg.marcadores_esquina.nombre_diccionario,
            cfg.deteccion_marcadores.refinamiento_esquinas)
        try:
            sistema = construir_sistema(imagen, cfg, detectados_aruco)
        except ErrorGeometria as exc:
            print("  {:<36} ERROR DE GEOMETRÍA: {}".format(nombre, exc))
            todo_bien = False
            continue
        pose = pose_camara(sistema, verdad.camara.matriz)
        cubos = detectar_cubos(imagen, sistema, cfg, pose)

        verdad_por_color = {c.color: c for c in verdad.cubos}
        faltan = sorted(set(verdad_por_color) - {c.color for c in cubos})
        errores, residuos = [], []
        for c in cubos:
            real = verdad_por_color.get(c.color)
            if real is None:
                continue
            errores.append(math.hypot(c.col - real.col, c.row - real.row) * cell)
            residuos.append(c.residuo_celdas)

        ingenuo = centroide_ingenuo(imagen, sistema, cfg)
        error_ingenuo = float("nan")
        if ingenuo is not None and len(verdad.cubos) == 1:
            real = verdad.cubos[0]
            error_ingenuo = math.hypot(ingenuo[0] - real.col, ingenuo[1] - real.row) * cell
        elif ingenuo is not None:
            # Con varios cubos, el centroide se compara contra el más grande.
            error_ingenuo = min(
                math.hypot(ingenuo[0] - r.col, ingenuo[1] - r.row) * cell for r in verdad.cubos)

        peor = max(errores) if errores else float("inf")
        confiables = [c.confiable for c in cubos if c.color in verdad_por_color]

        if nombre in LIMITES_CONOCIDOS:
            # No se le exige acertar: se le exige NO MENTIR.
            paso = (not faltan) and (peor <= umbral_mm or not any(confiables))
            motivo = ("OK (se declara NO confiable)" if paso and any(not c for c in confiables)
                      else "OK" if paso else "MINTIÓ: erró y se dio por confiable")
        else:
            paso = (not faltan) and peor <= umbral_mm and all(confiables)
            motivo = ("OK" if paso else
                      "FALTAN {}".format(faltan) if faltan else
                      "SE DECLARA NO CONFIABLE" if not all(confiables) else "FUERA DE UMBRAL")
        todo_bien = todo_bien and paso
        print("  {:<36} {:>3} {:>9.2f} {:>12.2f} {:>9.3f}  {}".format(
            nombre, len(errores), peor, error_ingenuo,
            max(residuos) if residuos else 0.0, motivo))

        if salida and nombre.startswith("un rover EMPUJANDO"):
            cv2.imwrite(salida, anotar(imagen, sistema, cubos, verdad,
                                       cfg.elementos.cubos.lado_mm / cell)
                        if quiere_anotar else imagen)

    print("\n  umbral de aprobación: {:.2f} mm".format(umbral_mm))
    print("  La columna 'centroide mm' es lo que daría tomar el centro de la mancha,")
    print("  sin modelo ni paralaje. Es el método que se descartó, y está al lado")
    print("  para que la diferencia se vea en vez de haber que creerla.")
    print("  resultado: {}".format("TODO OK" if todo_bien else "HAY ESCENARIOS QUE FALLAN"))
    if salida:
        print("  imagen guardada en: {}".format(salida))
    print()
    return todo_bien


# --------------------------------------------------------------------------
# La luz
# --------------------------------------------------------------------------


def _ruido_de_camara(imagen, semilla: int = 7, sigma: float = 3.9, tinte=(0.0, 0.0)):
    """Ruido de color como el de una webcam real, y el tinte de la luz, en Lab.

    El generador dibuja un tablero perfectamente gris, y contra eso cualquier
    umbral funciona. El `sigma` sale de dos capturas reales del tablero: deja el
    p95 del croma entre 9 y 10, que es lo que se midió. El ruido va suavizado
    porque el de la compresión MJPG viene en manchas, no píxel a píxel.
    """
    rng = np.random.default_rng(semilla)
    lab = cv2.cvtColor(imagen, cv2.COLOR_BGR2LAB).astype(np.float32)
    for canal, corrimiento in ((1, tinte[0]), (2, tinte[1])):
        ruido = cv2.GaussianBlur(
            rng.normal(0.0, 1.0, imagen.shape[:2]).astype(np.float32), (0, 0), 1.5)
        lab[..., canal] += ruido / ruido.std() * sigma + corrimiento
    return cv2.cvtColor(np.clip(lab, 0, 255).astype(np.uint8), cv2.COLOR_LAB2BGR)


def _brillo(imagen, ganancia: float):
    return np.clip(imagen.astype(np.float32) * ganancia, 0, 255).astype(np.uint8)


def _tapas_lavadas(imagen, verdad, cuanto: float):
    """La tapa de cada cubo, mezclada con blanco: lo que hace un reflejo parejo."""
    salida = imagen.astype(np.float32)
    for cubo in verdad.cubos:
        tapa = np.zeros(imagen.shape[:2], np.uint8)
        cv2.fillConvexPoly(tapa, np.array(cubo.tapa_px, np.float32).astype(np.int32), 1)
        salida[tapa == 1] = salida[tapa == 1] * (1.0 - cuanto) + 255.0 * cuanto
    return salida.astype(np.uint8)


def verificar_luz(cfg, umbral_mm: float) -> bool:
    """Los tres cubos, con la luz cambiada. Tienen que seguir estando los tres.

    Es la prueba que faltaba cuando el umbral de croma era un número fijo: en
    una cancha con mucha luz natural aparecía un cubo u otro, nunca los tres,
    porque los cubos de acrílico reflejan y la tapa se lava. Cada caso de acá es
    una forma en que la luz le saca croma a un cubo, sobre un tablero con el
    ruido de color de una cámara de verdad.

    Lo que NO se le exige: recuperar un cubo quemado del todo. Lo que el sensor
    recortó no está en la imagen, y eso se arregla con la exposición.
    """
    persp = Perspectiva(activa=True,
                        inclinacion_grados=cfg.sintetico.perspectiva.inclinacion_grados)
    base, verdad = generar(cfg, rovers=(), perspectiva=persp)
    marcadores = detectar_marcadores(
        base, cfg.marcadores_esquina.nombre_diccionario,
        cfg.deteccion_marcadores.refinamiento_esquinas)
    sistema = construir_sistema(base, cfg, marcadores)
    pose = pose_camara(sistema, verdad.camara.matriz)
    cell = cfg.tablero.cell_mm

    casos = (
        ("luz normal, tablero con ruido de cámara", _ruido_de_camara(base)),
        ("poca luz: brillo x0,4", _ruido_de_camara(_brillo(base, 0.4))),
        ("mucha luz: brillo x2", _ruido_de_camara(_brillo(base, 2.0))),
        ("reflejo: tapas lavadas al 50 %", _ruido_de_camara(_tapas_lavadas(base, verdad, 0.5))),
        ("reflejo: tapas lavadas al 70 %", _ruido_de_camara(_tapas_lavadas(base, verdad, 0.7))),
        ("luz teñida: tablero amarillento", _ruido_de_camara(base, tinte=(0.0, 10.0))),
        ("luz teñida: tablero azulado", _ruido_de_camara(base, tinte=(2.0, -10.0))),
    )

    print("=" * 78)
    print("LA LUZ — los tres cubos, con la iluminación cambiada")
    print("=" * 78)
    print("  {:<42} {:>9} {:>10}  {}".format("caso", "cubos", "peor mm", "estado"))
    print("  " + "-" * 74)
    todo_bien = True
    for nombre, imagen in casos:
        cubos = {c.color: c for c in detectar_cubos(imagen, sistema, cfg, pose)}
        errores, problemas = [], []
        for real in verdad.cubos:
            c = cubos.get(real.color)
            if c is None:
                problemas.append("falta {}".format(real.color))
            elif not c.confiable:
                problemas.append("{} no confiable".format(real.color))
            else:
                errores.append(math.hypot(c.col - real.col, c.row - real.row) * cell)
        peor = max(errores) if errores else float("nan")
        if errores and peor > umbral_mm:
            problemas.append("fuera de umbral")
        todo_bien = todo_bien and not problemas
        print("  {:<42} {:>9} {:>10.2f}  {}".format(
            nombre, "{} de {}".format(len(errores), len(verdad.cubos)), peor,
            "OK" if not problemas else "FALLA: " + ", ".join(problemas)))
    print("\n  resultado: {}\n".format("TODO OK" if todo_bien else "HAY CASOS QUE FALLAN"))
    return todo_bien


def _girar_matiz(imagen, grados: float):
    """Gira el matiz de todo lo coloreado: una luz que corre los tonos de los cubos."""
    lab = cv2.cvtColor(imagen, cv2.COLOR_BGR2LAB).astype(np.float32)
    a, b = lab[..., 1] - 128.0, lab[..., 2] - 128.0
    rad = math.radians(grados)
    lab[..., 1] = a * math.cos(rad) - b * math.sin(rad) + 128.0
    lab[..., 2] = a * math.sin(rad) + b * math.cos(rad) + 128.0
    return cv2.cvtColor(np.clip(lab, 0, 255).astype(np.uint8), cv2.COLOR_LAB2BGR)


def verificar_calibracion_colores(cfg, umbral_mm: float) -> bool:
    """La calibración de colores del arranque: acierta, o se niega. Nunca miente.

    Se giran los matices de los tres cubos, que es lo que hace una luz que corre
    los tonos, y se calibra mirando esa imagen. Dos cosas se le exigen:

    - con un corrimiento moderado, que después de calibrar estén **los tres
      cubos, cada uno con SU color y en su lugar**;
    - con un corrimiento tan grande que ya no se puede saber cuál es cuál —o con
      un cubo de menos—, que **se niegue** y deje los colores del archivo. Una
      calibración que aprende los colores cambiados es peor que no calibrar.
    """
    persp = Perspectiva(activa=True,
                        inclinacion_grados=cfg.sintetico.perspectiva.inclinacion_grados)
    base, verdad = generar(cfg, rovers=(), perspectiva=persp)
    marcadores = detectar_marcadores(
        base, cfg.marcadores_esquina.nombre_diccionario,
        cfg.deteccion_marcadores.refinamiento_esquinas)
    sistema = construir_sistema(base, cfg, marcadores)
    pose = pose_camara(sistema, verdad.camara.matriz)
    cell = cfg.tablero.cell_mm
    dos_cubos, _ = generar(cfg, rovers=(), cubos=cfg.cubos_demo[:2], perspectiva=persp)

    # (nombre, imagen, ¿tiene que calibrar?)
    casos = [("tonos sin correr", base, True)]
    casos += [("tonos corridos {:+d}°".format(g), _girar_matiz(base, g), True)
              for g in (30, 45, -30, -45)]
    casos += [("tonos corridos {:+d}°: irreconocibles".format(g), _girar_matiz(base, g), False)
              for g in (75, -75)]
    casos += [("falta un cubo", dos_cubos, False)]

    print("=" * 78)
    print("CALIBRACIÓN DE COLORES — aprender los matices mirando los cubos")
    print("=" * 78)
    print("  {:<38} {:>12} {:>14}  {}".format("caso", "sin calibrar", "calibrado", "estado"))
    print("  " + "-" * 74)
    todo_bien = True
    for nombre, imagen, debe_calibrar in casos:
        antes = len(detectar_cubos(imagen, sistema, cfg, pose))
        asignados = asignar_matices(medir_matices(imagen, sistema, cfg), cfg)
        if asignados is None:
            paso, despues = (not debe_calibrar), "se niega"
        else:
            cubos = {c.color: c for c in detectar_cubos(
                imagen, sistema, con_matices(cfg, asignados), pose)}
            reales = verdad.cubos if debe_calibrar else ()
            bien = sum(1 for r in reales if r.color in cubos and math.hypot(
                cubos[r.color].col - r.col, cubos[r.color].row - r.row) * cell <= umbral_mm)
            paso = debe_calibrar and bien == len(verdad.cubos)
            despues = "{} de {}".format(bien, len(verdad.cubos))
        todo_bien = todo_bien and paso
        print("  {:<38} {:>12} {:>14}  {}".format(
            nombre, "{} de {}".format(antes, len(verdad.cubos)), despues,
            "OK" if paso else "FALLA"))
    print("\n  resultado: {}\n".format("TODO OK" if todo_bien else "HAY CASOS QUE FALLAN"))
    return todo_bien


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Verifica la detección de cubos contra la verdad del generador sintético."
    )
    parser.add_argument("--config", default=None)
    parser.add_argument("--modo", choices=("ambos", "cenital", "perspectiva"), default="ambos")
    parser.add_argument("--umbral-mm", type=float, default=10.0,
                        help="error máximo aceptado; por defecto el criterio del sistema")
    parser.add_argument("--salida", default=None)
    parser.add_argument("--anotar", action="store_true")
    args = parser.parse_args(argv)

    cfg = cargar_config(args.config) if args.config else cargar_config()
    modos = {"ambos": (False, True), "cenital": (False,), "perspectiva": (True,)}[args.modo]
    resultados = []
    for con_persp in modos:
        salida = args.salida
        if salida and len(modos) > 1:
            base, punto, ext = salida.rpartition(".")
            sufijo = "_perspectiva" if con_persp else "_cenital"
            salida = "{}{}{}{}".format(base or salida, sufijo, punto, ext) if punto else salida + sufijo
        resultados.append(correr_modo(cfg, con_persp, args.umbral_mm, salida, args.anotar))
    resultados.append(verificar_luz(cfg, args.umbral_mm))
    resultados.append(verificar_calibracion_colores(cfg, args.umbral_mm))

    print("=" * 78)
    print("RESULTADO GENERAL: {}".format("TODO OK" if all(resultados) else "HAY FALLAS"))
    print("=" * 78)
    return 0 if all(resultados) else 1


if __name__ == "__main__":
    sys.exit(main())
