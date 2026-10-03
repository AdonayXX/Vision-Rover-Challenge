"""Sistema de coordenadas anclado a los cuatro marcadores de esquina.

Qué resuelve
------------
La cámara ve **píxeles**; el contrato publica **celdas**. Este módulo construye
el puente entre los dos, usando como única referencia los cuatro marcadores
ArUco pegados en las esquinas de la cancha.

Por qué una homografía y no una simple escala
---------------------------------------------
Porque la cámara real nunca va a estar perfectamente cenital. Con cualquier
inclinación, el tablero se ve como un trapecio y no como un rectángulo: una
escala daría bien en el centro y mal en los bordes. La homografía es la
transformación exacta entre dos planos vistos en perspectiva, y el tablero es
un plano. Cuatro puntos —los cuatro centros de marcador— la determinan por
completo.

Por qué los centros y no las esquinas de los marcadores
-------------------------------------------------------
El centro de un marcador es el promedio de sus cuatro esquinas detectadas, así
que promedia el ruido de las cuatro en vez de arrastrar el de una sola. Además
es lo único medible sin ambigüedad en la cancha física: "el centro del
marcador" no admite discusión, "su esquina superior izquierda" sí.

Separar detectar de decidir
---------------------------
`detectar_marcadores` solo mira la imagen y dice qué encontró. `construir_sistema`
decide si eso alcanza y arma las coordenadas. Son dos responsabilidades
distintas y fallan por motivos distintos (CLAUDE.md, sección 6).
"""

from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np

try:  # como paquete
    from ..configuracion import REFINAMIENTOS, ConfigVision, diccionario_aruco
except ImportError:  # como script suelto
    from vision.configuracion import (  # type: ignore[no-redef]
        REFINAMIENTOS, ConfigVision, diccionario_aruco,
    )


def parametros_detector(refinamiento: str = "ninguno"):
    """Los parámetros con los que corre el detector de ArUco.

    Existe para que el **refinamiento de esquinas** sea configuración y no una
    constante enterrada en una llamada. De las cuatro esquinas detectadas sale
    todo lo demás: el centro que ancla las coordenadas, el ángulo del rover y el
    lado que mide el filtro de plausibilidad, así que media fracción de píxel
    ahí se propaga a todo.

    El resto de los parámetros queda como los trae OpenCV, a propósito. Con
    `DICT_4X4_50` la corrección de errores ya está apagada de hecho —el
    diccionario declara un solo bit corregible, OpenCV lo multiplica por la tasa
    y trunca, así que con el 0,6 de fábrica el resultado es cero— y bajarla no
    cambiaría nada. Verificado con el detector: un marcador con un bit volteado
    no se detecta con la tasa en 0,6 y sí se detecta con la tasa en 1,0.
    """
    parametros = cv2.aruco.DetectorParameters()
    nombre = REFINAMIENTOS.get(refinamiento)
    if nombre is None:
        raise ValueError(
            "refinamiento de esquinas desconocido: {!r}; válidos: {}".format(
                refinamiento, sorted(REFINAMIENTOS))
        )
    parametros.cornerRefinementMethod = getattr(cv2.aruco, nombre)
    return parametros


class ErrorGeometria(Exception):
    """No se pudo establecer el sistema de coordenadas a partir de la imagen.

    Se levanta excepción en vez de devolver `None` a propósito: un `None` que
    nadie mira se convierte en coordenadas basura publicadas como si fueran
    buenas. El "falla abierto" del CLAUDE.md se implementa **arriba**, en el
    bucle de proceso, que atrapa esto y conserva el último estado bueno; no
    obligando a cada llamador a acordarse de comprobar el retorno.
    """


@dataclass(frozen=True, slots=True, eq=False)
class SistemaCoordenadas:
    """Convierte entre píxeles de la imagen y celdas de la cancha.

    Es inmutable: cada cuadro produce el suyo. Si los marcadores se mueven —o la
    cámara se corre— el sistema del cuadro siguiente es otro objeto, y el
    anterior sigue siendo válido para lo que ya se calculó con él.

    `eq=False` porque guarda matrices de NumPy.
    """

    a_celdas_h: np.ndarray  # homografía píxeles -> celdas
    a_pixeles_h: np.ndarray  # la inversa, útil para dibujar sobre la imagen
    cols: int
    rows: int
    cell_mm: float
    centros_px: dict[int, tuple[float, float]]

    def a_celdas(self, puntos_px: np.ndarray) -> np.ndarray:
        """Convierte puntos en píxeles a celdas. Recibe y devuelve (N, 2)."""
        return _aplicar(self.a_celdas_h, puntos_px)

    def a_pixeles(self, celdas: np.ndarray) -> np.ndarray:
        """Convierte celdas a píxeles. Recibe y devuelve (N, 2)."""
        return _aplicar(self.a_pixeles_h, celdas)

    def celda_de(self, x: float, y: float) -> tuple[float, float]:
        """Versión cómoda para un solo punto."""
        p = self.a_celdas(np.array([[x, y]], dtype=np.float64))
        return (float(p[0, 0]), float(p[0, 1]))


