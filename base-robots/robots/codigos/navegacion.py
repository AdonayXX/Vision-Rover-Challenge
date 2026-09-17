"""Geometría y recomendaciones hacia un punto; no envía órdenes a motores.

Convención del contrato: col hacia derecha, row hacia abajo, theta positivo
antihorario y cero hacia derecha. No planifica rutas ni evita colisiones.
"""
import math


def _finite(value):
    if type(value) not in (int, float) or not math.isfinite(value):
        raise ValueError("Se requiere un numero finito")
    return value


def giro_corto(degrees):
    """Devuelve [-180, 180); el empate de media vuelta se resuelve a -180."""
    return (_finite(degrees) + 180) % 360 - 180


def calcular_objetivo(pose, objetivo, cell_mm):
    """Distancia y giro relativos a la pose GLOBAL observada por ArUco."""
    cell_mm = _finite(cell_mm)
    if cell_mm <= 0:
        raise ValueError("cell_mm debe ser positivo")
    dc = _finite(objetivo["col"]) - _finite(pose["col"])
    dr = _finite(objetivo["row"]) - _finite(pose["row"])
    theta = _finite(pose["theta"])
    distance = math.hypot(dc, dr)
    # Invertir row: arriba en la imagen corresponde a +90 grados, no -90.
    heading = math.degrees(math.atan2(-dr, dc)) % 360 if distance else None
    distance_mm = distance * cell_mm
    _finite(distance_mm)
    return {
        "distancia_celdas": distance,
        "distancia_mm": distance_mm,
        "rumbo_grados": heading,
        "giro_grados": giro_corto(heading - theta) if heading is not None else 0.0,
    }


class PointNavigator:
    def __init__(self, position_tolerance_mm=20, angle_tolerance_deg=5,
                 border_margin_mm=0):
        self.position_tolerance_mm = _finite(position_tolerance_mm)
        self.angle_tolerance_deg = _finite(angle_tolerance_deg)
        self.border_margin_mm = _finite(border_margin_mm)
        if position_tolerance_mm < 0 or not 0 <= angle_tolerance_deg < 180 or border_margin_mm < 0:
            raise ValueError("Tolerancias o margen fuera de rango")

    def decide(self, state, objetivo):
        """Una recomendación por observación; el propietario debe validar la ruta.

        Las tolerancias son parámetros de simulación hasta calibrar hardware.
        El margen sólo comprueba los centros de origen/destino, no el chasis.
        """
        result = {"accion": "ESPERAR", "motivo": None, "medidas": None,
                  "ruta_verificada": False}
        reason = state.reason()
        if reason is not None:
            result["motivo"] = reason
            return result
        try:
            grid = state.message["grid"]
            pose = state.rover(state.robot_id)
            metrics = calcular_objetivo(pose, objetivo, grid["cell_mm"])
            margin = self.border_margin_mm / grid["cell_mm"]
            if 2 * margin >= min(grid["cols"], grid["rows"]):
                result["motivo"] = "margen_sin_espacio_util"
                return result
            for label, point in (("objetivo", objetivo), ("robot", pose)):
                if not (margin <= point["col"] <= grid["cols"] - margin and
                        margin <= point["row"] <= grid["rows"] - margin):
                    result["motivo"] = label + "_fuera_del_area_permitida"
                    return result
        except (ValueError, TypeError, KeyError, OverflowError):
            result["motivo"] = "objetivo_o_geometria_invalida"
            return result
        result["medidas"] = metrics
        if metrics["distancia_mm"] <= self.position_tolerance_mm:
            result.update(accion="ALCANZADO", motivo="dentro_de_tolerancia")
        elif abs(metrics["giro_grados"]) > self.angle_tolerance_deg:
            result.update(accion="GIRAR", motivo="alinear_con_objetivo")
        else:
            result.update(accion="AVANZAR", motivo="rumbo_alineado")
        return result
