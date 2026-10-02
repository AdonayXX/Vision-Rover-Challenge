"""Control autónomo en la placa contra un rover simulado con retrasos reales.

El simulador reproduce lo medido el 1-oct: los motores reaccionan 150 ms
tarde, la cámara sella la imagen 140 ms después de verla (290 ms de "retraso
de arranque" en total) y la red entrega con 150-350 ms de latencia variable.
El reloj de la placa no coincide con el de la visión.
"""
import math
from pathlib import Path
import random
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "codigos"))
from autonomia import ABORTADO, LLEGO, IrAPunto, hacia_punto
from command_protocol import parse_command
from modelo_rover import ModeloRover, Predictor
from sesion_comandos import CommandSession

CELL = 20.0


class Motores:
    def __init__(self, sim):
        self.sim, self.mode, self.reason = sim, None, "inicio"

    def set_motor(self, izquierda, derecha):
        self.mode = "MOTOR"
        self.sim.ordenes.append((self.sim.t, izquierda, derecha))

    def stop(self, reason="stop"):
        self.mode, self.reason = None, reason
        self.sim.ordenes.append((self.sim.t, 0.0, 0.0))

    def start_motor(self, izquierda, derecha):
        self.set_motor(izquierda, derecha)

    def update(self):
        pass


class Vision:
    """Lo mismo que expone ClienteVision al control: mensaje y desfase."""
    def __init__(self):
        self.mensaje, self.desfase_reloj = None, None


class Simulador:
    RELOJ_PLACA = 7_000_000      # la placa no comparte reloj con la vision

    def __init__(self, real, retraso_motor=150, sello_camara=140, latencia=(150, 350),
                 pose=(10.0, 20.0, 0.0), semilla=1):
        self.real, self.retraso_motor, self.sello = real, retraso_motor, sello_camara
        self.latencia = latencia
        self.rand = random.Random(semilla)
        self.t = 0
        self.col, self.row, self.theta = pose
        self.ordenes = [(-10_000, 0.0, 0.0)]
        self.en_vuelo = []                    # (llegada, mensaje)
        self.vision = Vision()
        self.seq = 0
        self.sin_vision_desde = None
        self.trayecto = []
        self.cubos = []
        self.contacto = False             # el cuerpo llego a tocar un cubo
        # Empuje (incremento 2): distancia centro de giro -> centro del cubo
        # al tocarlo con el frente; None = los cubos no se mueven.
        self.frente_mm = None
        self.deriva = 0.0                 # mm laterales que resbala el cubo por mm empujado
        self.empujados = set()
        # Como el 1-oct en la cancha: la camara deja de ver un cubo y el
        # mensaje trae su ULTIMA posicion con la edad creciendo (contrato §6).
        self.oculto = None                # callable(cubo, sim) -> True si no se ve
        self.vistos = {}
        # Inercia: la velocidad real sigue a la ordenada con esta constante de
        # tiempo; al parar el rover sigue deslizando ~v·inercia (rover 11:
        # ~30 mm a 150 mm/s, calibración 2-oct). None = sin inercia.
        self.inercia_ms = None
        self.v_real = self.w_real = 0.0

    def reloj_placa(self):
        return self.t + self.RELOJ_PLACA

    def _orden_fisica(self):
        vigente = (0.0, 0.0)
        for t, izquierda, derecha in self.ordenes:
            if t + self.retraso_motor > self.t:
                break
            vigente = (izquierda, derecha)
        return vigente

    def paso(self, dt=10):
        v, w = self.real.velocidades(*self._orden_fisica())
        if self.inercia_ms:
            self.v_real += (v - self.v_real) * min(1.0, dt / self.inercia_ms)
            self.w_real += (w - self.w_real) * min(1.0, dt / self.inercia_ms)
            v, w = self.v_real, self.w_real
        medio = math.radians(self.theta + w * dt / 2000)
        self.col += v * dt / 1000 * math.cos(medio) / CELL
        self.row -= v * dt / 1000 * math.sin(medio) / CELL
        self.theta = (self.theta + w * dt / 1000) % 360
        self.trayecto.append((self.col, self.row))
        if self.frente_mm is not None:
            self._empujar_cubos()
        for cubo in self.cubos:
            if math.hypot(cubo["col"] - self.col, cubo["row"] - self.row) * CELL < 85 + 30:
                self.contacto = True
        if self.t % 50 == 0 and (self.sin_vision_desde is None or self.t < self.sin_vision_desde):
            th = math.radians(self.theta)
            d = self.real.desfase_marcador_mm / CELL
            self.seq += 1
            mensaje = {"seq": self.seq, "ts_ms": self.t + self.sello, "grid": {"cols": 43, "rows": 43, "cell_mm": CELL},
                       "cube_side": 3.0, "obstacles": [], "cubes": self._cubos_vistos(),
                       "depots": [dict(d) for d in DEPOSITOS], "depot_size": {"length": 10.0, "depth": 7.5},
                       "rovers": [{"id": 10, "col": self.col + d * math.cos(th),
                                   "row": self.row - d * math.sin(th), "theta": self.theta, "age_ms": 0}]}
            llegada = self.t + self.sello + self.rand.uniform(*self.latencia)
            self.en_vuelo.append((llegada, mensaje))
        for item in [m for m in self.en_vuelo if m[0] <= self.t]:
            self.en_vuelo.remove(item)
            llegada, mensaje = item
            desfase = llegada + self.RELOJ_PLACA - mensaje["ts_ms"]
            if self.vision.desfase_reloj is None or desfase < self.vision.desfase_reloj:
                self.vision.desfase_reloj = desfase
            if self.vision.mensaje is None or mensaje["seq"] > self.vision.mensaje["seq"]:
                self.vision.mensaje = mensaje
        self.t += dt

    def _cubos_vistos(self):
        salida = []
        for cubo in self.cubos:
            if self.oculto is None or not self.oculto(cubo, self) or cubo["color"] not in self.vistos:
                self.vistos[cubo["color"]] = (dict(cubo), self.t)
            visto, cuando = self.vistos[cubo["color"]]
            salida.append(dict(visto, age_ms=self.t - cuando))
        return salida

    def _empujar_cubos(self):
        """El frente del rover (ancho ±55 mm) no deja que un cubo quede más cerca que frente_mm."""
        th = math.radians(self.theta)
        ux, uy = math.cos(th), -math.sin(th)
        for cubo in self.cubos:
            dc, dr = (cubo["col"] - self.col) * CELL, (cubo["row"] - self.row) * CELL
            adelante = dc * ux + dr * uy
            lateral = -dc * uy + dr * ux
            if 0 < adelante < self.frente_mm and abs(lateral) < 55:
                metido = self.frente_mm - adelante
                lateral += self.deriva * metido
                cubo["col"] = self.col + (self.frente_mm * ux - lateral * uy) / CELL
                cubo["row"] = self.row + (self.frente_mm * uy + lateral * ux) / CELL
                self.empujados.add(cubo["color"])


