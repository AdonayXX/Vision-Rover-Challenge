"""Geometría de aproximación y empuje de un cubo.

No toca motores ni red. La prueba física de PC reutiliza estas funciones para
colocarse detrás del cubo, alinearse con el destino y decidir cuándo detener el
empuje a partir de la telemetría fresca de visión.
"""

import math

from navegacion import _finite, calcular_objetivo


def _point(value):
    return {"col": _finite(value["col"]), "row": _finite(value["row"])}


def distancia_mm(a, b, cell_mm):
    """Distancia euclídea entre dos posiciones del contrato."""
    a, b = _point(a), _point(b)
    cell_mm = _finite(cell_mm)
    if cell_mm <= 0:
        raise ValueError("cell_mm debe ser positivo")
    return math.hypot(b["col"] - a["col"], b["row"] - a["row"]) * cell_mm


def punto_detras_del_cubo(cubo, destino, distancia_centro_mm, cell_mm):
    """Centro del rover detrás del cubo respecto de la dirección de empuje.

    `distancia_centro_mm` es la separación deseada entre el centro del cubo y
    el centro del rover durante la aproximación, antes de hacer contacto.
    """
    cubo, destino = _point(cubo), _point(destino)
    cell_mm = _finite(cell_mm)
    distancia_centro_mm = _finite(distancia_centro_mm)
    if cell_mm <= 0 or distancia_centro_mm <= 0:
        raise ValueError("Escala y distancia deben ser positivas")
    dc = destino["col"] - cubo["col"]
    dr = destino["row"] - cubo["row"]
    largo = math.hypot(dc, dr)
    if largo <= 1e-9:
        raise ValueError("El cubo ya coincide con el destino")
    separacion = distancia_centro_mm / cell_mm
    return {
        "col": cubo["col"] - dc / largo * separacion,
        "row": cubo["row"] - dr / largo * separacion,
    }


def destino_valido_para_cubo(destino, grid, cube_side_mm):
    """Exige que el cubo completo pueda quedar dentro del tablero.

    Se usa media diagonal, por lo que el criterio sirve para cualquier rotación.
    """
    destino = _point(destino)
    cell_mm = _finite(grid["cell_mm"])
    cols = _finite(grid["cols"])
    rows = _finite(grid["rows"])
    side = _finite(cube_side_mm)
    if min(cell_mm, cols, rows, side) <= 0:
        raise ValueError("Geometría inválida")
    margin = side * math.sqrt(2) / (2 * cell_mm)
    return (
        margin <= destino["col"] <= cols - margin
        and margin <= destino["row"] <= rows - margin
    )


def decidir_movimiento_hacia(pose, objetivo, cell_mm, tolerancia_mm=20,
                             tolerancia_angular_deg=6):
    """Decisión cerrada simple para el control físico por visión."""
    tolerancia_mm = _finite(tolerancia_mm)
    tolerancia_angular_deg = _finite(tolerancia_angular_deg)
    if tolerancia_mm < 0 or not 0 <= tolerancia_angular_deg < 180:
        raise ValueError("Tolerancias inválidas")
    medidas = calcular_objetivo(pose, objetivo, cell_mm)
    if medidas["distancia_mm"] <= tolerancia_mm:
        accion = "ALCANZADO"
    elif abs(medidas["giro_grados"]) > tolerancia_angular_deg:
        accion = "GIRAR"
    else:
        accion = "AVANZAR"
    return {"accion": accion, "medidas": medidas}


def objetivo_deposito(message, color):
    if color not in ("red", "green", "blue"):
        raise ValueError("Color de depósito inválido")
    for depot in message["depots"]:
        if depot["color"] == color:
            return {"col": float(depot["col"]), "row": float(depot["row"])}
    raise ValueError("Depósito ausente: " + color)
