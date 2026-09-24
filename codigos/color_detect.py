"""Prueba del sensor por colorimetría de reflexión secuencial RGB.

Cableado del rover probado:
    DI -> IO32
    AO -> IO33

La lectura de AO aumenta con la luz reflejada. Cada medición descuenta primero
la luz ambiente y la clasificación usa el canal con mayor reflexión.
"""

import board
import neopixel
import analogio
import keypad
from time import sleep
from ideaboard import IdeaBoard

# ==========================
# CONFIGURACIÓN
# ==========================

# Se repite el barrido completo para evitar que un pico aislado decida el color.
NUM_BARRIDOS = 7
MUESTRAS_POR_FASE = 20
TIEMPO_ASENTAMIENTO = 0.5
INTERVALO_MUESTRAS = 0.005
SENAL_MINIMA = 300
MARGEN_MINIMO = 0.10

ib = IdeaBoard()
ib.brightness = 0.2

# NeoPixel externo (iluminador)
pixel = neopixel.NeoPixel(
    board.IO32,
    1,
    brightness=1,
    auto_write=False
)
pixel[0] = (0, 0, 0)
pixel.show()

# Sensor de luz
luz = analogio.AnalogIn(board.IO33)

# Botón BOOT
boton = keypad.Keys(
    (board.IO0,),
    value_when_pressed=False,
    pull=True
)

# ==========================
# FUNCIONES
# ==========================

def mediana(valores):
    ordenados = sorted(valores)
    return ordenados[len(ordenados) // 2]


def lectura_activa(valores):
    """Usa la segunda lectura más alta: exige dos respuestas y descarta fallos."""
    ordenados = sorted(valores)
    return ordenados[-2]


def medir_color(color):
    """
    Enciende el LED del color indicado
    y retorna el promedio de la lectura.
    """

    pixel[0] = color
    pixel.show()

    sleep(TIEMPO_ASENTAMIENTO)

    total = 0

    for _ in range(MUESTRAS_POR_FASE):
        total += luz.value
        sleep(INTERVALO_MUESTRAS)

    pixel[0] = (0, 0, 0)
    pixel.show()

    return total / MUESTRAS_POR_FASE


def hacer_barrido():
    """Retorna ambiente y respuesta R/G/B después de descontar el ambiente."""
    ambiente = medir_color((0, 0, 0))
    raw = (
        medir_color((255, 0, 0)),
        medir_color((0, 255, 0)),
        medir_color((0, 0, 255)),
    )
    senal = tuple(max(0, valor - ambiente) for valor in raw)
    return ambiente, raw, senal


def detectar_color(senal):
    """Clasifica solo cuando existe señal y un canal gana claramente."""
    total = sum(senal)
    if total < SENAL_MINIMA:
        return None

    orden = sorted(((valor, indice) for indice, valor in enumerate(senal)), reverse=True)
    mayor, indice = orden[0]
    segundo = orden[1][0]
    if mayor <= 0 or (mayor - segundo) / mayor < MARGEN_MINIMO:
        return None
    return ("ROJO", "VERDE", "AZUL")[indice]


# ==========================
# PROGRAMA PRINCIPAL
# ==========================

print("Listo. Presione BOOT.")

while True:

    evento = boton.events.get()

    if evento and evento.released:
        ambientes = []
        raws = [[], [], []]

        print("Midiendo; mantenga el objeto quieto...")
        for _ in range(NUM_BARRIDOS):
            ambiente, raw, _senal = hacer_barrido()
            ambientes.append(ambiente)
            for indice in range(3):
                raws[indice].append(raw[indice])

        ambiente_final = mediana(ambientes)
        raw_final = [lectura_activa(valores) for valores in raws]
        # Consolidar primero cada fase evita mezclar fluctuaciones correlacionadas
        # del ambiente y del LED ocurridas en barridos distintos.
        senal_final = [max(0, valor - ambiente_final) for valor in raw_final]
        color = detectar_color(senal_final)

        print(
            "RAW ambiente/R/G/B: <{},{},{},{}>".format(
                int(ambiente_final),
                int(raw_final[0]),
                int(raw_final[1]),
                int(raw_final[2]),
            )
        )
        print(
            "REFLEXION R/G/B: <{},{},{}>".format(
                int(senal_final[0]),
                int(senal_final[1]),
                int(senal_final[2]),
            )
        )

        if color == "ROJO":
            ib.pixel = (255, 0, 0)
        elif color == "VERDE":
            ib.pixel = (0, 255, 0)
        elif color == "AZUL":
            ib.pixel = (0, 0, 255)
        else:
            ib.pixel = (0, 0, 0)

        print("Color detectado:", color or "DESCONOCIDO / INESTABLE")
        sleep(0.5)

    sleep(0.01)
