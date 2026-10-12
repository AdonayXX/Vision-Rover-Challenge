# Vision Rover Challenge: solución de dos rovers autónomos

![Cancha, cubos y rovers del reto](vrc1.jpeg)

Este repositorio reúne las reglas y recursos del **Vision Rover Challenge** y la solución desarrollada para competir con dos CenfoBots. El objetivo era que ambos rovers llevaran tres cubos de colores a sus zonas usando la posición publicada por una cámara cenital. La cámara informa, y **cada rover decide y controla sus motores por sí mismo**.

El equipo obtuvo el **tercer lugar con 42 segundos** en la competencia, según el resultado compartido por sus integrantes. Este repositorio conserva el código, las pruebas y las decisiones de diseño para explicar cómo se llegó allí.

## Entender el proyecto en dos minutos

```text
Cámara cenital y sistema de visión oficial
             │ posiciones, orientación, cubos y fase de la ronda (TCP)
             ▼
       Rover 10 ◄──── ESP-NOW ────► Rover 11
       ESP32 / CircuitPython       ESP32 / CircuitPython
             │                          │
             └── planifican, se coordinan y mueven sus motores
```

El software oficial de visión publica el estado de la cancha. En cada ESP32, nuestro firmware lee la observación más reciente, reparte tareas, calcula rutas, se aproxima a un cubo, lo empuja y comprueba si quedó depositado. Los dos rovers intercambian su estado por ESP-NOW. Durante una ronda, la computadora se usa como infraestructura de visión, no como controlador de los robots.

## Por dónde empezar

| Si quieres… | Abre… |
| --- | --- |
| Entender el objetivo y las reglas | [El reto](el_reto.md), [reglamento](reglamento.md) y [torneo](torneo.md) |
| Ver qué construyó el equipo | [Solución de los rovers](base-robots/README.md) |
| Seguir el firmware desde su entrada | [Mapa del código](base-robots/robots/README.md) y [`code.py`](base-robots/robots/codigos/code.py) |
| Entender el dato que reciben | [Contrato de telemetría](vision-system/contrato/CONTRATO.md) |

## Estructura del repositorio

| Ruta | Contenido |
| --- | --- |
| [`base-robots/robots/codigos/`](base-robots/robots/codigos/) | **Firmware autónomo del equipo** para los ESP32: visión, rutas, coordinación, motores y recuperación de fallos. |
| [`base-robots/robots/tests/`](base-robots/robots/tests/) | Pruebas automatizadas y simulación de los dos rovers. |
| [`base-robots/robots/pc/`](base-robots/robots/pc/) | Herramientas de diagnóstico y demostraciones en una computadora; no controlan la ronda oficial. |
| [`vision-system/`](vision-system/) | Sistema de visión y contrato oficial usados como referencia y para pruebas. |
| [`base-robots/vision-system/`](base-robots/vision-system/) | Copia de trabajo de visión incluida con la base de los rovers. |
| [`codigos/`](codigos/) | Ejemplos iniciales de sensores y movimiento; **no son el firmware de competencia**. |
| [`armado/`](armado/), [`conexiones/`](conexiones/), [`aruco/`](aruco/) y [`archivos_fabricacion/`](archivos_fabricacion/) | Materiales de hardware y cancha. |

## Probar sin robots

Desde la raíz, con Python 3 disponible en el terminal:

```powershell
python -B base-robots/robots/pc/demo_rutas.py
python -B base-robots/robots/pc/demo_asignacion.py --scenarios 20
cd base-robots/robots
python -B -m unittest discover -s tests
```

`demo_rutas.py` muestra un desvío alrededor de un cubo y casos en los que la decisión correcta es esperar. `demo_asignacion.py` compara repartos en escenarios generados: sus distancias son **estimaciones**, no tiempos de carrera. La suite usa dobles y simulaciones; pasarla no sustituye una prueba física con cámara, red, motores y baterías.

Para usar hardware, comienza por la [guía de la placa](base-robots/robots/codigos/README.md) y la [primera prueba de motores](base-robots/robots/PRIMERA_PRUEBA.md). Las credenciales Wi-Fi pertenecen a un archivo local de configuración; la [plantilla versionada](base-robots/robots/codigos/config_robot.example.json) no contiene contraseñas reales.

## Lo que enseñó la cancha

La cancha exigió rutas y decisiones fiables cuando un cubo tapaba otro, la visión perdía temporalmente un rover, dos rovers se estorbaban, el Wi-Fi se cortaba o la batería caía al arrancar. El código incluye control por estados, datos con antigüedad, parada ante observaciones inválidas, replanificación y registro de fallos.

Las [notas de desarrollo](ESTADO_ACTUAL.md) documentan pruebas y problemas concretos de octubre de 2026; son una **bitácora histórica**, no una instrucción de despliegue vigente. Las reglas, imágenes y el sistema de visión oficial se conservan como materiales del reto. La solución del equipo está en `base-robots/robots/`.
