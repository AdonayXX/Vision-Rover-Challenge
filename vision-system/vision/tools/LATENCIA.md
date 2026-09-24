# Latencia de vision

Reiniciar `python -m vision.sistema --ventana` después de actualizar el código.
Cada cinco segundos aparece `[latencia ms promedio/max]`:

- `lectura`: tiempo para obtener y rectificar el cuadro.
- `entrada`: edad del cuadro al entrar en el procesamiento.
- `marcadores`, `cubos`: tiempo de cada detector.
- `proceso`: procesamiento completo hasta construir las detecciones.
- `vista`: dibujo y atención de la ventana.
- `al_publicar`: edad de captura al entregar el estado al publicador. El
  temporizador de publicación y el transporte aún pueden sumar tiempo.

Si aumentan los `fallos`, revisar el `[aviso] último problema`: se conserva el
estado anterior cuando un cuadro no es válido, y ese estado sigue envejeciendo.
No se cambia `ts_ms` para disimular el retraso ni se eleva el límite del cliente.

La configuración activa ArUco3 con lado canónico mínimo de 16 píxeles, seguido
de refinamiento subpíxel sobre la imagen original. El mínimo de 32 de OpenCV
perdía los marcadores pequeños de ambos rovers en la captura de esta cancha.
Si falta una esquina o un rover seguido, se rehace la detección con el algoritmo
clásico. Los filtros de plausibilidad, duplicados y admisión siguen activos.
Para volver al algoritmo anterior: `deteccion_marcadores.usar_aruco3=false`.

Medición local del 18-09-2026: captura rectificada de 1280x720, ambos rovers y los
tres cubos. Sobre 20 repeticiones (descartando las tres primeras), procesamiento
clásico mediana/p95 = 218/234 ms; rápido = 80/87 ms. Dibujo sin abrir ventana =
14 ms aproximadamente. Las posiciones coinciden dentro de 0,002 celdas y los
ángulos a dos decimales. Es una prueba sobre imagen guardada, NO una medición
del retardo físico de la cámara ni una prueba de movimiento del rover.

Regresiones sin cámara ni motores, desde `vision-system`:

```powershell
python -m unittest vision.tools.test_latencia_vision vision.tools.test_area_cubos
```

Incluyen varios ángulos, duplicados, recuperación al detector clásico,
conservación del timestamp original y, si está disponible, la captura local.
