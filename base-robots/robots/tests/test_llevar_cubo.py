"""Incremento 2: llevar un cubo a su zona, contra el simulador con retrasos reales.

El simulador (test_autonomia.Simulador) empuja los cubos que quedan frente al
rover. La misión sólo ve lo que publica la visión simulada, con su latencia.
"""
import math
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "codigos"))
from test_autonomia import CELL, DEPOSITOS, Motores, Simulador
from autonomia import IrAPunto, Misiones
from command_protocol import parse_command
from llevar_cubo import (ABORTADO, ENTREGADO, LlevarCubo, cubo_en_su_zona, relativo,
                         punto_detras)
from modelo_rover import ModeloRover
from sesion_comandos import CommandSession

ZONA = {"length": 10.0, "depth": 7.5}
GRID = {"cols": 43, "rows": 43, "cell_mm": CELL}


def entregado(sim, color):
    cubo = next(c for c in sim.cubos if c["color"] == color)
    meta = next(d for d in DEPOSITOS if d["color"] == color)
    return cubo_en_su_zona(cubo, meta, ZONA, GRID, 3.0)


def simulador(pose, cubos, real=None, frente_mm=105.0, **extra):
    sim = Simulador(real or ModeloRover(), pose=pose, **extra)
    sim.frente_mm = frente_mm
    sim.cubos = [dict(c, age_ms=0) for c in cubos]
    return sim


def correr(mision, sim, hasta_ms=150000):
    while sim.t < hasta_ms and mision.activa:
        sim.paso()
        mision.tick()
    return mision.estado


def llevar(sim, color, creido=None, **parametros):
    mision = LlevarCubo(sim.vision, creido or ModeloRover(), Motores(sim), 10,
                        reloj=sim.reloj_placa, **parametros)
    mision.iniciar(color)
    return mision


class GeometriaTests(unittest.TestCase):
    def test_zone_rule_matches_contract_examples(self):
        verde = {"color": "green", "col": 21.5, "row": 3.75}
        self.assertEqual(cubo_en_su_zona({"col": 21.48, "row": 3.762}, verde, ZONA, GRID, 3.0), (True, 0.0))
        adentro, falta = cubo_en_su_zona({"col": 21.48, "row": 5.5}, verde, ZONA, GRID, 3.0)
        self.assertFalse(adentro)
        self.assertAlmostEqual(falta, .1213, places=3)

    def test_point_behind_is_on_the_push_line(self):
        p = punto_detras({"col": 20, "row": 20}, {"col": 39.25, "row": 20}, 160, CELL)
        self.assertAlmostEqual(p["col"], 12)
        self.assertAlmostEqual(p["row"], 20)

    def test_relative_frame_left_is_up_when_facing_right(self):
        adelante, izquierda = relativo({"col": 10, "row": 10, "theta": 0}, {"col": 12, "row": 9}, CELL)
        self.assertAlmostEqual(adelante, 40)
        self.assertAlmostEqual(izquierda, 20)


