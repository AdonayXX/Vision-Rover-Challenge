"""Subpaquete `tools` — herramientas de puesta a punto.

Nada de lo que hay acá corre durante una ronda: son utilidades de apoyo. Hoy son
trece, entre verificaciones contra verdad conocida —geometría, rovers, cubos,
seguimiento, acopio, ronda—, revisión de configuración, diagnósticos de cámara y
de falsos positivos, calibración de distorsión, patrón de calibración, medición
de precisión y de desfases, y la validación de los ejemplos de los documentos.
El detalle de cada una está en README.md.

El **monitor en vivo ya existe** y no está acá: es `../vista.py`, que se abre con
`--ventana`. Lo único planificado sin código es la guía de alineamiento.
"""
