"""Rutas estáticas para el centro del rover, con espacio para su cuerpo.

Se aproxima cada cuerpo con un círculo que lo contiene. Cada tramo completo
se comprueba, incluidos diagonales y enlaces a puntos con decimales.
No predice movimiento del compañero ni produce comandos de motores.
"""
import heapq
import math
from navegacion import _finite


def point_segment_distance(point, start, end):
    dx, dy = end[0] - start[0], end[1] - start[1]
    length2 = dx * dx + dy * dy
    t = 0 if length2 == 0 else max(0, min(1, ((point[0] - start[0]) * dx + (point[1] - start[1]) * dy) / length2))
    return math.hypot(point[0] - start[0] - t * dx, point[1] - start[1] - t * dy)


class RoutePlanner:
    def __init__(self, robot_radius_mm, peer_radius_mm, clearance_mm,
                 obstacle_side_mm=100, step_cells=1, max_nodes=4096,
                 required_colors=("red", "green", "blue")):
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
                circles.append((item["col"], item["row"], radius + margin))
        return {"cols": msg["grid"]["cols"], "rows": msg["grid"]["rows"],
                "margin": margin, "circles": circles, "cell_mm": scale}

    @staticmethod
    def free_segment(scene, start, end):
        margin = scene["margin"]
        for x, y in (start, end):
            if not (margin <= x <= scene["cols"] - margin and margin <= y <= scene["rows"] - margin):
                return False
        for x, y, radius in scene["circles"]:
            if point_segment_distance((x, y), start, end) <= radius + 1e-9:
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
            distance = sum(math.hypot(b[0] - a[0], b[1] - a[1]) for a, b in zip(simplified, simplified[1:]))
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

    def _search(self, scene, start, end):
        step, margin = self.step, scene["margin"]
        xmin, xmax = math.ceil(margin / step), math.floor((scene["cols"] - margin) / step)
        ymin, ymax = math.ceil(margin / step), math.floor((scene["rows"] - margin) / step)
        count = max(0, xmax - xmin + 1) * max(0, ymax - ymin + 1)
        if count > self.max_nodes:
            raise ValueError("grilla_supera_limite_de_nodos")
        nodes = {}
        for x in range(xmin, xmax + 1):
            for y in range(ymin, ymax + 1):
                p = (x * step, y * step)
                if self.free_segment(scene, p, p):
                    nodes[(x, y)] = p
        costs, parents, queue, closed = {}, {}, [], set()
        # Enlaces verificados desde la pose exacta: no redondear al rover
        # a una celda que podría estar del otro lado de un objeto.
        for key, p in nodes.items():
            if self.free_segment(scene, start, p):
                cost = math.hypot(p[0] - start[0], p[1] - start[1])
                costs[key], parents[key] = cost, None
                heapq.heappush(queue, (cost + math.hypot(p[0] - end[0], p[1] - end[1]), key))
        while queue:
            _, key = heapq.heappop(queue)
            if key in closed:
                continue
            closed.add(key)
            p = nodes[key]
            if self.free_segment(scene, p, end):
                path = [end]
                while key is not None:
                    path.append(nodes[key])
                    key = parents[key]
                path.append(start)
                return list(reversed(path))
            for dx, dy in ((-1, -1), (-1, 0), (-1, 1), (0, -1), (0, 1), (1, -1), (1, 0), (1, 1)):
                other = (key[0] + dx, key[1] + dy)
                if other not in nodes or other in closed:
                    continue
                q = nodes[other]
                if not self.free_segment(scene, p, q):
                    continue
                candidate = costs[key] + math.hypot(q[0] - p[0], q[1] - p[1])
                if candidate < costs.get(other, float("inf")):
                    costs[other], parents[other] = candidate, key
                    estimate = candidate + math.hypot(q[0] - end[0], q[1] - end[1])
                    heapq.heappush(queue, (estimate, other))
        return None
