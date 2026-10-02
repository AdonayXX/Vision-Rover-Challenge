# reglas/

**Lo que el sistema decide**, a partir del estado del mundo que producen los
detectores y el seguimiento.

Está separado de [`../detectors/`](../detectors/README.md) por la misma razón
que el proyecto separa siempre **detectar** de **decidir**: son dos trabajos
distintos y, sobre todo, se equivocan de formas distintas. Un detector falla por
la luz, un reflejo o una oclusión; una regla falla por el criterio. Mezclados,
no hay forma de saber cuál de los dos anduvo mal.

## Lo que existe

### `acopio.py` — cuántos cubos están en posición

Aplica la regla de entrega del reglamento: un cubo está entregado cuando queda
**completamente dentro** de la zona de acopio de su color.

| Hace | No hace |
|---|---|
| Evaluar cada cubo contra su zona | **Dibujar** — eso es de [`../vista.py`](../vista.py) |
| Llevar la memoria entre cuadros | **Publicar** — entrega su veredicto, y es el bucle del sistema quien lo pone en el mensaje |
| Exponer la cuenta y el detalle por color | **Cerrar la ronda** — eso lo decide el árbitro, que es quien lleva el cronómetro |

## La geometría sale del contrato; el veredicto se publica

La cuenta de "cubo dentro de la zona" es la de
[`contrato/schema.py`](../../contrato/CONTRATO.md). El árbitro la usa con la
ventana agrandada **2,5 mm por lado** (`conteo_acopio.tolerancia_mm`): el margen
conservador de media diagonal supone el peor giro del cubo, y un cubo bien
puesto podía quedar afuera por el error de ubicación.

Esa tolerancia no viaja en el mensaje, así que el rover no podría reproducir la
cuenta. Por eso desde el protocolo v3 **el veredicto viaja**: cada cubo lleva
`in_depot`, que es el `contado` de este paquete —adentro y con la permanencia
cumplida—. El rover lo lee y dice lo mismo que el árbitro sin calcular nada.

El simulador del contrato hace de árbitro para quien desarrolla sin cancha, con
la misma tolerancia y la misma permanencia.

Lo que vive acá es la **memoria entre cuadros**, que es justamente lo que el
contrato no puede tener: él ve un cubo y una zona, no una secuencia.

## Por qué hay una permanencia mínima

El conteo es **en vivo**: cuenta los que están adentro **ahora**. Si un rover
saca un cubo, la cuenta baja.

El problema es un cubo dejado **justo en el borde del criterio**: ahí entra y
sale del veredicto con el puro temblor de la detección, y sin permanencia el
número saltaría entre 2 y 3 varias veces por segundo, que en pantalla **se lee
como un sistema roto**.

No es hipotético. Con el fondo de zona de 100 mm que tuvo la primera versión, la
ventana sobre ese eje medía 15,2 mm y en la cancha real un cubo bien puesto
oscilaba entre 5 y 10 mm afuera del límite, cuadro a cuadro. Hoy la zona es de
150 mm y la ventana de **65,1 mm**, así que el caso es mucho más raro —pero la
permanencia se queda: un cubo se puede dejar al borde de cualquier ventana.

**La permanencia solo demora entrar, nunca salir.** Demorar la salida sería peor
que el titileo: diría que un cubo está entregado cuando un rover ya se lo llevó.

Es un milisegundaje de presentación, no un filtro de calidad: una detección
dudosa ya la filtró el seguimiento antes, conservando la última posición buena.
El valor está en `conteo_acopio.permanencia_minima_ms`.

## Un cubo tapado sigue contando

Es deliberado, y es la regla de oclusión del contrato aplicada al conteo. El
seguimiento conserva la última posición buena de un objeto tapado, así que un
cubo que ya estaba adentro y queda oculto por el rover que acaba de entregarlo
**sigue contado**.

Lo contrario sería que el contador se cayera justo en el momento de la entrega,
que es exactamente cuando hay un rover encima del cubo.

