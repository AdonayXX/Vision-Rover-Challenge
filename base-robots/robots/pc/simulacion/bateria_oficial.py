"""Canchas del generador oficial (docs/index.html) en el simulador de dos rovers.

uso: python bateria_oficial.py <base> <dificultad> <n> [semilla]
Reproduce proposedLayout/randomLayout/valid/stats del generador y lleva el
tablero (50x50, área útil 5..44, salida abajo, rojo arriba, verde izquierda,
azul derecha) a la cancha de la visión (salida a la izquierda, verde arriba,
rojo a la derecha, azul abajo): fila = gx - 3.5, columna = 46.5 - gy.
La cámara pierde al rover a menos de 2,2 celdas del borde de arriba (cancha 3-oct).
"""
import collections, contextlib, io, math, os, random, sys
base, D, N = sys.argv[1], float(sys.argv[2]), int(sys.argv[3])
semilla = int(sys.argv[4]) if len(sys.argv) > 4 else 1
sys.path.insert(0, base + "/tests"); sys.path.insert(0, base + "/codigos")

# ---------------------------------------------------------- generador oficial
SIZE, INNER_MIN, INNER_MAX, CUBE, MIN_GAP = 50, 5, 44, 3, 2
GOALS = {"red": (21, 1, 8, 6), "green": (1, 21, 6, 8), "blue": (43, 21, 6, 8)}
ROBOTS = [(19, 46, 4, 3), (27, 46, 4, 3)]
KEYS = ["red", "blue", "green"]
rnd = random.Random(semilla)


def inter(a, b):
    return a[0] < b[0] + b[2] and a[0] + a[2] > b[0] and a[1] < b[1] + b[3] and a[1] + a[3] > b[1]


def too_close(a, b):
    return (a[0] < b[0] + b[2] + MIN_GAP and a[0] + a[2] + MIN_GAP > b[0] and
            a[1] < b[1] + b[3] + MIN_GAP and a[1] + a[3] + MIN_GAP > b[1])


def valid(c, peers):
    r = (c[1], c[2], CUBE, CUBE)
    if r[0] < INNER_MIN or r[1] < INNER_MIN or r[0] + CUBE - 1 > INNER_MAX or r[1] + CUBE - 1 > INNER_MAX:
        return False
    if any(inter(r, z) for z in GOALS.values()) or any(inter(r, z) for z in ROBOTS):
        return False
    return not any(too_close(r, (o[1], o[2], CUBE, CUBE)) for o in peers)


def centro(c):
    return (c[1] + 1.5, c[2] + 1.5)


def meta(k):
    x, y, w, h = GOALS[k]
    return (x + w / 2, y + h / 2)


def seg_dist(a, b, c, d):
    def orient(p, q, r):
        return (q[0] - p[0]) * (r[1] - p[1]) - (q[1] - p[1]) * (r[0] - p[0])
    o1, o2, o3, o4 = orient(a, b, c), orient(a, b, d), orient(c, d, a), orient(c, d, b)
    if ((o1 > 0 > o2) or (o1 < 0 < o2)) and ((o3 > 0 > o4) or (o3 < 0 < o4)):
        return 0.0

    def ps(p, q, r):
        dx, dy = r[0] - q[0], r[1] - q[1]
        l2 = dx * dx + dy * dy
        t = 0 if not l2 else max(0, min(1, ((p[0] - q[0]) * dx + (p[1] - q[1]) * dy) / l2))
        return math.hypot(p[0] - (q[0] + t * dx), p[1] - (q[1] + t * dy))
    return min(ps(a, c, d), ps(b, c, d), ps(c, a, b), ps(d, a, b))


def stats(lay):
    dist = sum(abs(centro(c)[0] - meta(c[0])[0]) + abs(centro(c)[1] - meta(c[0])[1]) for c in lay) / 3
    cruces = 0
    for i in range(3):
        for j in range(i + 1, 3):
            if seg_dist(centro(lay[i]), meta(lay[i][0]), centro(lay[j]), meta(lay[j][0])) < 4:
                cruces += 1
    return dist, cruces


