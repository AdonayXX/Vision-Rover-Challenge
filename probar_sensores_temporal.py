"""Diagnóstico temporal de sensores, sin mover los motores.

Se ejecuta en la PC y solo utiliza STOP y SENSORS del protocolo del rover.
Los infrarrojos se revisan únicamente por presencia de datos porque el rover
está fijo sobre una superficie uniforme.
"""

import argparse
import math
from pathlib import Path
import statistics
import sys
import time


PC = Path(__file__).resolve().parent / "base-robots" / "robots" / "pc"
sys.path.insert(0, str(PC))
from prueba_transporte_cubo import RobotClient  # noqa: E402


def esperar(texto):
    input("\n" + texto + "\nPulsa ENTER cuando esté listo...")


def muestras(cliente, segundos):
    resultado = []
    fin = time.monotonic() + segundos
    print("Midiendo durante {:.0f} segundos...".format(segundos))
    while time.monotonic() < fin:
        resultado.append(cliente.sensors())
        time.sleep(0.2)
    return resultado


def mediana(valores):
    return statistics.median(valores) if valores else None


def prueba_ultrasonido(cliente):
    mediciones = []
    for cm in (20, 40):
        esperar(
            "ULTRASONIDO: coloca un cartón plano frente a los dos cilindros, "
            "a {} cm medidos desde el sensor.".format(cm)
        )
        lote = muestras(cliente, 5)
        valores = [
            float(x["distance_mm"])
            for x in lote
            if x.get("distance_mm") is not None
            and x.get("distance_age_ms") is not None
            and x["distance_age_ms"] < 500
            and "ultrasonic" not in x.get("errors", {})
        ]
        mediciones.append((cm, mediana(valores), len(valores), len(lote)))

    detalles = []
    for cm, valor, validas, total in mediciones:
        lectura = "ninguna distancia válida" if valor is None else "{:.0f} mm".format(valor)
        detalles.append("{} cm -> {} ({}/{})".format(cm, lectura, validas, total))
    m20, m40 = mediciones[0][1], mediciones[1][1]
    funciona = (
        m20 is not None
        and m40 is not None
        and 150 <= m20 <= 250
        and 300 <= m40 <= 500
        and m40 - m20 >= 100
    )
    return funciona, "; ".join(detalles)


def prueba_ir(cliente):
    lote = muestras(cliente, 5)
    columnas = [[] for _ in range(4)]
    for dato in lote:
        valores = dato.get("ir")
        edad = dato.get("ir_age_ms")
        if not isinstance(valores, list) or len(valores) != 4 or edad is None or edad >= 500:
            continue
        for i, valor in enumerate(valores):
            if isinstance(valor, (int, float)) and math.isfinite(valor):
                columnas[i].append(float(valor))

    presentes = all(len(columna) >= 5 for columna in columnas)
    detalles = []
    for i, columna in enumerate(columnas, 1):
        if not columna:
            detalles.append("IR{} sin datos".format(i))
            continue
        centro = mediana(columna)
        aviso = " (cerca del límite alto)" if centro >= 62000 else ""
        detalles.append(
            "IR{} mediana={:.0f}, rango={:.0f}..{:.0f}{}".format(
                i, centro, min(columna), max(columna), aviso
            )
        )
    return presentes, "; ".join(detalles)


def firmas(lote):
    unicas = {}
    for dato in lote:
        firma = dato.get("color_signature")
        secuencia = dato.get("color_seq")
        edad = dato.get("color_age_ms")
        if (
            isinstance(firma, list)
            and len(firma) == 3
            and secuencia is not None
            and edad is not None
            and edad < 500
            and all(isinstance(v, (int, float)) and math.isfinite(v) for v in firma)
        ):
            unicas[secuencia] = [float(v) for v in firma]
    return list(unicas.values())


def distancia(a, b):
    return math.sqrt(sum((x - y) ** 2 for x, y in zip(a, b)))


def prueba_color(cliente):
    grupos = {}
    for nombre, visible in (("red", "ROJO"), ("green", "VERDE"), ("blue", "AZUL")):
        esperar(
            "COLOR: coloca el cubo {} quieto frente a la cara sensible del sensor."
            .format(visible)
        )
        grupos[nombre] = firmas(muestras(cliente, 7))

    centros, detalles, estable = {}, [], True
    for nombre, grupo in grupos.items():
        if len(grupo) < 5:
            estable = False
            detalles.append("{}: solo {} barridos útiles".format(nombre, len(grupo)))
            continue
        centro = [statistics.mean(f[i] for f in grupo) for i in range(3)]
        dispersion = max(distancia(f, centro) for f in grupo)
        centros[nombre] = centro
        if dispersion > 0.15:
            estable = False
        detalles.append("{}: {} barridos, dispersión {:.3f}".format(nombre, len(grupo), dispersion))

    pares = (("red", "green"), ("red", "blue"), ("green", "blue"))
    separaciones = [
        distancia(centros[a], centros[b])
        for a, b in pares
        if a in centros and b in centros
    ]
    separable = len(separaciones) == 3 and min(separaciones) >= 0.15
    if separaciones:
        detalles.append("separación mínima={:.3f}".format(min(separaciones)))
    else:
        detalles.append("no se pudieron comparar los tres colores")
    return estable and separable and len(centros) == 3, "; ".join(detalles)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--robot-ip", help="IP actual del rover")
    parser.add_argument("--robot-port", type=int, default=5000)
    args = parser.parse_args(argv)
    ip = args.robot_ip or input("IP actual del rover: ").strip()
    if not ip:
        parser.error("falta la IP del rover")

    cliente = RobotClient(ip, args.robot_port)
    resultados = []
    try:
        cliente.connect()
        estado = cliente.sensors()
        if estado.get("diagnostic_only") is not True:
            raise RuntimeError("diagnostic_only debe permanecer en true para esta prueba")
        print("Conectado. STOP confirmado; esta prueba no mueve los motores.")
        resultados.append(("Ultrasonido",) + prueba_ultrasonido(cliente))
        print("\nINFRARROJOS: el rover se queda fijo. Solo comprobaremos que los cuatro entreguen datos.")
        resultados.append(("Infrarrojos",) + prueba_ir(cliente))
        resultados.append(("Color",) + prueba_color(cliente))
    except (ConnectionError, OSError, RuntimeError, ValueError) as error:
        print("\nERROR:", error)
        return 1
    except KeyboardInterrupt:
        print("\nPrueba cancelada.")
        return 130
    finally:
        cliente.close()

    print("\n=== RESULTADO ===")
    for nombre, correcto, detalle in resultados:
        if nombre == "Infrarrojos" and correcto:
            estado = "DATOS PRESENTES; RESPUESTA FÍSICA PENDIENTE"
        else:
            estado = "FUNCIONA" if correcto else "FALLA / NO CONCLUYENTE"
        print("{}: {}\n  {}".format(nombre, estado, detalle))
    print("\nLos infrarrojos no pueden declararse calibrados mientras el rover no cambie de superficie.")
    return 0 if all(x[1] for x in resultados) else 2


if __name__ == "__main__":
    raise SystemExit(main())
