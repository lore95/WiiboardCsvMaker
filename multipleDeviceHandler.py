import re
import time
import threading
import csv
import glob
import sys
import os
import signal
from datetime import datetime

import numpy as np
import serial

import matplotlib
matplotlib.use("TkAgg")
import matplotlib.pyplot as plt
from matplotlib.animation import FuncAnimation
from matplotlib.widgets import Button
from matplotlib.gridspec import GridSpec


CAL_DIR = "calibrationWeight"
CAL_FILENAME = None          # if None, auto-pick a calibration CSV from CAL_DIR
MAX_DEVICES = 4              # we only place up to 4 devices in the window corners
SAVE_DIR = "Readings"        # where per-device CSVs are saved
PLOT_HISTORY = 300           # number of samples to keep visible in live plots
BAUDRATE = 9600

# =========================
# Load calibration
# =========================
#TODO: create a calibration loading based on device name
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

A_COEFFS = load_avg_calibration(CAL_DIR, CAL_FILENAME)  # (a, b, c)

# =========================
# Serial port opening
# =========================
def list_serial_devices():
    candidates = []
    # macOS
    candidates += glob.glob('/dev/tty.usbmodem*')
    # Linux
    candidates += glob.glob('/dev/ttyACM*')
    candidates += glob.glob('/dev/ttyUSB*')
    # Windows (validated on open)
    candidates += [f"COM{i}" for i in range(1, 257)]

    uniq, seen = [], set()
    for p in candidates:
        if p not in seen:
            uniq.append(p); seen.add(p)
    return uniq

def try_open_serial(port):
    try:
        return serial.Serial(
            port=port,
            baudrate=BAUDRATE,
            parity=serial.PARITY_NONE,
            stopbits=serial.STOPBITS_ONE,
            bytesize=serial.EIGHTBITS,
            timeout=1
        )
    except Exception:
        return None