def _aplicar(h: np.ndarray, puntos: np.ndarray) -> np.ndarray:
    puntos = np.asarray(puntos, dtype=np.float64).reshape(-1, 1, 2)
    return cv2.perspectiveTransform(puntos, h).reshape(-1, 2)


class ErrorDuplicado(ErrorGeometria):
    """Dos marcadores distintos decodificaron el MISMO ID en un mismo cuadro.

    Es una subclase de `ErrorGeometria` para que el falla-abierto del bucle de
    proceso la atrape igual que a las demás: se descarta el cuadro y se conserva
    el último estado bueno.

    Por qué merece ser un error y no un desempate cualquiera
    --------------------------------------------------------
    Porque el desempate silencioso es exactamente el error más caro que puede
    cometer este sistema. Si el ID repetido es el de un **rover**, el rover se
    publica por un cuadro en un punto cualquiera del tablero **con edad cero**,
    o sea presentado como fresco y seguro, y el seguimiento conserva esa
    posición pisada hasta la próxima detección buena. Si es el de una
    **esquina**, la homografía se rearma con un marcador falso y **todas** las
    coordenadas salen mal, sin una sola queja: con los cuatro "visibles" la
    comprobación de desvío ni siquiera interviene, porque esa solo actúa cuando
    falta uno.
    """


def detectar_marcadores_crudo(
    imagen: np.ndarray, nombre_diccionario: str, refinamiento: str = "ninguno"
) -> tuple[tuple[int, np.ndarray], ...]:
    """**Todas** las detecciones del cuadro, sin colapsar por ID.

    Es la salida tal cual la devuelve OpenCV: una tupla de `(id, esquinas)` que
    puede repetir un ID. Existe porque el diccionario por ID **destruye
    información antes de que nadie la mire**: si dos marcadores dicen ser el 10,
    al armar el diccionario ya no hay forma de saber que hubo dos, ni de elegir
    cuál. Todo lo que quiera decidir entre ellos —o simplemente contarlos, como
    el diagnóstico de falsos positivos— tiene que partir de acá.
    """
    if imagen.ndim == 3:
        imagen = cv2.cvtColor(imagen, cv2.COLOR_BGR2GRAY)
    detector = cv2.aruco.ArucoDetector(
        diccionario_aruco(nombre_diccionario), parametros_detector(refinamiento)
    )
    esquinas, ids, _ = detector.detectMarkers(imagen)
    if ids is None:
        return ()
    return tuple(
        (int(id_aruco), esquina.reshape(4, 2).astype(np.float64))
        for id_aruco, esquina in zip(ids.ravel(), esquinas)
    )


def detectar_marcadores(
    imagen: np.ndarray, nombre_diccionario: str, refinamiento: str = "ninguno"
) -> dict[int, np.ndarray]:
    """Detecta los marcadores ArUco de la imagen. Lanza si hay un ID repetido.

    Devuelve `{id: esquinas}` con las esquinas como (4, 2) en orden TL, TR, BR,
    BL. No juzga si son los que hacen falta: eso es decidir, y lo hace
    `construir_sistema`.

    **Un ID repetido es un error, no un empate que se resuelve solo.** Antes el
    segundo marcador pisaba al primero según el orden en que OpenCV barrió la
    imagen, sin dejar rastro. Quien pueda resolverlo con contexto —el bucle de
    proceso, que tiene la homografía guardada y la última pose de cada rover—
    usa `resolver_duplicados`; quien no, se entera.
    """
    marcadores: dict[int, np.ndarray] = {}
    repetidos = []
    for id_aruco, esquinas in detectar_marcadores_crudo(
            imagen, nombre_diccionario, refinamiento):
        if id_aruco in marcadores:
            repetidos.append(id_aruco)
        marcadores[id_aruco] = esquinas
    if repetidos:
        raise ErrorDuplicado(
            "el mismo ID aparece más de una vez en el cuadro: {}. Sin contexto no se "
            "puede decidir cuál es el bueno, y quedarse con cualquiera sería pisar un "
            "marcador de verdad en silencio.".format(sorted(set(repetidos)))
        )
    return marcadores


def lado_mm_de(esquinas_px: np.ndarray, sistema: SistemaCoordenadas) -> float:
    """Cuánto mide el lado de un marcador **sobre el plano del tablero**.

    En píxeles un tamaño no significa nada comparable: el mismo marcador se ve
    más chico cerca del borde de la imagen que en el centro, y con la cámara
    inclinada la diferencia crece. La homografía deshace exactamente eso, así
    que en celdas un cuadrado vuelve a ser un cuadrado del tamaño que es.

    Se promedian los cuatro lados en vez de tomar uno: reparte el ruido de las
    cuatro esquinas detectadas en lugar de arrastrar el de una.
    """
    celdas = sistema.a_celdas(np.asarray(esquinas_px, dtype=np.float64).reshape(4, 2))
    lados = [float(np.linalg.norm(celdas[(i + 1) % 4] - celdas[i])) for i in range(4)]
    return sum(lados) / 4.0 * sistema.cell_mm


