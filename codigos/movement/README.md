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

En `move_heading.py` y `turn_angle.py`, cada movimiento empieza desde cero: el rumbo se integra solo durante ese movimiento y el programa se bloquea hasta terminar. `code.py` cambia cinco cosas.

**1. Un rumbo global con referencia.** El giroscopio se integra todo el tiempo, desde el arranque. El rover guarda además un *rumbo de referencia*, que es el rumbo planificado. `TURN|90` gira hasta la referencia más 90°, no hasta el rumbo actual más 90°. Si un giro termina en 89.2°, el siguiente compensa esa diferencia. Por eso los errores no se acumulan: cuatro `FWD` + `TURN|90` cierran un cuadrado.

**Los movimientos rectos mantienen su ángulo inicial.** `FWD` y `BACK` capturan el rumbo en el instante en que empiezan y lo sostienen durante todo el tramo. Si el giro anterior quedó en 89.2°, el rover avanza recto a 89.2° en lugar de curvarse buscando 90°. La referencia no cambia, así que el siguiente giro sigue corrigiendo esos 0.8°: los tramos salen rectos y el error de los giros tampoco se acumula.

**2. Giros de lazo cerrado.** `turn_angle.py` acumula grados hasta alcanzar el objetivo y se detiene, de modo que la inercia lo hace pasarse. En `code.py`, el giro:

- frena gradualmente en los últimos `TLENTO` grados, hasta la velocidad mínima `TMIN`;
- corrige en sentido contrario si se pasa;
- termina solo cuando el error es menor que `TOL` y la velocidad angular es menor que 15 °/s durante 120 ms seguidos;
- aborta con un mensaje de error si excede un tiempo máximo proporcional al ángulo.

**3. Un ciclo único que no bloquea.** En cada vuelta del ciclo, el programa lee el giroscopio, lee BLE, avanza un paso del movimiento en curso y envía telemetría. Como nada bloquea, `STOP` interrumpe cualquier movimiento al instante. Las órdenes precisas se encolan y se ejecutan una tras otra.

**4. Avance recto con prealimentación.** El PID de `move_heading.py` era débil (`KP` 0.015, `KI` 0.0005): con un motor más lento que el otro, el rover terminaba cada tramo desviado varios grados. En `code.py`:

- Las ganancias son más firmes y el término derivativo está filtrado, para que la vibración de los motores no se convierta en sacudidas.
- El rover **aprende el desbalance** de los motores (`TRIM`): al terminar cada avance guarda la corrección promedio que necesitó, por separado para adelante y atrás. El siguiente avance la aplica desde el inicio, proporcional a la velocidad del momento, y el PID solo corrige lo que falte.
- La rampa de arranque parte de `VMIN` y no de cero, para que ambos motores salgan juntos de su zona muerta. Si uno arranca antes que el otro, el rover pivotea en el primer instante.
- Al final de cada avance, el rover sugiere un valor de `RIGHT_GAIN` (`# RG sug`) calculado a partir de la corrección que necesitó. Así se calibra el desbalance de los motores sin un programa aparte.

**5. Verificación con el acelerómetro.** El acelerómetro no mide velocidad: a velocidad constante marca lo mismo que detenido. Lo que sí detecta son los *cambios* de velocidad, y con ellos el rover verifica cada avance:

- **Arranque:** debe aparecer un pulso en la dirección ordenada. Si no aparece, el rover está bloqueado o patinando. Si aparece al revés, los motores están invertidos. En ambos casos se detiene.
- **Durante el tramo:** un pulso contrario brusco es un choque, y el rover se detiene.
- **Frenado:** debe aparecer un pulso contrario suave. Si no aparece, el rover probablemente se trabó a mitad del tramo, y lo avisa.

Para eso cada avance tiene tres fases, todas reportadas como modo `D`: **base** (0.12 s quieto, mide la gravedad y la inclinación del piso para restarlas), **movimiento** y **frenado** (0.25 s detenido, mide el pulso de frenado y deja al rover quieto antes de la siguiente orden).

Además:

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
| `STAT` | Reporta el drift, `RG`, `GS`, `KP`, `KI`, el desbalance aprendido, `TMIN` y el eje del acelerómetro |
| `SET\|clave\|valor` | Cambia un parámetro en vivo (ver la tabla de parámetros) |

### Órdenes en cola

