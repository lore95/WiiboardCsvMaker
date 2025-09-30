import serial
import re
import time
import threading
import csv
import glob
import sys
import os
import numpy as np

import matplotlib
# Choose a GUI backend that opens real windows
matplotlib.use("TkAgg")   # or "QtAgg" / "Qt5Agg" / "MacOSX" (Mac only)
import matplotlib.pyplot as plt
from matplotlib.animation import FuncAnimation

# --- CONFIG ---
CAL_DIR = "calibrationWeight"
CAL_FILENAME = None  # e.g. "AB_AVG_calibration.csv"

# --- Load single averaged calibration (quadratic fit) ---
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
                if "force" in h: force_idx = i
                if "avg" in h or "mean" in h: raw_idx = i
        for row in reader:
            if not row or len(row) < 2: continue
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

# --- Find USB modem port ---
def find_usbmodem_port():
    ports = glob.glob('/dev/tty.usbmodem*')
    if not ports:
        print("No USB modem device found.")
        sys.exit(1)
    return ports[0]

# Load calibration (single global)
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

# --- Shared state ---
buffer_lock = threading.Lock()
# Each entry: (index, v1, v2, v3, v4, F_total)
data_buffer = []
stop_event = threading.Event()
_saved_once = threading.Event()  # prevents double-save on multiple callbacks

# --- Data reader thread ---
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

            with buffer_lock:
                data_buffer.append((index, v1, v2, v3, v4, F_total))

            index += 1

        except Exception as e:
            print(f"Read error: {e}")
            continue

# --- Plot 1: Total force (single line) ---
fig1 = plt.figure(num="Total Force")
ax1 = fig1.add_subplot(1, 1, 1)
(line_total,) = ax1.plot([], [], label="Total Force (Avg-calibrated)")
ax1.set_title("Live Total Force (N) — Averaged Calibration")
ax1.set_xlabel("Sample Index")
ax1.set_ylabel("Force (N)")
ax1.grid(True)
ax1.legend()

def update_plot_total(_frame):
    with buffer_lock:
        if len(data_buffer) < 10:
            return (line_total,)
        recent = data_buffer[-300:]
        x_vals = [row[0] for row in recent]
        y_vals = [row[5] for row in recent]  # F_total
        line_total.set_data(x_vals, y_vals)
        ax1.relim()
        ax1.autoscale_view()
    return (line_total,)

# --- Plot 2: Force distribution per sensor (4 lines) ---
fig2 = plt.figure(num="Force Distribution")
ax2 = fig2.add_subplot(1, 1, 1)
lines_dist = [ax2.plot([], [], label=f"V{i+1} share")[0] for i in range(4)]
ax2.set_title("Force Distribution per Sensor (N)")
ax2.set_xlabel("Sample Index")
ax2.set_ylabel("Force (N)")
ax2.grid(True)
ax2.legend()

def update_plot_distribution(_frame):
    with buffer_lock:
        if len(data_buffer) < 10:
            return lines_dist
        recent = data_buffer[-300:]
        x_vals = [row[0] for row in recent]

        for i, line in enumerate(lines_dist):
            y_vals = []
            for _, v1, v2, v3, v4, Ft in recent:
                raw_sum = v1 + v2 + v3 + v4
                if raw_sum != 0:
                    weights = [v1/raw_sum, v2/raw_sum, v3/raw_sum, v4/raw_sum]
                else:
                    weights = [0.25, 0.25, 0.25, 0.25]
                y_vals.append(float(np.round(Ft * weights[i], 3)))
            line.set_data(x_vals, y_vals)

        ax2.relim()
        ax2.autoscale_view()
    return lines_dist

# --- Finalize: save CSV + close everything ---
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
        # join if it exists and is alive (set later in main)
        if 'reading_thread' in globals() and reading_thread.is_alive():
            reading_thread.join(timeout=2)
    except Exception:
        pass

    with buffer_lock:
        rows = list(data_buffer)

    # Save CSV with required columns
    try:
        import datetime
        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        save_filename = f"Readings/session_{ts}.csv"
        with open(save_filename, "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["v1", "v2", "v3", "v4", "total_force_N"])
            for _, v1, v2, v3, v4, Ft in rows:
                w.writerow([v1, v2, v3, v4, Ft])
        print(f"Saved {len(rows)} rows to {save_filename}")
    except Exception as e:
        print(f"Failed to save CSV: {e}")

    try:
        ser.close()
    except Exception:
        pass

    plt.close('all')  # closes both windows

# --- Keyboard & close handlers ---
def on_key(event):
    if event.key == 'escape':
        finalize_and_exit()

def on_close(_event):
    # If a window is closed via the UI, still save once.
    finalize_and_exit()

fig1.canvas.mpl_connect('key_press_event', on_key)
fig2.canvas.mpl_connect('key_press_event', on_key)
fig1.canvas.mpl_connect('close_event', on_close)
fig2.canvas.mpl_connect('close_event', on_close)

# --- Main Execution ---
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