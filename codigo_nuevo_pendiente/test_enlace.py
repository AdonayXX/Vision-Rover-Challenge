"""ESP-NOW entre los dos rovers (enlace.py) y la ronda coordinada por radio."""
import math
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "codigos"))
from test_autonomia import CELL, Motores
from test_llevar_cubo import entregado, simulador
from autonomia import IrAPunto, Misiones
from enlace import ETIQUETA, Enlace
from llevar_cubo import LlevarCubo
from modelo_rover import ModeloRover
from ronda import COMPLETA, CORRIENDO, Ronda

COLORES = ("red", "green", "blue")


class Paquete:
    def __init__(self, mac, msg):
        self.mac, self.msg = mac, msg


class Aire:
    """El medio: lo que una radio difunde le llega a las demás (salvo corte)."""
    def __init__(self):
        self.radios, self.cortado = [], False


class RadioFalsa:
    def __init__(self, aire, mac):
        self.aire, self.mac, self.cola = aire, mac, []
        aire.radios.append(self)

    def send(self, msg, peer=None):
        if self.aire.cortado:
            return
        for radio in self.aire.radios:
            if radio is not self:
                radio.cola.append(Paquete(self.mac, bytes(msg)))

    def read(self):
        return self.cola.pop(0) if self.cola else None


def duo(cubos, radio=True, poses=((4.0, 17.5, 0.0), (4.0, 25.5, 0.0)), opciones=({}, {})):
    """Dos rovers simulados sobre LOS MISMOS cubos; cada uno ve al otro moverse."""
    a = simulador(poses[0], cubos)
    b = simulador(poses[1], [])
    b.id, b.cubos = 11, a.cubos
    aire = Aire()
    rovers = []
    for sim, mac, extra in ((a, bytes([1] * 6), opciones[0]), (b, bytes([2] * 6), opciones[1])):
        modelo, motores = ModeloRover(), Motores(sim)
        misiones = Misiones(IrAPunto(sim.vision, modelo, motores, sim.id, reloj=sim.reloj_placa),
                            LlevarCubo(sim.vision, modelo, motores, sim.id, reloj=sim.reloj_placa))
        enlace = Enlace(sim.id, sim.reloj_placa, radio=RadioFalsa(aire, mac)) if radio else None
        ronda = Ronda(sim.vision, misiones, sim.id, reloj=sim.reloj_placa, enlace=enlace, **extra)
        misiones.ronda = ronda
        rovers.append((sim, ronda, misiones))
    return aire, rovers


def renacer(aire, rovers, i, opciones=None):
    """La placa i arranca de nuevo: misión, ronda y radio desde cero (misma MAC)."""
    sim, vieja, _ = rovers[i]
    radio = vieja.enlace._esp
    aire.radios.remove(radio)
    modelo, motores = ModeloRover(), Motores(sim)
    misiones = Misiones(IrAPunto(sim.vision, modelo, motores, sim.id, reloj=sim.reloj_placa),
                        LlevarCubo(sim.vision, modelo, motores, sim.id, reloj=sim.reloj_placa))
    enlace = Enlace(sim.id, sim.reloj_placa, radio=RadioFalsa(aire, radio.mac))
    ronda = Ronda(sim.vision, misiones, sim.id, reloj=sim.reloj_placa, enlace=enlace, **(opciones or {}))
    misiones.ronda = ronda
    rovers[i] = (sim, ronda, misiones)