| Orden | Efecto |
| --- | --- |
| `FWD\|seg\|vel?` | Avanza recto manteniendo el ángulo con el que inició |
| `BACK\|seg\|vel?` | Retrocede recto manteniendo el ángulo con el que inició |
| `TURN\|grados\|vel?` | Gira de forma relativa a la referencia |
| `FACE\|rumbo\|vel?` | Gira hasta un rumbo absoluto, por el camino más corto |
| `HEADING\|rumbo\|vel\|seg` | Avanza manteniendo un rumbo absoluto (compatible con el repo) |
| `WAIT\|seg` | Espera |
| `ZERO` | Toma el rumbo actual como 0° |
| `CAL` | Recalibra el drift durante 2.5 s. El rover debe estar quieto |
| `EJE` | Avanza 0.5 s y detecta qué eje del acelerómetro apunta hacia adelante. Necesita unos 20 cm libres |

Una orden manual (`MOTOR`) cancela la cola. Una orden en cola saca al rover del modo manual.

### Mensajes del rover

Cada línea mide menos de 20 bytes para caber en una sola notificación BLE.

| Línea | Significado |
| --- | --- |
| `H,-12.3,T,2` | Telemetría a 5 Hz: rumbo, modo y órdenes en cola |
| `R,90.0` | Rumbo de referencia. Se envía cuando cambia y cada segundo |
| `# ok TURN` | La orden fue aceptada y encolada |
| `# fin 89.6` | Terminó un giro, con el rumbo final |
| `# fin 89.4 e0.2` | Terminó un avance: rumbo final y desvío respecto al ángulo inicial |
| `#emax 2.1@0.4 c.12` | Después de cada avance: desvío máximo, en qué segundo ocurrió, y corrección máxima aplicada |
| `# RG sug 0.742` | Valor de `RIGHT_GAIN` que haría avanzar recto sin corrección (solo en avances de más de ~0.8 s) |
| `#a+.11 f-.14 v.03` | Verificación: pulso de arranque, pulso de frenado y vibración, en g |
| `# err sin mov v.04` | No hubo pulso de arranque: bloqueado o patinando. Se detiene y vacía la cola |
| `# err dir -.12` | El pulso de arranque fue al revés: motores invertidos. Se detiene y vacía la cola |
| `# choque -.48g` | Impacto durante el avance. Se detiene y vacía la cola |
| `# aviso no frenó` | Arrancó pero no se detectó frenado: quizá se trabó a mitad del tramo |
| `# aviso: falta EJE` | La verificación está desactivada porque el eje del acelerómetro no está calibrado |
| `# eje Y+ p.15` | Resultado de `EJE`: eje de avance, signo y tamaño del pulso |
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

El CenfoBot no tiene encoders. Toda la precisión depende de que la IMU mida bien y de que los motores respondan de forma pareja. Haz estos pasos **en orden**, sobre la misma superficie donde competirás y con la batería cargada.

Todas las órdenes de esta sección se envían desde la webapp. Las que no tienen botón (`EJE`, `SET|…`) se escriben en el campo de orden libre de **Calibración y ajustes**.

> **Importante:** `SET` cambia los valores en vivo, pero se pierden al reiniciar la tarjeta. Cada paso indica qué línea escribir en `code.py` para conservar el resultado. Al final de esta sección hay un resumen de todas.

### Paso 1: drift del giroscopio (automático)

Aunque esté quieto, el giroscopio nunca marca exactamente cero. Ese sesgo, el *drift*, se integra y hace que el rumbo se desplace lentamente.

`code.py` lo mide al arrancar (3 s, con el LED en rojo) y lo afina mientras el rover está en reposo. **No muevas el rover mientras el LED está rojo.**

Si el rumbo empieza a desplazarse estando quieto, por ejemplo porque la tarjeta se calentó, pon el rover sobre la mesa sin tocarlo y pulsa **Calibrar giroscopio** (`CAL`).

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
2. Envía `ZERO`.
3. Gira el rover **a mano** exactamente una vuelta, hasta que vuelva a quedar alineado con la marca.
4. Lee el rumbo en la webapp. Una vuelta exacta debería marcar 0°. Si marca −8°, el sensor midió 352°.

Calcula:

```
GS = 360 / grados_medidos          ej. 360 / 352 = 1.023
```

Pruébalo con `SET|GS|1.023` y con la secuencia **Prueba de 360°**: el rover debe volver a quedar alineado con la marca. Luego escríbelo en `code.py`:

