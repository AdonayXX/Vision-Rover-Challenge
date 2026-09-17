# Reparto inicial de los tres cubos

Avance posterior: [coordinación de reservas y estados de tareas](COORDINACION.md). Ya consume el plan inicial, pero todavía no está unida al transporte de radio ni al movimiento de los robots. La suite completa actual suma **93 pruebas**.

Ya comparamos dos estrategias con las mismas posiciones y el mismo modelo de costo. La salida es una **propuesta**, no una orden ni una reserva comunicada a los robots.

## Ejecutar sin hardware

Desde la raíz del repositorio:

```powershell
python -B base-robots/robots/pc/demo_asignacion.py --scenarios 200
```

Sólo usa Python y la biblioteca estándar. Para repetir otra muestra, cambiar `--seed`; para guardar el informe completo, añadir `--output informe_asignacion.json`. La cantidad admitida es de 1 a 10 000 escenarios. Azure no es necesario para este volumen.

La demostración genera centros de cubos separados y coloca ambos rovers junto al lado izquierdo. Usa tres destinos por color y dimensiones del mensaje. Los escenarios son aptos para comparar costos numéricos; no certifican acceso físico ni transporte.

## Las dos estrategias

### Cercano

1. El robot de menor ID escoge el cubo disponible más cercano a su posición.
2. El otro escoge el más cercano entre los restantes.
3. El tercero se asigna al que, según el modelo, termine antes la primera entrega; en empate se elige el menor ID.

Es un reparto simulado de eventos. No detecta entregas reales ni implementa todavía un protocolo de acuerdos.

### Equilibrado

Compara las seis permutaciones de colores, con dos formas de dividir cada orden entre los robots: **12 repartos ordenados**. Se exige al menos una tarea por robot porque estamos comparando el reparto inicial de tres cubos con participación de ambos.

Elige, en este orden:

1. Menor carga del robot que más recorrido acumula.
2. Menor distancia total de ambos.
3. Un desempate fijo por orden de colores.

Los IDs se ordenan explícitamente. Dos clientes con la misma lectura producen la misma propuesta aunque intercambien su ID propio y el del compañero. Esto **no sustituye un acuerdo entre rovers**: pueden recibir lecturas diferentes o estar ejecutando tareas distintas.

## Qué significa el costo

Para cada tarea:

```text
costo = distancia recta desde la posición prevista del rover al cubo
      + distancia recta desde el cubo al centro de su destino
```

Después de esa entrega, el modelo coloca al rover en el centro del destino para calcular la siguiente aproximación. Suma las tareas asignadas a cada rover. La métrica principal es el máximo de esas dos sumas: `carga_maxima_mm`.

Con la misma velocidad constante para todos los tramos y sin esperas, minimizar esa carga equivale a minimizar el tiempo del último robot. **Esas hipótesis no están verificadas físicamente**, por eso el programa reporta milímetros y no segundos.

No se incluyen giros, rutas alrededor de obstáculos, posición de las paletas, maniobras para colocarse detrás del cubo, velocidad de empuje, fricción, cruces, frenado ni errores. El radio real y las zonas de entrega pueden hacer inviable un reparto que este modelo valora bien. El planificador de [RUTAS.md](RUTAS.md) todavía no está conectado a estos costos; además evita todos los cubos y no resuelve el transporte.

## Resultados medidos en esta entrega

200 escenarios, semilla `20260915`:

| Medida | Resultado |
|---|---:|
| Carga máxima media, estrategia cercana | 1350.61 mm |
| Carga máxima media, estrategia equilibrada | 1252.95 mm |
| Escenarios con reducción | 125 |
| Escenarios empatados | 75 |
| Media de la reducción porcentual calculada por escenario | 6.67 % |

La media de porcentajes por escenario no es el porcentaje de diferencia entre las dos medias de distancia. El programa informa ambas cantidades sin mezclarlas.

El primer escenario empata: rover 10 lleva azul y rover 11 lleva rojo y luego verde, con cargas estimadas de 941.2 y 1208.8 mm. La demostración muestra el primer escenario, no elige sólo un caso favorable.

La estrategia equilibrada no puede ser peor bajo este mismo objetivo porque busca el mínimo entre los 12 repartos y el reparto cercano está entre ellos. La comparación cuantifica cuánto se gana respecto a esa referencia; **no demuestra superioridad con rutas reales, éxito de entregas ni ventajas de IA**. Aún no estamos entrenando un modelo.

## Datos y límites operativos

- Se consulta la fase y la frescura de ambos rovers y los tres cubos. Se exige RUNNING.
- Se rechazan destinos ausentes o fuera de los límites de la cancha.
- Se devuelve `seq` para identificar la observación y `rutas_verificadas: false` para explicitar el alcance.
- La unidad se obtiene de `grid.cell_mm`; los costos escalan con ella.
- Es un **reparto inicial**: no admite tareas ya entregadas o en curso. No debe ejecutarse continuamente como si cada lectura iniciara una misión nueva.
- No registra reservas ni confirma órdenes. Durante competencia, esta lógica y los acuerdos deben ejecutarse en los rovers; la herramienta de PC es de desarrollo.

## Código y pruebas

- [asignacion.py](codigos/asignacion.py): cálculo de propuestas sobre la telemetría.
- [demo_asignacion.py](pc/demo_asignacion.py): generación y comparación reproducible.
- [test_asignacion.py](tests/test_asignacion.py): 10 pruebas nuevas.

La suite completa tiene **77 pruebas pasando**. Las nuevas comprueban que cada cubo aparece una vez, que ambos rovers participan, costos con soluciones calculables a mano, posición inicial de la siguiente tarea, empate del tercero, orden de IDs, cambio de escala, datos viejos, fase, desconexión y reproducibilidad.

```powershell
python -B -m unittest discover -s base-robots/robots/tests -v
```

## Qué sigue

Antes de usarlo para dirigir los robots, falta incorporar estados de tarea (libre, reservada, en ejecución, entregada), acuerdos de asignación y un modelo de aproximación/transporte que permita descartar repartos inviables. Después podremos comparar tiempos de misión simulados y, finalmente, contrastarlos con hardware.