@dataclass(frozen=True, slots=True)
class Duplicado:
    """Un ID que apareció más de una vez en un cuadro, y cómo terminó.

    Se informa **resuelto o no**: un duplicado resuelto no es un no-evento, es
    un fantasma que estuvo a punto de pisar un marcador de verdad. La cuenta de
    estos es la que va a decir si el problema se agrava cuando cambie la luz o
    el tablero.
    """

    id: int
    lados_mm: tuple[float, ...]
    ganador_mm: float | None
    resuelto: bool
    motivo: str


def _desvio_del_esperado(
    id_aruco: int,
    esquinas_px: np.ndarray,
    cfg: ConfigVision,
    sistema: SistemaCoordenadas,
    ultimas_poses_rover: dict[int, tuple[float, float]],
    pose: "PoseCamara | None",
) -> tuple[float, float] | None:
    """`(desvío, lado_mm)` de un candidato respecto de lo que se espera de SU ID.

    Devuelve `None` si el ID no está declarado —ni esquina ni rover—, porque de
    esos no se espera nada: nadie los usa y no hay contra qué compararlos.

    El desvío combina dos cosas **en unidades del propio marcador**, para no
    tener que ponderar milímetros contra celdas a mano:

    - el error **relativo de tamaño**, que es adimensional por definición;
    - la distancia a donde debería estar, **dividida por el lado esperado**.

    Un fantasma de 15 mm que dice ser una esquina de 100 mm y aparece a media
    cancha de su sitio no pierde por poco: pierde por dos órdenes de magnitud.
    """
    esquinas_ids = cfg.marcadores_esquina.ids_esperados
    if id_aruco in esquinas_ids:
        lado_esperado = cfg.marcadores_esquina.lado_mm
        celda_esperada = cfg.marcadores_esquina.disposicion[id_aruco]
    elif id_aruco in cfg.deteccion_rovers.ids_rover:
        # El marcador del rover está a 80 mm del tablero, así que NO está en el
        # plano de la homografía: se ve más grande y corrido hacia afuera. Las
        # dos cosas las da la pose de cámara, y las dos hay que aplicarlas, o la
        # comparación mezcla espacios distintos.
        altura = cfg.paralaje.altura_marcador_rover_mm
        factor = pose.factor_paralaje(altura) if pose is not None else 1.0
        lado_esperado = cfg.elementos.marcador_rover.lado_mm * factor
        celda_esperada = ultimas_poses_rover.get(id_aruco)
        if celda_esperada is not None and pose is not None:
            # La memoria del seguidor guarda la posición YA corregida, y los
            # candidatos se miden sin corregir: hay que elevar la esperada a
            # donde SE VE, no bajar el candidato. Sin esto, el propio marcador
            # legítimo arrastra un desvío de 0,6 —26 mm de paralaje sobre 41,6
            # de lado— que no dice nada de su plausibilidad.
            elevada = pose.elevar(np.array([celda_esperada], dtype=np.float64), altura)[0]
            celda_esperada = (float(elevada[0]), float(elevada[1]))
    else:
        return None

    lado = lado_mm_de(esquinas_px, sistema)
    desvio = abs(lado - lado_esperado) / lado_esperado
    if celda_esperada is not None:
        celdas = sistema.a_celdas(np.asarray(esquinas_px, dtype=np.float64).reshape(4, 2))
        col, row = centro_de(celdas)
        distancia_mm = float(np.hypot(col - celda_esperada[0], row - celda_esperada[1]))
        distancia_mm *= sistema.cell_mm
        desvio += distancia_mm / lado_esperado
    return desvio, lado


@dataclass(frozen=True, slots=True)
class Rechazo:
    """Un marcador detectado que NO es plausible, y por qué.

    Se informa en vez de descartarse en silencio: la cuenta de rechazos es la
    que va a decir si el problema se agrava —otra luz, otro tablero, otra
    cámara— y, sobre todo, si alguna vez el filtro empieza a comerse marcadores
    de verdad. Un filtro mudo que rechaza de más es indistinguible de una
    cámara que no ve.
    """

    id: int
    motivo: str          # "tamaño" o "posición"
    lado_mm: float
    esperado_mm: float
    col: float
    row: float


def _lado_esperado_mm(id_aruco: int, cfg: ConfigVision, pose: "PoseCamara | None") -> float | None:
    """Cuánto DEBERÍA medir el marcador de ese ID, o `None` si no se sabe.

    El del rover no es una constante: está a 80 mm del tablero, así que se ve
    más grande, y el factor sale de la pose de cámara. Eso regala una
    comprobación gratis: si lo medido se apartara de lo teórico, hay algo mal en
    la altura declarada o en la pose, y se ve en el aviso.
    """
    if id_aruco in cfg.marcadores_esquina.ids_esperados:
        return cfg.marcadores_esquina.lado_mm
    if id_aruco in cfg.deteccion_rovers.ids_rover:
        altura = cfg.paralaje.altura_marcador_rover_mm
        factor = pose.factor_paralaje(altura) if pose is not None else 1.0
        return cfg.elementos.marcador_rover.lado_mm * factor
    return None


