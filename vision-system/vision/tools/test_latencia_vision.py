"""Regresión del detector rápido, sin cámara, TCP ni motores."""
from pathlib import Path
import unittest
from unittest.mock import patch

import cv2
import numpy as np

from vision.configuracion import cargar_config, diccionario_aruco, RoverDemo
from vision.geometry.coordenadas import detectar_marcadores_crudo
from vision.sources.generador_sintetico import generar
from vision.sources.fuente import Cuadro
from vision.sistema import procesar, Seguidor, AnclajeCancha, RegistroAdmision, RelojRonda


class DetectorRapidoTests(unittest.TestCase):
    def setUp(self):
        self.cfg = cargar_config()

    def detectar(self, imagen, rapido=True, requeridos=()):
        return detectar_marcadores_crudo(imagen, "DICT_4X4_50", "subpixel",
                                        usar_aruco3=rapido, ids_requeridos=requeridos)

    def test_conserva_duplicados(self):
        imagen = np.full((300, 600), 255, np.uint8)
        marcador = cv2.aruco.generateImageMarker(diccionario_aruco("DICT_4X4_50"), 10, 96)
        imagen[80:176, 80:176] = marcador
        imagen[80:176, 380:476] = marcador
        self.assertEqual([i for i, _ in self.detectar(imagen)], [10, 10])

    def test_respaldo_si_falta_un_id_requerido(self):
        esquinas = (np.array([[[20, 20], [50, 20], [50, 50], [20, 50]]], np.float32),)
        with patch("vision.geometry.coordenadas.cv2.aruco.ArucoDetector") as detector:
            detector.return_value.detectMarkers.side_effect = [
                ((), None, ()), (esquinas, np.array([[10]]), ())]
            encontrados = self.detectar(np.full((80, 80), 255, np.uint8), requeridos={10})
            self.assertEqual(encontrados[0][0], 10)
            self.assertEqual(detector.call_count, 2)
            self.assertTrue(detector.call_args_list[0].args[1].useAruco3Detection)
            self.assertFalse(detector.call_args_list[1].args[1].useAruco3Detection)

    def test_imagen_vacia_no_inventa_marcadores(self):
        self.assertEqual(self.detectar(np.full((240, 320), 255, np.uint8)), ())

    def test_precision_en_varias_orientaciones(self):
        for angulo in (0, 45, 90, 179, 270):
            with self.subTest(angulo=angulo):
                rovers = (RoverDemo(id=10, col=20, row=20, theta=angulo),)
                imagen, _ = generar(self.cfg, rovers=rovers, cubos=())
                clasico = dict(self.detectar(imagen, False))
                rapido = dict(self.detectar(imagen, requeridos={0, 1, 2, 3, 10}))
                self.assertTrue({0, 1, 2, 3, 10}.issubset(rapido))
                for id_ in (0, 1, 2, 3, 10):
                    np.testing.assert_allclose(rapido[id_], clasico[id_], atol=.15)

    def test_pipeline_conserva_timestamp_de_captura(self):
        imagen, verdad = generar(self.cfg)
        tiempos = {}
        _, estado = procesar(Cuadro(imagen, 123456, 1), self.cfg, verdad.camara.matriz,
                             "IDLE", RelojRonda(), Seguidor(self.cfg), AnclajeCancha(self.cfg),
                             set(), [], [], RegistroAdmision(self.cfg), [], tiempos)
        self.assertEqual(estado.ts_ms, 123456)
        self.assertEqual(set(tiempos), {"marcadores", "cubos", "proceso"})
        self.assertGreaterEqual(tiempos["proceso"], tiempos["marcadores"] + tiempos["cubos"])

    def test_captura_real_si_disponible(self):
        ruta = Path(__file__).resolve().parents[1] / "mediciones/diagnostico_cubos_actual.png"
        if not ruta.exists():
            self.skipTest("captura de la cancha local no versionada")
        imagen = cv2.imread(str(ruta))
        clasico = self.detectar(imagen, False)
        rapido = dict(self.detectar(imagen, requeridos={0, 1, 2, 3, 10, 11}))
        self.assertEqual(set(rapido), {0, 1, 2, 3, 10, 11})
        for id_, esquinas in rapido.items():
            # El detector anterior también entrega un falso ID 10 en el tablero.
            opciones = [p for i, p in clasico if i == id_]
            self.assertLess(min(np.max(np.abs(p - esquinas)) for p in opciones), .15)


if __name__ == "__main__":
    unittest.main()
