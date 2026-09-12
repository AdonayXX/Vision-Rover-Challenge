# tools/

**Herramientas visuales.** Utilidades que apoyan la puesta a punto. No forman
parte del flujo de publicación: nada de lo que hay acá se ejecuta durante una
ronda.

> **¿Vas a poner a punto una cámara?** El procedimiento en orden, paso a paso,
> está en [`PUESTA_A_PUNTO.md`](../../PUESTA_A_PUNTO.md). Este README es la
> **referencia** de cada herramienta —qué hace, todas sus opciones y por qué
> está hecha así—; aquel es el **instructivo**.

## Lo que ya existe

### `verificar_geometria.py`

Verifica el sistema de coordenadas contra la **verdad conocida** del generador
sintético de `sources/`: genera una imagen del tablero, detecta los cuatro
marcadores de esquina, construye la transformación de píxeles a celdas y mide
cuánto se desvía de lo real.

```bash
python -m vision.tools.verificar_geometria
python -m vision.tools.verificar_geometria --salida /tmp/tablero.png --anotar
```

Mide en puntos que **no participaron del ajuste** de la homografía —el centro,
los medios de los bordes y una rejilla interior—, porque una homografía de
cuatro puntos es exacta en esos cuatro por definición y verificar sobre los
marcadores no probaría nada. Corre en dos modos, con y sin inclinación de
cámara, y devuelve código de salida distinto de cero si algún grupo se pasa del
umbral.

#### Y un tercer bloque: la degradación

Además comprueba **qué pasa si se pierde un marcador de esquina**, tapándolos de
verdad sobre la imagen —agrandando el cuadrilátero para tapar también la zona
blanca, que es exactamente cómo se pierde un marcador en la cancha real—.

| Situación | Qué se exige |
|---|---|
| Los cuatro visibles | recalcula, 0,520 mm |
| Uno tapado | conserva y verifica: **0,520 mm**, la misma precisión |
| Dos tapados | **rechaza**: no hay con qué comprobar nada |
| Uno tapado y la cámara movida 0,5° o 2° | **rechaza**: los tres visibles la delatan |
| Uno tapado y la cámara movida 0,1° | acepta, y es correcto: son 0,62 mm de error |

El detalle de por qué con tres se conserva en vez de reajustar está en
[`../geometry/README.md`](../geometry/README.md).

#### Y un cuarto bloque: los IDs duplicados

Dos marcadores distintos que decodifican el **mismo ID** en un cuadro. La cancha
real lo produce sola: medido, el ID 10 —que es un ID de rover— apareció 46 veces
en dos minutos con el rover retirado del tablero.

| Situación | Qué se exige |
|---|---|
| Fantasma de 30 mm con el ID de un rover | **resuelve**: gana el de 41,6 mm |
| Fantasma de 30 mm con el ID de una esquina | **resuelve**, y la homografía sigue dando 0,52 mm |
| Dos marcadores idénticos con el ID de un rover, sin el rover | **descarta el cuadro** |

Las dos salidas son correctas en su caso. Resolver, porque en cada ronda hay un
marcador real 10 y del orden de veintitrés fantasmas 10 por minuto chocando
contra él: descartar tiraría más del 1 % de los cuadros por algo que el sistema
puede decidir midiendo. Descartar, cuando los candidatos son igual de
plausibles, porque ahí elegir es adivinar.

> **El caso ambiguo se arma SIN el rover real, y no es un detalle de montaje.**
> Con el rover en la cancha el caso deja de ser ambiguo: uno de los tres
> candidatos está justo donde el seguimiento lo recuerda y gana limpio.

Los marcadores extra los dibuja el generador a pedido (`MarcadorExtra`): esperar
a que la cancha real produzca el caso sería depender de la suerte.

### `verificar_rovers.py`

Verifica la **detección de rovers** contra la misma verdad conocida: genera
imágenes con rovers en celdas y ángulos que el generador sabe, los detecta y
compara. Reporta error de **posición** (celdas y mm) y de **orientación**
(grados), con máximo, promedio y umbral.

