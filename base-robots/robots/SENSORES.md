# Sensores locales y visión

El código está integrado en PC y firmware, pero NO se ha cargado ni probado en
el hardware. La configuración actual está en `diagnostic_only=true`: bloquea
TODOS los movimientos, incluidos los del control manual, y permite leer sensores.
Por solicitud del usuario se habilitó `allow_unverified_echo_diagnostic=true`
para leer el montaje existente de Cenfotec. `echo_3v3_confirmed` sigue en false:
NO se ha medido ni certificado el voltaje. Una lectura válida no lo certifica.
Este modo NO protege contra sobretensión; solo impide órdenes de motor.
No equivale a una puesta en marcha ni resuelve por sí solo el rumbo.

## Cableado y límites eléctricos

- HC-SR04: Trig IO25, Echo IO26. VCC va a alimentación, **no a la señal IO26**.
  Verificar que el V+ usado entregue la tensión admitida por el sensor
  (5 V en el HC-SR04 estándar), no asumir que V+ es 5 V si el jumper toma Vin.
  Echo de un HC-SR04 estándar es 5 V: verificar divisor/adaptación a 3,3 V antes
  de conectarlo al ESP32. Sin confirmación se permite únicamente la excepción
  de lectura diagnóstica explícitamente solicitada; no se autoriza navegación.
- IR analógicos: Sen1 IO36, Sen2 IO39, Sen3 IO34, Sen4 IO35; alimentación 3,3 V.
- Color: NeoPixel DI IO32. AO IO4 es ADC2 y **no funciona con Wi-Fi en ESP32**.
  El usuario indicó que moverá AO: `color.analog` ya está preparado en `IO33`.
  Completar físicamente ese cambio con la placa apagada antes de subirlo.
- Motores: conexiones existentes, sin cambiar polaridad ni calibración.
- QWIIC identifica un conector/bus, no el modelo de sensor conectado. La IMU
  existente sigue bajo `use_imu` en config_robot.json; no se activa por asumir
  que cualquier dispositivo QWIIC es un giroscopio.

Cambiar conexiones con placa y alimentación de motores apagadas. Una opción en
JSON NO protege eléctricamente el pin: confirmar físicamente antes de marcarla.

