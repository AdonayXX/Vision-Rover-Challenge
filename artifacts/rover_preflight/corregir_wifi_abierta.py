"""Respalda, actualiza y verifica solo wifi_config.py; no envia motores."""
import hashlib
import ast
import json
from pathlib import Path
import time

from ampy.files import Files
from ampy.pyboard import Pyboard


class CircuitPythonFiles(Files):
    def get(self, filename):
        # CircuitPython 9 usa binascii, no el ubinascii que espera ampy.get.
        self._pyboard.enter_raw_repl()
        try:
            result = self._pyboard.exec_(
                "print(repr(open({!r}, 'rb').read()))".format(filename))
            return ast.literal_eval(result.decode("utf-8").strip())
        finally:
            self._pyboard.exit_raw_repl()

ROOT = Path(__file__).resolve().parents[2]
local = ROOT / "base-robots/robots/codigos/wifi_config.py"
board = Pyboard("COM3")
board.serial.timeout = .2
fs = CircuitPythonFiles(board)
try:
    original = fs.get("wifi_config.py")
    backup = Path(__file__).with_name("wifi_config.antes.py")
    if not backup.exists():
        backup.write_bytes(original)
    config_before = fs.get("config_robot.json")
    cfg = json.loads(config_before)
    print("Configuracion conservada; pregunta al arrancar:", cfg.get("ask_wifi_on_boot"), flush=True)
    data = local.read_bytes()
    fs.put("wifi_config.py", data)
    if fs.get("wifi_config.py") != data:
        fs.put("wifi_config.py", original)
        raise RuntimeError("Verificacion fallo; archivo anterior restaurado")
    if fs.get("config_robot.json") != config_before:
        raise RuntimeError("La configuracion cambio durante la verificacion")
    print("wifi_config.py actualizado y verificado:", hashlib.sha256(data).hexdigest(), flush=True)
    print("config_robot.json permanece identico. Reiniciando programa...", flush=True)
    board.serial.write(b"\x04")
    end, chunks = time.monotonic() + 20, []
    while time.monotonic() < end:
        chunk = board.serial.read(max(1, board.serial.in_waiting))
        if chunk:
            chunks.append(chunk.decode("utf-8", "replace"))
    output = "".join(chunks)
    for key in ("wifi_ssid", "wifi_password"):
        if cfg.get(key):
            output = output.replace(cfg[key], "[oculto]")
    Path(__file__).with_name("arranque_wifi_corregido.log").write_text(output, encoding="utf-8")
    print(output)
finally:
    board.close()
