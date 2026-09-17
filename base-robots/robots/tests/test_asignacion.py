"""Reparto completo, costos verificables y comparación reproducible."""
import json
from pathlib import Path
import sys
import unittest

ROBOTS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROBOTS / "codigos"))
sys.path.insert(0, str(ROBOTS / "pc"))
from asignacion import compare_assignments
from telemetria import TelemetryState
from demo_rutas import scenario
from demo_asignacion import run_comparison


class AssignmentTests(unittest.TestCase):
    def setUp(self):
        self.message = scenario()
        self.now = 0
        self.state = TelemetryState(monotonic=lambda: self.now, wall=lambda: 1000 + self.now)
        self.state.connect()

    def compare(self):
        self.message["seq"] += 1
        self.assertTrue(self.state.accept_line(json.dumps(self.message)), self.state.fault)
        return compare_assignments(self.state)

    def test_all_cubes_once_both_robots_used(self):
        result = self.compare()
        self.assertEqual(result["estado"], "PROPUESTA")
        self.assertEqual(result["candidatos_evaluados"], 12)
        self.assertFalse(result["rutas_verificadas"])
        for strategy in ("cercano", "equilibrado"):
            plans = result[strategy]["robots"]
            self.assertEqual([p["robot_id"] for p in plans], [10, 11])
            self.assertTrue(all(p["cubos"] for p in plans))
            self.assertEqual(sorted(c for p in plans for c in p["cubos"]), ["blue", "green", "red"])

    def test_known_line_cost_and_third_goes_to_first_available(self):
        # Distancias fáciles de comprobar; no es una escena física viable.
        # R10 en 0, R11 en 30; cubos/destinos en 1, 10, 29.
        self.message["grid"]["cell_mm"] = 1
        self.message["rovers"][0].update(col=0, row=20)
        self.message["rovers"][1].update(col=30, row=20)
        positions = {"blue": 1, "green": 10, "red": 29}
        for group in ("cubes", "depots"):
            for entity in self.message[group]:
                entity.update(col=positions[entity["color"]], row=20)
        result = self.compare()
        # Ambos terminan su primera tarea tras 1 unidad; desempata ID 10.
        self.assertEqual(result["cercano"]["robots"][0]["cubos"], ["blue", "green"])
        self.assertEqual(result["cercano"]["robots"][0]["carga_mm"], 10)
        self.assertEqual(result["cercano"]["robots"][1]["carga_mm"], 1)
        self.assertEqual(result["equilibrado"]["carga_maxima_mm"], 10)
        self.assertEqual(result["equilibrado"]["distancia_total_mm"], 11)

    def test_delivery_included_and_next_task_starts_at_depot(self):
        self.message["grid"]["cell_mm"] = 1
        self.message["rovers"][0].update(col=0, row=20)
        self.message["rovers"][1].update(col=30, row=20)
        for cube in self.message["cubes"]:
            cube.update(col={"blue": 1, "green": 10, "red": 29}[cube["color"]], row=20)
        for depot in self.message["depots"]:
            depot.update(col={"blue": 4, "green": 12, "red": 20}[depot["color"]], row=20)
        result = self.compare()["cercano"]
        # R10: 0->1->4 (4), luego 4->10->12 (8), total 12.
        # R11: 30->29->20, total 10; R10 queda libre primero.
        first = result["robots"][0]
        self.assertEqual(first["cubos"], ["blue", "green"])
        self.assertEqual(first["carga_mm"], 12)
        self.assertEqual(first["tareas"][1]["aproximacion_mm"], 6)
        self.assertEqual(first["tareas"][1]["entrega_mm"], 2)

    def test_same_plan_from_either_robot_and_different_array_order(self):
        result = self.compare()
        other = TelemetryState(robot_id=11, peer_id=10, monotonic=lambda: 0, wall=lambda: 1000)
        other.connect()
        self.message["rovers"].reverse()
        self.message["cubes"].reverse()
        other.accept_line(json.dumps(self.message))
        self.assertEqual(compare_assignments(other), result)

    def test_scaling_cells_scales_cost_not_assignment(self):
        before = self.compare()
        self.message["grid"]["cell_mm"] *= 2
        after = self.compare()
        for strategy in ("cercano", "equilibrado"):
            self.assertEqual(before[strategy]["carga_maxima_mm"] * 2, after[strategy]["carga_maxima_mm"])
            self.assertEqual([p["cubos"] for p in before[strategy]["robots"]],
                             [p["cubos"] for p in after[strategy]["robots"]])

    def test_old_missing_cube_and_inactive_round_wait(self):
        self.message["phase"] = "READY"
        self.assertEqual(self.compare()["estado"], "ESPERAR")
        self.message["phase"] = "RUNNING"
        self.message["cubes"][0]["age_ms"] = 600
        self.assertEqual(self.compare()["estado"], "ESPERAR")
        self.message["cubes"].pop(0)
        self.assertEqual(self.compare()["estado"], "ESPERAR")

    def test_stale_capture_or_disconnect_discards_proposal(self):
        self.compare()
        self.now = .6
        self.assertEqual(compare_assignments(self.state)["estado"], "ESPERAR")
        self.state.disconnect()
        self.assertEqual(compare_assignments(self.state)["estado"], "ESPERAR")

    def test_outside_depot_cannot_be_used(self):
        self.message["depots"][0]["col"] = 1000
        self.assertEqual(self.compare()["estado"], "ESPERAR")

    def test_reproducibility_and_no_worse_than_nearest_under_same_model(self):
        first = run_comparison(25, 123)
        second = run_comparison(25, 123)
        self.assertEqual(first, second)
        self.assertEqual(first["mejoras_en_el_modelo"] + first["empates_en_el_modelo"], 25)
        self.assertLessEqual(first["carga_maxima_media_equilibrado_mm"], first["carga_maxima_media_cercano_mm"])

    def test_zero_cost_does_not_divide_by_zero(self):
        for group in ("rovers", "cubes", "depots"):
            for entity in self.message[group]:
                entity.update(col=20, row=20)
        result = self.compare()
        self.assertEqual(result["cercano"]["carga_maxima_mm"], 0)
        self.assertEqual(result["reduccion_porcentaje"], 0)


if __name__ == "__main__":
    unittest.main()
