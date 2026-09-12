"""Revisa la configuración del sistema y muestra lo que declara.

Cómo se corre:

    python -m vision.tools.verificar_config
    python -m vision.tools.verificar_config --config otra_config.json

Qué responde
------------
Dos preguntas distintas, que es justo el motivo por el que esta herramienta
existe:

1. **¿La configuración es posible?** Eso lo decide `revisar_config`, y si la
   respuesta es no, el sistema **no arranca**. Una zona de acopio declarada en
   una esquina, o más grande que la cancha, no produce un error en el momento de
   usarla: produce telemetría perfectamente válida que describe una cancha que
   no existe, y el equipo que la consume busca el problema en su propio código.

2. **¿Es además razonable?** Eso lo dice `avisos_config`, y **no** bloquea nada.
   Hay cosas que son posibles pero justas —la ventana de aceptación del acopio
   contra el error de ubicación del sistema es el caso que motivó todo esto— y
   quien opera la cancha tiene que poder verlas sin que el programa decida por
   él.

Esa separación es deliberada. Un aviso que impidiera arrancar terminaría
borrado por quien tiene una ronda esperando; un error que solo avisara,
ignorado hasta que sea tarde.

**El código de salida solo mira los errores.** Con avisos y sin errores, sale
0: encadenar esta herramienta a otra cosa no tiene que romperse porque una
medida quedó ajustada.
"""

from __future__ import annotations

import argparse
import sys

try:  # como paquete
    from ..configuracion import avisos_config, cargar_config, geometrias_deposito
except ImportError:  # como script suelto
    from vision.configuracion import (  # type: ignore[no-redef]
        avisos_config, cargar_config, geometrias_deposito,
    )


def mostrar_lugares(cfg) -> None:
    """La cancha y los lugares fijos, como quedaron declarados.

    Se imprime lo que el sistema ENTENDIÓ, no lo que dice el archivo: el lado de
    cada zona, por ejemplo, no está escrito en ningún lado —se deduce del borde
    más cercano—, y verlo acá es la forma de confirmar que se dedujo el que uno
    esperaba antes de que la cancha esté montada.
    """
    cell = cfg.tablero.cell_mm
    tam = cfg.lugares.tamano_deposito
    print("  Cancha:  {} x {} celdas de {:.0f} mm  ({:.0f} x {:.0f} mm)".format(
        cfg.tablero.cols, cfg.tablero.rows, cell,
        cfg.tablero.cols * cell, cfg.tablero.rows * cell))
    print("  Salida:  ({:.2f}, {:.2f}) celdas".format(
        cfg.lugares.start_col, cfg.lugares.start_row))
    print("  Zonas:   {:.0f} x {:.0f} mm (largo x fondo), una por color".format(
        tam.largo_mm, tam.fondo_mm))
    print("  Cubo:    {:.0f} mm de lado".format(cfg.elementos.cubos.lado_mm))
    print()
    print("  {:<7} {:<11} {:>16} {:>22} {:>16}".format(
        "color", "lado", "centro (celdas)", "ventana de aceptación", "tolerancia"))
    print("  " + "-" * 76)
    for color, geo in sorted(geometrias_deposito(cfg).items()):
        print("  {:<7} {:<11} {:>16} {:>22} {:>16}".format(
            color, geo.lado,
            "({:.2f}, {:.2f})".format(geo.col, geo.row),
            "{:.1f} x {:.1f} mm".format(geo.ventana_col * 2 * cell, geo.ventana_row * 2 * cell),
            "+/- {:.1f} mm".format(min(geo.ventana_col, geo.ventana_row) * cell)))
    print()
    print("  La VENTANA es dónde puede caer el CENTRO del cubo para que el cubo")
    print("  entero quede adentro, con cualquier rotación. La TOLERANCIA es la mitad")
    print("  de su lado más angosto: cuánto se puede correr el cubo del eje de la")
    print("  zona antes de quedar afuera.")
    print()
    print("  Permanencia mínima para contar un cubo: {} ms".format(
        cfg.conteo_acopio.permanencia_minima_ms))
    print()
    print("  Preparación (READY): {:.0f} s      Ronda (RUNNING): {:.0f} s".format(
        cfg.ronda.preparacion_ms / 1000.0, cfg.ronda.duracion_ms / 1000.0))
    print("  La preparación termina SOLA: no hay tecla que adelante el paso a")
    print("  RUNNING. La ronda se cierra al agotarse el tiempo, o antes si los")
    print("  tres cubos quedan en posición.")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Revisa la configuración del sistema de visión y muestra lo que declara."
    )
    parser.add_argument("--config", default=None)
    args = parser.parse_args(argv)

    print("=" * 78)
    print("REVISIÓN DE LA CONFIGURACIÓN")
    print("=" * 78)

    try:
        cfg = cargar_config(args.config) if args.config else cargar_config()
    except (ValueError, KeyError, OSError) as exc:
        # `cargar_config` ya corre `revisar_config` y lanza con el texto completo.
        # Un KeyError es una clave que falta en el JSON, que para quien edita el
        # archivo es el mismo problema: la configuración no se puede usar.
        print("\nHAY UN ERROR Y EL SISTEMA NO ARRANCARÍA:")
        print("  ✗ {}".format(exc))
        print("\n" + "=" * 78)
        print("RESULTADO: CONFIGURACIÓN INVÁLIDA")
        print("=" * 78)
        return 1

    print()
    mostrar_lugares(cfg)

    avisos = avisos_config(cfg)
    print("\n" + "-" * 78)
    if avisos:
        print("AVISOS — la configuración es válida, pero conviene saber esto:")
        for aviso in avisos:
            print("  ! {}".format(aviso))
    else:
        print("Sin avisos.")

    print("\n" + "=" * 78)
    print("RESULTADO: TODO OK{}".format(
        " (con {} aviso{})".format(len(avisos), "s" if len(avisos) != 1 else "") if avisos else ""))
    print("=" * 78)
    return 0


if __name__ == "__main__":
    sys.exit(main())