class LlevarCuboTests(unittest.TestCase):
    def assert_entregado(self, mision, sim, color):
        self.assertEqual(mision.estado, ENTREGADO, mision.informe())
        self.assertTrue(entregado(sim, color)[0], (sim.cubos, mision.informe()))

    def test_straight_push_to_red_zone(self):
        sim = simulador((10.0, 21.0, 0.0), [{"color": "red", "col": 24.0, "row": 21.5}])
        mision = llevar(sim, "red")
        correr(mision, sim)
        self.assert_entregado(mision, sim, "red")
        self.assertLess(sim.t, 60000)
        # Al terminar se aparta: el cubo queda libre.
        rojo = sim.cubos[0]
        self.assertGreater(math.hypot(rojo["col"] - sim.col, rojo["row"] - sim.row) * CELL, 140)

    def test_goes_around_to_get_behind_the_cube(self):
        # El cubo verde va hacia arriba: hay que ponerse DEBAJO de él.
        sim = simulador((10.0, 12.0, 0.0), [{"color": "green", "col": 20.0, "row": 14.0}])
        mision = llevar(sim, "green")
        correr(mision, sim)
        self.assert_entregado(mision, sim, "green")

    def test_detours_other_cube_without_touching_it(self):
        sim = simulador((8.0, 30.0, 0.0), [{"color": "green", "col": 22.0, "row": 16.0},
                                           {"color": "blue", "col": 16.0, "row": 27.0}])
        azul = dict(sim.cubos[1])
        mision = llevar(sim, "green")
        correr(mision, sim)
        self.assert_entregado(mision, sim, "green")
        self.assertNotIn("blue", sim.empujados)
        self.assertAlmostEqual(sim.cubos[1]["col"], azul["col"])
        self.assertGreaterEqual(mision.replanes, 1)

    def test_model_error_and_closer_contact_than_assumed(self):
        real = ModeloRover(k_lineal=630 * .8, k_giro=715 * 1.15)
        sim = simulador((10.0, 21.0, 0.0), [{"color": "red", "col": 24.0, "row": 19.0}],
                        real=real, frente_mm=92.0)
        mision = llevar(sim, "red")
        correr(mision, sim)
        self.assert_entregado(mision, sim, "red")

    def test_cube_sliding_sideways_is_corrected(self):
        sim = simulador((10.0, 21.0, 0.0), [{"color": "red", "col": 22.0, "row": 21.5}])
        sim.deriva = 0.12                       # 12 mm de lado por cada 100 mm empujados
        mision = llevar(sim, "red")
        correr(mision, sim)
        self.assert_entregado(mision, sim, "red")

    def test_camera_losing_the_pushed_cube_neither_stops_nor_overshoots(self):
        # Como la prueba del 1-oct: el rojo en (23.2, 20.5) y la cámara deja de
        # verlo durante el empuje. Antes el rover paraba y, con la posición
        # vieja, lo pasaba 43 mm del centro (fuera de la zona).
        for nombre, oculto in (
                ("tramo", lambda cubo, sim: 30.0 < cubo["col"] < 36.0),
                ("parpadeo", lambda cubo, sim: cubo["col"] > 28.0 and sim.t % 1000 < 600)):
            sim = simulador((11.0, 20.5, 0.0), [{"color": "red", "col": 23.16, "row": 20.53}])
            sim.oculto = oculto
            mision = llevar(sim, "red")
            correr(mision, sim)
            self.assert_entregado(mision, sim, "red")
            pasado_mm = (sim.cubos[0]["col"] - 39.25) * CELL
            self.assertLess(pasado_mm, 20, nombre)          # nunca más allá del centro
            self.assertEqual(mision.esperas, 0, nombre)      # sin paradas a medio empuje

    def test_starting_against_the_border_first_moves_out(self):
        # La salida del contrato está a 75 mm del borde: menos que el radio + margen.
        sim = simulador((3.75, 21.5, 0.0), [{"color": "red", "col": 22.0, "row": 23.0}])
        mision = llevar(sim, "red")
        correr(mision, sim)
        self.assert_entregado(mision, sim, "red")

    def test_blocked_push_corridor_aborts_without_pushing_into_it(self):
        sim = simulador((10.0, 21.5, 0.0), [{"color": "red", "col": 22.0, "row": 21.5},
                                            {"color": "blue", "col": 31.0, "row": 21.5}])
        mision = llevar(sim, "red")
        correr(mision, sim)
        self.assertEqual(mision.estado, ABORTADO)
        self.assertTrue(mision.motivo.startswith("corredor_bloqueado: cubo blue"), mision.motivo)
        self.assertNotIn("blue", sim.empujados)

    def test_cube_against_the_far_wall_is_moved_out_first(self):
        # Azul a 140 mm de la pared de arriba y su zona abajo: el rover no cabe
        # entre el cubo y la pared, así que primero lo despega empujando de lado.
        sim = simulador((10.0, 25.0, 0.0), [{"color": "blue", "col": 20.0, "row": 7.0}])
        mision = llevar(sim, "blue")
        correr(mision, sim)
        self.assert_entregado(mision, sim, "blue")
        self.assertIn("reubicar", mision.ultimo)

    def test_random_scenes_never_push_another_cube(self):
        import random
        azar = random.Random(3)
        for escena in range(12):
            puntos = []
            while len(puntos) < 4:
                p = (azar.uniform(8, 35), azar.uniform(8, 35))
                if all(math.hypot(p[0] - q[0], p[1] - q[1]) >= 9 for q in puntos):
                    puntos.append(p)
            colores = ["red", "green", "blue"]
            azar.shuffle(colores)
            sim = simulador((puntos[3][0], puntos[3][1], azar.uniform(0, 360)),
                            [{"color": c, "col": p[0], "row": p[1]} for c, p in zip(colores, puntos)],
                            semilla=escena)
            mision = llevar(sim, colores[0])
            correr(mision, sim)
            self.assertEqual(sim.empujados - {colores[0]}, set(), escena)
            if mision.estado == ENTREGADO:
                self.assertTrue(entregado(sim, colores[0])[0], escena)
            else:
                self.assertEqual(mision.estado, ABORTADO, escena)
                self.assertTrue(mision.motivo, escena)

    def test_cube_already_in_zone_is_left_alone(self):
        sim = simulador((20.0, 21.5, 0.0), [{"color": "red", "col": 39.2, "row": 21.5}])
        mision = llevar(sim, "red")
        correr(mision, sim)
        self.assertEqual(mision.estado, ENTREGADO)
        self.assertEqual(sim.empujados, set())
        self.assertLess(sim.t, 3000)

    def test_lost_vision_stops_then_aborts(self):
        sim = simulador((10.0, 21.0, 0.0), [{"color": "red", "col": 24.0, "row": 21.5}])
        mision = llevar(sim, "red")
        sim.sin_vision_desde = 4000
        correr(mision, sim)
        self.assertEqual(mision.estado, ABORTADO)
        self.assertEqual(mision.motivo, "vision_vieja")
        self.assertIsNone(mision.motores.mode)


