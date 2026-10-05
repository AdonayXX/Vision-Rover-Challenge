# Vision Rover Challenge: estado del proyecto

**Fecha:** 4 de octubre de 2026 · **Rama:** `desarrollo` · **Último commit:** `2fb9928`, con cambios sin commit (ver sección 9).

Documento para retomar el trabajo en un chat nuevo sin perder contexto. Léelo completo antes de tocar nada.

---

## 0. Resumen en pocas líneas

- Hay dos rovers (IDs **10** y **11**, IdeaBoard ESP32 con CircuitPython 9.2.4). Tienen que llevar 3 cubos (rojo, verde y azul) a su zona, **de forma autónoma**. Todo lo decide el rover a partir de la telemetría de la visión oficial (TCP, puerto 2026).
- El software está completo: ronda autónoma, reparto de cubos, coordinación por radio ESP-NOW, planificador A\*, misión de empuje, recuperación de fallos, grabador de la cancha y tabla de resultados. **Pasan las 322 pruebas.**
- **Resultados en la cancha real:** 7 de 17 rondas grabadas se completaron, con tiempos de 18 a 88 s. **La mayoría de las fallas fueron de infraestructura**, no de estrategia:
  - el NeoPixel del rover 10, que la cámara veía como un cubo;
  - bajo voltaje (BROWNOUT) en el rover 11;
  - el Wi-Fi de la U, con varias antenas y canales distintos;
  - un error de pila (`pystack`) que ya está corregido.
- **Situación al cierre:**
  - El NeoPixel del rover 10 se desconectó físicamente.
  - Se cambió al **hotspot del celular**.
  - Los rovers no arrancaban (`fase=None`) porque `vision_host` apuntaba a la IP vieja. Ya se corrigió en el `config_robot.json` local, **pero falta subirlo a los dos rovers**.

---

## 1. El reto: reglas que importan

Archivos de reglas: `reglamento.md`, `el_reto.md`, `robot.md`, `torneo.md` (en la raíz) y `docs/README.md` (generador oficial de canchas).

**Fases:**
- La visión pasa por `IDLE` → `READY` (60 s de preparación) → `RUNNING` → `FINISHED`.
- **El cronómetro arranca en `RUNNING`.** Lo confirmó el organizador; por eso `fase_inicio="RUNNING"`.
- La ronda se cierra sola cuando los 3 cubos llevan 1 s dentro de su zona. Al cerrar, la visión escribe un acta en `vision-system/vision/actas/`.

**Reglas clave:**
- Después de READY, **ninguna PC puede mandar comandos** (11.2.7). `ver_ronda` se usa solo en pruebas.
- **Cada rover debe llevar al menos 1 cubo** (12.2.13).
- No se pueden mover los cubos a mano (11.2.9).
- **ESP-NOW está permitido** (robot.md; 4.2.6, 7.2–7.6).

**Confirmado por el organizador:**
- El cronómetro arranca en RUNNING.
- Los rovers pueden salirse un poco de las líneas azules.
- En la competencia la red Wi-Fi tiene **un solo router**, y cada tablero tiene su propia IP de visión.

**Coordenadas de la cancha (visión):**
- 43 × 43 celdas de 20 mm. `col` crece hacia la derecha y `row` hacia abajo.
- Salida a la izquierda (3.75, 21.5).
- Zonas (centro): **verde arriba** (21.5, 3.75), **rojo a la derecha** (39.25, 21.5), **azul abajo** (21.5, 39.25).
- Cada zona mide 200 × 150 mm. El cubo mide 60 mm.
- Desde el protocolo v3, cada cubo trae `in_depot`, que es el veredicto del árbitro.