# =========================
# Wiiboards setup
# =========================
class DeviceContext:
    """
    One device: serial, buffers, thread, and a single total-force subplot.
    """
    def __init__(self, port, ser, ax_total):
        self.port = port
        self.port_sanitized = port.replace("/", "_").replace("\\", "_").replace(":", "_")
        self.ser = ser
        self.a, self.b, self.c = A_COEFFS

        # data
        self.lock = threading.Lock()
        # Each entry: (index, v1_raw, v2_raw, v3_raw, v4_raw, F1, F2, F3, F4, F_total)
        self.buffer = []
        self.index = 0

        # control
        self.stop_event = threading.Event()
        self.saved_once = threading.Event()
        self.reader_thread = None

        # plot
        self.ax_total = ax_total
        (self.line_total,) = self.ax_total.plot([], [], label=f"{self.port} Total Force")
        self.ax_total.set_title(f"{self.port} — Total Force")
        self.ax_total.set_xlabel("Sample Index")
        self.ax_total.set_ylabel("Force (N)")
        self.ax_total.grid(True)
        self.ax_total.legend(loc="upper right")

    # ====== THREAD: read loop ======
    def start_reader(self):
        self.reader_thread = threading.Thread(target=self._read_loop, daemon=True)
        self.reader_thread.start()

    def _read_loop(self):
        pattern = re.compile(
            r'Time:(-?\d+),V1:(-?\d+(?:\.\d+)?),'
            r'V2:(-?\d+(?:\.\d+)?),V3:(-?\d+(?:\.\d+)?),V4:(-?\d+(?:\.\d+)?)'
        )
        while not self.stop_event.is_set():
            try:
                line = self.ser.readline().decode('utf-8', errors='ignore').strip()
                match = pattern.match(line)
                if not match:
                    continue

                _t_ms = int(match.group(1))
                v1, v2, v3, v4 = [float(match.group(i)) for i in range(2, 6)]

                avg_raw = (v1 + v2 + v3 + v4) / 4.0
                F_total = self.a * (avg_raw ** 2) + self.b * avg_raw + self.c
                F_total = float(np.round(F_total, 3))

                raw_sum = v1 + v2 + v3 + v4
                if raw_sum != 0:
                    weights = [v1/raw_sum, v2/raw_sum, v3/raw_sum, v4/raw_sum]
                else:
                    weights = [0.25, 0.25, 0.25, 0.25]

                F1 = float(np.round(F_total * weights[0], 3))
                F2 = float(np.round(F_total * weights[1], 3))
                F3 = float(np.round(F_total * weights[2], 3))
                F4 = float(np.round(F_total * weights[3], 3))

                with self.lock:
                    self.buffer.append((self.index, v1, v2, v3, v4, F1, F2, F3, F4, F_total))
                    self.index += 1
            except Exception as e:
                print(f"[{self.port}] Read error: {e}")
                continue

    # ====== DRAW: update total line ======
    def update_total(self):
        with self.lock:
            if len(self.buffer) < 10:
                return
            recent = self.buffer[-PLOT_HISTORY:]
            x = [r[0] for r in recent]
            y = [r[9] for r in recent]  # F_total
            self.line_total.set_data(x, y)
            self.ax_total.relim()
            self.ax_total.autoscale_view()

    # ====== GET: series of totals for aggregation ======
    def get_total_series(self):
        with self.lock:
            if not self.buffer:
                return []
            return [r[9] for r in self.buffer]  # F_total series

    # ====== FINALIZE: save CSV & close serial ======
    def finalize_and_save(self):
        if self.saved_once.is_set():
            return
        self.saved_once.set()

        self.stop_event.set()
        try:
            if self.reader_thread and self.reader_thread.is_alive():
                self.reader_thread.join(timeout=2)
        except Exception:
            pass

        with self.lock:
            rows = list(self.buffer)

        try:
            os.makedirs(SAVE_DIR, exist_ok=True)
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"{SAVE_DIR}/session_{ts}_{self.port_sanitized}.csv"
            with open(filename, "w", newline="") as f:
                w = csv.writer(f)
                w.writerow([
                    "v1_raw", "v2_raw", "v3_raw", "v4_raw",
                    "v1_force_N", "v2_force_N", "v3_force_N", "v4_force_N",
                    "total_force_N"
                ])
                for row in rows:
                    _, v1, v2, v3, v4, F1, F2, F3, F4, Ft = row
                    w.writerow([v1, v2, v3, v4, F1, F2, F3, F4, Ft])
            print(f"[{self.port}] Saved {len(rows)} rows to {filename}")
        except Exception as e:
            print(f"[{self.port}] Failed to save CSV: {e}")

        try:
            self.ser.close()
        except Exception:
            pass

# =========================
# Build figure layout (single window)
# =========================
DEVICES = []         # list[DeviceContext]
FIG = None
ANIM = None
BTN_STOP = None
BTN_AX = None
CENTER_AX = None
CENTER_LINE = None
_FINALIZED_ALL = threading.Event()

