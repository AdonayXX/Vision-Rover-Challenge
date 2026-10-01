"""CircuitPython ejecuta este archivo cuando la placa entra en modo seguro.

En modo seguro NO corre code.py: el rover queda encendido pero mudo, sin
Wi-Fi, hasta un reset manual. Pasa tras una caida de voltaje (BROWNOUT) o un
fallo interno. Se guarda el motivo para que la PC lo muestre y se reinicia
normal, asi el rover vuelve solo.
"""
import microcontroller
import supervisor

from registro_fallos import guardar

motivo = supervisor.runtime.safe_mode_reason
# Si una persona pidio el modo seguro (boton al arrancar), se respeta.
if motivo not in (supervisor.SafeModeReason.USER, supervisor.SafeModeReason.PROGRAMMATIC):
    guardar("modo_seguro", str(motivo).split(".")[-1])
    microcontroller.reset()