DEPOSITOS = ({"color": "green", "col": 21.5, "row": 3.75}, {"color": "blue", "col": 21.5, "row": 39.25},
             {"color": "red", "col": 39.25, "row": 21.5})


def correr(mision, sim, hasta_ms=15000):
    while sim.t < hasta_ms and mision.estado not in (LLEGO, ABORTADO):
        sim.paso()
        mision.tick()
    return mision.estado


def nueva_mision(creido, sim):
    return IrAPunto(sim.vision, creido, Motores(sim), 10, reloj=sim.reloj_placa)


class ModeloTests(unittest.TestCase):
    def setUp(self):
        self.m = ModeloRover()

    def test_power_inverse_roundtrip(self):
        for v, w in ((150, 0), (100, 40), (0, 90), (0, -60), (-120, 0)):
            vv, ww = self.m.velocidades(*self.m.potencias(v, w, limite=1))
            self.assertAlmostEqual(vv, v, delta=1)
            self.assertAlmostEqual(ww, w, delta=1)

    def test_in_place_turn_has_dead_zone(self):
        self.assertEqual(self.m.velocidades(-.04, .04)[1], 0)
        self.assertGreater(self.m.velocidades(-.18, .18)[1], 80)

    def test_power_limit_keeps_curvature(self):
        izquierda, derecha = self.m.potencias(600, 200, limite=.35)
        self.assertLessEqual(max(abs(izquierda), abs(derecha)), .35 + 1e-9)
        self.assertGreater(derecha, izquierda)

    def test_marker_is_ahead_of_center(self):
        centro = self.m.centro_desde_marcador({"col": 10, "row": 10, "theta": 90}, CELL)
        self.assertAlmostEqual(centro["row"], 10 + 30 / CELL)
        self.assertAlmostEqual(centro["col"], 10)

    def test_predictor_integrates_only_issued_commands(self):
        p = Predictor(self.m)
        p.registrar(1000, .25, .25)
        pose = p.predecir({"col": 10, "row": 10, "theta": 0}, 600, 1400, CELL)
        avance = (pose["col"] - 10) * CELL
        self.assertAlmostEqual(avance, self.m.k_lineal * .25 * .4, delta=2)

    def test_load_from_calibration_summary(self):
        resumen = {"avance_mm_s_por_unidad": 637.1, "retraso_arranque_ms": 293,
                   "desfase_marcador_mm": 29.1, "latencia_vision_ms": {"min": 150},
                   "familias": {"giro_izq": {"k_por_unidad": 701.4, "zona_muerta": .061},
                                "giro_der": {"k_por_unidad": 730.0, "zona_muerta": .052}}}
        m = ModeloRover.desde_resumen(resumen)
        self.assertAlmostEqual(m.k_giro, 715.7, delta=.1)
        self.assertAlmostEqual(m.zona_muerta_giro, .0565, delta=.001)
        self.assertEqual(m.retraso_ms, 293)


