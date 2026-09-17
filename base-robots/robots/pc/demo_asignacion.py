"""Comparación local y reproducible de reparto inicial de cubos."""
import argparse
import json
import math
from pathlib import Path
import random
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "codigos"))
from asignacion import compare_assignments
from telemetria import TelemetryState
from demo_rutas import scenario


def run_comparison(count=200, seed=20260915):
    if type(count) is not int or not 1 <= count <= 10000:
        raise ValueError("Cantidad debe estar entre 1 y 10000")
    rng = random.Random(seed)
    total_before = total_after = total_reduction = 0.0
    improved = tied = 0
    example = None
    for _ in range(count):
        message = scenario()
        message["rovers"][0].update(col=5, row=16, theta=0)
        message["rovers"][1].update(col=5, row=27, theta=0)
        # Escenarios de asignación: centros de cubos separados. No certifican
        # accesibilidad con el cuerpo del rover ni maniobras de transporte.
        placed = []
        for cube in message["cubes"]:
            for attempt in range(1000):
                position = (rng.uniform(12, 34), rng.uniform(8, 35))
                if all(math.hypot(position[0] - x, position[1] - y) >= 6 for x, y in placed):
                    break
            else:
                raise RuntimeError("No se pudo generar un escenario separado")
            placed.append(position)
            cube.update(col=position[0], row=position[1])
        state = TelemetryState(monotonic=lambda: 0, wall=lambda: 1000)
        state.connect()
        if not state.accept_line(json.dumps(message)):
            raise AssertionError(state.fault)
        comparison = compare_assignments(state)
        if comparison["estado"] != "PROPUESTA":
            raise AssertionError(comparison)
        before = comparison["cercano"]["carga_maxima_mm"]
        after = comparison["equilibrado"]["carga_maxima_mm"]
        if after > before + 1e-8:
            raise AssertionError("El minimo enumerado fue peor que un candidato")
        total_before += before
        total_after += after
        total_reduction += comparison["reduccion_porcentaje"]
        if before - after > 1e-8:
            improved += 1
        else:
            tied += 1
        # Mostrar el primer caso, no seleccionar sólo uno especialmente favorable.
        if example is None:
            example = {"observacion": message, "comparacion": comparison}
    return {"resultado": "OK", "escenarios": count, "semilla": seed,
            "modelo": "distancias_rectas_velocidades_iguales_sin_interacciones",
            "carga_maxima_media_cercano_mm": total_before / count,
            "carga_maxima_media_equilibrado_mm": total_after / count,
            "reduccion_porcentual_media_por_escenario": total_reduction / count,
            "mejoras_en_el_modelo": improved, "empates_en_el_modelo": tied,
            "primer_escenario": example}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scenarios", type=int, default=200)
    parser.add_argument("--seed", type=int, default=20260915)
    parser.add_argument("--output", help="Guardar informe JSON en esta ruta")
    args = parser.parse_args()
    try:
        report = run_comparison(args.scenarios, args.seed)
    except ValueError as error:
        parser.error(str(error))
    print("Comparacion por distancias estimadas; no mide tiempos ni entregas reales.")
    for strategy in ("cercano", "equilibrado"):
        print("Primer escenario /", strategy)
        for robot in report["primer_escenario"]["comparacion"][strategy]["robots"]:
            print("  Robot {}: {} | carga {:.1f} mm".format(robot["robot_id"], " -> ".join(robot["cubos"]), robot["carga_mm"]))
    summary = {k: v for k, v in report.items() if k != "primer_escenario"}
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    if args.output:
        Path(args.output).write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
