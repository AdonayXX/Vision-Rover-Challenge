"""Diagnóstico en vivo del detector de cubos sobre la cámara real.

No cambia ningún umbral. Muestra la misma imagen rectificada que consume
``vision.sistema`` y, para cada componente coloreado que cae dentro de la
cancha, informa por qué pasa o por qué se descarta:

* área relativa a la cara esperada del cubo;
* matiz y croma medios en Lab;
* color más cercano y distancia angular;
* residuo del ajuste del modelo y si es confiable.

Uso desde ``vision-system``::

    python -m vision.tools.diagnostico_cubos
    python -m vision.tools.diagnostico_cubos --camara "Logitech C270"

Teclas: ``q``/Esc sale; ``g`` guarda el cuadro anotado y la máscara.
"""

from __future__ import annotations

import argparse
import math
import time
from dataclasses import replace
from types import SimpleNamespace

import cv2
import numpy as np

try:  # como paquete
    from ..configuracion import cargar_config
    from ..detectors.cubos import ajustar_cubo, clasificar, mascara_de_color, matiz_y_croma
    from ..geometry.coordenadas import (
        ErrorGeometria,
        construir_sistema,
        detectar_marcadores_crudo,
        pose_camara,
    )
    from ..sistema import abrir_fuente
except ImportError:  # como script suelto
    from vision.configuracion import cargar_config  # type: ignore[no-redef]
    from vision.detectors.cubos import (  # type: ignore[no-redef]
        ajustar_cubo,
        clasificar,
        mascara_de_color,
        matiz_y_croma,
    )
    from vision.geometry.coordenadas import (  # type: ignore[no-redef]
        ErrorGeometria,
        construir_sistema,
        detectar_marcadores_crudo,
        pose_camara,
    )
    from vision.sistema import abrir_fuente  # type: ignore[no-redef]


VERDE = (70, 220, 70)
AMARILLO = (0, 210, 255)
ROJO = (60, 60, 240)
BLANCO = (245, 245, 245)
NEGRO = (0, 0, 0)


def _marcadores_esquina(imagen: np.ndarray, cfg) -> tuple[dict[int, np.ndarray], tuple[int, ...]]:
    """Conserva solo los ArUco de esquina y reporta duplicados ajenos.

    El diagnóstico de cubos no necesita IDs de rover ni IDs espurios. Un falso
    positivo duplicado como el 17 no debe cerrar la herramienta. En cambio, si
    se duplica uno de los IDs 0-3 no elegimos uno al azar: se omite ese ID para
    que ``construir_sistema`` declare que no hay geometría válida ese cuadro.
    """
    esperados = cfg.marcadores_esquina.ids_esperados
    por_id: dict[int, list[np.ndarray]] = {}
    duplicados_ajenos: set[int] = set()
    for id_aruco, esquinas in detectar_marcadores_crudo(
        imagen,
        cfg.marcadores_esquina.nombre_diccionario,
        cfg.deteccion_marcadores.refinamiento_esquinas,
    ):
        if id_aruco not in esperados:
            if id_aruco in por_id:
                duplicados_ajenos.add(id_aruco)
            por_id.setdefault(id_aruco, []).append(esquinas)
            continue
        por_id.setdefault(id_aruco, []).append(esquinas)

    esquinas_validas = {
        id_aruco: candidatos[0]
        for id_aruco, candidatos in por_id.items()
        if id_aruco in esperados and len(candidatos) == 1
    }
    return esquinas_validas, tuple(sorted(duplicados_ajenos))


def _distancia_angular(a: float, b: float) -> float:
    return abs((a - b + 180.0) % 360.0 - 180.0)


def _color_mas_cercano(matiz: float, cfg) -> tuple[str | None, float]:
    if not cfg.deteccion_cubos.matices_grados:
        return None, 360.0
    pares = [
        (nombre, _distancia_angular(matiz, referencia))
        for nombre, referencia in cfg.deteccion_cubos.matices_grados.items()
    ]
    return min(pares, key=lambda par: par[1])


def _area_cara_px(sistema, cfg) -> float:
    lado = cfg.elementos.cubos.lado_mm / cfg.tablero.cell_mm
    extremos = np.array([[0.0, 0.0], [lado, 0.0]], dtype=np.float64)
    px = sistema.a_pixeles(extremos)
    lado_px = float(np.hypot(px[1, 0] - px[0, 0], px[1, 1] - px[0, 1]))
    return max(1.0, lado_px ** 2)


def _dentro_de_cancha(sistema, centro_px: tuple[float, float], cfg) -> bool:
    celda = sistema.a_celdas(np.array([[centro_px[0], centro_px[1]]], dtype=np.float64))[0]
    margen = 2.0
    return (
        -margen <= float(celda[0]) <= cfg.tablero.cols + margen
        and -margen <= float(celda[1]) <= cfg.tablero.rows + margen
    )