```bash
python -m vision.tools.verificar_rovers
python -m vision.tools.verificar_rovers --salida /tmp/rovers.png --anotar
python -m vision.tools.verificar_rovers --umbral-mm 5 --umbral-grados 2
```

Corre cuatro escenarios en los dos modos de cámara:

| Escenario | Qué pone a prueba |
|---|---|
| Los dos rovers de la configuración | el caso de todos los días |
| Cinco rovers repartidos | que cada rover se corresponde con **su** ID |
| Ángulos en el borde del círculo | el salto de 359° a 0° |
| Barrido cada 10° | que el ángulo está bien en todo el círculo |

La prueba de identidad no se conforma con que los errores sean chicos: exige que
**cada rover esté más cerca de su propia verdad que de la de cualquier otro**.
Dos rovers que se intercambiaran el ID podrían tener errores individuales
razonables y estar todo mal.

El escenario del salto angular imprime, al lado, la **resta ingenua** y la
diferencia bien calculada, para que se vea el problema en vez de tener que
creerlo.

### `verificar_cubos.py`

Verifica la **detección de cubos**: que los encuentre por color, que los ubique
por su **base** —que es lo que el contrato publica— y que aguante que un rover
los tape.

```bash
python -m vision.tools.verificar_cubos
python -m vision.tools.verificar_cubos --salida /tmp/cubos.png --anotar
```

Cinco escenarios en los dos modos de cámara: los tres cubos de la configuración,
cubos repartidos por la cancha, tres rotaciones distintas, un rover **empujando**
el cubo, y un rover tapándolo aún más.

Cada fila reporta el ajuste **al lado del centroide ingenuo** —el método que se
descartó— para que la diferencia se vea en vez de haber que creerla. Con la
cámara inclinada: **1,05 mm** contra 9,84 con el cubo despejado, y **4,88 mm**
contra 17,01 con un rover empujándolo.

> **El último escenario cambia de pregunta.** Con el 70 % del cubo tapado el
> ajuste llega a errar más que el centroide: cuando se le acaba la evidencia, el
> método se degrada. Ahí no se le exige **acertar** sino **no mentir**, y lo que
> se comprueba es que la detección se marque como no confiable.

### `verificar_seguimiento.py`

Verifica que el seguimiento cumpla **la promesa del contrato sobre oclusión**:
que un objeto tapado no desaparezca de su lista.

```bash
python -m vision.tools.verificar_seguimiento
```

La sección 8 de [`CONTRATO.md`](../../contrato/CONTRATO.md) hace cuatro
afirmaciones comprobables, y cada escenario las comprueba todas: mientras el
objeto está tapado **sigue en la lista**, su **posición no se mueve**, su **edad
crece** y coincide con el tiempo transcurrido, y al reaparecer **vuelve a cero**.

| Escenario | Qué pone a prueba |
|---|---|
| El cubo verde deja de verse | la oclusión total |
| Al rover 11 se le tapa el marcador | que los rovers reciben el mismo trato |
| Un rover tapa el cubo hasta volverlo no confiable | que una detección dudosa **no** refresca |

Se prueba con **cuadros generados y procesados de punta a punta**, no con
detecciones escritas a mano: así se ejercitan detección, confiabilidad y memoria
juntas, en vez de comprobar solo que un diccionario recuerda cosas.

### `verificar_acopio.py`

Verifica la regla de entrega del reto: **¿el cubo está completamente dentro de
su zona?**

```bash
python -m vision.tools.verificar_acopio
python -m vision.tools.verificar_acopio --holgura-mm 5
python -m vision.tools.verificar_acopio --modo cenital
```

Corre en **dos bloques**, y el primero es el que sostiene todo lo demás.

**Bloque 1 — el criterio, sin imágenes.** Que el límite de la ventana esté donde
dice, y sobre todo que el criterio sea **conservador para cualquier rotación**:
con el centro del cubo parado en el borde de la ventana, sus cuatro esquinas
tienen que caer dentro de la zona esté como esté girado. Se barre el giro de 0°
a 90° sobre los cuatro bordes de las tres zonas. Si esa propiedad no se
cumpliera, el sistema daría por entregado un cubo que sobresale.

