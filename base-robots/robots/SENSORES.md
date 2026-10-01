# Sensores locales y visión

El sensor ultrasónico fue probado físicamente en una CRCibernetica IdeaBoard con
ESP32 y CircuitPython 9.2.4. La alimentación **Motores y Ultrasónico** debe estar
activada. Con esa alimentación activa, IO25 genera TRIG, IO26 recibe ECHO y las
mediciones respondieron de forma coherente entre aproximadamente 8 y 26 cm.
La configuración actual usa `diagnostic_only=false`; esta es la única opción
global que inhibe los motores por modo diagnóstico.

## Cableado y límites eléctricos

- HC-SR04/compatible: VCC a V+, GND a GND, Trig IO25 y Echo IO26. La habilitación
  de alimentación **Motores y Ultrasónico** de la IdeaBoard debe estar activa.
  Si el módulo tiene un quinto pin OUT, queda sin conectar.
- IR analógicos: Sen1 IO36, Sen2 IO39, Sen3 IO34, Sen4 IO35; alimentación 3,3 V.
- Color: NeoPixel DI IO32. AO IO4 es ADC2 y **no funciona con Wi-Fi en ESP32**.
  El usuario indicó que moverá AO: `color.analog` ya está preparado en `IO33`.
  Completar físicamente ese cambio con la placa apagada antes de subirlo.
- Motores: conexiones existentes, sin cambiar polaridad ni calibración.
- QWIIC identifica un conector/bus, no el modelo de sensor conectado. La IMU
  existente sigue bajo `use_imu` en config_robot.json; no se activa por asumir
  que cualquier dispositivo QWIIC es un giroscopio.

Referencias: [ADC2 y Wi-Fi en CircuitPython](https://docs.circuitpython.org/en/stable/shared-bindings/analogio/index.html),
[pines ESP32](https://documentation.espressif.com/esp32-wroom-32_datasheet_en.html).

## Subir y leer sin movimiento

1. Mantener AO del sensor de color en IO33. No modificar credenciales ni signos
   de motores durante una actualización de sensores.
2. Usar **Subir paquete completo** en la interfaz de carga. Incluye
   `hardware_sensores.py`, `sensores_rover.py`, `config_sensores.json`, receptor,
   controlador y protocolo. El botón de Wi-Fi por sí solo no actualiza el paquete.
3. Reiniciar placa, conectar Wi-Fi y cerrar el control manual. Desde la raíz:

```powershell
.\vision-system\.venv\Scripts\python.exe -X utf8 -B .\base-robots\robots\pc\leer_sensores.py --robot-ip <IP_DEL_ROVER>
```

El monitor confirma STOP y solo consulta `SENSORS`; nunca envía movimiento.
Debe mostrar distancia, cuatro IR y `color_raw` (ambiente/R/G/B). Revisar
`errors`: si faltan pines/módulos/eco, se informa, no se inventa una lectura.
El código usa `pulseio`, `digitalio`, `analogio`, `neopixel`; deben estar
disponibles en la versión de CircuitPython de la placa. El eco se atiende
cooperativamente con timeout de 60 ms e intervalo de 80 ms; no hay espera larga
bloqueando STOP. El pulso TRIG usa `microcontroller.delay_us()`.

## Color: calibrar cada cubo

El muestreo espera 300 ms tras cambiar cada iluminación y toma cinco lecturas
separadas al menos 10 ms. El firmware reúne siete barridos completos, conserva
la firma RGB de cada uno y elige como firma representativa el barrido más cercano
al conjunto. La detección clasifica cada barrido completo y exige dos votos del
mismo color. Así no mezcla canales tomados en condiciones distintas ni permite
que un único pico decida el resultado. El NeoPixel usa `show()` explícito. Todo
el proceso es cooperativo: no bloquea STOP ni el watchdog mientras espera. Un
resultado consolidado tarda varios segundos y se invalida al mover el rover.

La configuración local usa `color.polarity=1`: en la prueba manual de AO IO33,
el usuario midió 2819–3971 tapado y 37613 iluminado. La lectura aumenta con
la luz; esto confirma respuesta de AO, no reconocimiento de colores todavía.
Subir esta configuración a la placa antes de calibrar. Este resultado aplica
al sensor probado: verificar la polaridad por separado en el otro rover.
Si se cambia la polaridad de un sensor ya calibrado, borrar sus perfiles y
calibrar nuevamente los tres colores; no reutilizar perfiles de otro montaje.

Motores parados, presentar el cubo con una cara paralela a aproximadamente 1 cm,
la distancia validada en banco. Calibrar cada color bajo cada condición de luz.
Si se omite `--segundos`, una calibración dura 100 segundos. Ejemplo:

```powershell
.\vision-system\.venv\Scripts\python.exe -X utf8 -B .\base-robots\robots\pc\leer_sensores.py --robot-ip <IP_DEL_ROVER> --calibrar-color red --escenario artificial
```

Repetir con `green` y `blue`, y luego con escenarios como `tenue` o `natural`.
Cada perfil requiere al menos seis firmas válidas. El calibrador identifica hasta
cuatro grupos densos dentro del mismo escenario y descarta como máximo 30 % de
lecturas atípicas. Se guardan varios perfiles por color y escenario. Si los
perfiles de colores distintos quedan demasiado cerca, el archivo no se sobrescribe.
Para estos tres cubos, una firma de calibración solo se acepta cuando el canal
del color presentado supera claramente al segundo canal. Las respuestas mixtas
que comparten verde y azul se rechazan porque no permiten distinguir los cubos.
Tras completar los escenarios, volver a subir `config_sensores.json` y reiniciar
la placa. Verificar los tres colores y que fondo/sin cubo resulte desconocido.
No basta con elegir el canal mayor: el material puede reflejar más otro canal.

Si el sensor mira al SUELO, no puede confirmar un cubo frente a las palas.
Hace falta confirmar su montaje antes de usar la comprobación de empuje.

## Qué controla cada sensor

- **Ultrasonido (freno DESACTIVADO con `ultrasonic.blocks_motion=false`):** el
  HC-SR04 no mide por debajo de ~20 mm y, empujando, el cubo queda más cerca;
  el freno bloqueaba el empuje. Con `false` solo informa `distance_mm` (usado
  para acercarse al cubo antes de medir color) y el rover NO frena ante
  obstáculos: la protección queda en visión y en el color antes de cada empuje.
  Con `true` (comportamiento original): la placa rechaza o detiene avance con distancia <= `stop_mm`
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
para mover. Todo sigue sujeto a verificar rutas, cámara, STOP, watchdog y
polaridad de motores antes de una misión. Para bloquear todos los movimientos
durante una prueba de banco, usar `diagnostic_only=true`; no hay otra bandera
de habilitación en el software.
