# Reglamento

## Objetivo del reto

Desarrollar un sistema autónomo compuesto por dos robots tipo rover capaces de coordinarse para navegar una superficie delimitada, identificar objetos cúbicos de un color específico y transportarlos hasta una zona de acopio.

Una cámara superior y el sistema oficial de visión proporcionarán información global sobre la posición y orientación de los robots, la posición de los cubos, las zonas de acopio y el estado general de la prueba. A partir de esta información, los rovers deberán interpretar el entorno, distribuir tareas, planificar sus movimientos, coordinarse y corregir su comportamiento durante la ejecución.

La solución deberá integrar robótica móvil, comunicación inalámbrica, planificación de rutas, coordinación entre robots, control y autonomía.

A partir del cambio del sistema oficial de visión al estado `READY`, los rovers deberán operar sin intervención humana y sin que una computadora externa, servicio en la nube u otro dispositivo externo tome decisiones o modifique su planificación en tiempo real.

# Reglas del reto

## 1. Plataforma robótica

1.1. Cada equipo utilizará los dos robots oficiales entregados por la organización.

1.2. Los robots deberán utilizarse con su configuración física y electrónica original.

1.3. No se permite modificar, sustituir, remover ni agregar componentes físicos o electrónicos.

1.4. No se permite cambiar la tarjeta electrónica principal.

1.5. No se permite sustituir el microcontrolador.

1.6. No se permite utilizar otra tarjeta de desarrollo como controlador principal o auxiliar.

1.7. No se permite modificar el chasis, los motores, las ruedas, los sensores ni el sistema de alimentación.

1.8. No se permite agregar mecanismos de recolección, servomotores, estructuras impresas en 3D ni sensores adicionales.

1.9. No se permite reemplazar los robots entregados por otra plataforma robótica.

1.10. Se permite modificar únicamente el software y la programación de los robots.

---

## 2. Componentes incluidos en los robots

2.1. Cada robot será entregado completamente ensamblado.

2.2. Cada robot incluirá:

2.2.1. Sensor ultrasónico para medición de distancia y detección de obstáculos.

2.2.2. Acelerómetro para medir aceleraciones y cambios de movimiento.

2.2.3. Giroscopio para estimar orientación, rotación y cambios angulares.

2.2.4. Sensor de color para reconocer objetos cercanos.

2.2.5. Sensores infrarrojos para detección de la superficie cuadriculada.

2.2.6. Motores y sistema de locomoción diferencial.

2.2.7. Microcontrolador y tarjeta electrónica principal ESP32 IdeaBoard.

2.2.8. Sistema de alimentación por baterías.

2.2.9. Sistema de comunicación inalámbrica disponible en el ESP32.

2.3. Los equipos deberán desarrollar sus soluciones utilizando exclusivamente las capacidades disponibles en esta plataforma.

---

## 3. Entrega de robots y materiales

3.1. La organización entregará a cada equipo dos robots tipo rover sin costo.

3.2. La organización proporcionará los materiales oficiales necesarios para ejecutar el reto.

3.3. Los equipos no deberán comprar componentes para modificar los robots.

3.4. Los cubos, marcadores visuales, superficie de competencia y demás elementos oficiales del escenario serán suministrados por la organización.

3.5. La participación y el uso de los robots y materiales oficiales no tendrán costo para los equipos.

---

## 4. Programación de los robots

4.1. Los equipos podrán modificar el código ejecutado por el microcontrolador.

4.2. Los equipos podrán:

4.2.1. Programar el movimiento de los motores.

4.2.2. Procesar las mediciones de los sensores integrados.

4.2.3. Recibir y procesar la telemetría publicada por el sistema oficial de visión.

4.2.4. Implementar algoritmos de navegación y corrección de trayectoria.

4.2.5. Implementar algoritmos de asignación de tareas entre los dos rovers.

4.2.6. Desarrollar protocolos de comunicación entre los robots.

4.2.7. Implementar estrategias para evitar colisiones.

4.2.8. Implementar estrategias para empujar, orientar o transportar los cubos utilizando la estructura original del robot.

4.2.9. Utilizar los lenguajes, bibliotecas y herramientas de software que consideren apropiados, siempre que sean compatibles con el hardware oficial y respeten las condiciones de autonomía del reto.

4.3. La lógica necesaria para tomar decisiones durante un intento deberá estar cargada y ejecutarse en los rovers.

4.4. No se permitirá realizar cambios físicos para facilitar estas tareas.

---

## 5. Sistema de visión global

5.1. Una cámara superior observará la superficie de competencia.

5.2. El sistema oficial de visión será proporcionado por la organización.

5.3. El sistema de visión determinará la posición y orientación de cada rover.

5.4. El sistema de visión determinará la posición de los cubos y proporcionará las zonas de acopio definidas para el intento.