def correr_duo(rovers, hasta_ms, cortar_en=None, aire=None, reinicio=None):
    """Devuelve (ms hasta los tres entregados o None, distancia mínima entre rovers en mm).

    reinicio=(i, t_ms, parado_ms): la placa i se cuelga en t_ms (motores
    parados, radio muda) y vuelve parado_ms después con la ronda en cero,
    como cuando se traba el flujo de la visión y se reinicia (cancha 5-oct).
    """
    (a, _, _), (b, _, _) = rovers
    minimo = float("inf")
    fin = None
    colgado = None                        # (i, cuándo vuelve)
    while a.t < hasta_ms or fin is not None:
        if cortar_en is not None and a.t >= cortar_en:
            aire.cortado = True
        if reinicio is not None and colgado is None and a.t >= reinicio[1]:
            i = reinicio[0]
            rovers[i][2].detener_mision("cuelgue")
            Motores(rovers[i][0]).stop("cuelgue")
            colgado = (i, a.t + reinicio[2])
        if colgado is not None and colgado[1] is not None and a.t >= colgado[1]:
            renacer(aire, rovers, colgado[0])
            colgado = (colgado[0], None)
        a.companeros = [{"id": b.id, "col": b.col, "row": b.row, "theta": b.theta}]
        b.companeros = [{"id": a.id, "col": a.col, "row": a.row, "theta": a.theta}]
        a.paso()
        b.paso()
        for j, (sim, ronda, misiones) in enumerate(rovers):
            if colgado is not None and colgado[1] is not None and colgado[0] == j:
                continue                  # colgada: ni decide ni habla
            ronda.tick()
            misiones.tick()
        minimo = min(minimo, math.hypot(a.col - b.col, a.row - b.row) * CELL)
        if fin is None and all(entregado(a, c)[0] for c in COLORES) \
                and not any(m.activa for _, _, m in rovers):
            fin = a.t                     # unos ticks más: que las rondas lo anoten
        if fin is not None and a.t >= fin + 1000:
            return fin, minimo
    return None, minimo


TRES = [{"color": "red", "col": 27.0, "row": 21.5},
        {"color": "green", "col": 17.0, "row": 13.0},
        {"color": "blue", "col": 17.0, "row": 30.0}]


class GeneradorOficialTests(unittest.TestCase):
    def test_rovers_blocking_each_other_take_turns(self):
        # Cancha del generador oficial (dificultad 0,8): el punto de ataque de
        # cada uno caía en el camino del otro y los dos esperaban para siempre
        # (0 entregas). Ahora cede el paso el de ID mayor y se aparta.
        cubos = [{"color": "red", "col": 11.0, "row": 19.0}, {"color": "blue", "col": 26.0, "row": 12.0},
                 {"color": "green", "col": 21.0, "row": 33.0}]
        aire, rovers = duo([dict(c) for c in cubos])
        t, minimo = correr_duo(rovers, 240000)
        # Ya no se esperan para siempre: los dos entregan y nunca se tocan.
        # Con el margen de empuje de 30 mm (4-oct) esta cancha termina con 2:
        # un rover arrastra el verde de costado al pasar y queda tapado por el
        # rojo. En la batería oficial el cambio suma (35/36 rondas contra
        # 34/36). Pendiente: no arrastrar cubos ajenos al pasar.
        entregados = sum(entregado(rovers[0][0], c)[0] for c in COLORES)
        self.assertGreaterEqual(entregados, 2, [r.informe() for _, r, _ in rovers])
        self.assertGreaterEqual(minimo, 120)


