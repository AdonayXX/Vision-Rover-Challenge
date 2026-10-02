# code.py  —  CenfoBot Rover: comandos por BLE con movimientos precisos por IMU
#
# Guardar como code.py en la raíz de CIRCUITPY, junto con ideaboard.py
# y las librerías adafruit_ble, adafruit_lsm6ds, adafruit_motor, neopixel,
# simpleio (carpeta lib/).
#
# Basado en los códigos del Vision Rover Challenge:
#   move_heading.py, turn_angle.py, motor_calibration.py, command_protocol.py
#
# Diferencias clave con esos ejemplos:
#   · El rover integra el giroscopio TODO el tiempo, no solo durante un
#     movimiento. Así existe un rumbo global y los giros se encadenan sin
#     acumular error: TURN|90 cuatro veces cierra un cuadrado.
#   · Nada bloquea. Un ciclo único lee BLE, avanza el movimiento en curso y
#     envía telemetría, de modo que STOP interrumpe en cualquier momento.
#   · Los giros son de lazo cerrado sobre el rumbo (con rampa de frenado y
#     verificación de asentamiento), no de "acumular hasta llegar".
#
# CONVENCIÓN DE ÁNGULOS (igual que test_motores.py: right() = giro horario)
#   rumbo positivo = giro a la DERECHA (horario visto desde arriba)
#   rumbo 0       = orientación al encender o tras ZERO
#   rango reportado: -180 a +180
#
# PROTOCOLO (texto, una orden por línea terminada en \n)
#   Inmediatas:
#     STOP                  detiene todo y vacía la cola
#     MOTOR|izq|der         control directo -1..1 (watchdog 0.6 s)
#     PING                  responde "# PONG"
#     STAT                  reporta drift, ganancias y estado
#     SET|clave|valor       ajusta un parámetro (ver PARAMETROS)
#   En cola (se ejecutan una tras otra):
#     FWD|seg|vel           avanza recto sobre el rumbo de referencia
#     BACK|seg|vel          retrocede recto sobre el rumbo de referencia
#     TURN|grados|vel       gira relativo al rumbo de referencia
#     FACE|rumbo|vel        gira hasta un rumbo absoluto
#     HEADING|rumbo|vel|seg avanza manteniendo un rumbo absoluto (repo)
#     WAIT|seg              espera
#     ZERO                  el rumbo actual pasa a ser 0
#     CAL                   recalibra el drift (el rover debe estar quieto)
#   "vel" es opcional en FWD, BACK, TURN y FACE.
#
# MENSAJES DEL ROVER (líneas < 20 bytes, regla del skill BLE)
#   H,rumbo,modo,cola     telemetría a 5 Hz. modo: I M T D W C
#   R,rumbo               rumbo de referencia (cuando cambia y cada 1 s)
#   # texto               confirmaciones, fin de movimiento y errores

import time
import math
import board

from ideaboard import IdeaBoard
from adafruit_lsm6ds.lsm6ds3trc import LSM6DS3TRC

from adafruit_ble import BLERadio
from adafruit_ble.advertising.standard import ProvideServicesAdvertisement
from adafruit_ble.services.nordic import UARTService


# --------------------------------------------------
# CONFIGURACION
# --------------------------------------------------

NOMBRE_BLE = "Rover1"   # ≤ 8 caracteres. Cambiarlo en cada versión del archivo.

# Resultado de motor_calibration.py. Multiplica a motor_2.
RIGHT_GAIN = 1.0

# Signo del giroscopio. Con la IMU boca arriba, gyro Z es positivo al girar
# antihorario, por eso -1 hace que la derecha sea positiva.
# PRUEBA: gira el rover con la mano hacia la derecha; el rumbo en la app debe
# SUBIR. Si baja, cambia esto a 1.0.
GYRO_SIGN = -1.0

# Corrección de escala del giroscopio. Para medirla: ZERO, gira el rover a
# mano exactamente 360° (contra una marca de la cuadrícula) y lee el rumbo.
# Si marca 352°, GYRO_SCALE = 360 / 352 = 1.023
GYRO_SCALE = 1.0

