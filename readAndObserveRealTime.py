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

# --- Load calibration functions ---
calibration_dir = "calibrationWeights"
conversion_functions = {}

for filename in os.listdir(calibration_dir):
    match = re.search(r'(V\d)', filename)
    if not match:
        continue

    sensor = match.group(1)
    forces = []
    raw_means = []

    filepath = os.path.join(calibration_dir, filename)
    with open(filepath, newline='') as f:
        reader = csv.reader(f)
        next(reader)  # Skip header
        for row in reader:
            force_N = float(row[0])
            raw_val = float(row[1])
            forces.append(force_N)
            raw_means.append(raw_val)

    coeffs = np.polyfit(raw_means, forces, 1)
    slope, intercept = coeffs
    conversion_functions[sensor] = (slope, intercept)
    print(f"{sensor} calibration: Force_N = {slope:.4f} * Raw + {intercept:.4f}")

# --- Find USB modem port ---
def find_usbmodem_port():
    ports = glob.glob('/dev/tty.usbmodem*')
    if not ports:
        print("No USB modem device found.")
        sys.exit(1)
    return ports[0]

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
data_buffer = []
stop_event = threading.Event()

# --- Data reader thread ---
def read_data():
    index = 0
    prev_time = None
    prev_values = None
    skipped_counter = 0

    while not stop_event.is_set():
        try:
            line = ser.readline().decode('utf-8').strip()
            match = re.match(r'Time:(-?\d+),V1:(-?\d+),V2:(-?\d+),V3:(-?\d+),V4:(-?\d+)', line)
            if not match:
                continue

            t_ms, v1, v2, v3, v4 = map(int, match.groups())
            raw_values = [v1, v2, v3, v4]

            # Step time
            step_ms = 0 if prev_time is None else t_ms - prev_time

            # Smart noise filter
            if prev_values:
                valid = 0
                for i in range(4):
                    prev_v = prev_values[i]
                    curr_v = raw_values[i]
                    if prev_v == 0:
                        continue
                    percent_change = abs(curr_v - prev_v) / abs(prev_v)
                    if percent_change < 1.8:
                        valid += 1

                if valid < 2:
                    skipped_counter += 1
                    if skipped_counter <= 10:
                        print(f"Skipped noisy frame {index} (valid={valid}/4)")
                        continue
                    else:
                        print("⚠️ Forcing accept after 10 skips")
                        skipped_counter = 0
                else:
                    skipped_counter = 0

            # Convert to Newtons
            converted_values = []
            for i, raw in enumerate(raw_values):
                label = f"V{i+1}"
                if label in conversion_functions:
                    slope, intercept = conversion_functions[label]
                    converted = slope * raw + intercept
                else:
                    converted = None
                converted_values.append(converted)

            with buffer_lock:
                data_buffer.append((index, *converted_values))

            prev_time = t_ms
            prev_values = raw_values
            index += 1

        except Exception as e:
            print(f"Read error: {e}")
            continue

# --- Plotting setup ---
fig, ax = plt.subplots()
lines = [ax.plot([], [], label=f"V{i+1}")[0] for i in range(4)]
ax.set_title("Live Sensor Data (Forces in Newtons)")
ax.set_xlabel("Sample Index")
ax.set_ylabel("Force (N)")
ax.grid(True)
ax.legend()

def update_plot(frame):
    with buffer_lock:
        if len(data_buffer) < 10:
            return
        recent = data_buffer[-100:]
        x_vals = [row[0] for row in recent]
        for i in range(4):
            y_vals = [row[i+1] for row in recent]
            lines[i].set_data(x_vals, y_vals)
        ax.relim()
        ax.autoscale_view()

# --- Main Execution ---
if __name__ == "__main__":
    reading_thread = threading.Thread(target=read_data, daemon=True)
    reading_thread.start()

    ani = FuncAnimation(fig, update_plot, interval=50)
    plt.show()

    stop_event.set()
    reading_thread.join()
    ser.close()
    print("Data collection stopped.")