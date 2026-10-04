"""Graba la cancha durante una ronda: posiciones de rovers y cubos, 5 por segundo.

Sólo LEE la telemetría de la visión, como un cliente más (no manda nada ni a
la visión ni a los rovers), así que se puede dejar corriendo en competencia.
Sirve para saber DÓNDE estaba un rover cuando la cámara lo perdió (cancha
3-oct: el rover 11 se salió por arriba y no había forma de ver por dónde).

En pantalla avisa al momento:
  - cambio de fase;
  - rover cerca del borde (centro a menos de 2 celdas de la línea);
  - rover perdido (la visión dejó de verlo) con su última posición vista.

Al terminar cada ronda agrega una fila a pc/grabaciones/tabla.csv: si se
completó, tiempo, cubos dentro, rovers perdidos, cubos fuera de la cancha y
cubos movidos a mano. Así se comparan versiones con números y no de memoria.

Uso:
  python -X utf8 -B pc/grabar_cancha.py --escenario dificil
El archivo queda en pc/grabaciones/cancha_AAAAMMDD_HHMMSS.jsonl (una línea por
muestra) y se puede pasar tal cual para revisarlo.
"""
import argparse
import csv
import json
import math
from pathlib import Path
import socket
import time

CARPETA = Path(__file__).resolve().parent / "grabaciones"


def _resumen(m):
    """Lo que interesa de un mensaje, en pocas cifras."""
    return {
        "fase": m.get("phase"),
        "rovers": [[r["id"], round(r["col"], 2), round(r["row"], 2), round(r.get("theta", 0)),
                    r.get("age_ms", 0)] for r in m.get("rovers", [])],
        "cubos": [[c["color"], round(c["col"], 2), round(c["row"], 2), c.get("age_ms", 0),
                   c.get("in_depot")] for c in m.get("cubes", [])],
    }


class Balance:
    """Lo que pasó en una ronda (de RUNNING a FINISHED), para la tabla."""
    COLUMNAS = ("fecha", "escenario", "completa", "tiempo_s", "cubos_dentro", "perdidos",
                "cerca_borde", "cubos_fuera", "a_mano", "archivo")

    def __init__(self):
        self.inicio = None                # t de RUNNING
        self.completa_en = None           # t en que los tres quedaron in_depot
        self.dentro = 0
        self.perdidos, self.cerca, self.fuera, self.a_mano = set(), set(), set(), set()
        self.vistos = set()               # rovers vistos alguna vez en esta ronda
        self.cubos = {}                   # color -> (t, col, row) de la última muestra

    def observar(self, t, m):
        grid = m.get("grid", {})
        cols, rows = grid.get("cols", 43), grid.get("rows", 43)
        rovers_vistos = []
        presentes = set()
        for r in m.get("rovers", []):
            presentes.add(r["id"])
            if r.get("age_ms", 0) <= 500:
                rovers_vistos.append((r["id"], r["col"], r["row"]))
                self.vistos.add(r["id"])
                if min(r["col"], r["row"], cols - r["col"], rows - r["row"]) < 2.0:
                    self.cerca.add(r["id"])
            elif r["id"] in self.vistos:
                self.perdidos.add(r["id"])
        self.perdidos.update(self.vistos - presentes)
        lado = m.get("cube_side", 3.0) / 2
        dentro = 0
        for c in m.get("cubes", []):
            color = c["color"]
            dentro += c.get("in_depot") is True
            # Con el centro a menos de medio cubo de la línea ya asoma afuera.
            if not (lado <= c["col"] <= cols - lado and lado <= c["row"] <= rows - lado):
                self.fuera.add(color)
            antes = self.cubos.get(color)
            if antes is not None and c.get("age_ms", 0) <= 200 and t - antes[0] <= 0.5:
                salto = math.hypot(c["col"] - antes[1], c["row"] - antes[2])
                # Un rover empuja a < 0,2 m/s (~5 celdas en 0,5 s) y siempre
                # pegado al cubo: un salto grande sin rover cerca es una mano.
                cerca = any(math.hypot(x - c["col"], y - c["row"]) < 8 or
                            math.hypot(x - antes[1], y - antes[2]) < 8 for _, x, y in rovers_vistos)
                if salto > 2.5 and not cerca:
                    self.a_mano.add(color)
            self.cubos[color] = (t, c["col"], c["row"])
        self.dentro = dentro
        if dentro == 3 and self.completa_en is None:
            self.completa_en = t

    def fila(self, escenario, archivo):
        tiempo = ""
        if self.completa_en is not None and self.inicio is not None:
            # El árbitro pide 1 s adentro antes de contar y fecha la ENTRADA.
            tiempo = round(max(0.0, self.completa_en - self.inicio - 1.0), 1)
        return {"fecha": time.strftime("%Y-%m-%d %H:%M"), "escenario": escenario,
                "completa": "si" if self.completa_en is not None else "no", "tiempo_s": tiempo,
                "cubos_dentro": self.dentro, "perdidos": " ".join(map(str, sorted(self.perdidos))),
                "cerca_borde": " ".join(map(str, sorted(self.cerca))),
                "cubos_fuera": " ".join(sorted(self.fuera)), "a_mano": " ".join(sorted(self.a_mano)),
                "archivo": archivo}


