"""Cliente de vision de la placa con red y reloj simulados."""
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "codigos"))
from cliente_vision_rover import ClienteVision


def mensaje(seq, ts_ms):
    return {"v": 2, "seq": seq, "ts_ms": ts_ms, "phase": "IDLE",
            "clock": {"elapsed_ms": 0, "remaining_ms": 600000, "total_ms": 600000},
            "grid": {"cols": 43, "rows": 43, "cell_mm": 20},
            "rovers": [{"id": 10, "col": 5, "row": 5, "theta": 0, "age_ms": 0}],
            "cubes": [{"color": "red", "col": 20, "row": 20, "age_ms": 0}],
            "obstacles": [], "start": {"col": 5, "row": 5},
            "depots": [{"color": "red", "col": 39.25, "row": 21.5}],
            "depot_size": {"length": 150, "depth": 100}, "cube_side": 2.5}


def linea(seq, ts_ms=1000):
    return (json.dumps(mensaje(seq, ts_ms)) + "\n").encode()


class Socket:
    def __init__(self, trozos=()):
        self.trozos = list(trozos)
        self.cerrado = False

    def settimeout(self, valor):
        pass

    def setblocking(self, valor):
        pass

    def connect(self, destino):
        self.destino = destino

    def recv_into(self, buffer):
        if not self.trozos:
            raise OSError(11, "sin datos")
        dato = self.trozos.pop(0)
        if isinstance(dato, Exception):
            raise dato
        parte, resto = dato[:len(buffer)], dato[len(buffer):]
        if resto:
            self.trozos.insert(0, resto)
        buffer[:len(parte)] = parte
        return len(parte)

    def close(self):
        self.cerrado = True


class Pool:
    AF_INET, SOCK_STREAM = 2, 1

    def __init__(self, sock):
        self.sock, self.creados = sock, 0

    def socket(self, *args):
        self.creados += 1
        return self.sock


