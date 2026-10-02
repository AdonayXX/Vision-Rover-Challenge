"""Revisión de un rover nuevo (o recién armado) antes de calibrarlo.

Pulsos cortos y suaves, medidos con la cámara:
  1. la placa: qué ID cree ser, sensores, por qué se reinició, memoria;
  2. la visión: ¿ve su marcador?;
  3. avance: MOTOR igual en las dos ruedas ~0,4 s -> ¿fue hacia adelante y recto?;
  4. giro:   izquierda atrás, derecha adelante -> ¿giró a la izquierda (antihorario)?
Al final dice qué cambiar en codigos/rover_<id>.json. No guarda nada.

    python -B pc/revisar_rover.py --robot-ip 10.50.42.XX --robot-id 11
"""
import argparse
import json
import math
import sys
import time

from cliente_vision import VisionClient
from prueba_transporte_cubo import DevelopmentTelemetryState, RobotClient

POTENCIA = 0.25
PULSO_S = 0.4          # menos que el watchdog de sesión (0,5 s)


def pose(vision, state, robot_id, segundos=5):
    fin = time.monotonic() + segundos
    while time.monotonic() < fin:
        vision.poll()
        rover = state.rover(robot_id)
        if state.reason() is None and rover is not None and rover["age_ms"] < 200:
            return dict(rover)
        time.sleep(.02)
    raise RuntimeError("La camara no ve el marcador {} ({})".format(robot_id, state.reason()))


def quieto(vision, state, robot_id):
    """Pose después de que el rover paró y la imagen lo refleja."""
    fin = time.monotonic() + 1.2
    while time.monotonic() < fin:
        vision.poll()
        time.sleep(.02)
    return pose(vision, state, robot_id)


def pulso(robot, izquierda, derecha):
    robot.send("MOTOR|{}|{}".format(izquierda, derecha), force=True)
    time.sleep(PULSO_S)
    robot.stop()


def giro(antes, despues):
    return (despues["theta"] - antes["theta"] + 180) % 360 - 180


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--robot-ip", required=True)
    p.add_argument("--robot-id", type=int, required=True, help="ID del marcador de ESTE rover")
    p.add_argument("--vision-host", default="127.0.0.1")
    args = p.parse_args()

    state = DevelopmentTelemetryState(robot_id=args.robot_id, peer_id=args.robot_id + 1, max_age_ms=900)
    vision = VisionClient(state, args.vision_host)
    robot = RobotClient(args.robot_ip, wait_seconds=30)
    problemas = []
    try:
        print("1) Placa")
        robot.connect()
        estado = json.loads(robot._exchange("SENSORS"))
        print("   ID configurado: {}   ultimo reinicio: {}   fallos: {}".format(
            estado.get("robot_id"), estado.get("reset_reason"), estado.get("fallos")))
        if estado.get("robot_id") != args.robot_id:
            problemas.append("La placa cree ser el rover {}: sube el paquete con 'ID del rover' = {}".format(
                estado.get("robot_id"), args.robot_id))
        if estado.get("reset_reason") == "BROWNOUT":
            problemas.append("Ultimo reinicio por BROWNOUT: revisa bateria/voltaje antes de seguir")
        print("   sensores: distancia={} mm, IR={}, errores={}".format(
            estado.get("distance_mm"), estado.get("ir"), estado.get("errors")))
        if estado.get("errors"):
            problemas.append("Sensores con errores: {}".format(estado.get("errors")))
        if estado.get("diagnostic_only"):
            problemas.append("config_sensores.json tiene diagnostic_only=true: los motores no se mueven")
        vista = (estado.get("vision") or {})
        print("   vision en la placa: {}".format(vista.get("estado", "sin datos")))

        print("2) Vision")
        inicio = pose(vision, state, args.robot_id)
        print("   marcador {} en col={:.2f} row={:.2f} theta={:.0f}".format(
            args.robot_id, inicio["col"], inicio["row"], inicio["theta"]))
        cell = state.message["grid"]["cell_mm"]

        print("3) Avance ({:.2f} en las dos ruedas, {:.1f} s)".format(POTENCIA, PULSO_S))
        print("   MIRA EL ROVER: debe moverse hacia sus PALETAS (su frente).")
        pulso(robot, POTENCIA, POTENCIA)
        fin = quieto(vision, state, args.robot_id)
        th = math.radians(inicio["theta"])
        dc, dr = (fin["col"] - inicio["col"]) * cell, (fin["row"] - inicio["row"]) * cell
        adelante = dc * math.cos(th) - dr * math.sin(th)
        girado = giro(inicio, fin)
        print("   avanzo {:.0f} mm y giro {:+.0f} grados".format(adelante, girado))
        al_reves = adelante < -15 and abs(girado) < 20
        if abs(adelante) < 15 and abs(girado) < 6:
            problemas.append("No se movio: revisa alimentacion de motores y la razon: {}".format(
                json.loads(robot._exchange("SENSORS")).get("motion_reason")))
        elif al_reves:
            problemas.append("Segun la camara va hacia ATRAS. Si se movio ALEJANDOSE de sus paletas: en "
                             "rover_{}.json pon left_sign=-1 y right_sign=-1. Si fue HACIA las paletas: el "
                             "marcador esta montado al reves (giralo 180 grados)".format(args.robot_id))
        elif abs(girado) >= 20 and abs(adelante) < 25:
            lado = "left_sign" if girado > 0 else "right_sign"
            problemas.append("Gira en vez de avanzar: una rueda va al reves; cambia el signo de {} en rover_{}.json".format(
                lado, args.robot_id))
        elif abs(girado) > 6:
            fuerte = "derecha" if girado > 0 else "izquierda"
            ganancia = "right_gain" if girado > 0 else "left_gain"
            print("   se desvia {:+.0f} grados: la rueda {} empuja mas; baja un poco {} (p. ej. 0.9)".format(
                girado, fuerte, ganancia))
        else:
            print("   OK: adelante y casi recto")

        print("4) Giro en el sitio (izquierda -{0:.2f}, derecha +{0:.2f})".format(POTENCIA))
        antes = quieto(vision, state, args.robot_id)
        pulso(robot, -POTENCIA, POTENCIA)
        despues = quieto(vision, state, args.robot_id)
        girado = giro(antes, despues)
        print("   giro {:+.0f} grados (debe ser positivo: a la izquierda)".format(girado))
        if abs(girado) < 5:
            problemas.append("No giro: con {:.2f} el roce no lo deja; normal si avanzo bien, la calibracion lo medira".format(POTENCIA))
        elif al_reves:
            # Con las dos ruedas al revés también el giro sale al revés: no
            # es otro problema. Si sale bien teniendo el avance al revés, sí.
            if girado > 0:
                problemas.append("El avance va al reves pero el giro no: motores cruzados (M1/M2) Y al revés, "
                                 "o marcador girado 180 grados. Revisa cables y marcador")
        elif girado < 0:
            problemas.append("Gira al REVES avanzando bien: los motores izquierdo y derecho estan "
                             "intercambiados (cables M1/M2)")
        else:
            print("   OK: gira hacia el lado correcto")
    except KeyboardInterrupt:
        print("Detenido por usuario.")
    except (RuntimeError, ConnectionError, OSError) as error:
        problemas.append(str(error))
    finally:
        robot.close()
        vision.close()

    print()
    if problemas:
        print("Revisar:")
        for texto in problemas:
            print("  -", texto)
        return 1
    print("Todo bien. Siguiente: calibrar_movimiento.py --robot-id {}".format(args.robot_id))
    return 0


if __name__ == "__main__":
    sys.exit(main())