PARAMETROS = {
    # Avance recto (PID de move_heading.py)
    "KP": 0.015,
    "KI": 0.0005,
    "KD": 0.002,
    "MAXC": 0.30,    # corrección máxima
    "RAMPA": 0.25,   # segundos de arranque suave (menos patinaje)
    # Giros
    "TVEL": 0.35,    # velocidad de giro por defecto
    "TMIN": 0.17,    # mínima que vence la fricción (ajustar al piso)
    "TLENTO": 35.0,  # grados antes del objetivo en que empieza a frenar
    "TOL": 1.5,      # tolerancia en grados
    # Generales
    "VEL": 0.5,      # velocidad de avance por defecto
    "RG": RIGHT_GAIN,
    "GS": GYRO_SCALE,
}

WATCHDOG_MOTOR = 0.6     # s sin MOTOR -> se detiene
PERIODO_TELEMETRIA = 0.2
COLA_MAX = 30
AUTODRIFT = True         # afina el drift mientras está quieto


# --------------------------------------------------
# HARDWARE
# --------------------------------------------------

ib = IdeaBoard()
sensor = LSM6DS3TRC(board.I2C(), 0x6B)

try:
    from adafruit_lsm6ds import Rate, GyroRange
    # 500 °/s basta para el rover y da 4x más resolución que 2000 °/s.
    sensor.gyro_range = GyroRange.RANGE_500_DPS
    sensor.gyro_data_rate = Rate.RATE_416_HZ
except Exception as e:  # noqa: BLE001
    print("Config IMU por defecto:", e)

RAD_A_GRAD = 180 / math.pi


def limit(v, lo, hi):
    return max(lo, min(hi, v))


def normalize_angle(a):
    while a > 180:
        a -= 360
    while a <= -180:
        a += 360
    return a


def motores(izq, der):
    ib.motor_1.throttle = limit(izq, -1.0, 1.0)
    ib.motor_2.throttle = limit(der * PARAMETROS["RG"], -1.0, 1.0)


def stop_motores():
    # throttle = 0 en adafruit_motor frena (ambos PWM activos), no deja rodar.
    ib.motor_1.throttle = 0
    ib.motor_2.throttle = 0


def pixel(color):
    try:
        ib.pixel = color
    except Exception:  # noqa: BLE001
        pass


# --------------------------------------------------
# GIROSCOPIO
# --------------------------------------------------

def gyro_z():
    return sensor.gyro[2]


def calibrar_drift(segundos=3.0):
    """Promedio del gyro Z en reposo (igual que en el repo)."""
    print("Calibrando giroscopio. No mover el robot.")
    total = 0.0
    n = 0
    t0 = time.monotonic()
    while time.monotonic() - t0 < segundos:
        g = gyro_z()
        if abs(g) < 0.05:
            total += g
            n += 1
        time.sleep(0.005)
    d = total / n if n else 0.0
    print("Drift:", d, "rad/s")
    return d


# --------------------------------------------------
# BLE
# --------------------------------------------------

ble = BLERadio()
ble.name = NOMBRE_BLE
uart = UARTService()
anuncio = ProvideServicesAdvertisement(uart)

sin_in_waiting = False


def leer_ble():
    """Lectura no bloqueante. readline() bloquearía hasta 1 s con una línea
    incompleta, y eso congelaría el control de los motores."""
    global sin_in_waiting
    if sin_in_waiting:
        return None
    try:
        n = uart.in_waiting
    except AttributeError:
        sin_in_waiting = True
        print("Esta versión de adafruit_ble no tiene in_waiting")
        return None
    if n:
        return uart.read(n)
    return None


def enviar(texto):
    """Una línea < 20 bytes = una notificación."""
    linea = texto[:19] + "\n"
    try:
        uart.write(linea.encode("utf-8"))
    except Exception as e:  # noqa: BLE001
        print("TX:", e)


def anunciar():
    try:
        ble.start_advertising(anuncio)
    except Exception:  # noqa: BLE001
        pass  # ya estaba anunciando