def propuesta(level):
    wave = math.sin(math.pi * level)
    jit = 2 if level < .1 else (2.4 if level > .9 else 3.6)
    anchors = {"red": (23.5 + rnd.uniform(-jit, jit), 8.5 + 31 * level + rnd.uniform(-jit, jit)),
               "green": (8.5 + 29 * level + rnd.uniform(-jit, jit), 23 + 5 * wave + rnd.uniform(-jit, jit)),
               "blue": (38.5 - 29 * level + rnd.uniform(-jit, jit), 23 - 5 * wave + rnd.uniform(-jit, jit))}
    lim = lambda v: max(INNER_MIN, min(INNER_MAX - CUBE + 1, int(round(v))))
    return [(k, lim(anchors[k][0]), lim(anchors[k][1])) for k in KEYS]


def cancha(level):
    best, best_loss = None, float("inf")
    exp = 6.5 + 35 * level
    want = 0 if level < .28 else 1 if level < .53 else 2 if level < .77 else 3
    for intento in range(700):
        lay = propuesta(level)
        if not all(valid(c, [o for j, o in enumerate(lay) if j != i]) for i, c in enumerate(lay)):
            continue
        d, cr = stats(lay)
        loss = abs(d - exp) / 36 * .55 + abs(cr - want) / 3 * .45 + rnd.uniform(0, .06)
        if loss < best_loss:
            best, best_loss = lay, loss
        if best_loss < .035 and intento > 40:
            break
    return best


def a_vision(lay):
    return [{"color": k, "col": 46.5 - (y + 1.5), "row": (x + 1.5) - 3.5} for k, x, y in lay]


# ---------------------------------------------------------- simulación
import llevar_cubo
_orig_ini = llevar_cubo.LlevarCubo.__init__
def _ini(self, *a, **k):
    _orig_ini(self, *a, **k)
    self.ceder_paso = os.environ.get('CEDER', '1') == '1'
    if os.environ.get('ANCHO_ROVER') == 'chico':
        pass
llevar_cubo.LlevarCubo.__init__ = _ini
import test_autonomia
paso_orig = test_autonomia.Simulador.paso
PERDIDOS = set()


def paso(self, *a, **k):
    r = paso_orig(self, *a, **k)
    if self.row < 2.2 and self.sin_vision_desde is None:
        self.sin_vision_desde = self.t
        PERDIDOS.add(self.id)
    return r


test_autonomia.Simulador.paso = paso
from test_enlace import duo, correr_duo, COLORES
from test_llevar_cubo import entregado

cubos_ok = completas = perdidas = 0
tiempos, motivos = [], collections.Counter()
for n in range(N):
    lay = cancha(D)
    cubos = a_vision(lay)
    PERDIDOS.clear()
    aire, rovers = duo([dict(c) for c in cubos])
    with contextlib.redirect_stdout(io.StringIO()):
        t, minimo = correr_duo(rovers, 240000)
    sim = rovers[0][0]
    k = sum(entregado(sim, c)[0] for c in COLORES)
    cubos_ok += k
    completas += t is not None
    perdidas += bool(PERDIDOS)
    if t is not None:
        tiempos.append(t / 1000)
    for _, ronda, _ in rovers:
        for color, motivo in ronda.fallos.items():
            if color not in ronda.hechos and not entregado(sim, color)[0]:
                motivos[str(motivo).split(":")[0]] += 1
    if os.environ.get("DETALLE"):
        print(n, [(c["color"], round(c["col"], 1), round(c["row"], 1)) for c in cubos], "->", k,
              "t=%s" % (None if t is None else round(t / 1000)), sorted(PERDIDOS),
              [(r.robot_id, r.fallos) for _, r, _ in rovers])
print("D={} | cubos {}/{} | completas {}/{} | t medio {:.1f}s | rondas con rover perdido {} | fallos {}".format(
    D, cubos_ok, 3 * N, completas, N, sum(tiempos) / max(1, len(tiempos)), perdidas, dict(motivos)))