class EnlaceTests(unittest.TestCase):
    def setUp(self):
        self.t = 0
        self.aire = Aire()
        reloj = lambda: self.t
        self.a = Enlace(10, reloj, radio=RadioFalsa(self.aire, bytes([1] * 6)))
        self.b = Enlace(11, reloj, radio=RadioFalsa(self.aire, bytes([2] * 6)))

    def test_partner_state_arrives_and_expires(self):
        self.a.enviar({"a": "red"})
        self.b.recibir()
        self.assertEqual(self.b.companero()["a"], "red")
        self.assertEqual(self.b.companero()["id"], 10)
        self.t += 2000
        self.assertIsNone(self.b.companero())                 # radio callada: sin compañero

    def test_slow_send_silences_the_radio_for_a_while(self):
        # send() de CircuitPython reintenta hasta 2 s con los búferes de
        # ESP-NOW llenos: con un latido de 5 Hz el bucle quedaba casi parado.
        prueba = self

        class Lenta(RadioFalsa):
            def send(self, msg, peer=None):
                prueba.t += 2000
                RadioFalsa.send(self, msg, peer)

        a = Enlace(10, lambda: self.t, radio=Lenta(self.aire, bytes([3] * 6)))
        a.enviar({"a": "red"})
        self.assertEqual((a.lentos, a.envio_max_ms), (1, 2000))
        self.t += 1000
        a.enviar({"a": "red"})                                 # callada: ni lo intenta
        self.assertEqual((a.tx, self.t), (1, 3000))
        self.t += 5000
        a.enviar({"a": "red"})                                 # pasó la pausa: vuelve a probar
        self.assertEqual(a.tx, 2)
        self.assertEqual(a.informe()["lentos"], 2)

    def test_foreign_messages_are_ignored(self):
        otro = RadioFalsa(self.aire, bytes([9] * 6))
        otro.send(b'{"t": "OTRO", "id": 10, "a": "red"}')      # otro protocolo
        otro.send(b"basura")
        self.b.recibir()
        self.assertIsNone(self.b.companero())
        self.a.enviar({"a": "blue"})
        self.b.recibir()
        self.assertEqual(self.b.compa["a"], "blue")
        # Ya aprendió la MAC del compañero: un rover de otro equipo con nuestro
        # mismo código e ID no lo pisa.
        otro.send(('{"t": "%s", "id": 10, "a": "green"}' % ETIQUETA).encode())
        self.b.recibir()
        self.assertEqual(self.b.compa["a"], "blue")

    def test_corrupted_espnow_buffer_is_reopened(self):
        # Cancha 3-oct: read() empezó a dar "ValueError: Invalid buffer" en
        # cada vuelta y la radio quedó muda el resto de la ronda.
        class Trabada(RadioFalsa):
            trabada, aperturas = True, 0

            def read(self):
                if self.trabada:
                    raise ValueError("Invalid buffer")
                return RadioFalsa.read(self)

            def reabrir(self):
                self.trabada, self.cola = False, []
                self.aperturas += 1
        radio = Trabada(self.aire, bytes([3] * 6))
        c = Enlace(11, lambda: self.t, radio=radio)
        c.recibir()
        self.assertEqual((radio.aperturas, c.reaperturas), (1, 1))
        self.a.enviar({"a": "red"})
        c.recibir()
        self.assertEqual(c.companero()["a"], "red")             # vuelve a oír
        radio.trabada = True
        c.recibir()
        c.recibir()
        self.assertEqual(c.reaperturas, 1)                       # no más de una cada 2 s
        self.t += 2000
        c.recibir()
        self.assertEqual(c.reaperturas, 2)
        self.assertIn("Invalid buffer", c.informe()["ultimo_error"])

    def test_own_echo_is_ignored(self):
        self.a.enviar({"a": "red"})
        self.a.recibir()
        self.assertIsNone(self.a.compa)


class RondaPorRadioTests(unittest.TestCase):
    def test_both_rovers_deliver_with_radio(self):
        aire, rovers = duo(TRES)
        t, minimo = correr_duo(rovers, 200000)
        self.assertIsNotNone(t)
        for _, ronda, _ in rovers:
            self.assertGreaterEqual(ronda.propios, 1, ronda.informe())     # 12.2.13
            self.assertGreater(ronda.enlace.rx, 0)

    def test_follower_adopts_the_leader_split(self):
        # El 11 calcula mal su reparto (cree que le tocan todos): por radio
        # adopta el del 10, y cada uno lleva lo suyo sin pisarse.
        aire, rovers = duo(TRES, opciones=({}, {"estrategia": "todos"}))
        t, minimo = correr_duo(rovers, 200000)
        self.assertIsNotNone(t)
        (_, r10, _), (_, r11, _) = rovers
        self.assertTrue(r11.plan_del_lider, r11.informe())
        self.assertFalse(set(r10.mis_cubos) & set(r11.mis_cubos) - set(r10.robados + r11.robados))
        self.assertGreaterEqual(r10.propios, 1)
        self.assertGreaterEqual(r11.propios, 1)

    def test_without_radio_it_still_works(self):
        aire, rovers = duo(TRES, radio=False)
        t, minimo = correr_duo(rovers, 200000)
        self.assertIsNotNone(t)

    def test_radio_lost_mid_round_falls_back(self):
        aire, rovers = duo(TRES)
        t, minimo = correr_duo(rovers, 250000, cortar_en=8000, aire=aire)
        self.assertIsNotNone(t)

    def test_leader_reset_mid_round_takes_what_is_left(self):
        # Cancha 5-oct: el flujo de la visión se trababa y la placa se
        # reiniciaba. El 10 volvía, repartía de nuevo con la cancha a medio
        # jugar y quedaba con el mismo cubo que el 11 (y otro sin dueño).
        # Canchas del generador oficial, D=0,5, el 10 colgado 15 s desde los
        # 15 s: 13/24 rondas completas así, 22/24 sin reinicio.
        cubos = [{"color": "red", "col": 20.0, "row": 25.0}, {"color": "blue", "col": 26.0, "row": 23.0},
                 {"color": "green", "col": 18.0, "row": 20.0}]           # oficial05
        aire, rovers = duo([dict(c) for c in cubos])
        t, minimo = correr_duo(rovers, 240000, aire=aire, reinicio=(0, 15000, 15000))
        (_, r10, _), (_, r11, _) = rovers
        self.assertIsNotNone(t, [r10.informe(), r11.informe()])
        self.assertTrue(r10.reincorporado, r10.informe())
        self.assertEqual(r10.enlace.informe()["compa"], 11)
        # Lo que tomó al volver no estaba en la lista del 11.
        self.assertFalse(set(r10.mis_cubos) & set(r11.mis_cubos), [r10.informe(), r11.informe()])

    def test_late_start_without_partner_splits_as_usual(self):
        # Reiniciada en plena ronda y el compañero no se oye (radio caída o
        # también reiniciándose): espera tarde_espera_ms y reparte como siempre.
        aire, rovers = duo(TRES)
        aire.cortado = True
        (a, r10, m10), _ = rovers
        a.t, a.running_desde = 20000, 0                        # la ronda empezó hace 20 s
        for _ in range(100):                                   # 1 s: todavía esperando
            a.paso()
            r10.tick()
        self.assertEqual(r10.estado, "ESPERANDO")
        for _ in range(150):
            a.paso()
            r10.tick()
        self.assertEqual(r10.estado, "CORRIENDO")
        self.assertFalse(r10.reincorporado)
        self.assertTrue(r10.mis_cubos)