class SesionLlevarTests(unittest.TestCase):
    def setUp(self):
        self.sim = simulador((10.0, 21.0, 0.0), [{"color": "red", "col": 24.0, "row": 21.5}])
        self.motores = Motores(self.sim)
        modelo = ModeloRover()
        self.misiones = Misiones(IrAPunto(self.sim.vision, modelo, self.motores, 10, reloj=self.sim.reloj_placa),
                                 LlevarCubo(self.sim.vision, modelo, self.motores, 10, reloj=self.sim.reloj_placa))
        self.sesion = CommandSession(self.motores, mission=self.misiones)

    def test_command_parses_only_known_colors(self):
        self.assertEqual(parse_command("LLEVAR|Red")["color"], "red")
        self.assertFalse(parse_command("LLEVAR|purple")["valid"])
        self.assertFalse(parse_command("LLEVAR")["valid"])

    def test_llevar_starts_and_stop_aborts(self):
        self.assertTrue(self.sesion.process_command("LLEVAR|red"))
        self.assertTrue(self.misiones.activa)
        self.assertEqual(self.misiones.informe()["color"], "red")
        self.sesion.process_command("STOP")
        self.assertFalse(self.misiones.activa)
        self.assertEqual(self.misiones.informe()["motivo"], "orden_stop")

    def test_switching_missions_keeps_one_active(self):
        self.sesion.process_command("LLEVAR|red")
        self.sesion.process_command("IR|30|20")
        self.assertEqual(self.misiones.cubo.estado, ABORTADO)
        self.assertTrue(self.misiones.ir.activa)
        self.assertEqual(self.misiones.tick, self.misiones.ir.tick)

    def test_mission_module_is_loaded_on_first_use_and_failure_is_reported(self):
        modelo = ModeloRover()
        creadas = []

        def fabrica():
            creadas.append(1)
            return LlevarCubo(self.sim.vision, modelo, self.motores, 10, reloj=self.sim.reloj_placa)

        misiones = Misiones(IrAPunto(self.sim.vision, modelo, self.motores, 10), fabrica_llevar=fabrica)
        self.assertEqual(creadas, [])                   # nada al arrancar
        sesion = CommandSession(self.motores, mission=misiones)
        self.assertTrue(sesion.process_command("LLEVAR|red"))
        self.assertTrue(sesion.process_command("LLEVAR|green"))
        self.assertEqual(creadas, [1])                  # una sola vez

        def sin_memoria():
            raise MemoryError("memory allocation failed")

        rota = Misiones(IrAPunto(self.sim.vision, modelo, self.motores, 10), fabrica_llevar=sin_memoria)
        sesion = CommandSession(self.motores, mission=rota)
        self.assertFalse(sesion.process_command("LLEVAR|red"))   # ERROR, la sesión sigue
        self.assertTrue(sesion.process_command("PING"))
        self.assertIn("MemoryError", rota.informe()["error_carga"])

    def test_full_delivery_through_the_session(self):
        self.sesion.process_command("LLEVAR|red")
        while self.sim.t < 150000 and self.misiones.activa:
            self.sim.paso()
            self.misiones.tick()
        self.assertEqual(self.misiones.informe()["estado"], ENTREGADO)


if __name__ == "__main__":
    unittest.main()
