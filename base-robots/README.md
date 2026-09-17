# Base de trabajo para los dos robots

**Para la visita con hardware:** [primera prueba de conexion y motores](robots/PRIMERA_PRUEBA.md). Incluye cliente de banco sin camara ni IMU.

Selección del repositorio Vision Rover Challenge para construir nuestra solución. La organización inicial está completa y el control de pruebas de los robots ya tiene correcciones. Todavía son componentes y ejemplos, no una aplicación integrada que complete el reto. Ver [correcciones, uso y pendientes](robots/CORRECCIONES.md).

**Sin hardware:** ya hay un cliente de telemetría probado con el publicador simulado. Ejecutar desde la raíz del repositorio `python -B base-robots/robots/pc/demo_vision.py`. Instrucciones y resultados en [Pruebas en computadora](robots/PRUEBAS_PC.md).

**Navegación básica:** cálculos de distancia/giro y recomendaciones hacia un punto, con ensayo de movimiento ideal. Ejecutar `python -B base-robots/robots/pc/demo_navegacion.py`. Ver [NAVEGACION.md](robots/NAVEGACION.md).

**Rutas libres:** desvíos alrededor de cubos, compañero y obstáculos con tamaños configurables. Ejecutar `python -B base-robots/robots/pc/demo_rutas.py`. Ver [RUTAS.md](robots/RUTAS.md).

**Reparto de cubos:** comparación de cercanía y carga equilibrada en escenarios repetibles. Ejecutar `python -B base-robots/robots/pc/demo_asignacion.py --scenarios 200`. Ver [ASIGNACION.md](robots/ASIGNACION.md).

**Acuerdos de tareas:** reservas, inicio y entrega con confirmaciones, revisiones y espera ante pérdida de comunicación. Ejecutar `python -B base-robots/robots/pc/demo_coordinacion.py`. Ver [COORDINACION.md](robots/COORDINACION.md). Suite actual: **100 pruebas pasando**.

## Estructura

```text
base-robots/
├── vision-system/           # Computadora: webcam, detección, telemetría y simulación
│   ├── contrato/            # Formato de datos, publicador simulado y cliente de ejemplo
│   └── vision/              # Procesamiento de cámara, calibración y verificaciones
├── robots/
│   ├── README.md            # Índice por función de los ejemplos
│   └── codigos/             # CircuitPython: hardware, motores, sensores y comunicación
├── hardware/
│   ├── armado/              # Guía e imagen de montaje
│   ├── conexiones/          # Cableado y referencias
│   ├── aruco/               # Marcadores imprimibles de tablero y robots
│   └── archivos_fabricacion/ # Tablero, cubos y piezas
├── documentacion/
│   ├── reglamento.md
│   ├── robot.md
│   ├── el_reto.md
│   └── programacion/        # Preparación del entorno del robot
└── INVENTARIO.json          # Origen, estado y hashes originales/actuales
```

## Por dónde empezar

1. [Componentes del robot](robots/README.md): localizar lo que vamos a integrar.
2. [Contrato de visión](vision-system/contrato/CONTRATO.md): conocer los datos que recibirán los rovers.
3. [Cliente de ejemplo](vision-system/contrato/test_client.py): referencia de lectura de telemetría; requiere adaptación a CircuitPython.
4. [Sistema de visión](vision-system/README.md): ejecutar la cámara o las fuentes sintéticas cuando preparemos el entorno.
5. [Montaje del tablero](vision-system/MONTAJE.md), [puesta a punto](vision-system/PUESTA_A_PUNTO.md) y [operación](vision-system/OPERACION.md).
6. [Reglamento copiado](documentacion/reglamento.md): referencia de la ronda y del reparto de responsabilidades.

## Criterios de organización

- Visión y contrato permanecen juntos y conservan su estructura interna para mantener sus imports, configuraciones y recursos relativos.
- Los ejemplos CircuitPython permanecen juntos en `robots/codigos/`, junto a `ideaboard.py`, para conservar sus imports locales. El índice de robots los organiza por función.
- Las guías se copian con los recursos locales de sus carpetas. Los enlaces externos originales siguen requiriendo conexión; no se descargaron videos ni bibliotecas externas.
- Calibraciones y mediciones de visión se conservan como referencia del montaje original, no como calibración confirmada de nuestro montaje.
- `vision-system/CLAUDE.md` conserva las notas originales de mantenimiento del sistema de visión. Las referencias a la estructura anterior en documentos copiados se pueden rastrear con el inventario.
- No se incluyen historial Git, cachés, entornos virtuales ni archivos generados no versionados. Esta carpeta se puede copiar completa a otro lugar.

## Etapa siguiente: integración autónoma

Ya corregidos: protocolo compartido, recepción TCP, control de avance/giro por pasos y paradas por comandos inválidos, desconexión o permiso vencido. Pendiente: cliente de telemetría en los rovers, integración de sensores y fases, navegación por coordenadas, coordinación de tareas y maniobras con cubos. La lista completa y sus criterios de verificación están en [CORRECCIONES.md](robots/CORRECCIONES.md).

Los módulos corregidos de movimiento, protocolo y sesión no inicializan hardware al importarse. Los demás ejemplos originales todavía pueden inicializar hardware y ejecutar movimientos al cargarse. Esta estructura es una base de desarrollo; no es una carpeta lista para copiar entera a la placa. Las dependencias de visión se declaran en su `requirements.txt`; las bibliotecas externas de CircuitPython todavía deben prepararse.