class TurnosTests(unittest.TestCase):
    # Cancha 4-oct 15:54, desde la salida real: a la vez, el 10 terminaba y se
    # quedaba en el camino del 11, que le cedía el rojo 10 veces (130 s).
    CUBOS = [{"color": "blue", "col": 26.3, "row": 33.5}, {"color": "green", "col": 18.9, "row": 10.5},
             {"color": "red", "col": 31.1, "row": 24.3}]
    POSES = ((2.0, 26.1, 2.0), (2.2, 17.9, 0.0))

    def correr(self, radio=True, opciones=({"cruce_mm": 0}, {"cruce_mm": 0})):
        aire, rovers = duo([dict(c) for c in self.CUBOS], radio=radio, poses=self.POSES, opciones=opciones)
        (a, r10, _), (b, r11, m11) = rovers
        al_empezar_11 = []                     # estado del 10 cuando el 11 lanza su primer cubo
        termino_10 = []                        # dónde quedó el 10 al terminar lo suyo
        fin = None
        self.minimo = float("inf")
        while a.t < 150000:
            a.companeros = [{"id": b.id, "col": b.col, "row": b.row, "theta": b.theta}]
            b.companeros = [{"id": a.id, "col": a.col, "row": a.row, "theta": a.theta}]
            a.paso()
            b.paso()
            for _, ronda, misiones in rovers:
                ronda.tick()
                misiones.tick()
            self.minimo = min(self.minimo, math.hypot(a.col - b.col, a.row - b.row) * CELL)
            if r11.actual is not None and not al_empezar_11:
                al_empezar_11.append((a.t, r10.estado))
            if r10.estado == COMPLETA and not termino_10:
                termino_10.append((a.col, a.row))
            if all(entregado(a, c)[0] for c in COLORES):
                fin = a.t
                break
        return fin, al_empezar_11, termino_10, (a.col, a.row), r10, r11, m11

    def test_second_rover_waits_its_turn_and_both_deliver(self):
        fin, al_empezar_11, termino_10, final_10, r10, r11, m11 = self.correr()
        self.assertIsNotNone(fin, [r10.informe(), r11.informe()])
        # A la vez tardaba 130 s. Por turnos, 106 s: el 11 se estaciona en la
        # esquina de arriba a la derecha y tapa el único paso del 10 (por
        # encima del rojo); el 10 termina reubicando el azul. Pendiente: que
        # el que espera sepa por dónde necesita pasar el otro.
        self.assertLess(fin, 120000)
        self.assertEqual(al_empezar_11[0][1], COMPLETA)        # empezó cuando el 10 terminó
        self.assertGreaterEqual(r10.propios, 1)                 # 12.2.13
        self.assertGreaterEqual(r11.propios, 1)
        self.assertEqual(sum(m11.cubo.cesiones.values()), 0)    # nadie le cede el paso a nadie
        # El 10 se apartó al terminar (antes: camino_bloqueado por su propio cubo)
        self.assertGreater(math.hypot(final_10[0] - termino_10[0][0], final_10[1] - termino_10[0][1]), 5)

    def test_per_cube_turns_both_work_when_paths_do_not_cross(self):
        # La misma cancha con turnos por cubo (cruce_mm, lo de fábrica): el 11
        # no espera a que el 10 termine todo, sólo a que su camino no se cruce
        # con el del cubo que lleva el 10. Por turnos enteros, 106 s.
        fin, al_empezar_11, termino_10, final_10, r10, r11, m11 = self.correr(opciones=({}, {}))
        self.assertIsNotNone(fin, [r10.informe(), r11.informe()])
        self.assertLess(fin, 75000)
        self.assertEqual(al_empezar_11[0][1], CORRIENDO)       # salió con el 10 todavía trabajando
        self.assertGreaterEqual(r10.propios, 1)                 # 12.2.13
        self.assertGreaterEqual(r11.propios, 1)
        self.assertEqual(sum(m11.cubo.cesiones.values()), 0)    # nadie le cede el paso a nadie
        self.assertGreaterEqual(self.minimo, 150)               # nunca más cerca que por turnos
        self.assertTrue(any("se cruza" in e for e in r11.eventos), r11.eventos)
        lanzados = [e for e in r11.eventos if " lleva " in e]
        self.assertLessEqual(len(lanzados), 3, lanzados)        # sin relanzar el mismo cubo

    def test_without_radio_there_are_no_turns(self):
        fin, al_empezar_11, termino_10, final_10, r10, r11, m11 = self.correr(radio=False)
        self.assertIsNotNone(fin)
        self.assertLess(al_empezar_11[0][0], 10000)             # no esperó a nadie


