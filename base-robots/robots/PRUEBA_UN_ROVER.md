# Prueba autónoma con el rover 10

La PC ejecuta la estrategia y usa la visión por TCP 2026; el rover recibe
comandos MOTOR/STOP por TCP 5000. La integración de sensores requiere subir el
paquete completo actualizado a la placa; reiniciar solo la PC no basta.
Antes de continuar, completar [SENSORES.md](SENSORES.md): cableado confirmado,
lecturas verificadas y calibración de color. El control manual conserva sus
comandos, pero ahora también está sujeto a la protección local de sensores.

1. Deja el rover 10 y los tres cubos visibles. Retira el rover 11 para esta
   prueba de un solo robot (si permanece, el planificador lo trata como obstáculo).
2. Conecta el rover al Wi-Fi mediante `subir_esp32_gui.bat` y anota su IP.
   Cierra el control manual `prueba_robot.py` antes de iniciar la prueba.
3. Reinicia la visión para cargar la corrección del detector:

   ```powershell
   cd .\vision-system
   .\.venv\Scripts\Activate.ps1
   python -m vision.sistema --ventana
   ```

   Selecciona la cámara Logitech del tablero. Deben aparecer los tres cubos
   identificados como red, green y blue. La prueba de desarrollo funciona en
   IDLE: no requiere iniciar una ronda ni que exista el rover 11.

4. Desde **otra terminal en la raíz del repositorio**, comprueba la escena:

   ```powershell
   .\prueba_autonoma_rover10.bat --solo-verificar
   ```

   Este modo lee visión y comprueba rutas en la escena actual; no abre el puerto
   de motores. No comprueba los sensores de la placa ni simula los movimientos
   posteriores de los cubos.

5. Inicia la prueba:

   ```powershell
   .\prueba_autonoma_rover10.bat
   ```

   Introduce la IP cuando la pida, o pásala con `--robot-ip DIRECCION_IP`.
   El movimiento empieza tras conectar y esperar dos segundos.
   Transporta **rojo, verde y azul**, cada uno a su zona, y se retira antes
   de pasar al siguiente. `Ctrl+C` envía STOP y termina.

Cada movimiento se solicita en un pulso corto (avance 120 ms, giro hasta
100 ms), seguido de STOP confirmado. El siguiente paso espera una imagen
capturada después de esa parada y de 80 ms de asentamiento; una republicación
del cuadro anterior no autoriza otro giro. El tiempo real del pulso también
depende de la respuesta TCP del rover. La consola muestra ángulo, error y edad
en cada `Paso` para comprobar el control sobre el hardware.

El signo de giro predeterminado es `--turn-sign -1`, según el registro del
rover 10: el comando negativo/positivo hacía disminuir theta. La adaptación
afecta al giro en sitio y a las correcciones de avance, empuje y retirada;
no modifica el ángulo publicado por visión ni invierte el avance recto.
Para otro montaje con respuesta convencional se puede usar `--turn-sign 1`.
Cada paso muestra también `cmd=MOTOR|...|...` para contrastar orden y respuesta.
Esta correspondencia está probada en software; al probarla físicamente,
mantener espacio libre y detener con Ctrl+C si no responde como se espera.

El robot se aproxima por una ruta con margen para su cuerpo, se alinea y empuja
en línea recta con corrección de rumbo. Confirma el cubo completamente dentro
de la zona, cerca del centro y durante 0,5 segundos. Se detiene si pierde datos
frescos, encuentra un corredor bloqueado o supera 120 segundos por cubo.
Si el cubo necesita rodear un obstáculo, esta prueba se detiene: no implementa
empuje en varias etapas. Se debe recolocar la escena para dejar libre ese corredor.

El radio de 85 mm, la separación de aproximación de 150 mm y las velocidades
son parámetros de prueba; confirma que corresponden al montaje y al sentido
real de los motores. La entrega física debe verificarse sobre la cancha.

Para probar **un único cubo** desde la raíz:

```powershell
.\vision-system\.venv\Scripts\python.exe -X utf8 -B -u .\base-robots\robots\pc\prueba_transporte_cubo.py --robot-id 10 --cube red --depot red
```

Para revisar filtros de detección, cierra la ventana de visión y ejecuta desde
`vision-system`: `python -m vision.tools.diagnostico_cubos`. Muestra el motivo
de rechazo y el área calculada localmente según la perspectiva.