def _analizar(imagen: np.ndarray, cfg, sistema, pose):
    mascara, lab = mascara_de_color(imagen, cfg)
    cantidad, etiquetas, stats, centroides = cv2.connectedComponentsWithStats(mascara, 8)
    area_ref = _area_cara_px(sistema, cfg)
    dc = cfg.deteccion_cubos
    area_min = area_ref * dc.area_minima_relativa
    area_max = area_ref * dc.area_maxima_relativa
    lado_celdas = cfg.elementos.cubos.lado_mm / cfg.tablero.cell_mm
    nadir = np.array(pose.nadir_celdas, dtype=np.float64)
    factor = pose.factor_paralaje(cfg.elementos.cubos.lado_mm)

    resultados = []
    for etiqueta in range(1, cantidad):
        area = int(stats[etiqueta, cv2.CC_STAT_AREA])
        cx, cy = (float(v) for v in centroides[etiqueta])
        if not _dentro_de_cancha(sistema, (cx, cy), cfg):
            continue

        x = int(stats[etiqueta, cv2.CC_STAT_LEFT])
        y = int(stats[etiqueta, cv2.CC_STAT_TOP])
        w = int(stats[etiqueta, cv2.CC_STAT_WIDTH])
        h = int(stats[etiqueta, cv2.CC_STAT_HEIGHT])
        region = (etiquetas == etiqueta).astype(np.uint8)
        matiz, croma = matiz_y_croma(cv2.mean(lab, mask=region)[:3])
        cercano, distancia = _color_mas_cercano(matiz, cfg)
        area_rel = area / area_ref
        area_ok = area_min <= area <= area_max
        color = clasificar(matiz, cfg) if area_ok else None
        residuo = None
        confiable = False

        if not area_ok:
            motivo = "AREA BAJA" if area < area_min else "AREA ALTA"
        elif color is None:
            if cercano not in cfg.elementos.cubos.colores:
                motivo = "COLOR RESERVADO {}".format(cercano)
            else:
                motivo = "MATIZ FUERA"
        else:
            contornos, _ = cv2.findContours(region, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
            if not contornos:
                motivo = "SIN CONTORNO"
            else:
                contorno_px = max(contornos, key=cv2.contourArea).reshape(-1, 2).astype(np.float64)
                if len(contorno_px) > 120:
                    contorno_px = contorno_px[:: max(1, len(contorno_px) // 120)]
                contorno = sistema.a_celdas(contorno_px)
                _, _, _, residuo = ajustar_cubo(
                    contorno, lado_celdas, nadir, factor, cfg,
                )
                confiable = residuo <= dc.residuo_maximo_celdas
                motivo = "OK" if confiable else "RESIDUO ALTO"

        resultados.append({
            "bbox": (x, y, w, h),
            "centro": (cx, cy),
            "area": area,
            "area_rel": area_rel,
            "matiz": matiz,
            "croma": croma,
            "cercano": cercano,
            "distancia": distancia,
            "color": color,
            "residuo": residuo,
            "confiable": confiable,
            "motivo": motivo,
        })

    resultados.sort(key=lambda r: r["area"], reverse=True)
    return mascara, resultados, area_ref


def _dibujar(imagen: np.ndarray, mascara: np.ndarray, resultados, cfg, area_ref: float) -> np.ndarray:
    lienzo = imagen.copy()
    alto, ancho = lienzo.shape[:2]
    dc = cfg.deteccion_cubos

    for i, r in enumerate(resultados[:12], 1):
        x, y, w, h = r["bbox"]
        color = VERDE if r["confiable"] else AMARILLO if r["color"] else ROJO
        cv2.rectangle(lienzo, (x, y), (x + w, y + h), color, 2)
        etiqueta = "#{} {} {:.2f}x H{:.1f} C{:.1f}".format(
            i, r["motivo"], r["area_rel"], r["matiz"], r["croma"],
        )
        if r["residuo"] is not None:
            etiqueta += " R{:.3f}".format(r["residuo"])
        ty = max(18, y - 7)
        cv2.putText(lienzo, etiqueta, (x, ty), cv2.FONT_HERSHEY_SIMPLEX,
                    0.48, NEGRO, 3, cv2.LINE_AA)
        cv2.putText(lienzo, etiqueta, (x, ty), cv2.FONT_HERSHEY_SIMPLEX,
                    0.48, color, 1, cv2.LINE_AA)

    mascara_bgr = cv2.cvtColor((mascara * 255).astype(np.uint8), cv2.COLOR_GRAY2BGR)
    extras = " ".join(
        "{}>={:.1f}".format(color, minimo)
        for color, minimo in sorted(dc.croma_minimo_por_color.items())
    )
    titulo_mascara = "MASCARA croma >= {:.1f}".format(dc.croma_minimo)
    if extras:
        titulo_mascara += " | " + extras
    cv2.putText(mascara_bgr, titulo_mascara,
                (15, 28), cv2.FONT_HERSHEY_SIMPLEX, 0.72, BLANCO, 2, cv2.LINE_AA)
    cv2.putText(mascara_bgr,
                "area valida {:.2f}x..{:.2f}x | residuo <= {:.3f}".format(
                    dc.area_minima_relativa, dc.area_maxima_relativa,
                    dc.residuo_maximo_celdas),
                (15, 56), cv2.FONT_HERSHEY_SIMPLEX, 0.56, BLANCO, 1, cv2.LINE_AA)

    # La mitad derecha es la máscara exacta usada por el detector. Así se ve de
    # inmediato si una cara verde queda perforada o partida por falta de croma.
    if mascara_bgr.shape[:2] != (alto, ancho):
        mascara_bgr = cv2.resize(mascara_bgr, (ancho, alto))
    return np.hstack((lienzo, mascara_bgr))


def _linea_resultado(r) -> str:
    residuo = "-" if r["residuo"] is None else "{:.3f}".format(r["residuo"])
    return (
        "{} | area={:.2f}x | H={:.1f}° C={:.1f} | cercano={} d={:.1f}° | "
        "residuo={}".format(
            r["motivo"], r["area_rel"], r["matiz"], r["croma"],
            r["cercano"], r["distancia"], residuo,
        )
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Diagnóstico en vivo de cubos por Lab/área/residuo.")
    parser.add_argument("--config", default=None)
    parser.add_argument("--indice", type=int, default=None)
    parser.add_argument("--camara", default=None, help="perfil de calibración, por nombre")
    parser.add_argument(
        "--croma-prueba",
        type=float,
        default=None,
        help=(
            "umbral de croma temporal para esta corrida; no modifica config_vision.json "
            "(por defecto usa el valor configurado)"
        ),
    )
    args = parser.parse_args(argv)

    cfg = cargar_config(args.config) if args.config else cargar_config()
    croma_original = cfg.deteccion_cubos.croma_minimo
    if args.croma_prueba is not None:
        cfg = replace(
            cfg,
            deteccion_cubos=replace(
                cfg.deteccion_cubos,
                croma_minimo=float(args.croma_prueba),
            ),
        )
    fuente_args = SimpleNamespace(sintetico=False, indice=args.indice, camara=args.camara)
    fuente, descripcion, _ = abrir_fuente(cfg, fuente_args)
    print("Diagnóstico de cubos sobre {}".format(descripcion))
    print("No se modifica config_vision.json. q/Esc sale; g guarda imagen.")
    if args.croma_prueba is not None:
        print(
            "Croma temporal de prueba: {:.1f} (config real: {:.1f})".format(
                cfg.deteccion_cubos.croma_minimo, croma_original
            )
        )

    ventana = "Diagnostico de cubos — imagen | mascara Lab"
    ultimo_informe = 0.0
    ultimo_lienzo = None

    with fuente:
        while True:
            cuadro = fuente.leer()
            if cuadro is None:
                time.sleep(0.01)
                continue

            imagen = cuadro.imagen
            detectados, duplicados_ajenos = _marcadores_esquina(imagen, cfg)
            try:
                sistema = construir_sistema(imagen, cfg, detectados)
                pose = pose_camara(sistema, fuente.matriz_camara)
                mascara, resultados, area_ref = _analizar(imagen, cfg, sistema, pose)
                lienzo = _dibujar(imagen, mascara, resultados, cfg, area_ref)
                if duplicados_ajenos:
                    cv2.putText(
                        lienzo,
                        "IDs duplicados ajenos ignorados: {}".format(
                            ",".join(str(i) for i in duplicados_ajenos)
                        ),
                        (20, lienzo.shape[0] - 18),
                        cv2.FONT_HERSHEY_SIMPLEX,
                        0.5,
                        AMARILLO,
                        1,
                        cv2.LINE_AA,
                    )
            except ErrorGeometria as exc:
                mascara, _ = mascara_de_color(imagen, cfg)
                resultados = []
                mascara_bgr = cv2.cvtColor((mascara * 255).astype(np.uint8), cv2.COLOR_GRAY2BGR)
                lienzo = np.hstack((imagen.copy(), mascara_bgr))
                cv2.putText(lienzo, "SIN GEOMETRIA: {}".format(exc), (20, 35),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.55, ROJO, 2, cv2.LINE_AA)

            ultimo_lienzo = lienzo
            ahora = time.monotonic()
            if ahora - ultimo_informe >= 1.0:
                ultimo_informe = ahora
                print("\n--- candidatos dentro de la cancha ---")
                if not resultados:
                    print("ninguno")
                for i, r in enumerate(resultados[:8], 1):
                    print("#{:02d} {}".format(i, _linea_resultado(r)))

            cv2.imshow(ventana, lienzo)
            tecla = cv2.waitKey(1) & 0xFF
            if tecla in (ord("q"), 27):
                break
            if tecla == ord("g") and ultimo_lienzo is not None:
                nombre = "diagnostico_cubos_{}.png".format(int(time.time()))
                cv2.imwrite(nombre, ultimo_lienzo)
                print("guardado: {}".format(nombre))

    cv2.destroyWindow(ventana)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
