# Estados y acuerdos de tareas

Ya existe un coordinador de tareas y una réplica por robot. El coordinador debe vivir en el **rover de menor ID**, no en una computadora externa durante la competencia. Por ahora los tres objetos se ejecutan en la PC y los mensajes se intercambian en memoria para probar el protocolo.

## Demostración sin hardware

Desde la raíz del repositorio:

```powershell
python -B base-robots/robots/pc/demo_coordinacion.py
```

La demostración toma una propuesta del asignador y comprueba:

1. Ambos rovers reservan e inician su primer cubo.
2. Dejan de recibir confirmaciones recientes: ambos pierden el permiso de tarea y conservan las reservas.
3. Recuperan la comunicación, sincronizan estados y recuperan el permiso.
4. Se inyectan observaciones de los cubos dentro de sus destinos y se registran entregas.
5. El robot con dos tareas puede reservar la siguiente después de entregar la primera.

Resultado comprobado: tres tareas ENTREGADO y revisión final 9. **No es una misión física completada:** la demostración mueve las coordenadas de los cubos directamente a sus zonas para verificar transiciones y evidencia. No ejecuta rutas ni empuja cubos.

## Estados y transiciones

| Estado | Significado | Transición permitida |
|---|---|---|
| LIBRE | Sin reserva activa, aunque el plan inicial ya indica a quién corresponde | RESERVAR, sólo por el rover asignado y respetando el orden |
| RESERVADO | Dueño confirmado; todavía no tiene permiso de desplazamiento por esta tarea | INICIAR o LIBERAR, sólo por el dueño |
| EN_TRASLADO | Tarea iniciada y confirmada; incluye la aproximación al cubo | ENTREGAR, con evidencia de visión |
| ENTREGADO | Entrega registrada localmente | Terminal; no vuelve a reservarse |

Cada rover sólo puede tener una tarea RESERVADO o EN_TRASLADO. Una tarea en traslado no se libera automáticamente ni por una petición LIBERAR. La cancelación segura de una tarea ya iniciada requiere un protocolo futuro de parada y confirmación.

## Acuerdo, versiones y confirmación

Cada solicitud lleva versión de protocolo de coordinación, identificador de sesión (`ronda`), emisor, número de solicitud, revisión conocida, operación y color. **Este protocolo de coordinación es independiente del contrato oficial de visión**, que permanece sin cambios.

- Un coordinador fijo es la única autoridad que modifica el registro.
- Cada cambio incrementa la revisión del registro completo.
- Una solicitud con revisión vieja recibe rechazo y el estado actual. El cliente se sincroniza y crea otra solicitud, sin aplicar el cambio a ciegas.
- Repetir la misma solicitud devuelve la respuesta guardada y no repite el cambio. Sólo se guarda la última solicitud por emisor, manteniendo memoria acotada.
- Reutilizar el mismo número con otro contenido o enviar uno anterior no modifica tareas.
- La réplica sólo acepta respuestas del coordinador, de su sesión y para su solicitud pendiente.
- Mientras un cambio espera confirmación, el permiso de tarea es falso. Reservar por sí solo tampoco da permiso: debe confirmarse INICIAR.

`sender_id` se pasa aparte del contenido. En la radio real deberá obtenerse de una asociación MAC→ID previamente validada; confiar solamente en el campo `emisor` de un mensaje no identifica al remitente.

## Pérdida de comunicación

El plazo de ejemplo es 0.5 segundos. Las réplicas consultan periódicamente con PING y reciben el registro. Este PING corresponde a **coordinación**, no al protocolo del servidor de motores de pruebas.

La frescura se mide desde que se envió la solicitud, no desde que llegó la respuesta. Así un mensaje retrasado no concede otros 0.5 segundos como si fuera nuevo. Una respuesta fuera del plazo o de una solicitud anterior no renueva el permiso. Un duplicado tampoco renueva la presencia del rover en el coordinador.

Si el compañero deja de consultar, el coordinador informa que el equipo no está en línea. Si el coordinador deja de responder, la réplica vence por su propio reloj. La reserva se mantiene para evitar que otro robot asuma un cubo que todavía podría estar siendo manipulado.

**No hay elección automática de otro coordinador ni recuperación de reinicio.** No se debe recrear un registro vacío bajo la misma sesión mientras algún rover siga funcionando. La recuperación tras reiniciar requiere detener y acordar otra sesión antes de usar la lógica; durante una ronda debe respetarse la restricción de reinicios del reglamento.

## Entregas

ENTREGAR exige una observación reciente del cubo y que quede completamente dentro de su zona usando el criterio conservador de media diagonal del contrato. No basta con el centro apenas dentro del rectángulo. Puede registrarse la última entrega en FINISHED si la evidencia sigue fresca, pero esa fase no permite trabajar.

Es un registro **local de tarea**, basado en una observación. No sustituye el tiempo de permanencia, conteo ni veredicto oficial del árbitro. El cubo podría moverse después de registrarlo: la vigilancia posterior y la reapertura controlada de una entrega no están implementadas.

## Integración pendiente

`TaskReplica.can_work(color, vision)` devuelve un permiso de **tarea**. Todavía no acciona motores ni garantiza que haya un camino libre. El futuro bucle del rover deberá combinar:

```text
permiso de tarea reciente
    + telemetría y fase válidas
    + próximo tramo comprobado
    + sensores y condiciones de parada
```

Una ruta bloqueada deberá detener el movimiento y recalcularse conservando la tarea; el coordinador no cambia reservas por eventos de navegación. Esa unión con el ejecutor de rutas aún está pendiente.

También faltan el transporte ESP-NOW real, la adaptación de tamaño/serialización de mensajes, retransmisiones periódicas, el arranque común de sesión, mediciones de latencia y memoria en CircuitPython. La lógica actual mantiene el plan inicial: no reasigna automáticamente el tercero si otro rover termina antes de lo previsto.

## Archivos y verificación

- [coordinacion.py](codigos/coordinacion.py): coordinador, réplica y comprobación local de entrega.
- [demo_coordinacion.py](pc/demo_coordinacion.py): intercambio y pérdidas simuladas.
- [test_coordinacion.py](tests/test_coordinacion.py): 16 pruebas nuevas.

**93 pruebas pasan** en total. Las nuevas cubren exclusividad, revisión concurrente, pérdida de confirmación, duplicados, IDs de solicitud reutilizados, timeout, respuestas tardías, sesión/remitente incorrectos, bloqueo de segunda tarea, entrega fuera de zona o vieja, liberación, fase final y snapshots inválidos.

```powershell
python -B -m unittest discover -s base-robots/robots/tests -v
```