def filtrar_plausibles(
    crudos: tuple[tuple[int, np.ndarray], ...],
    cfg: ConfigVision,
    sistema: SistemaCoordenadas | None,
    pose_rover: "PoseCamara | None" = None,
) -> tuple[tuple[tuple[int, np.ndarray], ...], tuple[Rechazo, ...]]:
    """Descarta lo que no puede ser un marcador de esta cancha.

    Dos preguntas, las dos con información que el sistema ya tiene y ninguna con
    un umbral inventado:

    **¿Mide lo que tiene que medir?** El lado se mide en milímetros sobre el
    plano del tablero con la homografía, y se compara contra el esperado con la
    tolerancia declarada. Medido sobre la cancha real: los marcadores legítimos
    caen entre −8,3 % y +0 % del esperado, y las 361 detecciones falsas de
    cuatro corridas midieron **siempre** entre 13,2 y 18,0 mm, contra los 41,6
    del marcador del rover. Un factor 2,3 de separación no necesita ajuste fino.

    **¿Está donde puede haber un marcador?** Fuera de la cancha más un margen no
    hay nada que detectar. El margen no es cero: el paralaje empuja hacia afuera
    y un rover sobre el borde se publica legítimamente en columna negativa.

    Sin geometría —el primer cuadro— no hay con qué medir, así que **no se
    filtra nada**: es preferible dejar pasar un fantasma que rechazar al
    marcador que está por establecer las coordenadas.

    Se filtra ANTES de resolver duplicados, y el orden importa: un fantasma que
    cae por tamaño deja de disputar el ID, así que el duplicado desaparece en
    vez de tener que resolverse. Medido en la cancha, eso convierte trece
    disputas por minuto en ninguna.
    """
    if sistema is None:
        return crudos, ()

    tolerancia = cfg.deteccion_marcadores.tolerancia_tamano
    margen = cfg.deteccion_marcadores.margen_fuera_de_cancha_celdas
    cols, rows = cfg.tablero.cols, cfg.tablero.rows

    aceptados = []
    rechazos = []
    for id_aruco, esquinas in crudos:
        celdas = sistema.a_celdas(np.asarray(esquinas, dtype=np.float64).reshape(4, 2))
        col, row = centro_de(celdas)
        lado = lado_mm_de(esquinas, sistema)

        if not (-margen <= col <= cols + margen and -margen <= row <= rows + margen):
            rechazos.append(Rechazo(id=id_aruco, motivo="posición", lado_mm=lado,
                                    esperado_mm=0.0, col=col, row=row))
            continue

        esperado = _lado_esperado_mm(id_aruco, cfg, pose_rover)
        # De un ID que no es ni esquina ni rover no se espera NADA, así que no
        # hay contra qué compararlo. No hace falta: la lista blanca de IDs ya lo
        # descarta más adelante, y el sistema lo informa.
        if esperado is not None and abs(lado - esperado) > tolerancia * esperado:
            rechazos.append(Rechazo(id=id_aruco, motivo="tamaño", lado_mm=lado,
                                    esperado_mm=esperado, col=col, row=row))
            continue

        aceptados.append((id_aruco, esquinas))
    return tuple(aceptados), tuple(rechazos)