5.5. Los rovers utilizarán marcadores visuales oficiales para ser identificados por el sistema.

5.6. El sistema de visión publicará telemetría en tiempo real para que los rovers puedan conocer el estado global del entorno.

5.7. El sistema oficial de visión no deberá ser modificado por los equipos durante la competencia.

5.8. La telemetría deberá interpretarse según el contrato oficial publicado en el repositorio del Vision Rover Challenge.

5.9. El sistema de visión proporciona percepción global del entorno, pero no proporciona la estrategia, las rutas ni las decisiones de los equipos.

5.10. El sistema oficial de visión también proporcionará los estados utilizados para controlar el inicio de cada intento, incluyendo `IDLE` y `READY`.

---

## 6. Uso de computadoras externas y servicios en la nube

6.1. Durante el desarrollo y preparación, los equipos podrán utilizar laptops, computadoras de escritorio, mini PC, servicios en la nube, modelos de inteligencia artificial, simuladores y otras herramientas.

6.2. Estas herramientas podrán utilizarse para:

6.2.1. Desarrollar y depurar código.

6.2.2. Simular escenarios.

6.2.3. Analizar datos.

6.2.4. Diseñar y evaluar estrategias.

6.2.5. Generar planes o parámetros que posteriormente sean cargados en los rovers.

6.2.6. Configurar direcciones IP, direcciones MAC y parámetros de comunicación.

6.2.7. Verificar el funcionamiento de los robots y su conexión con el sistema de visión.

6.3. Una vez que el sistema oficial de visión cambie al estado `READY`:

6.3.1. No se permite que una computadora externa calcule nuevas rutas para los robots.

6.3.2. No se permite que una computadora externa distribuya o reasigne tareas entre los robots.

6.3.3. No se permite que una computadora externa tome decisiones de navegación.

6.3.4. No se permite que una computadora externa genere comandos de movimiento.

6.3.5. No se permite que un servicio en la nube modifique la estrategia o planificación de los robots en tiempo real.

6.3.6. No se permite enviar cambios de planificación desde un dispositivo externo.

6.3.7. No se permite utilizar una computadora, teléfono u otro dispositivo como sistema de control remoto, aunque los comandos sean generados automáticamente.

6.4. La computadora utilizada por la organización para ejecutar el sistema oficial de visión no se considera parte del sistema de control del equipo.

6.5. Su función será observar el entorno, publicar telemetría y gestionar los estados oficiales del intento.

---

## 7. Comunicación

7.1. Los rovers recibirán información del sistema oficial de visión mediante la red definida por la organización y de acuerdo con el contrato de telemetría.

7.2. Los robots podrán comunicarse entre sí mediante los mecanismos inalámbricos disponibles en el hardware oficial.

7.3. Los rovers podrán intercambiar información sobre sus estados, tareas y movimientos.

7.4. Los rovers podrán coordinar rutas y evitar colisiones.

7.5. Los rovers podrán informar entre ellos sobre la detección, transporte o entrega de objetos.

7.6. Las decisiones de coordinación deberán producirse de manera autónoma en los rovers.

7.7. No se permite enviar instrucciones humanas durante la ejecución.

7.8. No se permite utilizar una computadora externa como intermediario para tomar decisiones o controlar los rovers durante un intento.

7.9. Los equipos deberán trabajar con el estado más reciente disponible de la telemetría y evitar ejecutar decisiones basadas en una cola de estados antiguos.

7.10. Los campos de secuencia, tiempo y antigüedad definidos en el contrato de telemetría podrán utilizarse para determinar la vigencia de los datos recibidos.

---

## 8. Preparación de un intento

8.1. Antes de cada intento, la organización restablecerá el escenario de competencia según la configuración oficial correspondiente.

8.2. Los robots, cubos, zonas de acopio y demás elementos serán colocados en las condiciones iniciales definidas para el intento.

8.3. Todos los equipos competirán bajo las mismas condiciones oficiales establecidas para la ronda.

8.4. Una vez preparado el escenario, el sistema oficial de visión establecerá el estado `IDLE` durante **1 minuto**.

8.5. Durante el estado `IDLE`, los rovers deberán estar encendidos, programados, conectados al sistema de visión y preparados para ejecutar la prueba.

8.6. Antes del cambio a `READY` se permitirá:

8.6.1. Calibrar los sensores.

8.6.2. Verificar la comunicación.

8.6.3. Ajustar los parámetros del sistema.

8.6.4. Comprobar el funcionamiento de los robots.

8.6.5. Configurar direcciones IP, direcciones MAC u otros parámetros de red.

8.6.6. Cargar el software y los planes previamente desarrollados en los rovers.

8.6.7. Colocar los robots en la posición inicial establecida.

8.7. El período de 1 minuto en estado `IDLE` no forma parte del tiempo oficial del intento.

---

