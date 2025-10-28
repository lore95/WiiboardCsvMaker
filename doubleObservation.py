import serial
import re
import time
import threading
import csv
import glob
import sys
import os
import numpy as np
import signal

import matplotlib
matplotlib.use("TkAgg")
import matplotlib.pyplot as plt
from matplotlib.animation import FuncAnimation
from matplotlib.widgets import Button

CAL_DIR = "calibrationWeight"
CAL_FILENAME = None  # automatically assigned in loop

#load calibration
def load_avg_calibration(cal_dir, cal_filename=None):
    target_path = None
    if cal_filename:
        candidate = os.path.join(cal_dir, cal_filename)
        if not os.path.isfile(candidate):
            print(f"Calibration file not found: {candidate}")
            sys.exit(1)
        target_path = candidate
    else:
        for fname in os.listdir(cal_dir):
            if fname.endswith("_AVG_calibration.csv"):
                target_path = os.path.join(cal_dir, fname)
                break
        if target_path is None:
            for fname in os.listdir(cal_dir):
                if fname.lower().endswith(".csv"):
                    target_path = os.path.join(cal_dir, fname)
                    break
        if target_path is None:
            print(f"No calibration CSV found in {cal_dir}")
            sys.exit(1)

    forces, avg_raws = [], []
    with open(target_path, newline='') as f:
        reader = csv.reader(f)
        header = next(reader, None)
        force_idx, raw_idx = 0, 1
        if header:
            hl = [h.strip().lower() for h in header]
            for i, h in enumerate(hl):
                if "force" in h:
                    force_idx = i
                if "avg" in h or "mean" in h:
                    raw_idx = i
        for row in reader:
            if not row or len(row) < 2:
                continue
            try:
                forces.append(float(row[force_idx]))
                avg_raws.append(float(row[raw_idx]))
            except:
                pass

    if len(forces) < 2:
        print(f"Not enough calibration points in {target_path}")
        sys.exit(1)

    a, b, c = np.polyfit(avg_raws, forces, 2)
    print(f"Loaded AVG calibration from {os.path.basename(target_path)}")
    print(f"Global calibration (quad): F = {a:.6e}·AvgRaw² + {b:.6f}·AvgRaw + {c:.6f}")
    return a, b, c

#port selection todo: make iteratative multiple ports
def find_usbmodem_port():
    ports = glob.glob('/dev/tty.usbmodem*')
    if not ports:
        print("No USB modem device found.")
        sys.exit(1)
    return ports[0]

#setup
a, b, c = load_avg_calibration(CAL_DIR, CAL_FILENAME)

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
# Each entry: (index, v1_raw, v2_raw, v3_raw, v4_raw, F1, F2, F3, F4, F_total)
data_buffer = []
stop_event = threading.Event()
_saved_once = threading.Event()  # prevents double-save on multiple callbacks

# reading thread
def read_data():
    index = 0
    pattern = re.compile(
        r'Time:(-?\d+),V1:(-?\d+(?:\.\d+)?),'
        r'V2:(-?\d+(?:\.\d+)?),V3:(-?\d+(?:\.\d+)?),V4:(-?\d+(?:\.\d+)?)'
    )

    while not stop_event.is_set():
        try:
            line = ser.readline().decode('utf-8', errors='ignore').strip()
            match = pattern.match(line)
            if not match:
                continue

            # raw values
            _t_ms = int(match.group(1))
            v1, v2, v3, v4 = [float(match.group(i)) for i in range(2, 6)]

            # Total force via avg-based quadratic
            avg_raw = (v1 + v2 + v3 + v4) / 4.0
            F_total = a * (avg_raw ** 2) + b * avg_raw + c
            F_total = float(np.round(F_total, 3))

            # Split total force into sensor contributions (N) by raw share
            raw_sum = v1 + v2 + v3 + v4
            if raw_sum != 0:
                weights = [v1/raw_sum, v2/raw_sum, v3/raw_sum, v4/raw_sum]
            else:
                weights = [0.25, 0.25, 0.25, 0.25]

            F1 = float(np.round(F_total * weights[0], 3))
            F2 = float(np.round(F_total * weights[1], 3))
            F3 = float(np.round(F_total * weights[2], 3))
            F4 = float(np.round(F_total * weights[3], 3))

            with buffer_lock:
                data_buffer.append((index, v1, v2, v3, v4, F1, F2, F3, F4, F_total))

            index += 1

        except Exception as e:
            print(f"Read error: {e}")
            continue

#plot setup

