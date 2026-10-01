"""Movimientos cortos separados por una observación posterior a la parada.

No interpreta una republicación TCP como una imagen nueva. El ts_ms de
captura y la edad individual del rover determinan cuándo se puede decidir
otro movimiento, aun si la cámara publica con retraso.
"""
import time


class VisualSteps:
    def __init__(self, vision, pulse_seconds=.12, turn_seconds=.10,
                 settle_seconds=.08, monotonic=time.monotonic,
                 wall=time.time, sleep=time.sleep, max_steps=60):
        if type(max_steps) is not int or max_steps < 1:
            raise ValueError("Limite de pulsos invalido")
        self.vision = vision
        self.pulse_seconds, self.turn_seconds = pulse_seconds, turn_seconds
        self.settle_seconds = settle_seconds
        self.monotonic, self.wall, self.sleep = monotonic, wall, sleep
        self.after_ms = None
        self.direction_previous = None
        self.waiting_fresh = False
        self.steps = 0
        self.max_steps = max_steps

    def ready(self, state):
        if self.after_ms is None:
            return True
        rover = state.rover(state.robot_id)
        if rover is None:
            return False
        # Una posición recordada no es una observación posterior al movimiento.
        observed_ms = state.message["ts_ms"] - rover["age_ms"]
        if observed_ms <= self.after_ms:
            return False
        # El cubo y los obstaculos tambien deben haberse observado DESPUES
        # del pulso; una pose nueva del rover no rejuvenece los demas objetos.
        return all(state.message["ts_ms"] - item["age_ms"] > self.after_ms
                   for group in ("cubes", "obstacles", "rovers")
                   for item in state.message.get(group, []))

    def direction(self, error):
        sign = 1 if error > 0 else -1
        # +179 y -179 son prácticamente el mismo rumbo. El ruido no debe
        # alternar el sentido elegido cuando el objetivo está a la espalda.
        if self.direction_previous is None or abs(error) < 150:
            self.direction_previous = sign
        return self.direction_previous

    def execute(self, robot, state, command, is_fresh, action, error=None):
        if self.steps >= self.max_steps:
            robot.stop()
            raise RuntimeError("Limite de pulsos alcanzado; prueba detenida")
        if not self.ready(state) or not is_fresh():
            robot.stop()
            return False
        turning = action == "GIRAR"
        duration = self.turn_seconds if turning else self.pulse_seconds
        if turning and error is not None:
            duration *= max(.4, min(1., abs(error) / 25.))
        # Si la imagen caduca antes de acabar el pulso, el pulso se aborta a
        # medias y la prueba se cancela. Mejor esperar al siguiente cuadro.
        max_age = getattr(state, "max_age_ms", None)
        if max_age is not None and state.capture_age_ms() + duration * 1000 >= max_age:
            if not self.waiting_fresh:
                print("Imagen demasiado vieja para un pulso completo; esperando otra.", flush=True)
                self.waiting_fresh = True
            robot.stop()
            return False
        self.waiting_fresh = False
        if not turning:
            self.direction_previous = None
        rover = state.rover(state.robot_id)
        self.steps += 1
        print("Paso {}: {} | theta={:.1f} | error={} | captura={:.0f} ms | pulso={:.0f} ms | cmd={}".format(
            self.steps, action, rover["theta"], "-" if error is None else "{:+.1f}".format(error),
            state.capture_age_ms(), duration * 1000, command), flush=True)
        # El plazo empieza ANTES de esperar el ACK, no después: el motor puede
        # estar funcionando mientras la respuesta viaja por Wi-Fi.
        deadline = self.monotonic() + duration
        stop_reason = "fin_de_pulso"
        try:
            robot.send(command, force=True)
            while self.monotonic() < deadline:
                self.vision.poll()
                if not is_fresh():
                    stop_reason = "telemetria_vencida_o_perdida"
                    break
                self.sleep(min(.01, max(0, deadline - self.monotonic())))
        except OSError as error:
            stop_reason = "error_TCP"
            raise ConnectionError("El rover no confirmo {} por TCP: {}".format(action, error)) from error
        except BaseException:
            stop_reason = "interrupcion_o_error"
            raise
        finally:
            confirmed = robot.stop()
            self.after_ms = (self.wall() + self.settle_seconds) * 1000
            print("STOP paso={} motivo={} confirmado={}".format(self.steps, stop_reason, confirmed), flush=True)
        if not confirmed:
            raise ConnectionError("El rover no confirmo la parada del paso; prueba detenida")
        if stop_reason != "fin_de_pulso":
            raise RuntimeError("Prueba cancelada: " + stop_reason)
        return True
