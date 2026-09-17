"""Inicio de giro cooperativo; importar este archivo no inicializa hardware."""
from control_movimiento import MotionController, calibrate_drift


def turn_angle(controller, degrees, speed=0.30):
    """Grados relativos, positivos antihorarios; avanzar con controller.update()."""
    controller.start_turn(degrees, speed)
    return controller
