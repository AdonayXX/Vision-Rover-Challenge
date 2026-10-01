"""Evidencia de vision sin crear ningun cliente del rover."""
import collections
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "base-robots/robots/pc"))
from prueba_transporte_cubo import DevelopmentTelemetryState, _mission_reason
from cliente_vision import VisionClient

state = DevelopmentTelemetryState(max_age_ms=600)
client = VisionClient(state)
records, reasons = [], collections.Counter()
end = time.monotonic() + 15
try:
    while time.monotonic() < end:
        client.poll()
        reason = _mission_reason(state, "red", True)
        reasons[str(reason)] += 1
        if state.message is not None and (not records or state.seq != records[-1]["seq"]):
            records.append(dict(seq=state.seq, wall_ms=time.time() * 1000,
                                capture_age_ms=state.capture_age_ms(), reason=reason,
                                message=state.message))
        time.sleep(.02)
finally:
    client.close()
summary = dict(accepted=state.accepted, rejected=state.rejected,
               poll_reasons=dict(reasons), connections=client.connections,
               unique_captures=len({r["message"]["ts_ms"] for r in records}))
result = dict(summary=summary, records=records)
Path(__file__).with_name("vision_verificacion_final.json").write_text(
    json.dumps(result, indent=2), encoding="utf-8")
print(json.dumps(summary))
