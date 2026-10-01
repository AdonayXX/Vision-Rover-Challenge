"""Registro de fallos en microcontroller.nvm: sobrevive a reinicios (no a
quitar la bateria). Sin cable USB es la unica forma de saber por que se cayo
el rover: la PC lo lee en la respuesta SENSORS al reconectar.
"""
import json

_MAGIA = b"RF"
_TAM = 256


def _nvm():
    import microcontroller
    return microcontroller.nvm


def leer(nvm=None):
    try:
        nvm = _nvm() if nvm is None else nvm
        if bytes(nvm[0:2]) != _MAGIA:
            return {}
        largo = nvm[2]
        return json.loads(bytes(nvm[3:3 + largo]).decode("utf-8"))
    except Exception:
        return {}


def guardar(clave, texto, nvm=None):
    """Guarda texto (recortado) bajo clave. Nunca lanza: esto corre en fallos."""
    try:
        nvm = _nvm() if nvm is None else nvm
        datos = leer(nvm)
        datos[clave] = str(texto)[:120]
        crudo = json.dumps(datos).encode("utf-8")
        if len(crudo) > _TAM - 3:
            datos = {clave: datos[clave]}
            crudo = json.dumps(datos).encode("utf-8")
        nvm[0:3 + len(crudo)] = _MAGIA + bytes([len(crudo)]) + crudo
    except Exception:
        pass


def borrar(nvm=None):
    try:
        nvm = _nvm() if nvm is None else nvm
        nvm[0:2] = bytes(2)
    except Exception:
        pass
