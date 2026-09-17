"""Reparto inicial de tres cubos: propuestas por distancia, sin ejecutar tareas.

Modelo: cada tarea cuesta aproximación recta + entrega recta; el robot termina
en el centro del destino. Ambos robots tienen la misma velocidad supuesta.
No incluye giros, empuje, colisiones, esperas ni factibilidad de rutas.
"""
import math

COLORS = ("blue", "green", "red")


def _distance(a, b, scale):
    return math.hypot(b["col"] - a["col"], b["row"] - a["row"]) * scale


def _inputs(state):
    for color in COLORS:
        reason = state.reason(color)
        if reason is not None:
            raise ValueError(reason)
    ids = tuple(sorted((state.robot_id, state.peer_id)))
    grid = state.message["grid"]
    depots = {color: state.depot(color) for color in COLORS}
    for depot in depots.values():
        if depot is None or not (0 <= depot["col"] <= grid["cols"] and 0 <= depot["row"] <= grid["rows"]):
            raise ValueError("destino_ausente_o_fuera_de_cancha")
    return ids, {identity: state.rover(identity) for identity in ids}, {
        color: state.cube(color) for color in COLORS}, depots, grid["cell_mm"]


def _evaluate(ids, robots, cubes, depots, scale, orders):
    plans = []
    for identity, order in zip(ids, orders):
        position, load, tasks = robots[identity], 0.0, []
        for color in order:
            approach = _distance(position, cubes[color], scale)
            delivery = _distance(cubes[color], depots[color], scale)
            load += approach + delivery
            tasks.append({"color": color, "aproximacion_mm": approach,
                          "entrega_mm": delivery, "acumulado_mm": load})
            position = depots[color]
        plans.append({"robot_id": identity, "cubos": list(order),
                      "carga_mm": load, "tareas": tasks})
    return {"robots": plans, "carga_maxima_mm": max(p["carga_mm"] for p in plans),
            "distancia_total_mm": sum(p["carga_mm"] for p in plans)}


def _nearest(ids, robots, cubes, depots, scale):
    remaining = list(COLORS)
    positions = dict(robots)
    loads = {identity: 0.0 for identity in ids}
    orders = {identity: [] for identity in ids}
    # Ambos reciben una tarea al inicio; desempate determinista por ID.
    for turn in range(3):
        identity = ids[turn] if turn < 2 else min(ids, key=lambda r: (loads[r], r))
        color = min(remaining, key=lambda c: (_distance(positions[identity], cubes[c], scale), c))
        orders[identity].append(color)
        loads[identity] += (_distance(positions[identity], cubes[color], scale)
                            + _distance(cubes[color], depots[color], scale))
        positions[identity] = depots[color]
        remaining.remove(color)
    return _evaluate(ids, robots, cubes, depots, scale, [orders[r] for r in ids])


def _balanced(ids, robots, cubes, depots, scale):
    best, best_key = None, None
    # Seis órdenes de colores, con dos cortes: 12 repartos ordenados.
    # Se exige al menos un cubo por rover, por tratarse del reparto inicial.
    for first in COLORS:
        for second in COLORS:
            if second == first:
                continue
            third = next(c for c in COLORS if c != first and c != second)
            permutation = (first, second, third)
            for split in (1, 2):
                orders = (permutation[:split], permutation[split:])
                plan = _evaluate(ids, robots, cubes, depots, scale, orders)
                key = (plan["carga_maxima_mm"], plan["distancia_total_mm"], orders)
                if best_key is None or key < best_key:
                    best, best_key = plan, key
    return best


def compare_assignments(state):
    """Compara dos propuestas sobre la misma lectura y las mismas hipótesis.

    No reserva cubos, no comunica decisiones y no confirma entregas. Ambos
    rovers pueden obtener el mismo resultado porque se ordenan por ID.
    """
    result = {"estado": "ESPERAR", "motivo": None, "seq": state.seq,
              "rutas_verificadas": False,
              "modelo": "distancias_rectas_velocidades_iguales_sin_interacciones"}
    try:
        inputs = _inputs(state)
        nearest = _nearest(*inputs)
        balanced = _balanced(*inputs)
        # No devolver una propuesta que envejeció durante el cálculo.
        _inputs(state)
        if state.seq != result["seq"]:
            raise ValueError("observacion_cambio_durante_calculo")
        before = nearest["carga_maxima_mm"]
        reduction = before - balanced["carga_maxima_mm"]
        result.update(estado="PROPUESTA", motivo="comparacion_de_repartos_iniciales",
                      cercano=nearest, equilibrado=balanced,
                      reduccion_carga_maxima_mm=reduction,
                      reduccion_porcentaje=100 * reduction / before if before else 0.0,
                      candidatos_evaluados=12)
    except (ValueError, TypeError, KeyError, OverflowError) as error:
        result["motivo"] = str(error)
    return result
