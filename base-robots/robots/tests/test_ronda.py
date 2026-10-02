"""Incremento 3: la ronda autónoma (fase de la visión -> reparto -> cubos de a uno)."""
import math
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "codigos"))
from test_autonomia import CELL, DEPOSITOS, Motores
from test_llevar_cubo import entregado, simulador
from autonomia import IrAPunto, Misiones
from llevar_cubo import LlevarCubo
from modelo_rover import ModeloRover
from ronda import COMPLETA, CORRIENDO, DETENIDA, ESPERANDO, TERMINADA, Ronda, repartir
from sesion_comandos import CommandSession

TRES = [{"color": "red", "col": 27.0, "row": 21.5},
        {"color": "green", "col": 17.0, "row": 13.0},
        {"color": "blue", "col": 17.0, "row": 30.0}]


def mensaje(rovers, cubos=TRES, fase="RUNNING"):
    return {"phase": fase, "seq": 1, "ts_ms": 0, "grid": {"cols": 43, "rows": 43, "cell_mm": CELL},
            "cube_side": 3.0, "depot_size": {"length": 10.0, "depth": 7.5}, "obstacles": [],
            "depots": [dict(d) for d in DEPOSITOS], "cubes": [dict(c, age_ms=0) for c in cubos],
            "rovers": [dict(r, theta=0.0, age_ms=0) for r in rovers]}


def armar(sim, robot_id=10, **opciones):
    modelo, motores = ModeloRover(), Motores(sim)
    misiones = Misiones(IrAPunto(sim.vision, modelo, motores, robot_id, reloj=sim.reloj_placa),
                        LlevarCubo(sim.vision, modelo, motores, robot_id, reloj=sim.reloj_placa))
    ronda = Ronda(sim.vision, misiones, robot_id, reloj=sim.reloj_placa, **opciones)
    misiones.ronda = ronda
    return ronda, misiones, motores


def correr(sim, ronda, misiones, hasta_ms, hasta_completar=False):
    while sim.t < hasta_ms:
        sim.paso()
        ronda.tick()
        misiones.tick()
        if hasta_completar and ronda.estado == COMPLETA and not misiones.activa:
            break


class RepartoTests(unittest.TestCase):
    ROVERS = [{"id": 10, "col": 4.0, "row": 17.5}, {"id": 11, "col": 4.0, "row": 25.5}]

    def test_alone_takes_all_three(self):
        self.assertEqual(sorted(repartir(mensaje(self.ROVERS[:1]), 10)), ["blue", "green", "red"])

    def test_two_rovers_split_without_overlap_and_both_work(self):
        a = repartir(mensaje(self.ROVERS), 10)
        b = repartir(mensaje(self.ROVERS), 11)
        self.assertEqual(sorted(a + b), ["blue", "green", "red"])     # nadie repite ni deja uno
        self.assertTrue(a and b)                                      # 12.2.13: al menos uno cada uno

    def test_both_rovers_agree_despite_camera_noise_when_there_is_no_tie(self):
        # Cada rover lee su propio mensaje: la misma cancha con ruido de 1 mm.
        # Sin comunicación sólo se garantiza el acuerdo si no hay casi-empate
        # (medido: 1-3 % de canchas al azar empatan; las cubre la ayuda).
        claros = [{"color": "red", "col": 30.0, "row": 12.0},
                  {"color": "green", "col": 12.0, "row": 9.0},
                  {"color": "blue", "col": 14.0, "row": 33.0}]
        ruido = [dict(r, col=r["col"] + .05, row=r["row"] - .05) for r in self.ROVERS]
        cubos = [dict(c, col=c["col"] - .05) for c in claros]
        a, b = repartir(mensaje(self.ROVERS, claros), 10), repartir(mensaje(ruido, cubos), 11)
        self.assertEqual(sorted(a + b), ["blue", "green", "red"])
        self.assertEqual(a, repartir(mensaje(ruido, cubos), 10))

    def test_delivered_cubes_are_not_assigned(self):
        cubos = [dict(TRES[0], col=39.25)] + TRES[1:]                 # el rojo ya en su zona
        a, b = repartir(mensaje(self.ROVERS, cubos), 10), repartir(mensaje(self.ROVERS, cubos), 11)
        self.assertEqual(sorted(a + b), ["blue", "green"])

    def test_single_pending_cube_goes_to_exactly_one_rover(self):
        cubos = [TRES[0], dict(TRES[1], row=3.75, col=21.5), dict(TRES[2], row=39.25, col=21.5)]
        a, b = repartir(mensaje(self.ROVERS, cubos), 10), repartir(mensaje(self.ROVERS, cubos), 11)
        self.assertEqual(sorted(a + b), ["red"])


