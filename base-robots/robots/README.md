# Código reutilizable de los rovers

**Para conectar la placa:** [primera prueba de conexion y motores](PRIMERA_PRUEBA.md), con pulsos individuales y comprobacion de parada.

Último avance: [estados y acuerdos de tareas](COORDINACION.md), con reservas, confirmaciones y pérdida de comunicación simulada. La suite actual suma **100 pruebas**.

Nuevo: [reparto inicial de cubos](ASIGNACION.md), con comparación de dos estrategias en 200 escenarios y 77 pruebas en la suite completa.

Para trabajar sin robot ni cámara: [pruebas de telemetría en computadora](PRUEBAS_PC.md). Incluyen una demostración automática con el publicador simulado y el cliente nuevo.

También están disponibles los [cálculos y decisiones de navegación hacia un punto](NAVEGACION.md), probados con movimiento ideal sin motores.

El paso siguiente ya está implementado: [rutas estáticas con espacio para el cuerpo del rover](RUTAS.md). Se prueban rodeando cubos y esperando cuando el paso se bloquea.

Los archivos de `codigos/` parten de los ejemplos originales; los módulos de control y recepción ya se corrigieron. Se mantienen juntos porque varios importan `ideaboard` desde esa misma ubicación. Ver [CORRECCIONES.md](CORRECCIONES.md) para uso, cambios de API y pendientes.

| Área | Archivos | Uso previsto |
|---|---|---|
| Hardware | [ideaboard.py](codigos/ideaboard.py) | Acceso a motores, entradas y LED de la placa |
| Movimiento básico | [test_motores.py](codigos/test_motores.py) | Comprobar motores y sentidos de giro |
| Calibración | [motor_calibration.py](codigos/motor_calibration.py) | Compensar diferencias entre motores |
| Control | [control_movimiento.py](codigos/control_movimiento.py), [move_heading.py](codigos/move_heading.py), [turn_angle.py](codigos/turn_angle.py) | Avance y giro cooperativos; `code_PID.py` queda como ejemplo original |
| Sensores | [code_4IR.py](codigos/code_4IR.py), [code_ultrasonic.py](codigos/code_ultrasonic.py), [color_detect.py](codigos/color_detect.py), [code_acc.py](codigos/code_acc.py) | Lectura de infrarrojos, ultrasonido, color e IMU |
| Comunicación entre robots | [espnow_bidirectional.py](codigos/espnow_bidirectional.py), [guía ESP-NOW](codigos/ESPNOW/README.md) | Base de mensajes directos entre los dos rovers |
| Comandos para pruebas | [wifi_command_receiver.py](codigos/wifi_command_receiver.py), [command_protocol.py](codigos/command_protocol.py), [sesion_comandos.py](codigos/sesion_comandos.py) | Receptor y protocolo unificados, con watchdog y procesamiento por ciclos |
| Estado | [robot_state.py](codigos/robot_state.py) | Estado operativo del rover; no implementa la misión |
| Registro | [code_storage.py](codigos/code_storage.py) | Referencia para almacenar mediciones |

La recepción del estado del tablero se estudia en [el cliente del contrato](../vision-system/contrato/test_client.py). El receptor Wi-Fi de esta carpeta recibe órdenes de motores: no sustituye a ese cliente.

El receptor usa [config_robot.example.json](codigos/config_robot.example.json) como plantilla para la configuración local. Los IDs y MAC del ejemplo ESP-NOW siguen pendientes de adaptación. El reglamento copiado reserva las decisiones durante la ronda a los rovers; el control desde computadora queda como herramienta de desarrollo.