def resolver_duplicados(
    crudos: tuple[tuple[int, np.ndarray], ...],
    cfg: ConfigVision,
    sistema: SistemaCoordenadas | None,
    ultimas_poses_rover: dict[int, tuple[float, float]] | None = None,
    pose_rover: "PoseCamara | None" = None,
) -> tuple[dict[int, np.ndarray], tuple[Duplicado, ...]]:
    """Arma el diccionario por ID resolviendo los duplicados por plausibilidad.

    Lanza `ErrorDuplicado` cuando un duplicado **no se puede** resolver, que es
    lo correcto: entre dos candidatos igual de plausibles, elegir es adivinar, y
    el falla-abierto conserva el último estado bueno, que vale más que una
    posición inventada.

    Por qué no se descarta el cuadro siempre
    ----------------------------------------
    Porque los duplicados van a ser la norma, no la excepción. Todos los equipos
    corren con los IDs 10 y 11, así que en cada ronda hay un marcador real 10
    sobre el tablero y del orden de veintitrés fantasmas 10 por minuto chocando
    contra él. Descartar el cuadro entero tiraría más del 1 % de los cuadros en
    plena ronda, y por un motivo que el sistema **puede resolver solo**: mide
    los dos candidatos y se queda con el que se parece al marcador que espera.

    `sistema` es la homografía **guardada** del cuadro anterior. Alcanza y sobra
    porque la cámara está atornillada, y es lo único que permite medir tamaños
    en milímetros. Sin ella —en el primer cuadro— no hay con qué decidir.

    `pose_rover` es la pose de cámara deducida de esa misma geometría guardada.
    Sirve para dos cosas, y las dos hacen falta: saber cuánto **agranda** el
    paralaje al marcador del rover, y saber cuánto lo **corre**, para poder
    comparar contra una memoria que está guardada ya corregida.
    """
    ultimas_poses_rover = ultimas_poses_rover or {}
    candidatos: dict[int, list[np.ndarray]] = {}
    for id_aruco, esquinas in crudos:
        candidatos.setdefault(id_aruco, []).append(esquinas)

    marcadores: dict[int, np.ndarray] = {}
    duplicados: list[Duplicado] = []
    for id_aruco, lista in candidatos.items():
        if len(lista) == 1:
            marcadores[id_aruco] = lista[0]
            continue

        if sistema is None:
            raise ErrorDuplicado(
                "el ID {} aparece {} veces y todavía no hay una geometría guardada con "
                "la cual medirlos. No hay forma de decidir cuál es el bueno.".format(
                    id_aruco, len(lista))
            )

        evaluados = [
            (_desvio_del_esperado(id_aruco, e, cfg, sistema, ultimas_poses_rover, pose_rover), e)
            for e in lista
        ]
        medidos = [(d[0], d[1], e) for d, e in evaluados if d is not None]
        if not medidos:
            # ID no declarado: ni esquina ni rover. Nadie lo usa, así que el
            # duplicado no hace daño; se informa igual porque es un fantasma más
            # y la cuenta importa.
            lados = tuple(lado_mm_de(e, sistema) for e in lista)
            marcadores[id_aruco] = lista[0]
            duplicados.append(Duplicado(
                id=id_aruco, lados_mm=lados, ganador_mm=lados[0], resuelto=True,
                motivo="ID no declarado: no es esquina ni rover, así que nadie lo usa",
            ))
            continue

        medidos.sort(key=lambda x: x[0])
        mejor_desvio, mejor_lado, mejor_esquinas = medidos[0]
        lados = tuple(m[1] for m in medidos)
        margen = cfg.deteccion_marcadores.margen_decision_duplicados
        segundo_desvio = medidos[1][0] if len(medidos) > 1 else float("inf")

        if mejor_desvio > margen * segundo_desvio:
            raise ErrorDuplicado(
                "el ID {} aparece {} veces y ninguno de los candidatos es claramente el "
                "bueno: lados de {} mm, desvíos de {:.3f} y {:.3f}. Elegir entre dos "
                "candidatos igual de plausibles sería adivinar.".format(
                    id_aruco, len(lista),
                    ", ".join("{:.1f}".format(x) for x in lados),
                    mejor_desvio, segundo_desvio)
            )

        marcadores[id_aruco] = mejor_esquinas
        duplicados.append(Duplicado(
            id=id_aruco, lados_mm=lados, ganador_mm=mejor_lado, resuelto=True,
            motivo="gana por {:.0f}x: desvío {:.3f} contra {:.3f}".format(
                segundo_desvio / mejor_desvio if mejor_desvio > 0 else float("inf"),
                mejor_desvio, segundo_desvio),
        ))
    return marcadores, tuple(duplicados)


def _cruz(a: np.ndarray, b: np.ndarray) -> float:
    """Producto cruz de dos vectores 2D: el escalar `ax*by - ay*bx`.

    A mano y no con `np.cross` porque en NumPy 2 el caso de dos dimensiones está
    deprecado, y son dos multiplicaciones.
    """
    return float(a[0] * b[1] - a[1] * b[0])


def centro_de(esquinas: np.ndarray) -> tuple[float, float]:
    """Centro de un marcador: la **intersección de sus dos diagonales**.

    Por qué no el promedio de las cuatro esquinas
    ---------------------------------------------
    Porque bajo perspectiva **está sesgado**. El promedio es una operación afín,
    y la proyección en perspectiva no lo es: el promedio de las cuatro esquinas
    *proyectadas* no es la proyección del centro. Cuando la cámara mira el
    tablero con algo de ángulo, el lado del marcador que quedó más lejos se ve
    más chico, y el promedio se corre hacia el lado que se ve más grande.

    La intersección de las diagonales, en cambio, **sí se conserva**: una
    proyección manda rectas en rectas, así que manda las diagonales del cuadrado
    en las diagonales del cuadrilátero visto, y su punto de cruce en el punto de
    cruce. Es exacto, no una aproximación mejor.

    El sesgo crece con el tamaño del marcador —cuanta más superficie, más
    perspectiva a lo ancho de la propia marca— y por eso apareció recién al
    alinear el generador sintético con los marcadores reales de 100 mm: con los
    60 mm nominales de antes quedaba escondido bajo el ruido. Es un error de la
    cancha física, no del dibujo.

    Sigue usando las cuatro esquinas, así que sigue repartiendo el ruido de
    detección en vez de confiar en una sola.
    """
    p = np.asarray(esquinas, dtype=np.float64).reshape(4, 2)
    # Diagonales del cuadrilátero: TL->BR y TR->BL. Las esquinas vienen en el
    # orden TL, TR, BR, BL, que es el que devuelve OpenCV.
    origen_a, direccion_a = p[0], p[2] - p[0]
    origen_b, direccion_b = p[1], p[3] - p[1]

    denominador = _cruz(direccion_a, direccion_b)
    if abs(denominador) < 1e-12:
        # Diagonales paralelas: el cuadrilátero está degenerado (marcador visto
        # de canto, o una detección rota). No hay punto de cruce que devolver,
        # así que se cae al promedio, que al menos siempre existe.
        c = p.mean(axis=0)
        return (float(c[0]), float(c[1]))

    t = _cruz(origen_b - origen_a, direccion_b) / denominador
    centro = origen_a + t * direccion_a
    return (float(centro[0]), float(centro[1]))