class ClienteVisionTests(unittest.TestCase):
    def setUp(self):
        self.now = 5000
        self.sock = Socket()
        self.pool = Pool(self.sock)
        self.cliente = ClienteVision(self.pool, "10.0.0.2", reloj=lambda: self.now)

    def test_only_newest_complete_line_is_decoded(self):
        self.sock.trozos = [linea(1) + linea(2) + linea(3)]
        self.assertTrue(self.cliente.poll())
        self.assertEqual(self.cliente.mensaje["seq"], 3)
        self.assertEqual(self.cliente.decodificados, 1)
        self.assertEqual(self.cliente.descartadas, 2)
        self.assertEqual(self.sock.destino, ("10.0.0.2", 2026))

    def test_fragmented_line_waits_until_complete(self):
        datos = linea(7)
        self.sock.trozos = [datos[:300]]
        self.assertFalse(self.cliente.poll())
        self.sock.trozos = [datos[300:]]
        self.assertTrue(self.cliente.poll())
        self.assertEqual(self.cliente.mensaje["seq"], 7)

    def test_seq_gaps_and_old_seq(self):
        self.sock.trozos = [linea(1)]
        self.cliente.poll()
        self.sock.trozos = [linea(4)]
        self.cliente.poll()
        self.assertEqual(self.cliente.saltos_seq, 2)
        self.sock.trozos = [linea(3)]
        self.assertFalse(self.cliente.poll())
        self.assertEqual(self.cliente.mensaje["seq"], 4)

    def test_relative_age_uses_fastest_delivery(self):
        self.sock.trozos = [linea(1, ts_ms=1000)]
        self.cliente.poll()                      # desfase 4000: el minimo
        self.now = 5300
        self.sock.trozos = [linea(2, ts_ms=1100)]
        self.cliente.poll()                      # llego 200 ms mas tarde
        self.assertEqual(self.cliente.edad_max, 200)
        self.now = 5400
        self.assertEqual(self.cliente.edad_relativa_ms(), 300)

    def test_silent_connection_is_closed_and_reported(self):
        # Wi-Fi caído sin aviso: el socket no da error, sólo deja de llegar
        # nada. A los 3 s se cierra; silencio_ms sigue creciendo para que la
        # placa reinicie el Wi-Fi si dura (cancha 2-oct).
        self.assertIsNone(self.cliente.silencio_ms())          # nunca llegó nada
        self.sock.trozos = [linea(1)]
        self.assertTrue(self.cliente.poll())
        self.now += 2000
        self.assertFalse(self.cliente.poll())
        self.assertEqual(self.cliente.estado, "ok")
        self.now += 1500
        self.assertFalse(self.cliente.poll())
        self.assertEqual(self.cliente.estado, "vision_sin_datos")
        self.assertTrue(self.sock.cerrado)
        self.now += 20000
        self.assertEqual(self.cliente.silencio_ms(), 23500)
        self.cliente.reiniciar_silencio()
        self.assertEqual(self.cliente.silencio_ms(), 0)

    def test_reconnecting_without_data_is_still_silence(self):
        # Red a medias: el socket vuelve a conectar pero no llega ni un byte.
        # Antes cada conexión reiniciaba el silencio y la placa nunca llegaba
        # a reiniciar el Wi-Fi (cancha 4-oct: cortes de más de un minuto).
        self.sock.trozos = [linea(1)]
        self.assertTrue(self.cliente.poll())
        for _ in range(4):
            self.now += 3500
            self.assertFalse(self.cliente.poll())       # se cierra: sin datos
            self.now += 1000
            self.assertFalse(self.cliente.poll())       # vuelve a conectar, y nada
        self.assertEqual(self.cliente.silencio_ms(), 18000)

    def test_stream_that_stalls_after_each_reconnect_is_counted(self):
        # Cancha 5-oct: cada conexión nueva trae una ráfaga y se vuelve a
        # trabar. Las ráfagas reinician el silencio, pero los cortes se cuentan
        # y la placa se reinicia con dos en 20 s.
        self.sock.trozos = [linea(1)]
        self.assertTrue(self.cliente.poll())
        seq = 2
        for _ in range(2):
            self.now += 3500
            self.assertFalse(self.cliente.poll())       # trabada: se cierra
            self.now += 1000
            self.sock.trozos = [linea(seq)]
            self.assertTrue(self.cliente.poll())        # reconecta: llega una ráfaga
            seq += 1
        self.assertLess(self.cliente.silencio_ms(), 1000)
        self.assertEqual(self.cliente.cortes_recientes(20000), 2)
        self.now += 30000
        self.assertEqual(self.cliente.cortes_recientes(20000), 0)
        self.cliente.reiniciar_silencio()
        self.assertEqual(self.cliente.cortes, [])

    def test_draining_during_route_keeps_only_the_latest_message(self):
        # El A* llama a drenar (rutas.ESPERA): vacía el socket sin decodificar
        # y poll() después usa sólo el último mensaje.
        self.sock.trozos = [linea(1)]
        self.assertTrue(self.cliente.poll())
        for seq in range(2, 12):
            self.sock.trozos = [linea(seq)]
            self.cliente.drenar()
        self.assertLess(len(self.cliente.buffer), 3000 + len(linea(11)))
        self.assertTrue(self.cliente.poll())
        self.assertEqual(self.cliente.mensaje["seq"], 11)

    def test_invalid_message_is_counted_not_used(self):
        self.sock.trozos = [b'{"v": 3}\n']
        self.assertFalse(self.cliente.poll())
        self.assertIsNone(self.cliente.mensaje)
        self.assertEqual(self.cliente.errores_mensaje, 1)

    def test_no_reconnect_while_motors_run(self):
        self.assertFalse(self.cliente.poll(puede_bloquear=False))
        self.assertEqual(self.pool.creados, 0)

    def test_closed_connection_retries_later(self):
        self.sock.trozos = [b""]
        self.cliente.poll()
        self.assertTrue(self.sock.cerrado)
        self.assertEqual(self.cliente.estado, "vision_cerro_conexion")
        self.cliente.poll()
        self.assertEqual(self.pool.creados, 1)   # todavia en espera
        self.now += 1000
        self.cliente.poll()
        self.assertEqual(self.pool.creados, 2)

    def test_runaway_partial_line_is_bounded(self):
        self.sock.trozos = [b"x" * 9000]
        self.cliente.poll()
        self.cliente.poll()
        self.assertLessEqual(len(self.cliente.buffer), 8192)
        self.assertGreater(self.cliente.errores_mensaje, 0)

    def test_stats_are_json_serializable(self):
        self.sock.trozos = [linea(1)]
        self.cliente.poll()
        json.dumps(self.cliente.estadisticas(memoria_libre=50000))


if __name__ == "__main__":
    unittest.main()
