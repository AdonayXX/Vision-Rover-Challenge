"""Orientación del frente por ID, sin conectar cámara ni motores."""
from dataclasses import replace
import json
from pathlib import Path
import tempfile
import unittest

from vision.configuracion import cargar_config, CONFIG_POR_DEFECTO, revisar_config, DesfaseMarcadorRobot
from vision.detectors.rovers import PoseMarcador, aplicar_desfases


class DesfaseRoverTests(unittest.TestCase):
    def setUp(self):
        self.cfg = cargar_config()
        self.ajustes = self.cfg.deteccion_rovers

    def test_montaje_confirmado_rover10(self):
        pose = PoseMarcador(10, 21.89, 20.93, 89.2)
        rover = aplicar_desfases(pose, self.ajustes, 20)
        self.assertAlmostEqual(rover.theta_grados, 179.2)
        self.assertEqual((rover.col, rover.row), (pose.col, pose.row))
        self.assertEqual(rover.marcador, pose)

    def test_no_modifica_rover11(self):
        rover = aplicar_desfases(PoseMarcador(11, 20, 20, 89.2), self.ajustes, 20)
        self.assertAlmostEqual(rover.theta_grados, 89.2)

    def test_giros_y_cruce_cero(self):
        for marcador, frente in ((0, 90), (90, 180), (180, 270), (270, 0), (350, 80)):
            with self.subTest(marcador=marcador):
                rover = aplicar_desfases(PoseMarcador(10, 20, 20, marcador), self.ajustes, 20)
                self.assertAlmostEqual(rover.theta_grados, frente)

    def test_especifico_reemplaza_general(self):
        ajustes = replace(self.ajustes, desfase_angular_grados=30)
        self.assertEqual(ajustes.desfase_angular_para(10), 90)
        self.assertEqual(ajustes.desfase_angular_para(11), 30)

    def test_posicion_se_rota_con_frente_corregido(self):
        ajustes = replace(self.ajustes, desfase_posicion=DesfaseMarcadorRobot(20, 0))
        rover = aplicar_desfases(PoseMarcador(10, 20, 20, 90), ajustes, 20)
        self.assertAlmostEqual(rover.col, 19)
        self.assertAlmostEqual(rover.row, 20)

    def test_config_antigua_sigue_funcionando(self):
        datos = json.loads(Path(CONFIG_POR_DEFECTO).read_text(encoding="utf-8"))
        datos["deteccion_rovers"].pop("desfase_angular_por_id")
        with tempfile.TemporaryDirectory() as carpeta:
            ruta = Path(carpeta) / "config.json"
            ruta.write_text(json.dumps(datos), encoding="utf-8")
            cfg = cargar_config(str(ruta))
        self.assertEqual(cfg.deteccion_rovers.desfase_angular_para(10), 0)

    def test_rechaza_ids_y_angulos_invalidos(self):
        for pares in (((0, 90),), ((99, 90),), ((10, 90), (10, 0)),
                      ((10, float("nan")),), ((10, float("inf")),), ((10, 361),)):
            with self.subTest(pares=pares):
                cfg = replace(self.cfg, deteccion_rovers=replace(
                    self.ajustes, desfase_angular_por_id=pares))
                self.assertIsNotNone(revisar_config(cfg))


if __name__ == "__main__":
    unittest.main()
