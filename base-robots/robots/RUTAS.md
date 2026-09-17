# Caminos libres para el rover

Se agregó un planificador de rutas estáticas. Recibe la telemetría y un destino, y devuelve una secuencia de puntos libres o ESPERAR con el motivo. No controla motores ni coordina los movimientos simultáneos de dos robots.

## Probar sin hardware

Desde la raíz del repositorio:

```powershell
python -B base-robots/robots/pc/demo_rutas.py
```

Sólo requiere Python y su biblioteca estándar. El escenario numérico tiene dos rovers y tres cubos. La demostración:

1. Encuentra un desvío alrededor del cubo rojo: **667.8 mm**, frente a una recta de 580 mm que está bloqueada.
2. Coloca al compañero en un punto de la ruta. Con los tamaños del ejemplo se cierra el paso y el resultado cambia a **ESPERAR**.
3. Rechaza un destino dentro de un cubo.
4. Exige esperar si la posición de un cubo está vieja.

La ruta inicial es `(7,21) → (20,29) → (22,29) → (36,21)`, en celdas. Son resultados geométricos de este escenario, no distancias medidas sobre hardware. El ensayo no mueve motores ni representa el empuje de cubos.

## Cómo considera el tamaño

Los valores de [rutas.example.json](pc/rutas.example.json) son **supuestos de simulación**, pendientes de medición:

| Parámetro | Ejemplo | Significado |
|---|---|---|
| `robot_radius_mm` | 85 mm | Radio del círculo que debe contener todo el robot, incluidas paletas |
| `peer_radius_mm` | 85 mm | Radio equivalente del compañero |
| `clearance_mm` | 15 mm | Separación adicional respecto a bordes y objetos |
| `obstacle_side_mm` | 100 mm | Lado supuesto de obstáculos cuadrados, si aparecen |
| `step_cells` | 1 | Separación entre puntos de la grilla de búsqueda |
| `max_nodes` | 4096 | Máximo de puntos candidatos en esa grilla |
| `required_colors` | rojo, verde, azul | Cubos que deben estar presentes antes de planificar |

En el ejemplo, el centro del rover debe permanecer a 100 mm de los bordes. Para evitar un objeto se suma su radio al radio del rover y al margen. Los cubos y obstáculos cuadrados se cubren con su media diagonal: así el cálculo es conservador ante su rotación.

**Hay que medir el robot completo antes de elegir su radio.** No basta la mitad del ancho si las paletas o las esquinas sobresalen. Con los supuestos de este ejemplo, algunas posiciones de salida de la configuración original no tienen suficiente separación: el planificador indicará `origen_sin_espacio`. Eso significa revisar dimensiones y montaje; no reducir el radio para forzar una ruta.

## Algoritmo y resultado

1. Exige RUNNING y datos recientes de rovers, cubos requeridos y obstáculos publicados.
2. Comprueba que origen y destino tengan espacio para el cuerpo del robot.
3. Si la línea directa está libre, la utiliza.
4. Si está bloqueada, busca con A* sobre una grilla: explora primero los puntos con menor recorrido acumulado más distancia estimada al destino.
5. Comprueba **cada tramo completo**, incluidas diagonales y conexiones a coordenadas decimales. No redondea el origen al otro lado de un obstáculo.
6. Elimina puntos intermedios únicamente si el atajo completo también está libre.
7. Vuelve a comprobar la frescura antes de devolver la ruta.

El resultado incluye `estado`, `motivo`, `puntos`, `distancia_mm`, `seq` y el alcance `estatica_con_tamanos_configurados`. `seq` indica la observación usada. La longitud es la del recorrido del centro del robot y no estima el tiempo de ejecución.

`sin_ruta_en_la_grilla` significa que no se encontró un camino a esa resolución; puede existir un paso más fino que la grilla no represente. No es una prueba de imposibilidad geométrica absoluta. `grilla_supera_limite_de_nodos` exige un paso más grande o un límite adecuado; evita intentar una búsqueda desmesurada. El planificador está probado en PC y todavía no tiene una garantía de tiempo de cálculo o memoria en IdeaBoard.

## Ver rutas con el publicador simulado

Arrancar el simulador como indica [PRUEBAS_PC.md](PRUEBAS_PC.md). En otra terminal, desde la raíz del repositorio:

```powershell
python -B base-robots/robots/pc/cliente_vision.py --target-col 36 --target-row 21 --route-config base-robots/robots/pc/rutas.example.json
```

El monitor muestra una ruta o la causa de espera aproximadamente una vez por segundo, y al cambiar el estado de los datos. No envía órdenes al simulador. Sus movimientos preexistentes son independientes de estas rutas.

## Qué queda resuelto y qué falta

Ya se comprueba un camino para **objetos inmóviles en una observación**, considerando sus tamaños configurados. El compañero es un obstáculo en su posición observada. Una ruta deja de servir si se mueve un objeto, pasa demasiado tiempo o cambian las dimensiones.

Para seguirla de verdad falta:

- Revalidar el próximo tramo con cada observación nueva, cancelar maniobras y volver a planificar.
- Coordinar prioridades o reservas de paso entre los dos robots; no basta con tratar al compañero como un objeto inmóvil.
- Conectar los puntos de la ruta al controlador de giros/avances, considerando tolerancias, distancia de frenado, desvíos y señales de sensores.
- Adaptar y medir ejecución/memoria en CircuitPython.
- Planificar aproximación y empuje de cubos. El planificador actual **evita todos los cubos** y no permite usar su centro como destino de navegación ordinaria.

Se bloquea la planificación si falta un cubo requerido o una entidad publicada está vieja. Esto no descubre obstáculos que la cámara nunca detectó: en la edición copiada, `obstacles` llega vacío. El soporte geométrico para obstáculos está implementado y probado con mensajes construidos, pero su detección real sigue pendiente si nuestra variante los necesita.

## Verificación

**67 pruebas pasan**: las 52 anteriores y 15 nuevas. Se comprueban desvíos, caminos directos, compañero en el paso, coordenadas decimales, destinos ocupados, bordes, falta de datos, paredes sin paso, tangencias, obstáculos, límites de búsqueda y cambios del escenario. Además del cálculo analítico, las rutas devueltas se muestrean independientemente para comprobar separación de los objetos.

```powershell
python -B -m unittest discover -s base-robots/robots/tests -v
```

Código: [rutas.py](codigos/rutas.py), [demostración](pc/demo_rutas.py) y [pruebas](tests/test_rutas.py).
