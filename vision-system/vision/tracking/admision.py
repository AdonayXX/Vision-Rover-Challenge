"""Admisión de identidades nuevas: un rover tiene que sostenerse para existir.

Qué resuelve
------------
Un fantasma con el ID de un rover hace dos cosas distintas según quién esté en
la cancha, y la segunda es la peligrosa:

- con el rover **presente**, colisiona con él, y eso lo resuelve la resolución de
  duplicados midiendo los dos candidatos;
- con el rover **ausente**, no colisiona con nadie: **crea una identidad que no
  existe**. Se publica como un rover más, con edad cero —o sea presentado como
  fresco y seguro—, y el seguimiento lo conserva hasta que lo barre la edad
  máxima. Medido en vivo antes de las defensas: un rover 10 fantasma que saltaba
  478 mm entre cuadros con edad de 133 ms.

Esta pieza ataja eso exigiendo que una identidad **nueva** se vea en varios
cuadros consecutivos antes de aceptarla. Un fantasma no lo consigue: la racha más
larga medida fue de **dos cuadros**, tanto en las dos sesiones con datos crudos
guardados —196 detecciones falsas, 25 IDs distintos— como en las cuatro corridas
completas, 361 detecciones. Dos en todas.

Por qué el margen es holgado y no justo
---------------------------------------
Hacen falta **cinco** cuadros, no tres, porque los dos costos no se parecen:

- **subirlo** cuesta 66 ms más, **una sola vez**, al poner el robot;
- **equivocarse** cuesta hasta un **minuto**. Un fantasma admitido deja de ser
  una detección suelta: se vuelve **identidad seguida**, y las detecciones
  siguientes la refrescan, así que el error se sostiene hasta que lo barre
  `edad_maxima_ms`.

Con esa asimetría el umbral no se elige apretado contra el peor caso medido.

Solo la primera aparición
-------------------------
El costo se paga **una sola vez**, cuando el robot entra a la cancha: cinco
cuadros son unos 166 ms a 30 fps. Durante la ronda no cuesta nada, porque un ID
que ya está en la memoria del seguimiento se acepta **de inmediato**, incluso
después de una oclusión larga: ya demostró que existe.

Por qué sigue existiendo si el filtro de tamaño ya los mata
------------------------------------------------------------
Porque el margen del filtro de tamaño es una propiedad de **esta** escena, esta
luz y esta altura de cámara, no del sistema. Medido, el fantasma más grande está
a factor 1,9 del umbral, no a factor 10: alcanza con que cambie la iluminación o
se baje la cámara para que ese margen se achique. La persistencia no depende de
ningún margen —depende de que un fantasma no se sostenga— y cuesta 166 ms una
vez. Es una red, no la defensa principal.

Solo se aplica a los rovers
---------------------------
Los marcadores de **esquina no se demoran nunca**: son los que establecen las
coordenadas, y retrasar su admisión retrasaría el anclaje entero, además de
estorbar la degradación con tres marcadores. A ellos los protegen el tamaño, la
posición y la resolución de duplicados.
"""

from __future__ import annotations

try:  # como paquete
    from ..configuracion import ConfigVision
except ImportError:  # como script suelto
    from vision.configuracion import ConfigVision  # type: ignore[no-redef]


class RegistroAdmision:
    """Lleva cuántos cuadros seguidos se viene viendo cada identidad nueva.

    Es memoria entre cuadros, y por eso vive en `tracking/` y no en el detector,
    que mira un cuadro y no sabe nada del anterior.

    No es seguro para usar desde varios hilos, y no hace falta que lo sea: vive
    en el hilo de proceso, que es el único que lo toca.
    """

    def __init__(self, cfg: ConfigVision):
        self._cfg = cfg
        self._necesarios = cfg.deteccion_marcadores.cuadros_para_admitir_rover
        #: Cuántos cuadros consecutivos lleva visto cada ID de rover.
        self._rachas: dict[int, int] = {}
        #: Los que ya entraron. La racha sigue creciendo después de la admisión
        #: —no hay motivo para reiniciarla—, así que sin esta marca `esperando`
        #: informaría como "esperando" a un rover que entró bien, y su aviso
        #: manda a revisar el montaje. Un aviso que se equivoca hace perder más
        #: tiempo que no tenerlo.
        self._admitidos: set[int] = set()

    def filtrar(
        self,
        detectados: dict,
        ya_seguidos: dict[int, tuple[float, float]],
    ) -> tuple[dict, tuple[tuple[int, int], ...]]:
        """Devuelve `(aceptados, en_espera)` para un cuadro.

        `ya_seguidos` son los rovers que el seguimiento ya recuerda: esos pasan
        sin esperar, porque su identidad ya está establecida. `en_espera` trae
        `(id, cuántos cuadros lleva)` de los que todavía no alcanzan, para poder
        informarlos: una identidad que se queda esperando para siempre es un
        rover que alguien puso y el sistema no acepta, y eso hay que verlo.
        """
        ids_rover = self._cfg.deteccion_rovers.ids_rover
        aceptados = {}
        en_espera = []

        for id_aruco, esquinas in detectados.items():
            if id_aruco not in ids_rover or id_aruco in ya_seguidos:
                # No es un rover, o su identidad ya está establecida: pasa.
                aceptados[id_aruco] = esquinas
                continue

            racha = self._rachas.get(id_aruco, 0) + 1
            self._rachas[id_aruco] = racha
            if racha >= self._necesarios:
                aceptados[id_aruco] = esquinas
                self._admitidos.add(id_aruco)
            else:
                en_espera.append((id_aruco, racha))

        # Una racha se corta si el ID no apareció en ESTE cuadro. Es lo que hace
        # que un fantasma no acumule apariciones sueltas a lo largo del tiempo:
        # tiene que sostenerse, no repetirse.
        for id_aruco in list(self._rachas):
            if id_aruco not in detectados:
                del self._rachas[id_aruco]
                self._admitidos.discard(id_aruco)

        return aceptados, tuple(en_espera)

    @property
    def esperando(self) -> dict[int, int]:
        """Los que están esperando **ahora**, para el diagnóstico.

        Los ya admitidos quedan afuera aunque su racha siga creciendo: esto es
        lo que alimenta un aviso que dice "si hay un robot de verdad ahí, no se
        está viendo estable", y decirlo de un rover que entró bien es mandar a
        revisar una cancha que no tiene nada.
        """
        return {i: n for i, n in self._rachas.items() if i not in self._admitidos}
