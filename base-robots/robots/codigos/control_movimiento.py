"""Control cooperativo: update() ejecuta un paso y devuelve el control.

No importa hardware ni lo crea. El propietario llama update() frecuentemente
y garantiza stop() en su finally. Ángulos relativos positivos: antihorario.
"""
import math
import time
from command_protocol import finite, limit


def normalize_angle(angle):
    return (finite(angle) + 180) % 360 - 180


class MotionController:
    def __init__(self, robot, sensor=None, drift=0.0, clock=time.monotonic,
                 gyro_sign=1, left_sign=1, right_sign=1,
                 left_gain=1.0, right_gain=1.0, max_step=0.25,
                 turn_timeout=10.0, max_duration=30.0,
                 kp=0.015, ki=0.0005, kd=0.002, max_correction=0.30,
                 tolerance=2.0, slow_angle=30.0, slow_speed=0.15):
        self.robot, self.sensor, self.clock = robot, sensor, clock
        self.drift = finite(drift)
        for value in (gyro_sign, left_sign, right_sign):
            if value not in (-1, 1):
                raise ValueError("Los signos deben ser -1 o 1")
        for value in (left_gain, right_gain, max_step, turn_timeout, max_duration,
                      tolerance, slow_angle, slow_speed):
            if finite(value) <= 0:
                raise ValueError("Ganancias, limites y tiempos deben ser positivos")
        for value in (kp, ki, kd, max_correction):
            if finite(value) < 0:
                raise ValueError("PID y correccion deben ser no negativos")
        self.gyro_sign, self.left_sign, self.right_sign = gyro_sign, left_sign, right_sign
        self.left_gain, self.right_gain = left_gain, right_gain
        self.max_step, self.turn_timeout, self.max_duration = max_step, turn_timeout, max_duration
        self.kp, self.ki, self.kd = kp, ki, kd
        self.max_correction = max_correction
        self.tolerance, self.slow_angle, self.slow_speed = tolerance, slow_angle, slow_speed
        self.mode = None
        self.reason = "inicio"
        self.stop()

    def _drive(self, left, right):
        self.robot.motor_1.throttle = limit(left * self.left_gain * self.left_sign, -1, 1)
        self.robot.motor_2.throttle = limit(right * self.right_gain * self.right_sign, -1, 1)

    def stop(self, reason="stop"):
        self.mode = None
        self.reason = reason
        # Intentar ambos motores incluso si uno falla al escribir.
        try:
            self.robot.motor_1.throttle = 0
        finally:
            self.robot.motor_2.throttle = 0

    def _begin(self, mode):
        self.stop()
        if mode != "MOTOR" and self.sensor is None:
            raise ValueError("Movimiento angular requiere IMU")
        self.started = self.previous = self.clock()
        self.angle = self.integral = 0.0
        self.previous_error = None
        self.mode, self.reason = mode, "activo"

    def start_motor(self, left, right):
        self.stop()
        left, right = finite(left), finite(right)
        if not -1 <= left <= 1 or not -1 <= right <= 1:
            raise ValueError("Velocidad fuera de rango")
        self._begin("MOTOR")
        self.left, self.right = left, right

    def start_turn(self, degrees, speed=0.30):
        self.stop()
        degrees, speed = finite(degrees), finite(speed)
        if not 0 < speed <= 1:
            raise ValueError("Velocidad de giro invalida")
        self._begin("TURN")
        self.target, self.speed = degrees, speed
        if abs(degrees) <= self.tolerance:
            self.stop("completado")

    def start_heading(self, heading=0, speed=0.5, duration=1):
        self.stop()
        heading, speed, duration = finite(heading), finite(speed), finite(duration)
        if not -1 <= speed <= 1 or not 0 < duration <= self.max_duration:
            raise ValueError("Velocidad o duracion fuera de rango")
        self._begin("HEADING")
        self.target, self.speed, self.duration = normalize_angle(heading), speed, duration

    def update(self):
        """Un paso, sin sleep: termina o se detiene ante demora/fallo de IMU."""
        if self.mode is None:
            return
        try:
            now = self.clock()
            dt = now - self.previous
            if dt < 0 or dt > self.max_step:
                self.stop("ciclo_tardio")
                return
            if self.mode == "MOTOR":
                self.previous = now
                self._drive(self.left, self.right)
                return
            if self.mode == "TURN" and now - self.started >= self.turn_timeout:
                self.stop("timeout_giro")
                return
            if self.mode == "HEADING" and now - self.started >= self.duration:
                self.stop("completado")
                return
            if dt == 0:
                return
            self.previous = now
            rate = (finite(self.sensor.gyro[2]) - self.drift) * self.gyro_sign
            self.angle += rate * (180 / math.pi) * dt
            if self.mode == "TURN":
                direction = 1 if self.target > 0 else -1
                # El giro contrario RESTA progreso; el ruido no suma distancia.
                remaining = abs(self.target) - direction * self.angle
                if remaining <= self.tolerance:
                    self.stop("completado")
                    return
                speed = min(self.speed, self.slow_speed) if remaining <= self.slow_angle else self.speed
                self._drive(-speed * direction, speed * direction)
            else:
                error = normalize_angle(self.target - self.angle)
                self.integral = limit(self.integral + error * dt, -100, 100)
                derivative = 0 if self.previous_error is None else normalize_angle(error - self.previous_error) / dt
                self.previous_error = error
                correction = limit(self.kp * error + self.ki * self.integral + self.kd * derivative,
                                   -self.max_correction, self.max_correction)
                self._drive(self.speed - correction, self.speed + correction)
        except Exception:
            self.stop("error_control")
            raise


def calibrate_drift(sensor, seconds=3, clock=time.monotonic, sleep=time.sleep):
    """Calibración de arranque con motores detenidos; falla si no estuvo quieto."""
    seconds = finite(seconds)
    if seconds <= 0:
        raise ValueError("Duracion de calibracion invalida")
    start, total, samples = clock(), 0.0, 0
    while clock() - start < seconds:
        rate = finite(sensor.gyro[2])
        if abs(rate) >= 0.05:
            raise ValueError("Mantener el robot quieto durante la calibracion")
        total += rate
        samples += 1
        sleep(0.005)
    if not samples:
        raise ValueError("Sin muestras para calibrar")
    return total / samples
