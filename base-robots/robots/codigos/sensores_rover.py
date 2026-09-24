"""Lecturas cooperativas y permiso local de movimiento; sin hardware al importar.

El ultrasonido no identifica el objeto. IR mide reflectancia, no distancia.
El color se aprende con muestras reales; sin perfiles NO se inventa una clase.
"""
import math
import time


def firma_color(raw, polarity=-1, minimum=300):
    if len(raw) != 4 or any(not math.isfinite(v) or not 0 <= v <= 65535 for v in raw):
        return None
    signal = [max(0, polarity * (v - raw[0])) for v in raw[1:]]
    total = sum(signal)
    return None if total < minimum else [v / total for v in signal]


def _perfiles_por_color(profiles):
    """Normaliza perfiles antiguos y perfiles separados por escenario."""
    result = {}
    for name, configured in profiles.items():
        if isinstance(configured, dict):
            values = list(configured.values())
        else:
            values = [configured]
        result[name] = values
    return result


def perfiles_completos(profiles):
    grouped = _perfiles_por_color(profiles)
    return all(grouped.get(name) for name in ("red", "green", "blue"))


def clasificar_color(signature, profiles, tolerance=.15, margin=.04):
    if signature is None or not perfiles_completos(profiles):
        return None
    distances = []
    for name, candidates in _perfiles_por_color(profiles).items():
        distances.append((min(
            sum((a - b) ** 2 for a, b in zip(signature, profile)) ** .5
            for profile in candidates
        ), name))
    distances.sort()
    if distances[0][0] > tolerance or distances[1][0] - distances[0][0] < margin:
        return None
    return distances[0][1]


def validar_config(cfg):
    if type(cfg.get("diagnostic_only", False)) is not bool or type(cfg["ultrasonic"].get("allow_unverified_echo_diagnostic", False)) is not bool:
        raise ValueError("Opciones de diagnostico deben ser booleanos")
    if type(cfg.get("enabled")) is not bool or type(cfg["ultrasonic"].get("echo_3v3_confirmed")) is not bool:
        raise ValueError("enabled y echo_3v3_confirmed deben ser booleanos")
    if cfg["ir"]["pins"] != ["IO36", "IO39", "IO34", "IO35"]:
        raise ValueError("IR requiere el cableado declarado IO36/IO39/IO34/IO35")
    if cfg["ultrasonic"]["trigger"] != "IO25" or cfg["ultrasonic"]["echo"] != "IO26":
        raise ValueError("Ultrasonido requiere Trig IO25 / Echo IO26")
    if cfg["color"]["led"] != "IO32" or cfg["color"]["analog"] not in ("IO4", "IO33"):
        raise ValueError("Color requiere LED IO32 y AO IO4 (bloqueado con Wi-Fi) o IO33 confirmado")
    def positivo(section, key, maximum):
        value = section[key]
        if not isinstance(value, (float, int)) or not math.isfinite(value) or not 0 < value <= maximum:
            raise ValueError("Parametro de sensores invalido: " + key)
    positivo(cfg, "max_age_ms", 1000)
    positivo(cfg["ultrasonic"], "stop_mm", 1000)
    positivo(cfg["color"], "settle_seconds", .5)
    brightness = cfg["color"].get("brightness", 1)
    if isinstance(brightness, bool) or not isinstance(brightness, (float, int)) or not math.isfinite(brightness) or not 0 < brightness <= 1:
        raise ValueError("brightness debe estar en (0, 1]")
    count = cfg["color"].get("samples_per_phase", 1)
    if type(count) is not int or count not in (1, 3, 5, 7, 9):
        raise ValueError("samples_per_phase debe ser impar entre 1 y 9")
    interval = cfg["color"].get("sample_interval_seconds", .01)
    if isinstance(interval, bool) or not isinstance(interval, (int, float)) or not math.isfinite(interval) or not 0 < interval <= .05:
        raise ValueError("sample_interval_seconds debe estar entre 0 y 0.05")
    sweeps = cfg["color"].get("sweeps_per_result", 1)
    if type(sweeps) is not int or not 1 <= sweeps <= 15:
        raise ValueError("sweeps_per_result debe estar entre 1 y 15")
    votes = cfg["color"].get("min_color_votes", 1)
    if type(votes) is not int or not 1 <= votes <= sweeps:
        raise ValueError("min_color_votes debe estar entre 1 y sweeps_per_result")
    positivo(cfg["color"], "min_signal", 65535 * 3)
    for key in ("tolerance", "margin"):
        positivo(cfg["color"], key, 2)
    if cfg["color"]["polarity"] not in (-1, 1):
        raise ValueError("Polaridad de color debe ser -1 o 1")
    for name, configured in cfg["color"]["profiles"].items():
        if name not in ("red", "green", "blue"):
            raise ValueError("Perfil de color invalido")
        if isinstance(configured, dict):
            if not configured or any(not isinstance(label, str) or not label for label in configured):
                raise ValueError("Escenario de color invalido")
            profiles = configured.values()
        else:
            profiles = (configured,)
        for profile in profiles:
            if not isinstance(profile, list) or len(profile) != 3:
                raise ValueError("Perfil de color invalido")
            if any(not math.isfinite(v) or not 0 <= v <= 1 for v in profile) or abs(sum(profile) - 1) > .01:
                raise ValueError("Perfil de color debe ser una firma normalizada")
    ranges = cfg["ir"]["floor_ranges"]
    if ranges is not None and (len(ranges) != 4 or any(
            len(r) != 2 or not 0 <= r[0] < r[1] <= 65535 for r in ranges)):
        raise ValueError("floor_ranges requiere cuatro pares minimo/maximo")