**Generador oficial de canchas** (`docs/index.html`, también publicado en https://universidad-cenfotec.github.io/Vision-Rover-Challenge/):
- Tiene una dificultad D de 0 a 1.
- Los cubos quedan separados al menos 2 casillas entre sí y pueden quedar junto a los bordes.
- **Conversión a nuestra cancha:** si el generador muestra un cubo en (x, y), su centro en la visión es **col = y − 2, fila = x − 2**.

**Entregables pendientes:** código fuente, documentación técnica y registro de costos.

---

## 2. Hardware

- **Placa:** IdeaBoard ESP32 con CircuitPython **9.2.4**. Motores `motor_1` y `motor_2`.
- **Medidas del rover:** 9 cm de largo (de las paletas a la cola) y 8 cm de rueda a rueda. Las paletas son del mismo ancho que las ruedas.
- **Modelo del rover en el código:**
  - radio de giro de 85 mm (para girar y para el otro rover);
  - paletas a 80 mm delante del centro de giro y cola a 20 mm detrás;
  - medio ancho de 45 mm;
  - contacto con el cubo a 110 mm (del centro del rover al centro del cubo).
- **Sensores:**
  - ultrasonido HC-SR04 al frente;
  - IR analógicos;
  - sensor de color analógico en IO33, con NeoPixel en IO32. En `config_sensores.json` está `"barrido": false`. **En el rover 10 el NeoPixel se desconectó físicamente el 4-oct**, porque la cámara lo veía como un cubo azul o verde.
  - Sin IMU (`use_imu: false`). Agregar sensores o hacer cambios físicos está restringido por las reglas.
- **Calibración propia de cada rover:** `codigos/rover_10.json` y `rover_11.json` (signos, ganancias y `ramp_seconds`). El rover 11 tiene ahora **`ramp_seconds: 0.25`** contra 0.05 antes. Ese cambio no está en el commit.
- **Baterías:** el rover 11 se reinició por bajo voltaje (**BROWNOUT**) unas **7 veces** entre el 3 y el 4 de octubre, siempre al arrancar o al girar. El rover 10 lo hizo una vez. Bajo carga, el voltaje cae a 4.6 V. **Pendiente: medir las baterías y comparar entre rovers.**

---

## 3. Arquitectura del software (`base-robots/robots/`)

### Placa (`codigos/`)

Se sube compilado a `.mpy`. `code.py`, `boot.py` y `safemode.py` quedan como `.py`.

| Archivo | Qué hace |
|---|---|
| `code.py` → `wifi_command_receiver.py` | Bucle principal: Wi-Fi, servidor de comandos (puerto 5000), cliente de la visión, `ronda.tick()` y `misiones.tick()`, watchdog, `registro_fallos`, reconexión del Wi-Fi, ESP-NOW y reinicio entre rondas |
| `cliente_vision_rover.py` | Cliente TCP de la visión. Se queda solo con el mensaje más nuevo y estima el desfase de reloj. Cierra la conexión tras 3 s sin datos |
| `telemetria.py` | Valida los mensajes v2 y v3 (`in_depot`) |
| `ronda.py` | La ronda autónoma: espera RUNNING, reparte los cubos, decide el siguiente cubo, coordina por radio, se estaciona, cede el paso, reintenta fallidos, ayuda al otro y pide reinicio entre rondas |
| `enlace.py` | ESP-NOW por difusión en el canal del router, con mensajes JSON etiquetados `VRC-AD1`. Latido de 5 Hz con `e` (estado), `a` (cubo actual), `m` (sus cubos), `h` (entregados por él) y `r` (robados). Se reabre solo ante `ValueError: Invalid buffer` |
| `llevar_cubo.py` | La misión de llevar un cubo. Estados: PLANIFICAR → APROXIMAR → ALINEAR → VERIFICAR → EMPUJAR → (RETROCEDER, RETIRAR, SALIR) → ENTREGADO o ABORTADO. Incluye: reubicación del cubo (`submeta`), entrada de costado, espera o cesión al compañero, detección de atasco, márgenes por borde y salida en abanico cuando queda pegado |
| `autonomia.py` | `IrAPunto`, `Misiones` (el administrador de misiones) y `obstaculo_en_camino`, la red de seguridad que frena al rover |
| `rutas.py` | `RoutePlanner`: A\* con búferes reservados de antemano, márgenes por lado (`edges`) y la regla de escape (alejarse siempre se permite) |
| `modelo_rover.py` | Modelo de movimiento, `Predictor` y desfase del marcador |
| `control_movimiento.py` | Control de motores con rampa (arranque suave) |
| `sensores_rover.py`, `hardware_sensores.py`, `config_sensores.json` | Sensores. El barrido del LED está apagado y el LED se apaga al iniciar |
| `registro_fallos.py` | Guarda los fallos en la NVM: sobreviven a reinicios y se ven en `ver_ronda` |
| `wifi_config.py` | Credenciales y `elegir_ap()`, que elige la antena (ver sección 5) |
| `config_robot.json` | **Secreto, en `.gitignore`.** Wi-Fi, `vision_host`, etc. Nunca mostrar ni commitear la contraseña. La plantilla es `config_robot.example.json` |
| `rover_10.json`, `rover_11.json` | La herramienta de subida los copia como `rover.json` |

**Parámetros clave actuales:**
- **`LlevarCubo`:**
  - `aproximacion_mm=160`, `contacto_mm=110`, `radio_mm=85`, `holgura_mm=10`, `holgura_ruta_mm=25`;
  - `borde_mm=25`, `borde_arriba_mm=60`;
  - `espera_compa_ms=3000`, `max_cesiones=10`, `ceder_paso=True`;
  - `frente_mm=80`, `cola_mm=20`, `medio_ancho_mm=45`;
  - `atasco_ms=2000`, `max_replanes=10`.
- **`Ronda`:**
  - `intentos_por_cubo=2`, `sin_dueno_ms=30000`, `reintento_ms=15000`;
  - `robar=False`, `apartarse_ms=8000`.
- **Opciones de `config_robot.json`:**
  - `vision_host`, `vision_port`;
  - `wifi_elegir_antena` (true), `wifi_canal` (null);
  - `borde_arriba_mm` (60), `reiniciar_entre_rondas` (true);
  - `espnow` (true), `robar` (false), `fase_inicio`, `estrategia`.

### PC (`pc/`)

| Archivo | Qué hace |
|---|---|
| `ver_ronda.py` | Monitor de un rover, solo para pruebas. Ver cómo leerlo en la sección 4 |
| `grabar_cancha.py` | Graba la cancha a 5 Hz (solo lee la visión) y avisa si un rover está cerca del borde o se pierde. **Al terminar cada ronda agrega una fila a `pc/grabaciones/tabla.csv`**: completa, tiempo, cubos dentro, rovers perdidos, cubos fuera y cubos movidos a mano. **Las grabaciones están en `.gitignore` y solo existen en esta PC** |
| `simulacion/bateria_oficial.py` | Corre canchas del generador oficial en el simulador de dos rovers: `python -B pc/simulacion/bateria_oficial.py . <D> <n>` (desde `base-robots/robots`) |
| `simulacion/resumen_grab.py` | Resume una grabación: `python resumen_grab.py <archivo.jsonl> <paso_s> <hasta_s>` |
| `simulacion/fantasma.py` | Busca cubos que "saltan" a la punta de un rover (detectó el NeoPixel) |
| `simulacion/peso_pila.py` | Mide el peso de la pila de Python en la planificación |

### Pruebas (`tests/`)

- **322 pruebas.** Se corren con: `..\..\vision-system\.venv\Scripts\python.exe -B -m unittest discover -s tests`, desde `base-robots/robots`.
- **Simulador:** `test_autonomia.Simulador` incluye la latencia de la visión, el retraso de los motores, la inercia, el empuje de cubos y los cubos tapados. `test_enlace.duo()` y `correr_duo()` corren dos rovers con radio falsa.
- **Lo que la PC NO simula:** la pila de Python de la placa (~1.5 KB), la RAM, el Wi-Fi real, los choques de costado y el voltaje de las baterías.
- **`test_planning_fits_in_the_board_python_stack`** exige un peso de pila ≤ 173. Atrapa el error `pystack exhausted`.

---

## 4. Cómo correr todo

**1. Visión** (nunca modificar `vision-system/`):
```
cd vision-system
.\.venv\Scripts\python.exe -m vision.sistema --ventana --ventana-hz 5 --camara logitech_c270
```
- Exposición -6.5 y cámara índice 1.
- Comandos: `ready`, `stop`, `abort`, `quit`. De READY pasa sola a RUNNING a los 60 s.
- Deben aparecer `[cliente] conectado <ip>` por cada rover, y `clientes=` en `[estado]`.

**2. Subir código a los rovers:** `subir_esp32_gui.bat` (o `tools/subir_esp32_gui.py`).
- Usar "Subir paquete" con "Compilar a .mpy" marcado.
- Usa `tools/mpy-cross/mpy-cross-9.2.4.exe` (en `.gitignore`; lo descarga de Adafruit).
- Borra los `.py` viejos de la placa.
- Copia `rover_<id>.json` como `rover.json`.

**3. Monitor:**
```
.\vision-system\.venv\Scripts\python.exe -X utf8 -B .\base-robots\robots\pc\ver_ronda.py --robot-ip <IP> --robot-id <10|11>
```
- La línea `placa:` muestra el tiempo encendida, el motivo del último reinicio y los `fallos` guardados en la NVM: BROWNOUT, wifi, memoria, etc.
- La línea `wifi:` muestra el canal elegido y las antenas vistas como `[canal, dBm]`.
- Cada línea de estado incluye:
  - `fase`;
  - `ronda`;
  - `cubos` (los suyos), `hechos` y `actual`;
  - `mision` y su motivo;
  - el detalle de la misión: `submeta`, `retroceso`, `estorbo`, `espera`, `entrada`;
  - `fallos` y `ram`;
  - `radio: tx rx hace canal plan errores reaperturas ultimo_error`.

**4. Grabador** (en la PC de la visión, abrirlo **antes** de dar `ready`):
```
.\vision-system\.venv\Scripts\python.exe -X utf8 -B .\base-robots\robots\pc\grabar_cancha.py --escenario oficial05
```

**5. Revisar que compila para la placa:**
```
tools\mpy-cross\mpy-cross-9.2.4.exe base-robots\robots\codigos\<archivo>.py -o %TEMP%\x.mpy
```

---

## 5. Redes

**Red de la U** (varias antenas en los canales 1, 6 y 11):
- PC de la visión en `10.50.42.8`, rover 10 en `10.50.42.120`, rover 11 en `10.50.42.151`.
- **Problemas:**
  - cada rover se conectaba a una antena distinta, así que ESP-NOW no cruzaba (solo funciona en el mismo canal);
  - el Wi-Fi tenía cortes de varios segundos (`timed out`, `vision_vieja`, `rover_no_visible`).
- `elegir_ap()` elige entre las antenas con señal ≥ -70 dBm la del canal más bajo y, en él, la más fuerte. Si ninguna llega a -70, elige la más fuerte. **Esa última regla es inestable** cuando las señales son parecidas (en oficial02, -74 contra -76 dBm separó a los rovers). Se puede forzar con `wifi_canal`.

**Hotspot del celular "HONOR X8"** (el que se usa ahora; tiene que ser de 2.4 GHz):
- PC en **`10.91.8.217`**, rover 10 en **`10.91.8.70`**, rover 11 en **`10.91.8.149`**.
- Los dos rovers quedan en el canal 11 con -50 dBm y la radio cruza bien.
- En Windows la red quedó como "Pública". El firewall deja pasar a Python 3.12 en redes públicas.
- **`config_robot.json` local ya tiene `vision_host: 10.91.8.217`, pero FALTA SUBIRLO A LOS DOS ROVERS.** Sin eso salen con `fase=None` y nunca arrancan.
- Al volver a la U hay que poner otra vez `vision_host` en `10.50.42.8`.

**Competencia:** un solo router. `vision_host` será la IP del tablero que toque.

---

## 6. Qué funciona (verificado en la cancha)

- **Sin reinicios por memoria:**
  - los `.mpy` se compilan en la PC;
  - la misión y el planificador se cargan antes de RUNNING;
  - los búferes del A\* se reservan una sola vez;
  - los `MemoryError` se capturan.
- Un solo rover hizo los 3 cubos en el escenario difícil en unos 65 s.
- **Radio:**
  - los dos se oyen a 5 Hz;
  - el 11 adopta el reparto del 10 (`plan=lider`);
  - "Invalid buffer" se recupera solo.
- **Recuperación:**
  - reconecta el Wi-Fi si se cae en silencio;
  - detecta atascos y retrocede;
  - sale en abanico cuando queda pegado a algo;
  - si un rover se reinicia en plena ronda, vuelve a jugar solo;
  - se reinicia entre rondas (resuelve el problema del "segundo ready").
- No hubo más pérdidas del rover en el borde de arriba desde que existe `borde_arriba_mm=60`.
- Desde el arreglo, ya no hubo errores `pystack exhausted`.

---

## 7. Resultados

### En la cancha real (`pc/grabaciones/tabla.csv` y logs)

| Fecha | Escenario | Resultado | Causa principal |
|---|---|---|---|
| 3-oct 16:10 | fácil | **completa, 0:36** | n/a |
| 3-oct 16:50 | difícil | incompleta | El rover 10 reubicó un cubo por culpa del 11, pasó por el borde de arriba y la cámara lo perdió |
| 3-oct 17:18 | n/a | 1:22, no válida | Se sacó el verde de la cancha y se devolvió a mano |
| 3-oct 18:38 | fácil | **completa, 21.8 s** | n/a |
| 3-oct 18:41 | n/a | 0 cubos | Problema del segundo `ready` (ya resuelto con el reinicio entre rondas) |
| 3-oct 18:45 | difícil | **completa, 41.1 s** | El 10 se reinició por BROWNOUT, la radio dio "Invalid buffer" y el 11 quedó atrapado (todo corregido) |
| 3-oct 19:03 | n/a | **completa, 68.3 s** | Rovers en canales distintos, el 10 atascado girando y el 11 reubicó el azul |
| 3-oct 19:27 | difícil | incompleta | El 11 se perdió en el borde de arriba (llevó a `borde_arriba_mm=60`) |
| 3-oct 19:53 | difícil | **completa, 51.7 s** | n/a |
| 3-oct 19:59 | difícil | 0 cubos | Rondas seguidas sin apagar: el 10 sin red y con poca RAM (llevó al reinicio entre rondas) |
| 3-oct 20:06 | difícil | 0 cubos | Cubos en fila bloqueados 3 min (llevó a usar la forma real del rover) |
| 3-oct 20:13 | fácil | **completa, 51.1 s** | n/a |
| 3-oct 20:20 | fácil | incompleta | Los dos quietos 34 s al arrancar (rondas seguidas) |
| 3-oct 20:22 | fácil | **completa, 18.0 s** | n/a |
| 3-oct 20:29 | borde | 0 cubos | Verde en una esquina, inalcanzable para empujar; el 11 con BROWNOUT |
| 3-oct 21:24 y 21:30 | oficial02 | 0 cubos | `pystack exhausted`: el rover 10 nunca se movió (error de código, ya corregido) |
| 3-oct 21:56 | oficial02 | **completa, 88.5 s** | El 11 tuvo BROWNOUT a mitad de ronda; terminaron igual |
| 4-oct 14:35 | oficial05 | 0 cubos | Cubo fantasma (NeoPixel del 10), verde del 11 tapado por el rojo y cortes de Wi-Fi |
| 4-oct 14:45 | oficial08 | 0 cubos (no está en la tabla) | El 10 "empujó" su propio LED azul hasta el borde de abajo |
| 4-oct 15:01 | oficial08 | 0 cubos | Fantasma; el 11 quieto 2 min (causa desconocida, el log se cortó) y el 10 esperándolo |
| 4-oct (hotspot) | n/a | no arrancan | `vision_host` con la IP vieja (corregido en local, falta subirlo) |

### En el simulador (canchas del generador oficial, 12 por dificultad, dos rovers)

| Dificultad | Antes de usar la forma real del rover | Ahora |
|---|---|---|
| 0.2 | 36/36 cubos, 12/12 rondas | 34/36 cubos, 11/12 rondas (36 s) |
| 0.5 | 8/36 cubos, 1/12 rondas | **33/36 cubos, 11/12 rondas** (56 s) |
| 0.8 | 25/36 cubos, 5/12 rondas | 30/36 cubos, 7/12 rondas (82 s) |

Otras baterías:
- un rover solo: 108/120 cubos;
- dos rovers en canchas al azar: 76/90;
- cubos junto a la orilla: **46/120, el punto débil**.

---

## 8. Problemas abiertos (por prioridad)

**Infraestructura** (primero, sin esto las pruebas no dicen nada):
1. **Subir `config_robot.json`** con `vision_host 10.91.8.217` a los dos rovers, y confirmar que la visión muestra `[cliente] conectado` dos veces y `ver_ronda` muestra `fase=IDLE`.
2. **Subir el código sin commit** (sección 9) a los dos rovers. Hasta ahora no hay forma de saber qué versión tiene cada placa.
3. **BROWNOUT del rover 11:** medir las baterías y confirmar que tiene `rover_11.json` con la rampa de 0.25 s.
4. **Verificar que el fantasma desapareció:** poner solo el rover 10 en la cancha y mirar la ventana de la visión, o correr `pc/simulacion/fantasma.py` sobre las grabaciones nuevas.

**Estrategia** (arreglar solo lo que se repita en la tabla):

5. **Rovers esperándose entre sí** (oficial08):
   - el 10, de ID menor, espera hasta 10 cesiones (unos 50 s o más);
   - el 11 "cede" el paso pero `_aparcar` puede no moverlo si no encuentra un lugar mucho mejor.
   - **Idea:** al ceder, alejarse de verdad del camino del otro.
6. **Cubo tapado por otro cubo que nadie lleva** (oficial05: el rojo pasaba a 6 cm de la línea de empuje del verde, y el rover necesita 7.5 cm).
   - **Idea:** mover primero el cubo que tapa.
7. **La reubicación deja cubos en los bordes** (en oficial08 el verde quedó en (15.3, 3.9), 6 celdas a la izquierda de su zona). Cubos en esquinas: no hay desde dónde empujarlos.
8. **El rover 10 se pasa al frenar** (llega a 130–140 mm del cubo en vez de 160), y al girar las paletas rozan el cubo (atasco).
   - **Idea:** retroceder antes de girar si quedó demasiado cerca.
9. **La regla de elegir antena es inestable** cuando todas las señales son débiles. Solo importa en redes con varias antenas.
10. **Por qué el 11 se quedó quieto en oficial08** (sin log): ¿Wi-Fi, visión o batería?

---

## 9. Cambios sin commit (desde `2fb9928`)

`git diff --stat`: 14 archivos, unas 495 líneas.

**Código de la placa:**
- **`llevar_cubo.py`:**
  - forma real del rover contra los cubos (`frente_mm`, `cola_mm`, `medio_ancho_mm`); contra el otro rover sigue valiendo el radio completo;
  - entrada de costado al punto de ataque (`_entradas`);
  - reglas para ceder el paso, esperar y soltar el cubo (`_sin_compa`, `_esperar_compa`, `ceder_paso`, `max_cesiones=10`);
  - margen del borde de arriba (`_bordes`, `borde_arriba_mm`);
  - salida en abanico (`_salir`);
  - **reorganización para la pila de la placa: el A\* solo se llama desde `_planificar`.**
- **`ronda.py`:**
  - `pedir_reinicio` entre rondas;
  - `apartarse_ms` y `apartandose` al ceder el paso;
  - reinicia `cesiones` en cada ronda.
- **`autonomia.py`:** `obstaculo_en_camino` con `ancho_mm`, permite alejarse de lo que ya está cerca, y raíz cuadrada en línea (por la pila).
- **`rutas.py`:** márgenes por lado (`edges`) y `free_segment` y `_search` con menos variables (por la pila).
- **`enlace.py`:** búfer de 1536 bytes, se reabre ante "Invalid buffer", y cuenta `ajenos`, `errores`, `ultimo_error` y `reaperturas`.
- **`wifi_command_receiver.py`:** elige antena con `wifi_canal`, guarda `ANTENA` en el informe, pasa `borde_arriba_mm` a la misión y reinicia entre rondas (`microcontroller.reset()`).
- **`wifi_config.py`:** `elegir_ap(..., canal=)`.
- **`rover_11.json`:** `ramp_seconds 0.25`.
- **`config_robot.example.json`:** `wifi_elegir_antena`, `wifi_canal` y `borde_arriba_mm`.

**PC:**
- **`pc/ver_ronda.py`:** muestra la antena y el detalle de la misión.
- **`pc/simulacion/` (nuevo):** las herramientas de simulación y análisis.

**Pruebas:**
- `test_llevar_cubo.py`: cubos en fila, pila de la placa, salida en abanico y espera al compañero.
- `test_enlace.py`: "Invalid buffer" y bloqueo mutuo en una cancha oficial.
- `test_ronda.py`: reinicio entre rondas.
- `test_wifi_config.py`: canal preferido.

**Recomendación:** commitear este estado como base antes de seguir. Lo hace el usuario.

---

## 10. Tres canchas oficiales de prueba (col, fila en la ventana de la visión)

| Escenario | Rojo | Azul | Verde |
|---|---|---|---|
| `oficial02` | (32, 25) | (27, 32) | (20, 9) |
| `oficial05` | (20, 25) | (26, 23) | (18, 20) |
| `oficial08` | (12, 22) | (26, 12) | (21, 31) |

**Rutina:**
1. Colocar los cubos y los rovers en la salida.
2. Abrir el grabador con `--escenario`.
3. Dar `ready` y no tocar nada durante la ronda.
4. Al final, revisar `tabla.csv` y, **solo de las rondas que fallen**, los `ver_ronda` de los dos rovers.

Los mensajes de más de unos 50 000 caracteres se cortan: hay que enviar los logs de a una ronda.

---

## 11. Cómo trabajar en este proyecto (reglas firmes)

- **`vision-system/` no se toca nunca.** Es el de la U, restaurado al commit `7110555`. Todos los ajustes van en el rover.
- **Commits:** los hace el usuario. **Nunca** poner `Co-Authored-By` ni menciones a Claude o IA.
- **`config_robot.json` es secreto:** no mostrar la contraseña ni commitearlo.
- **Hablar antes de cambios grandes**, ir paso a paso y explicar en español simple.
- **Límites de la placa:**
  - pila de Python de ~1.5 KB: evitar llamadas anidadas en la planificación y llamar al A\* solo desde `_planificar`;
  - RAM libre de ~55–70 KB;
  - `math.hypot` no está garantizado (usar `_norma` o `math.sqrt`);
  - no existe `ubinascii`;
  - todo tiene que compilar con mpy-cross 9.2.4.
- **Antes de dar algo por bueno:**
  - pruebas en verde;
  - prueba de la pila;
  - compilación con mpy-cross;
  - y, cuando aplique, la batería de canchas oficiales comparada contra la versión anterior.

  El simulador **no** reemplaza la cancha.
- **Analizar fallas con datos:**
  - las grabaciones (`pc/grabaciones/*.jsonl`, con `resumen_grab.py`);
  - los `ver_ronda`;
  - reproducir la posición exacta en el simulador antes de cambiar código.
- **En Windows, los heredocs de Bash rompen las barras invertidas:** escribir los scripts de edición en archivos.
- **Memoria persistente de Claude Code** (se carga sola en este proyecto): `C:\Users\David\.claude\projects\d--Proyectos-Vision-Rover-Challenge\memory\`. Incluye: sin atribución en commits, vision-system intocable, se puede salir de las líneas, cronómetro en RUNNING, red de competencia con un router y generador oficial.

---

## 12. Próximos pasos recomendados

1. Subir `config_robot.json` y el código actual a los dos rovers. Verificar:
   - en la visión, `[cliente] conectado` para los dos;
   - en `ver_ronda`, `fase=IDLE`, el mismo `canal=` en los dos y `rx` subiendo.
2. Commitear la base.
3. Revisar las baterías del rover 11.
4. Correr oficial02, oficial05 y oficial08 (1 vez cada una, después 3) con el grabador.
5. Con la tabla, arreglar **solo** la falla que más se repita. Los candidatos son los puntos 5 y 6 de la sección 8.
6. Preparar el cambio rápido de `vision_host` para el día de la competencia.
7. Entregables: documentación técnica y registro de costos.
