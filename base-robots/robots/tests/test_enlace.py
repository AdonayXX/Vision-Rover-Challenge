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
from ronda import COMPLETA, Ronda

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


def correr_duo(rovers, hasta_ms, cortar_en=None, aire=None):
    """Devuelve (ms hasta los tres entregados o None, distancia mínima entre rovers en mm)."""
    (a, _, _), (b, _, _) = rovers
    minimo = float("inf")
    fin = None
    while a.t < hasta_ms or fin is not None:
        if cortar_en is not None and a.t >= cortar_en:
            aire.cortado = True
        a.companeros = [{"id": b.id, "col": b.col, "row": b.row, "theta": b.theta}]
        b.companeros = [{"id": a.id, "col": a.col, "row": a.row, "theta": a.theta}]
        a.paso()
        b.paso()
        for sim, ronda, misiones in rovers:
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


if __name__ == "__main__":
    unittest.main()