```python
GYRO_SCALE = 1.023
```

### Paso 4: velocidad mínima de giro (`TMIN`)

Cerca del objetivo, el giro baja hasta `TMIN`. Si ese valor no alcanza para vencer la fricción del piso, el rover se queda quieto antes de llegar y termina con `# err tiempo`.

1. Envía varios `TURN|90` y `TURN|-90`, y anota los rumbos finales (`# fin …`).
2. Ajusta:
   - Si los giros **se quedan cortos** o se atascan cerca del final, sube `TMIN` de 0.02 en 0.02: `SET|TMIN|0.19`.
   - Si los giros **oscilan** alrededor del objetivo (se pasan, vuelven y se pasan otra vez), baja `TMIN` o sube `TLENTO`.
3. El valor correcto es el más bajo que siempre termina sin error, dentro de ±1.5°.

Escríbelo en el diccionario `PARAMETROS` de `code.py`:

```python
    "TMIN": 0.19,
```

### Paso 5: eje del acelerómetro (`EJE`)

La verificación de los avances necesita saber qué eje del acelerómetro apunta hacia adelante. Mientras no esté calibrado, los avances funcionan pero sin verificación, y el rover avisa una vez con `# aviso: falta EJE`.

1. Comprueba que los motores estén bien conectados: `FWD|1` debe mover el rover hacia adelante. `EJE` asume que el avance fue hacia adelante.
2. Pon el rover en el piso con unos 20 cm libres al frente.
3. Envía `EJE`. El rover avanza medio segundo y responde, por ejemplo:

   ```
   eje Y+ p.15
   ```

   Esto significa: eje Y, signo positivo, pulso de 0.15 g. Si responde `err eje sin pulso`, el pulso fue demasiado débil: sube la velocidad con `SET|VEL|0.7` y repite.

4. Escríbelo en `code.py` (X = 0, Y = 1, Z = 2; `+` = 1, `−` = −1):

   ```python
   ACC_EJE = 1
   ACC_SIGNO = 1
   ```

### Paso 6: equilibrio de los motores (`RIGHT_GAIN`)

Los dos motores nunca son idénticos, así que con la misma potencia el rover se curva. El PID lo corrige, pero si el desbalance es grande se queda sin margen. `RIGHT_GAIN` compensa el desbalance de fondo multiplicando la potencia de `motor_2`.

El rover calcula el valor por ti:

1. Envía tres `FWD|2`, uno tras otro. Después de cada uno, el registro muestra algo así:

   ```
   fin -1.0 e-1.0
   emax 9.5@0.3 c.30
   RG sug 0.742
   ```

2. Si los valores de `RG sug` de los tres avances son parecidos, aplica uno de ellos en vivo:

   ```
   SET|RG|0.742
   ```

   Al cambiar `RG`, el desbalance aprendido (`TRIM`) se reinicia, porque dependía del valor anterior.

3. Repite dos o tres `FWD|2`. Ahora deberías ver:
   - `c` (la corrección máxima) por debajo de 0.1;
   - `RG sug` cerca del valor que aplicaste;
   - `emax` por debajo de 2°.

   Si `RG sug` sigue lejos del valor aplicado, aplica el nuevo y repite. Suele bastar con dos rondas.

4. Escríbelo en `code.py`:

   ```python
   RIGHT_GAIN = 0.742
   ```

**Cómo leer `emax 9.5@0.3 c.30`:** el desvío máximo fue de 9.5°, a los 0.3 s del arranque, y la corrección llegó a 0.30.

- Si `c` llega a 0.45 (el valor de `MAXC`), el PID se quedó sin margen: el desbalance es demasiado grande para compensarlo solo con corrección. Ajustar `RIGHT_GAIN` lo resuelve.
- Si el desvío máximo ocurre siempre en los primeros 0.3 s, el problema está en el arranque. Ver el paso 8.

> Una alternativa es `motor_calibration.py` del repositorio, que calcula `RIGHT_GAIN` con tres pruebas y lo muestra en la consola serie. `RG sug` tiene la ventaja de medirse con el mismo programa, la misma velocidad y el mismo piso que vas a usar.

### Paso 7: umbrales de la verificación (`UARR`, `UCHO`)

Los pulsos de arranque y frenado dependen del peso del rover, la batería, la velocidad y el piso. Los umbrales por defecto son razonables, pero conviene confirmarlos con datos.

