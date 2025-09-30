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
import matplotlib.pyplot as plt  # Optional: enable if you want plots


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

    line_re = re.compile(
        r'Time:(-?\d+),V1:(-?\d+(?:\.\d+)?),V2:(-?\d+(?:\.\d+)?),V3:(-?\d+(?:\.\d+)?),V4:(-?\d+(?:\.\d+)?)'
    )

    def read_data():
        while not stop_event.is_set():
            try:
                line = ser.readline().decode('utf-8', errors='ignore').strip()
                m = line_re.match(line)
                if not m:
                    continue
                t_ms = int(m.group(1))
                raw_values = [float(m.group(i)) for i in range(2, 6)]

                # Update history and apply median
                smoothed_values = []
                for i in range(4):
                    history[i].append(raw_values[i])
                    if len(history[i]) == history[i].maxlen:
                        smoothed = float(np.median(history[i]))
                    else:
                        smoothed = raw_values[i]
                    smoothed_values.append(smoothed)

                with buffer_lock:
                    data_buffer.append([t_ms] + smoothed_values)
            except Exception:
                continue

    def wait_for_enter():
        input(prompt_msg)
        stop_event.set()

    reader_thread = threading.Thread(target=read_data, daemon=True)
    input_thread = threading.Thread(target=wait_for_enter, daemon=True)

    reader_thread.start()
    input_thread.start()

    input_thread.join()
    stop_event.set()
    reader_thread.join(timeout=0.5)

    with buffer_lock:
        return data_buffer

def calculateChannelMean(data):
    if not data:
        return [float('nan')] * 4
    v1s = [row[1] for row in data]
    v2s = [row[2] for row in data]
    v3s = [row[3] for row in data]
    v4s = [row[4] for row in data]
    return [statistics.fmean(vs) for vs in (v1s, v2s, v3s, v4s)]

def calculateMean(data):
    """Return the average of the four channel means (i.e., (m1+m2+m3+m4)/4)."""
    ch_means = calculateChannelMean(data)
    return statistics.fmean(ch_means), ch_means

# ----------------- Session -----------------

# Open serial
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
    ser.close()
    sys.exit(1)

os.makedirs("calibrationWeight", exist_ok=True)

print("\nStart with NO weight on the board (nothing touching).")
baseline_data = record_data("Recording baseline... Press Enter when stable.\n", ser)
baseline_overall, baseline_ch_means = calculateMean(baseline_data)
print(f"Baseline channel means: {', '.join(f'{m:.2f}' for m in baseline_ch_means)}")
print(f"Baseline overall mean (avg of 4): {baseline_overall:.2f}\n")

# First weight (centered)
weight_kg = float(input("Place the FIRST known weight (kg) at the center of the 4 sensors: "))
weight_N = weight_kg * 9.81
first_data = record_data(f"Recording for {weight_kg:.2f} kg... Press Enter when stable.\n", ser)
first_overall, first_ch_means = calculateMean(first_data)
print(f"Channel means: {', '.join(f'{m:.2f}' for m in first_ch_means)}")
print(f"Overall mean (avg of 4): {first_overall:.2f}\n")

# Arrays to save
forces = [0.0, weight_N]
avg_means = [baseline_overall, first_overall]

# More weights
while True:
    entry = input("Enter another weight in kg (centered) — or press Enter to finish: ").strip()
    if not entry:
        break
    try:
        w_kg = float(entry)
        w_N = w_kg * 9.81
        data = record_data(f"Recording for {w_kg:.2f} kg... Press Enter when stable.\n", ser)
        overall_mean, ch_means = calculateMean(data)
        forces.append(w_N)
        avg_means.append(overall_mean)
        print(f"Channel means: {', '.join(f'{m:.2f}' for m in ch_means)}")
        print(f"Overall mean (avg of 4): {overall_mean:.2f}\n")
    except Exception:
        print("Invalid input. Try again.")

ser.close()

# Save CSV (AVG-based)
filename = f"calibrationWeight/{session_label}_AVG_calibration.csv"
with open(filename, 'w', newline='') as f:
    writer = csv.writer(f)
    writer.writerow(["Force_N", "Avg_mean"])
    for f_n, v in zip(forces, avg_means):
        writer.writerow([round(f_n, 3), round(v, 2)])

print(f"\nCalibration data saved to {filename}")
