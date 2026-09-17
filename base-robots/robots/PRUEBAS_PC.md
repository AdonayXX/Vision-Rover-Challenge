# Pruebas de visión sin robots ni cámara

Estado más reciente: [coordinación de tareas simulada](COORDINACION.md). La suite completa actual tiene **93 pruebas**; los conteos siguientes corresponden a etapas previas.

Último avance: [comparación de reparto inicial](ASIGNACION.md). La suite completa ya tiene **77 pruebas**; los conteos inferiores describen etapas anteriores.

Avances posteriores: [navegación básica hacia un punto](NAVEGACION.md) y [planificación de rutas estáticas](RUTAS.md). La suite completa ahora suma **67 pruebas**, incluidas las 40 de esta etapa, 12 de navegación y 15 de rutas.

## Ejecutar la demostración

Desde la raíz del repositorio, en PowerShell:

```powershell
python -B base-robots/robots/pc/demo_vision.py
```

Sólo requiere el Python de la computadora y su biblioteca estándar. No utiliza OpenCV, webcam, Wi-Fi del robot ni motores.

La demostración arranca el publicador simulado **original del repositorio** en la dirección local `127.0.0.1` y un puerto temporal. Usa una copia temporal de su configuración para acortar la preparación a un segundo; conserva los archivos oficiales. Al terminar cierra los procesos y elimina los archivos temporales.

Debe imprimir `OK` en estas etapas:

1. Conexión y reconocimiento de IDLE: datos sin habilitar para navegación.
2. Identificación de rovers 10 y 11, tres cubos y destinos por color.
3. READY: continuar esperando.
4. RUNNING: datos frescos habilitados.
5. FINISHED: volver a exigir parada.
6. Apagado del simulador: detectar desconexión.
7. Reinicio: reconectar, aceptar la nueva secuencia y esperar en IDLE.
8. Nueva ronda: volver a habilitar datos frescos en RUNNING.

Al final muestra un resumen JSON con `resultado: OK`, mensajes aceptados, rechazados y cantidad de conexiones. Un fallo produce un error, incluye diagnóstico del simulador y termina con código distinto de cero. El puerto temporal se reserva antes de arrancar el publicador; si otro proceso lo ocupa en ese intervalo, la prueba falla indicando el problema y puede repetirse.

**Esto prueba recepción y evaluación de datos. No prueba navegación ni que los robots transporten cubos.** Los movimientos del simulador son su demostración preexistente, no decisiones de nuestro cliente.

## Ejecutar todas las pruebas

Desde la raíz del repositorio:

```powershell
python -B -m unittest discover -s base-robots/robots/tests -v
```

Resultado comprobado en esta entrega: **40 pruebas pasan**. Son las 24 de control anteriores, 15 de telemetría y una integración por TCP local con el publicador original.

Las pruebas de telemetría cubren IDs en distinto orden, cubos ausentes o viejos, compañero ausente, fases, datos inválidos, versiones desconocidas, NaN, identidades duplicadas, secuencias repetidas, captura vieja aunque llegue un mensaje nuevo, relojes desfasados, fragmentación de líneas y tamaño máximo de buffer. La integración levanta, apaga y reinicia el proceso real del simulador.

## Monitor manual, para explorar

En una primera terminal, desde la raíz del repositorio:

```powershell
cd base-robots/vision-system
python -B -m contrato.mock_publisher --host 127.0.0.1
```

En una segunda terminal, desde la raíz del repositorio:

```powershell
python -B base-robots/robots/pc/cliente_vision.py --robot-id 10 --peer-id 11 --target-color red
```

En la terminal del simulador escribir `ready` y Enter. Pasará por READY a RUNNING al agotarse la preparación configurada. `stop` termina la ronda y `quit` cierra el servidor. Se puede volver a arrancar el simulador: el monitor reintentará conectarse solo. Ctrl+C cierra el monitor.

Para observar desde el otro robot, intercambiar IDs: `--robot-id 11 --peer-id 10`. Se pueden abrir ambos monitores a la vez. `--seconds 15` limita la duración del monitor; `--max-age-ms 500` configura la edad máxima y `--host` acepta la IPv4 de la computadora que publique la visión. La dirección `127.0.0.1` corresponde únicamente a esta computadora.

La pantalla muestra `ESPERAR: motivo` o `DATOS HABILITADOS`, fase, secuencia y posiciones. Si la conexión se corta, conserva la última lectura para diagnóstico, siempre acompañada por ESPERAR. Las coordenadas son celdas, no milímetros; su escala está en `grid.cell_mm`.

## Reglas del cliente

- Consume JSON crudo v2 y no importa `schema.py` ni el motor de visión.
- Busca los rovers por ID y cubos/destinos por color; no por posición en las listas.
- Sólo habilita datos en RUNNING, con ambos rovers presentes y frescos. Si se elige `--target-color`, también exige ese cubo fresco.
- Estima la edad de cada entidad sumando `age_ms`, antigüedad de captura y tiempo transcurrido local. La edad máxima por defecto es 500 ms. Un reloj monótono impide rejuvenecer una captura al atrasar el reloj de pared.
- Exige relojes Unix sincronizados para comparar `ts_ms`. En esta demostración cliente y servidor usan el reloj de la misma PC. Un timestamp más de 100 ms en el futuro se rechaza.
- No permite que PING, TCP conectado, secuencias duplicadas o capturas viejas aparenten datos nuevos. Un mensaje inválido conserva el último bueno para diagnóstico, pero bloquea la habilitación hasta recibir uno nuevo válido.
- Reinicia la referencia de secuencia al reconectar, pero sigue exigiendo datos frescos y una nueva lectura válida. Nunca envía información a la visión.
- Conexión, reconexión y lecturas se procesan por ciclos, usando [socket](https://docs.python.org/3/library/socket.html) y [select](https://docs.python.org/3/library/select.html) de Python. El monitor limita memoria y cantidad de lecturas por ciclo. Reintenta cada 0.5 s y abandona la conexión si pasa un segundo sin mensajes válidos.

`datos habilitados` significa que se pueden evaluar esas observaciones. **No significa que haya una ruta libre ni autoriza por sí solo un movimiento.** La evaluación de bordes sólo revisa los centros; falta la huella física del robot, la evasión y la planificación. Las edades de cubos distintos del objetivo y de obstáculos deberán usarse al construir el planificador.

## Archivos nuevos y próximo paso

- [telemetria.py](codigos/telemetria.py): formato, identidades, fases y antigüedad.
- [cliente_vision.py](pc/cliente_vision.py): conexión y monitor para computadora.
- [demo_vision.py](pc/demo_vision.py): demostración automática.
- [test_telemetria.py](tests/test_telemetria.py): pruebas de datos e integración.

Todavía falta adaptar el transporte a `socketpool` en CircuitPython, sincronizar el reloj del rover, verificar memoria disponible y conectar el permiso de datos al programa de motores. El monitor no es firmware para cargar en la IdeaBoard.

Ya se agregaron los cálculos de ángulo y distancia, y decisiones básicas hacia un punto. Se pueden probar con [demo_navegacion.py](pc/demo_navegacion.py); el alcance y límites están en [NAVEGACION.md](NAVEGACION.md). La precisión física sigue pendiente.
