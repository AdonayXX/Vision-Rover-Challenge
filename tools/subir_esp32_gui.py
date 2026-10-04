import json
import os
import queue
import re
import subprocess
import sys
import threading
import time
import tkinter as tk
import urllib.request
from tkinter import filedialog, messagebox, ttk


PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
CODE_DIR = os.path.join(PROJECT_ROOT, "base-robots", "robots", "codigos")

DEFAULT_FILES = [
    os.path.join(CODE_DIR, "code.py"),
    os.path.join(CODE_DIR, "wifi_command_receiver.py"),
    os.path.join(CODE_DIR, "config_robot.json"),
    os.path.join(CODE_DIR, "wifi_config.py"),
    os.path.join(CODE_DIR, "control_movimiento.py"),
    os.path.join(CODE_DIR, "sesion_comandos.py"),
    os.path.join(CODE_DIR, "command_protocol.py"),
    os.path.join(CODE_DIR, "sensores_rover.py"),
    os.path.join(CODE_DIR, "hardware_sensores.py"),
    os.path.join(CODE_DIR, "config_sensores.json"),
    os.path.join(CODE_DIR, "ideaboard.py"),
    os.path.join(CODE_DIR, "registro_fallos.py"),
    os.path.join(CODE_DIR, "safemode.py"),
    os.path.join(CODE_DIR, "cliente_vision_rover.py"),
    os.path.join(CODE_DIR, "telemetria.py"),
    os.path.join(CODE_DIR, "modelo_rover.py"),
    os.path.join(CODE_DIR, "autonomia.py"),
    os.path.join(CODE_DIR, "llevar_cubo.py"),
    os.path.join(CODE_DIR, "ronda.py"),
    os.path.join(CODE_DIR, "enlace.py"),
    os.path.join(CODE_DIR, "rutas.py"),
    os.path.join(CODE_DIR, "rutas_placa.py"),
    os.path.join(CODE_DIR, "navegacion.py"),
]

# Los modulos se suben COMPILADOS (.mpy) con el mpy-cross oficial de Adafruit
# para la version de CircuitPython de la placa: asi la placa no compila el
# codigo al importarlo, que pedia tanta RAM de golpe que la ronda se caia
# (cancha 2-oct: MemoryError fatal al planificar). El codigo fuente no cambia.
# CircuitPython ejecuta estos por NOMBRE: tienen que quedar como .py.
NO_COMPILAR = {"code.py", "boot.py", "safemode.py"}
MPY_DIR = os.path.join(PROJECT_ROOT, "tools", "mpy-cross")
MPY_URL = ("https://adafruit-circuit-python.s3.amazonaws.com/bin/mpy-cross/windows/"
           "mpy-cross-windows-{version}.static.exe")
CIRCUITPYTHON_POR_DEFECTO = "9.2.4"