class SensoresRover:
    def __init__(self, hardware, cfg, clock=time.monotonic):
        validar_config(cfg)
        self.hw, self.cfg, self.clock = hardware, cfg, clock
        self.distance, self.ir, self.raw, self.signature, self.color = None, None, None, None, None
        self.distance_at = self.ir_at = self.color_at = None
        self.errors = dict(hardware.errors)
        self.next_ir = self.next_color = 0
        self.phase = 0
        self.samples = []
        self.phase_samples = []
        self.sweeps = []
        self.sweep_signatures = []
        self.color_seq = 0
        self.scanning = False

    def _set_pixel(self, color):
        self.hw.pixel[0] = color
        show = getattr(self.hw.pixel, "show", None)
        if show is not None:
            show()

    def _consolidate_sweeps(self):
        """Elige el barrido medoid y conserva las firmas completas para votar."""
        c = self.cfg["color"]
        candidates = []
        for sweep in self.sweeps:
            signature = firma_color(sweep, c["polarity"], c["min_signal"])
            if signature is not None:
                candidates.append((signature, sweep))
        self.sweep_signatures = [item[0] for item in candidates]
        if not candidates:
            return self.sweeps[-1][:], None
        def score(item):
            signature = item[0]
            return sum(sum((a - b) ** 2 for a, b in zip(signature, other[0])) ** .5
                       for other in candidates)
        signature, raw = min(candidates, key=score)
        return raw[:], signature

    def _vote_color(self):
        c = self.cfg["color"]
        counts = {}
        for signature in self.sweep_signatures:
            label = clasificar_color(
                signature, c["profiles"], c["tolerance"], c["margin"]
            )
            if label is not None:
                counts[label] = counts.get(label, 0) + 1
        ordered = sorted(((count, name) for name, count in counts.items()), reverse=True)
        if not ordered or ordered[0][0] < c.get("min_color_votes", 1):
            return None
        if len(ordered) > 1 and ordered[0][0] == ordered[1][0]:
            return None
        return ordered[0][1]

    def update(self, moving=False):
        now = self.clock()
        if self.hw.sonar is not None:
            try:
                ready, distance = self.hw.sonar.poll()
                if ready:
                    if distance is None or not math.isfinite(distance) or not 20 <= distance <= 4000:
                        self.distance = None
                        self.errors["ultrasonic"] = "sin_eco_valido"
                    else:
                        self.distance, self.distance_at = distance, self.clock()
                        self.errors.pop("ultrasonic", None)
            except Exception as exc:
                self.distance = None
                self.errors["ultrasonic"] = str(exc)
        if self.hw.ir is not None and now >= self.next_ir:
            self.next_ir = now + .05
            try:
                self.ir = [pin.value for pin in self.hw.ir]
                self.ir_at = self.clock()
                self.errors.pop("ir", None)
            except Exception as exc:
                self.ir = None
                self.errors["ir"] = str(exc)
        # Un barrido RGB mezcla objetos distintos si el rover se mueve.
        # Se mide detenido; el control por pasos ofrece esa ventana.
        if self.hw.light is None or self.hw.pixel is None:
            return
        try:
            if moving:
                self._set_pixel((0, 0, 0))
                self.scanning = False
                self.phase_samples = []
                self.samples = []
                self.sweeps = []
                self.sweep_signatures = []
                self.color = self.signature = self.raw = None
                self.color_at = None
                return
            if not self.scanning:
                self._set_pixel((0, 0, 0))
                self.phase, self.samples, self.scanning = 0, [], True
                self.phase_samples = []
                self.next_color = self.clock() + self.cfg["color"]["settle_seconds"]
                return
            if now < self.next_color:
                return
            # Una muestra por tick, separadas en el tiempo. No bloquear STOP,
            # ultrasonido ni watchdog con sleeps o bucles de espera.
            self.phase_samples.append(self.hw.light.value)
            c = self.cfg["color"]
            if len(self.phase_samples) < c.get("samples_per_phase", 1):
                self.next_color = self.clock() + c.get("sample_interval_seconds", .01)
                return
            ordered = sorted(self.phase_samples)
            self.samples.append(ordered[len(ordered) // 2])
            self.phase_samples = []
            self.phase += 1
            lights = ((0, 0, 0), (255, 0, 0), (0, 255, 0), (0, 0, 255))
            if self.phase == 4:
                c = self.cfg["color"]
                self.sweeps.append(self.samples[:])
                if len(self.sweeps) >= c.get("sweeps_per_result", 1):
                    self.raw, self.signature = self._consolidate_sweeps()
                    self.color = self._vote_color()
                    self.color_at = self.clock()
                    self.color_seq += 1
                    self.sweeps = []
                self.scanning = False
                self._set_pixel((0, 0, 0))
                self.errors.pop("color", None)
            else:
                self._set_pixel(lights[self.phase])
                self.next_color = self.clock() + self.cfg["color"]["settle_seconds"]
        except Exception as exc:
            self.color, self.signature, self.raw = None, None, None
            self.scanning = False
            self.samples = []
            self.phase_samples = []
            self.sweeps = []
            self.sweep_signatures = []
            self.errors["color"] = str(exc)
            self._set_pixel((0, 0, 0))

    def age(self, timestamp):
        return None if timestamp is None else max(0, int((self.clock() - timestamp) * 1000))

    def reason(self, left, right):
        if left == 0 and right == 0:
            return None
        if self.motion_inhibited:
            return "diagnostico_sin_motores" if self.cfg.get("diagnostic_only") else "echo_electrico_sin_verificar"
        if self.errors:
            return "sensores_no_listos: " + ", ".join(sorted(self.errors))
        limit = self.cfg["max_age_ms"]
        if self.ir is None or self.age(self.ir_at) >= limit:
            return "ir_sin_datos_frescos"
        ranges = self.cfg["ir"]["floor_ranges"]
        if ranges is not None and any(not lo <= v <= hi for v, (lo, hi) in zip(self.ir, ranges)):
            return "ir_fuera_del_suelo_calibrado"
        # La sonda frontal no protege la parte trasera ni los lados.
        if left + right > 0:
            if self.distance is None or self.age(self.distance_at) >= limit:
                return "ultrasonido_sin_datos_frescos"
            if self.distance <= self.cfg["ultrasonic"]["stop_mm"]:
                return "obstaculo_frontal"
        return None

    @property
    def motion_inhibited(self):
        return (self.cfg.get("diagnostic_only", False) or
                self.cfg["ultrasonic"].get("echo_3v3_confirmed") is not True)

    def snapshot(self):
        return {"v": 1, "enabled": True, "distance_mm": self.distance,
                "diagnostic_only": self.cfg.get("diagnostic_only", False),
                "echo_3v3_confirmed": self.cfg["ultrasonic"].get("echo_3v3_confirmed", False),
                "warnings": list(getattr(self.hw, "warnings", [])),
                "distance_age_ms": self.age(self.distance_at), "ir": self.ir,
                "ir_age_ms": self.age(self.ir_at),
                "ir_calibrated": self.cfg["ir"]["floor_ranges"] is not None,
                "color_raw": self.raw, "color_signature": self.signature,
                "color_sweep_signatures": self.sweep_signatures,
                "color": self.color, "color_age_ms": self.age(self.color_at),
                "color_seq": self.color_seq,
                "color_calibrated": perfiles_completos(self.cfg["color"]["profiles"]),
                "stop_mm": self.cfg["ultrasonic"]["stop_mm"], "errors": dict(self.errors)}
