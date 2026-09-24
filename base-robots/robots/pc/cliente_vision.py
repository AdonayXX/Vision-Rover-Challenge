"""Monitor TCP para computadora. Sólo lee telemetría; no envía comandos."""
import argparse
import errno
import ipaddress
import json
import math
from pathlib import Path
import select
import socket
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "codigos"))
from telemetria import NDJSONReceiver, TelemetryState
from navegacion import PointNavigator
from rutas import RoutePlanner


class VisionClient:
    def __init__(self, state, host="127.0.0.1", port=2026,
                 retry_seconds=0.5, timeout_seconds=1.0):
        # IP literal: la resolución DNS síncrona no debe bloquear poll().
        self.host = str(ipaddress.IPv4Address(host))
        if type(port) is not int or not 0 < port <= 65535:
            raise ValueError("Puerto fuera de rango")
        for value in (retry_seconds, timeout_seconds):
            if not math.isfinite(value) or value <= 0:
                raise ValueError("Tiempos deben ser finitos y positivos")
        self.state, self.port = state, port
        self.retry_seconds, self.timeout_seconds = retry_seconds, timeout_seconds
        self.socket = None
        self.connecting = False
        self.next_retry = 0
        self.connections = 0
        self.receiver = NDJSONReceiver(state)

    def close(self, reason="cliente_cerrado"):
        if self.socket is not None:
            self.socket.close()
        self.socket = None
        self.connecting = False
        self.receiver.buffer = b""
        self.state.disconnect(reason)
        self.next_retry = self.state.monotonic() + self.retry_seconds

    def _connected(self):
        self.connecting = False
        self.connected_at = self.state.monotonic()
        self.last_data_at = self.connected_at
        self.connections += 1
        self.state.connect()

    def poll(self):
        """Conecta/reconecta sin esperar; procesa hasta 8 lecturas por ciclo."""
        now = self.state.monotonic()
        try:
            if self.socket is None:
                if now < self.next_retry:
                    return
                self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                self.socket.setblocking(False)
                result = self.socket.connect_ex((self.host, self.port))
                if result == 0:
                    self._connected()
                elif result in (errno.EINPROGRESS, errno.EWOULDBLOCK, errno.EALREADY, 10035, 10036, 10037):
                    self.connecting = True
                    self.connect_started = now
                else:
                    self.close("conexion_rechazada")
                    return
            if self.connecting:
                _, writable, exceptional = select.select([], [self.socket], [self.socket], 0)
                if writable or exceptional:
                    if self.socket.getsockopt(socket.SOL_SOCKET, socket.SO_ERROR):
                        self.close("conexion_rechazada")
                        return
                    self._connected()
                elif now - self.connect_started >= self.timeout_seconds:
                    self.close("timeout_conexion")
                    return
                else:
                    return
            for _ in range(8):
                try:
                    chunk = self.socket.recv(4096)
                except BlockingIOError:
                    break
                if not chunk:
                    self.close("servidor_desconectado")
                    return
                self.last_data_at = self.state.monotonic()
                self.receiver.feed(chunk)
            # Un cuadro viejo exige STOP, pero no significa que TCP se haya
            # caido. Reconectar por cada rechazo impedia recibir el siguiente
            # cuadro fresco y agregaba mas esperas a un productor lento.
            if self.state.monotonic() - self.last_data_at >= self.timeout_seconds:
                self.close("sin_datos")
        except (OSError, ValueError) as error:
            self.close("error_red: " + str(error))


def summary(state, target_color=None):
    reason = state.reason(target_color)
    status = "DATOS HABILITADOS" if reason is None else "ESPERAR: " + reason
    message = state.message
    if message is None:
        return status
    own, peer = state.rover(state.robot_id), state.rover(state.peer_id)
    cubes = ", ".join(
        "{}=({:.1f},{:.1f}) age={}ms".format(c["color"], c["col"], c["row"], c["age_ms"])
        for c in message["cubes"])
    pose = lambda r: "ausente" if r is None else "({:.1f},{:.1f}) {:.1f}deg".format(r["col"], r["row"], r["theta"])
    return "{} | fase={} seq={} | rover {}={} | rover {}={} | cubos: {}".format(
        status, message["phase"], message["seq"], state.robot_id, pose(own),
        state.peer_id, pose(peer), cubes)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1", help="IPv4 de la computadora de visión")
    parser.add_argument("--port", type=int, default=2026)
    parser.add_argument("--robot-id", type=int, default=10)
    parser.add_argument("--peer-id", type=int, default=11)
    parser.add_argument("--max-age-ms", type=float, default=500)
    parser.add_argument("--target-color", choices=("red", "green", "blue"))
    parser.add_argument("--target-col", type=float, help="Columna de un punto para recomendar giro/avance")
    parser.add_argument("--target-row", type=float, help="Fila del punto, en celdas")
    parser.add_argument("--route-config", help="JSON con tamaños para calcular una ruta estatica")
    parser.add_argument("--seconds", type=float, default=0, help="0 = hasta Ctrl+C")
    args = parser.parse_args(argv)
    if (args.target_col is None) != (args.target_row is None):
        parser.error("--target-col y --target-row deben indicarse juntos")
    target = None
    if args.target_col is not None:
        if not math.isfinite(args.target_col) or not math.isfinite(args.target_row):
            parser.error("Las coordenadas deben ser finitas")
        target = {"col": args.target_col, "row": args.target_row}
    navigator = PointNavigator()
    planner = None
    if args.route_config:
        if target is None:
            parser.error("--route-config requiere un punto objetivo")
        try:
            with open(args.route_config, encoding="utf-8") as source:
                planner = RoutePlanner(**json.load(source))
        except (OSError, ValueError, TypeError) as error:
            parser.error(str(error))
    if not math.isfinite(args.seconds) or args.seconds < 0:
        parser.error("--seconds debe ser finito y no negativo")
    try:
        state = TelemetryState(args.robot_id, args.peer_id, args.max_age_ms)
        client = VisionClient(state, args.host, args.port)
    except ValueError as error:
        parser.error(str(error))
    started, last_print, previous_status = time.monotonic(), -float("inf"), object()
    print("Monitor de datos; no controla motores. Ctrl+C para salir.")
    try:
        while args.seconds == 0 or time.monotonic() - started < args.seconds:
            client.poll()
            now, status = time.monotonic(), state.reason(args.target_color)
            if status != previous_status or now - last_print >= 1:
                print(summary(state, args.target_color), flush=True)
                if target is not None:
                    if planner is not None:
                        route = planner.plan(state, target)
                        if status is not None:
                            route.update(estado="ESPERAR", motivo=status, puntos=[], distancia_mm=None)
                        print("Ruta estatica; no autoriza movimiento:", route, flush=True)
                        last_print, previous_status = now, status
                        time.sleep(.02)
                        continue
                    decision = navigator.decide(state, target)
                    # El filtro de cubo seleccionado también debe prevalecer
                    # cuando el usuario pide simultáneamente un punto y un color.
                    if status is not None:
                        decision.update(accion="ESPERAR", motivo=status)
                    print("Recomendacion geometrica (ruta sin verificar):", decision, flush=True)
                last_print, previous_status = now, status
            time.sleep(.02)
    except KeyboardInterrupt:
        pass
    finally:
        client.close()
    print("Mensajes aceptados={}, rechazados={}, conexiones={}".format(
        state.accepted, state.rejected, client.connections))
    return 0 if state.accepted else 1


if __name__ == "__main__":
    raise SystemExit(main())