1. Haz varios `FWD|2` a la velocidad **más baja** que vayas a usar, y otros a la más alta. Después de cada uno aparece:

   ```
   a+.11 f-.14 v.03
   ```

   `a` es el pulso de arranque, `f` el de frenado y `v` la vibración, en g.

2. Ajusta:
   - **`UARR`** (0.04 g por defecto) debe quedar claramente por debajo del `a` más bajo que veas, por ejemplo a la mitad. Si aparecen `err sin mov` en avances que sí se movieron, bájalo: `SET|UARR|0.03`.
   - **`UCHO`** (0.35 g por defecto) debe quedar muy por encima del `|f|` más alto que veas. Si aparecen `choque` sin que haya chocado, súbelo: `SET|UCHO|0.45`.
   - Velocidades muy bajas o una `RAMPA` larga producen pulsos más pequeños. Si necesitas avanzar muy lento, quizá tengas que bajar `UARR`.

3. Escríbelos en `PARAMETROS`:

   ```python
       "UARR": 0.04,
       "UCHO": 0.35,
   ```

Si algo falla en plena prueba y necesitas seguir, `SET|VERIF|0` desactiva toda la verificación hasta reiniciar.

### Paso 8: ajuste fino del avance (opcional)

Si después del paso 6 el avance todavía no es satisfactorio, usa las líneas `fin` y `emax`:

| Síntoma | Ajuste |
| --- | --- |
| `emax` alto y ocurre en los primeros 0.3 s | Un motor arranca antes que el otro. Sube `VMIN` (p. ej. `SET\|VMIN\|0.18`) |
| Patina al arrancar | Sube `RAMPA` (p. ej. 0.4) |
| Se desvía lentamente durante todo el tramo | Sube `KP` (p. ej. 0.03 → 0.04) |
| Serpentea de lado a lado | Baja `KP` o sube `KD` (p. ej. 0.004) |
| El primer avance tras reiniciar sale peor que los siguientes | Normal: el rover está aprendiendo el desbalance (`TRIM`). Si es mucho, revisa `RIGHT_GAIN` |
| `emax` y `e` bajos, pero el rover igual se ve torcido | El rumbo se mantiene pero el giroscopio no mide bien la rotación real: revisa `GS` (paso 3) |

### Resumen: qué escribir en `code.py`

Al terminar, `code.py` debería tener tus valores en estas líneas:

| Línea | Paso | Ejemplo |
| --- | --- | --- |
| `GYRO_SIGN` | 2 | `-1.0` |
| `GYRO_SCALE` | 3 | `1.023` |
| `"TMIN"` en `PARAMETROS` | 4 | `0.19` |
| `ACC_EJE`, `ACC_SIGNO` | 5 | `1`, `1` |
| `RIGHT_GAIN` | 6 | `0.742` |
| `"UARR"`, `"UCHO"` en `PARAMETROS` | 7 | `0.04`, `0.35` |
| Otros parámetros que hayas ajustado | 8 | `"VMIN": 0.18` |

Después de copiar el archivo a la tarjeta, envía `STAT` para confirmar que los valores cargaron.

### Verificación final

Coloca el rover sobre la cuadrícula, ejecuta la secuencia **Cuadrado** y mide cuánto se separa del punto de partida. Repite tres veces.

Un rover bien calibrado termina con un rumbo final dentro de ±2° del inicial, sin errores de verificación. El error de posición se debe sobre todo a las duraciones, porque `FWD` se mide en segundos y no en distancia.

---

## Parámetros

Todos se cambian en vivo con `SET|clave|valor`. Los cambios se pierden al reiniciar: los valores definitivos van en el diccionario `PARAMETROS` de `code.py` (o en `GYRO_SCALE` y `RIGHT_GAIN`).