class RondaTests(unittest.TestCase):
    def test_full_round_alone_waits_for_running_then_delivers_three(self):
        sim = simulador((5.0, 21.5, 0.0), TRES)
        sim.fase = "IDLE"
        ronda, misiones, motores = armar(sim)
        correr(sim, ronda, misiones, 3000)
        self.assertEqual(ronda.estado, ESPERANDO)
        self.assertTrue(all(i == 0 and d == 0 for t, i, d in sim.ordenes))   # quieto en IDLE (8.5)
        sim.fase = "RUNNING"
        correr(sim, ronda, misiones, 600000, True)
        self.assertEqual(ronda.estado, COMPLETA, ronda.informe())
        for color in ("red", "green", "blue"):
            self.assertTrue(entregado(sim, color)[0], color)
        self.assertLess(sim.t, 120000)

    def test_end_of_round_stops_everything_and_rearms(self):
        sim = simulador((5.0, 21.5, 0.0), TRES)
        ronda, misiones, motores = armar(sim)
        correr(sim, ronda, misiones, 6000)
        self.assertTrue(misiones.activa)
        sim.fase = "FINISHED"
        correr(sim, ronda, misiones, 6500)
        self.assertEqual(ronda.estado, TERMINADA)
        self.assertFalse(misiones.activa)
        self.assertIsNone(motores.mode)
        sim.fase = "IDLE"
        correr(sim, ronda, misiones, 7000)
        self.assertEqual(ronda.estado, ESPERANDO)                     # lista para otra ronda

    def test_pc_watching_does_not_disturb_but_stop_does(self):
        sim = simulador((5.0, 21.5, 0.0), TRES)
        ronda, misiones, motores = armar(sim)
        correr(sim, ronda, misiones, 6000)
        self.assertEqual(ronda.estado, CORRIENDO)
        sesion = CommandSession(motores, mission=misiones)             # la PC se conecta
        self.assertTrue(sesion.process_command("SENSORS"))
        self.assertTrue(misiones.activa)                               # sigue sola
        self.assertIn("ronda", misiones.informe())
        sesion.process_command("STOP")
        self.assertEqual(ronda.estado, DETENIDA)
        self.assertFalse(misiones.activa)

    def test_with_a_partner_only_takes_its_share(self):
        sim = simulador((4.0, 17.5, 0.0), TRES)
        sim.companeros = [{"id": 11, "col": 4.0, "row": 25.5, "theta": 0.0}]
        ronda, misiones, motores = armar(sim)
        correr(sim, ronda, misiones, 3000)
        propios = list(ronda.mis_cubos)
        self.assertTrue(0 < len(propios) < 3)
        correr(sim, ronda, misiones, 300000, True)
        self.assertEqual(ronda.estado, COMPLETA)
        for color in propios:
            self.assertTrue(entregado(sim, color)[0], color)
        ajenos = [c for c in ("red", "green", "blue") if c not in propios]
        self.assertTrue(all(c not in sim.empujados for c in ajenos))   # lo del compañero, ni tocarlo

    def test_cube_nobody_took_is_taken_after_finishing(self):
        # Repartos incompatibles (casi-empate + ruido): un cubo sin dueño. El
        # rover que terminó lo suyo lo toma si 30 s nadie se le acerca.
        sim = simulador((4.0, 17.5, 0.0), TRES)
        sim.companeros = [{"id": 11, "col": 4.0, "row": 25.5, "theta": 0.0}]   # quieto: no hace nada
        ronda, misiones, motores = armar(sim, sin_dueno_ms=30000, ayuda_ms=10 ** 9)
        correr(sim, ronda, misiones, 3000)
        propios = list(ronda.mis_cubos)
        correr(sim, ronda, misiones, 200000)                         # sin cortar al completar lo suyo
        self.assertEqual(ronda.estado, COMPLETA)
        self.assertGreater(len(ronda.mis_cubos), len(propios))       # tomó lo abandonado
        for color in ronda.mis_cubos:
            self.assertTrue(entregado(sim, color)[0], color)

    def test_failed_cube_is_retried_after_the_others(self):
        sim = simulador((5.0, 21.5, 0.0), TRES)
        ronda, misiones, motores = armar(sim, estrategia="todos")
        primero = []
        original = misiones.llevar_en_ronda

        def falla_la_primera_vez(color):
            original(color)
            if not primero:
                primero.append(color)
                misiones.cubo.detener("falla_simulada")
        misiones.llevar_en_ronda = falla_la_primera_vez
        correr(sim, ronda, misiones, 600000, True)
        self.assertEqual(ronda.estado, COMPLETA)
        self.assertEqual(ronda.intentos, {primero[0]: 1})
        self.assertEqual(sorted(ronda.hechos), ["blue", "green", "red"])


if __name__ == "__main__":
    unittest.main()
