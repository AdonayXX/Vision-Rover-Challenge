"""Mira una ronda autónoma SIN intervenir (incremento 3).

Sólo pregunta SENSORS: nunca manda STOP ni movimiento. Con la ronda en marcha
conectarse o cerrar este script no detiene al rover. Pueden mirarse los dos
rovers a la vez en dos terminales.

En competencia NO se usa (11.2.7): es una herramienta de desarrollo.

    python -B pc/ver_ronda.py --robot-ip 10.50.42.120 --robot-id 10
"""
import argparse
import json
import socket
import time


def preguntar(sock, buffer):
    sock.sendall(b"SENSORS\n")
    while b"\n" not in buffer[0]:
        trozo = sock.recv(512)
        if not trozo:
            raise ConnectionError("El rover cerro la conexion")
        buffer[0] += trozo
    linea, buffer[0] = buffer[0].split(b"\n", 1)
    return json.loads(linea)


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--robot-ip", required=True)
    p.add_argument("--robot-id", type=int, required=True)
    p.add_argument("--port", type=int, default=5000)
    args = p.parse_args()

    anterior, ultimo_print = None, 0
    while True:
        try:
            with socket.create_connection((args.robot_ip, args.port), timeout=10) as sock:
                buffer = [b""]
                estado = preguntar(sock, buffer)
                if estado.get("robot_id") not in (None, args.robot_id):
                    print("En {} responde el rover {}, no el {}".format(
                        args.robot_ip, estado.get("robot_id"), args.robot_id))
                    return 1
                print("Mirando al rover {} (Ctrl+C sale sin tocarlo)".format(args.robot_id), flush=True)
                inicio = time.monotonic()
                while True:
                    estado = preguntar(sock, buffer)
                    mision = estado.get("mision") or {}
                    ronda = mision.get("ronda") or {}
                    clave = (ronda.get("estado"), ronda.get("fase"), ronda.get("actual"),
                             tuple(ronda.get("hechos") or ()), mision.get("estado"), mision.get("motivo"))
                    if clave != anterior or time.monotonic() - ultimo_print > 5:
                        print("{:6.1f}s fase={} ronda={} cubos={} hechos={} actual={} | mision={} {}{}".format(
                            time.monotonic() - inicio, ronda.get("fase"), ronda.get("estado"),
                            ronda.get("mis_cubos"), ronda.get("hechos"), ronda.get("actual"),
                            mision.get("estado"), mision.get("motivo") or "",
                            "  fallos={}".format(ronda["fallos"]) if ronda.get("fallos") else ""), flush=True)
                        anterior, ultimo_print = clave, time.monotonic()
                    time.sleep(.3)
        except KeyboardInterrupt:
            print("Fin (el rover sigue solo).")
            return 0
        except (OSError, ConnectionError, ValueError) as error:
            print("Sin conexion ({}); reintento en 2 s...".format(error), flush=True)
            time.sleep(2)


if __name__ == "__main__":
    raise SystemExit(main())
