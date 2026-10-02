# Firmware del CenfoBot Rover

Código que corre **en la placa** (IdeaBoard, CircuitPython 9) del rover del
**Vision Rover Challenge**. Se sube con `tools/subir_esp32_gui.py` ("Subir paquete
completo"); la lista exacta está en `DEFAULT_FILES` de esa herramienta.

Los ejemplos originales de la universidad (motores, IR, ultrasonido, color, IMU,
PID, ESP-NOW, etc.) siguen en la carpeta `codigos/` de la raíz del repositorio.

| Área | Código | Propósito |
| --- | --- | --- |
| **Arranque** | `code.py`, `safemode.py` | Arranca el servidor; si algo falla, guarda el motivo y reinicia solo. |
| **Servidor** | `wifi_command_receiver.py`, `wifi_config.py` | Wi-Fi, puerto de comandos 5000, watchdog de placa y bucle principal. |
| **Protocolo** | `command_protocol.py`, `sesion_comandos.py` | Órdenes de desarrollo (`STOP`, `MOTOR`, `SENSORS`, `IR`, `LLEVAR`, `RUTA`…). |
| **Motores** | `control_movimiento.py`, `ideaboard.py` | Potencias con rampa y control de bajo nivel de la IdeaBoard. |
| **Sensores** | `sensores_rover.py`, `hardware_sensores.py`, `config_sensores.json` | Ultrasonido, IR del suelo y sensor de color. |
| **Visión** | `cliente_vision_rover.py`, `telemetria.py` | Lee la telemetría oficial (TCP 2026) directamente en la placa. |
| **Modelo** | `modelo_rover.py`, `modelo_movimiento.json` | Cómo se mueve el rover y predicción de su pose (sale de `pc/calibrar_movimiento.py`). |
| **Autonomía** | `autonomia.py` | Ir a un punto con control continuo, adaptación en marcha y red de seguridad. |
| **Autonomía** | `llevar_cubo.py` | Llevar un cubo a su zona: planificar, aproximar, alinear, empujar y verificar. |
| **Rutas** | `rutas.py`, `navegacion.py`, `rutas_placa.py` | Planificador A* que esquiva cubos y la medición de su costo en la placa. |
| **Diagnóstico** | `registro_fallos.py` | Guarda en memoria no volátil por qué falló o se reinició la placa. |
| **Configuración** | `config_robot.example.json` | Plantilla de `config_robot.json` (ese no se sube a git: lleva la clave Wi-Fi). |

Pendientes de decidir en el incremento 3 (coordinación de los dos rovers):
`asignacion.py`, `coordinacion.py`, `robot_state.py`, `espnow_bidirectional.py`,
`ESPNOW/` y `transporte.py`.
