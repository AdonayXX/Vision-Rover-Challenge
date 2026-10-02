"""Medición: ¿puede la placa planificar rutas con rutas.py? (incremento 2).

Se llama con los motores PARADOS: planificar bloquea el bucle mientras dura.
Usa la última telemetría que leyó la propia placa. Se importa solo cuando se
pide una medición, para no gastar memoria en el uso normal.
"""
import time

from cliente_vision_rover import ahora_ms


class EstadoPlaca:
    """Lo mínimo que RoutePlanner pide de un estado de telemetría.

    Para medir no se exige frescura: se planifica sobre la última escena vista.
    """

    def __init__(self, mensaje, robot_id):
        self.message, self.robot_id = mensaje, robot_id
        self.seq = mensaje["seq"]
        self.max_age_ms = 10 ** 9

    def reason(self, target_color=None):
        return None

    def capture_age_ms(self):
        return 0

    def rover(self, identidad):
        for item in self.message["rovers"]:
            if item["id"] == identidad:
                return item
        return None

    def cube(self, color):
        for item in self.message["cubes"]:
            if item["color"] == color:
                return item
        return None


def _memoria():
    try:
        import gc
        gc.collect()
        return gc.mem_free()
    except (ImportError, AttributeError):
        return None


def _ampliar_watchdog(segundos):
    try:
        import microcontroller
        anterior = microcontroller.watchdog.timeout
        microcontroller.watchdog.timeout = segundos
        return anterior
    except Exception:
        return None


def medir_ruta(mensaje, robot_id, col, row, paso=1, radio_mm=85, holgura_mm=10):
    """Planifica una vez y devuelve tiempos, memoria y la ruta (o el error)."""
    resultado = {"objetivo": [col, row], "paso": paso, "mem_antes": _memoria()}
    if mensaje is None:
        resultado["error"] = "sin_telemetria"
        return resultado
    t0 = ahora_ms()
    try:
        from rutas import RoutePlanner
    except Exception as error:   # ImportError, MemoryError...
        resultado["error"] = "import: {}: {}".format(type(error).__name__, error)
        return resultado
    resultado["import_ms"] = ahora_ms() - t0
    resultado["mem_tras_import"] = _memoria()
    anterior = _ampliar_watchdog(60)   # una ruta larga no debe reiniciar la placa
    try:
        planner = RoutePlanner(radio_mm, radio_mm, holgura_mm, step_cells=paso,
                               required_colors=())
        t1 = ahora_ms()
        ruta = planner.plan(EstadoPlaca(mensaje, robot_id), {"col": col, "row": row})
        resultado["plan_ms"] = ahora_ms() - t1
        resultado["estado"] = ruta["estado"]
        resultado["motivo"] = ruta["motivo"]
        resultado["puntos"] = [[round(p["col"], 2), round(p["row"], 2)] for p in ruta["puntos"]]
        resultado["distancia_mm"] = None if ruta["distancia_mm"] is None else round(ruta["distancia_mm"])
    except MemoryError:
        resultado["error"] = "MemoryError"
    except Exception as error:
        resultado["error"] = "{}: {}".format(type(error).__name__, error)
    finally:
        if anterior is not None:
            _ampliar_watchdog(anterior)
    resultado["mem_despues"] = _memoria()
    return resultado