> **El borde exacto no se prueba, y es a propósito.** No se puede representar:
> `21.5 + 2.8786796564403576 − 21.5` devuelve dos milésimas de femtocelda de
> más —4 × 10⁻¹⁴ mm— así que una desigualdad cae de un lado o del otro según la
> zona y el eje. Probar ese punto mediría la coma flotante. Lo que se prueba es
> **un pelo adentro** y **un micrón afuera**, que es la frontera que existe.

**Bloque 2 — el sistema entero**, sobre imágenes sintéticas y en los dos modos
de cámara: los cubos en el centro de su zona, justo adentro del criterio, justo
afuera, y girados 45°. Acá no se prueba una fórmula sino la cadena completa
—detección de color y ajuste de la base incluidos—, que es donde entra el error
real de ubicación.

Cada veredicto positivo se comprueba además **contra la verdad del generador**:
que el cubo que el sistema dio por entregado esté de verdad entero dentro del
rectángulo, no solo que el número detectado sea coherente.

| Por qué la holgura | |
|---|---|
| "Justo adentro" y "justo afuera" no pueden ser *exactamente* el límite | el detector ubica con ~1 mm de error, y un cubo a cero del límite caería de un lado o del otro según el ruido: la prueba mediría la detección y no el criterio |
| Por defecto son **3 mm** | tres veces ese error |
| "Justo afuera" empuja **hacia adentro de la cancha** | es el error que ocurre de verdad en una ronda: el rover no terminó de empujar el cubo hasta el fondo de la zona |

### `verificar_ronda.py`

Verifica el **árbitro**: el mapa de transiciones y el cronómetro oficial.

```bash
python -m vision.tools.verificar_ronda
```

Seis bloques: las transiciones que se pueden y las que **no** —que `start` no
exista y que arrancar en `RUNNING` lance son parte de lo verificado—, los tres
valores del cronómetro, el cierre por reto cumplido, la cadena completa
contador + árbitro, **las guardas de geometría** —que sin ver la cancha no se
prepara ni se arranca una ronda, y que un apagón largo la cierra— y el acta.

El reloj **se inyecta**, y por eso la herramienta existe: verificar el cierre por
tiempo agotado durmiendo diez minutos haría que nadie la corriera nunca, y una
verificación que no se corre no verifica nada. Así se prueba el instante exacto
del límite, un milisegundo antes, y **pasado**, que es el caso que siempre ocurre
de verdad.

### `verificar_config.py`

Revisa `config_vision.json` **antes** de que importe, y muestra lo que el
sistema entendió de lo que ahí dice.

```bash
python -m vision.tools.verificar_config
python -m vision.tools.verificar_config --config otra_config.json
```

Responde **dos preguntas distintas**, y esa separación es el punto de la
herramienta:

| | Quién lo decide | Qué pasa |
|---|---|---|
| **¿Es posible?** | `revisar_config` | Si no, el sistema **no arranca** |
| **¿Es además razonable?** | `avisos_config` | Avisa y **deja arrancar** |

Un error es una configuración que describe una cancha que no existe —una zona de
acopio en una esquina, o más grande que el tablero—. Eso no falla cuando se usa:
publica telemetría perfectamente válida y mal, y el equipo que la consume busca
el problema en su propio código.

Un aviso es algo posible pero **ajustado**. El que motivó la separación, y que
hoy ya no aparece, es el mejor ejemplo de para qué sirve: con el fondo de zona
de 100 mm, la ventana donde tiene que caer el centro del cubo medía **15,2 mm**
—7,6 mm a cada lado del eje— contra un criterio de precisión de **10 mm**. La
cancha real le dio la razón: un cubo bien puesto oscilaba a través de ese
límite. El fondo subió a 150 mm y el aviso se apagó solo.

> **El código de salida solo mira los errores.** Con avisos y sin errores sale
> 0, para que encadenar esto a otra cosa no se rompa porque una medida quedó
> justa. Un aviso que bloqueara el arranque terminaría borrado por quien tiene
> una ronda esperando; un error que solo avisara, ignorado hasta que sea tarde.