class PilaDeLaPlacaTests(unittest.TestCase):
    def test_parking_fits_in_the_board_python_stack(self):
        # Cancha 4-oct 15:54: el 10 terminó y nunca se estacionó, y el 11
        # "cedía el paso" sin moverse. Estacionarse llamaba al A* desde
        # Ronda.tick > _avanzar > _aparcar > _ruta: peso 201, y en la placa
        # (pila de ~1,5 KB) eso falla; tick() atrapaba el error en silencio.
        # Mismo peso que test_planning_fits_in_the_board_python_stack (173),
        # pero midiendo desde Ronda.tick. Esa ronda desde la salida real: al
        # terminar, los dos planifican dónde estacionarse con búsqueda A*.
        cubos = [{"color": "blue", "col": 26.3, "row": 33.5}, {"color": "green", "col": 18.9, "row": 10.5},
                 {"color": "red", "col": 31.1, "row": 24.3}]
        pila, peor, planes = [], [0, []], [0]

        def perfil(frame, evento, arg):
            nombre = frame.f_code.co_filename.replace("\\", "/")
            if "codigos" not in nombre:
                return
            if evento == "call":
                if frame.f_code.co_name == "tick" and nombre.endswith("ronda.py"):
                    pila.clear()
                pila.append(frame.f_code)
                if pila[0].co_name != "tick" or not pila[0].co_filename.endswith("ronda.py"):
                    return
                if frame.f_code.co_name == "plan":
                    planes[0] += 1
                if all(c.co_name != "<module>" for c in pila):
                    total = sum(c.co_nlocals + c.co_stacksize + 4 for c in pila)
                    if total > peor[0]:
                        peor[0], peor[1] = total, [c.co_name for c in pila]
            elif evento == "return" and pila:
                pila.pop()

        aire, rovers = duo(cubos, poses=((2.0, 26.1, 2.0), (2.2, 17.9, 0.0)))
        sys.setprofile(perfil)
        try:
            correr_duo(rovers, 40000)
        finally:
            sys.setprofile(None)
        self.assertGreater(planes[0], 0, "la ronda no llegó a planificar dónde estacionarse")
        self.assertLessEqual(peor[0], 173, " > ".join(peor[1]))


if __name__ == "__main__":
    unittest.main()
