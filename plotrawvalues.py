import serial
import re
import time
import threading
import glob
import sys
import os
import signal

import matplotlib
matplotlib.use("TkAgg")
import matplotlib.pyplot as plt
from matplotlib.animation import FuncAnimation
from matplotlib.widgets import Button

# ---------- Serial port discovery (macOS-style usbmodem). Adjust if needed. ----------
def find_usbmodem_port():
    ports = glob.glob('/dev/tty.usbmodem*')
    if not ports:
        print("No USB modem device found.")
        sys.exit(1)
    return ports[0]

# ---------- Globals ----------
port_name = find_usbmodem_port()
ser = serial.Serial(
    port=port_name,
    baudrate=9600,
    parity=serial.PARITY_NONE,
    stopbits=serial.STOPBITS_ONE,
    bytesize=serial.EIGHTBITS,
    timeout=1
)

buffer_lock = threading.Lock()
# Each entry: (index, v1_raw, v2_raw, v3_raw, v4_raw)
data_buffer = []
stop_event = threading.Event()

# ---------- Reading thread: ONLY raw values ----------
def read_data():
    index = 0
    pattern = re.compile(
        r'Time:(-?\d+),V1:(-?\d+(?:\.\d+)?),'
        r'V2:(-?\d+(?:\.\d+)?),V3:(-?\d+(?:\.\d+)?),V4:(-?\d+(?:\.\d+)?)'
    )
    while not stop_event.is_set():
        try:
            line = ser.readline().decode('utf-8', errors='ignore').strip()
            print (line)
            match = pattern.match(line)
            print(match)
            if not match:
                continue

            # raw values only
            _t_ms = int(match.group(1))  # unused, but parsed for completeness
            v1, v2, v3, v4 = [float(match.group(i)) for i in range(2, 6)]

            with buffer_lock:
                data_buffer.append((index, v1, v2, v3, v4))
            index += 1

        except Exception as e:
            print(f"Read error: {e}")
            continue

# ---------- Plot setup: one figure, four raw traces ----------
fig = plt.figure(num="Raw Sensor Values (V1–V4)")
ax = fig.add_subplot(1, 1, 1)
lines = [ax.plot([], [], label=f"V{i+1}")[0] for i in range(4)]
ax.set_title("Live Raw Sensor Values")
ax.set_xlabel("Sample Index")
ax.set_ylabel("Raw Value")
ax.grid(True)
ax.legend(loc="upper right")

# Optional "Close" button
btn_ax = fig.add_axes([0.80, 0.02, 0.18, 0.07])  # [left, bottom, width, height]
btn_close = Button(btn_ax, "Close")

# ---------- Live update ----------
HISTORY = 300  # number of most recent points to show

def update_plot(_frame):
    with buffer_lock:
        if len(data_buffer) < 2:
            return lines

        recent = data_buffer[-HISTORY:]
        x_vals = [row[0] for row in recent]
        for i, line in enumerate(lines):
            y_vals = [row[1 + i] for row in recent]  # v1..v4 at indices 1..4
            line.set_data(x_vals, y_vals)

        ax.relim()
        ax.autoscale_view()

    return lines

# ---------- Clean shutdown (no saving) ----------
def shutdown():
    stop_event.set()
    try:
        time.sleep(0.05)
    except Exception:
        pass
    try:
        if 'reading_thread' in globals() and reading_thread.is_alive():
            reading_thread.join(timeout=2)
    except Exception:
        pass
    try:
        ser.close()
    except Exception:
        pass
    plt.close('all')

def _handle_term(_signum, _frame):
    try:
        shutdown()
    finally:
        os._exit(0)

signal.signal(getattr(signal, "SIGTERM", signal.SIGINT), _handle_term)
if hasattr(signal, "SIGBREAK"):
    signal.signal(signal.SIGBREAK, _handle_term)

def on_key(event):
    if event.key == 'escape':
        shutdown()

def on_close(_event):
    shutdown()

def on_close_button(_event):
    shutdown()

btn_close.on_clicked(on_close_button)
fig.canvas.mpl_connect('key_press_event', on_key)
fig.canvas.mpl_connect('close_event', on_close)

# ---------- Main ----------
if __name__ == "__main__":
    reading_thread = threading.Thread(target=read_data, daemon=True)
    reading_thread.start()

    ani = FuncAnimation(fig, update_plot, interval=50, blit=False)
    plt.show()

    # Safety net if show() returns
    shutdown()
    print("Stopped.")