Lo que imprime es **lo deducido, no lo escrito**: el lado sobre el que apoya
cada zona no está declarado en ninguna parte —sale del borde más cercano a su
centro— y verlo acá es la forma de confirmar que salió el que uno esperaba,
antes de tener la cancha montada.

### `medir_desfases.py`

Mide los **dos desfases entre el marcador y el robot** usando el propio sistema
de visión, sin instrumental aparte. Los muestra listos para pegar en la
configuración; **no los aplica**.

```bash
python -m vision.tools.medir_desfases --autoprueba          # sin cámara
python -m vision.tools.medir_desfases                       # con el robot real
python -m vision.tools.medir_desfases --metodo-angular avance
python -m vision.tools.medir_desfases --solo-posicion --desfase-angular 40.2
```

**Orden: primero el ángulo, después la posición.** El desfase de posición se
expresa en el marco del robot, y para pasar del marco del marcador al del robot
hace falta el desfase angular. Por eso `--solo-posicion` exige
`--desfase-angular`.

#### Desfase de posición: el robot gira sobre su eje

Si el marcador estuviera sobre el centro de rotación, la posición reportada se
quedaría quieta al girar. Como está corrido, describe una **circunferencia**.

El ajuste **no** es un ajuste de círculo. Un círculo usa solo las posiciones y
tira la orientación, que también se mide en cada muestra. Usándola, el problema
es **lineal y de un paso**: `M = C + a·adelante(φ) + i·izquierda(φ)`, cuatro
incógnitas y dos ecuaciones por muestra. La dirección sale en el mismo paso.

El **círculo de Kåsa se ajusta igual, como control cruzado independiente**: llega
al radio por un camino que ignora las orientaciones. Que los dos coincidan es la
salvaguarda de un número que después corrige todas las posiciones publicadas.

| Cuánto gira el robot | Amplificación del error del centro |
|---|---|
| 360° / 270° / 180° | ×1,0 |
| 120° | ×2,0 |
| 90° | ×3,4 |
| 45° | ×13,1 |
| 20° | ×65,8 |

Es `1/(1−cos(arco/2))`, y por eso hay un **mínimo duro**: por debajo de 120° la
herramienta **se niega a dar un resultado** en vez de dar uno malo con cara de
bueno. Lo recomendado es una vuelta completa con 24 muestras.

> El arco se mide como **cobertura**, no como `máximo − mínimo`: se resta del
> círculo el hueco más grande entre muestras consecutivas. Por eso una vuelta
> completa con muestras cada 15° reporta ~345° y no 360°. Dos muestras en 1° y
> 359° están **pegadas**, no separadas por 358°.

#### Desfase angular: dos métodos

| Método | Cómo | Precisión |
|---|---|---|
| `declarado` (por defecto) | alineás las paletas con una línea de la cuadrícula y declarás el rumbo con `0`/`9`/`8`/`2` | limitada por tu ojo al alinear |
| `avance` | mandás el robot **derecho** y la visión mide la dirección del desplazamiento | mejor: para un robot diferencial la dirección de avance **es** su frente, y la mide el sistema |

Los dos promedian varias orientaciones por **media circular**
(`atan2(Σ sen, Σ cos)`). Promediar 359° y 1° a secas da 180°, que es el revés de
la respuesta.

#### El paralaje infla el módulo un 4,0 %

El marcador está a 80 mm del tablero, así que se ve corrido hacia afuera.
Mientras el robot gira en el lugar, ese efecto es una **homotecia** alrededor del
punto bajo la cámara: **conserva la dirección y escala el módulo** por
`H/(H−h)` = 1,0396 con la cámara a 2,1 m.

La herramienta reporta **el valor medido y el corregido**, y recomienda el
corregido. Es el primer consumidor real del bloque `paralaje` de la
configuración. La altura se pasa con `--altura-camara-mm`.

#### El aviso en vivo: "Giro puro"

