# Correcciones y trabajo pendiente

**Último avance:** [coordinación de tareas](COORDINACION.md) con mensajes simulados, reservas exclusivas y vencimiento de permisos sin transferir el cubo. La suite actual suma **93 pruebas pasando**. Falta unir acuerdos, rutas y motores, y ejecutar los mensajes en radio real.

**Avance de asignación:** ya se comparan propuestas de reparto inicial por distancia estimada. Ver [ASIGNACION.md](ASIGNACION.md). La suite actual tiene **77 pruebas pasando**; los resultados de distancia no son tiempos de misión ni entregas verificadas.

**Estado más reciente:** hay [rutas estáticas con márgenes para el cuerpo del robot](RUTAS.md), además de lo descrito abajo. La suite completa suma **67 pruebas pasando**. Falta ejecución de rutas con motores, revalidación durante el movimiento y coordinación temporal entre ambos rovers.

**Avance posterior:** el cliente para computadora ya recibe y valida telemetría, maneja fases y datos viejos, y se reconecta al simulador. Hay **40 pruebas pasando** en total. Ver [PRUEBAS_PC.md](PRUEBAS_PC.md). La adaptación a IdeaBoard y la conexión al control de motores siguen pendientes.

**Avance de navegación:** también se implementaron distancia, giro y decisiones hacia un punto. La suite actual suma **52 pruebas pasando**. Ver [NAVEGACION.md](NAVEGACION.md); la llegada está probada con movimiento ideal y aún falta integrar motores y rutas libres.

## Alcance realizado

Se corrigió la base de movimiento y recepción de comandos dentro de `base-robots/robots/`. El código y contrato oficial de visión mantienen su contenido. Los originales fuera de `base-robots/` también permanecen intactos.

| Problema | Corrección |
|---|---|
| Constructor y receptor usaban separadores distintos | Un único parser; formato canónico `|`, admite espacios del receptor anterior |
| TURN y HEADING no eran ejecutados por el receptor | Despacho al controlador compartido |
| NaN/infinito y duraciones inválidas podían pasar | Validación de números finitos y rangos; los constructores también rechazan valores inválidos |
| PING mantenía motores encendidos | PING no renueva movimiento; KEEPALIVE lo renueva explícitamente |
| Avance/giro bloqueaban el programa | `MotionController.update()` ejecuta un paso y devuelve el control |
| Giro acumulaba el valor absoluto de cada muestra | Integra ángulo firmado; el sentido contrario resta progreso |
| Giro podía no terminar con IMU inmóvil | Tiempo máximo de giro configurable, incluso con KEEPALIVE |
| Movimiento seguía tras una pausa grande del bucle | Parada al superar `max_step` |
| `recv()` no existe en socketpool | Recepción mediante `recv_into()` con buffer reutilizable |
| Errores de socket se ocultaban y respuestas podían salir incompletas | Sólo se tolera EAGAIN/EWOULDBLOCK; resto detiene. Escrituras parciales conservan el sufijo |
| Entrada o respuestas pendientes crecían sin límite | Líneas de hasta 128 bytes y respuestas pendientes acotadas |
| Importar avance/giro ejecutaba demostraciones | Módulos sin inicialización de hardware al importar; el receptor arranca en `main()` |
| Estado repetido conservaba mensaje viejo | Actualiza mensaje y limpia código de error al recuperarse |
| Brillo aceptaba valores fuera de rango por usar OR | Acepta únicamente valores entre 0 y 1 |