class MisionSimuladaTests(unittest.TestCase):
    def objetivo_llegado(self, sim, objetivo, tolerancia_mm=40):
        return math.hypot(sim.col - objetivo[0], sim.row - objetivo[1]) * CELL <= tolerancia_mm

    def sobrepaso_mm(self, sim, inicio, objetivo):
        ux, uy = objetivo[0] - inicio[0], objetivo[1] - inicio[1]
        largo = math.hypot(ux, uy)
        maximo = max(((c - inicio[0]) * ux + (r - inicio[1]) * uy) / largo for c, r in sim.trayecto)
        return (maximo - largo) * CELL

    def test_reaches_point_straight_ahead_without_overshoot(self):
        sim = Simulador(ModeloRover())
        mision = nueva_mision(ModeloRover(), sim)
        mision.iniciar(30.0, 20.0)                     # 40 cm al frente
        self.assertEqual(correr(mision, sim), LLEGO)
        self.assertTrue(self.objetivo_llegado(sim, (30, 20)))
        self.assertLess(self.sobrepaso_mm(sim, (10, 20), (30, 20)), 30)
        self.assertLess(sim.t, 6000)                   # ~3 s de viaje, no 20 pulsos

    def test_reaches_point_behind_turning_first(self):
        sim = Simulador(ModeloRover(), pose=(25.0, 20.0, 0.0))
        mision = nueva_mision(ModeloRover(), sim)
        mision.iniciar(12.0, 26.0)                     # atrás y a un lado
        self.assertEqual(correr(mision, sim), LLEGO)
        self.assertTrue(self.objetivo_llegado(sim, (12, 26)))

    def test_tolerates_model_error(self):
        # El rover real va 20 % mas lento y gira 15 % mas rapido de lo creido.
        real = ModeloRover(k_lineal=630 * .8, k_giro=715 * 1.15)
        for objetivo in ((30.0, 20.0), (22.0, 8.0), (14.0, 30.0)):
            sim = Simulador(real, semilla=hash(objetivo) % 100)
            mision = nueva_mision(ModeloRover(), sim)
            mision.iniciar(*objetivo)
            self.assertEqual(correr(mision, sim), LLEGO, objetivo)
            self.assertTrue(self.objetivo_llegado(sim, objetivo), objetivo)

    def test_cube_in_path_stops_before_touching_it(self):
        sim = Simulador(ModeloRover())
        sim.cubos = [{"color": "red", "col": 24.0, "row": 20.0, "age_ms": 0}]
        mision = nueva_mision(ModeloRover(), sim)
        mision.iniciar(32.0, 20.0)
        self.assertEqual(correr(mision, sim), ABORTADO)
        self.assertTrue(mision.motivo.startswith("camino_bloqueado: cubo red"))
        correr(mision, sim, hasta_ms=sim.t + 1000)    # lo que ya iba en vuelo
        self.assertFalse(sim.contacto)

    def test_cube_beside_path_does_not_block(self):
        sim = Simulador(ModeloRover())
        sim.cubos = [{"color": "blue", "col": 20.0, "row": 30.0, "age_ms": 0}]
        mision = nueva_mision(ModeloRover(), sim)
        mision.iniciar(30.0, 20.0)
        self.assertEqual(correr(mision, sim), LLEGO)

    def test_real_dead_zone_still_converges(self):
        # Como el 1-oct: el rover real no avanza por debajo de ~0,08.
        real = ModeloRover(zona_muerta_lineal=.08)
        for creido in (ModeloRover(), ModeloRover(zona_muerta_lineal=.08)):
            sim = Simulador(real)
            mision = nueva_mision(creido, sim)
            mision.iniciar(22.5, 20.0)                 # 25 cm
            self.assertEqual(correr(mision, sim), LLEGO)
            self.assertTrue(self.objetivo_llegado(sim, (22.5, 20.0)))

    def test_close_target_behind_is_reached_in_reverse(self):
        sim = Simulador(ModeloRover(), pose=(20.0, 20.0, 0.0))
        mision = nueva_mision(ModeloRover(), sim)
        mision.iniciar(17.5, 20.0)                     # 5 cm detras
        self.assertEqual(correr(mision, sim), LLEGO)
        giro = min(abs((t - 0 + 180) % 360 - 180) for t in [sim.theta])
        self.assertLess(giro, 45)                       # no dio media vuelta

    def test_online_scales_learn_a_weaker_rover(self):
        # Como el 1-oct: en una hora el giro bajo a la mitad y el avance un 30 %.
        real = ModeloRover(k_lineal=630 * .7, k_giro=715 * .5)
        creido = ModeloRover()
        for objetivo, pose in (((30.0, 20.0), (10.0, 20.0, 0.0)),
                                ((14.0, 8.0), (30.0, 20.0, 0.0)),
                                ((30.0, 30.0), (14.0, 8.0, 0.0))):
            sim = Simulador(real, pose=pose)
            mision = nueva_mision(creido, sim)       # el modelo creido se conserva
            mision.iniciar(*objetivo)
            self.assertEqual(correr(mision, sim), LLEGO, objetivo)
            self.assertTrue(self.objetivo_llegado(sim, objetivo), objetivo)
        self.assertAlmostEqual(creido.escala_lineal, .7, delta=.15)
        self.assertAlmostEqual(creido.escala_giro, .5, delta=.15)

    def test_exact_model_keeps_scales_near_one(self):
        creido = ModeloRover()
        sim = Simulador(ModeloRover())
        mision = nueva_mision(creido, sim)
        mision.iniciar(30.0, 26.0)
        self.assertEqual(correr(mision, sim), LLEGO)
        self.assertAlmostEqual(creido.escala_lineal, 1, delta=.15)
        self.assertAlmostEqual(creido.escala_giro, 1, delta=.15)

    def test_stale_vision_stops_then_aborts(self):
        sim = Simulador(ModeloRover())
        mision = nueva_mision(ModeloRover(), sim)
        mision.iniciar(35.0, 20.0)
        sim.sin_vision_desde = 1500
        correr(mision, sim, hasta_ms=1500 + 1100)
        self.assertEqual(mision.estado, "ESPERANDO_VISION")
        self.assertIsNone(mision.motores.mode)
        self.assertEqual(correr(mision, sim, hasta_ms=9000), ABORTADO)

    def test_out_of_field_target_rejected(self):
        sim = Simulador(ModeloRover())
        sim.paso()
        sim.vision.mensaje = {"grid": {"cols": 43, "rows": 43, "cell_mm": CELL}, "rovers": []}
        mision = nueva_mision(ModeloRover(), sim)
        with self.assertRaises(ValueError):
            mision.iniciar(50.0, 10.0)


