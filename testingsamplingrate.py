import serial
import time
import csv
import os

def evaluate_sampling_rate(port='/dev/tty.usbmodem123456', baudrate=115200,
                           test_duration_s=10.0, output_dir='sampling_test'):
    """
    Open the specified serial port, capture all lines for test_duration_s seconds,
    save them to a CSV, and print the number of samples and effective rate.

    Args:
        port: the serial device to open (e.g. '/dev/tty.usbmodemXXXX').
        baudrate: the speed that matches your firmware.
        test_duration_s: how long to read data in seconds.
        output_dir: folder to save the captured CSV file.
    """
    ser = serial.Serial(port, baudrate=baudrate, timeout=1)
    os.makedirs(output_dir, exist_ok=True)

    timestamp = int(time.time())
    csv_path = os.path.join(output_dir, f'sampling_test_{timestamp}.csv')
    print(f"Capturing raw lines for {test_duration_s:.1f} s. Saving to {csv_path}")

    start_time = time.time()
    lines = []
    # Read lines until the time has elapsed
    while (time.time() - start_time) < test_duration_s:
        raw = ser.readline()
        if raw:
            decoded = raw.decode('utf-8', errors='ignore').strip()
            lines.append(decoded)

    ser.close()

    # Save the captured lines to CSV
    with open(csv_path, 'w', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(['line'])  # header
        for line in lines:
            writer.writerow([line])

    total_samples = len(lines)
    rate = total_samples / test_duration_s
    print(f"Captured {total_samples} samples in {test_duration_s:.2f} s "
          f"({rate:.1f} samples/s)")

    return csv_path, total_samples, rate

if __name__ == "__main__":
    # Replace the port string with your actual device
    evaluate_sampling_rate(port='/dev/tty.usbmodem2101', baudrate=115200, test_duration_s=10.0)