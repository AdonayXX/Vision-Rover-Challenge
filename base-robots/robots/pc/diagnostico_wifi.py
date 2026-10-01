"""Compara STOP/PING con consultas SENSORS. Nunca envia movimiento."""
import argparse
import json
from pathlib import Path
import statistics
import time

from prueba_transporte_cubo import RobotClient


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--robot-ip", required=True)
    parser.add_argument("--segundos", type=float, default=10,
                        help="Duracion de cada una de las dos fases (2 a 30 s)")
    parser.add_argument("--log", type=Path)
    args = parser.parse_args()
    if not 2 <= args.segundos <= 30:
        parser.error("--segundos debe estar entre 2 y 30")
    client = RobotClient(args.robot_ip)
    records = []
    success = False
    started = time.monotonic()
    try:
        client.connect()
        print("STOP confirmado. Diagnostico sin movimiento.", flush=True)
        for phase in ("PING_STOP", "SENSORS_STOP"):
            print("Fase:", phase, flush=True)
            deadline = time.monotonic() + args.segundos
            times = []
            while time.monotonic() < deadline:
                at = time.monotonic()
                record = {"fase": phase, "t_s": round(at - started, 3)}
                if phase == "PING_STOP":
                    client.send("PING", force=True)
                else:
                    status = client.sensors()
                    record.update({k: status.get(k) for k in
                                   ("color_seq", "errors", "motion_reason", "distance_mm")})
                client.send("STOP", force=True)
                elapsed = (time.monotonic() - at) * 1000
                times.append(elapsed)
                record["respuesta_ms"] = round(elapsed, 1)
                records.append(record)
                time.sleep(.1)
            print("{}: {} ciclos, mediana {:.0f} ms, maximo {:.0f} ms".format(
                phase, len(times), statistics.median(times), max(times)), flush=True)
        success = True
        return 0
    except (OSError, ValueError) as exc:
        records.append({"error": str(exc), "t_s": round(time.monotonic() - started, 3)})
        print("ERROR:", exc, flush=True)
        return 1
    except KeyboardInterrupt:
        print("Diagnostico interrumpido.", flush=True)
        return 130
    finally:
        connected = client.sock is not None
        stopped = client.close()
        print("STOP final confirmado:", stopped, flush=True)
        if args.log:
            args.log.write_text(json.dumps({"completo": success,
                "hubo_conexion": connected, "stop_final": stopped,
                "registros": records}, indent=2), encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
