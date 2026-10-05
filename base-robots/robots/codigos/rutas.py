"""Rutas estáticas para el centro del rover, con espacio para su cuerpo.

Se aproxima cada cuerpo con un círculo que lo contiene. Cada tramo completo
se comprueba, incluidos diagonales y enlaces a puntos con decimales.
No predice movimiento del compañero ni produce comandos de motores.
"""
import math
from array import array
from navegacion import _finite

# Cola de prioridad de ENTEROS sobre una lista que se reserva una vez: en la
# placa ni las tuplas ni los float por entrada, ni la lista que crece y se
# achica, dejan memoria suelta. `tam` es cuántos hay; lo demás es basura.
def _meter(cola, tam, valor):
    if tam == len(cola):
        cola.append(valor)
    else:
        cola[tam] = valor
    i = tam
    while i > 0:
        padre = (i - 1) >> 1
        if cola[padre] <= cola[i]:
            break
        cola[padre], cola[i] = cola[i], cola[padre]
        i = padre
    return tam + 1


def _sacar(cola, tam):
    """Devuelve el menor; el que llama resta uno a `tam`."""
    primero = cola[0]
    tam -= 1
    if tam:
        cola[0] = cola[tam]
        i = 0
        while True:
            hijo = 2 * i + 1
            if hijo >= tam:
                break
            if hijo + 1 < tam and cola[hijo + 1] < cola[hijo]:
                hijo += 1
            if cola[i] <= cola[hijo]:
                break
            cola[i], cola[hijo] = cola[hijo], cola[i]
            i = hijo
    return primero

try:
    from math import hypot
except ImportError:
    def hypot(x, y):
        return math.sqrt(x * x + y * y)


def point_segment_distance(point, start, end):
    dx, dy = end[0] - start[0], end[1] - start[1]
    length2 = dx * dx + dy * dy
    t = 0 if length2 == 0 else max(0, min(1, ((point[0] - start[0]) * dx + (point[1] - start[1]) * dy) / length2))
    return hypot(point[0] - start[0] - t * dx, point[1] - start[1] - t * dy)