# --------------------------------------------------
# ESTADO DEL ROVER
# --------------------------------------------------

rumbo = 0.0          # rumbo integrado, SIN envolver (permite giros de 720°)
rumbo_ref = 0.0      # rumbo al que deben referirse FWD/BACK/TURN
velocidad_ang = 0.0  # °/s, convención del rover (derecha positiva)
drift = 0.0

modo = "I"           # I quieto, M manual, T giro, D avance, W espera, C calib
cola = []
mov = {}             # datos del movimiento en curso
t_ultimo_motor = 0.0


def fmt(v):
    return "{:.1f}".format(v)


def objetivo_cercano(rumbo_abs):
    """Equivalente sin envolver de un rumbo absoluto, por el camino corto."""
    return rumbo + normalize_angle(rumbo_abs - normalize_angle(rumbo))


def terminar(mensaje=None):
    global modo, mov
    stop_motores()
    modo = "I"
    mov = {}
    if mensaje:
        enviar(mensaje)


def detener_todo():
    global cola, rumbo_ref
    cola = []
    rumbo_ref = rumbo
    terminar()
    enviar("# STOP")


# ---------- inicio de cada movimiento ----------

def iniciar(cmd):
    global modo, mov, rumbo, rumbo_ref
    ahora = time.monotonic()
    nombre = cmd[0]

    if nombre in ("FWD", "BACK", "HEADING"):
        if nombre == "HEADING":
            objetivo = objetivo_cercano(cmd[1])
            vel, dur = cmd[2], cmd[3]
        else:
            objetivo = rumbo_ref
            dur = cmd[1]
            vel = cmd[2] if cmd[2] is not None else PARAMETROS["VEL"]
            vel = abs(vel) * (-1 if nombre == "BACK" else 1)
        rumbo_ref = objetivo
        modo = "D"
        mov = {"obj": objetivo, "vel": vel, "dur": dur, "t0": ahora,
               "integral": 0.0}

    elif nombre in ("TURN", "FACE"):
        if nombre == "TURN":
            objetivo = rumbo_ref + cmd[1]
        else:
            objetivo = objetivo_cercano(cmd[1])
        vel = cmd[2] if cmd[2] is not None else PARAMETROS["TVEL"]
        rumbo_ref = objetivo
        modo = "T"
        tiempo_max = 3.0 + abs(objetivo - rumbo) / 40.0
        mov = {"obj": objetivo, "vel": abs(vel), "t0": ahora,
               "tmax": tiempo_max, "t_ok": None}

    elif nombre == "WAIT":
        modo = "W"
        mov = {"dur": cmd[1], "t0": ahora}

    elif nombre == "ZERO":
        rumbo = 0.0
        rumbo_ref = 0.0
        enviar("# fin ZERO")

    elif nombre == "CAL":
        stop_motores()
        modo = "C"
        mov = {"t0": ahora, "suma": 0.0, "n": 0}


# ---------- avance de cada movimiento (se llama en cada ciclo) ----------

def paso_avance(ahora, dt):
    t = ahora - mov["t0"]
    if t >= mov["dur"]:
        terminar("# fin " + fmt(normalize_angle(rumbo)))
        return
    error = mov["obj"] - rumbo   # >0: hay que girar a la derecha
    mov["integral"] = limit(mov["integral"] + error * dt, -100, 100)
    correccion = (PARAMETROS["KP"] * error
                  + PARAMETROS["KI"] * mov["integral"]
                  - PARAMETROS["KD"] * velocidad_ang)  # D sobre la medición
    correccion = limit(correccion, -PARAMETROS["MAXC"], PARAMETROS["MAXC"])
    escala = min(1.0, t / PARAMETROS["RAMPA"]) if PARAMETROS["RAMPA"] > 0 else 1.0
    v = mov["vel"] * escala
    # motor_1 es la rueda izquierda: izq > der gira a la derecha,
    # tanto avanzando como retrocediendo.
    motores(v + correccion, v - correccion)


