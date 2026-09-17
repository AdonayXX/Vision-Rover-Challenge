"""Geometría con resultados conocidos, decisiones e integración numérica."""
import copy
import json
import math
from pathlib import Path
import sys
import unittest

ROBOTS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROBOTS / "codigos"))
sys.path.insert(0, str(ROBOTS / "pc"))
from navegacion import PointNavigator, calcular_objetivo, giro_corto
from telemetria import TelemetryState
from demo_navegacion import run_demo


class NavigationTests(unittest.TestCase):
    def setUp(self):
        config = json.loads((ROBOTS.parent / "vision-system/contrato/config_simulador.json").read_text(encoding="utf-8"),
                            object_hook=lambda d: {k: v for k, v in d.items() if not k.startswith("_")})
        self.message = {k: copy.deepcopy(config[k]) for k in
                        ("grid", "start", "depots", "depot_size", "cube_side", "cubes", "rovers", "obstacles")}
        for key in ("rovers", "cubes", "obstacles"):
            for value in self.message[key]:
                value["age_ms"] = 0
        self.message.update(v=2, seq=1, ts_ms=1000000, phase="RUNNING",
                            clock={"elapsed_ms": 0, "remaining_ms": 1000, "total_ms": 1000})
        self.now = 0
        self.state = TelemetryState(monotonic=lambda: self.now, wall=lambda: 1000 + self.now)
        self.state.connect()
        self.nav = PointNavigator()
        self.own = next(r for r in self.message["rovers"] if r["id"] == 10)
        self.own.update(col=10, row=10, theta=0)

    def decide(self, col, row):
        self.message["seq"] += 1
        self.assertTrue(self.state.accept_line(json.dumps(self.message)), self.state.fault)
        return self.nav.decide(self.state, {"col": col, "row": row})

    def test_cardinal_headings_respect_rows_downwards(self):
        for target, expected in [((11, 10), 0), ((10, 9), 90), ((9, 10), 180), ((10, 11), 270)]:
            with self.subTest(target=target):
                result = calcular_objetivo(self.own, dict(zip(("col", "row"), target)), 20)
                self.assertEqual(result["rumbo_grados"], expected)
                self.assertEqual(result["distancia_mm"], 20)

    def test_diagonal_345_and_variable_scale(self):
        result = calcular_objetivo(self.own, {"col": 13, "row": 6}, 30)
        self.assertEqual(result["distancia_celdas"], 5)
        self.assertEqual(result["distancia_mm"], 150)
        self.assertAlmostEqual(result["rumbo_grados"], 53.130102, places=5)

    def test_short_turn_crosses_zero(self):
        pose = {"col": 0, "row": 0, "theta": 359}
        self.assertEqual(calcular_objetivo(pose, {"col": 1, "row": 0}, 20)["giro_grados"], 1)
        self.assertEqual(giro_corto(358), -2)
        self.assertEqual(giro_corto(-358), 2)
        self.assertEqual(giro_corto(180), -180)

    def test_coincident_point_has_no_arbitrary_heading(self):
        result = calcular_objetivo(self.own, self.own, 20)
        self.assertIsNone(result["rumbo_grados"])
        self.assertEqual(result["giro_grados"], 0)
        self.assertEqual(self.decide(10, 10)["accion"], "ALCANZADO")

    def test_turn_advance_and_arrival(self):
        self.assertEqual(self.decide(10, 5)["accion"], "GIRAR")
        self.own["theta"] = 90
        self.assertEqual(self.decide(10, 5)["accion"], "AVANZAR")
        self.own.update(row=5.5, theta=270)
        # Llegar prevalece sobre orientar, incluso mirando en sentido contrario.
        result = self.decide(10, 5)
        self.assertEqual(result["accion"], "ALCANZADO")
        self.assertFalse(result["ruta_verificada"])

    def test_tolerance_boundaries(self):
        self.assertEqual(self.decide(11, 10)["accion"], "ALCANZADO")
        self.own["theta"] = 355
        self.assertEqual(self.decide(15, 10)["accion"], "AVANZAR")
        self.own["theta"] = 354.9
        self.assertEqual(self.decide(15, 10)["accion"], "GIRAR")

    def test_waits_for_phase_disconnect_and_old_data(self):
        for phase in ("IDLE", "READY", "FINISHED"):
            self.message["phase"] = phase
            self.assertEqual(self.decide(15, 10)["accion"], "ESPERAR")
        self.message["phase"] = "RUNNING"
        self.decide(15, 10)
        self.now = .6
        self.assertEqual(self.nav.decide(self.state, {"col": 15, "row": 10})["accion"], "ESPERAR")
        self.state.disconnect()
        self.assertEqual(self.nav.decide(self.state, {"col": 15, "row": 10})["accion"], "ESPERAR")

    def test_waits_for_missing_peer_and_invalid_message(self):
        self.message["rovers"] = [self.own]
        self.assertEqual(self.decide(15, 10)["motivo"], "companero_ausente")
        self.state.accept_line('{"v":99}')
        self.assertEqual(self.nav.decide(self.state, {"col": 15, "row": 10})["accion"], "ESPERAR")

    def test_board_dimensions_and_margin_are_respected(self):
        self.message["grid"]["cols"] = 20
        self.assertEqual(self.decide(21, 10)["accion"], "ESPERAR")
        self.nav = PointNavigator(border_margin_mm=40)
        self.assertEqual(self.decide(1, 10)["motivo"], "objetivo_fuera_del_area_permitida")
        self.own["col"] = 1
        self.assertEqual(self.decide(10, 10)["motivo"], "robot_fuera_del_area_permitida")
        self.nav = PointNavigator(border_margin_mm=1000)
        self.assertEqual(self.decide(10, 10)["motivo"], "margen_sin_espacio_util")

    def test_invalid_inputs_never_recommend_motion(self):
        self.decide(15, 10)
        for value in (float("nan"), float("inf"), "15", True, None):
            self.assertEqual(self.nav.decide(self.state, {"col": value, "row": 10})["accion"], "ESPERAR")
        for cell in (0, -1, float("nan")):
            with self.assertRaises(ValueError):
                calcular_objetivo(self.own, {"col": 1, "row": 1}, cell)
        for args in ({"position_tolerance_mm": -1}, {"angle_tolerance_deg": 180}, {"border_margin_mm": -1}):
            with self.assertRaises(ValueError):
                PointNavigator(**args)

    def test_pose_from_selected_id_even_if_list_reordered(self):
        self.message["rovers"].reverse()
        result = self.decide(15, 10)
        self.assertEqual(result["medidas"]["distancia_mm"], 100)

    def test_ideal_closed_loop_reaches_point_and_pauses(self):
        result = run_demo(announce=lambda text: None)
        self.assertEqual(result["resultado"], "OK")
        self.assertLessEqual(result["error_final_mm"], 20)
        self.assertTrue(result["espera_por_datos_viejos"])


if __name__ == "__main__":
    unittest.main()
