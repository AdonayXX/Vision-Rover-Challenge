import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "codigos"))

from transporte import (
    decidir_movimiento_hacia,
    destino_valido_para_cubo,
    distancia_mm,
    objetivo_deposito,
    punto_detras_del_cubo,
)


class TransporteGeometryTests(unittest.TestCase):
    def setUp(self):
        self.grid = {"cols": 43, "rows": 43, "cell_mm": 20}

    def test_punto_detras_horizontal(self):
        point = punto_detras_del_cubo(
            {"col": 20, "row": 20}, {"col": 30, "row": 20}, 100, 20
        )
        self.assertAlmostEqual(point["col"], 15)
        self.assertAlmostEqual(point["row"], 20)

    def test_punto_detras_vertical_respeta_row(self):
        point = punto_detras_del_cubo(
            {"col": 20, "row": 20}, {"col": 20, "row": 10}, 100, 20
        )
        self.assertAlmostEqual(point["col"], 20)
        self.assertAlmostEqual(point["row"], 25)

    def test_distancia_usa_escala(self):
        self.assertAlmostEqual(
            distancia_mm({"col": 0, "row": 0}, {"col": 3, "row": 4}, 20), 100
        )

    def test_destino_con_margen_para_cubo(self):
        self.assertTrue(destino_valido_para_cubo({"col": 21, "row": 21}, self.grid, 60))
        self.assertFalse(destino_valido_para_cubo({"col": 0, "row": 0}, self.grid, 60))

    def test_decision_gira_y_luego_avanza(self):
        pose = {"col": 10, "row": 10, "theta": 90}
        target = {"col": 20, "row": 10}
        decision = decidir_movimiento_hacia(pose, target, 20)
        self.assertEqual(decision["accion"], "GIRAR")
        pose["theta"] = 0
        self.assertEqual(decidir_movimiento_hacia(pose, target, 20)["accion"], "AVANZAR")

    def test_objetivo_deposito_por_identidad(self):
        message = {"depots": [
            {"color": "blue", "col": 1, "row": 2},
            {"color": "red", "col": 3, "row": 4},
        ]}
        self.assertEqual(objetivo_deposito(message, "red"), {"col": 3.0, "row": 4.0})


if __name__ == "__main__":
    unittest.main()
