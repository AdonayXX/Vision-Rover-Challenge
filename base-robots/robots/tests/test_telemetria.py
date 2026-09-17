"""Validación del consumidor y prueba TCP real con el simulador copiado."""
import copy
import json
from pathlib import Path
import sys
import unittest

ROBOTS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROBOTS / "codigos"))
sys.path.insert(0, str(ROBOTS / "pc"))
from telemetria import NDJSONReceiver, TelemetryState
from demo_vision import run_demo


class TelemetryTests(unittest.TestCase):
    def setUp(self):
        self.now = 0.0
        self.wall_offset = 0
        self.state = TelemetryState(monotonic=lambda: self.now,
                                    wall=lambda: 1000 + self.now + self.wall_offset)
        self.state.connect()
        self.receiver = NDJSONReceiver(self.state)
        self.message = {
            "v": 2, "seq": 1, "ts_ms": 1000000, "phase": "RUNNING",
            "clock": {"elapsed_ms": 1, "remaining_ms": 999, "total_ms": 1000},
            "grid": {"cols": 43, "rows": 43, "cell_mm": 20},
            "rovers": [{"id": 11, "col": 4, "row": 25, "theta": 0, "age_ms": 0},
                       {"id": 10, "col": 4, "row": 17, "theta": 359, "age_ms": 0}],
            "cubes": [{"color": "red", "col": 20, "row": 20, "age_ms": 0}],
            "depots": [{"color": "red", "col": 39.25, "row": 21.5}],
            "obstacles": [], "start": {"col": 3.75, "row": 21.5},
            "depot_size": {"length": 10, "depth": 7.5}, "cube_side": 3,
        }

    def accept(self):
        return self.state.accept_line(json.dumps(self.message))

    def test_id_and_color_not_array_order(self):
        self.assertTrue(self.accept())
        self.assertEqual(self.state.rover(10)["row"], 17)
        self.assertEqual(self.state.rover(11)["row"], 25)
        self.assertEqual(self.state.cube("red")["col"], 20)
        self.assertEqual(self.state.depot("red")["col"], 39.25)
        self.assertIsNone(self.state.reason("red"))

    def test_all_phases(self):
        for seq, phase in enumerate(("IDLE", "READY", "RUNNING", "FINISHED"), 1):
            self.message.update(seq=seq, phase=phase)
            self.assertTrue(self.accept())
            self.assertEqual(self.state.reason(), None if phase == "RUNNING" else "fase_" + phase)

    def test_silence_ages_data(self):
        self.accept()
        self.now = .6
        self.assertEqual(self.state.reason(), "captura_vieja")

    def test_wall_clock_backwards_cannot_rejuvenate(self):
        self.accept()
        self.now = .6
        self.wall_offset = -20
        self.assertEqual(self.state.reason(), "captura_vieja")

    def test_object_age_includes_transport_and_wait(self):
        self.message["rovers"][1]["age_ms"] = 400
        self.message["ts_ms"] -= 100
        self.accept()
        self.assertEqual(self.state.reason(), "robot_propio_viejo")

    def test_missing_and_stale_peer(self):
        self.message["rovers"].pop(0)
        self.accept()
        self.assertEqual(self.state.reason(), "companero_ausente")
        self.message["rovers"].append({"id": 11, "col": 0, "row": 0, "theta": 0, "age_ms": 600})
        self.message["seq"] += 1
        self.accept()
        self.assertEqual(self.state.reason(), "companero_viejo")

    def test_target_cube_missing_or_old(self):
        self.accept()
        self.assertEqual(self.state.reason("blue"), "cubo_objetivo_ausente")
        self.message["seq"] += 1
        self.message["cubes"][0]["age_ms"] = 600
        self.accept()
        self.assertEqual(self.state.reason("red"), "cubo_objetivo_viejo")
        self.assertIsNone(self.state.reason())

    def test_position_outside_board_not_enabled(self):
        self.message["rovers"][1]["col"] = -1
        self.accept()
        self.assertEqual(self.state.reason(), "robot_propio_fuera_de_cancha")

    def test_invalid_does_not_replace_last_good_but_blocks(self):
        self.accept()
        previous = copy.deepcopy(self.state.message)
        self.message["v"] = 3
        self.assertFalse(self.accept())
        self.assertEqual(self.state.message, previous)
        self.assertIsNotNone(self.state.reason())
        self.message.update(v=2, seq=2)
        self.assertTrue(self.accept())
        self.assertIsNone(self.state.reason())

    def test_bad_shapes_numbers_and_identities(self):
        good = copy.deepcopy(self.message)
        variants = [None, [], {**good, "grid": {}}, {**good, "seq": True},
                    {**good, "ts_ms": -1}, {**good, "cube_side": float("nan")},
                    {**good, "rovers": good["rovers"] * 2}, {**good, "depots": []},
                    {**good, "cubes": good["cubes"] * 2}, {**good, "phase": "UNKNOWN"},
                    {**good, "clock": {"elapsed_ms": 1, "remaining_ms": 0, "total_ms": 0}}]
        for variant in variants:
            with self.subTest(variant=variant):
                self.assertFalse(self.state.accept_line(json.dumps(variant)))
                self.assertIsNotNone(self.state.reason())

    def test_duplicate_sequence_does_not_refresh(self):
        self.accept()
        self.now = .3
        self.assertFalse(self.accept())
        self.assertEqual(self.state.received_at, 0)
        self.now = .6
        self.message["seq"] += 1
        self.assertFalse(self.accept())  # seq nuevo, captura aún vieja

    def test_stale_and_future_timestamps(self):
        for timestamp in (999000, 1000200):
            self.message["ts_ms"] = timestamp
            self.assertFalse(self.accept())
        self.assertEqual(self.state.accepted, 0)

    def test_reconnect_resets_seq_but_waits_for_fresh_data(self):
        self.message["seq"] = 100
        self.accept()
        self.state.disconnect()
        self.assertIsNotNone(self.state.reason())
        self.state.connect()
        self.assertEqual(self.state.reason(), "esperando_datos")
        self.message["seq"] = 1
        self.assertTrue(self.accept())
        self.assertIsNone(self.state.reason())

    def test_fragmented_multiple_lines_and_bad_encoding(self):
        raw = json.dumps(self.message).encode() + b"\n"
        self.receiver.feed(raw[:10])
        self.assertEqual(self.state.accepted, 0)
        self.message["seq"] = 2
        self.receiver.feed(raw[10:] + json.dumps(self.message).encode() + b"\n")
        self.assertEqual(self.state.accepted, 2)
        self.assertEqual(self.state.seq, 2)
        self.receiver.feed(b"\xff\n")
        self.assertEqual(self.state.fault, "codificacion_invalida")

    def test_line_length_bounded(self):
        self.receiver = NDJSONReceiver(self.state, max_line_bytes=100)
        with self.assertRaises(ValueError):
            self.receiver.feed(b"x" * 101)
        self.assertEqual(len(self.receiver.buffer), 0)
        self.assertIsNotNone(self.state.reason())


class OfficialSimulatorTest(unittest.TestCase):
    def test_local_tcp_phases_and_reconnection(self):
        result = run_demo(announce=lambda text: None)
        self.assertEqual(result["resultado"], "OK")
        self.assertGreaterEqual(result["conexiones"], 2)
        self.assertEqual(result["mensajes_rechazados"], 0)
        self.assertEqual(len(result["etapas"]), 8)


if __name__ == "__main__":
    unittest.main()
