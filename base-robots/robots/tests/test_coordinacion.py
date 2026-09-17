"""Acuerdos con pérdida, duplicación, revisiones y entrega observada."""
import copy
from pathlib import Path
import sys
import unittest

ROBOTS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROBOTS / "codigos"))
sys.path.insert(0, str(ROBOTS / "pc"))
from coordinacion import delivery_seen
from demo_coordinacion import LocalMission, run_demo


class CoordinationTests(unittest.TestCase):
    def setUp(self):
        self.m = LocalMission()
        self.a, self.b = sorted(self.m.orders)
        self.color = self.m.orders[self.a][0]

    def test_only_assigned_owner_can_reserve(self):
        response = self.m.exchange(self.b, "RESERVAR", self.color)
        self.assertFalse(response["ok"])
        self.m.change(self.a, "RESERVAR", self.color)
        self.assertEqual(self.m.leader.tasks[self.color]["owner"], self.a)

    def test_simultaneous_different_requests_require_current_revision(self):
        first = self.m.replicas[self.a].request("RESERVAR", self.color)
        other_color = self.m.orders[self.b][0]
        second = self.m.replicas[self.b].request("RESERVAR", other_color)
        self.assertTrue(self.m.leader.handle(first, self.a, self.m.vision)["ok"])
        response = self.m.leader.handle(second, self.b, self.m.vision)
        self.assertFalse(response["ok"])
        self.assertEqual(response["motivo"], "revision_desactualizada")
        self.assertEqual(self.m.leader.tasks[other_color]["estado"], "LIBRE")

    def test_lost_confirmation_never_allows_work(self):
        self.m.change(self.a, "RESERVAR", self.color)
        request = self.m.replicas[self.a].request("INICIAR", self.color)
        reply = self.m.leader.handle(request, self.a, self.m.vision)
        self.assertFalse(self.m.replicas[self.a].can_work(self.color, self.m.vision))
        self.assertTrue(self.m.replicas[self.a].receive(reply, self.a))
        self.assertTrue(self.m.replicas[self.a].can_work(self.color, self.m.vision))

    def test_duplicate_is_idempotent(self):
        packet = self.m.replicas[self.a].request("RESERVAR", self.color)
        first = self.m.leader.handle(packet, self.a, self.m.vision)
        revision = self.m.leader.revision
        second = self.m.leader.handle(packet, self.a, self.m.vision)
        self.assertEqual(first, second)
        self.assertEqual(self.m.leader.revision, revision)

    def test_same_number_with_other_payload_rejected(self):
        packet = self.m.replicas[self.a].request("RESERVAR", self.color)
        self.m.leader.handle(packet, self.a, self.m.vision)
        packet["tipo"] = "INICIAR"
        self.assertFalse(self.m.leader.handle(packet, self.a, self.m.vision)["ok"])
        self.assertEqual(self.m.leader.tasks[self.color]["estado"], "RESERVADO")

    def test_peer_timeout_freezes_without_transfer(self):
        self.m.change(self.a, "RESERVAR", self.color)
        self.m.change(self.a, "INICIAR", self.color)
        self.m.now += .6
        self.m.observe()
        self.m.exchange(self.a)
        self.assertFalse(self.m.replicas[self.a].can_work(self.color, self.m.vision))
        self.assertEqual(self.m.leader.tasks[self.color]["owner"], self.a)
        self.assertEqual(self.m.leader.tasks[self.color]["estado"], "EN_TRASLADO")
        self.m.heartbeat()
        self.assertTrue(self.m.replicas[self.a].can_work(self.color, self.m.vision))

    def test_late_reply_does_not_renew_permission(self):
        packet = self.m.replicas[self.a].request()
        reply = self.m.leader.handle(packet, self.a, self.m.vision)
        self.m.now += .6
        self.assertFalse(self.m.replicas[self.a].receive(reply, self.a))
        fresh = self.m.replicas[self.a].request()
        self.assertNotEqual(fresh["solicitud"], reply["solicitud"])
        self.assertFalse(self.m.replicas[self.a].receive(reply, self.a))

    def test_reply_deadline_measured_from_request_not_arrival(self):
        self.m.change(self.a, "RESERVAR", self.color)
        self.m.change(self.a, "INICIAR", self.color)
        packet = self.m.replicas[self.a].request()
        reply = self.m.leader.handle(packet, self.a, self.m.vision)
        self.m.now += .4
        self.assertTrue(self.m.replicas[self.a].receive(reply, self.a))
        self.m.now += .11
        self.m.observe()
        self.assertFalse(self.m.replicas[self.a].can_work(self.color, self.m.vision))

    def test_old_session_and_fake_sender_do_not_mutate(self):
        packet = self.m.replicas[self.a].request("RESERVAR", self.color)
        old = dict(packet, ronda="otra")
        self.assertIsNone(self.m.leader.handle(old, self.a, self.m.vision))
        self.assertIsNone(self.m.leader.handle(packet, self.b, self.m.vision))
        self.assertEqual(self.m.leader.revision, 0)

    def test_no_second_cube_until_delivery(self):
        owner = next(i for i, tasks in self.m.orders.items() if len(tasks) == 2)
        first, second = self.m.orders[owner]
        self.m.change(owner, "RESERVAR", first)
        response = self.m.exchange(owner, "RESERVAR", second)
        self.assertEqual(response["motivo"], "rover_ocupado")
        self.m.change(owner, "INICIAR", first)
        self.m.place_cube_for_test(first)
        self.m.change(owner, "ENTREGAR", first)
        self.m.change(owner, "RESERVAR", second)
        self.assertEqual(self.m.leader.tasks[second]["estado"], "RESERVADO")

    def test_delivery_requires_fresh_cube_inside_zone(self):
        self.m.change(self.a, "RESERVAR", self.color)
        self.m.change(self.a, "INICIAR", self.color)
        self.assertFalse(self.m.exchange(self.a, "ENTREGAR", self.color)["ok"])
        self.m.place_cube_for_test(self.color)
        cube = next(c for c in self.m.message["cubes"] if c["color"] == self.color)
        cube["age_ms"] = 600
        self.m.observe()
        self.assertFalse(self.m.exchange(self.a, "ENTREGAR", self.color)["ok"])
        cube["age_ms"] = 0
        self.m.observe()
        self.m.change(self.a, "ENTREGAR", self.color)
        self.assertFalse(self.m.replicas[self.a].can_work(self.color, self.m.vision))

    def test_cube_center_inside_is_not_enough(self):
        self.m.place_cube_for_test("red")
        self.assertTrue(delivery_seen(self.m.vision, "red"))
        cube = next(c for c in self.m.message["cubes"] if c["color"] == "red")
        cube["col"] = 42.9  # centro dentro de la cancha; el cubo sobresale
        self.m.observe()
        self.assertFalse(delivery_seen(self.m.vision, "red"))

    def test_cannot_release_in_transit_or_reopen_delivered(self):
        self.m.change(self.a, "RESERVAR", self.color)
        self.m.change(self.a, "LIBERAR", self.color)
        self.assertIsNone(self.m.leader.tasks[self.color]["owner"])
        self.m.change(self.a, "RESERVAR", self.color)
        self.m.change(self.a, "INICIAR", self.color)
        self.assertFalse(self.m.exchange(self.a, "LIBERAR", self.color)["ok"])
        self.m.place_cube_for_test(self.color)
        self.m.change(self.a, "ENTREGAR", self.color)
        self.assertFalse(self.m.exchange(self.a, "RESERVAR", self.color)["ok"])

    def test_final_phase_stops_work_but_allows_final_delivery_record(self):
        self.m.change(self.a, "RESERVAR", self.color)
        self.m.change(self.a, "INICIAR", self.color)
        self.m.place_cube_for_test(self.color)
        self.m.message["phase"] = "FINISHED"
        self.m.observe()
        self.assertFalse(self.m.replicas[self.a].can_work(self.color, self.m.vision))
        self.m.change(self.a, "ENTREGAR", self.color)

    def test_malformed_snapshot_does_not_overwrite(self):
        packet = self.m.replicas[self.a].request()
        response = copy.deepcopy(self.m.leader.handle(packet, self.a, self.m.vision))
        response["tareas"][self.color] = {"estado": "FANTASMA", "owner": self.a}
        self.assertFalse(self.m.replicas[self.a].receive(response, self.a))

    def test_full_simulated_mission(self):
        result = run_demo(announce=lambda _: None)
        self.assertEqual(result["resultado"], "OK")
        self.assertEqual(result["revision"], 9)
        self.assertTrue(all(t["estado"] == "ENTREGADO" for t in result["tareas"].values()))


if __name__ == "__main__":
    unittest.main()
