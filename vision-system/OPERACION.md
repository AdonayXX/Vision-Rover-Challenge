# Operar una ronda

Esta guía es para quien **corre el sistema durante una ronda**. Armar la cancha
está en [`MONTAJE.md`](MONTAJE.md); dejar la cámara fina, en
[`PUESTA_A_PUNTO.md`](PUESTA_A_PUNTO.md). Acá se da por hecho que la cancha está
montada y la cámara calibrada.

Lo que hay que entender antes de empezar: **la visión no solo mira, arbitra**.
Lleva el cronómetro oficial, arranca la ronda sola y la cierra sola. Quien opera
prepara y, si hace falta, interrumpe; no arranca ni cronometra.

---

## 1. El ciclo de una ronda

| Fase | Qué significa | Qué cuenta el reloj |
|---|---|---|
| `IDLE` | Sistema encendido, ronda no preparada. | nada |
| `READY` | Preparación en curso. | cuánto falta para que empiece |
| `RUNNING` | Ronda en juego. | cuánto queda |
| `FINISHED` | Ronda terminada. | se detiene con lo que tardó |

```
IDLE ──ready──▶ READY ───el reloj───▶ RUNNING ───el reloj───▶ FINISHED
                  │                       │
                  └──abort──▶ IDLE        └──stop──▶ FINISHED

FINISHED ──ready──▶ READY          FINISHED ──abort──▶ IDLE
```

**Las dos transiciones del medio las hace el reloj, no vos.** De `READY` a
`RUNNING` pasa al agotarse la preparación, y no hay forma de adelantarlo: ahí
vive la igualdad de tiempo de preparación entre equipos.

Los tiempos se declaran en `vision/config_vision.json`, bloque `ronda`: un minuto
de preparación y diez de ronda. Para probar sin esperar once minutos, se bajan
ahí; para eso están declarados.

---

## 2. Los comandos

Se escriben en la terminal donde corre el sistema, o se aprietan como tecla si
está abierta la ventana con `--ventana`.

| Comando | Tecla | Desde | Deja la ronda en |
|---|---|---|---|
| `ready` | `r` | `IDLE` o `FINISHED` | `READY` — arranca la preparación |
| `stop` | `f` | `RUNNING` | `FINISHED` — cierra antes de tiempo |
| `abort` | `a` | `READY` o `FINISHED` | `IDLE` — cancela y vuelve al principio |
| `quit` | `q` o `ESC` | cualquiera | apaga el sistema |

**No hay comando para arrancar la ronda.** Si escribís `start`, el sistema
contesta por qué no existe.

**`ready` no se acepta desde `READY`.** Con cuenta regresiva en marcha, volver a
apretarlo la reiniciaría: sería estirar la preparación apretando una tecla. Para
rehacerla hay que abortar a `IDLE` y volver a entrar, que deja rastro en el acta.

---

## 3. El cronómetro

Se mide con **reloj monótono**, no con el de pared. Un ajuste de hora del sistema
—o un servidor de tiempo corrigiendo la máquina en mitad de una ronda— no puede
alterar un tiempo de competencia. La fecha del acta sí sale del reloj de pared,
porque un tiempo monótono no sirve para fechar nada: son dos relojes con dos
trabajos distintos.

### No se pausa nunca

Si el sistema pierde de vista la cancha en medio de la ronda, **el cronómetro
sigue corriendo**. No es un descuido:

1. Es lo justo. La ronda dura lo que dura; que el sistema tenga un problema de
   visión no le regala segundos a nadie.
2. Pausarlo sería **explotable**: tapar un marcador daría tiempo extra.

Lo mismo vale para la preparación. Si al llegar a cero no hay coordenadas, la
ronda **no arranca** —espera a que vuelvan— pero el tiempo de preparación ya se
consumió. Nadie gana preparación tapando la cancha; solo demora el arranque para
todos por igual.

---

## 4. Las dos guardas: sin ver la cancha no se arbitra

El sistema **se niega a preparar una ronda** en dos casos:

| Guarda | Qué pasa | Qué hacer |
|---|---|---|
| **No hay coordenadas** | no se ven los cuatro marcadores de esquina, ni tres con la geometría conservada | destapar los marcadores, revisar la luz, mirar que la cámara no se haya movido |
| **El perfil de cámara deforma** | el perfil cargado no corresponde a la cámara conectada | elegir el perfil correcto, o calibrar esta cámara (ver `PUESTA_A_PUNTO.md`) |

En los dos casos el sistema **sigue publicando telemetría**: como observador
funciona, como árbitro no. Es la regla de los dos oficios de `CLAUDE.md`: lo que
para observar es desaconsejable, para arbitrar es impedimento.

La misma guarda vale para el arranque automático. Sin esto, la preparación podía
terminar con la geometría perdida y la ronda arrancaba a ciegas sin que nadie
tocara nada.

### Si se pierde la cancha **durante** la ronda

Más de **2 segundos seguidos** sin coordenadas y la ronda se cierra con motivo
`geometria_perdida`. Se mide ceguera **continua**, no acumulada: cualquier cuadro
bueno reinicia la cuenta. Ver tres marcadores con la homografía conservada **no**
cuenta como pérdida.