class AnclajeCancha:
    """Mantiene el sistema de coordenadas cuadro a cuadro, aguantando un marcador menos.

    Por qué hace falta
    ------------------
    `construir_sistema` exige los cuatro marcadores, y con razón: una homografía
    tiene **ocho grados de libertad** y cada punto aporta dos ecuaciones, así que
    cuatro puntos la determinan justo. Con tres solo alcanza para una
    transformación **afín**, y lo que falta son exactamente los términos de
    perspectiva. Medido contra la verdad del generador, con la cámara a 8°: la
    afín erra **36 mm** donde la homografía erra 0,52.

    Pero reajustar no es la única opción, y no es la mejor.

    La cámara está atornillada
    --------------------------
    Los marcadores están pegados al tablero y la cámara no se mueve durante una
    ronda: **la homografía es prácticamente constante**. Recalcularla en cada
    cuadro no es una necesidad sino una función de robustez, para reanclarse solo
    si alguien la golpea.

    Entonces, con tres visibles, lo correcto es **conservar la última buena**. La
    precisión no se degrada nada, porque es literalmente la misma homografía.

    Y los tres que quedan sirven para vigilar
    -----------------------------------------
    Conservar una homografía vieja sería un desastre silencioso si la cámara se
    movió. Pero tres marcadores alcanzan de sobra para **detectarlo**: se los
    reproyecta con la homografía guardada y se mira si caen donde deben.

    La comprobación es **conservadora por construcción**: siempre acusa más de lo
    que el error realmente vale. Medido, con la cámara movida 0,25°, los tres
    acusan 1,58 mm mientras el error real de posición es 0,92. Por eso el umbral
    en milímetros de desvío se traduce en un error real menor.

    No hay límite de tiempo para seguir así, y es a propósito: lo que autoriza a
    conservar la homografía no es que haya pasado poco tiempo, sino que los tres
    marcadores visibles **siguen confirmándola en cada cuadro**. La salvaguarda
    es la verificación, no un cronómetro.
    """

    def __init__(self, cfg: ConfigVision):
        self._cfg = cfg
        self._sistema: SistemaCoordenadas | None = None
        #: Cuántos cuadros seguidos se viene conservando la homografía.
        self.cuadros_conservados = 0
        #: Cuántas esquinas se vieron en el último cuadro.
        self.esquinas_visibles = 0
        #: Cuánto se desviaron las visibles de donde deberían estar, en mm.
        self.desvio_mm = 0.0

    def actualizar(self, imagen: np.ndarray, detectados: dict[int, np.ndarray]) -> SistemaCoordenadas:
        """Devuelve el sistema de coordenadas de este cuadro.

        Lanza `ErrorGeometria` cuando no se puede sostener: con dos marcadores o
        menos, o cuando los tres visibles delatan que la cámara se movió.
        """
        esperados = self._cfg.marcadores_esquina.ids_esperados
        visibles = sorted(esperados & set(detectados))
        self.esquinas_visibles = len(visibles)

        if len(visibles) == 4:
            self._sistema = construir_sistema(imagen, self._cfg, detectados)
            self.cuadros_conservados = 0
            self.desvio_mm = 0.0
            return self._sistema

        if self._sistema is None:
            raise ErrorGeometria(
                "hacen falta los cuatro marcadores de esquina para arrancar; se ven {}. "
                "Todavía no hay un sistema de coordenadas anterior que conservar.".format(visibles)
            )
        if len(visibles) < 3:
            raise ErrorGeometria(
                "solo se ven {} marcadores de esquina. Con menos de tres no se puede "
                "comprobar que la cámara no se haya movido, así que la homografía "
                "guardada deja de ser confiable.".format(len(visibles))
            )

        # Tres visibles: se conserva la homografía y se la somete a los tres.
        self.desvio_mm = self._desvio(detectados, visibles)
        if self.desvio_mm > self._cfg.marcadores_esquina.desvio_maximo_mm:
            self.cuadros_conservados = 0
            raise ErrorGeometria(
                "se ven 3 marcadores de esquina y NO confirman la geometría guardada: "
                "se desvían {:.2f} mm, más del máximo de {:.2f}. La cámara se movió, "
                "así que las coordenadas viejas ya no valen.".format(
                    self.desvio_mm, self._cfg.marcadores_esquina.desvio_maximo_mm)
            )
        self.cuadros_conservados += 1
        return self._sistema

    def _desvio(self, detectados: dict[int, np.ndarray], visibles: list[int]) -> float:
        """Cuánto se apartan los marcadores visibles de donde deberían caer.

        Se los pasa por la homografía guardada y se compara contra la celda que
        declara la configuración. Si la cámara no se movió, el desvío es el
        ruido de detección; si se movió, se dispara.
        """
        assert self._sistema is not None
        observados = np.array([centro_de(detectados[i]) for i in visibles], dtype=np.float64)
        recuperados = self._sistema.a_celdas(observados)
        declarados = np.array(
            [self._cfg.marcadores_esquina.disposicion[i] for i in visibles], dtype=np.float64
        )
        distancias = np.linalg.norm(recuperados - declarados, axis=1)
        return float(distancias.max()) * self._cfg.tablero.cell_mm

    @property
    def sistema(self) -> SistemaCoordenadas | None:
        """La última geometría buena, o `None` si todavía no hubo ninguna.

        La necesita la resolución de IDs duplicados, que tiene que **medir** los
        candidatos en milímetros **antes** de que la geometría de este cuadro
        exista —justo porque uno de esos candidatos podría ser el que la arme—.
        Usar la guardada es legítimo y no una aproximación: la cámara está
        atornillada, así que la homografía del cuadro anterior sigue valiendo.
        """
        return self._sistema

    @property
    def conservando(self) -> bool:
        """Si el cuadro actual está usando una homografía guardada."""
        return self.cuadros_conservados > 0


