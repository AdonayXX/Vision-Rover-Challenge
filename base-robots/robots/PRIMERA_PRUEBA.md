# Primera prueba con hardware: un robot, un motor a la vez

Objetivo de la visita: cargar el receptor, conectar la computadora y comprobar movimiento y parada de ambos motores. No requiere tablero, cámara, cubos, IMU ni segundo robot. No completa todavía la misión autónoma.

## 1. Identificar y preparar

Este receptor está hecho para **IdeaBoard con CircuitPython**. Si la placa es otro ESP32, anoten modelo exacto y modelo del controlador de motores antes de adaptar los pines; no carguen `ideaboard.py` como si fuera compatible. Los motores se conectan al controlador de motores, nunca directamente a GPIO.

Llevar computadora con Python y Thonny, cable USB de datos, robot, alimentación apropiada para su placa/motores y acceso a una red Wi-Fi compartida. Revisar las [conexiones del repositorio](../hardware/conexiones/README.md) para la IdeaBoard. Hacer conexiones con alimentación desconectada y mantener ruedas levantadas durante toda esta prueba.

Guardar una copia del programa existente de la placa antes de sustituirlo. En Thonny seleccionar CircuitPython (genérico) y el puerto COM correspondiente. No instalar firmware de un modelo distinto. La [página oficial de IdeaBoard](https://circuitpython.org/board/crcibernetica_ideaboard/) identifica su firmware; el [flujo oficial para ESP32](https://learn.adafruit.com/circuitpython-with-esp32-quick-start) explica que estos ESP32 pueden requerir acceso por Thonny o web en vez de una unidad USB CIRCUITPY.

## 2. Archivos de la placa

Copiar **solo** estos archivos desde `base-robots/robots/codigos/` a la raíz de la placa mediante Thonny:

- `ideaboard.py`
- `control_movimiento.py`
- `command_protocol.py`
- `sesion_comandos.py`
- `wifi_config.py`
- `wifi_command_receiver.py`
- `config_banco.example.json`, guardado como **`config_robot.json`**.
- `code_banco.py`, guardado como **`code.py`** (copiar este al final).

El perfil de banco trae `ask_wifi_on_boot: true`: al arrancar, la consola serial pide `SSID:` y `Password:`. Así no hace falta editar el archivo cada vez que cambia la red. Si después se quiere un arranque autónomo, guardar `wifi_ssid` y `wifi_password` en el `config_robot.json` local y cambiar `ask_wifi_on_boot` a `false`. No subir credenciales al repositorio.

El perfil de banco usa además `use_imu: false` y watchdog de **0.5 segundos**. Mantener esos valores para las pruebas de esta guía.

La placa necesita las bibliotecas CircuitPython compatibles con su versión: `neopixel`, `simpleio` y `adafruit_motor`, con sus dependencias. Si ya funciona el código original, puede tenerlas instaladas. Ante `ImportError`, anotar el módulo faltante e instalarlo desde el [bundle oficial](https://circuitpython.org/libraries); no son paquetes que se resuelvan con `pip` en la computadora. Las bibliotecas externas y el firmware no se incluyen en esta entrega.

Reiniciar y observar la consola. Primero debe aparecer algo similar a:

```text
=== Configuracion Wi-Fi del rover ===
SSID: MiWifi
Password: ********
```

Después de escribir las credenciales debe mostrar `Comandos de prueba: <IP> 5000`. Si aparece una excepción, resolverla antes de intentar mover motores. Con `use_imu: false`, los comandos angulares TURN/HEADING se rechazan deliberadamente. La consola puede mostrar lo que se escribe en el campo de contraseña dependiendo del terminal usado.

## 3. Desde la computadora

Abrir PowerShell en la raíz del repositorio. Reemplazar `192.168.1.50` por la IP que mostró la placa. La computadora y el robot deben poder comunicarse en la misma red; una red de invitados puede aislarlos.

Primero conexión, sin movimiento:

```powershell
python -B base-robots/robots/pc/prueba_banco.py 192.168.1.50
```

Luego un pulso por motor, observando cuál rueda gira y en qué sentido:

```powershell
python -B base-robots/robots/pc/prueba_banco.py 192.168.1.50 --test pulso --motor 1
python -B base-robots/robots/pc/prueba_banco.py 192.168.1.50 --test pulso --motor 2
```

Por defecto: potencia 0.2 durante 0.3 segundos. Para comprobar giro inverso añadir `--power -0.2`. El cliente limita potencia absoluta a 0.3 y pulso a 0.4 segundos. Si no gira a esta potencia, eso no demuestra una falla de comunicación: revisar alimentación, conexiones y rozamiento, sin aumentar automáticamente la potencia.

Parada por falta de órdenes, manteniendo conexión y enviando PING:

```powershell
python -B base-robots/robots/pc/prueba_banco.py 192.168.1.50 --test watchdog --motor 1
```

Observar que el motor deja de recibir impulso aproximadamente a los 0.5 segundos, **antes de terminar** el ensayo de un segundo. Si solo se detiene al finalizar, el STOP final puede estar ocultando un fallo del watchdog. PING no renueva el movimiento. El giro por inercia puede durar más que la alimentación del motor.

Parada por cierre de conexión:

```powershell
python -B base-robots/robots/pc/prueba_banco.py 192.168.1.50 --test desconexion --motor 1
```

Este último envía MOTOR y cierra inmediatamente: el pulso puede ser apenas perceptible. Comprueba el cierre TCP normal; no reproduce por sí solo toda pérdida de radio o un bloqueo del firmware. Repetir ambas pruebas para motor 2. Si algún motor sigue impulsando, cortar su alimentación y corregir antes de bajar las ruedas.

`OK` significa que el receptor aceptó la orden; no mide la rueda ni confirma físicamente la parada. El watchdog es software, no una protección contra todos los fallos eléctricos o bloqueos.

## 4. Qué anotar y qué sigue

| Dato | Resultado observado |
|---|---|
| Modelo de placa y versión CircuitPython | |
| Conexión TCP y dirección IP | |
| Motor 1: rueda física y sentido con potencia positiva | |
| Motor 2: rueda física y sentido con potencia positiva | |
| STOP al terminar cada pulso | |
| Parada por watchdog antes del STOP final | |
| Parada por cierre TCP | |
| Errores completos de consola | |

Si todo pasa, habremos comprobado alimentación, acceso a ambos motores, comunicación básica y esas rutas de parada en el hardware real. Luego toca ajustar sentidos, conectar y calibrar la IMU, comprobar giros y avance corto, y finalmente incorporar cámara/tablero. Aún faltan integración de navegación en CircuitPython, transporte real de coordinación entre robots y manipulación de cubos.

El control desde computadora de esta guía es de desarrollo. Durante la ronda oficial, las decisiones y órdenes deben ejecutarse en los rovers según el [reglamento](../documentacion/reglamento.md).
