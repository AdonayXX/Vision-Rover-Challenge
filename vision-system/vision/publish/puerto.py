"""Dejar el puerto de telemetría libre antes de abrirlo.

Por qué existe
--------------
El puerto **2026 es oficial y no se cambia** (CLAUDE.md, sección 5). Eso lo
vuelve un recurso único: si algo lo tiene tomado, el sistema de visión no puede
publicar, y hasta ahora el `bind()` fallaba con `Address already in use` y el
arranque moría entero. El día de la competencia eso es inaceptable: **cuando el
sistema arranca, el puerto tiene que quedar listo para conexión**.

Quién puede tenerlo tomado
--------------------------
En todo el proyecto hay exactamente **dos** programas que abren el 2026, y los
dos son nuestros:

1. **Otra instancia del sistema de visión** que quedó viva. Es el caso frecuente:
   se lanzó dos veces, o la terminal anterior se cerró sin apagar el proceso.
2. **El simulador del contrato** (`contrato/mock_publisher.py`), que usa el mismo
   puerto **a propósito**, para que un equipo pase del simulador a la cancha sin
   tocar su código. El precio de esa decisión es que los dos son mutuamente
   excluyentes.

Software ajeno prácticamente no aparece: el 2026 no lo usa ningún servicio común
y está muy por debajo del rango de puertos efímeros, así que tampoco se lo lleva
por casualidad una conexión saliente de otro programa.

La decisión: se libera, no se pregunta
--------------------------------------
Al arrancar, el sistema **termina al proceso que tenga el puerto** y sigue. Se
eligió así porque el arranque tiene que ser incondicional, y porque los dos
candidatos reales son procesos nuestros y reemplazables.

Es una acción destructiva, y por eso se hace **ruidosa**: se anuncia por pantalla
el nombre y el PID de cada proceso antes de terminarlo. Si alguien estaba usando
el simulador, se entera de por qué se le murió.

Dos salvaguardas que no la debilitan:

- **Solo se termina a quien está ESCUCHANDO** en el puerto, nunca a un cliente
  conectado a él. Sin ese filtro, un rover o un `test_client` conectado aparecería
  en la lista y lo mataríamos por error.
- **Nunca se termina a uno mismo** ni al proceso padre. Un `lsof` que se confunda
  y devuelva nuestro propio PID apagaría el sistema que estamos encendiendo.

Por qué acá y no en `contrato/`
-------------------------------
El `bind()` vive en `contrato/publicador.py`, compartido con el simulador. Pero
esta lógica **no puede ir ahí**, por dos motivos. Uno de regla: el contrato se
entrega suelto a los equipos y corre con biblioteca estándar pura; matar procesos
no es asunto suyo. Y otro de sentido: si la compartieran, el simulador también
mataría al sistema de visión, y dos programas que se apagan mutuamente al
arrancar es peor que el problema original. **El sistema de visión reclama el
puerto; el simulador sigue siendo educado.**

Por qué se consulta al sistema operativo con comandos
-----------------------------------------------------
Saber qué PID escucha un puerto no está en la biblioteca estándar de Python, y
las dependencias de visión están fijadas (`opencv`, `numpy`, `pillow`) y no se
agregan sin pedirlo. Así que se le pregunta al sistema operativo con las
herramientas que ya trae: `lsof` en macOS, `ss` o `lsof` en Linux, `netstat` en
Windows, que es el destino de despliegue.

Si ninguna está disponible o el formato no se entiende, esto **no rompe el
arranque**: informa que no pudo averiguarlo y deja que el `bind()` decida. Un
diagnóstico que falla no puede ser peor que no haberlo intentado.
"""

from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
from typing import Callable, NamedTuple


class Proceso(NamedTuple):
    """Un proceso que tiene tomado el puerto: su PID y con qué nombre corre."""

    pid: int
    nombre: str

    def __str__(self) -> str:
        return "{} (PID {})".format(self.nombre, self.pid)


class ErrorPuerto(Exception):
    """El puerto sigue ocupado después de intentar liberarlo."""


# --------------------------------------------------------------------------
# Preguntar quién escucha
# --------------------------------------------------------------------------