Referencias: [ADC2 y Wi-Fi en CircuitPython](https://docs.circuitpython.org/en/stable/shared-bindings/analogio/index.html),
[pines ESP32](https://documentation.espressif.com/esp32-wroom-32_datasheet_en.html),
[niveles del HC-SR04](https://learn.adafruit.com/distance-measurement-ultrasound-hcsr04?view=all).

## Subir y leer sin movimiento

1. Completar el cambio de AO a IO33 con la placa apagada. La configuración actual
   es solo de diagnóstico: no modificar credenciales ni signos de motores.
2. Usar **Subir paquete completo** en la interfaz de carga. Incluye
   `hardware_sensores.py`, `sensores_rover.py`, `config_sensores.json`, receptor,
   controlador y protocolo. El botón de Wi-Fi por sí solo no actualiza el paquete.
3. Reiniciar placa, conectar Wi-Fi y cerrar el control manual. Desde la raíz:

```powershell
.\vision-system\.venv\Scripts\python.exe -X utf8 -B .\base-robots\robots\pc\leer_sensores.py --robot-ip 10.141.29.149
```

El monitor confirma STOP y solo consulta `SENSORS`; nunca envía movimiento.
El firmware rechaza también MOTOR, TURN y HEADING aunque se conecte otro cliente.
Debe mostrar distancia, cuatro IR y `color_raw` (ambiente/R/G/B). Revisar
`errors`: si faltan pines/módulos/eco, se informa, no se inventa una lectura.
El código usa `pulseio`, `digitalio`, `analogio`, `neopixel`; deben estar
disponibles en la versión de CircuitPython de la placa. El eco se atiende
cooperativamente con vencimiento de 30 ms; no hay espera larga bloqueando STOP.

## Color: calibrar cada cubo

El muestreo actual espera 200 ms tras cambiar cada iluminacion y toma cinco
lecturas separadas al menos 10 ms; usa su mediana para descartar picos aislados.
Es cooperativo: no agrega esperas bloqueantes a STOP ni al watchdog. Un barrido
tarda al menos 0,96 s; usar `--segundos 30` al calibrar para reunir 12 barridos.
Subir tanto `sensores_rover.py` como `config_sensores.json` para aplicar el cambio.
Esta mejora no garantiza respuesta optica: si no hay senal, no inventa un color
ni relaja el criterio de estabilidad. Inestabilidad no demuestra movimiento.

La configuración local usa `color.polarity=1`: en la prueba manual de AO IO33,
el usuario midió 2819–3971 tapado y 37613 iluminado. La lectura aumenta con
la luz; esto confirma respuesta de AO, no reconocimiento de colores todavía.
Subir esta configuración a la placa antes de calibrar. Este resultado aplica
al sensor probado: verificar la polaridad por separado en el otro rover.
Si se cambia la polaridad de un sensor ya calibrado, borrar sus perfiles y
calibrar nuevamente los tres colores; no reutilizar perfiles de otro montaje.

Motores parados, presentar el cubo al sensor a la distancia y orientación que
tendrá durante el empuje. Repetir el comando cambiando `red` por `green` y `blue`:

```powershell
.\vision-system\.venv\Scripts\python.exe -X utf8 -B .\base-robots\robots\pc\leer_sensores.py --robot-ip 10.141.29.149 --segundos 30 --calibrar-color red
```

Se requieren al menos 12 barridos distintos y estables. Los perfiles se guardan
SOLO en el archivo local. Tras los tres, volver a subir `config_sensores.json`
y reiniciar la placa. Verificar los tres colores y que fondo/sin cubo resulte
desconocido; si no, recalibrar señal mínima, tolerancia y margen con lecturas
reales. No basta con elegir el canal mayor: sin calibración no se etiqueta color.

Si el sensor mira al SUELO, no puede confirmar un cubo frente a las palas.
Hace falta confirmar su montaje antes de usar la comprobación de empuje.

## Qué controla cada sensor

- **Ultrasonido:** la placa rechaza o detiene avance con distancia <= `stop_mm`
  (inicialmente 80 mm), sin esperar la PC. Falta de eco/fallo/lectura vieja
  bloquea movimiento; un eco ausente NO equivale a camino libre.
  Es una medida desde el sensor, no entre centros de objetos. Solo mira al
  frente: no protege trasera/laterales ni identifica el cubo objetivo.
- **IR:** lecturas crudas y frescura vigiladas. `floor_ranges=null` significa
  que NO hay detector de borde calibrado. El ajedrezado blanco/negro no puede
  tratarse como línea de borde. Solo habilitar cuatro rangos permitidos si las
  mediciones de toda la cancha y su exterior permiten distinguirlos realmente.
- **Color:** escaneo ambiente/R/G/B con rover detenido. La PC exige una clase
  calibrada, fresca e igual al cubo objetivo antes de cada pulso de empuje.
- **Visión:** mantiene posición global, orientación, rutas, depósitos y
  protección geométrica. No se modificó el contrato de visión v2.

La distancia de parada de 80 mm es un valor inicial de banco, **no una
calibración de contacto**. Puede impedir llegar a tocar el cubo. Medir con
motores detenidos cuánto marca el ultrasonido cuando el cubo toca las palas y
qué distancia permite frenar; revisar umbral, montaje y velocidad antes de
habilitar transporte físico. No hay una excepción que ignore obstáculos al
empujar. Por debajo del rango mínimo útil, la lectura se considera inválida.

El BAT autónomo ahora incluye `--usar-sensores` y no acepta firmware antiguo
sin `SENSORS`. La prueba `--solo-verificar` continúa siendo solo de visión/rutas.
STOP y el watchdog de 0,5 s se conservan; consultar sensores no renueva permiso
para mover. Todo sigue sujeto a verificación física antes de una misión.
Para salir del diagnóstico habrá que verificar la conexión eléctrica, completar
la calibración, y subir la configuración con `echo_3v3_confirmed=true` y
`diagnostic_only=false`. No marcar el voltaje como confirmado solo porque se
reciben distancias. La excepción diagnóstica no habilita motores fuera de ese modo.