Durante la captura, el panel muestra el **tamaño de la nube de puntos** al lado
del **círculo que el ajuste va estimando**. La comprobación es directa: si el
desfase vale `r`, la posición del marcador en una vuelta tiene que recorrer un
círculo de diámetro `2r` **y nada más**. Una nube mucho más grande no es un
desfase grande: es el robot **desplazándose mientras gira**.

Si se pone rojo, aparece `EL ROBOT SE ESTÁ TRASLADANDO — pará y reintentá`, y
también sale por consola con los dos números.

Usa **los mismos umbrales** que el veredicto final: un aviso en vivo que juzgara
con otro criterio sería peor que no tenerlo, porque diría "vas bien" y después
reprobaría. Existe por dos sesiones perdidas del 9-ago-2026, donde eso se supo
al terminar de capturar; reproduciéndolas, el aviso habría saltado en la muestra
**15 de 24** y **16 de 22**. Sobre un giro limpio no da ninguna falsa alarma.

#### El residuo es un diagnóstico físico

El modelo supone giro **puro**. Si el robot se traslada mientras gira, el residuo
se dispara. Un residuo alto casi nunca significa "la matemática falló": significa
**"el robot se movió del lugar"**, y así se reporta. El veredicto mira el **RMS**
y no el máximo, porque el máximo lo fija una sola muestra desafortunada —con 24
siempre hay una— y daría falsas alarmas sobre mediciones sanas.

#### La autoprueba

`--autoprueba` corre **sin cámara**: le inyecta al generador sintético un robot
con un desfase **conocido** (35 mm adelante, −12 mm a la izquierda, 40° de
desfase angular), genera las imágenes de un giro y comprueba que el estimador lo
recupera. La matemática se verifica contra la verdad conocida **antes** de
apuntarle al robot: si hubiera un signo cambiado, se descubre acá y no con el
robot en la mano.

### `diagnostico_camara.py`

Responde si la cámara sirve tal cual o hay algo que resolver. Abre la webcam,
muestra el video en vivo e informa **fps reales**, **edad del cuadro**, qué
ajustes aceptó de verdad y **si ve los cuatro marcadores de esquina**,
dibujándolos sobre la imagen.

```bash
python -m vision.tools.diagnostico_camara            # ventana en vivo
python -m vision.tools.diagnostico_camara --listar   # ¿qué cámaras responden?
python -m vision.tools.diagnostico_camara --indice 1 # elegir otra cámara
python -m vision.tools.diagnostico_camara --sintetico    # sin cámara
python -m vision.tools.diagnostico_camara --sin-ventana  # sin pantalla
python -m vision.tools.diagnostico_camara --segundos 10  # cerrar solo a los 10 s
python -m vision.tools.diagnostico_camara --sin-efecto   # saltear la prueba de ajustes
```

Si no se pasa `--indice`, respeta lo que diga `camara.indice` en la
configuración, que además del número acepta `"menu"` para elegir de una lista.
Ver [`../sources/README.md`](../sources/README.md).

