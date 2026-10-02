"""Calibra cómo se mueve el rover: avance, giro, arranque, frenado y latencia.

Es preparación (reglamento 6.2.5): la laptop manda maniobras fijas y la visión
mide el resultado. El modelo que sale se carga después en el rover para que
pueda PREDECIR su pose actual a partir de una imagen con retraso.

La visión corre en esta misma laptop, así que `time.time()` y `ts_ms` usan el
mismo reloj: aquí sí se mide la latencia absoluta de la visión.

Las maniobras van en pares de ida y vuelta para que el rover acabe cerca de
donde empezó. Necesita unos 40 x 40 cm libres alrededor del rover.
"""
import argparse
import json
import math
from pathlib import Path
import statistics
import time

from cliente_vision import VisionClient
from prueba_transporte_cubo import DevelopmentTelemetryState, RobotClient

CODIGOS = Path(__file__).resolve().parents[1] / "codigos"   # modelo_movimiento_<id>.json, uno por rover

# (nombre, izquierdo, derecho, segundos). Pares que se compensan.
MANIOBRAS = (
    # Baja potencia: mide la zona muerta (el control se acerca despacio).
    ("avance_0.10", .10, .10, 1.2), ("retroceso_0.10", -.10, -.10, 1.2),
    ("avance_0.15", .15, .15, 1.0), ("retroceso_0.15", -.15, -.15, 1.0),
    ("avance_0.20", .20, .20, 1.0), ("retroceso_0.20", -.20, -.20, 1.0),
    ("avance_0.25", .25, .25, 1.0), ("retroceso_0.25", -.25, -.25, 1.0),
    ("avance_0.30", .30, .30, 1.0), ("retroceso_0.30", -.30, -.30, 1.0),
    # Giros mas largos: con ~250 ms de retraso, 0,6 s dejaba 3 muestras utiles.
    ("giro_izq_0.18", -.18, .18, 1.2), ("giro_der_0.18", .18, -.18, 1.2),
    ("giro_izq_0.25", -.25, .25, 1.0), ("giro_der_0.25", .25, -.25, 1.0),
    ("giro_izq_0.12", -.12, .12, 1.2), ("giro_der_0.12", .12, -.12, 1.2),
)
MARGEN_BORDE_MM = 120
KEEPALIVE_S = .15


# ---------------------------------------------------------------- análisis
def _unwrap(angulos):
    salida, previo, extra = [], None, 0.0
    for a in angulos:
        if previo is not None:
            d = a - previo
            if d > 180:
                extra -= 360
            elif d < -180:
                extra += 360
        salida.append(a + extra)
        previo = a
    return salida


def _pendiente(xs, ys):
    if len(xs) < 3:
        return None
    mx, my = statistics.fmean(xs), statistics.fmean(ys)
    den = sum((x - mx) ** 2 for x in xs)
    if den == 0:
        return None
    return sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / den


def _promedio_pose(muestras):
    thetas = _unwrap([m["theta"] for m in muestras])
    return {"t": statistics.fmean(m["t"] for m in muestras),
            "col": statistics.fmean(m["col"] for m in muestras),
            "row": statistics.fmean(m["row"] for m in muestras),
            "theta": statistics.fmean(thetas)}


def _interpolar(muestras, t):
    previa = None
    for m in muestras:
        if m["t"] >= t:
            if previa is None:
                return m
            f = (t - previa["t"]) / max(1e-9, m["t"] - previa["t"])
            ang = _unwrap([previa["theta"], m["theta"]])
            return {"t": t, "col": previa["col"] + f * (m["col"] - previa["col"]),
                    "row": previa["row"] + f * (m["row"] - previa["row"]),
                    "theta": ang[0] + f * (ang[1] - ang[0])}
        previa = m
    return previa


