"""Busca 'cubos' que aparecen justo delante de un rover (posible luz/objeto de color en el rover).

Para cada muestra en RUNNING/READY/IDLE: si un cubo salta > 3 celdas respecto de la
muestra anterior y cae a menos de 1,2 celdas del punto 4,3 celdas delante del
marcador de algún rover, se anota (rover, color, adelante_mm, lateral_mm).
"""
import glob, json, math, os, sys, collections

carpeta = sys.argv[1]
total = collections.Counter()
for ruta in sorted(glob.glob(os.path.join(carpeta, "cancha_*.jsonl"))):
    L = [json.loads(l) for l in open(ruta, encoding="utf-8")]
    previo = {}
    casos = []
    for m in L:
        for c in m["cubos"]:
            color, col, row = c[0], c[1], c[2]
            antes = previo.get(color)
            previo[color] = (col, row)
            if antes is None or math.hypot(col - antes[0], row - antes[1]) < 3:
                continue
            for r in m["rovers"]:
                rid, rc, rr, th = r[0], r[1], r[2], math.radians(r[3])
                dc, dr = col - rc, row - rr
                adelante = (dc * math.cos(th) - dr * math.sin(th)) * 20
                lateral = (-dc * math.sin(th) - dr * math.cos(th)) * 20
                if 50 < adelante < 120 and abs(lateral) < 40:
                    casos.append((round(m["t"], 1), m["fase"], rid, color, round(adelante), round(lateral)))
                    total[(rid, color)] += 1
    if casos:
        print(os.path.basename(ruta), len(casos), "saltos a la punta de un rover:", casos[:6])
print("total por (rover, color):", dict(total))
