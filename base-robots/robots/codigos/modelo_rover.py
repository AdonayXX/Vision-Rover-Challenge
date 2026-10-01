"""Modelo de movimiento del rover y predicción de su pose actual.

Los números salen de pc/calibrar_movimiento.py (modelo_movimiento.json).

Por qué hace falta predecir: entre que el rover recibe una orden y la visión
publica una imagen que la refleja pasan ~500 ms. A 170 mm/s son ~8 cm. El
controlador decide sobre la pose PREDICHA, no sobre la última vista.

La cuenta de tiempos no necesita separar el retraso de los motores del de la
cámara: una imagen con marca `ts` refleja todas las órdenes emitidas antes de
`ts - retraso_ms` (lo que mide la calibración como retraso de arranque). Lo
que una orden nueva puede cambiar es lo que viene después de todas las órdenes
ya emitidas; por eso se integran las emitidas entre `ts - retraso_ms` y ahora.

Convención del contrato: col a la derecha, row hacia abajo, theta antihorario
con cero hacia la derecha. Se trabaja con el CENTRO DE GIRO, no con el
marcador, que está `desfase_marcador_mm` por delante: al girar en el sitio el
marcador se desplaza varios centímetros aunque el rover no avance.
"""
import math


def _num(valor, defecto):
    return defecto if valor is None else float(valor)


class ModeloRover:
    def __init__(self, k_lineal=630.0, k_giro=715.0, zona_muerta_giro=0.056,
                 desfase_marcador_mm=30.0, retraso_ms=290.0, latencia_minima_ms=150.0,
                 zona_muerta_lineal=0.0):
        self.k_lineal = k_lineal              # mm/s por unidad de potencia
        # Potencia por debajo de la cual el rover NO avanza (roce). Sin ella el
        # predictor "cree" que a 0,09 avanza 60 mm/s y el rover se para antes.
        self.zona_muerta_lineal = zona_muerta_lineal
        # Correccion en marcha (autonomia.Adaptador): la bateria y el suelo
        # cambian la velocidad real; medido el 1-oct, el giro bajo a la mitad
        # en una hora. 1.0 = lo calibrado.
        self.escala_lineal = 1.0
        self.escala_giro = 1.0
        self.k_giro = k_giro                  # grados/s por unidad, girando en el sitio
        self.zona_muerta_giro = zona_muerta_giro
        self.desfase_marcador_mm = desfase_marcador_mm
        self.retraso_ms = retraso_ms
        self.latencia_minima_ms = latencia_minima_ms

    @classmethod
    def desde_resumen(cls, resumen):
        """Construye el modelo con el bloque `resumen` de modelo_movimiento.json."""
        familias = resumen.get("familias") or {}
        giros = [familias.get(n) for n in ("giro_izq", "giro_der") if familias.get(n)]
        latencia = resumen.get("latencia_vision_ms") or {}
        modelo = cls()
        modelo.k_lineal = _num(resumen.get("avance_mm_s_por_unidad"), modelo.k_lineal)
        avance = familias.get("avance")
        if avance and avance["zona_muerta"] > 0:
            # Con maniobras de baja potencia la recta con zona muerta describe
            # mejor el avance. El retroceso se satura y su ajuste es peor.
            modelo.k_lineal = avance["k_por_unidad"]
            modelo.zona_muerta_lineal = avance["zona_muerta"]
        if giros:
            modelo.k_giro = sum(g["k_por_unidad"] for g in giros) / len(giros)
            modelo.zona_muerta_giro = max(0.0, sum(g["zona_muerta"] for g in giros) / len(giros))
        modelo.desfase_marcador_mm = _num(resumen.get("desfase_marcador_mm"), modelo.desfase_marcador_mm)
        modelo.retraso_ms = _num(resumen.get("retraso_arranque_ms"), modelo.retraso_ms)
        modelo.latencia_minima_ms = _num(latencia.get("min"), modelo.latencia_minima_ms)
        return modelo

    # -------------------------------------------------------- cinemática
    def velocidades(self, izquierda, derecha):
        """(mm/s, grados/s) que produce un par de potencias."""
        avance = (izquierda + derecha) / 2
        giro = (derecha - izquierda) / 2
        magnitud = abs(giro)
        if abs(avance) < self.zona_muerta_giro:
            # Girar en el sitio tiene zona muerta; en marcha el roce ya cedió.
            magnitud = max(0.0, magnitud - self.zona_muerta_giro)
        signo = 1 if giro >= 0 else -1
        efectivo = max(0.0, abs(avance) - self.zona_muerta_lineal)
        k_lineal = self.k_lineal * self.escala_lineal
        return (k_lineal * efectivo if avance >= 0 else -k_lineal * efectivo,
                signo * self.k_giro * self.escala_giro * magnitud)

    def potencias(self, v_mm_s, w_deg_s, limite=0.35):
        """Inversa de velocidades(): potencias para lograr (v, w)."""
        avance = 0.0
        if v_mm_s:
            avance = abs(v_mm_s) / (self.k_lineal * self.escala_lineal) + self.zona_muerta_lineal
            if v_mm_s < 0:
                avance = -avance
        giro = abs(w_deg_s) / (self.k_giro * self.escala_giro)
        if giro > 0 and abs(avance) < self.zona_muerta_giro:
            giro += self.zona_muerta_giro
        if w_deg_s < 0:
            giro = -giro
        izquierda, derecha = avance - giro, avance + giro
        mayor = max(abs(izquierda), abs(derecha))
        if mayor > limite:
            # Se escala el par completo: conserva la curvatura pedida.
            izquierda, derecha = izquierda * limite / mayor, derecha * limite / mayor
        return izquierda, derecha

    # -------------------------------------------------------- marcos
    def centro_desde_marcador(self, pose, cell_mm):
        th = math.radians(pose["theta"])
        d = self.desfase_marcador_mm / cell_mm
        return {"col": pose["col"] - d * math.cos(th),
                "row": pose["row"] + d * math.sin(th),
                "theta": pose["theta"] % 360}


class Predictor:
    """Recuerda las órdenes emitidas y las integra sobre una pose observada."""

    def __init__(self, modelo, memoria_ms=3000):
        self.modelo, self.memoria_ms = modelo, memoria_ms
        self.ordenes = []                     # (t_ms local, izquierda, derecha)

    def registrar(self, t_ms, izquierda, derecha):
        if self.ordenes and self.ordenes[-1][1:] == (izquierda, derecha):
            return
        self.ordenes.append((t_ms, izquierda, derecha))
        corte = t_ms - self.memoria_ms
        # Se conserva la última orden anterior al corte: sigue vigente.
        while len(self.ordenes) > 1 and self.ordenes[1][0] <= corte:
            self.ordenes.pop(0)

    def orden_en(self, t_ms):
        vigente = (0.0, 0.0)
        for t, izquierda, derecha in self.ordenes:
            if t > t_ms:
                break
            vigente = (izquierda, derecha)
        return vigente

    def predecir(self, pose, desde_ms, hasta_ms, cell_mm, paso_ms=20):
        col, row, theta = pose["col"], pose["row"], pose["theta"]
        t = desde_ms
        while t < hasta_ms:
            dt = min(paso_ms, hasta_ms - t) / 1000
            v, w = self.modelo.velocidades(*self.orden_en(t))
            medio = math.radians(theta + w * dt / 2)
            col += v * dt * math.cos(medio) / cell_mm
            row -= v * dt * math.sin(medio) / cell_mm
            theta += w * dt
            t += paso_ms
        return {"col": col, "row": row, "theta": theta % 360}
