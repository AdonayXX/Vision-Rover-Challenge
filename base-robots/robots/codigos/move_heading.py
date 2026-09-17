"""Inicio de avance cooperativo; importar este archivo no mueve el robot."""
from control_movimiento import MotionController, calibrate_drift, normalize_angle


def move_heading(controller, heading_target=0, speed=0.5, duration=3):
    """Inicia el movimiento; el bucle principal debe llamar controller.update()."""
    controller.start_heading(heading_target, speed, duration)
    return controller