def setup_devices_and_figure():
    global FIG, DEVICES, BTN_STOP, BTN_AX, CENTER_AX, CENTER_LINE

    # Discover and open ports (cap to MAX_DEVICES)
    ports = list_serial_devices()
    opened_pairs = []
    for p in ports:
        if len(opened_pairs) >= MAX_DEVICES:
            break
        ser = try_open_serial(p)
        if ser:
            opened_pairs.append((p, ser))

    if not opened_pairs:
        print("No serial devices found/available.")
        sys.exit(1)

    n = len(opened_pairs)

    # Single figure with GridSpec 3x3: corners for device plots, big center for sum
    FIG = plt.figure(figsize=(14, 9))
    gs = GridSpec(3, 3, figure=FIG, width_ratios=[1, 1.4, 1], height_ratios=[1, 1.2, 1])

    # Center (sum) axes spans full middle column (rows 0..2, col 1)
    CENTER_AX = FIG.add_subplot(gs[:, 1])
    (CENTER_LINE,) = CENTER_AX.plot([], [], label="Sum of Total Forces")
    CENTER_AX.set_title("TOTAL FORCE — ALL DEVICES (SUM)")
    CENTER_AX.set_xlabel("Sample Index (aligned min length)")
    CENTER_AX.set_ylabel("Force (N)")
    CENTER_AX.grid(True)
    CENTER_AX.legend(loc="upper right")

    # Corner slots (top-left, top-right, bottom-left, bottom-right)
    corner_slots = [(0, 0), (0, 2), (2, 0), (2, 2)]

    for i, (port, ser) in enumerate(opened_pairs):
        r, c = corner_slots[i]
        ax_total = FIG.add_subplot(gs[r, c])
        ctx = DeviceContext(port, ser, ax_total)
        DEVICES.append(ctx)
        ctx.start_reader()
        print(f"[{port}] Reader started.")

    # Add “Stop All” button (keep a strong reference!)
    BTN_AX = FIG.add_axes([0.40, 0.02, 0.20, 0.06])  # left, bottom, width, height (figure coords)
    BTN_STOP = Button(BTN_AX, "Stop All")

    def _on_stop_all(_evt=None):
        try:
            BTN_STOP.label.set_text("Stopping…")
            FIG.canvas.draw_idle()
        except Exception:
            pass
        finalize_all_and_exit()

    BTN_STOP.on_clicked(_on_stop_all)

    # Esc and window close events trigger stop all
    FIG.canvas.mpl_connect('key_press_event', lambda e: finalize_all_and_exit() if e.key == 'escape' else None)
    FIG.canvas.mpl_connect('close_event', lambda _evt: finalize_all_and_exit())

# =========================
# Animation update (single timer updates all devices + center sum)
# =========================
def update_all(_frame):
    # Update per-device total plots
    for ctx in DEVICES:
        ctx.update_total()

    # Compute summed series across devices
    if not DEVICES:
        return ()
    # Get total series for each device
    series_list = [ctx.get_total_series() for ctx in DEVICES if ctx.get_total_series()]
    if not series_list:
        return ()
    min_len = min(len(s) for s in series_list)
    if min_len < 10:
        return ()
    # Align and sum sample-wise (0..min_len-1)
    summed = [float(np.sum([s[i] for s in series_list])) for i in range(min_len)]
    x = list(range(min_len))
    CENTER_LINE.set_data(x[-PLOT_HISTORY:], summed[-PLOT_HISTORY:])
    CENTER_AX.relim()
    CENTER_AX.autoscale_view()

    return ()

# =========================
# Finalize all & exit
# =========================
def finalize_all_and_exit():
    if _FINALIZED_ALL.is_set():
        return
    _FINALIZED_ALL.set()

    for ctx in DEVICES:
        try:
            ctx.finalize_and_save()
        except Exception as e:
            print(f"[{ctx.port}] finalize error: {e}")

    try:
        plt.close(FIG)
    except Exception:
        pass
    try:
        plt.close('all')
    except Exception:
        pass

# =========================
# Signals — graceful stop from outside
# =========================
def _handle_term(_signum, _frame):
    try:
        finalize_all_and_exit()
    finally:
        os._exit(0)

signal.signal(getattr(signal, "SIGTERM", signal.SIGINT), _handle_term)
if hasattr(signal, "SIGBREAK"):  # Windows CTRL_BREAK_EVENT
    signal.signal(signal.SIGBREAK, _handle_term)

# =========================
# Main
# =========================
if __name__ == "__main__":
    setup_devices_and_figure()
    ANIM = FuncAnimation(FIG, update_all, interval=50, blit=False)  # keep strong ref in ANIM
    plt.show()

    # Safety net
    finalize_all_and_exit()
    print("All data collection stopped.")