Como ese veredicto se sostiene sobre una posición **conservada** y no sobre una
observación fresca, `EstadoZona` expone la **edad** del cubo y la vista la
muestra cuando pasa a ser vieja. Quien mira la pantalla tiene que poder saber
sobre qué se apoya lo que está viendo.

## A qué hora entró cada cubo

Además de cuánto hace que está adentro, el contador recuerda **en qué instante
del cronómetro oficial entró** cada cubo. Es lo que quien mira la pantalla
quiere saber —"el verde entró a 1:23"— y lo que un equipo pregunta después.

| Regla | |
|---|---|
| Se toma **al entrar** | no cuando se cumple la permanencia, por lo mismo que el cierre de la ronda |
| Vive **solo mientras el cubo sigue adentro** | si sale, por el motivo que sea —un rover lo saca, titila en el borde, deja de verse—, se borra en ese cuadro |
| Se **vuelve a tomar** al reingresar | con la hora de esa nueva entrada. No hay "primera entrada" que sobreviva a una salida |
| Solo existe si entró **durante la ronda** | un cubo que ya estaba puesto al arrancar, o que entra en `IDLE` o `READY`, no tiene hora |
| Se **vacía al preparar otra ronda** | para que un cubo que quedó puesto no muestre la hora de la vuelta pasada |

Viaja en `EstadoZona.entro_en_ronda_ms`. La vista la muestra en el panel y en la
etiqueta de la zona, y el acta la guarda. **No se publica**: lo único del conteo
que viaja en el mensaje es el veredicto de cada cubo, `in_depot`.

## Verificado

Con `python -m vision.tools.verificar_acopio`, en cinco bloques:

| Bloque | Qué comprueba |
|---|---|
| **El criterio, sin imágenes** | que el límite de la ventana esté donde dice, y que con el centro del cubo en ese límite el cubo entre entero **girado como esté** (0° a 90°, cuatro bordes, tres zonas) |
| **El recorrido** | que una sola llamada evalúe las tres zonas, cuenten o no cuenten |
| **La hora de entrada** | un cubo seguido por una ronda inventada: entra, sale, vuelve, desaparece, termina la ronda y se prepara otra |
| **La tolerancia y el veredicto** | que la ventana del árbitro crezca 2,5 mm por lado, y que `in_depot` salga recién con la permanencia cumplida y caiga en el cuadro en que el cubo sale |
| **El sistema entero** | cubos en el centro, justo adentro, justo afuera y girados 45°, procesando el cuadro completo en los dos modos de cámara |

Cada veredicto positivo se contrasta además **contra la verdad del generador**:
que el cubo dado por entregado esté de verdad entero dentro del rectángulo.

El antirrebote se verifica aparte, con estados escritos a mano: un cubo que
entra y no se sostiene no cuenta, uno que se sostiene cuenta, uno que sale
descuenta de inmediato, y uno tapado sigue contando con su edad creciendo.

## Este paquete cuenta; el árbitro decide

Cuando todos los cubos en juego están en posición, la imagen lo anuncia y el
contador **se lo informa al árbitro**, que cierra la ronda con motivo
`reto_cumplido`. La frontera no desapareció: se movió. Acá se cuenta y se dice
**desde cuándo**; quién termina la ronda es una sola voz, la de
[`../sistema.py`](../sistema.py), que es la que lleva el cronómetro.

Lo que se le informa es el instante de la **entrada** del último cubo, no el del
cumplimiento de la permanencia mínima. El contador exige un segundo sostenido
para no titilar, y cobrárselo a todos los equipos sería descalibrar el reloj.

Dos cosas que el árbitro **no** da por cumplidas aunque la cuenta esté completa:
si en ese instante no se ven las coordenadas —no se certifica lo que no se está
viendo— y si el reto nunca se vio incompleto durante la ronda, que es el caso de
una cancha que quedó armada de la vuelta anterior.

El conteo tampoco viaja en el mensaje: es para la pantalla y para el acta.
