"""Copia de la configuración de la U con la preparación acortada (solo pruebas).

No toca vision-system: lee su config_vision.json, cambia `ronda.preparacion_ms`
y escribe la copia en la carpeta temporal. Se usa con `--config`:

    python -B pc/config_prueba_vision.py --preparacion-s 5
    python -m vision.sistema --ventana --config <ruta que imprime>

En competencia NO se usa: la preparación es la de la U (60 s).
"""
import argparse
import json
import os
from pathlib import Path
import tempfile

ORIGINAL = Path(__file__).resolve().parents[3] / "vision-system" / "vision" / "config_vision.json"


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--preparacion-s", type=float, default=5.0)
    args = p.parse_args()
    config = json.loads(ORIGINAL.read_text(encoding="utf-8"))
    config["ronda"]["preparacion_ms"] = int(args.preparacion_s * 1000)
    salida = Path(tempfile.gettempdir()) / "config_vision_prueba.json"
    salida.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")
    print(os.fspath(salida))


if __name__ == "__main__":
    main()