## 9. Inicio del intento

9.1. Finalizado el período de 1 minuto en estado `IDLE`, el sistema oficial de visión cambiará al estado `READY`.

9.2. Los rovers deberán detectar el estado `READY` mediante la telemetría oficial.

9.3. La detección del estado `READY` deberá provocar automáticamente el inicio de la estrategia desarrollada por el equipo.

9.4. El cambio a `READY` marca el **inicio oficial del intento y del cronometraje**.

9.5. No se permitirá intervención humana para iniciar los rovers después del cambio a `READY`.

9.6. No se permitirá presionar botones para iniciar la estrategia después del cambio a `READY`.

9.7. La detección de `READY` y el inicio de la ejecución deberán formar parte del software desarrollado por el equipo.

9.8. La secuencia general de inicio será:

**Preparación → `IDLE` durante 1 minuto → `READY` → inicio automático de los rovers**

---

## 10. Duración y finalización del intento

10.1. Cada intento tendrá una duración máxima de **10 minutos**.

10.2. Los 10 minutos se medirán a partir del cambio del sistema oficial de visión al estado `READY`.

10.3. El intento finalizará cuando ocurra alguna de las siguientes condiciones:

10.3.1. Los tres cubos se encuentren correctamente depositados en sus respectivas zonas de acopio.

10.3.2. Se alcance el límite máximo de 10 minutos.

10.3.3. El juez detenga el intento por razones de seguridad.

10.3.4. El juez detenga el intento por incumplimiento del reglamento.

10.3.5. Ocurra una falla de infraestructura que, a criterio del juez, haga imposible continuar el intento en condiciones válidas.

10.4. Si el equipo completa correctamente los tres cubos antes de los 10 minutos, se registrará el tiempo transcurrido desde el cambio a `READY` hasta que el tercer cubo quede correctamente depositado.

10.5. La posición final de los rovers no forma parte de la condición de éxito una vez que los tres cubos hayan sido depositados correctamente.

---

## 11. Autonomía durante el intento

11.1. La ejecución autónoma comienza formalmente cuando el sistema oficial de visión cambia del estado `IDLE` al estado `READY`.

11.2. A partir de ese momento:

11.2.1. Los rovers deberán iniciar automáticamente su estrategia.

11.2.2. No se permitirá tocar, mover o reorientar los robots.

11.2.3. No se permitirá presionar botones para iniciar, reiniciar o modificar su comportamiento.

11.2.4. No se permitirá modificar el código.

11.2.5. No se permitirá reprogramar o reiniciar los robots.

11.2.6. No se permitirá enviar instrucciones humanas.

11.2.7. No se permitirá enviar comandos desde una computadora, teléfono u otro dispositivo.

11.2.8. No se permitirá modificar parámetros o configuraciones.

11.2.9. No se permitirá mover manualmente los cubos ni otros elementos del escenario.

11.2.10. No se permitirá corregir manualmente la posición de ningún elemento.

11.2.11. No se permitirá modificar externamente la estrategia, asignación de tareas, rutas o comandos de movimiento.

11.2.12. No se permitirá utilizar lógica externa en una laptop, computadora, teléfono o servicio en la nube para alterar el comportamiento de los rovers en tiempo real.

11.3. Los rovers deberán ejecutar completamente la tarea de manera autónoma.

---

## 12. Ejecución de la tarea

12.1. Los robots deberán iniciar desde la zona establecida.

12.2. Durante el intento deberán:

12.2.1. Interpretar la información recibida del sistema oficial de visión.

12.2.2. Identificar los objetos que deben transportar.

12.2.3. Relacionar cada cubo con su zona de acopio correspondiente.

12.2.4. Navegar en la superficie.

12.2.5. Coordinar sus movimientos.

12.2.6. Distribuir las tareas entre ambos rovers.

12.2.7. Evitar colisiones entre ellos.

12.2.8. Localizar y aproximarse a los cubos.

12.2.9. Empujar o transportar los cubos utilizando la estructura original del robot.

12.2.10. Llevar los objetos hasta la zona de acopio correspondiente.

12.2.11. Corregir sus trayectorias utilizando la información de la cámara y de sus sensores integrados.

12.2.12. Continuar operando de forma razonable cuando un objeto quede temporalmente oculto y la telemetría conserve su última posición conocida.

12.3. La orientación de los cubos no forma parte de la información requerida para completar la tarea.

12.4. La posición y el color son suficientes para identificar cada cubo dentro del contrato de telemetría.

---

## 13. Validez de los cubos depositados

13.1. Un cubo se considerará correctamente depositado cuando se encuentre **completamente dentro de su zona de acopio correspondiente**.

13.2. El tiempo de depósito de un cubo corresponderá al momento, medido desde el cambio a `READY`, en que el cubo quede correctamente depositado.

13.3. Un cu
