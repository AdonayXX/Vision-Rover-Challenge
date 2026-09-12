# tracking/

**Productor.** Le da continuidad en el tiempo a lo que los detectores ven cuadro
por cuadro, y arma el **estado del mundo** que consumen `publish/` y `record/`.

## Estado: funcionando y verificado

Dos piezas: [`seguimiento.py`](seguimiento.py), que le da continuidad e identidad
a lo que los detectores ven cuadro por cuadro, y [`admision.py`](admision.py),
que decide cuándo una identidad de rover **nueva** entra al estado del mundo.

## Lo que existe

### Identidad entre cuadros

Un detector mira **un** cuadro y no sabe nada del anterior. Esta pieza es la que
sabe que el rover que aparece ahora es el mismo que estaba hace un instante un
poco más allá.

Para los rovers es directo, porque el ID de su marcador ArUco es su identidad.
Para los cubos también, porque el color los identifica y no hay dos iguales.

### Oclusión y edad — la regla que no se negocia

Cuando un objeto se tapa —un rover que pasa por encima de un cubo, un reflejo
sobre un marcador— **no desaparece del estado del mundo**. Se conserva su última
posición conocida y se le hace crecer un campo de **edad** (`age_ms`).

**Nunca** se hace parpadear un objeto entre existir y no existir. Un consumidor
no puede distinguir "se lo llevaron" de "no lo veo en este cuadro", así que
tendría que adivinar. Un dato viejo **marcado como viejo** siempre es mejor que
un agujero.

### El estado del mundo, inmutable

El resultado es una **foto completa de la cancha en un instante**, que no se
modifica: cada cuadro produce una nueva. Es lo único que cruza de los productores
a los consumidores, y por eso los dos lados pueden correr a ritmos distintos sin
pisarse.


---

## Acá no hay problema de asociación

Vale la pena decirlo primero, porque cambia el tamaño del problema: **cada objeto
de este reto trae su propia identidad**. El rover la trae en el ID de su marcador
ArUco; el cubo, en su color, y no hay dos del mismo.

O sea que no hay que adivinar **qué detección de este cuadro corresponde a cuál
del anterior** —el problema difícil de todo seguimiento, el que obliga a
predicciones, filtros de Kalman y algoritmos de asignación— porque la respuesta
viene escrita en el objeto.

Lo que queda es memoria y edad. Mucho más simple, y por eso mucho más confiable.

## Qué cuenta como "verlo de verdad"

| | Criterio |
|---|---|
| **Rover** | que se haya detectado su marcador. La detección de ArUco es binaria |
| **Cubo** | que se haya detectado **y que el ajuste sea confiable** |

La segunda fila es la que importa. Una detección de cubo marcada como no
confiable dice *"el cubo está por acá"* pero no *"el cubo está acá"*, así que
**no refresca la posición ni la edad**. Es el caso del rover empujando un cubo y
tapándole casi todo: se conserva la última posición buena y la edad crece, que es
exactamente lo que el contrato promete para un objeto ocluido.

Refrescar con esa detección sería publicar una posición que el propio sistema
considera dudosa, y encima presentarla como fresca.

## Admisión: una identidad nueva tiene que sostenerse

`admision.py` es lo último que decide si un **ID de rover que el seguimiento no
venía siguiendo** entra al estado del mundo: tiene que verse **5 cuadros
seguidos**, unos 166 ms.

El modo de falla que ataja es concreto y ya se vio de verdad. Un fantasma con el
ID de un rover hace dos cosas distintas:

| | Qué pasa | Quién lo resuelve |
|---|---|---|
| con el rover **presente** | colisiona con él: dos marcadores dicen ser el 10 | la resolución de duplicados, midiendo los dos |
| con el rover **ausente** | no colisiona con nadie: **inventa un rover** que se publica con edad cero, o sea presentado como fresco | **esto** |

**Solo se paga una vez**, al poner el robot en la cancha: un ID que ya está en la
memoria del seguimiento entra **de inmediato**, incluso después de una oclusión
larga —ya demostró que existe—, así que durante la ronda no cuesta nada. Y solo
afecta a los rovers: demorar un marcador de **esquina** demoraría el sistema de
coordenadas entero.

**Por qué existe si el filtro de tamaño ya mata el 100 % de los fantasmas
medidos.** Porque ese margen es una propiedad de **esta** escena, esta luz y esta
altura de cámara, no del sistema: el fantasma más grande medido está a factor
**1,9** del umbral, no a factor 10. Esta defensa no depende de ningún margen, sino
de que un fantasma no se sostenga —la racha más larga medida fue de **dos**
cuadros, igual en las dos sesiones guardadas (196 detecciones falsas) que en las
cuatro corridas completas (361)—. Es la red, no la defensa principal.

**Por qué cinco y no tres.** Porque los dos costos no se parecen. Subir el umbral
cuesta 66 ms más **una sola vez**; equivocarse cuesta hasta un **minuto**, porque
un fantasma admitido se vuelve **identidad seguida** y las detecciones siguientes
lo refrescan, así que el error se sostiene hasta que lo barre `edad_maxima_ms`.
Con esa asimetría, el margen sobre el peor caso medido no se elige apretado.

## El barrido no es para oclusiones

`edad_maxima_ms` saca de la lista lo que hace demasiado que no se ve. **No es
para manejar oclusiones** —para eso está la edad, y el contrato promete que un
objeto tapado no desaparece—: es para barrer **fantasmas**, una detección espuria
que nunca se repitió o un objeto que de verdad se fue de la cancha.

Sesenta segundos son generosos a propósito: una ronda dura minutos y una oclusión
normal dura segundos, así que una oclusión legítima nunca alcanza ese límite.

## Verificado

Con `python -m vision.tools.verificar_seguimiento`, que comprueba las cuatro
afirmaciones del contrato sobre oclusión, cada una sobre una secuencia de cuadros
generados y procesados de punta a punta:

| Escenario | Qué comprueba |
|---|---|
| El cubo verde deja de verse por completo | sigue en la lista, la posición no se mueve, la edad crece 50→300 ms y vuelve a 0 |
| Al rover 11 se le tapa el marcador | mismo trato que a un cubo |
| Un rover tapa el cubo hasta volverlo no confiable | la detección dudosa **no** refresca; la edad crece igual |

Se prueba con **cuadros** y no con detecciones escritas a mano a propósito: así
se ejercita el camino completo —detección, confiabilidad y memoria— en vez de
comprobar solo que un diccionario recuerda cosas.
