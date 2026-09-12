# Contrato de telemetría — Vision-Rover-Challenge

**Protocolo v2**

Este documento es el acuerdo entre el **sistema de visión** y **los equipos**.
La visión mira la cancha desde arriba y publica, varias veces por segundo, dónde
está cada cosa. Ustedes lo consumen.

Lo que está acá **no cambia por sorpresa**. Si algo tiene que cambiar, sube el
número de versión (`v`) y se les avisa. Pueden escribir código contra este
formato con confianza.

> ### 🔁 Qué cambió en la v2
>
> - Las **zonas de acopio** dejan de ser un punto en una esquina: ahora son
>   **rectángulos de 20 × 15 cm**, uno al **centro de cada uno de los tres lados**
>   que no son el de la salida. `depots[i]` es el **centro** del rectángulo.
> - La **salida** deja de estar en la esquina del marcador 0 y pasa al **centro
>   del lado que va del marcador 0 al 3** (el lado izquierdo). **El origen de
>   coordenadas no se movió**: sigue siendo el centro del marcador 0.
> - El mensaje suma dos campos raíz: **`depot_size`** (el tamaño de las zonas) y
>   **`cube_side`** (el lado del cubo), los dos en celdas.
> - Con eso se puede calcular **si un cubo está completamente dentro de su
>   zona**, que es la condición de entrega del reglamento. La regla, con código
>   para copiar, está en la [sección 3](#cuándo-un-cubo-está-en-su-zona).
>
> La nota de migración —qué se rompe y qué no— está en la
> [sección 9](#9-cambios-de-contrato).

> ### 🚀 ¿Nunca corriste esto? Empezá por la [sección 7](#7-herramientas-incluidas-y-cómo-correrlas)
>
> Ahí está la guía paso a paso para pasar de "tengo la carpeta" a "veo
> telemetría en pantalla", sin dar por sabido nada de línea de comandos.
> Las secciones 1 a 6 describen **el formato**; la 7 explica **cómo correrlo**.

---

## 1. Cómo se conectan

| | |
|---|---|
| **Transporte** | TCP |
| **Puerto** | `2026` |
| **Formato** | NDJSON — **un objeto JSON por línea**, terminada en `\n` |
| **Codificación** | UTF-8 (en la práctica, ASCII) |
| **Dirección** | Solo la visión escribe. Ustedes **nunca envían nada**. |

Se conectan, leen líneas y listo. No hay handshake, ni suscripción, ni comandos.

### El error clásico: TCP no respeta los límites de los mensajes

Un `recv()` puede devolverles **media línea**, o **dos líneas y media**. Si
parsean directo lo que llegó, les va a funcionar en la compu y les va a fallar
en la cancha.

**Hay que acumular en un buffer y cortar por `\n`:**

```python
buffer = b""
while True:
    trozo = conexion.recv(4096)
    if not trozo:
        break                      # la visión cerró la conexión
    buffer += trozo
    while b"\n" in buffer:
        linea, buffer = buffer.split(b"\n", 1)
        mensaje = json.loads(linea)
        # ... usar mensaje ...
```

Está implementado así en [`test_client.py`](test_client.py), listo para copiar.

### Si la conexión se cae

Reconecten. La visión acepta clientes en cualquier momento y les manda el estado
actual: **no hay que ponerse al día con nada**, porque no existe historial. El
primer mensaje que reciben ya es el presente.

### Conectarse desde el robot: la IP importa

En todos los ejemplos de este documento aparece `127.0.0.1`. Esa dirección
significa **"esta misma computadora"** y solo sirve para probar el simulador y
el cliente en una sola máquina.

**Un robot nunca se conecta a `127.0.0.1`.** El rover es otro aparato, en otro
lugar de la red: tiene que apuntar a la **IP de la computadora donde corre la
visión** (o el simulador).

**1. Averiguá la IP de la máquina de visión.** En esa computadora, ejecutá:

| Sistema | Comando |
|---|---|
| Windows (PowerShell) | `ipconfig` → mirá "Dirección IPv4" del adaptador de Wi-Fi |
| macOS | `ipconfig getifaddr en0` |
| Linux | `hostname -I` |

Te va a dar algo como `192.168.1.47`. **Esa** es la dirección que va en el
código del robot, junto con el puerto `2026`.

**2. Los dos tienen que estar en la misma red.** El robot y la computadora de
visión deben estar conectados al **mismo Wi-Fi**. Si el robot está en la red de
invitados y la computadora en otra, no se van a ver aunque la IP esté bien.

**3. Si no conecta, sospechá del firewall.** El cortafuegos de Windows suele
bloquear conexiones entrantes la primera vez. Hay que permitirle a Python
aceptar conexiones en redes privadas.

**4. Probá primero desde otra computadora**, antes de pelearte con el robot:

```bash
python3 test_client.py --host 192.168.1.47 --port 2026
```

Si eso funciona desde otra máquina de la red, el problema no es la visión: es el
código o la red del robot.

> **Qué viene después: el cliente de referencia del robot.** El cliente que
> vamos a entregar para el rover está pensado en **CircuitPython, sobre
> ESP32/IdeaBoard** (no Arduino). Todavía **no está incluido en esta carpeta**;
> se va a agregar más adelante.
>
> Mientras tanto, el ejemplo probado y funcionando es el de la sección 7: abrir
> un socket TCP contra `IP:2026`, acumular en un buffer, cortar por `\n` y
> parsear con `json`. Eso es todo lo que necesita el rover; lo único que cambia
> en la placa es la parte de conectarse al Wi-Fi.

---

## 2. El mensaje

Ejemplo real, formateado para leerlo (en el cable viaja **todo en una sola
línea**):

```json
{
  "v": 2,
  "seq": 4137,
  "ts_ms": 1785012345678,
  "phase": "RUNNING",
  "clock": { "elapsed_ms": 88000, "remaining_ms": 512000, "total_ms": 600000 },
  "grid": { "cols": 43, "rows": 43, "cell_mm": 20.0 },
  "rovers": [
    { "id": 10, "col": 18.402, "row": 6.705,  "theta": 84.20, "age_ms": 0 },
    { "id": 11, "col": 15.265, "row": 28.661, "theta": 40.22, "age_ms": 0 }
  ],
  "cubes": [
    { "color": "green", "col": 21.480, "row": 3.762, "age_ms": 0   },
    { "color": "blue",  "col": 15.000, "row": 29.000, "age_ms": 425 },
    { "color": "red",   "col": 33.071, "row": 25.983, "age_ms": 0   }
  ],
  "obstacles": [],
  "start":  { "col": 3.75, "row": 21.5 },
  "depots": [
    { "color": "green", "col": 21.5,  "row": 3.75  },
    { "color": "red",   "col": 39.25, "row": 21.5  },
    { "color": "blue",  "col": 21.5,  "row": 39.25 }
  ],
  "depot_size": { "length": 10.0, "depth": 7.5 },
  "cube_side": 3.0
}
```

> Mirá el cubo **azul**: `age_ms: 425`. El rover 11 está justo encima
> (`15.265, 28.661`) y lo tapa. El cubo **no desapareció** de la lista: sigue
> ahí, con su última posición conocida y la edad creciendo. Esto es lo normal,
> no un error. Ver la sección 6.
>
> Y mirá el **verde**: está en `(21.480, 3.762)` y su zona está centrada en
> `(21.5, 3.75)`. Ese cubo **ya está entregado**, y se comprueba con la cuenta de
> [más abajo](#cuándo-un-cubo-está-en-su-zona) — no alcanza con que las
> coordenadas se parezcan.

---

## 3. Campo por campo

### Nivel raíz

| Campo | Tipo | Significado |
|---|---|---|
| `v` | entero | Versión del protocolo. Hoy `2`. **Si ven un número que no conocen, descarten el mensaje**: el formato cambió. |
| `seq` | entero | Número de secuencia, sube de a uno por mensaje publicado. Sirve para detectar pérdidas. |
| `ts_ms` | entero | Instante de **captura del cuadro**, en milisegundos desde época (Unix). **No** es el instante de envío. |
| `phase` | texto | `IDLE`, `READY`, `RUNNING` o `FINISHED`. Ver sección 5. |
| `clock` | objeto | El cronómetro oficial de la ronda, **del mismo instante que `ts_ms`**. Ver sección 5. |
| `grid` | objeto | Dimensiones de la cancha. |
| `rovers` | lista | Robots detectados. **Dinámico.** |
| `cubes` | lista | Cubos detectados. **Dinámico.** |
| `obstacles` | lista | Obstáculos detectados. **Dinámico.** |
| `start` | objeto | Punto de salida de los robots. **Estático.** |
| `depots` | lista | Zonas de acopio: el **centro** de cada una. **Estático.** |
| `depot_size` | objeto | Tamaño de las zonas, en celdas. **Uno solo para las tres.** **Estático.** |
| `cube_side` | número | Lado del cubo, en celdas. **Estático.** |

### `clock`

| Campo | Tipo | Significado |
|---|---|---|
| `elapsed_ms` | entero | Cuánto lleva la fase que se está contando. |
| `remaining_ms` | entero | Cuánto le queda. |
| `total_ms` | entero | Cuánto dura. **En cero, no se está contando nada** (`IDLE`). |

Vale siempre `elapsed_ms + remaining_ms == total_ms`, y los tres son del **mismo
instante** que el `ts_ms` de ese mensaje. Con eso alcanza para saber en qué punto
de la ronda está la cancha **con un solo mensaje y sin memoria**: no hace falta
haber visto los anteriores ni llevar un reloj propio.

**No lleven su propio cronómetro.** Un reloj que arranca en el robot se desvía
del oficial, y uno que se conecta tarde no sabe en qué momento entró. El único
tiempo que vale es el que viene acá.

En `FINISHED`, `elapsed_ms` es **el tiempo que tomó la ronda**. Si terminó antes
de agotarse, `remaining_ms` dice cuánto sobró.

### `grid`

| Campo | Tipo | Significado |
|---|---|---|
| `cols` | entero | Ancho de la cancha, en celdas. |
| `rows` | entero | Alto de la cancha, en celdas. |
| `cell_mm` | float | Lado de una celda en milímetros. Vale `20.0`. |

**Lean `grid` del mensaje, no lo hardcodeen.** La cancha efectiva es el área
encerrada por los **centros** de los cuatro marcadores ArUco de esquina, y
depende de dónde se peguen el día del montaje.

> **Ojo: el tablero físico y la cancha del sistema son dos números distintos.**
> En la cancha actual, el tablero mide **50 × 50 cuadros** pero la cancha
> efectiva es de **43 × 43 celdas**, porque los marcadores van pegados hacia
> adentro del borde. Los 7 cuadros de diferencia son margen y **no se usan**:
> todo el juego ocurre dentro del área de 43 × 43.
>
> Por eso `grid` viene en cada mensaje y hay que leerlo de ahí. Si montan otra
> cancha, el número va a ser otro.

### `rovers[]`

| Campo | Tipo | Significado |
|---|---|---|
| `id` | entero | **ID del marcador ArUco** pegado al robot. Es su identidad. |
| `col` | float | Posición en celdas, eje horizontal. |
| `row` | float | Posición en celdas, eje vertical. |
| `theta` | float | Orientación en **grados**, `0` = derecha, sentido **antihorario**, rango `[0, 360]`. |
| `age_ms` | entero | Milisegundos desde la última vez que se lo vio de verdad. |

Los dos robots son **negros e idénticos**: lo único que los distingue es el
marcador. **Su rover es el del ID de su marcador.** Búsquenlo por `id`, nunca
por posición en la lista.

### `cubes[]`

| Campo | Tipo | Significado |
|---|---|---|
| `color` | texto | `green`, `blue` o `red`. **El color es la identidad.** |
| `col` | float | Posición en celdas. |
| `row` | float | Posición en celdas. |
| `age_ms` | entero | Milisegundos desde la última observación real. |

Cubos de **6 cm**. **No hay dos del mismo color**, por eso no llevan `id`: el
color alcanza para identificarlos. Puede haber 2 o 3 cubos en juego.

### `obstacles[]`

| Campo | Tipo | Significado |
|---|---|---|
| `col` | float | Posición en celdas. |
| `row` | float | Posición en celdas. |
| `age_ms` | entero | Milisegundos desde la última observación real. |

Bloques **amarillos de 10 cm**. No llevan `color` porque **el amarillo está
reservado**: un objeto amarillo **nunca** es un cubo. No llevan `id` porque son
intercambiables entre sí; lo único que importa es esquivarlos.

> ### ℹ️ En esta primera edición del reto, `obstacles` viene **vacío**
>
> No hay obstáculos en la cancha. **El campo sigue existiendo y sigue siendo una
> lista**: simplemente llega sin elementos.
>
> **Esto NO es un cambio de contrato.** El formato es idéntico y `v` sigue
> valiendo `2`. No hay que tocar nada: si iteran la lista —como manda la
> [regla 6.1](#61-iterar-nunca-indexar-por-posición-fija)— no encuentran nada y
> siguen de largo. El código que escriban hoy va a seguir funcionando si en una
> edición futura vuelven los obstáculos.
>
> El simulador también los emite vacíos, para que lo que prueban sea lo que van
> a encontrar en la cancha.

### `start`

| Campo | Tipo | Significado |
|---|---|---|
| `col` | float | Posición en celdas. |
| `row` | float | Posición en celdas. |

**Punto de salida de los robots**, compartido por los dos. Está al **centro del
lado que va del marcador 0 al 3** —el lado izquierdo mirando la cancha desde
arriba—, a 3,75 celdas del borde: la misma distancia a la que están los centros
de las tres zonas de acopio del suyo.

> **Ojo, que son dos cosas distintas.** Hasta la v1 la salida coincidía con el
> **origen (0,0)**, que es el centro del marcador ArUco de menor ID. En la v2 la
> salida se mudó al centro del lado, pero **el origen no se movió**: se sigue
> midiendo desde el marcador 0. Si su código usaba `start` como si fuera el
> origen, ahí hay un supuesto que dejó de valer.

### `depots[]`

| Campo | Tipo | Significado |
|---|---|---|
| `color` | texto | `green`, `blue` o `red`. |
| `col` | float | **Centro** de la zona, en celdas. |
| `row` | float | **Centro** de la zona, en celdas. |

Zonas de acopio, **una por color**, al **centro de cada uno de los tres lados**
que no son el de la salida. **Cada cubo va al depot de su color.** Se cruzan las
dos listas por `color`:

```python
depots_por_color = {d["color"]: d for d in msg["depots"]}
for cubo in msg["cubes"]:
    destino = depots_por_color[cubo["color"]]
```

**No asuman qué color va en qué lado.** Eso se define al montar la cancha y
puede cambiar. Léanlo del mensaje.

**`col` y `row` son el CENTRO del rectángulo**, no una esquina. El tamaño está
en `depot_size` y la orientación **no se declara**: se deduce, y cómo se deduce
está [más abajo](#cuándo-un-cubo-está-en-su-zona).

### `depot_size`

| Campo | Tipo | Significado |
|---|---|---|
| `length` | float | Lado **largo** de la zona, en celdas. Va **paralelo al borde** donde apoya. |
| `depth` | float | **Fondo**: cuánto entra la zona desde el borde hacia adentro, en celdas. |

Hoy vale `{ "length": 10.0, "depth": 7.5 }`, o sea **200 × 150 mm**.

> **Léanlo del mensaje, no de acá.** Este número ya cambió una vez: el fondo era
> de 100 mm y subió a 150 en sep-2026, después de ver en la cancha real que con
> 100 un cubo bien puesto podía quedar afuera por una rendija. **No subió la
> versión del protocolo**, porque la forma del mensaje no cambió: el tamaño es un
> dato, y el que lo lee del mensaje no se enteró de nada.

Es **uno solo para las tres zonas**, y por eso viaja una vez en la raíz del
mensaje y no repetido en cada `depot`: tres copias del mismo número son tres
oportunidades de que un día digan cosas distintas.

Se llama largo y fondo —y no ancho y alto— porque **la zona gira con su lado**:
la de arriba tiene sus 10 celdas sobre `col`, y la de la derecha, sobre `row`.
"Ancho" querría decir cosas distintas en cada una.

### `cube_side`

| Tipo | Significado |
|---|---|
| float | Lado del cubo, en celdas. Hoy `3.0`, o sea **60 mm**. |

Viaja en el mensaje por la misma razón que `grid`: **no lo asuman**. El veredicto
de "cubo completamente dentro de su zona" depende del lado del cubo tanto como
del tamaño de la zona, y un número copiado de este documento no se puede
verificar contra lo que la cancha está publicando.

### Cuándo un cubo está en su zona

El reglamento pide que el cubo quede **completamente dentro** del área de su zona
de acopio. Esta es la cuenta exacta con la que se decide, y es la misma que usa
el sistema de visión para mostrarlo en pantalla.

**Primero: sobre qué lado apoya la zona.** No viene en el mensaje, se deduce. La
zona apoya su lado largo sobre el **borde de la cancha más cercano a su centro**.
Con los números de esta edición el centro está a **3,75 celdas** de su borde y a
**21,5** de los perpendiculares, así que no hay ambigüedad posible.

**Después: el margen de media diagonal.** El centro del cubo tiene que estar a
`cube_side * √2 / 2` de cada borde del rectángulo. Ese número —**2,1213 celdas =
42,43 mm**— es el radio del círculo que contiene al cubo entero, así que el
criterio **vale para cualquier rotación** del cubo, y ustedes lo pueden calcular
**con el puro centro**: la rotación del cubo no viaja en el mensaje, y no hace
falta.

Lo que queda es la **ventana de aceptación**: dónde puede caer el centro del cubo.

| | Zona | Ventana donde cae el centro |
|---|---|---|
| A lo **largo** | 200 mm | **115,15 mm** (±57,6 mm desde el centro) |
| A lo **ancho del fondo** | 150 mm | **65,15 mm** (±32,6 mm desde el centro) |

> **Traducido a la cancha: el cubo va CENTRADO en el fondo de la zona**, a unos
> 75 mm del borde. Cuidado con el reflejo de "empujarlo hasta el fondo": el
> borde externo de la zona es **la línea entre los centros de los marcadores**,
> no el borde de la mesa. Un cubo empujado más allá de esa línea **sobresale de
> la zona y no cuenta**, aunque a ojo parezca bien puesto. Un cubo apoyado
> **justo sobre** esa línea ya reporta **42,4 mm** de falta —media diagonal
> entera—, y uno empujado media celda más allá, 52,4 mm.
>
> Los 32,6 mm de tolerancia son cómodos, y no siempre lo fueron: con el fondo de
> 100 mm que tuvo la primera versión de la v2 eran **7,6 mm**, y en la cancha
> real un cubo bien puesto oscilaba a través de ese límite entre cuadro y
> cuadro. Por eso la zona se agrandó. **El criterio no se aflojó**: lo que se
> agranda es la zona, nunca el margen.

Este fragmento corre tal cual, con Python puro y nada importado:

```python
import math


def cubo_en_su_zona(cubo, depot, depot_size, grid, cube_side):
    """¿El cubo entero está dentro de su zona? Devuelve (adentro, cuánto falta)."""
    # 1. Sobre qué borde apoya la zona: el más cercano a su centro.
    distancias = {
        "arriba": depot["row"],
        "abajo": grid["rows"] - depot["row"],
        "izquierda": depot["col"],
        "derecha": grid["cols"] - depot["col"],
    }
    lado = min(distancias, key=lambda l: distancias[l])

    # 2. El largo va paralelo al borde, así que cuál de las dos medidas
    #    corresponde a col y cuál a row depende del lado.
    if lado in ("arriba", "abajo"):
        semi_col, semi_row = depot_size["length"] / 2, depot_size["depth"] / 2
    else:
        semi_col, semi_row = depot_size["depth"] / 2, depot_size["length"] / 2

    # 3. Media diagonal del cubo: el margen que lo mete entero con cualquier
    #    rotación, sin necesitar conocerla.
    margen = cube_side * math.sqrt(2) / 2

    exceso_col = max(0.0, abs(cubo["col"] - depot["col"]) - (semi_col - margen))
    exceso_row = max(0.0, abs(cubo["row"] - depot["row"]) - (semi_row - margen))
    falta = math.hypot(exceso_col, exceso_row)
    return falta == 0.0, falta
```

Con el cubo verde del mensaje de la [sección 2](#2-el-mensaje) —`(21.480, 3.762)`
contra una zona centrada en `(21.5, 3.75)`— da `(True, 0.0)`: está entregado. Si
ese cubo estuviera en `row = 5.5`, o sea 35 mm más adentro de la cancha, daría
`(False, 0.1213)`: le faltarían 0,12 celdas, 2,4 mm, para entrar.

Está implementado así en [`test_client.py`](test_client.py), listo para copiar.

### ¿Por qué `start`, `depots`, `depot_size` y `cube_side` no tienen `age_ms`?

Porque no se detectan: **se declaran**. Son lugares y medidas fijas que siempre
están y nunca se ocluyen. Los cubos, en cambio, se mueven, se tapan y envejecen.
Por eso van en listas separadas aunque compartan el color.

---

## 4. Sistema de coordenadas

```
              col ─────────────────────────────────────►

   (0,0) ▣═════════════[  zona VERDE  ]═════════════▣ (cols, 0)
     │   ║                                          ║
     │   ║                                          ║          ▣ = marcador
    row  ║                                    zona  ║              ArUco
     │   ▪ SALIDA            ▪ cubo           ROJA  ╢
     │   ║                                          ║
     ▼   ║                                          ║
         ▣═════════════[  zona AZUL   ]═════════════▣ (cols, rows)
```

Los números exactos de esta cancha de 43 × 43 celdas:

| Lugar | Color | Lado | Centro (col, row) | Ocupa en col | Ocupa en row |
|---|---|---|---|---|---|
| Acopio | `green` | arriba (0→1) | `(21.5, 3.75)` | 16,5 a 26,5 | 0 a 7,5 |
| Acopio | `red` | derecha (1→2) | `(39.25, 21.5)` | 35,5 a 43 | 16,5 a 26,5 |
| Acopio | `blue` | abajo (2→3) | `(21.5, 39.25)` | 16,5 a 26,5 | 35,5 a 43 |
| Salida | — | izquierda (3→0) | `(3.75, 21.5)` | — | — |

**Léanlos del mensaje igual.** Están acá para que se entienda la disposición, no
para que los escriban en el código: si se monta otra cancha, cambian.

- **Origen (0,0)** = marcador ArUco de **menor ID (el 0)**. Desde la v2 **no** es
  la salida: la salida está al centro del lado izquierdo. El origen es desde
  dónde se mide; la salida, dónde arrancan los robots.
- **`col` crece hacia la derecha.**
- **`row` crece hacia abajo.**
- **Unidad: celdas con decimales.** Una celda = **20 mm**.
  `col = 12.35` significa 247 mm desde el origen. Para pasar a milímetros:
  `mm = celdas * grid["cell_mm"]`.
- **`theta` en grados**, `0` = hacia la derecha (`col` creciente), sentido
  **antihorario**, rango `[0, 360]`.

Ojo con el ángulo: como `row` crece hacia **abajo**, un `theta` de 90° apunta
hacia **arriba** en la pantalla (`row` decreciente). El vector unitario de avance
es:

```python
dcol = math.cos(math.radians(theta))
drow = -math.sin(math.radians(theta))   # el signo menos es porque row va hacia abajo
```

### Nunca redondeen a entero

Las posiciones vienen con decimales **a propósito**. Un cubo en `col = 12.4` no
está "en la celda 12": está a 248 mm del origen. Redondear tira 10 mm de
precisión, que es la mitad de una celda. Trabajen en float.

### Puede haber valores apenas fuera de la grilla

La visión corrige el **paralaje** (los objetos altos se ven corridos hacia
afuera desde el centro de la cámara). Después de corregir, un objeto pegado al
borde puede quedar en `col = -0.3`. Es un dato **válido**, no un error. Si
necesitan acotarlo, acótenlo ustedes.

---

## 5. Fases

**La visión es árbitro.** Lleva el cronómetro oficial de la ronda y decide
cuándo empieza y cuándo termina.

| Fase | Qué significa para la visión | Qué cuenta el reloj |
|---|---|---|
| `IDLE` | Sistema encendido, ronda no preparada. | nada (`total_ms: 0`) |
| `READY` | Preparación en curso. | cuánto falta para que empiece la ronda |
| `RUNNING` | Ronda en juego. | cuánto queda de ronda |
| `FINISHED` | Ronda terminada. | se detiene con el tiempo que tomó |

### Quién dispara cada transición

```
IDLE ──ready──▶ READY ───el reloj───▶ RUNNING ───el reloj───▶ FINISHED
                  │                       │
                  └──abort──▶ IDLE        └──stop──▶ FINISHED
FINISHED ──ready──▶ READY        FINISHED ──abort──▶ IDLE
```

- **`READY → RUNNING` la hace el reloj, sola, y no hay forma de adelantarla.**
  Es lo que hace que todos los equipos preparen con el mismo tiempo. No existe
  ningún comando que salte la preparación.
- **`RUNNING → FINISHED` también puede hacerla el reloj**, de dos maneras: se
  agota el tiempo, o **todos los cubos en juego quedan en posición**. En el segundo caso el
  cronómetro se detiene con el tiempo que tomó el reto.
- Las demás las hace una persona operando el sistema.

### Por qué una ronda puede no arrancar

La visión **no prepara ni arranca una ronda si no ve la cancha**. Si no se
distinguen los marcadores de esquina, se queda donde está y lo dice en pantalla:
un árbitro no puede juzgar lo que no ve. Puede pasar también que la preparación
llegue a cero sin coordenadas; en ese caso la ronda **espera** a que vuelvan y
arranca ahí, sin devolverle a nadie el tiempo de preparación ya consumido.

Y si durante la ronda el sistema se queda sin ver la cancha más de un par de
segundos seguidos, la ronda **se cierra** con motivo `geometria_perdida`.

Para ustedes esto se ve en `phase` y `clock`, como todo lo demás: la fase no
cambia, o cambia a `FINISHED` antes de tiempo. No hay un campo aparte que lo
explique.

### Cuándo se toma el tiempo del reto

Cuando el último cubo **entra** en su zona, no cuando el sistema termina de
confirmarlo. La visión exige que un cubo se sostenga dentro durante un rato antes
de darlo por entregado —si no, la cuenta titilaría con el cubo parado justo en el
borde— pero ese rato **no se les cobra**: el reloj se detiene en el instante de
la entrada.

### La telemetría no se corta nunca

La visión **publica en todas las fases**, incluso en `IDLE`. Que llegue
telemetría no significa que la ronda esté corriendo: hay que mirar `phase`.
Conviene conectarse mucho antes de que empiece la ronda; descubrir un problema de
conexión cuando el reloj ya corre es caro.

---

## 6. Reglas de consumo

Estas cinco reglas son la diferencia entre un cliente que anda en la cancha y
uno que anda solo en la compu.

### 6.1. Iterar, nunca indexar por posición fija

**Mal:**

```python
mi_rover = msg["rovers"][0]        # ¿y si esta vez sos vos el [1]?
cubo_verde = msg["cubes"][0]       # ¿y si el verde está ocluido... o el orden cambió?
```

**Bien:**

```python
mi_rover = None
for r in msg["rovers"]:
    if r["id"] == MI_ID_ARUCO:
        mi_rover = r
        break

cubo_verde = next((c for c in msg["cubes"] if c["color"] == "green"), None)
```

La cantidad de objetos **cambia entre mensajes** y el orden **no está
garantizado**. Busquen siempre por identidad: `id` para rovers, `color` para
cubos y depots. Y manejen el caso de que **no esté**: `mi_rover` puede ser
`None`.

### 6.2. `age_ms` alto significa oclusión, no desaparición

Cuando algo se tapa —un rover encima de un cubo, un reflejo sobre un marcador—
la visión **no lo saca de la lista**. Lo mantiene con su **última posición
conocida** y **`age_ms` creciendo**.

Esto es deliberado: un objeto que parpadea entre existir y no existir vuelve
loco al consumidor. Es preferible un dato viejo y marcado como viejo, que un
agujero.

**Cómo se usa:**

```python
if cubo["age_ms"] < 200:
    pass    # dato fresco: la visión lo está viendo ahora
elif cubo["age_ms"] < 1500:
    pass    # probablemente tapado por un rover; sigue estando ahí, con menos certeza
else:
    pass    # muy viejo: hace rato que la visión no lo ve
```

Elijan sus umbrales, pero **elíjanlos**. Un dato de 3 segundos y uno de 20 ms
describen dos situaciones distintas, y el campo está para poder distinguirlas.

Y al revés: **que un cubo tenga `age_ms` alto no quiere decir que se lo llevaron**.
Quiere decir que la visión no lo ve. Casi siempre sigue justo donde dice.

### 6.3. Quédense con el último mensaje

La visión publica con la política **"el último valor gana"**: hay un buffer de
**un solo mensaje por cliente**, y si ustedes no lo drenan a tiempo, **se pisa**.
Nunca se les va a encolar telemetría vieja.

Esto significa que **los saltos en `seq` son normales**. Si ven `seq` 100, 101,
104, se perdieron dos: ustedes estaban ocupados. No hay nada que recuperar,
porque no hay nada que valga la pena recuperar — dónde estaba su rover hace
150 ms no le sirve a nadie.

**Lo que sí importa:** si `seq` salta **mucho**, su bucle es demasiado lento.
Midan los saltos y usen ese número para calibrar. `test_client.py` los cuenta.

**No acumulen mensajes para procesarlos después.** Lean, quédense con el más
nuevo, descarten el resto.

### 6.4. No naveguen con datos viejos

Midan la latencia: **`ahora_ms - ts_ms`**. `ts_ms` es el instante de **captura**,
así que ese número es la edad real del dato desde que la cámara lo vio.

```python
latencia_ms = int(time.time() * 1000) - msg["ts_ms"]
if latencia_ms > 500:
    pass            # el dato más nuevo que tengo es de hace medio segundo
```

Si la latencia se dispara —red saturada, su bucle trabado, la visión atrasada—
el mensaje que están usando describe un instante que **ya pasó**. El contrato les
da el número para que puedan saberlo; qué hacer con él es decisión de cada
equipo.

> Esto supone que el reloj del rover y el de la visión están más o menos en
> hora. Si difieren mucho, la latencia absoluta va a estar corrida; en ese caso
> miren la **variación** de la latencia, que sigue siendo útil.

### 6.5. Validen la versión

```python
if msg["v"] != 2:
    continue      # formato desconocido: descartar, no adivinar
```

Es una línea y les evita interpretar mal un mensaje del futuro.

---

## 7. Herramientas incluidas y cómo correrlas

Todo corre con **Python puro**: sin OpenCV, sin cámara, sin instalar nada.

Esta sección está escrita para alguien que **nunca usó la línea de comandos**.
Si ya te manejás, andá directo a "Resumen para tener a mano" al final.

---

### Paso 1 — Comprobá que tenés Python

Necesitás **Python 3.9 o superior**. El piso es bajo a propósito, para que te
sirva el que ya tenés: el que viene de fábrica en macOS es 3.9 y alcanza.

Abrí una terminal:

- **Windows:** apretá la tecla Windows, escribí `PowerShell`, Enter.
- **macOS:** apretá `Cmd + Espacio`, escribí `Terminal`, Enter.
- **Linux:** `Ctrl + Alt + T`.

Escribí este comando y apretá Enter:

| Sistema | Comando |
|---|---|
| **Windows** | `python --version` |
| **macOS / Linux** | `python3 --version` |

Tiene que responder `Python 3.9.x` o un número mayor.

> **⚠️ `python` y `python3` no son lo mismo.** En macOS y Linux el comando casi
> siempre es **`python3`**: si escribís `python` a secas te va a decir
> `command not found`. En Windows suele ser **`python`**.
>
> **Regla simple: usá de ahora en adelante el mismo nombre que te funcionó
> acá.** En todo este documento verás `python3`; si estás en Windows,
> reemplazalo mentalmente por `python` en cada comando.
>
> Si en Windows `python` no anda, probá `py` — algunas instalaciones usan ese.

Si no tenés Python o es muy viejo, bajalo de
[python.org/downloads](https://www.python.org/downloads/).

---

### Paso 2 — Pararte en la carpeta correcta

**Este es el paso donde más gente se traba.** La terminal siempre está "parada"
en alguna carpeta, y los comandos solo funcionan desde la carpeta correcta.

Tenés que pararte **dentro de la carpeta `contrato`** (la que contiene
`mock_publisher.py`). Escribí `cd `, un espacio, y **arrastrá la carpeta desde
el explorador de archivos hasta la ventana de la terminal**: se pega sola la
ruta. Después Enter.

Te va a quedar algo así:

```bash
cd "/Users/tu-usuario/Descargas/contrato"        # macOS / Linux
cd "C:\Users\tu-usuario\Downloads\contrato"      # Windows
```

> **Las comillas importan** si la ruta tiene espacios. Sin comillas, la terminal
> cree que le pasás varias cosas y falla.

Para confirmar que estás donde tenés que estar:

| Sistema | Comando | Qué tiene que aparecer |
|---|---|---|
| **Windows** | `dir` | la lista de archivos, con `mock_publisher.py` entre ellos |
| **macOS / Linux** | `ls` | ídem |

**Si no ves `mock_publisher.py` en esa lista, no sigas**: estás en otra carpeta
y todo lo demás va a fallar.

---

### Paso 3 — Levantar el simulador (terminal 1)

```bash
python3 mock_publisher.py
```

*(En Windows: `python mock_publisher.py`.)*

**Lo que tenés que ver si arrancó bien:**

```
==================================================================
Simulador del Vision-Rover-Challenge — protocolo v2
Publicando NDJSON en 0.0.0.0:2026 a 20 Hz
Cancha: 43x43 celdas de 20 mm
Preparación: 60 s   ·   Ronda: 600 s   (de READY a RUNNING pasa solo)
Comandos: ready | stop | abort | quit
==================================================================
```

Y cada 5 segundos, una línea de estado:

```
[estado] fase=IDLE seq=94 clientes=0 pisados=0
```

Que se lee: *estoy en fase IDLE, ya publiqué 94 mensajes, no hay nadie
conectado.*

> ### ⚠️ La terminal queda ocupada y parece congelada. **Está bien.**
>
> Después del cartel no vas a poder escribir otros comandos ahí, y no vuelve a
> aparecer el símbolo del sistema. **No se colgó.** El simulador está corriendo,
> publicando 20 mensajes por segundo, y esa terminal ahora le pertenece.
>
> Dejala abierta y **no la toques**. Todo lo demás va en una segunda terminal.

---

### Paso 4 — Conectar el cliente (terminal 2)

Hace falta **una segunda ventana de terminal**, porque la primera está ocupada
con el simulador.

**Cómo abrir la segunda:**

- **Windows:** abrí PowerShell de nuevo desde el menú Inicio.
- **macOS:** con la Terminal en primer plano, `Cmd + N`.
- **Linux:** `Ctrl + Alt + T` otra vez.

**Importante: en esta terminal nueva hay que repetir el Paso 2.** Cada ventana
arranca en su propia carpeta y no hereda nada de la otra. Volvé a hacer `cd` a
la carpeta `contrato`.

Y ahora sí:

```bash
python3 test_client.py
```

**Lo que tenés que ver si conectó bien:**

```
Conectando a 127.0.0.1:2026 ...
Conectado. Ctrl-C para cortar.

--- primer mensaje: ejemplo de consumo -------------------------
  cancha: 43x43 celdas de 20.0 mm  |  fase: IDLE  |  sin cuenta
  rover id=10  col=3.95 row=17.51 theta=0.4°  age=0 ms
  rover id=11  col=3.97 row=25.46 theta=0.9°  age=0 ms
  zona de acopio: 10.0 x 7.5 celdas (largo x fondo)  |  cubo: 3.0 celdas de lado
  cubo green en (26.03, 10.09) -> zona arriba (21.50, 3.75)  age=0 ms  [le falta 4.99 celdas]
  cubo blue  en (15.02, 28.99) -> zona abajo (21.50, 39.25)  age=0 ms  [le falta 9.35 celdas]
  cubo red   en (32.96, 26.01) -> zona derecha (39.25, 21.50)  age=0 ms  [le falta 4.94 celdas]
  salida en (3.75, 21.50)
---------------------------------------------------------------

[  2.0s] recibidos=37 invalidos=0 saltos=0 (perdidos=0)  latencia min/prom/max = 2/18/38 ms  age_max=38 ms
```

> Los dos rovers arrancan **junto a la salida**, al centro del lado izquierdo, y
> los tres cubos están repartidos por la cancha: por eso a cada uno "le falta"
> lo que le falta para entrar en su zona. Ese corchete es la cuenta de la
> [sección 3](#cuándo-un-cubo-está-en-su-zona) corriendo sobre datos de verdad,
> y cuando el cubo entra dice `EN POSICIÓN`.
>
> `obstacles` no aparece porque llega **vacío**, que es lo normal en esta
> edición del reto.

**Cómo leer esas cifras:**

| Dato | Qué significa | Qué esperar |
|---|---|---|
| `recibidos` | mensajes que llegaron | sube sin parar, ~20 por segundo |
| `invalidos` | mensajes que violaron el contrato | **tiene que ser 0** |
| `saltos` | veces que se salteó un número de secuencia | normal que haya algunos |
| `latencia` | cuánto tardó el dato en llegar, en milisegundos | decenas de ms |

Y en la **terminal 1** vas a ver aparecer la confirmación del otro lado:

```
[cliente] conectado 127.0.0.1:54087
```

Si ves eso, **funciona**. Ya estás recibiendo telemetría.

---

### Paso 5 — Controlar la fase de la ronda

Los comandos se escriben **en la terminal 1, la del simulador**, uno por vez, y
se aprieta **Enter**. El simulador hace de **árbitro**: él decide en qué fase
está la ronda.

| Escribís | Deja la fase en | Qué significa |
|---|---|---|
| `ready` | `READY` | Empieza la preparación, y el reloj con ella |
| `stop` | `FINISHED` | Cierra la ronda antes de tiempo |
| `abort` | `IDLE` | Cancela la preparación y vuelve al principio |
| `quit` | — | Apaga el simulador |

**No hay comando para arrancar la ronda**: de `READY` a `RUNNING` pasa el reloj
solo, al agotarse la preparación. El orden natural es escribir **`ready`** y
esperar.

> **El mundo simulado solo se mueve en `RUNNING`.** Si se conectan y ven todo
> quieto, no está roto: la ronda no empezó. Miren `phase` y `clock`.
>
> Para probar el ciclo completo sin esperar once minutos, bajen
> `ronda.preparacion_ms` y `ronda.duracion_ms` en `config_simulador.json`. Para
> eso están declarados.

Cada vez que escribís uno, el simulador te confirma en pantalla:

```
[fase] fase: IDLE -> READY
[fase] fase: READY -> RUNNING (se agotó la preparación)
[fase] fase: RUNNING -> FINISHED (se agotó el tiempo)
```

Ese `fase: X -> Y` es la prueba de que te escuchó. Fijate que las **dos últimas
las hizo el reloj solo**: vos solo escribiste `ready`.

> **No hay comando para arrancar la ronda.** Si escribís `start`, te responde:
>
> ```
> [fase] 'start' ya no existe: de READY a RUNNING pasa el reloj, no una tecla.
>        Para probar sin esperar, bajá ronda.preparacion_ms.
> ```
>
> Y equivocarte de orden tampoco rompe nada. Un `stop` sin ronda en juego:
>
> ```
> [fase] 'stop' no es válido desde IDLE (se puede desde ['RUNNING'])
> ```
>
> y sigue funcionando normal. Probá tranquilo.

El campo `phase` del mensaje cambia al instante, así que podés ver en el cliente
cómo reacciona tu código a cada fase. Qué significa cada una en detalle está en
la **sección 5**.

---

### Paso 6 — Cerrar todo

**Para cerrar el cliente (terminal 2):** apretá **`Ctrl + C`**. Te imprime un
resumen final y volvés al símbolo del sistema.

**Para cerrar el simulador (terminal 1):** dos formas, las dos válidas.

- Escribí **`quit`** y Enter. Es la forma prolija.
- O apretá **`Ctrl + C`**.

En ambos casos te despide con:

```
Simulador detenido. Mensajes publicados: 465
```

Podés cerrar el simulador **aunque el cliente siga conectado**: espera a que
todos terminen antes de salir.

> **`Ctrl + C` no es "copiar" en la terminal.** Es la señal de "interrumpí lo
> que estás haciendo". Para copiar texto en una terminal se usa `Ctrl + Shift +
> C` en Windows/Linux, o `Cmd + C` en macOS.

---

### Problemas frecuentes

#### `No se pudo conectar: [Errno 61] Connection refused`

**Qué pasó:** el cliente no encontró a nadie escuchando.

**Causa casi siempre:** arrancaste el cliente **antes** que el simulador, o el
simulador se cerró.

**Solución:** andá a la terminal 1 y confirmá que el simulador esté corriendo
(tiene que estar mostrando líneas `[estado] ...`). Si no, levantalo primero.
**El orden importa: primero el simulador, después el cliente.**

*(En Windows el número puede ser `[WinError 10061]`; es el mismo problema.)*

#### `OSError: [Errno 48] Address already in use`

**Qué pasó:** el puerto 2026 ya está ocupado. Aparece con varias líneas de texto
técnico; **no rompiste nada**.

**Causa:** ya hay otro simulador corriendo — típicamente uno de antes que quedó
abierto en otra ventana.

**Solución:** buscá la ventana donde quedó corriendo y cerralo con `quit`. Si no
la encontrás, cerrá todas las terminales y volvé a empezar.

*(En Windows el número es `[WinError 10048]`.)*

#### `No module named 'contrato'`

**Qué pasó:** estás parado en la carpeta equivocada.

**Causa:** ese error sale al usar el comando `python3 -m contrato.mock_publisher`
desde **adentro** de la carpeta `contrato`. Esa forma solo funciona desde la
carpeta **de arriba**.

**Solución:** usá la forma simple de esta guía, que anda desde adentro de
`contrato`:

```bash
python3 mock_publisher.py
```

#### `command not found: python` / `'python' no se reconoce...`

**Qué pasó:** ese nombre de comando no existe en tu sistema.

**Solución:** en macOS y Linux probá **`python3`**. En Windows probá **`python`**
y, si tampoco, **`py`**. Usá el que te haya funcionado en el Paso 1.

#### El simulador arrancó pero no pasa nada / parece congelado

**No está congelado.** Es lo normal: la terminal queda ocupada por el programa.
Fijate que cada 5 segundos aparezca una línea `[estado] ...`. Si aparece, está
vivo. El cliente va en **otra** ventana.

#### El cliente conecta pero los rovers no se mueven

Están quietos porque la ronda no arrancó: **el mundo simulado solo se mueve en
`RUNNING`**. Andá a la terminal 1, escribí `ready`, Enter, y **esperá**: la
preparación dura un minuto y después la ronda arranca sola. Mientras tanto,
`clock.remaining_ms` te dice cuánto falta.

Si no querés esperar cada vez que probás, bajá `ronda.preparacion_ms` en
`config_simulador.json`. Para eso está declarado.

---

### Tu propio código: consumir la telemetría

Todo lo que necesitás está en el JSON que llega por la red. **No hay ninguna
biblioteca que instalar, ni ningún archivo de esta carpeta que importar.** Se
abre un socket, se leen líneas, se parsea cada una con las herramientas
estándar del lenguaje, y se leen los campos.

Este es **el** ejemplo. Corre tal cual contra el simulador:

```python
import json
import socket

HOST = "127.0.0.1"       # IP de la máquina donde corre la visión (ver sección 1)
PORT = 2026
MI_ID_ARUCO = 10         # el ID del marcador pegado a TU robot

conexion = socket.create_connection((HOST, PORT))
buffer = b""

while True:
    trozo = conexion.recv(4096)
    if not trozo:
        break                                   # la visión cerró la conexión
    buffer += trozo

    while b"\n" in buffer:
        linea, buffer = buffer.split(b"\n", 1)
        mensaje = json.loads(linea)

        if mensaje["v"] != 2:                   # versión desconocida: descartar
            continue
        if mensaje["phase"] != "RUNNING":       # la ronda no está en juego
            continue

        # Mi rover se BUSCA por id. Nunca se indexa por posición: el orden de
        # la lista no está garantizado y la cantidad cambia entre mensajes.
        mi_rover = None
        for rover in mensaje["rovers"]:
            if rover["id"] == MI_ID_ARUCO:
                mi_rover = rover
        if mi_rover is None:
            continue                            # este cuadro no me vio

        # Cada cubo va al depot de SU color: se cruzan las dos listas por color.
        depots = {}
        for depot in mensaje["depots"]:
            depots[depot["color"]] = depot

        print("fase={}  mi rover: col={:.2f} row={:.2f} theta={:.1f}".format(
            mensaje["phase"], mi_rover["col"], mi_rover["row"], mi_rover["theta"]))

        for cubo in mensaje["cubes"]:
            if cubo["age_ms"] > 1500:
                continue                        # dato viejo: seguramente tapado
            destino = depots[cubo["color"]]
            print("   cubo {:<5} en ({:.2f}, {:.2f})  ->  depot ({:.2f}, {:.2f})".format(
                cubo["color"], cubo["col"], cubo["row"], destino["col"], destino["row"]))

        for obstaculo in mensaje["obstacles"]:
            pass                                # ... esquivarlos ...
```

**Probalo ahora mismo:** guardá eso como `mi_cliente.py`, dejá el simulador
corriendo (Paso 3), corrélo con `python3 mi_cliente.py` y escribí `ready` en la
terminal del simulador. Cuando se agote la preparación, la ronda arranca sola y
vas a ver:

```
fase=RUNNING  mi rover: col=11.92 row=17.93 theta=359.2
   cubo green en (26.05, 10.06)  ->  depot (21.50, 3.75)
   cubo blue  en (14.93, 28.96)  ->  depot (21.50, 39.25)
   cubo red   en (33.03, 26.14)  ->  depot (39.25, 21.50)
```

**Detalles que importan de ese ejemplo, y por qué:**

| Qué hace | Por qué |
|---|---|
| Acumula en `buffer` y corta por `\n` | TCP no respeta los límites de los mensajes (sección 1) |
| Descarta si `v` no es 2 | formato desconocido: no adivinar |
| No hace nada fuera de `RUNNING` | el campo `phase` dice si la ronda está en juego (sección 5) |
| **Busca el rover por `id`**, no por posición | el orden de las listas no está garantizado (sección 6.1) |
| **Cruza cubos y depots por `color`** | el color es la identidad del cubo |
| Ignora cubos con `age_ms` alto | están tapados: el dato es viejo (sección 6.2) |

> **Si no imprime nada**, es porque la ronda no arrancó: escribí `ready` en la
> terminal del simulador y esperá a que se agote la preparación. Y si te sale
> `ConnectionRefusedError`, el simulador no está corriendo — mirá "Problemas
> frecuentes" acá arriba.

> **En el robot es exactamente lo mismo.** El rover corre **CircuitPython** sobre
> ESP32, que también trae `json` y sockets: la telemetría se parsea igual, con
> las herramientas estándar del lenguaje. Lo único distinto es la parte de
> conectar la placa al Wi-Fi, y que la dirección ya no es `127.0.0.1` sino la IP
> de la máquina de visión (sección 1).

Las reglas completas de consumo —qué hacer con `age_ms`, cómo medir latencia,
por qué quedarse siempre con el último mensaje— están en la **sección 6**.

---

### Las herramientas, en detalle

#### `mock_publisher.py` — el simulador

**Miente feo a propósito.** Reproduce las patologías reales:

- **ruido** en posición y orientación;
- **oclusiones**: un rover que pasa sobre un cubo lo tapa, y el `age_ms` del
  cubo crece;
- **pérdidas** ocasionales de detección de un rover;
- **cubos que se mueven** cuando un rover los empuja.

Si tu código anda contra el simulador, tiene chance en la cancha. Si el ruido
del simulador lo rompe, la cancha lo va a romper igual.

Todo lo configurable está en [`config_simulador.json`](config_simulador.json):
tamaño de grilla, IDs de los rovers, cuántos cubos y de qué color, posiciones de
`start` y `depots`, nivel de ruido y tasa de publicación. Editá ese archivo, no
el código, para probar otros escenarios.

#### `test_client.py` — cliente de referencia

Ejemplo mínimo y funcional de consumo. Se conecta, parsea, **valida cada
mensaje** y mide latencia y saltos de secuencia. Acepta opciones:

```bash
python3 test_client.py --host 127.0.0.1 --port 2026 --duracion 10
```

| Opción | Para qué |
|---|---|
| `--host` | a qué máquina conectarse (ver sección 1 para el caso del robot) |
| `--port` | el puerto; por defecto `2026` |
| `--duracion` | segundos a escuchar y salir solo; `0` = hasta `Ctrl + C` |
| `--silencioso` | solo el resumen final |

Usalo de dos formas: como **punto de partida** para tu propio cliente, y como
**diagnóstico** — si no sabés si el problema es tuyo o de la red, corré esto al
lado y compará.

---

### Resumen para tener a mano

**Terminal 1** — parado dentro de la carpeta `contrato`:

```bash
python3 mock_publisher.py
```

Después escribí `ready`, Enter. La ronda arranca sola cuando se agota la
preparación.

**Terminal 2** — también parado dentro de `contrato`:

```bash
python3 test_client.py
```

**Para cerrar:** `Ctrl + C` en el cliente, `quit` en el simulador.

*(En Windows, `python` en lugar de `python3`.)*

> **Nota para quien ya se maneja:** también podés correrlos como módulos desde
> la carpeta **madre** de `contrato/`, con
> `python3 -m contrato.mock_publisher`. Las dos formas son equivalentes; la de
> esta guía se eligió porque funciona desde la carpeta donde están los archivos
> y evita el error `No module named 'contrato'`.

---

## 8. Qué garantiza la visión y qué no

**Garantiza:**

- El formato de este documento, mientras `v` valga `2`.
- Que va a **seguir publicando** aunque algo falle adentro: ante un error se
  conserva el último estado bueno y se sigue emitiendo. El sistema no se cae a
  mitad de ronda.
- Que un objeto **no desaparece** de su lista por estar tapado: se queda con su
  última posición y `age_ms` creciendo.
- Que `seq` sube de a uno **por mensaje publicado** (los huecos que ustedes ven
  son mensajes que se pisaron por la política de último-valor-gana).

**No garantiza:**

- Que todos los objetos estén siempre frescos. Miren `age_ms`.
- Que las listas tengan un largo fijo, ni un orden estable. Iteren y busquen por
  identidad.
- Que las posiciones caigan siempre dentro de la grilla (corrección de paralaje).
- Una tasa de entrega exacta a cada cliente. Un cliente lento recibe menos
  mensajes, siempre los más nuevos.

---

## 9. Cambios de contrato

Este formato **es un contrato**. No cambia sin:

1. **subir `v`**, y
2. **avisarles** con tiempo.

### El campo `clock`, agregado dentro de la v2

La v2 **sumó `clock` sin subir la versión**, y conviene que quede escrito por qué,
para que no se lea como que el contrato se puede estirar a gusto.

La regla —no se cambia el contrato sin subir `v` y avisar— existe para proteger a
quien ya escribió código contra el formato. En el momento de agregarlo **ningún
equipo tenía todavía un cliente de telemetría**, así que no había nada que
romper: no había código que proteger. Subir a `v: 3` habría obligado a todos a
escribir un número distinto sin que nadie ganara nada.

**Esto no vuelve a pasar.** Con clientes en la calle, un campo nuevo es un cambio
de contrato como cualquier otro y va con cambio de versión y aviso.

### Migración de la v1 a la v2

**Qué NO se rompe.** Nada de la forma del mensaje que ya consumían: `grid`,
`rovers`, `cubes`, `obstacles`, `phase`, `seq`, `ts_ms`, `start` y `depots`
siguen existiendo, con los mismos nombres, los mismos tipos y las mismas
unidades. El transporte, el puerto, el NDJSON y la política de último-valor-gana
tampoco cambian. El código que itera listas y busca por identidad sigue andando.

**Qué se rompe, y cómo darse cuenta.**

| Qué | Qué hacer |
|---|---|
| El chequeo `msg["v"] != 1` descarta **todos** los mensajes | Cambiarlo por `!= 2`. Es el síntoma más común: el cliente conecta, no procesa nada y parece que la visión no publica. |
| Un validador estricto que rechace campos desconocidos | Ahora llegan `depot_size` y `cube_side`. Aceptarlos. |
| Código que trataba `start` como el **origen (0,0)** | Ya no coinciden. El origen sigue siendo el marcador 0; la salida está en `(3.75, 21.5)`. |
| Código que asumía las zonas **en las esquinas** | Ahora están al centro de los lados. Si estaba escrito leyendo `depots` del mensaje —como pedía la v1— no hay nada que tocar. |
| Llegar a la zona y soltar el cubo "cerca" del punto | En la v1 la zona era un punto y "cerca" era una decisión de cada equipo. Ahora hay un **criterio exacto** y el cubo tiene que quedar **entero adentro**: ver [la cuenta](#cuándo-un-cubo-está-en-su-zona). |

**Qué conviene aprovechar.** `depot_size` y `cube_side` les permiten calcular
**durante la ronda** si un cubo ya está entregado, con la misma cuenta que usa la
visión. No hace falta estimarlo ni pedirlo por radio.

Si algo de este documento les resulta ambiguo, **pregunten antes de asumir**.
Una ambigüedad aclarada a tiempo cuesta cinco minutos; descubierta el día de la
competencia, cuesta la ronda.
