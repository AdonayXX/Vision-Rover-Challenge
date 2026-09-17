import socket
import json
import math
import time


# =========================================================
# CONFIGURACIÓN
# =========================================================

VISION_IP = "127.0.0.1"
VISION_PORT = 2026

ROBOT_IP = "192.168.40.19"
ROBOT_PORT = 5000

# Cambia esto al ID ArUco de TU robot
ROVER_ID = 0

# Cubo que queremos buscar
CUBE_COLOR = "red"

# Velocidades
FORWARD_SPEED = 0.65
TURN_SPEED = 0.38

# Cuánto error angular permitimos antes de avanzar
ANGLE_TOLERANCE = 12

# Distancia al cubo en CELDAS
# 1 celda = 20 mm
STOP_DISTANCE = 5.0


# =========================================================
# UTILIDADES
# =========================================================

def normalize_angle(angle):
    """Convierte un ángulo al rango -180..180."""
    return (angle + 180) % 360 - 180


def distance(a_col, a_row, b_col, b_row):
    return math.hypot(
        b_col - a_col,
        b_row - a_row
    )


def desired_angle(rover_col, rover_row, target_col, target_row):
    dx = target_col - rover_col

    # row crece hacia abajo en la imagen,
    # pero theta positivo es antihorario.
    dy = -(target_row - rover_row)

    return math.degrees(
        math.atan2(dy, dx)
    ) % 360


# =========================================================
# CONEXIÓN CON EL ROBOT
# =========================================================

robot = socket.socket(
    socket.AF_INET,
    socket.SOCK_STREAM
)

print("Conectando al robot...")

robot.connect(
    (ROBOT_IP, ROBOT_PORT)
)

print("Robot conectado")


def send_robot(command):
    try:
        robot.sendall(
            (command + "\n").encode("utf-8")
        )

        response = robot.recv(64)

        return response.decode().strip()

    except Exception as e:
        print("Error robot:", e)
        return None


def stop():
    send_robot("STOP")


def forward():
    send_robot(
        f"MOTOR {FORWARD_SPEED} {FORWARD_SPEED}"
    )


def turn_left():
    send_robot(
        f"MOTOR {-TURN_SPEED} {TURN_SPEED}"
    )


def turn_right():
    send_robot(
        f"MOTOR {TURN_SPEED} {-TURN_SPEED}"
    )


# =========================================================
# CONEXIÓN CON VISIÓN
# =========================================================

vision = socket.socket(
    socket.AF_INET,
    socket.SOCK_STREAM
)

print("Conectando a visión...")

vision.connect(
    (VISION_IP, VISION_PORT)
)

print("Visión conectada")

buffer = b""


# =========================================================
# LOOP
# =========================================================

try:

    while True:

        data = vision.recv(65536)

        if not data:
            print("Se cerró la conexión de visión")
            break

        buffer += data

        while b"\n" in buffer:

            line, buffer = buffer.split(b"\n", 1)

            if not line.strip():
                continue

            try:
                msg = json.loads(
                    line.decode("utf-8")
                )
            except json.JSONDecodeError:
                continue


            # --------------------------------------------
            # Buscar nuestro rover
            # --------------------------------------------

            rover = None

            for r in msg["rovers"]:

                if r["id"] == ROVER_ID:
                    rover = r
                    break


            # --------------------------------------------
            # Buscar cubo
            # --------------------------------------------

            cube = None

            for c in msg["cubes"]:

                if c["color"] == CUBE_COLOR:
                    cube = c
                    break


            if rover is None:
                print("No veo mi rover")
                stop()
                continue


            if cube is None:
                print(
                    "No veo el cubo",
                    CUBE_COLOR
                )
                stop()
                continue


            # No usar información demasiado vieja
            if rover["age_ms"] > 500:
                print("Posición del robot vieja")
                stop()
                continue

            if cube["age_ms"] > 500:
                print("Posición del cubo vieja")
                stop()
                continue


            # --------------------------------------------
            # Geometría
            # --------------------------------------------

            d = distance(
                rover["col"],
                rover["row"],
                cube["col"],
                cube["row"]
            )

            target_angle = desired_angle(
                rover["col"],
                rover["row"],
                cube["col"],
                cube["row"]
            )

            error = normalize_angle(
                target_angle - rover["theta"]
            )


            print(
                f"Distancia: {d:.2f} | "
                f"theta={rover['theta']:.1f} | "
                f"objetivo={target_angle:.1f} | "
                f"error={error:.1f}"
            )


            # --------------------------------------------
            # Llegamos
            # --------------------------------------------

            if d < STOP_DISTANCE:

                stop()

                print("✅ Llegué al cubo")

                time.sleep(0.1)

                continue


            # --------------------------------------------
            # Girar
            # --------------------------------------------

            if error > ANGLE_TOLERANCE:

                print("← Girando izquierda")

                turn_left()


            elif error < -ANGLE_TOLERANCE:

                print("→ Girando derecha")

                turn_right()


            # --------------------------------------------
            # Avanzar
            # --------------------------------------------

            else:

                print("↑ Avanzando")

                forward()


            # El watchdog del robot es 0.5 s.
            # Le estamos enviando comandos continuamente.
            time.sleep(0.05)


except KeyboardInterrupt:

    print("\nDeteniendo...")


finally:

    stop()

    vision.close()
    robot.close()

    print("Robot detenido")