import json, sys
nombre = sys.argv[1]
paso = float(sys.argv[2]) if len(sys.argv) > 2 else 1.0
hasta = float(sys.argv[3]) if len(sys.argv) > 3 else 1e9
L = [json.loads(l) for l in open(nombre, encoding="utf-8")]
t0 = next((m["t"] for m in L if m["fase"] == "RUNNING"), None)
print("muestras", len(L), "RUNNING en", t0, "fases", sorted({m["fase"] for m in L}))
if t0 is None:
    t0 = L[0]["t"]
prox = -5
for m in L:
    t = m["t"] - t0
    if t < prox or t > hasta:
        continue
    prox = t + paso
    r = {x[0]: x for x in m["rovers"]}
    c = {x[0]: x for x in m["cubos"]}
    def rv(i):
        x = r.get(i)
        return "--" if x is None else "(%4.1f,%4.1f,%3d,a%d)" % (x[1], x[2], x[3], x[4])
    def cb(k):
        x = c.get(k)
        return "--" if x is None else "(%4.1f,%4.1f%s%s)" % (x[1], x[2], ",a%d" % x[3] if x[3] else "", ",IN" if x[4] else "")
    print("%6.1f %-8s r10=%s r11=%s b=%s g=%s r=%s" % (t, m["fase"], rv(10), rv(11), cb("blue"), cb("green"), cb("red")))