def _correr(orden: list[str], timeout: float = 5.0) -> str | None:
    """Corre un comando y devuelve su salida, o `None` si no se pudo.

    Cualquier fallo —el comando no existe, tarda de más, devuelve error— es un
    `None`, no una excepción: acá se está haciendo un diagnóstico auxiliar y
    ninguno de sus problemas justifica impedir el arranque.
    """
    try:
        completado = subprocess.run(
            orden, capture_output=True, text=True, timeout=timeout, check=False)
    except (OSError, subprocess.SubprocessError):
        return None
    return completado.stdout or ""


def _nombre_de_pid(pid: int) -> str:
    """Con qué nombre corre un PID. Best-effort: si no se sabe, 'desconocido'."""
    if sys.platform == "win32":
        salida = _correr(["tasklist", "/FI", "PID eq {}".format(pid), "/NH", "/FO", "CSV"])
        if salida:
            for linea in salida.splitlines():
                if linea.strip().startswith('"'):
                    return linea.split('","')[0].strip('"')
        return "desconocido"
    salida = _correr(["ps", "-p", str(pid), "-o", "comm="])
    if salida and salida.strip():
        return os.path.basename(salida.strip().splitlines()[0].strip())
    return "desconocido"


def _pids_unix(puerto: int) -> set[int] | None:
    """PIDs que ESCUCHAN el puerto, en macOS y Linux.

    `-sTCP:LISTEN` es la parte importante: sin ese filtro, `lsof` devuelve
    también los clientes conectados al puerto, y terminarlos sería matar a los
    rovers que están consumiendo la telemetría.
    """
    salida = _correr(
        ["lsof", "-nP", "-iTCP:{}".format(puerto), "-sTCP:LISTEN", "-t"])
    if salida is not None:
        return {int(p) for p in salida.split() if p.strip().isdigit()}

    # Linux sin lsof: `ss` viene de fábrica en casi todas las distribuciones.
    salida = _correr(["ss", "-ltnp", "sport", "=", ":{}".format(puerto)])
    if salida is None:
        return None
    pids = set()
    for linea in salida.splitlines():
        # El formato es users:(("python3",pid=1234,fd=5))
        for trozo in linea.split("pid=")[1:]:
            numero = ""
            for caracter in trozo:
                if not caracter.isdigit():
                    break
                numero += caracter
            if numero:
                pids.add(int(numero))
    return pids


def _pids_windows(puerto: int) -> set[int] | None:
    """PIDs que ESCUCHAN el puerto en Windows, vía `netstat -ano`.

    Se filtra por estado LISTENING por el mismo motivo que en Unix: las
    conexiones establecidas contra el 2026 son los equipos, no el dueño del
    puerto.
    """
    salida = _correr(["netstat", "-ano", "-p", "TCP"])
    if salida is None:
        return None
    pids = set()
    sufijo = ":{}".format(puerto)
    for linea in salida.splitlines():
        partes = linea.split()
        # proto | dirección local | dirección remota | estado | PID
        if len(partes) < 5 or partes[3].upper() != "LISTENING":
            continue
        if partes[1].endswith(sufijo) and partes[4].isdigit():
            pids.add(int(partes[4]))
    return pids


def quien_escucha(puerto: int) -> list[Proceso] | None:
    """Qué procesos están escuchando el puerto.

    Devuelve la lista —vacía si está libre— o `None` si **no se pudo averiguar**,
    que es distinto de "no hay nadie" y por eso no se colapsan en el mismo valor:
    con `None`, quien llama no debe concluir que el puerto está libre.

    Nunca se incluye a uno mismo ni al proceso padre: terminarlos sería apagar el
    sistema que se está encendiendo.
    """
    pids = _pids_windows(puerto) if sys.platform == "win32" else _pids_unix(puerto)
    if pids is None:
        return None
    propios = {os.getpid(), os.getppid()}
    return [Proceso(pid, _nombre_de_pid(pid)) for pid in sorted(pids - propios)]


# --------------------------------------------------------------------------
# Terminar y confirmar
# --------------------------------------------------------------------------

def _terminar(pid: int, forzar: bool) -> None:
    """Le pide a un proceso que termine; con `forzar`, no le pide, lo mata."""
    if sys.platform == "win32":
        orden = ["taskkill", "/PID", str(pid)]
        if forzar:
            orden.append("/F")
        _correr(orden)
        return
    import signal
    try:
        os.kill(pid, signal.SIGKILL if forzar else signal.SIGTERM)
    except (ProcessLookupError, PermissionError):
        pass


