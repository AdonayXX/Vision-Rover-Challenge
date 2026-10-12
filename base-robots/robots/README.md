# Cómo está organizado el software de los rovers

El firmware que participó en el reto vive en [`codigos/`](codigos/). Cada IdeaBoard ESP32 ejecuta `code.py`, que inicia la red y entra al bucle de `wifi_command_receiver.py`. En cada ciclo se leen sensores y telemetría, se actualiza la ronda y se avanza la misión de movimiento.

```text
code.py
  └─ wifi_command_receiver.py
       ├─ cliente_vision_rover.py → telemetria.py
       ├─ ronda.py → asignacion.py / enlace.py (ESP-NOW)
       ├─ autonomia.py → llevar_cubo.py → rutas.py
       └─ control_movimiento.py → ideaboard.py / hardware_sensores.py
```

| Módulo | Responsabilidad |
| --- | --- |
| [`cliente_vision_rover.py`](codigos/cliente_vision_rover.py) y [`telemetria.py`](codigos/telemetria.py) | Recibir el último mensaje TCP válido y vigilar la antigüedad de los datos. |
| [`ronda.py`](codigos/ronda.py) y [`asignacion.py`](codigos/asignacion.py) | Esperar el inicio oficial, repartir cubos y decidir cuándo tomar otro. |
| [`enlace.py`](codigos/enlace.py) | Compartir estado y tareas entre los dos rovers por ESP-NOW. |
| [`autonomia.py`](codigos/autonomia.py), [`llevar_cubo.py`](codigos/llevar_cubo.py) y [`rutas.py`](codigos/rutas.py) | Navegar, buscar aproximación, empujar, verificar entrega y replanificar. |
| [`control_movimiento.py`](codigos/control_movimiento.py), [`ideaboard.py`](codigos/ideaboard.py) y [`hardware_sensores.py`](codigos/hardware_sensores.py) | Traducir decisiones a motores y leer sensores de la placa. |
| [`registro_fallos.py`](codigos/registro_fallos.py) y [`safemode.py`](codigos/safemode.py) | Registrar errores y apoyar la recuperación. |

Las configuraciones [`rover_10.json`](codigos/rover_10.json) y [`rover_11.json`](codigos/rover_11.json) ajustan sentido y ganancia de los motores de cada robot. [`config_robot.example.json`](codigos/config_robot.example.json) es una plantilla; la configuración local con credenciales no se publica.

## Explorar sin hardware

| Demostración | Qué permite observar |
| --- | --- |
| [`pc/demo_rutas.py`](pc/demo_rutas.py) | Una ruta que evita un cubo y la decisión de esperar ante datos viejos o destino ocupado. |
| [`pc/demo_asignacion.py`](pc/demo_asignacion.py) | Cómo se comparan repartos de los tres cubos. |
| [`pc/demo_navegacion.py`](pc/demo_navegacion.py) | Llegada a un punto en un modelo ideal, con parada por datos caducados. |
| [`tests/`](tests/) | Pruebas de los módulos y simulaciones de la ronda completa. |

Ejecuta las demostraciones desde la raíz del repositorio. Ejecuta `python -B -m unittest discover -s tests` desde `base-robots/robots`. Las pruebas de computadora no certifican precisión física, estabilidad del Wi-Fi ni autonomía de las baterías.

Para llevar el código a la placa, sigue la [guía de firmware](codigos/README.md). Las [notas de coordinación](COORDINACION.md), [rutas](RUTAS.md), [asignación](ASIGNACION.md) y [primeras pruebas](PRIMERA_PRUEBA.md) explican cómo evolucionó cada parte; algunas conservan el lenguaje y las cifras de su etapa original.
