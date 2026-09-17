"""Prueba manual de IdeaBoard por TCP. Sin paquetes externos ni cámara."""
import argparse
import math
import socket
import time


class Client:
    def __init__(self, sock):
        self.sock = sock
        self.buffer = b""

    def command(self, command):
        self.sock.sendall((command + "\n").encode("ascii"))
        while b"\n" not in self.buffer:
            part = self.sock.recv(128)
            if not part:
                raise ConnectionError("La placa cerro la conexion")
            self.buffer += part
            if len(self.buffer) > 512:
                raise ValueError("Respuesta demasiado larga")
        line, self.buffer = self.buffer.split(b"\n", 1)
        if line.strip() != b"OK":
            raise ValueError("La placa rechazo el comando: " + repr(line))


def exercise(client, test="conexion", motor=1, power=0.2, duration=0.3,
             sleep=time.sleep):
    if test not in ("conexion", "pulso", "watchdog", "desconexion"):
        raise ValueError("Prueba desconocida")
    if motor not in (1, 2) or not math.isfinite(power) or not 0 < abs(power) <= 0.3:
        raise ValueError("Motor 1 o 2; potencia entre -0.3 y 0.3, distinta de cero")
    if not math.isfinite(duration) or not 0 < duration <= 0.4:
        raise ValueError("Duracion entre 0 y 0.4 segundos")
    try:
        client.command("STOP")
        client.command("PING")
        if test == "conexion":
            return
        left, right = (power, 0) if motor == 1 else (0, power)
        client.command("MOTOR|{}|{}".format(left, right))
        if test == "desconexion":
            # Cierre intencional, sin STOP: comprueba la ruta EOF del receptor.
            client.sock.close()
            return
        if test == "watchdog":
            # PING mantiene trafico pero NO renueva el permiso de movimiento.
            for _ in range(10):
                sleep(0.1)
                client.command("PING")
        else:
            sleep(duration)
    finally:
        try:
            client.command("STOP")
        except (OSError, ValueError):
            # El watchdog de la placa es quien debe parar si ya no hay enlace.
            pass


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("host", help="IP mostrada por la placa en Thonny")
    parser.add_argument("--port", type=int, default=5000)
    parser.add_argument("--test", choices=("conexion", "pulso", "watchdog", "desconexion"), default="conexion")
    parser.add_argument("--motor", type=int, choices=(1, 2), default=1)
    parser.add_argument("--power", type=float, default=0.2)
    parser.add_argument("--duration", type=float, default=0.3)
    args = parser.parse_args()
    print("Banco: ruedas levantadas, alimentacion al alcance. Prueba:", args.test)
    try:
        with socket.create_connection((args.host, args.port), timeout=1) as sock:
            exercise(Client(sock), args.test, args.motor, args.power, args.duration)
    except (OSError, ValueError) as error:
        parser.exit(1, "Fallo: {}. Comprueba que los motores esten detenidos.\n".format(error))
    print("Intercambio terminado. OK confirma recepcion; observa el motor para validar movimiento y parada.")


if __name__ == "__main__":
    main()