def puerto_libre(puerto: int, host: str = "0.0.0.0") -> bool:
    """Si el puerto se puede tomar AHORA, probándolo de verdad.

    Es la única comprobación que no miente: abre y cierra un socket con las
    mismas opciones que usará el publicador. Preguntarle a `lsof` solo dice qué
    ve el sistema operativo; esto dice si el `bind()` va a andar.
    """
    prueba = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        prueba.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        prueba.bind((host, puerto))
        return True
    except OSError:
        return False
    finally:
        prueba.close()


def liberar_puerto(puerto: int, espera_s: float = 5.0,
                   avisar: Callable[[str], None] = print,
                   host: str = "0.0.0.0") -> None:
    """Deja el puerto disponible, terminando a quien lo tenga tomado.

    El orden es: mirar si hace falta, pedir por las buenas, esperar, y recién
    entonces matar. Un proceso al que se le pide terminar cierra su socket de
    escucha ordenadamente; matarlo de entrada dejaría clientes cortados a la
    mitad sin necesidad.

    `espera_s` es cuánto se le da a cada etapa para soltar el puerto. Sale de la
    configuración, no del código: es un umbral, y los umbrales son datos
    (CLAUDE.md, sección 6).

    Lanza `ErrorPuerto` si al final sigue ocupado. Que el arranque sea
    incondicional no significa mentir: si no se logró, hay que decirlo.
    """
    if puerto_libre(puerto, host):
        return

    ocupantes = quien_escucha(puerto)
    if ocupantes is None:
        avisar("[puerto] el {} está ocupado y no se pudo averiguar quién lo tiene "
               "(falta lsof/ss/netstat). Se espera a que se libere solo.".format(puerto))
    elif not ocupantes:
        # El puerto no se puede tomar pero nadie lo escucha: casi siempre es un
        # socket en TIME_WAIT que SO_REUSEADDR no alcanzó a cubrir. Se resuelve
        # solo en segundos; no hay a quién terminar.
        avisar("[puerto] el {} todavía no se puede tomar, pero no hay ningún "
               "proceso escuchándolo. Se espera a que el sistema lo suelte.".format(puerto))
    else:
        avisar("[puerto] el {} está ocupado por: {}. El sistema de visión lo "
               "necesita, así que se termina{} para poder arrancar.".format(
                   puerto, ", ".join(str(p) for p in ocupantes),
                   "n" if len(ocupantes) > 1 else ""))
        for proceso in ocupantes:
            _terminar(proceso.pid, forzar=False)

    if _esperar_libre(puerto, espera_s, host):
        avisar("[puerto] el {} quedó libre.".format(puerto))
        return

    # No soltó por las buenas. Segunda vuelta, sin pedir permiso.
    ocupantes = quien_escucha(puerto) or []
    for proceso in ocupantes:
        avisar("[puerto] {} no soltó el {}: se fuerza.".format(proceso, puerto))
        _terminar(proceso.pid, forzar=True)

    if _esperar_libre(puerto, espera_s, host):
        avisar("[puerto] el {} quedó libre.".format(puerto))
        return

    raise ErrorPuerto(
        "el puerto {} sigue ocupado después de {:.0f} segundos{}. El sistema no "
        "puede publicar telemetría sin él, y el puerto es oficial y no se cambia. "
        "Hay que liberarlo a mano y volver a arrancar.".format(
            puerto, espera_s * 2,
            " por " + ", ".join(str(p) for p in ocupantes) if ocupantes else ""))


def _esperar_libre(puerto: int, espera_s: float, host: str) -> bool:
    """Sondea hasta que el puerto se pueda tomar, o hasta que se acabe el tiempo.

    Se sondea en vez de dormir el total de una: un proceso que muere rápido
    —el caso normal— libera el puerto en milisegundos, y no tiene sentido
    hacerle esperar cinco segundos al arranque por eso.
    """
    limite = time.monotonic() + max(0.0, espera_s)
    while True:
        if puerto_libre(puerto, host):
            return True
        if time.monotonic() >= limite:
            return False
        time.sleep(0.1)
