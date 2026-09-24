"""Detección de cubos por color.

Qué hace y qué no
-----------------
Encuentra los cubos de un cuadro y dice **dónde apoya cada uno**, en celdas.
Nada más: no recuerda cuadros anteriores ni decide si un cubo desapareció. Eso
es seguimiento y va en `tracking/`.

El color ES la identidad
------------------------
No hay dos cubos del mismo color, así que el color alcanza para identificarlos y
no llevan ID. El **amarillo está reservado**: un objeto amarillo nunca es un
cubo. Sigue siendo una clase del clasificador aunque esta edición del reto no
tenga obstáculos, para que una mancha amarilla se descarte en vez de forzarse a
uno de los colores de cubo.

Croma para separar, matiz para clasificar
-----------------------------------------
El tablero es acromático: grises, blancos y negros. Entonces todo lo que tenga
**croma** alto en Lab —`√(a*² + b*²)`, que es la saturación en sentido
perceptual— es por definición un objeto de interés. Es un filtro que separa el
fondo del contenido casi gratis, y de paso deja fuera al chasis negro del rover.

La clase sale del **matiz**, el ángulo `atan2(b*, a*)`, y no de la distancia a un
color RGB. El matiz es mucho más estable ante iluminación que comparar canales
crudos. Los valores de referencia se pueden calibrar con los cubos reales, y el
umbral de croma puede tener una recuperación específica por color cuando una cara
del plástico queda menos saturada que las demás.

El problema de verdad: la mancha no es el cubo
----------------------------------------------
Lo que la cámara ve de un cubo **no es una cara**: es la **tapa más una o dos
caras laterales**, y la tapa aparece corrida hacia afuera del punto bajo la
cámara porque está a 60 mm de altura. El centroide de esa mancha no está ni en
el centro del cubo ni a una altura fija: está a una altura efectiva intermedia
que **cambia según dónde esté el cubo** en la cancha.

Por eso el cubo se ubica por su **base**, que está en el piso. Un punto a altura
cero tiene factor de paralaje exactamente 1: no hay nada que corregir y la
homografía del tablero es exacta ahí por construcción.

Pero el borde inferior da una **línea**, y el contrato publica un **centro**. El
punto más bajo de la mancha es una esquina de la base, entre 30 y 42 mm del
centro según cómo esté rotado el cubo: tres a cuatro veces el umbral de 10 mm.

La solución: ajustar el contorno al modelo completo
---------------------------------------------------
La silueta de un cubo es el **casco convexo de su base y de su tapa desplazada**,
y la huella es un cuadrado de **60 mm conocidos**. Eso deja solo **tres
incógnitas** —dónde está el cuadrado y cómo está rotado— contra un contorno de
cientos de puntos.

Ajustar el modelo entero, en vez de buscar dos aristas concretas, es lo que hace
que el detector **aguante la oclusión**: no importa *qué* parte del cubo se vea
mientras se vea suficiente contorno. Y hace falta, porque el caso más frecuente
del juego —el rover empujando un cubo hacia una zona de acopio— le esconde al
cubo alrededor del 22 % del área, y justamente del lado de la arista de la base.

El costo del ajuste es **robusto**: se queda con la fracción de puntos que mejor
encaja y descarta el resto. Cuando un rover tapa parte del cubo, el borde de la
mancha por ese lado no es el borde del cubo sino el del chasis, y esos puntos
tirarían del ajuste hacia un lugar equivocado.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from functools import lru_cache

import cv2
import numpy as np

try:  # como paquete
    from ..configuracion import ConfigVision
    from ..geometry.coordenadas import PoseCamara, SistemaCoordenadas
except ImportError:  # como script suelto
    from vision.configuracion import ConfigVision  # type: ignore[no-redef]
    from vision.geometry.coordenadas import (  # type: ignore[no-redef]
        PoseCamara,
        SistemaCoordenadas,
    )


@dataclass(frozen=True, slots=True)
class CuboDetectado:
    """Un cubo visto en un cuadro. `col` y `row` son el centro de su BASE.

    El centro de la base y no el de la mancha: es lo que el contrato publica, y
    es lo único que está en el piso y por lo tanto libre de paralaje.

    `residuo_celdas` dice qué tan bien encajó el modelo del cubo en el contorno
    observado, y `confiable` es ese residuo comparado contra su umbral.

    **Que exista `confiable` no es un adorno.** Con muy poca evidencia —un rover
    tapando el 70 % del cubo— el ajuste llega a errar más que tomar el centro de
    la mancha. Lo que el detector no puede hacer es errar **en silencio**: con el
    contorno recortado dice que no sabe, y el seguimiento conserva la última
    posición buena con la edad creciendo, que es lo que manda el contrato.
    """

    color: str
    col: float
    row: float
    theta_grados: float
    residuo_celdas: float
    area_px: int
    ocluido: bool
    confiable: bool


# --------------------------------------------------------------------------
# Color
# --------------------------------------------------------------------------


def matiz_y_croma(lab_medio: np.ndarray) -> tuple[float, float]:
    """Matiz en grados y croma, a partir de un `(L*, a*, b*)` de OpenCV.

    OpenCV guarda `a*` y `b*` desplazados 128 para que entren en un byte; hay
    que devolverlos a su origen antes de sacar el ángulo, o el matiz sale
    cualquier cosa.
    """
    a = float(lab_medio[1]) - 128.0
    b = float(lab_medio[2]) - 128.0
    return (math.degrees(math.atan2(b, a)) % 360.0, math.hypot(a, b))


def clasificar(matiz: float, cfg: ConfigVision) -> str | None:
    """Devuelve el color de un matiz, o `None` si no es ninguno de los cubos.

    Se compara por diferencia angular, que respeta el cierre del círculo: el
    rojo está en 39,9° y un matiz de 359° está a 41° de él, no a 319°.

    El amarillo participa de la comparación y después se descarta. Eso es lo
    que lo vuelve una clase de **exclusión** y no una ausencia: si se lo sacara
    de la lista, una mancha amarilla podría terminar forzada al color de cubo
    más cercano.
    """
    dc = cfg.deteccion_cubos
    mejor, distancia_mejor = None, 360.0
    for color, referencia in dc.matices_grados.items():
        distancia = abs((matiz - referencia + 180.0) % 360.0 - 180.0)
        if distancia < distancia_mejor:
            mejor, distancia_mejor = color, distancia
    if mejor is None or distancia_mejor > dc.matiz_tolerancia_grados:
        return None
    if mejor not in cfg.elementos.cubos.colores:  # amarillo u otro reservado
        return None
    return mejor


@lru_cache(maxsize=8)
def _tabla_color(croma_minimo, minimos_por_color, matices, tolerancia):
    """Precalcula las 256x256 combinaciones posibles de a/b de OpenCV.

    El filtro solo depende de estos dos bytes y de la configuración. Repetir
    trigonometría por cada píxel de cada cuadro costaba cientos de milisegundos.
    La tabla aplica exactamente las mismas comparaciones y cambia de clave si
    cambian los umbrales (incluidas las pruebas temporales del diagnóstico).
    """
    valores = np.arange(256, dtype=np.float32) - 128
    a32, b32 = np.meshgrid(valores, valores, indexing="ij")
    croma = np.hypot(a32, b32)
    mascara = croma >= croma_minimo

    # Recuperación por color: el umbral global sigue protegiendo al tablero y a
    # los otros objetos, pero un plástico concreto puede tener una cara menos
    # saturada. Solo se recuperan píxeles cuyo matiz corresponde inequívocamente
    # a ese color y cae dentro de una banda más estrecha que la tolerancia normal
    # del clasificador. Así el verde puede bajar su croma sin abrir la compuerta
    # a todo el fondo de la escena.
    if minimos_por_color:
        referencias = dict(matices)
        matiz = np.degrees(np.arctan2(b32, a32)) % 360.0
        for color, minimo in minimos_por_color:
            referencia = referencias[color]
            distancia = np.abs((matiz - referencia + 180.0) % 360.0 - 180.0)
            es_mas_cercano = np.ones(matiz.shape, dtype=bool)
            for otro, ref_otro in matices:
                if otro == color:
                    continue
                distancia_otro = np.abs((matiz - ref_otro + 180.0) % 360.0 - 180.0)
                es_mas_cercano &= distancia <= distancia_otro
            mascara |= (
                (croma >= minimo)
                & (distancia <= tolerancia)
                & es_mas_cercano
            )

    tabla = mascara.astype(np.uint8)
    tabla.flags.writeable = False
    return tabla


def mascara_de_color(imagen_bgr: np.ndarray, cfg: ConfigVision) -> tuple[np.ndarray, np.ndarray]:
    """Separa lo coloreado del tablero. Devuelve `(máscara, imagen Lab)`."""
    lab = cv2.cvtColor(imagen_bgr, cv2.COLOR_BGR2LAB)
    dc = cfg.deteccion_cubos
    tabla = _tabla_color(dc.croma_minimo, tuple(sorted(dc.croma_minimo_por_color.items())),
                         tuple(sorted(dc.matices_grados.items())), dc.matiz_tolerancia_recuperacion_grados)
    mascara = tabla[lab[:, :, 1], lab[:, :, 2]]
    # Cierra agujeros de un píxel sin mover los bordes, que es de donde sale
    # toda la información de posición.
    nucleo = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
    return cv2.morphologyEx(mascara, cv2.MORPH_CLOSE, nucleo), lab


# --------------------------------------------------------------------------
# El modelo del cubo
# --------------------------------------------------------------------------


def cuadrado(col: float, row: float, lado: float, theta_grados: float) -> np.ndarray:
    """Las cuatro esquinas de un cuadrado en celdas, rotado `theta`."""
    rad = math.radians(theta_grados)
    ux, uy = math.cos(rad), -math.sin(rad)
    vx, vy = -uy, ux
    h = lado / 2.0
    return np.array([
        [col + a * h * ux + b * h * vx, row + a * h * uy + b * h * vy]
        for a, b in ((-1, -1), (1, -1), (1, 1), (-1, 1))
    ], dtype=np.float64)


def silueta_modelo(col, row, theta, lado_celdas, nadir, factor) -> np.ndarray:
    """La silueta que tendría un cubo con esa pose: casco de la base y la tapa.

    La tapa es la base llevada por la homotecia del paralaje. Un cubo es convexo,
    así que su contorno es el casco convexo de sus vértices proyectados.
    """
    base = cuadrado(col, row, lado_celdas, theta)
    tapa = nadir + (base - nadir) * factor
    return cv2.convexHull(np.vstack((base, tapa)).astype(np.float32))


def _costo(contorno: np.ndarray, silueta: np.ndarray, recorte: float) -> float:
    """Distancia media recortada de los puntos observados al borde del modelo.

    Recortada, no media a secas: los puntos del contorno que están sobre el
    borde de un rover que tapa el cubo **no son del cubo**, y una media los
    dejaría tirar del ajuste. Quedándose con la fracción que mejor encaja, el
    ajuste se apoya solo en el contorno que de verdad pertenece al cubo.
    """
    distancias = np.array([
        abs(cv2.pointPolygonTest(silueta, (float(p[0]), float(p[1])), True))
        for p in contorno
    ])
    if len(distancias) == 0:
        return float("inf")
    distancias.sort()
    cuantos = max(3, int(round(len(distancias) * recorte)))
    return float(distancias[:cuantos].mean())


def ajustar_cubo(contorno_celdas: np.ndarray, lado_celdas: float, nadir: np.ndarray,
                 factor: float, cfg: ConfigVision) -> tuple[float, float, float, float]:
    """Encuentra la pose del cubo que mejor explica el contorno observado.

    Tres incógnitas —`col`, `row`, `theta`— contra cientos de puntos. El **lado
    no es incógnita**: son 60 mm conocidos, y eso es exactamente lo que permite
    reconstruir el cuadrado entero viendo solo una parte de él.

    Arranca de una estimación razonable y refina por descenso de coordenadas,
    partiendo el paso a la mitad en cada ronda. No hace falta nada más
    sofisticado: el espacio es de tres dimensiones, el arranque está cerca y la
    función no tiene mínimos locales lejanos.

    La rotación se busca en `[0°, 90°)` porque un cuadrado es simétrico cada 90°:
    buscar en todo el círculo sería repetir la misma solución cuatro veces.
    """
    centroide = contorno_celdas.mean(axis=0)
    # El centroide de la mancha está corrido hacia afuera respecto de la base,
    # porque la mancha incluye la tapa. Traerlo hacia el nadir la mitad de lo
    # que separa a la tapa de la base deja un arranque mucho mejor.
    inicio = nadir + (centroide - nadir) / ((1.0 + factor) / 2.0)

    mejor = (float(inicio[0]), float(inicio[1]), 0.0)
    mejor_costo = float("inf")
    # Barrido grueso de rotación: es la única incógnita sin buena estimación.
    for theta in np.arange(0.0, 90.0, 7.5):
        c = _costo(contorno_celdas,
                   silueta_modelo(mejor[0], mejor[1], theta, lado_celdas, nadir, factor),
                   cfg.deteccion_cubos.recorte_robusto)
        if c < mejor_costo:
            mejor_costo, mejor = c, (mejor[0], mejor[1], float(theta))

    paso_pos, paso_ang = 0.5, 4.0
    for _ in range(cfg.deteccion_cubos.pasos_refinamiento):
        for eje in range(3):
            for signo in (1.0, -1.0):
                candidato = list(mejor)
                candidato[eje] += signo * (paso_ang if eje == 2 else paso_pos)
                c = _costo(contorno_celdas,
                           silueta_modelo(*candidato, lado_celdas, nadir, factor),
                           cfg.deteccion_cubos.recorte_robusto)
                if c < mejor_costo:
                    mejor_costo, mejor = c, tuple(candidato)
        paso_pos /= 2.0
        paso_ang /= 2.0

    return (mejor[0], mejor[1], mejor[2] % 90.0, mejor_costo)


# --------------------------------------------------------------------------
# Detección
# --------------------------------------------------------------------------


def area_cara_local_px(sistema: SistemaCoordenadas, centro_px, lado_celdas: float) -> float:
    """Área de una cara en el piso, proyectada donde está el candidato.

    Con perspectiva, los dos lados tienen escalas distintas y cambian de un
    extremo al otro de la cancha. Elevar al cuadrado un lado medido en el
    origen subestimaba el área y rechazaba cubos reales en cámaras inclinadas.
    """
    col, row = sistema.a_celdas(np.asarray([centro_px], dtype=np.float64))[0]
    cara = sistema.a_pixeles(cuadrado(col, row, lado_celdas, 0.0))
    return max(1.0, float(cv2.contourArea(cara.astype(np.float32))))


def detectar_cubos(
    imagen_bgr: np.ndarray,
    sistema: SistemaCoordenadas,
    cfg: ConfigVision,
    pose_de_camara: PoseCamara,
) -> tuple[CuboDetectado, ...]:
    """Encuentra los cubos de un cuadro y devuelve dónde apoya cada uno.

    Necesita la **pose de cámara** —que sale de los cuatro marcadores de esquina,
    sin declarar nada— por dos motivos: para saber dónde está el nadir, que es
    hacia donde se desplaza la tapa, y para construir el modelo de la silueta.

    Si dos manchas se clasifican del mismo color se conserva la más grande: el
    color es la identidad y **no puede haber dos cubos del mismo color**, así que
    la segunda es un reflejo o un objeto ajeno.

    Devuelve la tupla ordenada por color para que dos corridas den lo mismo. Eso
    **no** habilita a indexar por posición: hay que buscar por `color`.
    """
    dc = cfg.deteccion_cubos
    lado_celdas = cfg.elementos.cubos.lado_mm / cfg.tablero.cell_mm
    nadir = np.array(pose_de_camara.nadir_celdas, dtype=np.float64)
    factor = pose_de_camara.factor_paralaje(cfg.elementos.cubos.lado_mm)

    mascara, lab = mascara_de_color(imagen_bgr, cfg)
    cantidad, etiquetas, stats, centroides = cv2.connectedComponentsWithStats(mascara, 8)

    candidatos: dict[str, CuboDetectado] = {}
    for etiqueta in range(1, cantidad):
        area = int(stats[etiqueta, cv2.CC_STAT_AREA])
        area_cara = area_cara_local_px(sistema, centroides[etiqueta], lado_celdas)
        if not (area_cara * dc.area_minima_relativa <= area <= area_cara * dc.area_maxima_relativa):
            continue

        region = (etiquetas == etiqueta).astype(np.uint8)
        matiz, croma = matiz_y_croma(cv2.mean(lab, mask=region)[:3])
        color = clasificar(matiz, cfg)
        if color is None:
            continue

        contornos, _ = cv2.findContours(region, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
        if not contornos:
            continue
        contorno_px = max(contornos, key=cv2.contourArea).reshape(-1, 2).astype(np.float64)
        # Submuestreo: con cien puntos alcanza para fijar tres incógnitas, y el
        # ajuste tiene que correr a la velocidad de la cámara.
        if len(contorno_px) > 120:
            contorno_px = contorno_px[:: max(1, len(contorno_px) // 120)]

        # A CELDAS antes de ajustar nada, por lo mismo de siempre: en píxeles la
        # forma depende de dónde caiga el objeto en el cuadro.
        contorno = sistema.a_celdas(contorno_px)
        col, row, theta, residuo = ajustar_cubo(contorno, lado_celdas, nadir, factor, cfg)

        cubo = CuboDetectado(
            color=color, col=col, row=row, theta_grados=theta,
            residuo_celdas=residuo, area_px=area,
            ocluido=area < area_cara * 0.8,
            confiable=residuo <= dc.residuo_maximo_celdas,
        )
        anterior = candidatos.get(color)
        if anterior is None or cubo.area_px > anterior.area_px:
            candidatos[color] = cubo

    return tuple(candidatos[c] for c in sorted(candidatos))