| Clave | Por defecto | Qué controla |
| --- | --- | --- |
| `KP` | 0.03 | Proporcional del avance recto (por grado de error) |
| `KI` | 0.015 | Integral del avance recto |
| `KD` | 0.002 | Derivativo del avance recto, sobre la velocidad angular filtrada |
| `MAXC` | 0.45 | Corrección máxima por motor |
| `RAMPA` | 0.25 s | Duración del arranque suave |
| `VMIN` | 0.12 | Potencia desde la que parte la rampa (zona muerta de los motores) |
| `TRIM` | 1 | 1 = aprender el desbalance de los motores entre avances; 0 = no |
| `VEL` | 0.5 | Velocidad por defecto de `FWD` y `BACK` |
| `TVEL` | 0.35 | Velocidad de giro por defecto |
| `TMIN` | 0.17 | Velocidad mínima de giro (fricción) |
| `TLENTO` | 35° | Distancia al objetivo en que el giro empieza a frenar |
| `TOL` | 1.5° | Tolerancia del giro |
| `RG` | 1.0 | Ganancia de `motor_2`. Cambiarla reinicia el desbalance aprendido |
| `GS` | 1.0 | Escala del giroscopio |
| `VERIF` | 1 | 1 = verificar los avances con el acelerómetro; 0 = no |
| `AEJE` | −1 | Eje de avance del acelerómetro (0 X, 1 Y, 2 Z; −1 sin calibrar). Lo fija `EJE` |
| `ASIG` | 1 | Signo del eje de avance. Lo fija `EJE` |
| `UARR` | 0.04 g | Pulso mínimo de arranque |
| `UCHO` | 0.35 g | Pulso contrario que se considera choque |
| `VENT` | 0.5 s | Tiempo para que aparezca el pulso de arranque |

Constantes que solo se cambian en `code.py`:

| Constante | Por defecto | Qué controla |
| --- | --- | --- |
| `NOMBRE_BLE` | `"Rover1"` | Nombre BLE. Máximo 8 caracteres |
| `GYRO_SIGN` | −1.0 | Signo del giroscopio (paso 2) |
| `GYRO_SCALE` | 1.0 | Valor inicial de `GS` (paso 3) |
| `RIGHT_GAIN` | 1.0 | Valor inicial de `RG` (paso 6) |
| `ACC_EJE`, `ACC_SIGNO` | −1, 1 | Valores iniciales de `AEJE` y `ASIG` (paso 5) |
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

El menú de parámetros de la webapp no incluye los de la verificación ni `VMIN` o `TRIM`. Para esos, y para `EJE`, usa el campo de orden libre: por ejemplo `SET|UARR|0.03`.

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
| Los giros nunca terminan (`# err tiempo`) | `GYRO_SIGN` invertido, o `TMIN` demasiado bajo | Pasos 2 y 4 de la calibración |
| Los giros terminan pero quedan cortos o largos siempre en la misma proporción | Escala del giroscopio | Paso 3 (`GS`) |
| El avance se curva y `c` llega a 0.45 | Desbalance grande entre motores | Paso 6 (`RIGHT_GAIN`) |
| El avance se desvía al arrancar (`emax` en los primeros 0.3 s) | Un motor sale de la zona muerta antes que el otro | Paso 8: subir `VMIN` |
| Aparece `aviso: falta EJE` | El eje del acelerómetro no está calibrado o no se guardó en `code.py` | Paso 5 |
| `err sin mov` en avances que sí se movieron | Umbral de arranque alto para esa velocidad, o eje mal calibrado | Paso 7: bajar `UARR`; repetir paso 5 |
| `err dir` con motores bien conectados | `EJE` se calibró con los motores invertidos | Repetir el paso 5 con los motores correctos |
| `choque` sin haber chocado | Umbral de choque bajo para ese frenado o ese piso | Paso 7: subir `UCHO` |
| El rumbo se desplaza con el rover quieto | Drift mal calibrado | `CAL` con el rover inmóvil |
| El rover se detiene solo en manejo manual | Watchdog: no llegan `MOTOR` cada 0.6 s | Revisar la calidad de la conexión o acercarse al rover |

---

## Limitaciones

- **Sin encoders, la distancia se controla por tiempo.** `FWD|1.5` avanza 1.5 segundos, no 1.5 metros. La distancia real depende de la batería y la superficie. Para posición absoluta, combina estas órdenes con el sistema de visión del reto (ArUco).
- **El rumbo es relativo.** El giroscopio mide cambios, no orientación absoluta, así que el error crece lentamente con el tiempo. En partidas largas, conviene corregir la orientación con la cámara o con `ZERO` en una posición conocida.
- **El acelerómetro solo ve los cambios de velocidad.** Confirma el arranque, el frenado y los choques, pero no puede saber si el rover sigue avanzando a mitad de un tramo a velocidad constante. Si se traba suavemente, sin golpe, solo se nota al final por la falta de frenado (`aviso no frenó`).
- El rover está pensado para recibir órdenes de **una sola conexión** a la vez.