def anotar(fila, ruta=None):
    ruta = ruta or CARPETA / "tabla.csv"
    nueva = not ruta.exists()
    with open(ruta, "a", encoding="utf-8", newline="") as f:
        escritor = csv.DictWriter(f, fieldnames=Balance.COLUMNAS)
        if nueva:
            escritor.writeheader()
        escritor.writerow(fila)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--host", default="127.0.0.1", help="IP de la computadora de visión")
    parser.add_argument("--port", type=int, default=2026)
    parser.add_argument("--hz", type=float, default=5.0, help="muestras por segundo en el archivo")
    parser.add_argument("--escenario", default="", help="nombre para la tabla: facil, dificil, borde...")
    args = parser.parse_args(argv)

    CARPETA.mkdir(exist_ok=True)
    ruta = CARPETA / time.strftime("cancha_%Y%m%d_%H%M%S.jsonl")
    sock = socket.create_connection((args.host, args.port), timeout=5)
    sock.settimeout(5)
    print("Grabando en", ruta, "(Ctrl+C para terminar)", flush=True)

    inicio = time.monotonic()
    proxima = 0.0
    buffer = b""
    fase = None
    perdidos, cerca = set(), set()
    ultimo_visto = {}
    balance = None

    def cerrar_ronda():
        fila = balance.fila(args.escenario, ruta.name)
        anotar(fila)
        print("RONDA: completa={completa} tiempo={tiempo_s}s cubos_dentro={cubos_dentro} perdidos=[{perdidos}] "
              "cerca_borde=[{cerca_borde}] cubos_fuera=[{cubos_fuera}] a_mano=[{a_mano}]".format(**fila), flush=True)
        print("        (anotado en {})".format(CARPETA / "tabla.csv"), flush=True)
    with open(ruta, "w", encoding="utf-8") as archivo:
        try:
            while True:
                datos = sock.recv(65536)
                if not datos:
                    print("La visión cerró la conexión.")
                    break
                buffer += datos
                fin = buffer.rfind(b"\n")
                if fin < 0:
                    continue
                linea = buffer[:fin].rsplit(b"\n", 1)[-1]
                buffer = buffer[fin + 1:]
                try:
                    m = json.loads(linea)
                except ValueError:
                    continue
                t = round(time.monotonic() - inicio, 2)
                grid = m.get("grid", {})
                cols, rows = grid.get("cols", 43), grid.get("rows", 43)

                if balance is not None:
                    # Antes del cambio de fase: el mensaje que pasa a FINISHED
                    # es el primero con los tres cubos contados.
                    antes_fuera, antes_mano = set(balance.fuera), set(balance.a_mano)
                    balance.observar(t, m)
                    for color in balance.fuera - antes_fuera:
                        print("{:7.1f}s cubo {} ASOMA FUERA DE LA CANCHA".format(t, color), flush=True)
                    for color in balance.a_mano - antes_mano:
                        print("{:7.1f}s cubo {} MOVIDO A MANO (salto sin rover cerca)".format(t, color), flush=True)
                if m.get("phase") != fase:
                    if fase == "RUNNING" and balance is not None:
                        cerrar_ronda()
                        balance = None
                    fase = m.get("phase")
                    print("{:7.1f}s fase={}".format(t, fase), flush=True)
                    if fase == "RUNNING":
                        balance = Balance()
                        balance.inicio = t

                presentes = [r["id"] for r in m.get("rovers", [])]
                ausentes = [{"id": rid, "age_ms": 10 ** 6} for rid in ultimo_visto if rid not in presentes]
                for r in m.get("rovers", []) + ausentes:
                    rid = r["id"]
                    if r.get("age_ms", 0) <= 500:
                        ultimo_visto[rid] = (t, r["col"], r["row"], r.get("theta", 0))
                        if rid in perdidos:
                            perdidos.discard(rid)
                            print("{:7.1f}s rover {} visto otra vez en ({:.1f}, {:.1f})".format(
                                t, rid, r["col"], r["row"]), flush=True)
                        borde = min(r["col"], r["row"], cols - r["col"], rows - r["row"])
                        if borde < 2.0 and rid not in cerca:
                            cerca.add(rid)
                            print("{:7.1f}s rover {} CERCA DEL BORDE en ({:.1f}, {:.1f}) rumbo {:.0f}°".format(
                                t, rid, r["col"], r["row"], r.get("theta", 0)), flush=True)
                        elif borde >= 3.0:
                            cerca.discard(rid)
                    elif rid not in perdidos:
                        perdidos.add(rid)
                        visto = ultimo_visto.get(rid)
                        donde = ("visto por última vez a los {:.1f}s en ({:.1f}, {:.1f}) rumbo {:.0f}°".format(*visto)
                                 if visto else "nunca visto")
                        print("{:7.1f}s rover {} PERDIDO: {}".format(t, rid, donde), flush=True)

                if t >= proxima:
                    proxima = t + 1.0 / args.hz
                    archivo.write(json.dumps(dict(_resumen(m), t=t)) + "\n")
                    archivo.flush()
        except KeyboardInterrupt:
            pass
        finally:
            sock.close()
            if balance is not None:           # cortada antes de FINISHED
                cerrar_ronda()
    print("Listo:", ruta)


if __name__ == "__main__":
    main()