def paso_giro(ahora):
    error = mov["obj"] - rumbo
    tol = PARAMETROS["TOL"]
    if abs(error) <= tol:
        stop_motores()
        # Asentado: dentro de tolerancia y casi sin velocidad durante 120 ms.
        if abs(velocidad_ang) < 15:
            if mov["t_ok"] is None:
                mov["t_ok"] = ahora
            elif ahora - mov["t_ok"] > 0.12:
                terminar("# fin " + fmt(normalize_angle(rumbo)))
                return
        else:
            mov["t_ok"] = None
    else:
        mov["t_ok"] = None
        tmin = PARAMETROS["TMIN"]
        vmax = max(mov["vel"], tmin)
        f = min(1.0, abs(error) / PARAMETROS["TLENTO"])
        v = tmin + (vmax - tmin) * f
        if error > 0:
            motores(v, -v)      # derecha, como right() en test_motores.py
        else:
            motores(-v, v)
    if ahora - mov["t0"] > mov["tmax"]:
        terminar("# err tiempo " + fmt(error))


def paso_calibracion(ahora, g):
    global drift, modo
    if abs(g) < 0.05:
        mov["suma"] += g
        mov["n"] += 1
    if ahora - mov["t0"] >= 2.5:
        if mov["n"]:
            drift = mov["suma"] / mov["n"]
        terminar("# fin CAL")
        print("Drift:", drift)


# --------------------------------------------------
# COMANDOS
# --------------------------------------------------

def num(partes, i, defecto=None):
    if len(partes) > i and partes[i] != "":
        return float(partes[i])
    if defecto is None:
        raise ValueError
    return defecto


def procesar_comando(linea):
    global modo, t_ultimo_motor, cola
    linea = linea.strip()
    if not linea:
        return
    partes = linea.split("|")
    c = partes[0].upper()
    print("RX:", linea)

    try:
        # ---------- inmediatas ----------
        if c == "STOP":
            detener_todo()
            return
        if c == "PING":
            enviar("# PONG " + NOMBRE_BLE)
            return
        if c == "MOTOR":
            izq = limit(num(partes, 1), -1, 1)
            der = limit(num(partes, 2), -1, 1)
            if modo != "M":
                cola = []
                terminar()
                modo = "M"
            motores(izq, der)
            t_ultimo_motor = time.monotonic()
            return
        if c == "STAT":
            enviar("# drift " + "{:.5f}".format(drift))
            enviar("# RG {} GS {}".format(PARAMETROS["RG"], PARAMETROS["GS"]))
            enviar("# KP {}".format(PARAMETROS["KP"]))
            enviar("# TMIN {}".format(PARAMETROS["TMIN"]))
            return
        if c == "SET":
            clave = partes[1].upper()
            if clave not in PARAMETROS:
                enviar("# err clave " + clave)
                return
            PARAMETROS[clave] = num(partes, 2)
            enviar("# {}={}".format(clave, PARAMETROS[clave]))
            return

        # ---------- en cola ----------
        if c in ("FWD", "BACK"):
            dur = num(partes, 1)
            vel = num(partes, 2, -99)
            cmd = (c, max(0.0, dur), None if vel == -99 else limit(vel, 0, 1))
        elif c in ("TURN", "FACE"):
            ang = num(partes, 1)
            vel = num(partes, 2, -99)
            cmd = (c, ang, None if vel == -99 else limit(vel, 0, 1))
        elif c == "HEADING":
            cmd = (c, num(partes, 1), limit(num(partes, 2), -1, 1),
                   max(0.0, num(partes, 3)))
        elif c == "WAIT":
            cmd = (c, max(0.0, num(partes, 1)))
        elif c in ("ZERO", "CAL"):
            cmd = (c,)
        else:
            enviar("# err ? " + c)
            return
    except (ValueError, IndexError):
        enviar("# err params " + c)
        return

    if len(cola) >= COLA_MAX:
        enviar("# err cola llena")
        return
    if modo == "M":           # un comando preciso sale del modo manual
        terminar()
    cola.append(cmd)
    enviar("# ok " + c)


# --------------------------------------------------
# ARRANQUE
# --------------------------------------------------

stop_motores()