@dataclass(frozen=True, slots=True, eq=False)
class PoseCamara:
    """Dónde está la cámara respecto de la cancha, deducido de los marcadores.

    Nadie mide esto con una cinta: sale de los cuatro marcadores de esquina, que
    el sistema ya tiene que ver de todas formas. Si alguien mueve la cámara, el
    cuadro siguiente trae una pose nueva y nadie tiene que acordarse de nada.

    Para qué hace falta
    -------------------
    Las coordenadas NO la necesitan: la homografía de los cuatro centros alcanza
    y sobra. La necesitan las dos cosas que dependen de que los objetos tengan
    **altura**, porque los marcadores de esquina están al ras y no saben nada de
    eso:

    - la **corrección de paralaje**, que necesita `altura_mm` y `nadir_celdas`;
    - la **detección de cubos**, que necesita saber hacia dónde está el nadir
      para distinguir la base de la tapa.

    `nadir_celdas` es la celda justo debajo de la cámara. Es el centro de la
    homotecia del paralaje: un objeto ahí no se corre nada por alto que sea.
    """

    nadir_celdas: tuple[float, float]
    altura_mm: float
    error_reproyeccion_px: float

    def factor_paralaje(self, altura_objeto_mm: float) -> float:
        """`H/(H−h)`: cuánto se agranda lo que se ve de un objeto elevado."""
        if altura_objeto_mm <= 0 or altura_objeto_mm >= self.altura_mm:
            return 1.0
        return self.altura_mm / (self.altura_mm - altura_objeto_mm)

    def a_ras(self, celdas: np.ndarray, altura_objeto_mm: float) -> np.ndarray:
        """Corrige el paralaje: de dónde SE VE un objeto elevado a dónde ESTÁ.

        Es traer el punto hacia el nadir en la proporción `(H−h)/H`. Exacto para
        cualquier inclinación de cámara, porque el rayo solo depende del centro
        óptico y no de hacia dónde mire.
        """
        celdas = np.asarray(celdas, dtype=np.float64).reshape(-1, 2)
        nadir = np.array(self.nadir_celdas, dtype=np.float64)
        return nadir + (celdas - nadir) / self.factor_paralaje(altura_objeto_mm)

    def elevar(self, celdas: np.ndarray, altura_objeto_mm: float) -> np.ndarray:
        """El camino de vuelta: de dónde ESTÁ un objeto a dónde SE VE."""
        celdas = np.asarray(celdas, dtype=np.float64).reshape(-1, 2)
        nadir = np.array(self.nadir_celdas, dtype=np.float64)
        return nadir + (celdas - nadir) * self.factor_paralaje(altura_objeto_mm)