class Esp32Uploader(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Subir archivos a ESP32")
        self.geometry("820x620")
        self.minsize(720, 520)

        self.log_queue = queue.Queue()
        self.busy = False
        self.selected_files = []

        self.port_var = tk.StringVar(value="COM3")
        # Cada rover tiene su ID de marcador, ganancias y calibracion:
        # rover_<id>.json -> /rover.json, modelo_movimiento_<id>.json -> /modelo_movimiento.json
        self.rover_var = tk.StringVar(value="10")
        self.status_var = tk.StringVar(value="Listo")
        self.ssid_var = tk.StringVar()
        self.password_var = tk.StringVar()
        self.ask_wifi_var = tk.BooleanVar(value=False)
        self.compilar_var = tk.BooleanVar(value=True)

        self._build_ui()
        self.load_wifi_config()
        self.after(100, self._drain_log_queue)

    def _build_ui(self):
        root = ttk.Frame(self, padding=12)
        root.pack(fill="both", expand=True)

        top = ttk.Frame(root)
        top.pack(fill="x")

        ttk.Label(top, text="ID del rover").pack(side="left")
        ttk.Entry(top, textvariable=self.rover_var, width=5).pack(side="left", padx=(8, 12))
        ttk.Label(top, text="Puerto").pack(side="left")
        self.port_entry = ttk.Entry(top, textvariable=self.port_var, width=10)
        self.port_entry.pack(side="left", padx=(8, 12))

        ttk.Button(top, text="Detectar puertos", command=self.detect_ports).pack(side="left")
        ttk.Button(top, text="Instalar ampy", command=self.install_ampy).pack(side="left", padx=(8, 0))

        buttons = ttk.Frame(root)
        buttons.pack(fill="x", pady=(12, 8))

        self.upload_default_btn = ttk.Button(
            buttons,
            text="Subir paquete completo",
            command=self.upload_default_package,
        )
        self.upload_default_btn.pack(side="left")

        self.choose_btn = ttk.Button(
            buttons,
            text="Elegir archivos...",
            command=self.choose_files,
        )
        self.choose_btn.pack(side="left", padx=(8, 0))

        self.upload_selected_btn = ttk.Button(
            buttons,
            text="Subir seleccionados",
            command=self.upload_selected_files,
        )
        self.upload_selected_btn.pack(side="left", padx=(8, 0))

        self.reset_btn = ttk.Button(
            buttons,
            text="Reiniciar placa",
            command=self.reset_board,
        )
        self.reset_btn.pack(side="left", padx=(8, 0))

        ttk.Checkbutton(
            buttons,
            text="Compilar a .mpy (recomendado)",
            variable=self.compilar_var,
        ).pack(side="left", padx=(12, 0))

        selected_box = ttk.LabelFrame(root, text="Archivos seleccionados")
        selected_box.pack(fill="x", pady=(0, 10))

        selected_inner = ttk.Frame(selected_box)
        selected_inner.pack(fill="x", padx=8, pady=8)

        self.selected_list = tk.Listbox(selected_inner, height=4)
        self.selected_list.pack(side="left", fill="x", expand=True)

        selected_actions = ttk.Frame(selected_inner)
        selected_actions.pack(side="left", padx=(8, 0), fill="y")

        self.remove_selected_btn = ttk.Button(
            selected_actions,
            text="Quitar",
            command=self.remove_selected_file,
        )
        self.remove_selected_btn.pack(fill="x")

        self.clear_selected_btn = ttk.Button(
            selected_actions,
            text="Limpiar",
            command=self.clear_selected_files,
        )
        self.clear_selected_btn.pack(fill="x", pady=(6, 0))

        wifi_box = ttk.LabelFrame(root, text="Wi-Fi")
        wifi_box.pack(fill="x", pady=(0, 10))

        wifi_grid = ttk.Frame(wifi_box)
        wifi_grid.pack(fill="x", padx=8, pady=8)

        ttk.Label(wifi_grid, text="SSID").grid(row=0, column=0, sticky="w")
        ttk.Entry(wifi_grid, textvariable=self.ssid_var).grid(row=0, column=1, sticky="ew", padx=(8, 12))

        ttk.Label(wifi_grid, text="Password").grid(row=0, column=2, sticky="w")
        ttk.Entry(wifi_grid, textvariable=self.password_var, show="*").grid(row=0, column=3, sticky="ew", padx=(8, 0))

        wifi_grid.columnconfigure(1, weight=2)
        wifi_grid.columnconfigure(3, weight=2)

        self.ask_wifi_check = ttk.Checkbutton(
            wifi_grid,
            text="Preguntar al arrancar",
            variable=self.ask_wifi_var,
        )
        self.ask_wifi_check.grid(row=1, column=1, sticky="w", pady=(8, 0))

        self.save_wifi_btn = ttk.Button(
            wifi_grid,
            text="Guardar Wi-Fi local",
            command=self.save_wifi_local,
        )
        self.save_wifi_btn.grid(row=1, column=2, sticky="ew", padx=(0, 8), pady=(8, 0))

        self.upload_wifi_btn = ttk.Button(
            wifi_grid,
            text="Guardar y subir Wi-Fi",
            command=self.save_and_upload_wifi,
        )
        self.upload_wifi_btn.grid(row=1, column=3, sticky="ew", pady=(8, 0))

        self.connect_wifi_btn = ttk.Button(
            wifi_grid,
            text="Conectar rover al Wi-Fi",
            command=self.connect_wifi,
        )
        self.connect_wifi_btn.grid(
            row=2,
            column=0,
            columnspan=4,
            sticky="ew",
            pady=(8, 0),
        )

        log_box = ttk.LabelFrame(root, text="Salida")
        log_box.pack(fill="both", expand=True)

        self.log = tk.Text(log_box, height=16, wrap="word", state="disabled")
        self.log.pack(side="left", fill="both", expand=True)

        scrollbar = ttk.Scrollbar(log_box, command=self.log.yview)
        scrollbar.pack(side="right", fill="y")
        self.log.configure(yscrollcommand=scrollbar.set)

        status = ttk.Frame(root)
        status.pack(fill="x", pady=(8, 0))
        ttk.Label(status, textvariable=self.status_var, anchor="w").pack(side="left", fill="x", expand=True)

    def detect_ports(self):
        self.run_worker(
            "Detectando puertos...",
            [
                "powershell.exe",
                "-NoProfile",
                "-Command",
                "[System.IO.Ports.SerialPort]::GetPortNames()",
            ],
        )

    def install_ampy(self):
        self.set_busy(True, "Instalando dependencias...")
        thread = threading.Thread(target=self._install_worker, daemon=True)
        thread.start()

    def _install_worker(self):
        try:
            self.log_queue.put(("log", f"Python usado: {sys.executable}\n"))
            self.log_queue.put(("log", "Activando pip si hace falta...\n"))
            self.run_command([sys.executable, "-m", "ensurepip", "--upgrade"])
            self.log_queue.put(("log", "Instalando pyserial y adafruit-ampy...\n"))
            self.run_command([sys.executable, "-m", "pip", "install", "--upgrade", "pyserial", "adafruit-ampy"])
            self.log_queue.put(("status", "Dependencias instaladas"))
        except Exception as error:
            self.log_queue.put(("log", f"\nERROR: {error}\n"))
            self.log_queue.put(("status", "Error instalando dependencias"))
        finally:
            self.log_queue.put(("done", None))

    def choose_files(self):
        files = filedialog.askopenfilenames(
            title="Elige archivos para subir",
            initialdir=CODE_DIR,
            filetypes=[
                ("Python y JSON", "*.py *.json"),
                ("Todos", "*.*"),
            ],
        )
        if not files:
            return

        for path in files:
            if path not in self.selected_files:
                self.selected_files.append(path)

        self.refresh_selected_files()

    def refresh_selected_files(self):
        self.selected_list.delete(0, "end")
        for path in self.selected_files:
            self.selected_list.insert("end", os.path.basename(path))

    def remove_selected_file(self):
        indexes = list(self.selected_list.curselection())
        if not indexes:
            return
        for index in reversed(indexes):
            del self.selected_files[index]
        self.refresh_selected_files()

    def clear_selected_files(self):
        self.selected_files = []
        self.refresh_selected_files()

    def rover_files(self):
        """Archivos propios del rover elegido, con el nombre que llevan en la placa.

        Devuelve (lista de (origen, destino), aviso o None). Sin calibracion
        para ese rover no se sube modelo y se borra el que hubiera en la placa:
        mejor el modelo por defecto que el de OTRO rover.
        """
        rover = self.rover_var.get().strip()
        if not rover.isdigit():
            raise ValueError("El ID del rover debe ser un numero (el de su marcador)")
        propio = os.path.join(CODE_DIR, f"rover_{rover}.json")
        if not os.path.isfile(propio):
            raise ValueError(f"No existe rover_{rover}.json en codigos/")
        archivos = [(propio, "/rover.json")]
        modelo = os.path.join(CODE_DIR, f"modelo_movimiento_{rover}.json")
        if os.path.isfile(modelo):
            return archivos + [(modelo, "/modelo_movimiento.json")], None
        return archivos, f"El rover {rover} no tiene calibracion (modelo_movimiento_{rover}.json): usara el modelo por defecto."

    def upload_default_package(self):
        try:
            propios, aviso = self.rover_files()
        except ValueError as error:
            messagebox.showerror("Rover", str(error))
            return
        if aviso:
            self.write_log("AVISO: " + aviso + "\n")
        borrar = [] if any(r == "/modelo_movimiento.json" for _, r in propios) else ["/modelo_movimiento.json"]
        if not self.compilar_var.get():
            # Sin compilar: los .mpy viejos no estorban (un .py se importa
            # antes que un .mpy del mismo nombre), pero se borran igual.
            borrar += ["/" + os.path.splitext(os.path.basename(f))[0] + ".mpy" for f in DEFAULT_FILES
                       if f.endswith(".py") and os.path.basename(f) not in NO_COMPILAR]
            self.upload_files(DEFAULT_FILES + propios, borrar)
            return
        self.set_busy(True, "Compilando...")
        thread = threading.Thread(target=self._paquete_compilado_worker,
                                  args=(DEFAULT_FILES + propios, borrar), daemon=True)
        thread.start()

    def _version_placa(self):
        """Version de CircuitPython de la placa, preguntada a la propia placa.

        `ampy get` no sirve: usa ubinascii, que CircuitPython no trae.
        """
        import tempfile
        with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False, encoding="utf-8") as script:
            script.write("import sys\nprint('CircuitPython', '.'.join(str(n) for n in sys.implementation.version))\n")
        try:
            texto = "".join(self.run_command(self.ampy_command("run", script.name)))
        except RuntimeError:
            texto = ""
        finally:
            os.remove(script.name)
        encontrada = re.search(r"CircuitPython (\d+\.\d+\.\d+)", texto)
        if encontrada:
            return encontrada.group(1)
        self.log_queue.put(("log", "AVISO: no pude leer la version de la placa; uso "
                                   f"CircuitPython {CIRCUITPYTHON_POR_DEFECTO}.\n"))
        return CIRCUITPYTHON_POR_DEFECTO

    def _mpy_cross(self, version):
        """mpy-cross oficial para esa version; se descarga una sola vez."""
        os.makedirs(MPY_DIR, exist_ok=True)
        exe = os.path.join(MPY_DIR, f"mpy-cross-{version}.exe")
        if not os.path.isfile(exe):
            url = MPY_URL.format(version=version)
            self.log_queue.put(("log", f"Descargando mpy-cross {version} de Adafruit...\n{url}\n"))
            temporal = exe + ".parcial"
            urllib.request.urlretrieve(url, temporal)
            os.replace(temporal, exe)
        salida = "".join(self.run_command([exe, "--version"]))
        if version not in salida:
            raise RuntimeError(f"mpy-cross no corresponde a CircuitPython {version}: {salida}")
        return exe

    def _paquete_compilado_worker(self, archivos, borrar):
        try:
            self.log_queue.put(("log", f"Usando puerto {self.port()}\nLeyendo version de la placa...\n"))
            version = self._version_placa()
            self.log_queue.put(("log", f"Placa con CircuitPython {version}\n"))
            exe = self._mpy_cross(version)
            salida = os.path.join(MPY_DIR, "build", version)
            os.makedirs(salida, exist_ok=True)
            comandos, borrar = [], list(borrar)
            for item in archivos:
                origen, remoto = item if isinstance(item, tuple) else (item, self.remote_name(item))
                if not os.path.isfile(origen):
                    raise RuntimeError(f"No existe: {origen}")
                nombre = os.path.basename(origen)
                if not nombre.endswith(".py") or nombre in NO_COMPILAR:
                    comandos.append((origen, remoto))
                    continue
                base = os.path.splitext(nombre)[0]
                mpy = os.path.join(salida, base + ".mpy")
                self.run_command([exe, "-o", mpy, origen])
                comandos.append((mpy, "/" + base + ".mpy"))
                borrar.append("/" + base + ".py")      # si queda el .py, la placa carga ese
            self.log_queue.put(("log", f"Compilados {sum(r.endswith('.mpy') for _, r in comandos)} modulos.\n"))
            self._upload_worker(comandos, borrar)
        except Exception as error:
            self.log_queue.put(("log", f"\nERROR: {error}\n"))
            self.log_queue.put(("status", "Error"))
            self.log_queue.put(("done", None))

    def upload_selected_files(self):
        if not self.selected_files:
            messagebox.showinfo("Sin archivos", "Primero elige archivos o usa 'Subir paquete completo'.")
            return
        self.upload_files(self.selected_files)

    def config_path(self):
        return os.path.join(CODE_DIR, "config_robot.json")

    def load_wifi_config(self):
        try:
            with open(self.config_path(), "r", encoding="utf-8") as source:
                config = json.load(source)
        except Exception as error:
            self.write_log(f"No pude leer config_robot.json: {error}\n")
            return

        self.ssid_var.set(str(config.get("wifi_ssid", "")))
        self.password_var.set(str(config.get("wifi_password", "")))
        self.ask_wifi_var.set(bool(config.get("ask_wifi_on_boot", False)))

    def build_wifi_config(self):
        ssid = self.ssid_var.get().strip()
        password = self.password_var.get()
        ask_on_boot = bool(self.ask_wifi_var.get())

        if not ask_on_boot and not ssid:
            raise ValueError("El SSID no puede quedar vacio si no vas a preguntar al arrancar.")
        if not ask_on_boot and password and len(password) < 8:
            raise ValueError("El password debe estar vacio o tener al menos 8 caracteres.")

        with open(self.config_path(), "r", encoding="utf-8") as source:
            config = json.load(source)

        config["wifi_ssid"] = ssid
        config["wifi_password"] = password
        config["ask_wifi_on_boot"] = ask_on_boot
        return config

    def save_wifi_local(self):
        try:
            config = self.build_wifi_config()
            with open(self.config_path(), "w", encoding="utf-8") as target:
                json.dump(config, target, indent=2)
                target.write("\n")
            self.write_log("Wi-Fi guardado en config_robot.json local.\n")
            self.status_var.set("Wi-Fi guardado")
            return True
        except Exception as error:
            messagebox.showerror("Wi-Fi", str(error))
            return False

    def save_and_upload_wifi(self):
        if not self.save_wifi_local():
            return
        self.upload_files([self.config_path()])

    def connect_wifi(self):
        """Responde los prompts seriales y deja el rover listo para el control."""
        ssid = self.ssid_var.get().strip()
        password = self.password_var.get()

        if not ssid:
            messagebox.showerror("Wi-Fi", "Escribe el SSID de la red.")
            return

        self.set_busy(True, "Conectando el rover al Wi-Fi...")
        thread = threading.Thread(
            target=self._connect_wifi_worker,
            args=(ssid, password),
            daemon=True,
        )
        thread.start()

    def _connect_wifi_worker(self, ssid, password):
        try:
            try:
                import serial
            except ImportError as error:
                raise RuntimeError(
                    "Falta pyserial. Usa el boton 'Instalar ampy' y vuelve a intentar."
                ) from error

            port = self.port()
            self.log_queue.put(("log", f"Abriendo {port} a 115200 baudios...\n"))
            self.log_queue.put(("log", "Esperando las preguntas del rover...\n"))

            robot_ip, robot_port = self.configure_wifi_over_serial(
                serial, port, ssid, password
            )

            self.log_queue.put(
                ("log", f"\nRover listo en {robot_ip}:{robot_port}.\n")
            )
            self.log_queue.put(
                ("log", "Puerto serie cerrado. Ya puedes abrir prueba_robot.py manualmente.\n")
            )
            self.log_queue.put(("status", f"Rover listo en {robot_ip}:{robot_port}"))
        except Exception as error:
            self.log_queue.put(("log", f"\nERROR: {error}\n"))
            self.log_queue.put(("status", "Error conectando Wi-Fi"))
        finally:
            self.log_queue.put(("done", None))

    def configure_wifi_over_serial(self, serial_module, port, ssid, password):
        """Automatiza el mismo dialogo que se atiende manualmente en miniterm."""
        deadline = time.monotonic() + 60
        received = ""
        sent_ssid = False
        sent_password = False

        try:
            connection = serial_module.Serial(
                port=port,
                baudrate=115200,
                timeout=0.15,
                write_timeout=2,
            )
        except Exception as error:
            raise RuntimeError(
                f"No pude abrir {port}. Cierra miniterm, Thonny o cualquier programa que use el puerto. ({error})"
            ) from error

        try:
            self.restart_circuitpython(connection)
            deadline = time.monotonic() + 60

            while time.monotonic() < deadline:
                chunk = connection.read(max(connection.in_waiting, 1))
                if not chunk:
                    continue

                text = chunk.decode("utf-8", errors="replace")
                received += text
                # Conserva suficiente contexto para prompts divididos entre lecturas.
                received = received[-8000:]
                self.log_queue.put(("log", text))

                if not sent_ssid and "SSID:" in received:
                    connection.write((ssid + "\r\n").encode("utf-8"))
                    connection.flush()
                    sent_ssid = True
                    self.log_queue.put(("log", "[SSID enviado]\n"))

                if not sent_password and "Password:" in received:
                    connection.write((password + "\r\n").encode("utf-8"))
                    connection.flush()
                    sent_password = True
                    if not sent_ssid:
                        self.log_queue.put(
                            ("log", "[SSID ya estaba guardado en el rover]\n")
                        )
                    self.log_queue.put(("log", "[Password enviado]\n"))

                endpoint = self.extract_server_endpoint(received)
                if endpoint:
                    return endpoint

                if "No se pudo conectar al Wi-Fi" in received:
                    raise RuntimeError("El rover rechazo la conexion Wi-Fi. Revisa SSID y password.")

            if not sent_ssid and not sent_password:
                raise RuntimeError(
                    "El rover no solicito credenciales ni confirmo el servidor "
                    "en 60 segundos. Revisa la salida serial y la configuracion."
                )
            raise RuntimeError(
                "El rover recibio las credenciales, pero no confirmo una IP en 60 segundos."
            )
        finally:
            connection.close()

    def restart_circuitpython(self, connection):
        """Interrumpe un input incompleto y reinicia code.py con el monitor abierto."""
        self.log_queue.put(
            ("log", "Sincronizando CircuitPython y reiniciando code.py...\n")
        )

        # ampy reinicia la placa antes de cerrar COM3. En ese pequeño intervalo,
        # code.py puede alcanzar input() y consumir bytes residuales. Ctrl-C lleva
        # la placa al REPL y Ctrl-D hace un soft reload mientras este monitor ya
        # esta conectado, por lo que no se pierde ninguno de los dos prompts.
        try:
            connection.reset_input_buffer()
        except (AttributeError, OSError):
            pass

        connection.write(b"\x03")
        connection.flush()
        time.sleep(0.4)
        connection.write(b"\x04")
        connection.flush()

    @staticmethod
    def extract_server_endpoint(text):
        matches = re.findall(
            r"Comandos de prueba:\s*(\d{1,3}(?:\.\d{1,3}){3})\s+(\d+)",
            text,
        )
        if not matches:
            return None
        ip, port = matches[-1]
        return ip, int(port)

    def upload_files(self, files, borrar=()):
        """files: rutas (se suben con su nombre) o pares (origen, destino en la placa)."""
        commands = []
        for item in files:
            path, remote = item if isinstance(item, tuple) else (item, self.remote_name(item))
            if not os.path.isfile(path):
                self.write_log(f"No existe: {path}\n")
                return
            commands.append((path, remote))

        self.write_log("Se van a subir: " + ", ".join(
            os.path.basename(path) + ("" if os.path.basename(path) == remote.lstrip("/") else " -> " + remote.lstrip("/"))
            for path, remote in commands) + "\n")
        self.set_busy(True, "Subiendo archivos...")
        thread = threading.Thread(target=self._upload_worker, args=(commands, list(borrar)), daemon=True)
        thread.start()

    def reset_board(self):
        self.run_worker("Reiniciando placa...", self.ampy_command("reset", "--hard"))

    def _upload_worker(self, commands, borrar=()):
        try:
            self.log_queue.put(("log", f"Usando puerto {self.port()}\n"))
            for path, remote in commands:
                self.log_queue.put(("log", f"Subiendo {path} -> {remote}\n"))
                self.run_command(self.ampy_command("put", path, remote))
            if borrar:
                # Solo lo que esta: cada llamada a ampy tarda un par de segundos.
                presentes = {"/" + linea.strip().lstrip("/") for linea in self.run_command(self.ampy_command("ls"))}
                borrar = [remote for remote in borrar if remote in presentes]
            for remote in borrar:
                self.log_queue.put(("log", f"Borrando {remote} de la placa (viejo o de otro rover)\n"))
                try:
                    self.run_command(self.ampy_command("rm", remote))
                except RuntimeError:
                    pass                          # no estaba: nada que borrar
            self.log_queue.put(("log", "\nComprobando archivos en la placa...\n"))
            en_placa = {"/" + linea.strip().lstrip("/") for linea in self.run_command(self.ampy_command("ls"))}
            faltan = [remote for _, remote in commands if remote not in en_placa]
            sobran = [remote for remote in borrar if remote.endswith(".py") and remote in en_placa]
            if sobran:
                raise RuntimeError("No se pudieron borrar (la placa los cargaria en vez del .mpy): "
                                   + ", ".join(sobran))
            if faltan:
                raise RuntimeError("No quedaron en la placa: " + ", ".join(faltan))
            self.log_queue.put(("log", f"Los {len(commands)} archivos estan en la placa.\n"))
            self.log_queue.put(("log", "\nReiniciando placa...\n"))
            self.run_command(self.ampy_command("reset", "--hard"))
            self.log_queue.put(("status", "Carga terminada"))
            self.log_queue.put(("done", None))
        except Exception as error:
            self.log_queue.put(("log", f"\nERROR: {error}\n"))
            self.log_queue.put(("status", "Error"))
            self.log_queue.put(("done", None))

    def run_worker(self, status, command):
        self.set_busy(True, status)
        thread = threading.Thread(target=self._command_worker, args=(command,), daemon=True)
        thread.start()

    def _command_worker(self, command):
        try:
            self.run_command(command)
            self.log_queue.put(("status", "Listo"))
        except Exception as error:
            self.log_queue.put(("log", f"\nERROR: {error}\n"))
            self.log_queue.put(("status", "Error"))
        finally:
            self.log_queue.put(("done", None))

    def run_command(self, command):
        process = subprocess.Popen(
            command,
            cwd=PROJECT_ROOT,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
        )

        assert process.stdout is not None
        lines = []
        for line in process.stdout:
            lines.append(line)
            self.log_queue.put(("log", line))

        exit_code = process.wait()
        if exit_code != 0:
            raise RuntimeError(
                "El comando fallo. Revisa dependencias, puerto seleccionado y que el puerto no este ocupado."
            )
        return lines

    def ampy_command(self, *args):
        return [sys.executable, "-m", "ampy.cli", "--port", self.port(), *args]

    def _drain_log_queue(self):
        try:
            while True:
                kind, value = self.log_queue.get_nowait()
                if kind == "log":
                    self.write_log(value)
                elif kind == "status":
                    self.status_var.set(value)
                elif kind == "done":
                    self.set_busy(False, self.status_var.get())
        except queue.Empty:
            pass

        self.after(100, self._drain_log_queue)

    def write_log(self, text):
        self.log.configure(state="normal")
        self.log.insert("end", text)
        self.log.see("end")
        self.log.configure(state="disabled")

    def set_busy(self, busy, status):
        self.busy = busy
        self.status_var.set(status)
        state = "disabled" if busy else "normal"
        for button in (
            self.upload_default_btn,
            self.choose_btn,
            self.upload_selected_btn,
            self.reset_btn,
            self.remove_selected_btn,
            self.clear_selected_btn,
            self.save_wifi_btn,
            self.upload_wifi_btn,
            self.connect_wifi_btn,
        ):
            button.configure(state=state)

    def port(self):
        return self.port_var.get().strip() or "COM3"

    @staticmethod
    def remote_name(path):
        name = os.path.basename(path)
        if name == "code_banco.py":
            return "/code.py"
        return "/" + name

    @staticmethod
    def python_cmd():
        return sys.executable


if __name__ == "__main__":
    app = Esp32Uploader()
    app.mainloop()
