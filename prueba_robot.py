import argparse
import socket
import tkinter as tk


def parse_args():
    parser = argparse.ArgumentParser(description="Control manual del CenfoBot por Wi-Fi")
    parser.add_argument("--host", default="10.50.42.207", help="IP del rover")
    parser.add_argument("--port", type=int, default=5000, help="Puerto TCP del rover")
    return parser.parse_args()

ARGS = parse_args()
ROBOT_IP = ARGS.host
ROBOT_PORT = ARGS.port

SPEED = 0.55
PUSH_SPEED = 1.00
SEND_INTERVAL_MS = 60

sock = None
current_command = "STOP"


def connect_robot():
    global sock

    try:
        if sock is not None:
            sock.close()

        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(6)
        sock.connect((ROBOT_IP, ROBOT_PORT))
        sock.settimeout(1)

        status_label.config(text=f"Conectado a {ROBOT_IP}:{ROBOT_PORT}")
        print("Conectado al robot")

    except Exception as error:
        sock = None
        status_label.config(text=f"Error: {error}")


def send_command(command):
    global sock

    if sock is None:
        return

    try:
        sock.sendall((command + "\n").encode())
        response = sock.recv(64).decode().strip()

        if response:
            print(command, "->", response)

    except Exception as error:
        status_label.config(text=f"Desconectado: {error}")

        try:
            sock.close()
        except OSError:
            pass

        sock = None


def repeat_command():
    if current_command != "STOP":
        send_command(current_command)

    root.after(SEND_INTERVAL_MS, repeat_command)


def start_move(command):
    global current_command

    current_command = command
    send_command(command)


def stop_move(event=None):
    global current_command

    current_command = "STOP"
    send_command("STOP")


def forward(event=None):
    start_move(f"MOTOR {SPEED} {SPEED}")


def push_cube(event=None):
    start_move(f"MOTOR {PUSH_SPEED} {PUSH_SPEED}")


def backward(event=None):
    start_move(f"MOTOR {-SPEED} {-SPEED}")


def left(event=None):
    start_move(f"MOTOR {-SPEED} {SPEED}")


def right(event=None):
    start_move(f"MOTOR {SPEED} {-SPEED}")


root = tk.Tk()
root.title("Control CenfoBot")
root.geometry("420x510")
root.resizable(False, False)

title = tk.Label(root, text="CenfoBot", font=("Arial", 22, "bold"))
title.pack(pady=15)

status_label = tk.Label(root, text="Desconectado", font=("Arial", 12))
status_label.pack()

connect_button = tk.Button(
    root,
    text="Conectar",
    font=("Arial", 12),
    command=connect_robot,
)
connect_button.pack(pady=10)

frame = tk.Frame(root)
frame.pack(pady=15)

btn_up = tk.Button(frame, text="UP", width=7, height=2, font=("Arial", 16))
btn_up.grid(row=0, column=1, padx=5, pady=5)

btn_left = tk.Button(frame, text="LEFT", width=7, height=2, font=("Arial", 16))
btn_left.grid(row=1, column=0, padx=5, pady=5)

btn_stop = tk.Button(
    frame,
    text="STOP",
    width=7,
    height=2,
    font=("Arial", 14, "bold"),
    command=stop_move,
)
btn_stop.grid(row=1, column=1, padx=5, pady=5)

btn_right = tk.Button(frame, text="RIGHT", width=7, height=2, font=("Arial", 16))
btn_right.grid(row=1, column=2, padx=5, pady=5)

btn_down = tk.Button(frame, text="DOWN", width=7, height=2, font=("Arial", 16))
btn_down.grid(row=2, column=1, padx=5, pady=5)

btn_push = tk.Button(
    root,
    text="EMPUJAR CUBO  (mantener ESPACIO)",
    font=("Arial", 12, "bold"),
    height=2,
)
btn_push.pack(pady=(5, 0), padx=20, fill="x")

speed_label = tk.Label(
    root,
    text=f"Movimiento: {SPEED:.2f}   |   Empuje: {PUSH_SPEED:.2f}",
    font=("Arial", 10),
)
speed_label.pack(pady=8)

btn_up.bind("<ButtonPress-1>", lambda event: forward())
btn_up.bind("<ButtonRelease-1>", stop_move)

btn_down.bind("<ButtonPress-1>", lambda event: backward())
btn_down.bind("<ButtonRelease-1>", stop_move)

btn_left.bind("<ButtonPress-1>", lambda event: left())
btn_left.bind("<ButtonRelease-1>", stop_move)

btn_right.bind("<ButtonPress-1>", lambda event: right())
btn_right.bind("<ButtonRelease-1>", stop_move)

btn_push.bind("<ButtonPress-1>", push_cube)
btn_push.bind("<ButtonRelease-1>", stop_move)

root.bind("<KeyPress-Up>", forward)
root.bind("<KeyPress-Down>", backward)
root.bind("<KeyPress-Left>", left)
root.bind("<KeyPress-Right>", right)

root.bind("<KeyRelease-Up>", stop_move)
root.bind("<KeyRelease-Down>", stop_move)
root.bind("<KeyRelease-Left>", stop_move)
root.bind("<KeyRelease-Right>", stop_move)

root.bind("<KeyPress-w>", forward)
root.bind("<KeyPress-s>", backward)
root.bind("<KeyPress-a>", left)
root.bind("<KeyPress-d>", right)

root.bind("<KeyRelease-w>", stop_move)
root.bind("<KeyRelease-s>", stop_move)
root.bind("<KeyRelease-a>", stop_move)
root.bind("<KeyRelease-d>", stop_move)

root.bind("<KeyPress-space>", push_cube)
root.bind("<KeyRelease-space>", stop_move)

repeat_command()
root.after(1500, connect_robot)

root.mainloop()
