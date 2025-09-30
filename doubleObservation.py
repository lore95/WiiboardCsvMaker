import serial
import re
import time
import threading
import csv
import glob
import sys
import os
import numpy as np
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
            except:  # ignore bad rows
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
# Each entry: (index, F_total, F1, F2, F3, F4)
data_buffer = []
stop_event = threading.Event()

# --- Data reader thread ---
def read_data():
    index = 0
    prev_time = None
    prev_values = None
    skipped_counter = 0

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

            t_ms = int(match.group(1))
            raws = [float(match.group(i)) for i in range(2, 6)]

            # # Smart noise filter (same as before)
            # if prev_values:
            #     valid = 0
            #     for p, cval in zip(prev_values, raws):
            #         if p == 0: continue
            #         if abs(cval - p) / (abs(p) if p != 0 else 1) < 1.8:
            #             valid += 1
            #     if valid < 2:
            #         skipped_counter += 1
            #         if skipped_counter <= 10:
            #             print(f"Skipped noisy frame {index} (valid={valid}/4)")
            #             continue
            #         else:
            #             print("⚠️ Forcing accept after 10 skips")
            #             skipped_counter = 0
            #     else:
            #         skipped_counter = 0

            # Total force via avg-based quadratic
            avg_raw = sum(raws) / 4.0
            F_total = a * (avg_raw ** 2) + b * avg_raw + c
            F_total = float(np.round(F_total, 3))

            # Distribute total force proportionally to raw contributions
            raw_sum = sum(raws)
            if raw_sum != 0:
                weights = [r / raw_sum for r in raws]
            else:
                weights = [0.25, 0.25, 0.25, 0.25]  # fallback
            F_parts = [float(np.round(F_total * w, 3)) for w in weights]

            with buffer_lock:
                data_buffer.append((index, F_total, *F_parts))

            prev_time = t_ms
            prev_values = raws
            index += 1

        except Exception as e:
            print(f"Read error: {e}")
            continue

# --- Plot 1: Total force (single line) ---
fig1, ax1 = plt.subplots()
(line_total,) = ax1.plot([], [], label="Total Force (Avg-calibrated)")
ax1.set_title("Live Total Force (N) — Averaged Calibration")
ax1.set_xlabel("Sample Index")
ax1.set_ylabel("Force (N)")
ax1.grid(True)
ax1.legend()

def update_plot_total(frame):
    with buffer_lock:
        if len(data_buffer) < 10:
            return (line_total,)
        recent = data_buffer[-300:]
        x_vals = [row[0] for row in recent]
        y_vals = [row[1] for row in recent]  # F_total
        line_total.set_data(x_vals, y_vals)
        ax1.relim()
        ax1.autoscale_view()
    return (line_total,)

# --- Plot 2: Force distribution per sensor (4 lines) ---
fig2, ax2 = plt.subplots()
lines_dist = [ax2.plot([], [], label=f"V{i+1} share")[0] for i in range(4)]
ax2.set_title("Force Distribution per Sensor (N)")
ax2.set_xlabel("Sample Index")
ax2.set_ylabel("Force (N)")
ax2.grid(True)
ax2.legend()

def update_plot_distribution(frame):
    with buffer_lock:
        if len(data_buffer) < 10:
            return lines_dist
        recent = data_buffer[-300:]
        x_vals = [row[0] for row in recent]
        for i, line in enumerate(lines_dist):
            # F1..F4 are columns 2..5 in data_buffer tuple
            y_vals = [row[2 + i] for row in recent]
            line.set_data(x_vals, y_vals)
        ax2.relim()
        ax2.autoscale_view()
    return lines_dist

# --- Main Execution ---
if __name__ == "__main__":
    reading_thread = threading.Thread(target=read_data, daemon=True)
    reading_thread.start()

    ani1 = FuncAnimation(fig1, update_plot_total, interval=50, blit=False)
    ani2 = FuncAnimation(fig2, update_plot_distribution, interval=50, blit=False)

    plt.show()

    stop_event.set()
    reading_thread.join()
    ser.close()
    print("Data collection stopped.")