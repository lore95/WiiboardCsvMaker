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
# Optional: exact filename; if None, we'll auto-detect the first *_AVG_calibration.csv
CAL_FILENAME = "WI_AVG_calibration.csv"  

# --- Load single averaged calibration (quadratic fit) ---
def loadCalibrationFile(cal_dir, cal_filename=None):
    # Pick file
    target_path = None
    if cal_filename:
        candidate = os.path.join(cal_dir, cal_filename)
        if not os.path.isfile(candidate):
            print(f"Calibration file not found: {candidate}")
            sys.exit(1)
        target_path = candidate
    else:
        # Prefer files ending with _AVG_calibration.csv; else first CSV containing 'Avg' in header
        for fname in os.listdir(cal_dir):
            if fname.endswith("_AVG_calibration.csv"):
                target_path = os.path.join(cal_dir, fname)
                break
        if target_path is None:
            # Fallback: first CSV that looks like our averaged format
            for fname in os.listdir(cal_dir):
                if not fname.lower().endswith(".csv"):
                    continue
                target_path = os.path.join(cal_dir, fname)
                break
        if target_path is None:
            print(f"No calibration CSV found in {cal_dir}")
            sys.exit(1)

    forces = []
    avg_raws = []

    with open(target_path, newline='') as f:
        reader = csv.reader(f)
        header = next(reader, None)
        # Try to detect columns
        # Expect header like ["Force_N", "Avg_mean"]
        force_idx = 0
        raw_idx = 1
        if header:
            # Heuristic: find "force" and "avg" columns if present
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
                fN = float(row[force_idx])
                r  = float(row[raw_idx])
            except Exception:
                continue
            forces.append(fN)
            avg_raws.append(r)

    if len(forces) < 2:
        print(f"Not enough calibration points in {target_path}")
        sys.exit(1)

    # Fit quadratic: force = a*raw^2 + b*raw + c
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
a, b, c = loadCalibrationFile(CAL_DIR, CAL_FILENAME)

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
data_buffer = []   # tuples: (index, force_N)
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
            raw_values = [float(match.group(i)) for i in range(2, 6)]

            # Step time (unused but could be logged)
            step_ms = 0 if prev_time is None else t_ms - prev_time

            # # Smart noise filter (same logic as before, but checks per-channel deltas)
            # if prev_values:
            #     valid = 0
            #     for p, cval in zip(prev_values, raw_values):
            #         if p == 0:
            #             continue
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

            # ---- Convert using global averaged calibration ----
            avg_raw = sum(raw_values) / 4.0
            force = a * (avg_raw ** 2) + b * avg_raw + c
            force = float(np.round(force, 3))

            with buffer_lock:
                data_buffer.append((index, force))

            prev_time = t_ms
            prev_values = raw_values
            index += 1

        except Exception as e:
            print(f"Read error: {e}")
            continue

# --- Plotting setup (single line: total force) ---
fig, ax = plt.subplots()
(line_total,) = ax.plot([], [], label="Total Force (Avg-calibrated)")
ax.set_title("Live Total Force (N) — Averaged Calibration")
ax.set_xlabel("Sample Index")
ax.set_ylabel("Force (N)")
ax.grid(True)
ax.legend()

def update_plot(frame):
    with buffer_lock:
        if len(data_buffer) < 10:
            return (line_total,)
        recent = data_buffer[-300:]
        x_vals = [row[0] for row in recent]
        y_vals = [row[1] for row in recent]
        line_total.set_data(x_vals, y_vals)
        ax.relim()
        ax.autoscale_view()
    return (line_total,)

# --- Main Execution ---
if __name__ == "__main__":
    reading_thread = threading.Thread(target=read_data, daemon=True)
    reading_thread.start()

    ani = FuncAnimation(fig, update_plot, interval=50, blit=False)
    plt.show()

    stop_event.set()
    reading_thread.join()
    ser.close()
    print("Data collection stopped.")