class RoutePlanner:
    def __init__(self, robot_radius_mm, peer_radius_mm, clearance_mm,
                 obstacle_side_mm=100, step_cells=1, max_nodes=4096,
                 required_colors=("red", "green", "blue"), edge_mm=None):
        for value in (robot_radius_mm, peer_radius_mm, obstacle_side_mm, step_cells):
            if _finite(value) <= 0:
                raise ValueError("Radios, lado de obstaculo y paso deben ser positivos")
        if _finite(clearance_mm) < 0:
            raise ValueError("Margen debe ser no negativo")
        if type(max_nodes) is not int or max_nodes <= 0:
            raise ValueError("Limite de nodos invalido")
        if any(c not in ("red", "green", "blue") for c in required_colors):
            raise ValueError("Color requerido invalido")
        self.radius = robot_radius_mm
        self.peer_radius = peer_radius_mm
        self.clearance = clearance_mm
        self.obstacle_side = obstacle_side_mm
        self.step = step_cells
        self.max_nodes = max_nodes
        self.required_colors = tuple(required_colors)
        # edge_mm: cuánto tiene que quedar el CENTRO del rover dentro de la
        # cancha. None = el radio más el margen, como con cualquier objeto.
        # La orilla no es una pared: con un valor chico el cuerpo puede
        # asomarse fuera para empujar un cubo pegado al borde. Un número vale
        # para los cuatro lados; (izquierda, arriba, derecha, abajo) los separa.
        self.edge = edge_mm
        # True: también alejarse de un cubo que ya está demasiado cerca (lo usa
        # la ronda para estacionarse; las misiones lo resuelven con SALIR).
        self.escapar = False
        self._n = None                     # tamaño de los búferes del A*

    def scene(self, state):
        reason = state.reason()
        if reason is not None:
            raise ValueError(reason)
        for color in self.required_colors:
            if state.cube(color) is None:
                raise ValueError("cubo_requerido_ausente: " + color)
        msg = state.message
        age = state.capture_age_ms()
        scale = msg["grid"]["cell_mm"]
        margin = (self.radius + self.clearance) / scale
        own = state.rover(state.robot_id)
        circles = []
        for group in ("rovers", "cubes", "obstacles"):
            for item in msg[group]:
                if item["age_ms"] + age >= state.max_age_ms:
                    raise ValueError("entidad_vieja: " + group)
                if group == "rovers" and item["id"] == state.robot_id:
                    continue
                if group == "rovers":
                    radius = self.peer_radius / scale
                elif group == "cubes":
                    radius = msg["cube_side"] * math.sqrt(2) / 2
                else:
                    radius = self.obstacle_side * math.sqrt(2) / (2 * scale)
                if own is not None and (group == "rovers" or self.escapar):
                    # Ya más cerca que el margen: del compañero al salir juntos
                    # (16 cm), de un cubo recién entregado al retirarse. Sin
                    # esto no había ruta a ningún lado y se quedaba trabado.
                    # Puede alejarse, nunca acercarse más.
                    cerca = hypot(item["col"] - own["col"], item["row"] - own["row"])
                    if cerca < radius + margin:
                        circles.append((item["col"], item["row"], max(0.0, cerca - 0.05)))
                        continue
                circles.append((item["col"], item["row"], radius + margin))
        cols, rows = msg["grid"]["cols"], msg["grid"]["rows"]
        edges = (margin, margin, margin, margin)
        if self.edge is not None:
            # Puede tapar un marcador de esquina: la visión de la U aguanta uno
            # menos sin perder precisión (AnclajeCancha conserva la homografía).
            lados = self.edge if isinstance(self.edge, (tuple, list)) else (self.edge,) * 4
            edges = tuple(e / scale for e in lados)
        return {"cols": cols, "rows": rows, "margin": margin, "edge": min(edges), "edges": edges,
                "circles": circles, "cell_mm": scale}

    @staticmethod
    def free_segment(scene, start, end):
        # Sin llamadas a funciones Python: en la placa la pila (pystack) es de
        # ~1,5 KB y el A* llama a esto desde lo más hondo. Es la misma cuenta
        # que point_segment_distance, comparada al cuadrado.
        # Bordes (izq, arriba, der, abajo) en una sola variable: cada variable
        # local pesa en la pila de la placa (cancha 3-oct: "pystack exhausted").
        e = scene.get("edges") or (scene["margin"],) * 4
        for x, y in (start, end):
            if not (e[0] <= x <= scene["cols"] - e[2] and e[1] <= y <= scene["rows"] - e[3]):
                return False
        sx, sy = start
        dx, dy = end[0] - sx, end[1] - sy
        length2 = dx * dx + dy * dy
        for x, y, radius in scene["circles"]:
            t = 0 if length2 == 0 else max(0, min(1, ((x - sx) * dx + (y - sy) * dy) / length2))
            ex, ey = x - sx - t * dx, y - sy - t * dy
            limite = radius + 1e-9
            if ex * ex + ey * ey <= limite * limite:
                return False
        return True

    def plan(self, state, target):
        result = {"estado": "ESPERAR", "motivo": None, "puntos": [],
                  "distancia_mm": None, "seq": state.seq,
                  "validacion": "estatica_con_tamanos_configurados"}
        try:
            end = (_finite(target["col"]), _finite(target["row"]))
            scene = self.scene(state)
            own = state.rover(state.robot_id)
            start = (own["col"], own["row"])
            if not self.free_segment(scene, start, start):
                raise ValueError("origen_sin_espacio")
            if not self.free_segment(scene, end, end):
                raise ValueError("destino_sin_espacio")
            if self.free_segment(scene, start, end):
                path = [start] if start == end else [start, end]
            else:
                path = self._search(scene, start, end)
                if path is None:
                    raise ValueError("sin_ruta_en_la_grilla")
            # Reconstruida: se puede quitar un vértice sólo si el atajo es libre.
            simplified = [path[0]]
            i = 0
            while i < len(path) - 1:
                j = len(path) - 1
                while j > i + 1 and not self.free_segment(scene, path[i], path[j]):
                    j -= 1
                simplified.append(path[j])
                i = j
            distance = sum(hypot(b[0] - a[0], b[1] - a[1]) for a, b in zip(simplified, simplified[1:]))
            # El cálculo puede consumir parte del plazo de frescura.
            self.scene(state)
            if state.seq != result["seq"]:
                raise ValueError("observacion_cambio_durante_calculo")
            result.update(estado="RUTA", motivo="camino_libre_en_esta_observacion",
                          puntos=[{"col": p[0], "row": p[1]} for p in simplified],
                          distancia_mm=distance * scene["cell_mm"])
        except (ValueError, KeyError, TypeError, OverflowError) as error:
            result["motivo"] = str(error)
        return result

    def _buffers(self, n):
        # Se reservan UNA vez y se reusan en cada ruta. En la placa el montón
        # se fragmenta con cada mensaje de la visión, y un A* que pide
        # memoria nueva en cada plan termina sin un bloque seguido (cancha
        # 2-oct: MemoryError de 1784 bytes al planificar el tercer cubo).
        if self._n != n:
            self._n = None
            self._estado = self._costo = self._padre = self._cola = None
            self._estado = bytearray(n)              # 0 ocupado, 1 abierto, 2 cerrado
            self._costo = array("f", [0.0] * n)
            self._padre = array("h", [0] * n)        # -1 = enlazado al origen
            self._cola = [0] * (2 * n)
            self._n = n
        return self._estado, self._costo, self._padre, self._cola

    def _search(self, scene, start, end):
        step = self.step
        e = scene.get("edges") or (scene["margin"],) * 4
        xmin, xmax = math.ceil(e[0] / step), math.floor((scene["cols"] - e[2]) / step)
        ymin, ymax = math.ceil(e[1] / step), math.floor((scene["rows"] - e[3]) / step)
        ancho = max(0, ymax - ymin + 1)
        count = max(0, xmax - xmin + 1) * ancho
        if count > self.max_nodes:
            raise ValueError("grilla_supera_limite_de_nodos")
        if count == 0:
            return None
        # Tamaño fijo (la grilla entera) para no reasignar cuando cambia el margen.
        n = max(count, (math.floor(scene["cols"] / step) + 1) * (math.floor(scene["rows"] / step) + 1))
        estado, costo, padre, cola = self._buffers(n)
        # Nodo i = (x - xmin) * ancho + (y - ymin); prioridad entera
        # int(estimado * 64) * n + i: sin tuplas, y a igual estimado gana el
        # menor (x, y), como antes con las tuplas.
        i = 0
        for x in range(xmin, xmax + 1):
            for y in range(ymin, ymax + 1):
                p = (x * step, y * step)
                estado[i] = 1 if self.free_segment(scene, p, p) else 0
                costo[i] = 1e30
                i += 1
        tam = 0
        # Enlaces verificados desde la pose exacta: no redondear al rover
        # a una celda que podría estar del otro lado de un objeto.
        for i in range(count):
            if estado[i]:
                p = ((xmin + i // ancho) * step, (ymin + i % ancho) * step)
                if self.free_segment(scene, start, p):
                    cost = hypot(p[0] - start[0], p[1] - start[1])
                    costo[i], padre[i] = cost, -1
                    tam = _meter(cola, tam, int((cost + hypot(p[0] - end[0], p[1] - end[1])) * 64) * n + i)
        while tam:
            i = _sacar(cola, tam) % n
            tam -= 1
            if estado[i] != 1:
                continue
            estado[i] = 2
            x, y = xmin + i // ancho, ymin + i % ancho
            p = (x * step, y * step)
            if self.free_segment(scene, p, end):
                path = [end]
                while i != -1:
                    path.append(((xmin + i // ancho) * step, (ymin + i % ancho) * step))
                    i = padre[i]
                path.append(start)
                return list(reversed(path))
            for dx, dy in ((-1, -1), (-1, 0), (-1, 1), (0, -1), (0, 1), (1, -1), (1, 0), (1, 1)):
                ox, oy = x + dx, y + dy
                if not (xmin <= ox <= xmax and ymin <= oy <= ymax):
                    continue
                j = (ox - xmin) * ancho + (oy - ymin)
                if estado[j] != 1:
                    continue
                q = (ox * step, oy * step)
                if not self.free_segment(scene, p, q):
                    continue
                candidate = costo[i] + hypot(q[0] - p[0], q[1] - p[1])
                if candidate < costo[j]:
                    costo[j], padre[j] = candidate, i
                    tam = _meter(cola, tam, int((candidate + hypot(q[0] - end[0], q[1] - end[1])) * 64) * n + j)
        return None
