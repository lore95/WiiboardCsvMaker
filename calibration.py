import serial
import re
import time
import threading
import csv
import glob
import sys
import statistics
import numpy as np
from collections import deque
import os
import csv
import re
import numpy as np
from collections import deque
import matplotlib.pyplot as plt  # Optional: comment out if not plotting

# # --- Load calibration functions ---
# calibration_dir = "calibrationWeights"
# conversion_functions = {}

# for filename in os.listdir(calibration_dir):
#     match = re.search(r'(V\d)', filename)
#     if not match:
#         continue

#     sensor = match.group(1)
#     forces = []
#     raw_means = []

#     filepath = os.path.join(calibration_dir, filename)
#     with open(filepath, newline='') as f:
#         reader = csv.reader(f)
#         header = next(reader)
#         for row in reader:
#             try:
#                 force_N = float(row[0])
#                 raw_val = float(row[1])
#                 forces.append(force_N)
#                 raw_means.append(raw_val)
#             except:
#                 print(f"⚠️ Skipping invalid row in {filename}: {row}")
#                 continue

#     if not any(f == 0.0 for f in forces):
#         print(f"❗ WARNING: No 0 N baseline in {filename}. This will cause offset errors.")

#     # Fit linear model
#     coeffs = np.polyfit(raw_means, forces, 1)
#     slope, intercept = coeffs
#     conversion_functions[sensor] = (slope, intercept)

#     # Intercept sanity check
#     if abs(intercept) > 5:
#         print(f"⚠️ {sensor}: Intercept = {intercept:.2f} N — possible calibration issue.")

#     print(f"{sensor} calibration: Force_N = {slope:.4f} * Raw + {intercept:.4f}")

#     # --- Optional: plot for visual check
#     try:
#         fit = np.poly1d(coeffs)
#         x = np.array(raw_means)
#         y = np.array(forces)
#         x_fit = np.linspace(min(x), max(x), 100)
#         y_fit = fit(x_fit)

#         plt.plot(x, y, 'o', label=f'{sensor} data')
#         plt.plot(x_fit, y_fit, '-', label=f'{sensor} fit')
#         plt.xlabel("Raw Value")
#         plt.ylabel("Force (N)")
#         plt.title(f"{sensor} Calibration Fit")
#         plt.grid(True)
#         plt.legend()
#     except Exception as e:
#         print(f"Could not plot {sensor}: {e}")

# # Show all sensor plots in one window
# plt.show()




def find_usbmodem_port():
    ports = glob.glob('/dev/tty.usbmodem*')
    if not ports:
        print("No USB modem device found.")
        sys.exit(1)
    return ports[0]

def record_data(prompt_msg, ser):
    data_buffer = []
    stop_event = threading.Event()
    buffer_lock = threading.Lock()

    # Median filter buffers for V1–V4
    history = [deque(maxlen=3) for _ in range(4)]

    def read_data():
        while not stop_event.is_set():
            try:
                line = ser.readline().decode('utf-8').strip()
                match = re.match(r'Time:(-?\d+),V1:(-?\d+),V2:(-?\d+),V3:(-?\d+),V4:(-?\d+)', line)
                if match:
                    t_ms, v1, v2, v3, v4 = map(int, match.groups())
                    raw_values = [v1, v2, v3, v4]

                    # Update history and apply median
                    smoothed_values = []
                    for i in range(4):
                        history[i].append(raw_values[i])
                        if len(history[i]) == history[i].maxlen:
                            smoothed = int(np.median(history[i]))
                        else:
                            smoothed = raw_values[i]
                        smoothed_values.append(smoothed)

                    with buffer_lock:
                        data_buffer.append([t_ms] + smoothed_values)
            except:
                continue

    def wait_for_enter():
        input(prompt_msg)
        stop_event.set()

    reader_thread = threading.Thread(target=read_data)
    input_thread = threading.Thread(target=wait_for_enter)

    reader_thread.start()
    input_thread.start()

    input_thread.join()
    reader_thread.join()

    with buffer_lock:
        return data_buffer

def compute_means(data):
    v1s = [row[1] for row in data]
    v2s = [row[2] for row in data]
    v3s = [row[3] for row in data]
    v4s = [row[4] for row in data]
    return [statistics.mean(vs) for vs in [v1s, v2s, v3s, v4s]]

# --- Start session
ser = serial.Serial(
    port=find_usbmodem_port(),
    baudrate=9600,
    parity=serial.PARITY_NONE,
    stopbits=serial.STOPBITS_ONE,
    bytesize=serial.EIGHTBITS,
    timeout=1
)

session_label = input("Enter a 2-character label for this sensor calibration: ").strip().upper()
if len(session_label) != 2:
    print("Label must be exactly 2 characters.")
    sys.exit(1)

print("\nStart with NO weight on the board.")
baseline_data = record_data("Recording baseline... Press Enter when stable.\n", ser)
baseline_means = compute_means(baseline_data)
print("Baseline averages:", baseline_means)

# Get first weight and determine sensor
weight_kg = float(input("Now place the FIRST known weight (kg) on a single sensor: "))
weight_N = weight_kg * 9.81
first_data = record_data(f"Recording for {weight_kg:.2f} kg... Press Enter when stable.\n", ser)
first_means = compute_means(first_data)

diffs = [abs(first_means[i] - baseline_means[i]) for i in range(4)]
sensor_index = diffs.index(max(diffs))
sensor_name = f"V{sensor_index+1}"

print(f"\nSensor with most variation: {sensor_name}")
print(f"This sensor will be used for calibration.\n")

# Save baseline and first weight
forces = [0.0, weight_N]
sensor_means = [baseline_means[sensor_index], first_means[sensor_index]]

# Loop for more weights
while True:
    entry = input("Enter another weight in kg (or press Enter to finish): ").strip()
    if not entry:
        break
    try:
        w_kg = float(entry)
        w_N = w_kg * 9.81
        data = record_data(f"Recording for {w_kg:.2f} kg... Press Enter when stable.\n", ser)
        means = compute_means(data)
        forces.append(w_N)
        sensor_means.append(means[sensor_index])
        print(f"{sensor_name} average: {means[sensor_index]:.2f}")
    except:
        print("Invalid input. Try again.")

ser.close()

# Save CSV
filename = f"{session_label}_{sensor_name}_calibration.csv"
with open(filename, 'w', newline='') as f:
    writer = csv.writer(f)
    writer.writerow(["Force_N", f"{sensor_name}_mean"])
    for f_n, v in zip(forces, sensor_means):
        writer.writerow([round(f_n, 3), round(v, 2)])

print(f"\nCalibration data saved to {filename}")