"""Verifica que los mensajes de ejemplo de los documentos sigan siendo válidos.

    python -m vision.tools.verificar_ejemplos

Por qué existe
--------------
Un documento con un ejemplo viejo no es un error de redacción: es un documento
que **nadie puede verificar**. El caso que la motivó: el mensaje de ejemplo de
`README.md` se quedó sin el campo `clock` cuando el protocolo lo agregó, y el
propio validador del contrato lo rechazaba —`faltan campos ['clock']`—. Nadie se
dio cuenta durante días, y apareció recién en una auditoría hecha a mano.

Un equipo que toma ese ejemplo como referencia escribe un cliente contra un
formato que el sistema no emite. Y el costo de descubrirlo es asimétrico: a
nosotros nos cuesta una línea, a ellos les cuesta una ronda.

Esta herramienta convierte esa auditoría en una comprobación de segundos: extrae
los bloques JSON de los documentos, los pasa por `schema.validate_message` —el
mismo validador que usa el sistema— y falla si alguno no cumple. La próxima vez
que el contrato cambie, el ejemplo viejo lo canta una herramienta.

Qué mira y qué no
-----------------
Mira los bloques de código marcados como ```json que **parecen un mensaje**: los
que traen `v` y `seq`. Los demás bloques JSON de los documentos son fragmentos de
configuración o de subobjetos, y validarlos como mensajes daría un error falso.

Para que ese criterio no se vuelva un agujero —un mensaje mal escrito al que le
falte `seq` pasaría por "no es un mensaje" y nadie lo miraría—, la herramienta
**informa cuántos bloques salteó y en qué línea**, para que quien la corre pueda
mirarlos si algo no cuadra.

No mira JSON suelto en medio de un párrafo, ni ejemplos dentro de bloques de
Python. Si mañana hace falta, se agregan acá.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if BASE not in sys.path:
    sys.path.insert(0, BASE)

from contrato import schema  # noqa: E402  (después de tocar sys.path, a propósito)

#: Los documentos que publican ejemplos. Las rutas son relativas a
#: `vision-system/`. Si un archivo no está, se informa y no se falla: la página
#: de los equipos vive fuera del repositorio y no siempre está a mano.
DOCUMENTOS = (
    "contrato/CONTRATO.md",
    "contrato/README.md",
    "README.md",
    "vision/README.md",
    "MONTAJE.md",
    "PUESTA_A_PUNTO.md",
)

#: Bloques ```json ... ``` de un documento de markdown.
_BLOQUE_JSON = re.compile(r"```json\n(.*?)```", re.S)

#: Lo mismo dentro de un HTML: <pre><code class="language-json">...</code></pre>
#: o cualquier bloque que empiece con una llave. Se busca por el contenido, que
#: es lo único estable entre generadores de HTML distintos.
_BLOQUE_HTML = re.compile(r"<(?:pre|code)[^>]*>\s*(\{.*?\})\s*</(?:code|pre)>", re.S)


def _linea_de(texto: str, posicion: int) -> int:
    return texto.count("\n", 0, posicion) + 1


def bloques_de(ruta: str) -> list[tuple[int, str]]:
    """Devuelve `(línea, texto)` de cada bloque JSON del documento."""
    with open(ruta, "r", encoding="utf-8") as f:
        texto = f.read()
    patron = _BLOQUE_HTML if ruta.endswith(".html") else _BLOQUE_JSON
    return [(_linea_de(texto, m.start(1)), m.group(1)) for m in patron.finditer(texto)]


def parece_mensaje(datos) -> bool:
    """Un mensaje de telemetría trae `v` y `seq`; un fragmento de config, no."""
    return isinstance(datos, dict) and "v" in datos and "seq" in datos


def revisar(ruta: str) -> tuple[int, int, list[str]]:
    """Devuelve `(validados, salteados, problemas)` de un documento."""
    validados = 0
    salteados = []
    problemas = []

    for linea, crudo in bloques_de(ruta):
        try:
            datos = json.loads(crudo)
        except json.JSONDecodeError as exc:
            # Un bloque marcado como json que no es json tampoco sirve de
            # ejemplo, aunque no sea un mensaje: se informa igual.
            problemas.append("{}:{} no es JSON válido: {}".format(ruta, linea, exc))
            continue
        if not parece_mensaje(datos):
            salteados.append("{}:{}".format(ruta, linea))
            continue
        error = schema.validate_message(datos)
        if error:
            problemas.append("{}:{} {}".format(ruta, linea, error))
        else:
            validados += 1

    return validados, salteados, problemas


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Valida los mensajes de ejemplo de los documentos contra el contrato."
    )
    parser.add_argument("--documento", action="append", default=None,
                        help="ruta extra a revisar (se puede repetir); por ejemplo, la "
                             "página que se les publica a los equipos")
    args = parser.parse_args(argv)

    documentos = list(DOCUMENTOS) + list(args.documento or ())

    print("=" * 78)
    print("EJEMPLOS DE LOS DOCUMENTOS, CONTRA EL VALIDADOR DEL CONTRATO")
    print("=" * 78)
    print("  protocolo v{} · {} campos raíz\n".format(
        schema.PROTOCOL_VERSION, len(schema._CAMPOS_MENSAJE)))

    total_ok = 0
    todos_salteados: list[str] = []
    todos_problemas: list[str] = []
    faltantes: list[str] = []

    for doc in documentos:
        ruta = doc if os.path.isabs(doc) else os.path.join(BASE, doc)
        if not os.path.exists(ruta):
            faltantes.append(doc)
            continue
        validados, salteados, problemas = revisar(ruta)
        total_ok += validados
        todos_salteados.extend(salteados)
        todos_problemas.extend(problemas)
        estado = "OK" if not problemas else "{} PROBLEMA(S)".format(len(problemas))
        print("  {:<44} {:>2} mensaje(s)  {}".format(doc, validados, estado))

    if faltantes:
        print("\n  no encontrados (no es falla): {}".format(", ".join(faltantes)))

    if todos_salteados:
        print("\n  bloques JSON que NO son mensajes, y por eso no se validaron:")
        print("    " + ", ".join(todos_salteados))
        print("    Si alguno debería serlo, le falta `v` o `seq` y hay que mirarlo.")

    if todos_problemas:
        print("\n" + "-" * 78)
        print("  PROBLEMAS:\n")
        for p in todos_problemas:
            print("    " + p)
        print("\n  Un ejemplo que el validador rechaza es un ejemplo que un equipo no")
        print("  puede usar. Se arregla el documento, no el validador.")

    print("\n" + "=" * 78)
    print("RESULTADO: {} — {} mensaje(s) válido(s), {} con problemas".format(
        "TODO OK" if not todos_problemas else "HAY FALLAS",
        total_ok, len(todos_problemas)))
    print("=" * 78)
    return 0 if not todos_problemas else 1


if __name__ == "__main__":
    sys.exit(main())
