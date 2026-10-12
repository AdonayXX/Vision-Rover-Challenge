# Solución autónoma de los rovers

Esta carpeta contiene la solución de los dos CenfoBots y una copia de trabajo de los materiales necesarios para probarla. La entrada principal para el firmware está en [`robots/codigos/code.py`](robots/codigos/code.py). El código de los rovers corre en **CircuitPython 9 sobre IdeaBoard ESP32**; las herramientas de `robots/pc/` se ejecutan en una computadora durante el desarrollo.

La cámara oficial publica telemetría por TCP. Cada rover recibe esos datos directamente, calcula su tarea y movimiento, y comparte su estado con el otro por ESP-NOW. La computadora del equipo no manda movimientos durante la ronda.

## Ruta de lectura

1. [Mapa del código de los rovers](robots/README.md): responsabilidades de cada módulo.
2. [Contrato de visión](vision-system/contrato/CONTRATO.md): campos de los mensajes que leen ambos ESP32.
3. [Asignación](robots/ASIGNACION.md), [rutas](robots/RUTAS.md) y [navegación](robots/NAVEGACION.md): decisiones geométricas y reparto.
4. [Firmware en la placa](robots/codigos/README.md): archivos que se cargan y configuración.
5. [Primera prueba con un rover](robots/PRIMERA_PRUEBA.md): comprobaciones iniciales de motores y parada.

## Carpetas

| Ruta | Qué contiene |
| --- | --- |
| `robots/codigos/` | Firmware real: cliente de visión, ronda, misiones, rutas, sensores, motores y enlace entre rovers. |
| `robots/tests/` | Pruebas de lógica, transporte, sensores y simulación. |
| `robots/pc/` | Demostraciones, mediciones, calibración y diagnóstico. |
| `vision-system/` | Copia de la visión y su contrato para desarrollo local. |
| `hardware/` | Armado, conexiones, marcadores ArUco y archivos de fabricación. |
| `documentacion/` | Copia de las reglas y materiales de partida. |
| `INVENTARIO.json` | Relación con los archivos de origen de esta base. |

## Ensayo local

Desde la raíz del repositorio, `python -B base-robots/robots/pc/demo_rutas.py` muestra una ruta que rodea un cubo. Para ejecutar las pruebas:

```powershell
cd base-robots/robots
python -B -m unittest discover -s tests
```

Estas pruebas no requieren motores ni cámara. Para un taller guiado, consulta [`../TALLER.md`](../TALLER.md). Los documentos de etapas tempranas, como `CORRECCIONES.md`, conservan el historial de decisiones y pueden contener cifras de pruebas antiguas; este README y el mapa del código describen la estructura actual.