class SesionTests(unittest.TestCase):
    def setUp(self):
        self.sim = Simulador(ModeloRover())
        self.motores = Motores(self.sim)
        self.mision = IrAPunto(self.sim.vision, ModeloRover(), self.motores, 10,
                               reloj=self.sim.reloj_placa)
        self.sesion = CommandSession(self.motores, mission=self.mision)

    def test_ir_command_parses_and_starts_mission(self):
        self.assertTrue(parse_command("IR|30.5|20")["valid"])
        self.assertTrue(self.sesion.process_command("IR|30.5|20"))
        self.assertTrue(self.mision.activa)

    def test_stop_or_manual_motor_aborts_mission(self):
        self.sesion.process_command("IR|30|20")
        self.sesion.process_command("STOP")
        self.assertEqual(self.mision.estado, ABORTADO)
        self.sesion.process_command("IR|30|20")
        self.sesion.process_command("MOTOR|.2|.2")
        self.assertEqual(self.mision.motivo, "orden_motor")

    def test_route_measurement_command_replies_with_plan(self):
        import json
        self.sim.cubos = [{"color": "red", "col": 20.0, "row": 20.0, "age_ms": 0}]
        for _ in range(60):
            self.sim.paso()
        self.sesion.process_command("IR|30|20")
        self.assertTrue(self.sesion.process_command("RUTA|30|20|2"))
        self.assertFalse(self.mision.activa)            # medir detiene la mision
        resultado = json.loads(self.sesion.reply)
        self.assertEqual(resultado["estado"], "RUTA")
        self.assertGreater(len(resultado["puntos"]), 2)  # rodea el cubo
        self.assertFalse(parse_command("RUTA|30|20|7")["valid"])

    def test_control_law_turns_in_place_when_target_behind(self):
        llego, izquierda, derecha, _, error = hacia_punto(
            {"col": 10, "row": 10, "theta": 0}, {"col": 5, "row": 10}, CELL, ModeloRover())
        self.assertFalse(llego)
        self.assertAlmostEqual(izquierda, -derecha, places=6)


if __name__ == "__main__":
    unittest.main()
