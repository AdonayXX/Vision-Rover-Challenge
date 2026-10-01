"""Análisis de la calibración con trayectorias sintéticas de resultado conocido."""
import math
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "pc"))
import calibrar_movimiento as cal

CELL = 20.0


def trayectoria(theta0, mm_s=0.0, deg_s=0.0, retraso=80, t_orden=1000, t_stop=2000,
                deriva_mm=0.0, paso=50):
    """Rover que arranca `retraso` ms tras la orden y se pasa `deriva_mm` al parar."""
    muestras = []
    for t in range(0, 4001, paso):
        activo = max(0, min(t, t_stop) - (t_orden + retraso)) / 1000
        avance = mm_s * activo + (deriva_mm if t >= t_stop + 300 else 0)
        giro = deg_s * activo
        th = math.radians(theta0)
        muestras.append({"t": t, "col": 10 + avance * math.cos(th) / CELL,
                         "row": 10 - avance * math.sin(th) / CELL,
                         "theta": (theta0 + giro) % 360})
    return muestras


class AnalisisTests(unittest.TestCase):
    def test_forward_speed_delay_and_coast(self):
        r = cal.analizar(trayectoria(0, mm_s=120, deriva_mm=6), 1000, 2000, CELL)
        self.assertAlmostEqual(r["mm_s"], 120, delta=1)
        self.assertAlmostEqual(r["retraso_arranque_ms"], 100, delta=50)
        self.assertAlmostEqual(r["deriva_tras_stop_mm"], 6, delta=.5)
        self.assertAlmostEqual(r["total_lateral_mm"], 0, delta=.5)

    def test_frame_follows_heading_with_row_downwards(self):
        # theta=90 apunta hacia row decreciente: sigue siendo "adelante".
        r = cal.analizar(trayectoria(90, mm_s=100), 1000, 2000, CELL)
        self.assertAlmostEqual(r["mm_s"], 100, delta=1)
        self.assertGreater(r["total_adelante_mm"], 80)

    def test_turn_rate_across_zero(self):
        r = cal.analizar(trayectoria(350, deg_s=-60), 1000, 2000, CELL)
        self.assertAlmostEqual(r["deg_s"], -60, delta=1)
        self.assertAlmostEqual(r["total_giro_deg"], -55, delta=2)

    def test_summary_fits_gain_through_origin(self):
        resultados = {"avance_0.20": {"mm_s": 100}, "retroceso_0.20": {"mm_s": -100},
                      "avance_0.30": {"mm_s": 150},
                      "giro_izq_0.18": {"deg_s": 90}, "giro_der_0.18": {"deg_s": -90}}
        s = cal.resumir(resultados, [300, 320, 500])
        self.assertAlmostEqual(s["avance_mm_s_por_unidad"], 500, delta=1)
        self.assertEqual(s["latencia_vision_ms"]["mediana"], 320)

    def test_dead_zone_fit_per_family(self):
        # Datos reales del 1-oct: izquierda casi atascada a 0,18.
        resultados = {"giro_izq_0.18": {"deg_s": 44.6}, "giro_izq_0.25": {"deg_s": 123.5},
                      "giro_der_0.18": {"deg_s": -92.4}, "giro_der_0.25": {"deg_s": -150.4}}
        izq = cal.ajuste_con_zona_muerta(resultados, "giro_izq", "deg_s")
        der = cal.ajuste_con_zona_muerta(resultados, "giro_der", "deg_s")
        self.assertAlmostEqual(izq["zona_muerta"], .14, delta=.01)
        self.assertAlmostEqual(der["zona_muerta"], .069, delta=.01)


if __name__ == "__main__":
    unittest.main()