La API de sockets se contrastó con la [documentación oficial de CircuitPython](https://docs.circuitpython.org/en/latest/shared-bindings/socketpool/index.html). La compatibilidad real de la placa, los sensores y sus bibliotecas requiere prueba física.

## Protocolo de pruebas

Todos los comandos terminan en `\n`. El puerto de pruebas por defecto es 5000; la telemetría oficial sigue en 2026 con su JSON original.

| Línea | Efecto |
|---|---|
| `PING` | Responde `OK`; no permite continuar un movimiento vencido |
| `STOP` | Cancela el movimiento y pone ambos motores a cero |
| `MOTOR|0.3|0.3` | Define velocidades izquierda/derecha entre -1 y 1 |
| `TURN|90|0.3` | Inicia un giro relativo de 90 grados antihorarios |
| `HEADING|0|0.3|2` | Avanza durante 2 segundos manteniendo el rumbo relativo inicial |
| `KEEPALIVE` | Renueva por 0.5 segundos el permiso de la maniobra activa; no reinicia su ángulo ni su duración |

Enviar KEEPALIVE, por ejemplo, cada 0.2 segundos **mientras se desea continuar la maniobra**. También MOTOR/TURN/HEADING conceden permiso al iniciar; repetir TURN o HEADING inicia una nueva maniobra. No usar su repetición como heartbeat. KEEPALIVE tras finalizar o vencer una maniobra devuelve ERROR y no la reinicia. Cada conexión comienza detenida.

`OK` confirma aceptación, no llegada al destino ni entrega del cubo. El reporte remoto de finalización de maniobras queda pendiente. Una orden inválida detiene y devuelve ERROR; descarta las otras órdenes del mismo buffer. Un fallo de conexión detiene y cierra la sesión. La reconexión Wi-Fi automática aún no está implementada.

## Preparación para la prueba física

1. Copiar a la placa `ideaboard.py`, `command_protocol.py`, `control_movimiento.py`, `sesion_comandos.py` y `wifi_command_receiver.py`.
2. Preparar las dependencias de IdeaBoard (`neopixel`, `simpleio`, `adafruit_motor`) y de la IMU (`adafruit_lsm6ds` y sus dependencias), compatibles con el CircuitPython instalado. No están incluidas en esta selección.
3. Copiar `config_robot.example.json` como `config_robot.json` y completar red, parámetros y signos. La configuración local está excluida de Git.
4. Usar este `code.py` para el banco de pruebas:

```python
from wifi_command_receiver import main
main()
```

El arranque calibra el giroscopio con los motores detenidos; mover el robot durante esa calibración produce un error. El ejemplo asume motor_1 izquierdo, motor_2 derecho, velocidades positivas hacia adelante y giro Z positivo antihorario. Confirmar esa correspondencia con ruedas levantadas; ajustar `left_sign`, `right_sign` y `gyro_sign` al montaje real antes de probar en el tablero. Las ganancias de motores y PID son valores iniciales, no una calibración física confirmada.

## API cooperativa para la futura autonomía

Las antiguas funciones bloqueantes se reemplazaron. Ahora se pasa un controlador ya creado:

```python
from control_movimiento import MotionController
from turn_angle import turn_angle

# robot y sensor se crean una sola vez por el programa propietario.
control = MotionController(robot, sensor, drift=drift_calibrado)
try:
    turn_angle(control, degrees=90, speed=0.3)
    while control.mode is not None:
        # Aquí se integrarán telemetría, sensores y decisiones de parada.
        control.update()
finally:
    control.stop()
```

`move_heading(control, heading_target=0, speed=0.3, duration=2)` usa el mismo patrón. Estos ángulos son **relativos al inicio de la maniobra**: todavía no convierten el theta global de ArUco. El watchdog de permiso pertenece a `CommandSession`; quien use el controlador directamente debe integrar sus propias condiciones de permiso basadas en telemetría, fase y sensores. Los ejemplos originales restantes, incluido ESP-NOW, siguen siendo demostraciones independientes.

## Verificación reproducible

Desde `base-robots/`:

```text
python -B -m unittest discover -s robots/tests -v
```

24 pruebas automatizadas con motores, IMU, reloj y socket simulados. Cubren números inválidos, permisos vencidos, PING, giro contrario, IMU inmóvil o inválida, corrección de rumbo, interrupción por STOP, demora del bucle, TCP fragmentado, envío parcial, desconexión y memoria acotada. No prueban fricción, batería, precisión física ni ejecución del firmware CircuitPython en la placa.

## Qué falta para completar el reto

| Prioridad | Trabajo | Cómo sabremos que está listo |
|---|---|---|
| 1 | Preparar dependencias y calibrar hardware | Ambos rovers avanzan y giran en el sentido esperado, y frenan ante pérdida de permiso |
| 2 | Adaptar a IdeaBoard el cliente de telemetría ya probado en PC | Lee NDJSON v2 por identidad, conserva el último estado válido y se reconecta; su permiso se conecta a las paradas por datos viejos, pérdida de conexión o fase no habilitada |
| 3 | Pose global y navegación a coordenadas | Combina ArUco y rumbo local; llega a un punto con tolerancia definida y sin salir del tablero |
| 4 | Integrar sensores y evasión | Respeta la huella del robot y márgenes a bordes/cubos; se detiene o cede paso al compañero |
| 5 | Maniobra de cubos | Se coloca del lado adecuado, empuja o arrastra con las paletas y recupera el cubo si se desvía |
| 6 | Coordinación de dos rovers | Reserva cubos sin duplicar asignaciones, confirma acuerdos, maneja pérdida del compañero y reasigna el tercero |
| 7 | Confirmación de entrega | Usa posición fresca y el criterio de cubo completamente dentro; se retira sin desplazarlo |
| 8 | Programa de misión completo | Integra salida, fases, tareas y recuperación en un único bucle autónomo en los rovers |
| 9 | Optimización y pruebas integrales | Mide entregas correctas, choques y tiempo en rondas repetidas con ambos robots |

Si nuestra variante incluye obstáculos, falta además su percepción y evasión: el sistema de visión copiado corresponde a una edición que publica `obstacles` vacío. El entorno Python utilizado en la revisión no tenía `cv2`; preparar el entorno de visión y verificar la webcam también sigue pendiente.

## Trazabilidad

`INVENTARIO.json` conserva el commit y SHA-256 de origen; registra además el hash actual y si el archivo fue conservado, modificado o agregado. Los hashes describen esta entrega y deben actualizarse al cambiar archivos otra vez. El inventario no se incluye a sí mismo.
