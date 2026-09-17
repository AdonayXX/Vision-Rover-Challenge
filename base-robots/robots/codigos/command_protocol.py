"""Comandos de pruebas: una línea ASCII por comando, separador canónico |.

Se aceptan espacios para compatibilidad con el receptor anterior.
KEEPALIVE renueva el permiso de un movimiento activo; PING sólo consulta.
Este protocolo no modifica el contrato de telemetría de visión.
"""
import math

PING = "PING"
STOP = "STOP"
MOTOR = "MOTOR"
TURN = "TURN"
HEADING = "HEADING"
KEEPALIVE = "KEEPALIVE"
MAX_LINE = 128


def finite(value):
    value = float(value)
    if not math.isfinite(value):
        raise ValueError("Se requiere un numero finito")
    return value


def limit(value, minimum, maximum):
    return max(minimum, min(maximum, finite(value)))


def valid_motor_speed(value):
    return math.isfinite(value) and -1 <= value <= 1


def parse_command(message):
    """Valida antes de permitir que un valor alcance los motores."""
    try:
        if not isinstance(message, str) or len(message) > MAX_LINE:
            raise ValueError("Mensaje invalido o demasiado largo")
        parts = message.strip().split("|") if "|" in message else message.split()
        if not parts:
            raise ValueError("Mensaje vacio")
        command = parts[0].strip().upper()
        fields = {PING: (), STOP: (), KEEPALIVE: (), MOTOR: ("left", "right"),
                  TURN: ("angle", "speed"), HEADING: ("heading", "speed", "duration")}
        if command not in fields or len(parts) != len(fields[command]) + 1:
            raise ValueError("Comando o cantidad de parametros invalida")
        result = {"valid": True, "command": command}
        for key, value in zip(fields[command], parts[1:]):
            result[key] = finite(value)
        if command == MOTOR and not all(valid_motor_speed(result[k]) for k in ("left", "right")):
            raise ValueError("Motores fuera de [-1, 1]")
        if command == TURN and not 0 < result["speed"] <= 1:
            raise ValueError("Velocidad de giro fuera de (0, 1]")
        if command == HEADING:
            if not valid_motor_speed(result["speed"]) or result["duration"] <= 0:
                raise ValueError("Velocidad o duracion invalida")
        return result
    except (ValueError, TypeError, OverflowError) as error:
        return {"valid": False, "error": str(error)}


def _build(command, *values):
    message = "|".join([command] + [str(finite(v)) for v in values])
    parsed = parse_command(message)
    if not parsed["valid"]:
        raise ValueError(parsed["error"])
    return message


def cmd_ping():
    return PING


def cmd_stop():
    return STOP


def cmd_keepalive():
    return KEEPALIVE


def cmd_motor(left, right):
    return _build(MOTOR, left, right)


def cmd_turn(angle, speed=0.30):
    return _build(TURN, angle, speed)


def cmd_heading(heading, speed=0.5, duration=1.0):
    return _build(HEADING, heading, speed, duration)