Mientras dura el apagón, el panel lo muestra en rojo con **cuánto falta para que
la ronda se cierre**. Ese es el tiempo que hay para destapar un marcador.

---

## 5. Por qué puede terminar una ronda

| Motivo | Quién lo dispara |
|---|---|
| `reto_cumplido` | el reloj, cuando todos los cubos en juego quedan en posición |
| `tiempo_agotado` | el reloj, al acabarse la ronda |
| `geometria_perdida` | el reloj, tras 2 s sin ver la cancha |
| `detenida_por_operador` | una persona, con `stop` |
| `abortada_en_preparacion` | una persona, con `abort` durante `READY` |

**El tiempo del reto se toma en la ENTRADA del último cubo**, no cuando el
sistema termina de confirmarlo. El contador exige que un cubo se sostenga dentro
un segundo antes de darlo por entregado —si no, la cuenta titilaría con el cubo
parado justo en el borde— pero ese segundo **no se le cobra a nadie**.

Dos casos en que la cuenta está completa y la ronda **no** se cierra:

- **no se ven las coordenadas en ese instante.** No se certifica lo que no se
  está viendo.
- **el reto nunca se vio incompleto durante la ronda.** Es el caso de la cancha
  que quedó armada de la vuelta anterior: si los cubos ya estaban puestos al
  arrancar, cumplirlos no es cumplir nada.

En `READY`, si algún cubo ya está dentro de su zona, el panel lo grita en rojo:
**`CUBOS YA EN ZONA`**. Es el único momento en que todavía se puede corregir.

### El rectángulo interior de cada zona

Dentro de cada zona, la ventana dibuja un rectángulo más chico: es **donde tiene
que caer el centro del cubo** para que el árbitro lo cuente. Sale de restarle a
la zona la media diagonal del cubo —lo que garantiza que entra entero, esté
girado como esté— y de devolverle **2,5 mm por lado** de tolerancia, que es la
holgura del árbitro frente al error de ubicación. La tolerancia está en
`vision/config_vision.json`, `conteo_acopio.tolerancia_mm`.

Cuando un cubo se sostiene un segundo ahí adentro, la zona se pinta plena y el
mensaje a los equipos lleva `in_depot: true` para ese cubo. **Los rovers reciben
el mismo veredicto que se ve en pantalla.**

### A qué hora entró cada cubo

Debajo de la cuenta de acopio, el panel muestra **una fila por zona** con el
estado de su cubo, y la etiqueta de la zona sobre el video dice lo mismo:

| Fila | Qué significa |
|---|---|
| `entró a 1:23 · hace 12.4 s` | entró al minuto 1:23 del cronómetro y lleva 12,4 s adentro |
| `dentro hace 12.4 s` | está adentro, pero no entró durante esta ronda: ya estaba al arrancar, o no hay ronda |
| `afuera` / `sin cubo` | no está en su zona, o no se lo ve |

**La hora es la de la estadía actual, no la de la primera vez.** Si el cubo
sale de la zona por el motivo que sea —un rover lo saca, o titila en el borde—
la hora se borra en ese mismo cuadro y vuelve a cero; al volver a entrar se toma
de nuevo. Al preparar otra ronda se vacían las de la anterior. El acta guarda
esa misma hora por cubo, en `entro_en_ronda`.

---

## 6. El acta

Cada ronda cerrada escribe un archivo en **`vision/actas/`**, con nombre
`acta_AAAAMMDD_HHMMSS.json`. **Sin acta hay un cronómetro en pantalla y nada que
revisar** cuando un equipo reclame.

Qué trae:

- **cuándo** fue, en hora de pared, y el **motivo** del cierre;
- el **tiempo final**, en milisegundos y en `m:ss`;
- **cuántos cubos** quedaron en posición y **cuáles**, con su veredicto, cuánto
  le faltaba a cada uno y la **edad** del dato sobre el que se decidió;
- las **posiciones finales** de rovers y cubos;
- **con qué perfil de cámara** se juzgó;
- cuántas veces se perdió la cancha de vista y **cuánto duró la peor**, aunque la
  ronda haya terminado bien: una con tres apagones de 1,8 s es una que el árbitro
  vio a medias;
- si el **arranque fue irregular** —cubos ya en zona al empezar— y cuáles.

Dos reglas del acta:

- **Una ronda sin geometría no genera acta.** Si el sistema nunca llegó a ver la
  cancha, no hay nada que certificar, y un documento que parece válido y no lo es
  es peor que no tener documento.
- **Las rondas sintéticas salen marcadas** con `NO_ES_UNA_RONDA_REAL` en el nivel
  de arriba: tienen la misma forma que una de verdad.

Las actas **no se versionan** —son datos de una ronda concreta y se acumulan
cientos—. Si alguna hay que conservar, se archiva a mano.

---

## 7. Cuando algo no sale

