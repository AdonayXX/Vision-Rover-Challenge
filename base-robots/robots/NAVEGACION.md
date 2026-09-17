# Distancia, orientación y decisiones hacia un punto

Avance posterior: ya hay un [planificador de rutas estáticas](RUTAS.md) que comprueba el espacio del robot y rodea objetos. La suite completa suma ahora **67 pruebas**. Las funciones de este documento siguen siendo recomendaciones geométricas; todavía no se integraron con un ejecutor de rutas en motores.

Ya podemos calcular cuánto falta para llegar a una coordenada y cuánto debe girar el rover desde su orientación observada. El código recomienda una acción; no ejecuta motores ni garantiza que el camino esté libre.

## Demostración sin hardware

Desde la raíz del repositorio:

```powershell
python -B base-robots/robots/pc/demo_navegacion.py
```

La demostración usa las posiciones y dimensiones de la configuración copiada, genera mensajes de telemetría v2 y pasa por nuestro cliente de datos. El movimiento se calcula con un modelo ideal: hasta diez grados por giro y medio cuadro por avance. No usa cámara, motores ni una conexión de red. La prueba TCP con el publicador oficial sigue disponible por separado en [PRUEBAS_PC.md](PRUEBAS_PC.md).

Resultado verificado con la configuración actual:

- Inicio en `(4, 17.5)`, rumbo `0°`; objetivo `(15, 10)`.
- Distancia inicial: **266.3 mm**; giro inicial: **+34.3°**, antihorario.
- Alterna GIRAR y AVANZAR según cada observación.
- Inyecta una captura vieja: responde ESPERAR y continúa sólo con una nueva válida.
- Termina dentro de la tolerancia de 20 mm: error numérico final **16.402 mm**, en 31 iteraciones.

Ese error corresponde únicamente al modelo ideal. No mide precisión física, tiempo real de recorrido ni transporte de cubos. Las posiciones publicadas se actualizan según la acción recomendada y el rumbo actual; el modelo no teletransporta el robot al destino.

## Qué decide

| Resultado | Condición |
|---|---|
| ESPERAR | Datos no habilitados, objetivo inválido, fuera del tablero o fuera del margen configurado |
| ALCANZADO | Distancia al punto menor o igual a la tolerancia de posición |
| GIRAR | Aún falta distancia y el error angular supera la tolerancia |
| AVANZAR | Aún falta distancia y el rumbo está dentro de tolerancia |

Cada resultado incluye `ruta_verificada: false`: corresponde a una recomendación geométrica. Un futuro planificador debe comprobar bordes, huella del robot, compañero, cubos y obstáculos antes de convertirla en movimiento.

Valores iniciales del ejemplo: tolerancia de posición 20 mm, tolerancia angular 5 grados y margen al borde 0 mm. **Margen cero sólo comprueba el centro**, no el cuerpo del robot. `border_margin_mm` permite exigir una separación adicional en origen y destino; habrá que definirla con las dimensiones reales. El código tampoco calcula una maniobra de recuperación si el robot ya está fuera de esa área.

## Coordenadas y signos

| Destino respecto al rover | Rumbo global |
|---|---|
| Derecha | 0° |
| Arriba (row menor) | 90° |
| Izquierda | 180° |
| Abajo (row mayor) | 270° |

La distancia se calcula en celdas y se convierte usando `grid.cell_mm`, sin asumir que todas las canchas tienen la misma escala. El giro recomendado es relativo al theta global recibido: positivo antihorario y negativo horario. Se toma el giro más corto; a exactamente 180 grados se elige -180 de manera determinista. Si origen y destino coinciden, el rumbo es `None` y no se pide girar.

Por ejemplo, mirar a 359° y querer apuntar a 0° requiere **+1°**, no una vuelta de -359°.

## Uso con telemetría del simulador

Arrancar el simulador como explica [PRUEBAS_PC.md](PRUEBAS_PC.md). En otra terminal, desde la raíz del repositorio:

```powershell
python -B base-robots/robots/pc/cliente_vision.py --target-col 15 --target-row 10
```

El monitor muestra la recomendación, distancia y giro calculados a partir de cada lectura. Las coordenadas indicadas están en celdas. No envía órdenes al simulador: sus rovers seguirán la demostración propia del publicador, no estas recomendaciones.

## Código reutilizable

En [navegacion.py](codigos/navegacion.py):

```python
from navegacion import PointNavigator

navegador = PointNavigator(
    position_tolerance_mm=20,
    angle_tolerance_deg=5,
    border_margin_mm=0,
)
decision = navegador.decide(estado_telemetria, {"col": 15, "row": 10})
```

No importa hardware, red ni el sistema oficial de visión. Esta lógica matemática se podrá reutilizar en el rover, verificando su ejecución en CircuitPython. Cada decisión debe recalcularse con información reciente; no se debe reenviar TURN continuamente, porque eso reiniciaría la maniobra del controlador actual.

## Verificación y límites

**52 pruebas pasan:** las 40 anteriores y 12 nuevas de navegación, con casos para los cuatro rumbos, distancias conocidas, escala variable, vuelta por cero, llegada, tolerancias, fases, datos viejos, compañero ausente, IDs en distinto orden, márgenes y valores inválidos. Incluyen el recorrido numérico completo con pérdida temporal de datos.

```powershell
python -B -m unittest discover -s base-robots/robots/tests -v
```

Falta seleccionar caminos libres, integrar el controlador de motores con la pose global y calibrar velocidades. Llegar al centro de un cubo no es una estrategia de manipulación: todavía falta elegir el punto de aproximación y la dirección de empuje. La coordinación de los dos robots y las entregas siguen pendientes.