# Figure 1: Total Force
fig1 = plt.figure(num="Total Force")
ax1 = fig1.add_subplot(1, 1, 1)
(line_total,) = ax1.plot([], [], label="Total Force (Avg-calibrated)")
ax1.set_title("Live Total Force (N) — Averaged Calibration")
ax1.set_xlabel("Sample Index")
ax1.set_ylabel("Force (N)")
ax1.grid(True)
ax1.legend()

# "Close Both" button on fig1
btn_ax = fig1.add_axes([0.78, 0.02, 0.20, 0.07])  # [left, bottom, width, height]
btn_close = Button(btn_ax, "Close Both")

# Figure 2: Per-sensor distribution
fig2 = plt.figure(num="Force Distribution")
ax2 = fig2.add_subplot(1, 1, 1)
lines_dist = [ax2.plot([], [], label=f"V{i+1} force (N)")[0] for i in range(4)]
ax2.set_title("Per-Sensor Forces (N)")
ax2.set_xlabel("Sample Index")
ax2.set_ylabel("Force (N)")
ax2.grid(True)
ax2.legend()

#realtime plots
def update_plot_total(_frame):
    with buffer_lock:
        if len(data_buffer) < 10:
            return (line_total,)
        recent = data_buffer[-300:]
        x_vals = [row[0] for row in recent]
        y_vals = [row[9] for row in recent]  # F_total at index 9
        line_total.set_data(x_vals, y_vals)
        ax1.relim()
        ax1.autoscale_view()
    return (line_total,)

def update_plot_distribution(_frame):
    with buffer_lock:
        if len(data_buffer) < 10:
            return lines_dist
        recent = data_buffer[-300:]
        x_vals = [row[0] for row in recent]
        for i, line in enumerate(lines_dist):
            y_vals = [row[5 + i] for row in recent]  # F1..F4 at indices 5..8
            line.set_data(x_vals, y_vals)
        ax2.relim()
        ax2.autoscale_view()
    return lines_dist

#create and save csv
def finalize_and_exit():
    # make idempotent
    if _saved_once.is_set():
        return
    _saved_once.set()

    stop_event.set()
    try:
        # give the reader a moment to exit cleanly
        time.sleep(0.05)
    except Exception:
        pass
    try:
        if 'reading_thread' in globals() and reading_thread.is_alive():
            reading_thread.join(timeout=2)
    except Exception:
        pass

    with buffer_lock:
        rows = list(data_buffer)

    # Save CSV with BOTH raw and force values
    try:
        import datetime
        os.makedirs("Readings", exist_ok=True)
        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        save_filename = f"Readings/session_{ts}.csv"
        with open(save_filename, "w", newline="") as f:
            w = csv.writer(f)
            w.writerow([
                "v1_raw", "v2_raw", "v3_raw", "v4_raw",
                "v1_force_N", "v2_force_N", "v3_force_N", "v4_force_N",
                "total_force_N"
            ])
            for row in rows:
                _, v1, v2, v3, v4, F1, F2, F3, F4, Ft = row
                w.writerow([v1, v2, v3, v4, F1, F2, F3, F4, Ft])
        print(f"Saved {len(rows)} rows to {save_filename}")
    except Exception as e:
        print(f"Failed to save CSV: {e}")

    try:
        ser.close()
    except Exception:
        pass

    plt.close('all')  # closes both windows

#stop from app
def _handle_term(_signum, _frame):
    try:
        finalize_and_exit()
    finally:
        os._exit(0)

# POSIX: handle SIGTERM; Windows: handle SIGBREAK if available
signal.signal(getattr(signal, "SIGTERM", signal.SIGINT), _handle_term)
if hasattr(signal, "SIGBREAK"):  # Windows console CTRL_BREAK_EVENT
    signal.signal(signal.SIGBREAK, _handle_term)

#gui
def on_key(event):
    if event.key == 'escape':
        finalize_and_exit()

def on_close(_event):
    finalize_and_exit()

def on_close_both(_event):
    finalize_and_exit()

btn_close.on_clicked(on_close_both)

fig1.canvas.mpl_connect('key_press_event', on_key)
fig2.canvas.mpl_connect('key_press_event', on_key)
fig1.canvas.mpl_connect('close_event', on_close)
fig2.canvas.mpl_connect('close_event', on_close)

if __name__ == "__main__":
    reading_thread = threading.Thread(target=read_data, daemon=True)
    reading_thread.start()

    ani1 = FuncAnimation(fig1, update_plot_total, interval=50, blit=False)
    ani2 = FuncAnimation(fig2, update_plot_distribution, interval=50, blit=False)

    # Show both figures; Esc or closing either window triggers finalize_and_exit()
    plt.show()

    # Safety net: if show() returns without Esc/handlers firing, still finalize
    finalize_and_exit()
    print("Data collection stopped.")