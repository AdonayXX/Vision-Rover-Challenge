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


def _radio(radio):
    """ESP-NOW con el compañero: mensajes recibidos y hace cuánto llegó el último."""
    if not radio:
        return ""
    texto = "  radio: tx={} rx={} hace={}ms canal={}".format(
        radio.get("tx"), radio.get("rx"), radio.get("edad_ms", "-"), radio.get("canal", "?"))
    for clave in ("plan", "robados", "cedidos", "ajenos", "errores", "reaperturas", "ultimo_error", "error"):
        if radio.get(clave):
            texto += " {}={}".format(clave, radio[clave])
    return texto


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
                # Si la placa se reinició (error fatal, BROWNOUT, WATCHDOG) lo dice aquí.
                print("  placa: encendida hace {} s, ultimo reinicio={}{}".format(
                    estado.get("uptime_s"), estado.get("reset_reason"),
                    ", fallos={}".format(estado["fallos"]) if estado.get("fallos") else ""), flush=True)
                if estado.get("idf_kb"):
                    # [libre, bloque mayor] KB de la memoria que usa el Wi-Fi para recibir.
                    print("  memoria wifi (KB): libre={} bloque={}".format(*estado["idf_kb"]), flush=True)
                antena = estado.get("antena")
                if antena:
                    # [canal, señal dBm] de cada antena de la red que vio al conectarse;
                    # ahorro: si la placa pudo quitar el ahorro de energía del Wi-Fi.
                    print("  wifi: canal elegido={} antenas vistas={} ahorro={}".format(
                        antena.get("canal"), antena.get("vistas"), antena.get("ahorro", "?")), flush=True)
                vista = estado.get("vision")
                if vista:
                    # fase=None con estado "conexion_fallida: ..." = no llega a la visión
                    # (IP vieja en la config, visión apagada, firewall).
                    print("  vision: {} estado={} conexiones={}".format(
                        vista.get("host", "?"), vista.get("estado"), vista.get("conexiones")), flush=True)
                else:
                    print("  vision: el rover no tiene vision_host en su config", flush=True)
                conexiones = (vista or {}).get("conexiones") or 0
                mostrados = None
                inicio = time.monotonic()
                while True:
                    estado = preguntar(sock, buffer)
                    mision = estado.get("mision") or {}
                    ronda = mision.get("ronda") or {}
                    vista = estado.get("vision") or {}
                    mem = vista.get("mem_libre")
                    clave = (ronda.get("estado"), ronda.get("fase"), ronda.get("actual"),
                             tuple(ronda.get("hechos") or ()), mision.get("estado"), mision.get("motivo"),
                             vista.get("estado"), vista.get("conexiones"), ronda.get("errores"), ronda.get("turno"))
                    if clave != anterior or time.monotonic() - ultimo_print > 5:
                        # Por qué hace lo que hace: reubicando, último retroceso, qué estorbó.
                        detalle = "".join(" {}={}".format(k, mision[k])
                                          for k in ("submeta", "retroceso", "estorbo", "espera") if mision.get(k))
                        # La conexión del ROVER con la visión: si no está ok, o si se
                        # reconectó desde que empezó a mirar (el rover perdió la red).
                        red = ""
                        if vista and vista.get("estado") != "ok":
                            red += "  vision={}".format(vista.get("estado"))
                        if (vista.get("conexiones") or 0) > conexiones:
                            red += "  vision_reconexiones={}".format(vista["conexiones"] - conexiones)
                        if ronda.get("turno"):
                            red += "  turno={}".format(ronda["turno"])     # espera a que el otro termine
                        if ronda.get("error"):
                            red += "  ERROR_RONDA={} (x{})".format(ronda["error"], ronda.get("errores"))
                        print("{:6.1f}s fase={} ronda={} cubos={} hechos={} actual={} | mision={} {}{}{}{}{}{}".format(
                            time.monotonic() - inicio, ronda.get("fase"), ronda.get("estado"),
                            ronda.get("mis_cubos"), ronda.get("hechos"), ronda.get("actual"),
                            mision.get("estado"), mision.get("motivo") or "", detalle,
                            "  fallos={}".format(ronda["fallos"]) if ronda.get("fallos") else "",
                            red,
                            "  ram={}".format(mem) if mem else "",
                            _radio(ronda.get("radio"))), flush=True)
                        anterior, ultimo_print = clave, time.monotonic()
                    eventos = ronda.get("eventos") or []
                    if eventos and eventos != mostrados:
                        # La placa lo entrega sólo con la ronda terminada: qué hizo y por
                        # qué, segundo a segundo (s desde RUNNING; "pre" = antes).
                        print("  --- registro de la ronda ({} eventos) ---".format(len(eventos)), flush=True)
                        for linea in eventos:
                            print("    " + linea, flush=True)
                        mostrados = eventos
                    time.sleep(1.0)        # cada informe gasta RAM de red en la placa (cancha 2-oct)
        except KeyboardInterrupt:
            print("Fin (el rover sigue solo).")
            return 0
        except (OSError, ConnectionError, ValueError) as error:
            print("Sin conexion ({}); reintento en 2 s...".format(error), flush=True)
            time.sleep(2)


if __name__ == "__main__":
    raise SystemExit(main())