def pose_camara(sistema: SistemaCoordenadas, matriz_camara: np.ndarray) -> PoseCamara:
    """Deduce dónde está la cámara a partir de los marcadores de esquina.

    Los cuatro centros son puntos **coplanares de posición métrica conocida** —
    están sobre el tablero, separados por `cols × cell_mm`— y la cámara está
    calibrada. Con eso, `solvePnP` da la pose completa sin ningún dato más.

    `matriz_camara` tiene que ser la de la imagen **ya rectificada**, que es
    `Rectificador.matriz_nueva` y no la del perfil: quitar la distorsión cambia
    los intrínsecos efectivos, y usar los de antes metería un error que después
    nadie sabría de dónde salió.

    Se devuelve el error de reproyección para que quien la use pueda decidir si
    creerle. Es el único control disponible: no hay una verdad contra la cual
    comparar en la cancha real.
    """
    ids = sorted(sistema.centros_px)
    if len(ids) < 4:
        raise ErrorGeometria(
            "hacen falta los cuatro marcadores de esquina para deducir la pose de cámara"
        )

    # Mundo: X = col·cell, Y = −row·cell, Z hacia arriba. El menos en Y es la
    # misma convención del generador, y es lo que hace que la imagen no salga
    # espejada con una cámara que mira hacia abajo.
    objeto = []
    imagen = []
    for id_aruco in ids:
        col, row = sistema.celda_de(*sistema.centros_px[id_aruco])
        objeto.append([col * sistema.cell_mm, -row * sistema.cell_mm, 0.0])
        imagen.append(list(sistema.centros_px[id_aruco]))

    objeto = np.array(objeto, dtype=np.float64)
    imagen = np.array(imagen, dtype=np.float64)

    ok, rvec, tvec = cv2.solvePnP(
        objeto, imagen, np.asarray(matriz_camara, dtype=np.float64),
        np.zeros(5, dtype=np.float64), flags=cv2.SOLVEPNP_IPPE,
    )
    if not ok:
        raise ErrorGeometria("solvePnP no pudo resolver la pose de la cámara")

    rot, _ = cv2.Rodrigues(rvec)
    # El centro óptico en coordenadas del mundo.
    centro = (-rot.T @ tvec).ravel()

    reproyectado, _ = cv2.projectPoints(
        objeto, rvec, tvec, np.asarray(matriz_camara, dtype=np.float64),
        np.zeros(5, dtype=np.float64),
    )
    error = float(np.linalg.norm(reproyectado.reshape(-1, 2) - imagen, axis=1).max())

    return PoseCamara(
        nadir_celdas=(float(centro[0] / sistema.cell_mm), float(-centro[1] / sistema.cell_mm)),
        altura_mm=float(centro[2]),
        error_reproyeccion_px=error,
    )


def construir_sistema(
    imagen: np.ndarray,
    cfg: ConfigVision,
    detectados: dict[int, np.ndarray] | None = None,
) -> SistemaCoordenadas:
    """Establece el sistema de coordenadas de la cancha a partir de una imagen.

    Exige los cuatro marcadores de esquina. Con tres no alcanza: una homografía
    necesita cuatro correspondencias, y con menos habría que suponer cosas sobre
    la cámara que no queremos suponer.

    `detectados` permite pasarle una detección ya hecha sobre ESTA misma imagen.
    Sirve para el bucle de proceso, que necesita los mismos marcadores para dos
    cosas —armar las coordenadas y encontrar los rovers— y no tiene por qué
    correr el detector de ArUco dos veces sobre el mismo cuadro. Si no se pasa,
    detecta por su cuenta, que es lo que hace falta para usarlo suelto.
    """
    if detectados is None:
        detectados = detectar_marcadores(imagen, cfg.marcadores_esquina.nombre_diccionario,
                                         cfg.deteccion_marcadores.refinamiento_esquinas)
    esperados = cfg.marcadores_esquina.ids_esperados
    faltantes = sorted(esperados - set(detectados))
    if faltantes:
        raise ErrorGeometria(
            "faltan marcadores de esquina: se esperaban {} y se detectaron {}. "
            "Revisar que los cuatro estén planos, completos, iluminados y con su "
            "zona blanca sin tapar.".format(sorted(esperados), sorted(detectados))
        )

    # El orden importa: cada centro en píxeles tiene que corresponderse con la
    # celda de SU marcador. Se recorre por ID para que no dependa del orden en
    # que el detector los haya devuelto.
    ids = sorted(esperados)
    origen_px = np.array([centro_de(detectados[i]) for i in ids], dtype=np.float32)
    destino_celdas = np.array(
        [cfg.marcadores_esquina.disposicion[i] for i in ids], dtype=np.float32
    )

    a_celdas_h = cv2.getPerspectiveTransform(origen_px, destino_celdas).astype(np.float64)
    a_pixeles_h = cv2.getPerspectiveTransform(destino_celdas, origen_px).astype(np.float64)

    return SistemaCoordenadas(
        a_celdas_h=a_celdas_h,
        a_pixeles_h=a_pixeles_h,
        cols=cfg.tablero.cols,
        rows=cfg.tablero.rows,
        cell_mm=cfg.tablero.cell_mm,
        centros_px={i: centro_de(detectados[i]) for i in ids},
    )
