import serial
import re
import time
import threading
import csv
import glob
import sys
import os
import numpy as np

# --- Load calibration functions (quadratic fit) ---
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
            forces.append(float(row[0]))
            raw_means.append(float(row[1]))

    # Fit a quadratic curve: force = a*raw^2 + b*raw + c
    a, b, c = np.polyfit(raw_means, forces, 2)
    conversion_functions[sensor] = (a, b, c)
    print(f"{sensor} calibration (quad): F = {a:.6e}·Raw² + {b:.6f}·Raw + {c:.6f}")

# --- Find USB modem port ---
def find_usbmodem_port():
    ports = glob.glob('/dev/tty.usbmodem*')
    if not ports:
        print("No USB modem device found.")
        sys.exit(1)
    print("connected to:", ports[0])
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

    pattern = re.compile(
        r'Time:(-?\d+),V1:(-?\d+(?:\.\d+)?),V2:(-?\d+(?:\.\d+)?),'
        r'V3:(-?\d+(?:\.\d+)?),V4:(-?\d+(?:\.\d+)?)'
    )

    while not stop_event.is_set():
        try:
            line = ser.readline().decode('utf-8', errors='ignore').strip()
            match = pattern.match(line)
            if not match:
                continue

            t_ms = int(match.group(1))
            raw_values = [float(match.group(i)) for i in range(2, 6)]

            # Step time
            step_ms = 0 if prev_time is None else t_ms - prev_time

            # Smart noise filter
            if prev_values:
                valid = 0
                for p, c in zip(prev_values, raw_values):
                    if p == 0:
                        continue
                    if abs(c - p) / abs(p) < 1.5:
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

            # Apply quadratic calibration per sensor
            converted_values = []
            for i, raw in enumerate(raw_values):
                label = f"V{i+1}"
                if raw is None or label not in conversion_functions:
                    converted = None
                else:
                    a, b, c = conversion_functions[label]
                    force = a * raw**2 + b * raw + c
                    converted = round(force, 3)
                converted_values.append(converted)

            print(index, t_ms, step_ms, *raw_values)
            new_entry = [index, t_ms, step_ms] + converted_values

            with buffer_lock:
                data_buffer.append(new_entry)

            prev_time = t_ms
            prev_values = raw_values
            index += 1

        except Exception as e:
            print(f"Error: {e}")
            break

# --- Save data to CSV (unchanged) ---
def save_to_csv(filename="data_converted.csv"):
    with buffer_lock:
        with open(filename, 'w', newline='') as f:
            writer = csv.writer(f)
            writer.writerow(["Index", "DeviceTime_ms", "Step_ms", "V1", "V2", "V3", "V4"])
            writer.writerows(data_buffer)
    print(f"Data saved to {filename}")

# --- Main Execution ---
if __name__ == "__main__":
    reading_thread = threading.Thread(target=read_data, daemon=True)
    reading_thread.start()

    try:
        input("Press Enter to stop and save data...\n")
    except KeyboardInterrupt:
        print("\nInterrupted by user.")

    stop_event.set()
    reading_thread.join()
    ser.close()

    save_to_csv()
    print("Data collection stopped.")