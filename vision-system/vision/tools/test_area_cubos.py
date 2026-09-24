"""Regresión de escala de área bajo perspectiva: python -m unittest vision.tools.test_area_cubos."""
import unittest

import cv2
import numpy as np

from vision.detectors.cubos import area_cara_local_px, _tabla_color


class Homografia:
    def __init__(self, matrix):
        self.matrix = np.array(matrix, dtype=np.float64)

    def a_pixeles(self, points):
        return cv2.perspectiveTransform(np.asarray(points, dtype=np.float64).reshape(-1, 1, 2), self.matrix).reshape(-1, 2)

    def a_celdas(self, points):
        return cv2.perspectiveTransform(np.asarray(points, dtype=np.float64).reshape(-1, 1, 2), np.linalg.inv(self.matrix)).reshape(-1, 2)


class AreaLocalTests(unittest.TestCase):
    def test_uses_both_axes_not_squared_length(self):
        system = Homografia([[20, 0, 80], [0, 8, 60], [0, 0, 1]])
        # Cara de 3x3 celdas -> 60x24 px. El método antiguo daba 60².
        self.assertAlmostEqual(area_cara_local_px(system, (300, 200), 3), 1440)

    def test_scale_depends_on_position(self):
        system = Homografia([[20, 0, 0], [0, 20, 0], [0, .02, 1]])
        near = system.a_pixeles([[20, 5]])[0]
        far = system.a_pixeles([[20, 35]])[0]
        self.assertGreater(area_cara_local_px(system, near, 3),
                           3 * area_cara_local_px(system, far, 3))


class ColorLookupTests(unittest.TestCase):
    def test_lookup_matches_previous_filter_for_every_lab_pair(self):
        values = np.arange(256, dtype=np.float32) - 128
        a, b = np.meshgrid(values, values, indexing="ij")
        chroma = np.hypot(a, b)
        hue = np.degrees(np.arctan2(b, a)) % 360
        refs = {"red": 39.9, "green": 171.0, "blue": 306.2, "yellow": 103.0}
        # Incluye el filtro configurado y cambios temporales del diagnóstico.
        for minimum, recovery in ((25.4, {"green": 22.0}), (40, {}),
                                  (30, {"green": 18, "blue": 23})):
            expected = chroma >= minimum
            for color, threshold in recovery.items():
                distance = np.abs((hue - refs[color] + 180) % 360 - 180)
                closest = np.ones(hue.shape, dtype=bool)
                for other, reference in refs.items():
                    if other != color:
                        closest &= distance <= np.abs((hue - reference + 180) % 360 - 180)
                expected |= (chroma >= threshold) & (distance <= 20) & closest
            actual = _tabla_color(minimum, tuple(sorted(recovery.items())), tuple(sorted(refs.items())), 20)
            np.testing.assert_array_equal(actual, expected.astype(np.uint8))
            self.assertFalse(actual.flags.writeable)


if __name__ == "__main__":
    unittest.main()