def analizar(muestras, t_orden, t_stop, cell_mm, umbral_mm=3.0, umbral_deg=1.5):
    """muestras: dicts {t (ms de observacion), col, row, theta}, ordenadas.

    Devuelve velocidades en régimen, retraso de arranque y deriva tras STOP,
    expresados en el marco del rover al empezar (adelante / izquierda).
    """
    antes = [m for m in muestras if m["t"] <= t_orden][-5:]
    despues = [m for m in muestras if m["t"] >= t_stop + 800]
    if len(antes) < 2 or len(despues) < 2:
        return {"error": "pocas_muestras"}
    p0, pf = _promedio_pose(antes), _promedio_pose(despues[-5:])
    th0 = math.radians(p0["theta"])
    ux, uy = math.cos(th0), -math.sin(th0)     # adelante en (col, row)
    lx, ly = -math.sin(th0), -math.cos(th0)    # izquierda en (col, row)

    def marco(m):
        dc, dr = (m["col"] - p0["col"]) * cell_mm, (m["row"] - p0["row"]) * cell_mm
        return dc * ux + dr * uy, dc * lx + dr * ly

    durante = [m for m in muestras if t_orden < m["t"] <= t_stop + 1500]
    giro0 = _unwrap([p0["theta"]] + [m["theta"] for m in durante])
    inicio = None
    for m, ang in zip(durante, giro0[1:]):
        ad, lat = marco(m)
        if math.hypot(ad, lat) >= umbral_mm or abs(ang - p0["theta"]) >= umbral_deg:
            inicio = m["t"]
            break
    regimen = [m for m in durante if inicio is not None and inicio + 150 <= m["t"] <= t_stop]
    ts = [(m["t"] - t_orden) / 1000 for m in regimen]
    adelante = [marco(m)[0] for m in regimen]
    angulos = _unwrap([p0["theta"]] + [m["theta"] for m in regimen])[1:]
    en_stop = _interpolar(muestras, t_stop)
    ad_stop, _ = marco(en_stop)
    ad_fin, lat_fin = marco(pf)
    giro_stop = _unwrap([p0["theta"], en_stop["theta"]])[1] - p0["theta"]
    giro_fin = _unwrap([p0["theta"], pf["theta"]])[1] - p0["theta"]
    return {
        "retraso_arranque_ms": None if inicio is None else round(inicio - t_orden),
        "mm_s": None if _pendiente(ts, adelante) is None else round(_pendiente(ts, adelante), 1),
        "deg_s": None if _pendiente(ts, angulos) is None else round(_pendiente(ts, angulos), 1),
        "deriva_tras_stop_mm": round(ad_fin - ad_stop, 1),
        "deriva_tras_stop_deg": round(giro_fin - giro_stop, 1),
        "total_adelante_mm": round(ad_fin, 1),
        "total_lateral_mm": round(lat_fin, 1),
        "total_giro_deg": round(giro_fin, 1),
        "muestras_regimen": len(regimen),
    }


def _ajuste_por_potencia(resultados, clave, prefijos):
    """Ganancia lineal: unidad/s por unidad de potencia, con la recta por el origen."""
    pares = []
    for nombre, r in resultados.items():
        for prefijo, signo in prefijos:
            if nombre.startswith(prefijo) and r.get(clave) is not None:
                potencia = float(nombre.rsplit("_", 1)[1])
                pares.append((potencia, signo * r[clave]))
    if not pares:
        return None
    return round(sum(p * v for p, v in pares) / sum(p * p for p, _ in pares), 1)


def ajuste_con_zona_muerta(resultados, prefijo, clave):
    """Recta v = k * (p - p0) por minimos cuadrados con ordenada libre.

    p0 es la zona muerta: la potencia por debajo de la cual no se mueve. Se
    ajusta por familia porque izquierda y derecha no son simetricas.
    """
    pares = [(float(n.rsplit("_", 1)[1]), abs(r[clave])) for n, r in resultados.items()
             if n.startswith(prefijo) and r.get(clave) is not None]
    if len(pares) < 2:
        return None
    media_p = statistics.fmean(p for p, _ in pares)
    media_v = statistics.fmean(v for _, v in pares)
    den = sum((p - media_p) ** 2 for p, _ in pares)
    if den == 0:
        return None
    k = sum((p - media_p) * (v - media_v) for p, v in pares) / den
    if k <= 0:
        return None
    return {"k_por_unidad": round(k, 1), "zona_muerta": round(media_p - media_v / k, 3)}