| Qué ves | Qué pasa |
|---|---|
| Apretás `r` y no pasa nada | una de las dos guardas. El panel dice cuál: *"no se ven los marcadores de esquina"* o *"el perfil de cámara deforma la imagen"* |
| La preparación llegó a `0:00` y no arranca | no hay coordenadas. Vuelve a arrancar sola en cuanto se vean; el tiempo consumido no se devuelve |
| La ronda se cerró sola antes de tiempo | mirá el motivo en el acta: `geometria_perdida` si se perdió la cancha, `reto_cumplido` si se completó |
| `SIN COORDENADAS` en rojo durante la ronda | tenés los segundos que marca el panel para destapar un marcador |
| Terminó y no hay acta | la ronda nunca tuvo geometría. El sistema lo dice en consola al cerrar |

---

## Si la sala tiene mucha luz

La exposición de la cámara es **fija** y está declarada en
`vision/config_vision.json`. Ese número se midió con una luz: en una sala más
luminosa quema la imagen, y los cubos de acrílico —que reflejan— pierden el color
justo en la tapa, que es casi todo lo que la cámara ve de ellos. El síntoma es un
cubo que no aparece, o que queda en ámbar con la edad creciendo.

**El detector se adapta solo a la luz**, hasta donde la imagen lo permite: el
umbral de color se calcula en cada cuadro contra el propio tablero, y el tinte de
la luz se le resta al cuadro. Un cubo más oscuro, más claro o con la tapa lavada
por un reflejo se sigue encontrando. Lo que no tiene arreglo por programa es un
cubo **quemado**: si el sensor llegó al tope, el color no está en la imagen. Para
eso está la exposición.

### Calibrar los colores al arrancar

Si con la luz de la sala algún cubo no se reconoce, el sistema puede **aprender
los colores mirando los cubos**. Al arrancar, después de la cámara y el perfil,
pregunta:

```
  ¿Calibrar los colores ahora? [s/N]:
```

Antes de contestar `s`, poné **los tres cubos dentro de la cancha**, separados
entre sí y sin el rover encima. El sistema los mira tres segundos, mide el tono
de cada uno con esa luz y lo usa durante toda la corrida. Muestra lo que midió:

```
  ✓ Colores calibrados con esta luz (89 cuadros):
      red    matiz  34.6°  (el del archivo era  39.9°, -5°)
      green  matiz 143.7°  (el del archivo era 136.0°, +8°)
      blue   matiz 287.9°  (el del archivo era 306.2°, -18°)
```

| | |
|---|---|
| **Enter** | no calibra: se usan los colores del archivo de configuración |
| **Vale para esa corrida** | no se guarda. La luz cambia a lo largo del día, y un color aprendido a la mañana sería a la tarde un número viejo |
| **Se niega si no está seguro** | si no hay exactamente un cubo de cada color a la vista, o si los tonos están tan corridos que no se puede saber cuál es cuál. En ese caso deja los colores del archivo y lo dice |
| **Sin preguntar** | `--calibrar-colores` calibra directo, para arrancar sin nadie delante |

Conviene calibrar **después** de elegir la exposición: primero que la imagen no
esté quemada, después los colores.

### Elegir la exposición al arrancar

Al arrancar, el sistema **pregunta la exposición**
junto con la cámara y el perfil. Enter deja la del archivo; un número la cambia
para esa corrida, sin editar nada. Para no contestar cada vez, o para arrancar
sin nadie delante, el mismo valor se pasa como opción:

```bash
.venv/bin/python -m vision.sistema --ventana --exposicion -8
```

**Más negativo es menos luz.** Con `-6` en el archivo, probá `-7` y `-8`. Al
arrancar, el sistema dice si la cámara **aceptó** el valor: pedirlo no es lo
mismo que tenerlo. Sigue siendo exposición fija; esto elige cuál, no la vuelve
automática.

Para elegir el valor con números y no a ojo, la misma opción existe en el
diagnóstico de cubos, que dice cuánto de la cancha está quemado:

```bash
.venv/bin/python -m vision.tools.diagnostico_cubos --exposicion -8
```

Cuando un valor resulte bueno para la sala de competencia, se escribe en el
archivo de configuración de **esa** máquina.

---

## Dos cosas que el sistema no deja hacer, a propósito

- **Arrancar en `RUNNING`.** `--fase` solo acepta `IDLE` y `READY`. Una ronda sin
  preparación y sin cronómetro desde cero parece válida y no lo es.
- **Saltear la guarda con `--fase READY`.** No entra en `READY` de una: queda
  como **intención** y se cumple en cuanto haya coordenadas, por la misma puerta
  que la tecla `r`.

---

## Para entender más

- [`MONTAJE.md`](MONTAJE.md) — armar la cancha y pegar los marcadores.
- [`PUESTA_A_PUNTO.md`](PUESTA_A_PUNTO.md) — calibrar la cámara y medir la
  precisión.
- [`contrato/CONTRATO.md`](contrato/CONTRATO.md) — qué reciben los equipos.
- `python -m vision.tools.verificar_config` — revisa la configuración declarada y
  muestra los dos tiempos de la ronda antes de competir.
- `python -m vision.tools.verificar_ronda` — verifica el árbitro: transiciones,
  cronómetro, guardas y acta.
