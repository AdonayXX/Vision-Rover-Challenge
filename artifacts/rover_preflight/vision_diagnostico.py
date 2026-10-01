"""Vision real con registro de un cuadro y dos hilos OpenCV para diagnostico."""
from pathlib import Path
import sys

import cv2

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "vision-system"))
from vision import sistema

cv2.setNumThreads(2)
print("Hilos OpenCV:", cv2.getNumThreads(), flush=True)
original = sistema.procesar
saved = False


def procesar(cuadro, *args, **kwargs):
    global saved
    if not saved:
        cv2.imwrite(str(Path(__file__).with_name("cancha_logitech_actual.png")), cuadro.imagen)
        saved = True
    return original(cuadro, *args, **kwargs)


sistema.procesar = procesar
raise SystemExit(sistema.main(["--indice", "1", "--camara", "logitech_c270", "--ventana"]))
