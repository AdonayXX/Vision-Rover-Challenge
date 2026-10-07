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

    def test_hidden_cube_counts_only_if_the_referee_says_so(self):
        # Cancha 3-oct: un rover tapaba un cubo ya sacado de su zona; con su
        # última posición vista la cuenta propia lo daba por entregado y nadie
        # volvía a buscarlo. Tapado (edad > 500 ms) sólo vale in_depot.
        dentro = dict(TRES[0], col=39.25)                         # en el centro de su zona
        m = mensaje(self.ROVERS[:1], [dentro] + TRES[1:])
        for cubo in m["cubes"]:
            cubo["in_depot"] = False
        self.assertNotIn("red", repartir(m, 10))                  # visto ahora: cuenta propia
        m["cubes"][0]["age_ms"] = 2000
        self.assertIn("red", repartir(m, 10))                     # tapado y el árbitro no lo cuenta
        m["cubes"][0]["in_depot"] = True
        self.assertNotIn("red", repartir(m, 10))

    def test_referee_verdict_counts_as_delivered(self):
        # v3: el árbitro tiene 2,5 mm de holgura; si dice in_depot, ya está.
        casi = dict(TRES[0], col=39.25 - 1.7)                  # 34 mm: afuera por la cuenta propia
        m = mensaje(self.ROVERS[:1], [casi] + TRES[1:])
        self.assertIn("red", repartir(m, 10))
        m["cubes"][0]["in_depot"] = True
        self.assertEqual(sorted(repartir(m, 10)), ["blue", "green"])

    def test_cube_pushed_from_inside_another_depot_goes_first(self):
        # Generador oficial, D=0,5-0,8 (y cancha 6-oct 20:58): el rover que
        # empuja el rojo se pone junto a la zona verde; con el verde ya
        # entregado, o no hay sitio o la horquilla lo saca. El rojo va antes.
        from ronda import _buscar, antes
        cubos = [{"color": "red", "col": 24.0, "row": 8.0}, {"color": "green", "col": 10.0, "row": 20.0},
                 {"color": "blue", "col": 15.0, "row": 30.0}]
        m = mensaje(self.ROVERS[:1], cubos)
        c = {k["color"]: _buscar(m["cubes"], "color", k["color"]) for k in cubos}
        z = {k: _buscar(m["depots"], "color", k) for k in c}
        self.assertEqual(antes(c, z, CELL), [("red", "green")])
        solo = repartir(m, 10)
        self.assertLess(solo.index("red"), solo.index("green"), solo)
        # De a dos (por turnos el 10 va primero): el rojo no queda después del verde.
        a, b = repartir(mensaje(self.ROVERS, cubos), 10), repartir(mensaje(self.ROVERS, cubos), 11)
        self.assertEqual(sorted(a + b), ["blue", "green", "red"])
        self.assertTrue(a and b)                                      # 12.2.13
        self.assertLess((a + b).index("red"), (a + b).index("green"), (a, b))

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

    def test_mission_and_planner_are_loaded_before_the_round(self):
        # En la placa cargar LlevarCubo y reservar el A* pide mucha RAM: se
        # hace en IDLE/READY, quieto, y no al arrancar la ronda (cancha 2-oct).
        sim = simulador((5.0, 21.5, 0.0), TRES)
        sim.fase = "IDLE"
        modelo, motores = ModeloRover(), Motores(sim)
        creados = []

        def fabrica():
            creados.append(LlevarCubo(sim.vision, modelo, motores, 10, reloj=sim.reloj_placa))
            return creados[-1]
        misiones = Misiones(IrAPunto(sim.vision, modelo, motores, 10, reloj=sim.reloj_placa),
                            fabrica_llevar=fabrica)
        ronda = Ronda(sim.vision, misiones, 10, reloj=sim.reloj_placa)
        misiones.ronda = ronda
        correr(sim, ronda, misiones, 500)
        self.assertEqual(len(creados), 1)
        self.assertIsNotNone(creados[0].planner)
        self.assertIsNotNone(creados[0].planner._n)                 # búferes ya reservados
        self.assertTrue(all(i == 0 and d == 0 for t, i, d in sim.ordenes))
        sim.fase = "RUNNING"
        correr(sim, ronda, misiones, 120000, True)
        self.assertEqual(ronda.estado, COMPLETA, ronda.informe())
        self.assertEqual(len(creados), 1)                           # la misma, sin recargar

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

    def test_event_log_is_kept_and_shown_only_after_the_round(self):
        # Cancha 4-oct: rondas sin ver_ronda (como en competencia) y el rover
        # quieto 13 s sin saber por qué. Anota lo que hace y lo entrega al
        # terminar la ronda, no durante (cada SENSORS gasta RAM de red).
        sim = simulador((5.0, 21.5, 0.0), TRES)
        ronda, misiones, motores = armar(sim)
        correr(sim, ronda, misiones, 120000, True)
        correr(sim, ronda, misiones, sim.t + 200)                   # una vuelta más: se anota
        self.assertEqual(ronda.estado, COMPLETA)
        self.assertNotIn("eventos", ronda.informe())                 # en plena ronda, no
        texto = "\n".join(ronda.eventos)
        for esperado in ("RUNNING", "lleva", "ENTREGADO", "COMPLETA"):
            self.assertIn(esperado, texto)
        self.assertTrue(ronda.eventos[0].split()[0] in ("pre", "0.0"), ronda.eventos[0])
        sim.fase = "FINISHED"
        correr(sim, ronda, misiones, sim.t + 500)
        self.assertEqual(ronda.estado, TERMINADA)
        self.assertEqual(ronda.informe()["eventos"], ronda.eventos)  # terminada, sí
        self.assertTrue(any("fin de la ronda" in e for e in ronda.eventos[-3:]), ronda.eventos[-3:])
        self.assertLessEqual(len(ronda.eventos), ronda.max_eventos)

    def test_board_asks_for_a_reset_only_between_rounds(self):
        # Rondas seguidas sin apagar dejaban la placa sin RAM ni red (3-oct):
        # tras una ronda jugada, al volver la visión a IDLE/READY, la placa
        # se reinicia. Al encenderla (IDLE de entrada) no.
        sim = simulador((5.0, 21.5, 0.0), TRES)
        sim.fase = "IDLE"
        ronda, misiones, motores = armar(sim)
        correr(sim, ronda, misiones, 1000)
        self.assertFalse(ronda.pedir_reinicio)
        sim.fase = "RUNNING"
        correr(sim, ronda, misiones, 4000)
        sim.fase = "FINISHED"
        correr(sim, ronda, misiones, 4500)
        self.assertEqual(ronda.estado, TERMINADA)
        self.assertFalse(ronda.pedir_reinicio)
        sim.fase = "READY"
        correr(sim, ronda, misiones, 5000)
        self.assertTrue(ronda.pedir_reinicio)

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

    def test_network_cuts_are_not_failed_attempts(self):
        # Cancha 4-oct: un corte de Wi-Fi o de la visión aborta la misión
        # (wifi_perdido, vision_vieja). No falló el cubo: con dos cortes en el
        # mismo cubo la ronda lo daba por perdido.
        sim = simulador((5.0, 21.5, 0.0), TRES)
        ronda, misiones, motores = armar(sim, estrategia="todos")
        cortes = ["wifi_perdido", "vision_vieja", "rover_no_visible"]
        original = misiones.llevar_en_ronda

        def se_corta_la_red(color):
            original(color)
            if cortes:
                misiones.cubo.detener(cortes.pop(0))
        misiones.llevar_en_ronda = se_corta_la_red
        correr(sim, ronda, misiones, 600000, True)
        self.assertEqual(ronda.estado, COMPLETA)
        self.assertEqual(ronda.intentos, {})
        self.assertEqual(sorted(ronda.hechos), ["blue", "green", "red"])


if __name__ == "__main__":
    unittest.main()
