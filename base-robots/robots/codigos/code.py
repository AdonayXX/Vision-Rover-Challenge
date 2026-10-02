"""Solo IdeaBoard: guardar en la placa como code.py para la prueba de banco."""
import time

import supervisor

from registro_fallos import guardar

try:
    # El import va dentro: si falla (falta un archivo, sin memoria) la placa
    # se quedaria con Wi-Fi activo (responde ping) pero sin servidor.
    from wifi_command_receiver import main
    main()
except Exception as error:
    # Sin esto la placa queda muerta hasta un reinicio manual. main() ya paro
    # los motores en su finally; Ctrl+C por serial (no es Exception) no recarga.
    print("Error fatal:", error, "- reiniciando en 3 s")
    try:
        guardar("error_fatal", "{}: {}".format(type(error).__name__, error))
    except Exception:
        pass
    time.sleep(3)
    supervisor.reload()
