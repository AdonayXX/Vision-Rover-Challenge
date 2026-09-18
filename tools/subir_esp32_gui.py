import os
import queue
import subprocess
import threading
import tkinter as tk
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
    os.path.join(CODE_DIR, "ideaboard.py"),
]


class Esp32Uploader(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Subir archivos a ESP32")
        self.geometry("760x520")
        self.minsize(650, 420)

        self.log_queue = queue.Queue()
        self.busy = False
        self.selected_files = []

        self.port_var = tk.StringVar(value="COM3")
        self.status_var = tk.StringVar(value="Listo")

        self._build_ui()
        self.after(100, self._drain_log_queue)

    def _build_ui(self):
        root = ttk.Frame(self, padding=12)
        root.pack(fill="both", expand=True)

        top = ttk.Frame(root)
        top.pack(fill="x")

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

        selected_box = ttk.LabelFrame(root, text="Archivos seleccionados")
        selected_box.pack(fill="x", pady=(0, 10))

        self.selected_label = ttk.Label(
            selected_box,
            text="Ninguno. Usa 'Subir paquete completo' para cargar el set del robot.",
            anchor="w",
        )
        self.selected_label.pack(fill="x", padx=8, pady=8)

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
        self.run_worker("Detectando puertos...", [self.python_cmd(), "-m", "serial.tools.list_ports"])

    def install_ampy(self):
        self.run_worker("Instalando ampy...", [self.python_cmd(), "-m", "pip", "install", "adafruit-ampy"])

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

        self.selected_files = list(files)
        names = ", ".join(os.path.basename(path) for path in self.selected_files)
        self.selected_label.configure(text=names)

    def upload_default_package(self):
        self.upload_files(DEFAULT_FILES)

    def upload_selected_files(self):
        if not self.selected_files:
            messagebox.showinfo("Sin archivos", "Primero elige archivos o usa 'Subir paquete completo'.")
            return
        self.upload_files(self.selected_files)

    def upload_files(self, files):
        commands = []
        for path in files:
            if not os.path.isfile(path):
                self.write_log(f"No existe: {path}\n")
                return
            remote = self.remote_name(path)
            commands.append((path, remote))

        self.set_busy(True, "Subiendo archivos...")
        thread = threading.Thread(target=self._upload_worker, args=(commands,), daemon=True)
        thread.start()

    def reset_board(self):
        self.run_worker("Reiniciando placa...", ["ampy", "--port", self.port(), "reset", "--hard"])

    def _upload_worker(self, commands):
        try:
            self.log_queue.put(("log", f"Usando puerto {self.port()}\n"))
            for path, remote in commands:
                self.log_queue.put(("log", f"Subiendo {path} -> {remote}\n"))
                self.run_command(["ampy", "--port", self.port(), "put", path, remote])
            self.log_queue.put(("log", "\nReiniciando placa...\n"))
            self.run_command(["ampy", "--port", self.port(), "reset", "--hard"])
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
        for line in process.stdout:
            self.log_queue.put(("log", line))

        exit_code = process.wait()
        if exit_code != 0:
            raise RuntimeError(
                "El comando fallo. Revisa que el puerto no este ocupado por Thonny, miniterm o VS Code."
            )

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
        return "python"


if __name__ == "__main__":
    app = Esp32Uploader()
    app.mainloop()
