"""Lee diagnostico y configuracion no secreta por USB; no envia motores."""
import json
import sys
from pathlib import Path
import time

import serial

ROOT = Path(__file__).resolve().parents[2]
cfg = json.loads((ROOT / "base-robots/robots/codigos/config_robot.json").read_text(encoding="utf-8"))


def clean(text):
    for key in ("wifi_ssid", "wifi_password"):
        if cfg.get(key):
            text = text.replace(cfg[key], "[oculto]")
    return text


def read_for(port, seconds):
    end, chunks = time.monotonic() + seconds, []
    while time.monotonic() < end:
        data = port.read(max(1, port.in_waiting))
        if data:
            chunks.append(data.decode("utf-8", "replace"))
    return clean("".join(chunks))


port = serial.Serial(port=None, baudrate=115200, timeout=.1, write_timeout=2)
port.dtr = port.rts = False
port.port = "COM3"
records = []
try:
    port.open()
    if "--esperar-reset" in sys.argv:
        print("Monitor USB abierto: esperando RESET durante 25 segundos.", flush=True)
        records.append("ARRANQUE OBSERVADO:\n" + read_for(port, 25))
    if "--reset" in sys.argv:
        port.rts = True
        time.sleep(.1)
        port.rts = False
        records.append("ARRANQUE TRAS RESET SOLICITADO:\n" + read_for(port, 8))
    records.append("SALIDA INICIAL:\n" + read_for(port, 2))
    port.write(b"\r\x03")
    time.sleep(.2)
    port.write(b"\x03\x02\r")
    reply = read_for(port, 2)
    records.append("INTERRUPCION PARA INSPECCION:\n" + reply)
    if ">>>" not in reply:
        raise RuntimeError("La placa no presento el REPL; no se enviaron consultas.")
    query = (
        "import os,json,microcontroller,wifi; "
        "c=json.load(open('config_robot.json')); "
        "print('DIAGNOSTICO',json.dumps({'reset_reason':str(microcontroller.cpu.reset_reason),"
        "'ask_wifi_on_boot':c.get('ask_wifi_on_boot'),"
        "'ssid_guardado':bool(c.get('wifi_ssid')) and c.get('wifi_ssid')!='TU_RED_WIFI',"
        "'password_guardado':bool(c.get('wifi_password')) and c.get('wifi_password')!='TU_PASSWORD',"
        "'ip':str(wifi.radio.ipv4_address),"
        "'files':[(n,os.stat(n)[6]) for n in os.listdir('/') if n.endswith('.py') or n.endswith('.json')]})); "
        "print('CODE',open('code.py').read())"
    )
    port.write(query.encode("utf-8") + b"\r\n")
    records.append("CONFIGURACION SIN CREDENCIALES:\n" + read_for(port, 3))
finally:
    port.close()
    result = "\n".join(records)
    Path(__file__).with_name("inspeccion_usb.log").write_text(result, encoding="utf-8")
    print(result)
