# Rover BLE: control por Bluetooth con movimientos precisos por IMU

Control del **CenfoBot Rover** del Vision Rover Challenge desde el navegador, por Bluetooth Low Energy. El rover usa el giroscopio de su IMU para avanzar recto y girar ángulos exactos.

El proyecto tiene dos partes:

| Archivo | Dónde va | Qué hace |
| --- | --- | --- |
| `code.py` | Raíz de la unidad `CIRCUITPY` de la IdeaBoard | Recibe órdenes por BLE, controla los motores con la IMU y envía telemetría |
| `rover_ble.html` | Un servidor web (`localhost` o GitHub Pages) | Interfaz para conectar, manejar, enviar secuencias y calibrar |

Ambos parten de los ejemplos de la carpeta [`codigos/`](../codigos): `move_heading.py`, `turn_angle.py`, `motor_calibration.py`, `command_protocol.py` y `test_motores.py`.

---

## Qué aporta frente a los ejemplos base

En `move_heading.py` y `turn_angle.py`, cada movimiento empieza desde cero: el rumbo se integra solo durante ese movimiento y el programa se bloquea hasta terminar. `code.py` cambia tres cosas.

**1. Un rumbo global con referencia.** El giroscopio se integra todo el tiempo, desde el arranque. El rover guarda además un *rumbo de referencia*, que es el rumbo que *debería* tener. `TURN|90` gira hasta la referencia más 90°, no hasta el rumbo actual más 90°. Si un giro termina en 89.2°, el siguiente compensa esa diferencia. Por eso los errores no se acumulan: cuatro `FWD` + `TURN|90` cierran un cuadrado.

**2. Giros de lazo cerrado.** `turn_angle.py` acumula grados hasta alcanzar el objetivo y se detiene, de modo que la inercia lo hace pasarse. En `code.py`, el giro:

- frena gradualmente en los últimos `TLENTO` grados, hasta la velocidad mínima `TMIN`;
- corrige en sentido contrario si se pasa;
- termina solo cuando el error es menor que `TOL` y la velocidad angular es menor que 15 °/s durante 120 ms seguidos;
- aborta con un mensaje de error si excede un tiempo máximo proporcional al ángulo.

**3. Un ciclo único que no bloquea.** En cada vuelta del ciclo, el programa lee el giroscopio, lee BLE, avanza un paso del movimiento en curso y envía telemetría. Como nada bloquea, `STOP` interrumpe cualquier movimiento al instante. Las órdenes precisas se encolan y se ejecutan una tras otra.

Además:

- El avance recto usa el PID de `move_heading.py`, con arranque suave (`RAMPA`) para reducir el patinaje y con la derivada calculada sobre la velocidad angular medida, para evitar saltos.
- En reposo el rumbo no se integra (evita que el ruido haga derivar el rumbo) y el drift se afina lentamente.
- Si se pierde la conexión BLE, el rover se detiene.

---

## Requisitos

**Hardware:** CenfoBot Rover con IdeaBoard (ESP32) e IMU LSM6DS3TRC en la dirección I2C `0x6B`.

**En la tarjeta:** CircuitPython con soporte BLE y, en `CIRCUITPY`:

```
CIRCUITPY/
├── code.py
├── ideaboard.py              ← de la carpeta codigos/
└── lib/
    ├── adafruit_ble/
    ├── adafruit_lsm6ds/
    ├── adafruit_motor/
    ├── adafruit_register/
    ├── adafruit_bus_device/
    ├── neopixel.mpy
    └── simpleio.mpy
```