def desfase_marcador_mm(resultados):
    """Distancia del marcador al centro de giro, a partir de los giros en el sitio.

    Si el centro no se mueve, el marcador describe un arco de radio d:
    adelante = d (cos(giro) - 1), lateral = d sen(giro). Minimos cuadrados.
    """
    estimaciones = []
    for nombre, r in resultados.items():
        if not nombre.startswith("giro") or r.get("total_giro_deg") is None:
            continue
        g = math.radians(r["total_giro_deg"])
        a, b = math.cos(g) - 1, math.sin(g)
        if a * a + b * b > .1:
            estimaciones.append((r["total_adelante_mm"] * a + r["total_lateral_mm"] * b) / (a * a + b * b))
    return round(statistics.median(estimaciones), 1) if estimaciones else None


def resumir(resultados, latencias_ms):
    def valores(clave, prefijo):
        return [r[clave] for n, r in resultados.items()
                if n.startswith(prefijo) and r.get(clave) is not None]
    retrasos = valores("retraso_arranque_ms", "")
    derivas = [abs(v) for v in valores("deriva_tras_stop_mm", "avance") + valores("deriva_tras_stop_mm", "retroceso")]
    giros_deriva = [abs(v) for v in valores("deriva_tras_stop_deg", "giro")]
    laterales = [r["total_lateral_mm"] / r["total_adelante_mm"] for n, r in resultados.items()
                 if n.startswith("avance") and r.get("total_adelante_mm")]
    lat = sorted(latencias_ms)
    rumbo = [r["deg_s"] / r["mm_s"] for n, r in resultados.items()
             if n.startswith("avance") and r.get("deg_s") is not None and r.get("mm_s")]
    return {
        "avance_mm_s_por_unidad": _ajuste_por_potencia(resultados, "mm_s", (("avance", 1), ("retroceso", -1))),
        "familias": {nombre: ajuste_con_zona_muerta(resultados, nombre, clave) for nombre, clave in (
            ("avance", "mm_s"), ("retroceso", "mm_s"),
            ("giro_izq", "deg_s"), ("giro_der", "deg_s"))},
        # >0: al avanzar recto gira a la izquierda (motor derecho mas fuerte).
        "giro_al_avanzar_deg_por_mm": round(statistics.median(rumbo), 4) if rumbo else None,
        "desfase_marcador_mm": desfase_marcador_mm(resultados),
        "retraso_arranque_ms": round(statistics.median(retrasos)) if retrasos else None,
        "deriva_tras_stop_mm": round(statistics.median(derivas), 1) if derivas else None,
        "deriva_tras_stop_deg": round(statistics.median(giros_deriva), 1) if giros_deriva else None,
        "deriva_lateral_por_mm_avance": round(statistics.median(laterales), 3) if laterales else None,
        "latencia_vision_ms": None if not lat else {
            "min": round(lat[0]), "mediana": round(statistics.median(lat)),
            "p90": round(lat[int(.9 * (len(lat) - 1))]),
            "max": round(lat[-1])},
    }


# ---------------------------------------------------------------- campo
class Registro:
    def __init__(self, vision, state, robot_id):
        self.vision, self.state, self.robot_id = vision, state, robot_id
        self.muestras, self.latencias, self.ultimo_seq = [], [], None

    def leer(self):
        self.vision.poll()
        msg = self.state.message
        if msg is None or msg["seq"] == self.ultimo_seq:
            return
        self.ultimo_seq = msg["seq"]
        self.latencias.append(time.time() * 1000 - msg["ts_ms"])
        rover = self.state.rover(self.robot_id)
        if rover is not None:
            self.muestras.append({"t": msg["ts_ms"] - rover["age_ms"], "col": rover["col"],
                                  "row": rover["row"], "theta": rover["theta"]})

    def esperar(self, segundos):
        fin = time.monotonic() + segundos
        while time.monotonic() < fin:
            self.leer()
            time.sleep(.005)


