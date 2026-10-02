"""Muestra cómo lee la PLACA la telemetría de visión. Nunca envía movimiento.

La placa se conecta sola a la visión (vision_host en config_robot.json) y mide
cuántos mensajes por segundo decodifica, cuánto tarda y cuánta memoria le
queda. Este script solo pregunta esas cifras por el puerto de comandos.
"""
import argparse
import json
import time

from prueba_transporte_cubo import RobotClient


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--robot-ip", required=True)
    parser.add_argument("--segundos", type=float, default=30)
    args = parser.parse_args()
    client = RobotClient(args.robot_ip, wait_seconds=30)
    client.connect()  # Envía STOP; después solo SENSORS.
    print("Conectado; STOP confirmado. Solo lectura.", flush=True)
    fin = time.monotonic() + args.segundos
    ultima = None
    try:
        while time.monotonic() < fin:
            status = json.loads(client._exchange("SENSORS"))
            vision = status.get("vision")
            if vision is None:
                print("La placa no lee vision: pon vision_host en config_robot.json y sube "
                      "cliente_vision_rover.py, telemetria.py y wifi_command_receiver.py.")
                return 1
            if vision != ultima:
                print(json.dumps(vision), flush=True)
                ultima = vision
            time.sleep(1)
    finally:
        client.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