La información en pantalla la dibuja [`panel.py`](#panelpy), que es lo que
permite que diga "exposición" y no "exposici??n".

Al cerrar imprime un resumen en lenguaje claro con lo que encontró y qué hacer
si falta algo. Reusa la detección de marcadores de
[`../geometry/`](../geometry/README.md): escribir otra acá daría dos
implementaciones que pueden divergir, y el diagnóstico dejaría de decir nada
sobre el sistema real.

El indicador que más importa apuntando al tablero físico es
**"MARCADORES DE ESQUINA: 4 de 4"**: significa que el mundo real se comporta como
lo sintético y las coordenadas se pueden anclar.

### `diagnostico_falsos_positivos.py`

Mide **cuántos marcadores inventa el detector de ArUco** sobre la cancha real.

```bash
python -m vision.tools.diagnostico_falsos_positivos
python -m vision.tools.diagnostico_falsos_positivos --minutos 5
python -m vision.tools.diagnostico_falsos_positivos --sintetico   # probar la herramienta
```

> ⚠️ **La cancha tiene que estar VACÍA**: los cuatro marcadores de esquina y nada
> más. Todo lo que aparezca que no sea una esquina es, por definición, un falso
> positivo.

**No corrige nada, y es el punto.** El tablero es una cuadrícula fina de blanco y
negro —exactamente la clase de textura con la que se construye un código ArUco— y
`DICT_4X4_50` tiene poca distancia entre códigos, así que un recorte afortunado
puede parecerse lo suficiente a un marcador válido. Elegir umbrales para eso a
ojo es adivinar; esta herramienta da los números con los que decidir.

De cada detección que no sea una esquina registra:

| Qué | Para qué sirve |
|---|---|
| **ID** | si cae en un ID declarado de rover, el fantasma **pisa a un rover de verdad**, en silencio |
| **Lado en mm** sobre el plano del tablero | un marcador real mide 100 mm (esquina) o 40 (rover); un fantasma casi nunca |
| **Error de cuadratura** | en celdas un marcador real vuelve a ser un cuadrado: sus cuatro lados y sus dos diagonales coinciden. Un recorte de la cuadrícula, no |
| **Racha** | cuántos cuadros CONSECUTIVOS duró. Un fantasma vive uno o dos y salta a otro lado |

Todo se mide **en celdas y no en píxeles**: en píxeles, un marcador cerca del
borde de la imagen se ve más chico que el mismo marcador en el centro, así que
los tamaños no se podrían comparar entre sí. La homografía deshace exactamente
eso.

**Los cuatro marcadores de esquina se miden también, con la misma vara.** Son el
**control**: sin saber cuánto se desvía un marcador legítimo no hay forma de
elegir la tolerancia con la que rechazar a los falsos.

El informe final da la tasa por minuto —en detecciones y en apariciones
distintas—, qué IDs aparecieron, la distribución de tamaños y cuántos de esos
tamaños caen cerca de un marcador real. También informa **cuánto infla el
paralaje** al marcador del rover, que está a 80 mm de altura y por eso se mide
más grande de lo que es: quien fije una tolerancia de tamaño tiene que
contemplarlo.

### `patron_calibracion.py`

Genera en PDF, **a tamaño real**, el ajedrezado que necesita la calibración.

```bash
python -m vision.tools.patron_calibracion --salida patron.pdf
python -m vision.tools.patron_calibracion --columnas 9 --filas 6    # version de una hoja
python -m vision.tools.patron_calibracion --marcador-prueba 20      # el marcador de precisión
```

**Qué patrón elegir.** Con cuadros de 25 mm sobre papel Carta horizontal:

| Esquinas internas | Tamaño | Hojas | Empalmes |
|---|---|---|---|
| 9 × 6 | 250 × 175 mm | 1 | 0 |
| **13 × 6** ← por defecto | **350 × 175 mm** | **2** | **1** |
| 13 × 9 | 350 × 250 mm | 4 | 3 |

Un patrón más ancho cubre mejor los bordes del cuadro, que es donde más
distorsiona el lente. Pero **cada empalme es una oportunidad de que deje de ser
plano**, y un patrón chico perfectamente plano calibra mejor que uno grande
ondulado: la calibración supone que el patrón es un plano perfecto y cada
ondulación la interpreta como distorsión del lente.

Por eso el valor por defecto es el que consigue 350 mm de ancho con un solo
empalme, y el de una hoja queda como alternativa segura.

El PDF se escribe con biblioteca estándar —no hay ninguna librería de PDF
instalada y agregarla iría contra la regla de dependencias— y lleva impresa una
**regla de verificación de 100 mm**, más una página entera de instrucciones de
impresión y armado.

Esa regla no es un adorno: si la hoja se imprime al 97 % —que es lo que hace
"ajustar a la página" sin avisar—, la calibración queda escalada **en silencio**,
porque el patrón sigue siendo coherente consigo mismo y el error de reproyección
sale bajo igual.

### `calibrar_camara.py`

Mide la distorsión del lente y la deja guardada como perfil de cámara.

```bash
python -m vision.tools.calibrar_camara --camara "Logitech C270"   # capturar y calibrar
python -m vision.tools.calibrar_camara --verificar                # ver el antes y después
```

**`--camara NOMBRE` es lo que decide a qué archivo va el perfil.** La distorsión
es del aparato, no del sistema: cada cámara tiene el suyo en
`vision/calibraciones/`, y el nombre que se pase acá es el que lo bautiza
(`"Logitech C270"` → `logitech_c270.json`). Si se omite, la herramienta lo
pregunta. Sin esto, calibrar una segunda cámara pisaría el perfil de la primera.
El detalle de cómo se elige después está en
[`../geometry/README.md`](../geometry/README.md).

**Captura guiada, no "sacá 15 fotos".** Lleva la cuenta de **zonas del cuadro,
distancias e inclinaciones**, y captura sola cuando el patrón está quieto y
aporta algo que falta. La razón está medida: 8 vistas todas de frente dan un
error de 0,14 px —que parece excelente— pero recuperan la distancia focal con un
**20 % de desvío**. El número no delata la falta de variedad; el contador sí.

**Semáforo del error de reproyección**, con qué hacer en cada caso:

| Error | Veredicto |
|---|---|
| < 0,3 px | excelente, usar tal cual |
| < 0,5 px | cumple el objetivo |
| < 1,0 px | usable, conviene repetir |
| ≥ 1,0 px | no confiable, **no se guarda** salvo `--guardar-igual` |

**Verificación con los ojos** (`--verificar`): video en vivo lado a lado, crudo
contra corregido, con una rejilla de líneas perfectamente rectas superpuesta en
ambos. Apuntando al tablero, lo que se ve curvado a la izquierda tiene que verse
recto a la derecha. Cuando el patrón está a la vista agrega el número: *"curvatura
de las filas: 4,89 px → 0,001 px"*.

Esa comprobación visual existe porque el error de reproyección **puede mentir**:
con el patrón mal impreso el ajuste es coherente consigo mismo y el número sale
bajo igual. Mirar algo que uno sabe que es recto comprueba lo que el número no.

Cuando el perfil cargado **no le corresponde** a la cámara conectada, avisa en
pantalla. Ver [`../geometry/README.md`](../geometry/README.md).

### `precision_ubicacion.py`

Responde con un número la pregunta que decide la compra: **¿esta cámara ubica
los objetos con error aceptable?**

```bash
python -m vision.tools.precision_ubicacion --camara "Logitech C270"
python -m vision.tools.precision_ubicacion --comparar       # tabla de cámaras medidas
```

**Criterio: error máximo por debajo de 1 cm** en toda la cancha. No es
arbitrario: un cubo mide 6 cm, así que 1 cm de error mantiene el objetivo dentro
del cubo.

**Mide una DISTANCIA, no una posición.** Se apoya el marcador de prueba en un
punto A, se lo corre un número exacto de cuadros y se lo captura en B. Dos
motivos, y el segundo es el decisivo:

1. Medir una posición absoluta exigiría ubicar el origen —el centro del marcador
   ID 0— con precisión, y eso reintroduce el error manual que se quiere evitar.
   Un desplazamiento no necesita saber dónde está el origen: se cancela al restar.
2. **Neutraliza el paralaje por construcción.** Un objeto de altura `h` a
   distancia `d` del punto bajo la cámara se ve corrido a `d · H/(H−h)`: una
   multiplicación alrededor de ese punto. Las dos posiciones se escalan por el
   **mismo** factor, así que al restarlas el paralaje queda como un **error de
   escala puro**, calculable y descontable, en vez de un corrimiento que varía
   con la posición y sería inseparable del error de la cámara.

> Por eso esta prueba se salva de necesitar la corrección de paralaje. El
> sistema real **sí la necesita**, porque publica posiciones absolutas.

**La cuadrícula del tablero es la regla.** Cada cuadro mide exactamente 20 mm, así
que contar cuadros da una distancia exacta, sin lectura que interpretar. El único
error humano que queda es alinear el marcador a las líneas.

**Se mide sobre puntos internos**, nunca sobre los marcadores de esquina: esos
son los que el sistema usa para definir sus coordenadas, así que medir ahí sería
corregir con las propias respuestas —darían cero por construcción y no probarían
nada—. Recorre **cinco zonas** (centro y las cuatro esquinas de la cancha útil),
en horizontal y vertical.

Todo lo demás sale de `config_vision.json`, sección `precision`: el umbral, el ID
y tamaño del marcador de prueba, cuántos cuadros mover, cuántas muestras
promediar por punto, la altura de la cámara y el margen mínimo a los marcadores.

**El marcador de prueba** se imprime con
`patron_calibracion --marcador-prueba 20`, y va apoyado **plano** sobre el
tablero. Su altura entra en la configuración (`altura_marcador_mm`) porque de
ella sale el factor de paralaje que se descuenta.

#### `--comparar`: una fila por cámara

```
  cámara                 resolución    err. máx   err. med     ruido  veredicto
  ArgomTech CAM40        1920x1080      1.58 mm    0.75 mm   0.16 mm  SIRVE
  Logitech C270          1280x720       1.01 mm    0.47 mm   0.17 mm  SIRVE
```

Muestra la **última medición válida** de cada cámara, **no la mejor**: quedarse
con la mejor escondería una cámara que falla seguido. Las anteriores no se
borran; se ven con `--historial`.

Cada sesión guarda en `vision/mediciones/` **con qué cancha se midió**. Eso
permite marcar una sesión como obsoleta **por causa y no por antigüedad**: si
mañana se remonta la cancha con otras medidas, las mediciones viejas quedan
marcadas solas, sin depender de que alguien recuerde cuándo fue el cambio. Una
sesión sin ese dato dice *"cancha no registrada"* y **sigue contando**: no saber
con qué cancha se midió no es lo mismo que saber que está mal.

**Resultado sobre hardware real:** las dos cámaras medidas quedan muy por debajo
del criterio de 10 mm, así que la elección se puede hacer por disponibilidad y
precio y no por precisión.

### `panel.py`

El panel de información que las herramientas dibujan sobre el video. No es una
herramienta en sí: lo usan `diagnostico_camara`, `calibrar_camara` y
`precision_ubicacion`.

**Existe por los acentos.** `cv2.putText` usa las fuentes Hershey, que son ASCII
puro: escriben "exposición" como "exposici??n" **sin avisar**. El camino nativo
sería `cv2.freetype`, que no viene compilado en la rueda de
`opencv-contrib-python`. Por eso el panel dibuja con **Pillow**, que sí tiene
fuentes TrueType del sistema.

**Pillow es opcional.** Si no está instalado, el panel cae a `cv2.putText`
transliterando los acentos: se lee peor, pero la herramienta no se rompe.

Otras dos cosas que resuelve:

- **La tipografía se carga una vez** (`Tipografia`). El panel se dibuja en cada
  cuadro; abrir la fuente cada vez costaría más que dibujar y el visor perdería
  cuadros.
- **Se escala con la resolución** (`escala_para`). Un panel pensado para 1080p es
  ilegible a 480p y ridículo a 4K.

El estado se comunica **por color antes que por texto** —verde bien, rojo
problema, ámbar no se pudo determinar—: en una herramienta que se mira de reojo
mientras uno mueve la cámara, el color se lee de un vistazo y la palabra
después.

> La paleta de `panel.py` va en **RGB** (es lo que espera Pillow); lo que se
> dibuja con OpenCV directamente sobre el video va en **BGR**. Son espacios
> distintos y mezclarlos pinta los avisos de un color equivocado.

## Lo que todavía NO existe

Planificado, sin código aún:

- **Guía de alineamiento.** Ayudar a colocar la cámara en la posición correcta
  sobre la cancha, indicando en vivo qué corregir.
> **El monitor en vivo ya existe**, y no está acá: es
> [`vision/vista.py`](../vista.py), una ventana **del propio sistema**
> (`python -m vision.sistema --ventana`).
>
> No es una herramienta de `tools/` a propósito. Un monitor separado tendría que
> abrir la cámara —y una webcam solo se puede abrir una vez— o reimplementar la
> detección, y en los dos casos mostraría **su** interpretación en vez de la del
> sistema. Un monitor que puede discrepar de lo que se publica es peor que no
> tener monitor.
