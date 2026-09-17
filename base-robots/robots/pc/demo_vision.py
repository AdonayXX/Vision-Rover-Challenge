"""Prueba completa local con el publicador original; no requiere webcam ni robots."""
import json
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time

from cliente_vision import TelemetryState, VisionClient, summary

BASE = Path(__file__).resolve().parents[2]


def run_demo(announce=print):
    report = {"resultado": "OK", "etapas": []}
    state = TelemetryState()
    with tempfile.TemporaryDirectory(prefix="rover-vision-") as temp:
        temp = Path(temp)
        config = json.loads((BASE / "vision-system/contrato/config_simulador.json").read_text(encoding="utf-8"))
        config["ronda"]["preparacion_ms"] = 1000
        config["ronda"]["duracion_ms"] = 60000
        # Mantener el ruido del simulador; quitar pérdidas aleatorias en esta
        # prueba de red. Las pérdidas/oclusiones tienen pruebas deterministas.
        config["patologias"]["prob_perdida_rover"] = 0
        config_path = temp / "config.json"
        config_path.write_text(json.dumps(config), encoding="utf-8")
        # Puerto temporal para no interferir con una visión ya abierta en 2026.
        with socket.socket() as reservation:
            reservation.bind(("127.0.0.1", 0))
            port = reservation.getsockname()[1]
        client = VisionClient(state, port=port, retry_seconds=.1)
        log = (temp / "simulador.log").open("w", encoding="utf-8")
        process = None

        def start():
            return subprocess.Popen(
                [sys.executable, "-B", "-u", "-m", "contrato.mock_publisher",
                 "--config", str(config_path), "--host", "127.0.0.1", "--port", str(port)],
                cwd=BASE / "vision-system", stdin=subprocess.PIPE, stdout=log,
                stderr=subprocess.STDOUT, text=True,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))

        def command(text):
            process.stdin.write(text + "\n")
            process.stdin.flush()

        def wait_for(predicate, label, timeout=6):
            deadline = time.monotonic() + timeout
            while time.monotonic() < deadline:
                client.poll()
                if predicate():
                    report["etapas"].append(label)
                    announce("OK - " + label)
                    return
                time.sleep(.01)
            log.flush()
            detail = (temp / "simulador.log").read_text(encoding="utf-8", errors="replace")
            raise AssertionError(label + " no se completo. " + summary(state) + "\n" + detail[-2000:])

        def stop_process():
            if process is not None:
                try:
                    if process.poll() is None:
                        command("quit")
                        process.wait(timeout=4)
                finally:
                    if process.poll() is None:
                        process.kill()
                        process.wait(timeout=4)
                    process.stdin.close()

        try:
            process = start()
            wait_for(lambda: state.fault is None and state.reason() == "fase_IDLE", "Conexion e IDLE sin habilitar datos")
            if not (state.rover(10) and state.rover(11) and
                    all(state.cube(c) and state.depot(c) for c in ("red", "green", "blue"))):
                raise AssertionError("Faltan entidades del simulador")
            report["etapas"].append("Dos rovers y tres cubos con sus destinos identificados")
            announce("OK - " + report["etapas"][-1])
            command("ready")
            wait_for(lambda: state.reason() == "fase_READY", "READY mantiene la espera")
            wait_for(lambda: state.reason() is None, "RUNNING habilita datos frescos")
            announce(summary(state))
            command("stop")
            wait_for(lambda: state.reason() == "fase_FINISHED", "FINISHED vuelve a exigir parada")
            stop_process()
            wait_for(lambda: not state.connected, "Corte del servidor detectado")
            accepted_before = state.accepted
            process = start()
            wait_for(lambda: state.accepted > accepted_before and state.reason() == "fase_IDLE",
                     "Reconexion tras reinicio con nueva secuencia")
            command("ready")
            wait_for(lambda: state.reason() is None, "Recuperacion de RUNNING tras reconectar")
            report.update(mensajes_aceptados=state.accepted, mensajes_rechazados=state.rejected,
                          conexiones=client.connections)
        finally:
            client.close()
            try:
                stop_process()
            finally:
                log.close()
    return report


if __name__ == "__main__":
    print("Prueba local: simulador oficial + nuestro cliente, sin hardware.")
    print(json.dumps(run_demo(), ensure_ascii=False, indent=2))
