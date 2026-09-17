"""Rutas y márgenes contra casos geométricos y muestreo independiente."""
import json
import math
from pathlib import Path
import sys
import unittest

ROBOTS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROBOTS / "codigos"))
sys.path.insert(0, str(ROBOTS / "pc"))
from rutas import RoutePlanner, point_segment_distance
from telemetria import TelemetryState
from demo_rutas import scenario, run_demo


class RouteTests(unittest.TestCase):
    def setUp(self):
        self.msg = scenario()
        self.now = 0
        self.state = TelemetryState(monotonic=lambda: self.now, wall=lambda: 1000 + self.now)
        self.state.connect()
        self.planner = RoutePlanner(robot_radius_mm=85, peer_radius_mm=85, clearance_mm=15)
        self.goal = {"col": 36, "row": 21}

    def plan(self, goal=None):
        self.msg["seq"] += 1
        self.assertTrue(self.state.accept_line(json.dumps(self.msg)), self.state.fault)
        return self.planner.plan(self.state, self.goal if goal is None else goal)

    def assert_clear(self, result):
        self.assertEqual(result["estado"], "RUTA", result)
        # Muestreo independiente de free_segment y point_segment_distance.
        # Radios esperados para la configuración de este fixture, en celdas.
        circles = [(r["col"], r["row"], 9.25) for r in self.msg["rovers"] if r["id"] != 10]
        circles += [(c["col"], c["row"], 5 + 3 * math.sqrt(2) / 2) for c in self.msg["cubes"]]
        circles += [(o["col"], o["row"], 5 + 5 * math.sqrt(2) / 2) for o in self.msg["obstacles"]]
        pts = result["puntos"]
        for a, b in zip(pts, pts[1:]):
            for i in range(501):
                t = i / 500
                x = a["col"] + t * (b["col"] - a["col"])
                y = a["row"] + t * (b["row"] - a["row"])
                self.assertTrue(5 <= x <= 38 and 5 <= y <= 38)
                for cx, cy, radius in circles:
                    self.assertGreater(math.hypot(x - cx, y - cy), radius)

    def test_detours_cube_and_preserves_endpoints(self):
        result = self.plan()
        self.assert_clear(result)
        self.assertEqual(result["puntos"][0], {"col": 7, "row": 21})
        self.assertEqual(result["puntos"][-1], self.goal)
        self.assertGreater(result["distancia_mm"], 580)

    def test_free_straight_path_is_direct(self):
        self.msg["cubes"] = []
        self.planner = RoutePlanner(85, 85, 15, required_colors=())
        result = self.plan()
        self.assert_clear(result)
        self.assertEqual(len(result["puntos"]), 2)
        self.assertEqual(result["distancia_mm"], 580)

    def test_peer_in_path_is_avoided(self):
        self.msg["cubes"] = []
        self.msg["rovers"][1].update(col=21, row=21)
        self.planner = RoutePlanner(85, 85, 15, required_colors=())
        result = self.plan()
        self.assert_clear(result)
        self.assertGreater(len(result["puntos"]), 2)

    def test_fractional_start_and_goal_never_snap_across_obstacles(self):
        self.msg["rovers"][0].update(col=7.3, row=20.8)
        self.goal = {"col": 36.2, "row": 21.2}
        result = self.plan()
        self.assert_clear(result)
        self.assertEqual(result["puntos"][0], {"col": 7.3, "row": 20.8})
        self.assertEqual(result["puntos"][-1], self.goal)

    def test_occupied_destination_and_border_rejected(self):
        for goal in ({"col": 21, "row": 21}, {"col": 1, "row": 20}, {"col": 44, "row": 20}):
            result = self.plan(goal)
            self.assertEqual(result["estado"], "ESPERAR")
            self.assertEqual(result["puntos"], [])

    def test_origin_collision_is_not_recovered_by_unsafe_escape(self):
        self.msg["rovers"][0].update(col=21, row=21)
        self.assertEqual(self.plan()["motivo"], "origen_sin_espacio")

    def test_unknown_or_stale_cube_blocks_planning(self):
        self.msg["cubes"][0]["age_ms"] = 600
        self.assertEqual(self.plan()["estado"], "ESPERAR")
        self.msg["cubes"].pop(0)
        self.assertIn("cubo_requerido_ausente", self.plan()["motivo"])

    def test_phase_disconnect_and_capture_age(self):
        self.msg["phase"] = "READY"
        self.assertEqual(self.plan()["motivo"], "fase_READY")
        self.msg["phase"] = "RUNNING"
        self.plan()
        self.now = .6
        self.assertEqual(self.planner.plan(self.state, self.goal)["estado"], "ESPERAR")
        self.state.disconnect()
        self.assertEqual(self.planner.plan(self.state, self.goal)["estado"], "ESPERAR")

    def test_wall_has_no_route(self):
        self.msg["obstacles"] = [{"col": 21, "row": row, "age_ms": 0} for row in (4, 12, 20, 28, 36, 43)]
        self.assertEqual(self.plan()["motivo"], "sin_ruta_en_la_grilla")

    def test_obstacle_and_tangency_checked_along_whole_segment(self):
        scene = {"cols": 10, "rows": 10, "margin": 0, "circles": [(5, 5, 1)]}
        self.assertFalse(self.planner.free_segment(scene, (1, 4), (9, 4)))
        self.assertFalse(self.planner.free_segment(scene, (1, 1), (9, 9)))
        self.assertTrue(self.planner.free_segment(scene, (1, 3.9), (9, 3.9)))
        self.assertEqual(point_segment_distance((5, 5), (1, 1), (1, 1)), math.sqrt(32))
        self.assertEqual(point_segment_distance((5, 5), (1, 4), (9, 4)), 1)

    def test_static_obstacle_rerouted_and_old_obstacle_blocks(self):
        self.msg["cubes"] = []
        self.msg["obstacles"] = [{"col": 21, "row": 21, "age_ms": 0}]
        self.planner = RoutePlanner(85, 85, 15, required_colors=())
        self.assert_clear(self.plan())
        self.msg["obstacles"][0]["age_ms"] = 600
        self.assertIn("entidad_vieja", self.plan()["motivo"])

    def test_search_space_is_bounded(self):
        self.planner = RoutePlanner(85, 85, 15, step_cells=.01)
        self.assertEqual(self.plan()["motivo"], "grilla_supera_limite_de_nodos")

    def test_zero_length_route_and_invalid_goal(self):
        result = self.plan({"col": 7, "row": 21})
        self.assertEqual(result["distancia_mm"], 0)
        self.assertEqual(len(result["puntos"]), 1)
        for goal in ({}, {"col": float("nan"), "row": 21}, {"col": True, "row": 21}):
            self.assertEqual(self.plan(goal)["estado"], "ESPERAR")

    def test_config_rejects_invalid_dimensions(self):
        for args in ((0, 85, 15), (85, -1, 15), (85, 85, -1), (float("inf"), 85, 15)):
            with self.assertRaises(ValueError):
                RoutePlanner(*args)

    def test_full_demo_drops_route_after_world_changes(self):
        result = run_demo(announce=lambda text: None)
        self.assertEqual(result["resultado"], "OK")
        self.assertEqual(result["tras_mover_companero"], "ESPERAR")
        self.assertEqual(result["destino_ocupado"], "ESPERAR")
        self.assertEqual(result["dato_viejo"], "ESPERAR")


if __name__ == "__main__":
    unittest.main()