Las librerías están en el [CircuitPython Library Bundle](https://circuitpython.org/libraries). Usa el bundle de la misma versión mayor que tu CircuitPython. Puedes confirmar la versión instalada en el archivo `boot_out.txt` de la tarjeta.

**En la computadora o el celular:** Chrome, Edge u Opera en escritorio o Android. Safari en iPhone no tiene Web Bluetooth; la app [Bluefy](https://apps.apple.com/app/bluefy-web-ble-browser/id1492822055) sí lo tiene.

---

## Puesta en marcha

### 1. Cargar el firmware

Copia `code.py` a la raíz de `CIRCUITPY`, sin renombrarlo. Al arrancar, el rover:

1. enciende el LED en blanco durante 1 s (autoprueba del indicador);
2. lo pone en rojo durante 3 s mientras calibra el giroscopio. **No lo muevas en esos segundos;**
3. empieza a anunciarse por BLE con el nombre `Rover1`, con el LED parpadeando en ámbar.

### 2. Abrir la webapp

Web Bluetooth solo funciona en un contexto seguro (`https://` o `localhost`). **Abrir el HTML con doble clic no sirve.**

Para usarla en tu computadora:

```bash
python3 -m http.server 8000
# luego abrir http://localhost:8000/rover_ble.html
```

Para usarla desde celulares o con un grupo, publícala en GitHub Pages. Ese servicio da `https://`, y el repositorio ya publica la carpeta `docs/`.

### 3. Conectar

Pulsa **Conectar rover** y elige `Rover1` en el selector. El registro debe mostrar `Suscrito a 1, escritura lista` y luego `← PONG Rover1`.

Para probar la interfaz sin hardware, usa **Probar sin rover**. El simulador ejecuta la misma lógica de control que `code.py`.

---

## Convención de ángulos

Se mantiene la convención de `test_motores.py`, donde `right()` gira en sentido horario.

- **Positivo = derecha** (horario, visto desde arriba).
- **0°** es la orientación del rover al encender o al enviar `ZERO`.
- El rumbo se reporta entre −180° y +180°. Internamente no se envuelve, así que `TURN|360` y `TURN|720` funcionan.
- `motor_1` es la rueda izquierda y `motor_2` la derecha.

---

## Protocolo

Es texto plano, una orden por línea terminada en `\n`, con el formato de `command_protocol.py`. Los parámetros marcados con `?` son opcionales.

### Órdenes inmediatas

| Orden | Efecto |
| --- | --- |
| `STOP` | Detiene los motores y vacía la cola |
| `MOTOR\|izq\|der` | Control directo de cada motor, de −1 a 1. Si no llega otro `MOTOR` en 0.6 s, el rover se detiene (watchdog) |
| `PING` | Responde `# PONG Rover1` |
| `STAT` | Reporta el drift, `RG`, `GS`, `KP` y `TMIN` |
| `SET\|clave\|valor` | Cambia un parámetro en vivo (ver la tabla de parámetros) |

### Órdenes en cola

| Orden | Efecto |
| --- | --- |
| `FWD\|seg\|vel?` | Avanza recto sobre el rumbo de referencia |
| `BACK\|seg\|vel?` | Retrocede recto sobre el rumbo de referencia |
| `TURN\|grados\|vel?` | Gira de forma relativa a la referencia |
| `FACE\|rumbo\|vel?` | Gira hasta un rumbo absoluto, por el camino más corto |
| `HEADING\|rumbo\|vel\|seg` | Avanza manteniendo un rumbo absoluto (compatible con el repo) |
| `WAIT\|seg` | Espera |
| `ZERO` | Toma el rumbo actual como 0° |
| `CAL` | Recalibra el drift durante 2.5 s. El rover debe estar quieto |

Una orden manual (`MOTOR`) cancela la cola. Una orden en cola saca al rover del modo manual.

### Mensajes del rover

Cada línea mide menos de 20 bytes para caber en una sola notificación BLE.

| Línea | Significado |
| --- | --- |
| `H,-12.3,T,2` | Telemetría a 5 Hz: rumbo, modo y órdenes en cola |
| `R,90.0` | Rumbo de referencia. Se envía cuando cambia y cada segundo |
| `# ok TURN` | La orden fue aceptada y encolada |
| `# fin 89.6` | Terminó un movimiento, con el rumbo final |
| `# err ...` | Error: parámetros inválidos, tiempo excedido, cola llena |

Modos: `I` quieto, `M` manual, `T` girando, `D` avanzando, `W` esperando, `C` calibrando.

### Ejemplo: cuadrado

```
FWD|1.5
TURN|90
FWD|1.5
TURN|90
FWD|1.5
TURN|90
FWD|1.5
TURN|90
```

---

## Calibración

El CenfoBot no tiene encoders. Toda la precisión depende de que la IMU mida bien y de que los motores respondan de forma pareja. Haz estos pasos en orden, sobre la misma superficie donde competirás y con la batería cargada.

### Paso 1: drift del giroscopio (automático)

Aunque esté quieto, el giroscopio nunca marca exactamente cero. Ese sesgo, el *drift*, se integra y hace que el rumbo se desplace lentamente.

`code.py` lo mide al arrancar (3 s) y lo afina mientras el rover está en reposo. Si el rumbo empieza a desplazarse estando quieto, por ejemplo porque la tarjeta se calentó, pon el rover sobre la mesa sin tocarlo y pulsa **Calibrar giroscopio** (`CAL`).

**Verificación:** con el rover quieto durante un minuto, el rumbo no debería moverse más de 1°.

### Paso 2: signo del giroscopio

Que el rumbo positivo sea la derecha depende de cómo esté montada la IMU.

1. Conecta la webapp.
2. Gira el rover **con la mano** hacia la derecha (sentido horario visto desde arriba).
3. El rumbo debe **subir**.

Si baja, cambia en `code.py`:

```python
GYRO_SIGN = 1.0   # por defecto es -1.0
```

> Con el signo equivocado, el rover gira sin detenerse en cualquier `TURN` (hasta abortar con `# err tiempo`) y se desvía cada vez más en los avances. Si ves eso, revisa este paso primero.

### Paso 3: escala del giroscopio (`GS`)

Cada sensor tiene un pequeño error de escala: al girar 360° reales puede medir 352° o 366°. Ese error es proporcional, así que en los giros grandes se nota mucho.

1. Coloca el rover alineado con una línea de la cuadrícula de la arena. Marca el frente con cinta.
2. En la webapp, elige la secuencia **Prueba de 360°** y pulsa **Ejecutar**.
3. Cuando termine, observa cuánto se pasó o le faltó respecto a la marca.

Para medir con más exactitud, gira el rover a mano:

1. Envía `ZERO`.
2. Gira el rover a mano exactamente una vuelta, hasta que vuelva a quedar alineado con la marca.
3. Lee el rumbo en la webapp. Una vuelta completa debería marcar 0°. Si marca −8°, el sensor midió 352°.

Calcula:

```
GS = 360 / grados_medidos          ej. 360 / 352 = 1.023
```

Pruébalo en vivo con `SET|GS|1.023`. Cuando funcione, escríbelo en `code.py` para que se conserve tras reiniciar:

```python
GYRO_SCALE = 1.023
```

### Paso 4: diferencia entre motores (`RG`)

Los dos motores nunca son idénticos, así que con la misma potencia el rover tiende a desviarse. El PID lo corrige, pero trabaja mejor si la diferencia de fondo ya está compensada.

1. Carga temporalmente `motor_calibration.py` del repo como `code.py`.
2. Coloca el rover en una superficie plana con al menos 1 m libre.
3. El programa hace tres pruebas y muestra en la consola serie:

   ```
   RIGHT_GAIN = 1.0472
   ```

4. Copia ese valor en el `code.py` del rover:

   ```python
   RIGHT_GAIN = 1.0472
   ```

`RG` multiplica la potencia de `motor_2`. También se puede ajustar en vivo con `SET|RG|1.05`.

> La consola serie se puede abrir desde Chrome, sin instalar nada, en [code.circuitpython.org](https://code.circuitpython.org).

### Paso 5: velocidad mínima de giro (`TMIN`)

Cerca del objetivo, el giro baja hasta `TMIN`. Si ese valor no alcanza para vencer la fricción del piso, el rover se queda quieto antes de llegar y termina con `# err tiempo`.

- Si los giros **se quedan cortos** o se atascan cerca del final, sube `TMIN` de 0.02 en 0.02: `SET|TMIN|0.19`.
- Si los giros **oscilan** alrededor del objetivo (se pasan, vuelven y se pasan otra vez), baja `TMIN` o sube `TLENTO`.

Pruébalo con varios `TURN|90` y `TURN|-90`, y anota los rumbos finales (`# fin ...`). El valor correcto es el más bajo que siempre termina sin error.

### Paso 6: PID de avance (opcional)

Los valores por defecto son los de `move_heading.py`. Ajústalos solo si el avance recto no es satisfactorio.

| Síntoma | Ajuste |
| --- | --- |
| Se desvía lentamente y no corrige | Subir `KP` (p. ej. 0.015 → 0.025) |
| Serpentea de lado a lado | Bajar `KP` o subir `KD` |
| Termina siempre un poco desviado hacia el mismo lado | Subir `KI` levemente, o revisar `RG` |
| Patina al arrancar | Subir `RAMPA` (p. ej. 0.4) |

### Resumen de verificación

Coloca el rover sobre la cuadrícula, ejecuta la secuencia **Cuadrado** y mide cuánto se separa del punto de partida. Repite tres veces.

Un rover bien calibrado termina con un rumbo final dentro de ±2° del inicial. El error de posición se debe sobre todo a las duraciones, porque `FWD` se mide en segundos y no en distancia.

---

## Parámetros

Todos se cambian en vivo con `SET|clave|valor`. Los cambios se pierden al reiniciar: los valores definitivos van en el diccionario `PARAMETROS` de `code.py` (o en `GYRO_SCALE` y `RIGHT_GAIN`).

| Clave | Por defecto | Qué controla |
| --- | --- | --- |
| `KP` | 0.015 | Proporcional del avance recto |
| `KI` | 0.0005 | Integral del avance recto |
| `KD` | 0.002 | Derivativo del avance recto |
| `MAXC` | 0.30 | Corrección máxima del PID |
| `RAMPA` | 0.25 s | Duración del arranque suave |
| `VEL` | 0.5 | Velocidad por defecto de `FWD` y `BACK` |
| `TVEL` | 0.35 | Velocidad de giro por defecto |
| `TMIN` | 0.17 | Velocidad mínima de giro (fricción) |
| `TLENTO` | 35° | Distancia al objetivo en que el giro empieza a frenar |
| `TOL` | 1.5° | Tolerancia del giro |
| `RG` | 1.0 | Ganancia de `motor_2` (de `motor_calibration.py`) |
| `GS` | 1.0 | Escala del giroscopio |

Constantes que solo se cambian en `code.py`:

| Constante | Por defecto | Qué controla |
| --- | --- | --- |
| `NOMBRE_BLE` | `"Rover1"` | Nombre BLE. Máximo 8 caracteres |
| `GYRO_SIGN` | −1.0 | Signo del giroscopio (paso 2) |
| `WATCHDOG_MOTOR` | 0.6 s | Tiempo sin `MOTOR` antes de detenerse |
| `AUTODRIFT` | `True` | Afinar el drift en reposo |

---

## La webapp

| Sección | Uso |
| --- | --- |
| **Rumbo** | Dial con el rumbo en vivo y la referencia (marca morada). Toca el dial para orientar el rover (`FACE`) |
| **Movimientos precisos** | Velocidad, duración y velocidad de giro con controles deslizantes. Botones para avanzar, retroceder y girar ±15/45/90/180° |
| **Manejo manual** | Joystick, o flechas/WASD en el teclado. Envía `MOTOR` cada 120 ms y `STOP` al soltar |
| **Secuencia** | Una orden por línea; las líneas que empiezan con `#` son comentarios. Incluye ejemplos |
| **Calibración y ajustes** | `CAL`, `ZERO`, `STAT`, `PING`, ajuste de parámetros y orden libre |
| **Registro** | Lo que se envía (→) y lo que responde el rover (←). *Datos crudos* muestra cada paquete tal como llega |
| **STOP** | Botón fijo en la pantalla. También se activa con la barra espaciadora |

La app parte cada orden en trozos de 20 bytes y espera 35 ms entre líneas, porque el buffer de recepción del rover es de 64 bytes.

---

## Indicador LED

| Color (parpadeando) | Estado |
| --- | --- |
| Blanco fijo 1 s | Autoprueba al arrancar |
| Rojo fijo | Calibrando el giroscopio al arrancar. No mover |
| Ámbar | Esperando conexión |
| Azul | Conectado, quieto |
| Amarillo | Avanzando |
| Morado | Girando |
| Cian | Manejo manual |
| Rojo | Calibrando (`CAL`) |

Si el LED **no parpadea**, el programa se detuvo. Abre la consola serie y busca el `Traceback`.

---

## Solución de problemas

| Observación | Causa probable | Qué hacer |
| --- | --- | --- |
| El botón *Conectar* está desactivado y aparece un aviso rojo | Navegador sin Web Bluetooth o archivo abierto con `file://` | Servir por `localhost` o `https`, usar Chrome |
| El rover no aparece en el selector | No está anunciando, o el nombre es largo y desplaza al UUID | Revisar que el LED parpadee en ámbar y que `NOMBRE_BLE` tenga 8 caracteres o menos |
| Aparece un nombre distinto al esperado | La tarjeta ejecuta otro archivo | Verificar que `code.py` esté en la raíz de `CIRCUITPY`. Conviene cambiar el nombre (`Rover2`, `Rover3`…) en cada versión |
| Conecta pero el registro dice *sin datos hace 4 s* | El programa se detuvo tras conectar | Consola serie: buscar el error |
| Los giros nunca terminan (`# err tiempo`) | `GYRO_SIGN` invertido, o `TMIN` demasiado bajo | Pasos 2 y 5 de la calibración |
| Los giros terminan pero quedan cortos o largos siempre en la misma proporción | Escala del giroscopio | Paso 3 (`GS`) |
| El avance se curva | Diferencia entre motores, o PID débil | Paso 4 (`RG`) y paso 6 |
| El rumbo se desplaza con el rover quieto | Drift mal calibrado | `CAL` con el rover inmóvil |
| El rover se detiene solo en manejo manual | Watchdog: no llegan `MOTOR` cada 0.6 s | Revisar la calidad de la conexión o acercarse al rover |

---

## Limitaciones

- **Sin encoders, la distancia se controla por tiempo.** `FWD|1.5` avanza 1.5 segundos, no 1.5 metros. La distancia real depende de la batería y la superficie. Para posición absoluta, combina estas órdenes con el sistema de visión del reto (ArUco).
- **El rumbo es relativo.** El giroscopio mide cambios, no orientación absoluta, así que el error crece lentamente con el tiempo. En partidas largas, conviene corregir la orientación con la cámara o con `ZERO` en una posición conocida.
- El rover está pensado para recibir órdenes de **una sola conexión** a la vez.