def _lejos_del_borde(state, robot_id, margen_mm):
    msg, rover = state.message, state.rover(robot_id)
    cell = msg["grid"]["cell_mm"]
    distancias = (rover["col"] * cell, (msg["grid"]["cols"] - rover["col"]) * cell,
                  rover["row"] * cell, (msg["grid"]["rows"] - rover["row"]) * cell)
    return min(distancias) >= margen_mm


def ejecutar(robot, registro, state, args, nombre, izq, der, segundos):
    if state.reason() is not None:
        raise RuntimeError("Vision no lista antes de {}: {}".format(nombre, state.reason()))
    if not _lejos_del_borde(state, args.robot_id, MARGEN_BORDE_MM):
        raise RuntimeError("Rover a menos de {} mm de un borde; centralo y repite".format(MARGEN_BORDE_MM))
    inicio = len(registro.muestras)
    registro.esperar(.6)                      # pose de reposo
    t_orden = time.time() * 1000
    robot.send("MOTOR|{:.3f}|{:.3f}".format(izq, der), force=True)
    fin = time.monotonic() + segundos
    while time.monotonic() < fin:
        registro.leer()
        if state.reason() is not None:
            robot.stop()
            raise RuntimeError("Vision perdida durante {}: {}".format(nombre, state.reason()))
        robot.send("KEEPALIVE", force=True)
        espera = time.monotonic() + KEEPALIVE_S
        while time.monotonic() < min(espera, fin):
            registro.leer()
            time.sleep(.005)
    robot.send("STOP", force=True)
    t_stop = time.time() * 1000
    registro.esperar(1.5)                     # deriva tras STOP y reposo final
    return analizar(registro.muestras[inicio:], t_orden, t_stop, state.message["grid"]["cell_mm"])


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--robot-ip", required=True)
    p.add_argument("--robot-id", type=int, default=10)
    p.add_argument("--vision-host", default="127.0.0.1")
    p.add_argument("--vision-port", type=int, default=2026)
    p.add_argument("--salida", type=Path, help="por defecto codigos/modelo_movimiento_<robot-id>.json")
    args = p.parse_args()
    if args.salida is None:
        args.salida = CODIGOS / "modelo_movimiento_{}.json".format(args.robot_id)

    state = DevelopmentTelemetryState(robot_id=args.robot_id, peer_id=args.robot_id + 1, max_age_ms=900)
    vision = VisionClient(state, args.vision_host, args.vision_port)
    registro = Registro(vision, state, args.robot_id)
    robot = RobotClient(args.robot_ip, wait_seconds=30)
    resultados = {}
    try:
        print("Esperando vision...", flush=True)
        limite = time.monotonic() + 15
        while state.reason() is not None and time.monotonic() < limite:
            registro.leer()
            time.sleep(.02)
        if state.reason() is not None:
            raise RuntimeError("Vision no lista: " + state.reason())
        robot.connect()
        robot.confirmar_identidad(args.robot_id)
        print("Rover conectado. {} maniobras; Ctrl+C detiene.".format(len(MANIOBRAS)), flush=True)
        for nombre, izq, der, segundos in MANIOBRAS:
            r = ejecutar(robot, registro, state, args, nombre, izq, der, segundos)
            resultados[nombre] = r
            print("{:16s} {}".format(nombre, json.dumps(r)), flush=True)
    except KeyboardInterrupt:
        print("Detenido por usuario.")
    finally:
        print("STOP confirmado." if robot.close() else "Sin confirmacion de STOP.")
        vision.close()
    if not resultados:
        return 1
    modelo = {"v": 1, "fecha": time.strftime("%Y-%m-%d %H:%M"), "robot_id": args.robot_id,
              "resumen": resumir(resultados, registro.latencias), "maniobras": resultados}
    args.salida.write_text(json.dumps(modelo, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print("\nResumen:", json.dumps(modelo["resumen"], indent=2, ensure_ascii=False))
    print("Guardado en", args.salida)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
