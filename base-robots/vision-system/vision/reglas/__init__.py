"""Paquete `reglas` — lo que el sistema DECIDE a partir del estado del mundo.

Separado de `detectors/` a propósito: **detectar** es mirar la imagen y decir
qué hay dónde; **decidir** es tomar ese resultado y aplicarle una regla del
reto. Son dos trabajos distintos, con dos formas distintas de estar mal —un
detector se equivoca por la luz o la oclusión, una regla se equivoca por el
criterio— y mezclarlos vuelve imposible saber cuál de los dos falló.

Nada de acá se publica. El contrato lleva **dónde está cada cosa**; lo que este
paquete produce es el **veredicto**, y va a la pantalla y al árbitro. La
separación se mantiene igual: acá se cuenta y se dice desde cuándo, pero la
ronda la cierra el árbitro, que es una sola voz y el que lleva el cronómetro.

Nada de acá dibuja tampoco. Estas piezas devuelven datos; quien los pinta es
`vista.py`.
"""
