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


class Ultrasonido:
    """Lo que SensoresRover expone: distancia al cubo que está DELANTE (±25 mm de lado).

    Pegado a las paletas mide ~25 mm, como en la cancha (25,4 mm el 1-oct).
    """
    def __init__(self, sim):
        self.sim, self.distance_at = sim, 0.0

    @property
    def distance(self):
        sim, mejor = self.sim, 400.0
        th = math.radians(sim.theta)
        for cubo in sim.cubos:
            dc, dr = (cubo["col"] - sim.col) * CELL, (cubo["row"] - sim.row) * CELL
            adelante, lateral = dc * math.cos(th) - dr * math.sin(th), -dc * math.sin(th) - dr * math.cos(th)
            if adelante > 0 and abs(lateral) < 25:
                mejor = min(mejor, adelante - (sim.frente_mm or 105) + 25)
        return mejor if mejor >= 20 else None     # el HC-SR04 no mide por debajo de 20 mm

    def age(self, momento):
        return 0


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

    def test_cube_behind_the_rover_is_circled_and_delivered(self):
        # Prueba del 1-oct: rover entre el cubo y su zona, mirando a la zona.
        for real in (ModeloRover(), ModeloRover(k_lineal=630 * .8, k_giro=715 * .6)):
            sim = simulador((28.0, 21.5, 0.0), [{"color": "red", "col": 20.0, "row": 21.5}], real=real)
            mision = llevar(sim, "red")
            correr(mision, sim)
            self.assert_entregado(mision, sim, "red")
            self.assertLess(sim.t, 40000)

    def test_cube_slipping_while_camera_flickers_is_noticed(self):
        # Con la imagen del cubo vieja, el desvío se mide contra la pose del
        # rover de ESE instante: si resbala, retrocede y vuelve a alinear en
        # vez de seguir empujando un cubo que ya no está delante.
        # Y nunca da por entregado un cubo con una imagen anterior a la parada.
        for oculto_ms in (600, 800, 900):
            sim = simulador((10.0, 21.0, 0.0), [{"color": "red", "col": 21.0, "row": 21.5}])
            sim.deriva = 0.3
            sim.oculto = lambda cubo, sim, ms=oculto_ms: sim.t % 1000 < ms
            mision = llevar(sim, "red")
            correr(mision, sim)
            self.assert_entregado(mision, sim, "red")

    def test_ultrasound_notices_a_hidden_cube_slipping_away(self):
        # Peor caso de la cancha: pegado al rover la cámara NO ve el cubo y el
        # cubo resbala. Sin sensor se empuja a ciegas y se pierde; con el
        # ultrasonido se nota que delante ya no hay nada y se vuelve a empezar.
        resultados = {}
        for con_sensor in (False, True):
            sim = simulador((10.0, 21.0, 0.0), [{"color": "red", "col": 21.0, "row": 21.5}])
            sim.deriva = 0.5
            sim.oculto = lambda cubo, sim: math.hypot(cubo["col"] - sim.col, cubo["row"] - sim.row) * CELL < 140
            retrocesos = set()
            mision = llevar(sim, "red", sensores=Ultrasonido(sim) if con_sensor else None,
                            us_libre_mm=80.0)       # la alarma viene apagada
            while sim.t < 150000 and mision.activa:
                sim.paso()
                mision.tick()
                retrocesos.add(mision.ultimo.get("retroceso"))
            resultados[con_sensor] = mision.estado == ENTREGADO and entregado(sim, "red")[0]
            if con_sensor:
                self.assertIn("ultrasonido_sin_cubo", retrocesos)
        self.assertEqual(resultados, {False: False, True: True})

    def test_ultrasound_that_never_sees_the_cube_is_ignored(self):
        # Cancha 1-oct: en marcha el eco pasaba por encima del cubo y daba
        # retrocesos en falso. Si nunca lo vio pegado, no se le hace caso.
        class Ciego:
            distance, distance_at = 300.0, 0.0

            def age(self, momento):
                return 0
        sim = simulador((10.0, 21.0, 0.0), [{"color": "red", "col": 24.0, "row": 21.5}])
        mision = llevar(sim, "red", sensores=Ciego(), us_libre_mm=80.0)
        retrocesos = set()
        while sim.t < 150000 and mision.activa:
            sim.paso()
            mision.tick()
            retrocesos.add(mision.ultimo.get("retroceso"))
        self.assert_entregado(mision, sim, "red")
        self.assertNotIn("ultrasonido_sin_cubo", retrocesos)

    def test_ultrasound_failures_never_stop_the_mission(self):
        class Roto:
            distance_at = 0.0

            @property
            def distance(self):
                raise OSError("sin eco")

            def age(self, momento):
                return 0
        sim = simulador((10.0, 21.0, 0.0), [{"color": "red", "col": 24.0, "row": 21.5}])
        mision = llevar(sim, "red", sensores=Roto())
        correr(mision, sim)
        self.assert_entregado(mision, sim, "red")

    def test_a_few_cm_off_the_push_line_pushes_without_replanning(self):
        # Cancha 1-oct: llegaba 39-44 mm fuera de la línea y replanificaba
        # todo (~3 s cada vez). Ahora mira al centro del cubo y empuja.
        sim = simulador((14.0, 21.5 - 35 / CELL, 0.0), [{"color": "red", "col": 22.0, "row": 21.5}])
        mision = llevar(sim, "red")
        mision.estado = "ALINEAR"                  # como si acabara de llegar
        correr(mision, sim)
        self.assert_entregado(mision, sim, "red")
        self.assertEqual(mision.replanes, 0)       # ni una replanificación
        self.assertGreater(abs(mision.ultimo["linea_mm"]), 25)   # sí estaba fuera de la línea

    def test_next_to_the_attack_point_but_off_line_corrects_along_the_line(self):
        # Rover 11, 2-oct: junto al punto de ataque y ~50 mm fuera de la línea,
        # las rutas cortas llegaban de lado y volvía a quedar fuera, tres
        # veces. Ahora: marcha atrás al punto previo y recto por la línea.
        for lado in (-50, 50):
            sim = simulador((13.0, 21.5 + lado / CELL, 90.0), [{"color": "red", "col": 21.0, "row": 21.5}])
            sim.inercia_ms = 200
            mision = llevar(sim, "red")
            usada = False
            while sim.t < 150000 and mision.activa:
                sim.paso()
                mision.tick()
                usada = usada or mision.correccion
            self.assert_entregado(mision, sim, "red")
            self.assertTrue(usada, lado)
            self.assertEqual(mision.replanes, 1, lado)

    def test_rover_hiding_the_cube_at_the_end_backs_off_to_see_it(self):
        # Como el 1-oct: parado junto al cubo ya en la zona, la cámara no lo ve.
        sim = simulador((10.0, 21.0, 0.0), [{"color": "red", "col": 24.0, "row": 21.5}])
        sim.oculto = lambda cubo, sim: (cubo["col"] > 35.0 and
                                        math.hypot(cubo["col"] - sim.col, cubo["row"] - sim.row) * CELL < 130)
        mision = llevar(sim, "red")
        correr(mision, sim)
        self.assert_entregado(mision, sim, "red")
        self.assertEqual(mision.ultimo.get("retroceso"), "cubo_tapado")

    def test_starting_against_the_border_first_moves_out(self):
        # La salida del contrato está a 75 mm del borde: menos que el radio + margen.
        sim = simulador((3.75, 21.5, 0.0), [{"color": "red", "col": 22.0, "row": 23.0}])
        mision = llevar(sim, "red")
        correr(mision, sim)
        self.assert_entregado(mision, sim, "red")

    def test_blocked_push_corridor_goes_around_without_pushing_into_it(self):
        # El azul tapa el empuje recto del rojo. Desde que el rover puede
        # asomarse fuera de la cancha (borde_mm) hay sitio para correr el rojo
        # de lado y entregarlo; antes abortaba con corredor_bloqueado.
        sim = simulador((10.0, 21.5, 0.0), [{"color": "red", "col": 22.0, "row": 21.5},
                                            {"color": "blue", "col": 31.0, "row": 21.5}])
        mision = llevar(sim, "red")
        correr(mision, sim, 60000)
        self.assert_entregado(mision, sim, "red")
        self.assertNotIn("blue", sim.empujados)

    def test_partner_crossing_is_waited_for_instead_of_going_around(self):
        # Cancha 3-oct 16:50: el 11 pasó por detrás del 10, que tomó eso por
        # un corredor tapado, reubicó el verde rodeándolo por el borde de
        # arriba y la cámara lo perdió. Ahora espera a que pase y empuja recto.
        cubos = [{"color": "green", "col": 20.5, "row": 10.5}]
        sim = simulador((18.9, 19.0, 90.0), cubos)
        sim.companeros = [{"id": 11, "col": 19.0, "row": 26.0, "theta": 0.0}]
        mision = llevar(sim, "green")
        submetas, fila = [], 99.0
        while sim.t < 60000 and mision.activa:
            if sim.t >= 2500:
                sim.companeros = [{"id": 11, "col": 6.0, "row": 30.0, "theta": 0.0}]   # ya pasó
            sim.paso()
            mision.tick()
            fila = min(fila, sim.row)
            if mision.submeta is not None:
                submetas.append(mision.submeta)
        self.assert_entregado(mision, sim, "green")
        self.assertEqual(submetas, [])                          # no movió el cubo de lado
        self.assertGreater(fila, 5.0)                           # ni se acercó al borde

    def test_partner_that_does_not_move_makes_it_drop_the_cube_not_relocate_it(self):
        # Cancha 3-oct 17:18: reubicar el verde por culpa del 11 lo sacó de la
        # cancha. Ahora lo suelta ("rover": la ronda espera y sigue con otro);
        # sólo si el otro sigue ahí después de max_cesiones vuelve a reubicar.
        cubos = [{"color": "green", "col": 20.5, "row": 10.5}]
        sim = simulador((10.0, 19.0, 0.0), cubos)
        sim.companeros = [{"id": 11, "col": 19.5, "row": 19.5, "theta": 90.0}]   # aparcado en su punto de ataque
        mision = llevar(sim, "green")
        for vez in range(mision.max_cesiones):
            if vez:
                mision.iniciar("green")
            while sim.t < 20000 * (vez + 1) and mision.activa:
                sim.paso()
                mision.tick()
                self.assertIsNone(mision.submeta)
            self.assertEqual(mision.estado, ABORTADO)
            self.assertIn("rover", mision.motivo)
        mision.iniciar("green")                                   # ya cedió 3 veces
        while sim.t < 90000 and mision.activa and mision.submeta is None:
            sim.paso()
            mision.tick()
        self.assertIsNotNone(mision.submeta)

    def test_sideways_against_its_cube_backs_away_from_it(self):
        # Cancha 3-oct 18:44: el 11 quedó de costado pegado al verde (111 mm,
        # el margen pide 152). Ni avanzar ni retroceder 14 cm lo sacaba de ahí
        # y abortó "origen_sin_espacio" con sus dos cubos.
        cubos = [{"color": "green", "col": 20.5, "row": 8.5}, {"color": "red", "col": 31.4, "row": 20.9},
                 {"color": "blue", "col": 21.3, "row": 31.7}]
        sim = simulador((22.7, 13.6, 63.0), cubos)
        # El otro rover tapa la marcha atrás pero no el camino de empuje: sólo
        # sale por el abanico (avanzar lo acerca al cubo).
        sim.companeros = [{"id": 11, "col": 27.0, "row": 21.0, "theta": 310.0}]
        mision = llevar(sim, "green")
        salidas = []
        original = mision._direccion_salida
        mision._direccion_salida = lambda *a: salidas.append(1) or original(*a)
        correr(mision, sim, 90000)
        self.assert_entregado(mision, sim, "green")
        self.assertTrue(salidas)                                # salió por el abanico

    def test_cubes_in_a_row_are_pushed_without_touching_the_others(self):
        # Cancha 3-oct 20:02 (difícil): azul justo debajo del verde a 24 cm y
        # el rojo al lado. Con el rover como círculo de 17 cm no cabía en
        # ningún punto de ataque y los dos rovers se trabaron 3 minutos.
        cubos = [{"color": "blue", "col": 20.0, "row": 27.3}, {"color": "green", "col": 20.2, "row": 15.3},
                 {"color": "red", "col": 26.7, "row": 21.5}]
        for color in ("green", "blue"):
            sim = simulador((3.7, 15.7, 0.0), cubos)
            mision = llevar(sim, color)
            correr(mision, sim, 120000)
            self.assert_entregado(mision, sim, color)
            self.assertEqual(sim.empujados, {color})

    def test_planning_fits_in_the_board_python_stack(self):
        # Cancha 3-oct 21:24: "pystack exhausted" al planificar (la pila de
        # Python de la placa es de ~1,5 KB). Peso de cada marco ~ variables +
        # pila de la función (como n_state de MicroPython); 173 es el máximo
        # de la versión que corría bien en la placa (commit 2fb9928).
        pila, peor = [], [0, []]

        def perfil(frame, evento, arg):
            if "codigos" not in frame.f_code.co_filename.replace("\\", "/"):
                return
            if evento == "call":
                if frame.f_code.co_name == "tick" and frame.f_code.co_filename.endswith("llevar_cubo.py"):
                    pila.clear()
                pila.append(frame.f_code)
                if all(c.co_name != "<module>" for c in pila):
                    total = sum(c.co_nlocals + c.co_stacksize + 4 for c in pila)
                    if total > peor[0]:
                        peor[0], peor[1] = total, [c.co_name for c in pila]
            elif evento == "return" and pila:
                pila.pop()

        cubos = [{"color": "blue", "col": 20.0, "row": 27.3}, {"color": "green", "col": 20.2, "row": 15.3},
                 {"color": "red", "col": 26.7, "row": 21.5}]
        sys.setprofile(perfil)
        try:
            for color in ("green", "blue"):
                sim = simulador((3.7, 15.7, 0.0), cubos)
                sim.companeros = [{"id": 11, "col": 12.0, "row": 30.0, "theta": 0.0}]
                mision = llevar(sim, color)
                correr(mision, sim, 60000)
        finally:
            sys.setprofile(None)
        self.assertLessEqual(peor[0], 173, " > ".join(peor[1]))

    def test_backing_off_never_leaves_the_camera_view(self):
        # Cancha 3-oct: el rover 11 se salió y la visión lo perdió. Marcha
        # atrás de 80 mm con la cola a 30 mm del borde: se acorta.
        sim = simulador((3.5, 21.5, 0.0), [{"color": "red", "col": 20.0, "row": 21.5}])
        mision = llevar(sim, "red")
        sim.paso()
        while sim.vision.mensaje is None:
            sim.paso()
        punto = mision._dentro({"col": 3.5, "row": 21.5, "theta": 0.0}, -80.0, CELL)
        self.assertGreaterEqual(punto["col"], mision.borde_mm / CELL)
        lejos = mision._dentro({"col": 20.0, "row": 21.5, "theta": 0.0}, -80.0, CELL)
        self.assertAlmostEqual(lejos["col"], 16.0)                  # en medio: los 80 mm completos

    def test_spinning_wheels_back_off_instead_of_draining_the_battery(self):
        # Cancha 3-oct: el rover 11 quedó trabado con las ruedas patinando y
        # se reinició por bajo voltaje una y otra vez. Ahora: motores con
        # potencia y la cámara lo ve quieto 2 s -> para y retrocede.
        sim = simulador((10.0, 21.5, 0.0), [{"color": "red", "col": 30.0, "row": 21.5}])
        mision = llevar(sim, "red")
        real = sim.real.velocidades
        correr(mision, sim, 1500)
        sim.real.velocidades = lambda izquierda, derecha: (0.0, 0.0)    # patina: no avanza
        inicio = sim.t
        while sim.t < inicio + 4000 and "atasco" not in mision.ultimo:
            sim.paso()
            mision.tick()
        self.assertIn("atasco", mision.ultimo)
        self.assertLess(sim.t - inicio, 3500)
        while sim.t < inicio + 30000 and mision.activa:                  # sigue trabado
            sim.paso()
            mision.tick()
        self.assertEqual((mision.estado, mision.motivo), (ABORTADO, "atascado"))
        self.assertEqual(sim.ordenes[-1][1:], (0.0, 0.0))               # motores quietos
        sim.real.velocidades = real

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
