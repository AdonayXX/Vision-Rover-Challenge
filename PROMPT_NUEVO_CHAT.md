Vas a continuar el proyecto **Vision Rover Challenge** (CENFOTEC): dos rovers autónomos (IDs 10 y 11, IdeaBoard ESP32 con CircuitPython 9.2.4) tienen que llevar 3 cubos (rojo, verde y azul) a sus zonas, guiándose por la telemetría de la visión oficial. El código de los rovers está en `base-robots/robots/`.

**Antes de responder nada, lee completo `ESTADO_ACTUAL.md` (en la raíz del repo).** Ahí están las reglas del reto, el hardware, la arquitectura del código, los comandos, las redes, los resultados de todas las rondas, los problemas abiertos, los cambios sin commit y las reglas de trabajo. No repitas en la conversación lo que ya está ahí; úsalo.

**Reglas firmes (no se negocian):**
1. `vision-system/` no se modifica nunca: es el sistema oficial de la universidad. Todo ajuste va en el rover.
2. Los commits los hago yo. Nunca agregues `Co-Authored-By` ni menciones a Claude o a una IA en commits ni en PRs.
3. `base-robots/robots/codigos/config_robot.json` tiene la contraseña del Wi-Fi: no la muestres ni la commitees.
4. Antes de un cambio grande, explícamelo y espera mi visto bueno. Vamos paso a paso.
5. Háblame en español simple y directo. Dime con honestidad qué funciona y qué no, con datos.

**Límites de la placa que rompieron cosas antes:**
- La pila de Python es de ~1.5 KB. Un error `pystack exhausted` dejó al rover 10 sin moverse. Llama al A\* solo desde `_planificar` y respeta `test_planning_fits_in_the_board_python_stack`.
- La RAM libre es de ~55–70 KB.
- Todo tiene que compilar con `tools/mpy-cross/mpy-cross-9.2.4.exe`.
- El simulador de la PC no modela ni la pila, ni la RAM, ni el Wi-Fi, ni las baterías.

**Cómo quiero que trabajes:**
- Basa cada diagnóstico en datos: las grabaciones (`pc/grabaciones/*.jsonl` y `tabla.csv`, que se analizan con `pc/simulacion/resumen_grab.py`) y los `ver_ronda` que te pegue. Reproduce la posición exacta en el simulador antes de cambiar código.
- Arregla **solo lo que se repite** en la tabla de resultados. No agregues funciones "por si acaso".
- Cada cambio se cierra con:
  - pruebas en verde (desde `base-robots/robots`: `..\..\vision-system\.venv\Scripts\python.exe -B -m unittest discover -s tests`, hoy son 322);
  - compilación con mpy-cross;
  - la batería de canchas oficiales (`pc/simulacion/bateria_oficial.py . <D> 12`) comparada contra la versión anterior.
- Al terminar, dime exactamente qué archivos subir a cada rover.
- Los logs largos se cortan a ~50 000 caracteres: pídeme los `ver_ronda` de a una ronda, y solo de las rondas que fallen.

**Dónde estamos ahora mismo:**
- Pasamos al hotspot del celular "HONOR X8": la PC tiene la IP 10.91.8.217, el rover 10 la 10.91.8.70 y el rover 11 la 10.91.8.149.
- Los rovers no arrancaban (`fase=None`) porque `vision_host` tenía la IP vieja. Ya está corregido en el `config_robot.json` local, pero **falta subirlo a los dos rovers**.
- El NeoPixel del rover 10, que la cámara veía como un cubo, ya se desconectó.

**Tu primera tarea:**
1. Guíame para dejar listo el montaje (subir la configuración y el código, y verificar la conexión con la visión y la radio).
2. Después vamos a correr las tres canchas oficiales (oficial02, oficial05 y oficial08) con el grabador. Analiza los resultados y propón el **único** arreglo de mayor impacto, con datos.

Recuerda también que el rover 11 ha tenido muchos reinicios por bajo voltaje (BROWNOUT): sigue pendiente revisar sus baterías.
