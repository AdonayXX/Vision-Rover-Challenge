"""Peso aproximado de la pila de Python (variables + pila de cada función, como
el n_state de MicroPython) en el momento más hondo debajo de LlevarCubo.tick.
uso: python peso_pila.py <base>"""
import contextlib, io, sys
base = sys.argv[1]
sys.path.insert(0, base + "/tests"); sys.path.insert(0, base + "/codigos")
import llevar_cubo
from test_llevar_cubo import simulador, llevar
from test_enlace import duo, correr_duo

pila, activo = [], [False]
peor = [0, None]
peor_plan = [0, None]


def peso(code):
    return code.co_nlocals + code.co_stacksize + 4      # +4: cabecera del marco


def perfil(frame, evento, arg):
    nombre = frame.f_code.co_filename.replace("\\", "/")
    if "codigos" not in nombre:
        return
    if evento == "call":
        if frame.f_code.co_name == "tick" and nombre.endswith("llevar_cubo.py"):
            activo[0] = True
            pila.clear()
        if activo[0]:
            pila.append(frame.f_code)
            if "<module>" not in [c.co_name for c in pila]:
                total = sum(peso(c) for c in pila)
                if total > peor[0]:
                    peor[0], peor[1] = total, [c.co_name + "(%d)" % peso(c) for c in pila]
                if "plan" in [c.co_name for c in pila] and total > peor_plan[0]:
                    peor_plan[0], peor_plan[1] = total, [c.co_name + "(%d)" % peso(c) for c in pila]
    elif evento == "return" and activo[0] and pila:
        pila.pop()
        if not pila:
            activo[0] = False


sys.setprofile(perfil)
try:
    cubos = [{"color": "blue", "col": 20.0, "row": 27.3}, {"color": "green", "col": 20.2, "row": 15.3},
             {"color": "red", "col": 26.7, "row": 21.5}]
    for color in ("green", "blue"):
        sim = simulador((3.7, 15.7, 0.0), cubos)
        m = llevar(sim, color)
        while sim.t < 60000 and m.activa:
            sim.paso(); m.tick()
    for c8 in ([{"color": "red", "col": 11.0, "row": 19.0}, {"color": "blue", "col": 26.0, "row": 12.0},
                {"color": "green", "col": 21.0, "row": 33.0}],
               [{"color": "red", "col": 20.0, "row": 25.0}, {"color": "blue", "col": 26.0, "row": 23.0},
                {"color": "green", "col": 18.0, "row": 20.0}],
               [{"color": "red", "col": 32.0, "row": 25.0}, {"color": "blue", "col": 27.0, "row": 32.0},
                {"color": "green", "col": 20.0, "row": 9.0}]):
        aire, rovers = duo([dict(c) for c in c8])
        with contextlib.redirect_stdout(io.StringIO()):
            correr_duo(rovers, 60000)
finally:
    sys.setprofile(None)
print("peso maximo (palabras):", peor[0])
print("cadena:", " > ".join(peor[1] or []))
print("peso maximo con A*:", peor_plan[0], " > ".join(peor_plan[1] or []))
