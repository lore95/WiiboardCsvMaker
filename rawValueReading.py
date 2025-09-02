import re
import csv
import sys
import glob
import threading
from datetime import datetime

# pip install pyserial
try:
    import serial
except ImportError:
    print("This script requires pyserial. Install with: pip install pyserial")
    sys.exit(1)

BAUDRATE = 115200   # <-- adjust if your device uses a different baud rate
READ_TIMEOUT = 0.2  # seconds; keeps the loop responsive to the stop signal

# --- Regex for your buffer format ---
pattern = re.compile(
    r'Time:(-?\d+),V1:(-?\d+(?:\.\d+)?),V2:(-?\d+(?:\.\d+)?),'
    r'V3:(-?\d+(?:\.\d+)?),V4:(-?\d+(?:\.\d+)?)'
)

# --- Find USB modem port ---
def find_usbmodem_port():
    ports = glob.glob('/dev/tty.usbmodem*')
    if not ports:
        print("No USB modem device found.")
        sys.exit(1)
    return ports[0]

def main():
    port = find_usbmodem_port()
    print(f"Opening serial port: {port} @ {BAUDRATE} baud")

    # Open serial
    try:
        ser = serial.Serial(port, BAUDRATE, timeout=READ_TIMEOUT)
    except serial.SerialException as e:
        print(f"Failed to open serial port {port}: {e}")
        sys.exit(1)

    # Storage for CSV rows
    readings = []  # rows: [Time, V1, V2, V3, V4]

    # Stop flag controlled by Enter key
    stop_event = threading.Event()

    def wait_for_enter():
        input("\nReading… Press ENTER to stop and save to raw_readings.csv\n")
        stop_event.set()

    stopper = threading.Thread(target=wait_for_enter, daemon=True)
    stopper.start()

    try:
        while not stop_event.is_set():
            try:
                raw = ser.readline()   # reads a line (ends with \n) or times out
            except serial.SerialException as e:
                print(f"\nSerial error: {e}")
                break

            if not raw:
                continue  # timeout—loop again so we can notice stop_event

            # Decode to text safely
            try:
                line = raw.decode('utf-8', errors='replace').strip()
            except Exception:
                # Fallback if decoding fails unexpectedly
                line = str(raw).strip()

            match = pattern.search(line)
            if match:
                time_val, v1, v2, v3, v4 = match.groups()
                print(f"V1={v1}, V2={v2}, V3={v3}, V4={v4}")
                readings.append([time_val, v1, v2, v3, v4])

    except KeyboardInterrupt:
        print("\nInterrupted by user (Ctrl+C).")
    finally:
        ser.close()

    # Write CSV
    if readings:
        out_path = "raw_readings.csv"
        try:
            with open(out_path, "w", newline="") as f:
                writer = csv.writer(f)
                writer.writerow(["Time", "V1", "V2", "V3", "V4"])
                writer.writerows(readings)
            print(f"Saved {len(readings)} rows to {out_path}")
        except OSError as e:
            print(f"Failed to write CSV: {e}")
    else:
        print("No valid readings captured—CSV not created.")

if __name__ == "__main__":
    main()