# Autoprueba del indicador: si no se ve blanco 1 s, el latido no sirve
# como diagnóstico.
pixel((80, 80, 80))
time.sleep(1)
pixel((255, 0, 0))
drift = calibrar_drift(3.0)
pixel((0, 0, 0))

print("Nombre BLE:", ble.name)
try:
    print("Anuncio:", len(bytes(anuncio)), "de 31 bytes")
except Exception:  # noqa: BLE001
    pass
anunciar()
print("Anunciando")

COLORES = {
    "I": (0, 0, 60), "M": (0, 80, 80), "T": (90, 0, 90),
    "D": (90, 70, 0), "W": (40, 40, 40), "C": (120, 0, 0),
}

buffer_rx = ""
t_prev = time.monotonic()
t_tel = 0.0
t_ref = 0.0
t_anuncio = t_prev
t_latido = 0.0
latido = False
ref_enviada = None
conectado_antes = False


# --------------------------------------------------
# CICLO UNICO (sin depender de ble.connected para enviar)
# --------------------------------------------------

while True:
    ahora = time.monotonic()
    dt = ahora - t_prev
    t_prev = ahora

    # ---------- IMU: integrar siempre ----------
    try:
        g = gyro_z()
    except Exception as e:  # noqa: BLE001
        print("IMU:", e)
        g = drift
    velocidad_ang = (GYRO_SIGN * PARAMETROS["GS"]
                     * (g - drift) * RAD_A_GRAD)
    quieto = modo in ("I", "W") and abs(velocidad_ang) < 0.6
    if quieto:
        # Reposo: no integrar ruido, y afinar el drift lentamente.
        if AUTODRIFT and abs(g - drift) < 0.01:
            drift += 0.002 * (g - drift)
    elif modo != "C" and 0 < dt < 0.1:
        rumbo += velocidad_ang * dt

    # ---------- BLE: comandos ----------
    datos = leer_ble()
    if datos:
        try:
            buffer_rx += datos.decode("utf-8")
        except UnicodeError:
            buffer_rx = ""
        while "\n" in buffer_rx:
            linea, buffer_rx = buffer_rx.split("\n", 1)
            procesar_comando(linea)
        if len(buffer_rx) > 80:
            buffer_rx = ""

    # ---------- movimiento en curso ----------
    if modo == "M":
        if ahora - t_ultimo_motor > WATCHDOG_MOTOR:
            rumbo_ref = rumbo
            terminar()
    elif modo == "D":
        paso_avance(ahora, dt)
    elif modo == "T":
        paso_giro(ahora)
    elif modo == "W":
        if ahora - mov["t0"] >= mov["dur"]:
            terminar("# fin WAIT")
    elif modo == "C":
        paso_calibracion(ahora, g)

    if modo == "I" and cola:
        iniciar(cola.pop(0))

    # ---------- seguridad: desconexión ----------
    conectado = ble.connected
    if conectado_antes and not conectado:
        print("Desconectado: deteniendo")
        cola = []
        rumbo_ref = rumbo
        terminar()
    conectado_antes = conectado

    # ---------- telemetría ----------
    if ahora - t_tel >= PERIODO_TELEMETRIA:
        t_tel = ahora
        enviar("H,{},{},{}".format(fmt(normalize_angle(rumbo)), modo,
                                    min(len(cola), 9)))
        ref_actual = fmt(normalize_angle(rumbo_ref))
        if ref_actual != ref_enviada or ahora - t_ref > 1.0:
            t_ref = ahora
            ref_enviada = ref_actual
            enviar("R," + ref_actual)

    # ---------- latido ----------
    if ahora - t_latido > 0.25:
        t_latido = ahora
        latido = not latido
        if not conectado and modo == "I":
            pixel((60, 40, 0) if latido else (0, 0, 0))   # ámbar: esperando
        else:
            pixel(COLORES.get(modo, (0, 0, 0)) if latido else (0, 0, 0))

    if not conectado and ahora - t_anuncio > 5:
        t_anuncio = ahora
        anunciar()

    time.sleep(0.004)
