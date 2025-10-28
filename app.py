import csv
import subprocess
import sys
import os
import signal
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.figure import Figure

class ForceApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Force Readings")
        self.geometry("1200x300")  # start compact since plots are hidden
        self.minsize(700, 200)

        self.obs_proc = None  # subprocess handle for doubleObservation.py

        # ====== ROOT LAYOUT (no plot area at start) ======
        self.columnconfigure(0, weight=1)

        # Placeholder for top (plots) — created lazily
        self.top = None
        self.fig_left = self.ax_left = self.canvas_left = None
        self.fig_right = self.ax_right = self.canvas_right = None

        # Bottom bar with buttons (always visible)
        bottom = ttk.Frame(self)
        bottom.grid(row=1, column=0, sticky="ew", padx=10, pady=10)
        bottom.columnconfigure(0, weight=1)
        bottom.columnconfigure(1, weight=0)
        bottom.columnconfigure(2, weight=0)

        title_lbl = ttk.Label(bottom, text="Force Readings", font=("Segoe UI", 16, "bold"))
        title_lbl.grid(row=0, column=0, sticky="w")

        self.btn_record = ttk.Button(bottom, text="Start Recording", command=self.start_recording)
        self.btn_record.grid(row=0, column=1, padx=8)

        self.btn_plot = ttk.Button(bottom, text="Plot", command=self.plot_from_file)
        self.btn_plot.grid(row=0, column=2)

        # Status bar
        self.status = tk.StringVar(value="Ready.")
        statusbar = ttk.Label(self, textvariable=self.status, anchor="w")
        statusbar.grid(row=2, column=0, sticky="ew", padx=10, pady=(0,10))

        # Close handling (ensure child proc is stopped)
        self.protocol("WM_DELETE_WINDOW", self.on_app_close)

    # ====== LAZY PLOT AREA CREATION ======
    def ensure_plot_area(self):
        if self.top is not None:
            return  # already created/shown

        # Expand window now that plots will be shown
        try:
            self.geometry("1200x700")
        except Exception:
            pass

        self.top = ttk.Frame(self)
        self.top.grid(row=0, column=0, sticky="nsew", padx=10, pady=(10, 0))
        self.top.columnconfigure(0, weight=1)
        self.top.columnconfigure(1, weight=1)
        self.top.rowconfigure(0, weight=1)

        # Left plot: Raw Voltages
        self.fig_left = Figure(figsize=(5, 4), dpi=100)
        self.ax_left = self.fig_left.add_subplot(111)
        self.ax_left.set_title("Raw Voltages")
        self.ax_left.set_xlabel("Index")
        self.ax_left.set_ylabel("Voltage")

        self.canvas_left = FigureCanvasTkAgg(self.fig_left, master=self.top)
        self.canvas_left.get_tk_widget().grid(row=0, column=0, sticky="nsew", padx=(0,5))

        # Right plot: Forces
        self.fig_right = Figure(figsize=(5, 4), dpi=100)
        self.ax_right = self.fig_right.add_subplot(111)
        self.ax_right.set_title("Forces (N)")
        self.ax_right.set_xlabel("Index")
        self.ax_right.set_ylabel("Force (N)")

        self.canvas_right = FigureCanvasTkAgg(self.fig_right, master=self.top)
        self.canvas_right.get_tk_widget().grid(row=0, column=1, sticky="nsew", padx=(5,0))

    # ====== BUTTON HANDLERS ======
    def start_recording(self):
        if self.obs_proc is not None and self.obs_proc.poll() is None:
            messagebox.showwarning("Already running", "doubleObservation.py is already recording.")
            return

        # Hide Plot button and swap Start->Stop
        self.btn_plot.grid_remove()
        self.btn_record.config(text="Stop Recording", command=self.stop_recording)

        # Launch doubleObservation.py as a subprocess
        try:
            python_exe = sys.executable or "python"
            creationflags = 0
            preexec_fn = None
            if os.name == "nt":
                creationflags = 0x00000200  # CREATE_NEW_PROCESS_GROUP
            else:
                preexec_fn = os.setsid

            self.obs_proc = subprocess.Popen(
                [python_exe, "doubleObservation.py"],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                creationflags=creationflags,
                preexec_fn=preexec_fn
            )
            self.status.set("Recording… (doubleObservation.py running)")
            self.after(200, self._drain_proc_output)
        except FileNotFoundError:
            messagebox.showerror("Not found", "Could not find doubleObservation.py in the current directory.")
            self.restore_buttons()
        except Exception as e:
            messagebox.showerror("Launch error", f"Failed to start doubleObservation.py:\n{e}")
            self.restore_buttons()

    def stop_recording(self):
        if self.obs_proc is None or self.obs_proc.poll() is not None:
            self.status.set("Not recording.")
            self.restore_buttons()
            return

        self.status.set("Stopping recording…")
        try:
            if os.name == "nt":
                self.obs_proc.send_signal(signal.CTRL_BREAK_EVENT)
            else:
                os.killpg(os.getpgid(self.obs_proc.pid), signal.SIGTERM)
        except Exception:
            try:
                self.obs_proc.terminate()
            except Exception:
                pass

        self.after(1500, self._finalize_stop)

    def _finalize_stop(self):
        if self.obs_proc is not None and self.obs_proc.poll() is None:
            try:
                if os.name == "nt":
                    self.obs_proc.kill()
                else:
                    os.killpg(os.getpgid(self.obs_proc.pid), signal.SIGKILL)
            except Exception:
                pass

        self.status.set("Recording stopped.")
        self.restore_buttons()
        self.obs_proc = None

    def restore_buttons(self):
        try:
            self.btn_plot.grid()
        except Exception:
            pass
        self.btn_record.config(text="Start Recording", command=self.start_recording)

    # ====== PROCESS OUTPUT ======
    def _drain_proc_output(self):
        if self.obs_proc is None:
            return
        try:
            if self.obs_proc.stdout:
                for _ in range(10):
                    line = self.obs_proc.stdout.readline()
                    if not line:
                        break
                    line = line.strip()
                    if line:
                        self.status.set((line[:120] + "…") if len(line) > 120 else line)
        except Exception:
            pass

        if self.obs_proc.poll() is None:
            self.after(200, self._drain_proc_output)
        else:
            self.status.set("doubleObservation.py exited.")
            self.restore_buttons()
            self.obs_proc = None

   
    # ====== FILE PLOTTING (CSV) ======
    def plot_from_file(self):
        base_dir = os.getcwd() + "/Readings" # restrict to current folder

        csv_path = filedialog.askopenfilename(
            title="Select CSV with force readings",
            initialdir=base_dir,
            filetypes=[("CSV files", "*.csv"), ("All files", "*.*")]
        )
        if not csv_path:
            return

        # Ensure selected file is within base_dir
        if not os.path.abspath(csv_path).startswith(os.path.abspath(base_dir) + os.sep):
            messagebox.showerror("Path Error", "Please select a file from the current folder.")
            return

        try:
            data = self._read_csv(csv_path)
        except Exception as e:
            messagebox.showerror("Read Error", f"Failed to read CSV:\n{e}")
            return

        # Create/show plot area only now
        self.ensure_plot_area()

        try:
            self._draw_plots(data)
            self.status.set(f"Plotted: {csv_path}")
        except Exception as e:
            messagebox.showerror("Plot Error", f"Failed to plot data:\n{e}")

    def _read_csv(self, path):
        index = []
        v1_raw, v2_raw, v3_raw, v4_raw = [], [], [], []
        v1_force, v2_force, v3_force, v4_force = [], [], [], []
        total_force = []

        with open(path, "r", newline="") as f:
            reader = csv.DictReader(f)
            required = [
                "v1_raw","v2_raw","v3_raw","v4_raw",
                "v1_force_N","v2_force_N","v3_force_N","v4_force_N",
                "total_force_N"
            ]
            missing = [c for c in required if c not in (reader.fieldnames or [])]
            if missing:
                raise ValueError(f"Missing columns: {', '.join(missing)}")

            for i, row in enumerate(reader):
                index.append(i)
                v1_raw.append(float(row["v1_raw"]))
                v2_raw.append(float(row["v2_raw"]))
                v3_raw.append(float(row["v3_raw"]))
                v4_raw.append(float(row["v4_raw"]))
                v1_force.append(float(row["v1_force_N"]))
                v2_force.append(float(row["v2_force_N"]))
                v3_force.append(float(row["v3_force_N"]))
                v4_force.append(float(row["v4_force_N"]))
                total_force.append(float(row["total_force_N"]))

        return {
            "index": index,
            "v_raw": [v1_raw, v2_raw, v3_raw, v4_raw],
            "v_force": [v1_force, v2_force, v3_force, v4_force],
            "total": total_force
        }

    def _draw_plots(self, data):
        idx = data["index"]

        # Left plot (raw voltages)
        self.ax_left.clear()
        self.ax_left.set_title("Raw Voltages")
        self.ax_left.set_xlabel("Index")
        self.ax_left.set_ylabel("Voltage")
        labels_raw = ["v1_raw", "v2_raw", "v3_raw", "v4_raw"]
        for series, label in zip(data["v_raw"], labels_raw):
            self.ax_left.plot(idx, series, label=label)
        self.ax_left.grid(True)
        self.ax_left.legend(loc="upper right")
        self.canvas_left.draw()

        # Right plot (forces)
        self.ax_right.clear()
        self.ax_right.set_title("Forces (N)")
        self.ax_right.set_xlabel("Index")
        self.ax_right.set_ylabel("Force (N)")
        labels_force = ["v1_force_N", "v2_force_N", "v3_force_N", "v4_force_N"]
        for series, label in zip(data["v_force"], labels_force):
            self.ax_right.plot(idx, series, label=label)
        self.ax_right.plot(idx, data["total"], label="total_force_N", linewidth=2, linestyle="--")
        self.ax_right.grid(True)
        self.ax_right.legend(loc="upper right")
        self.canvas_right.draw()

    def on_app_close(self):
        try:
            if self.obs_proc is not None and self.obs_proc.poll() is None:
                self.stop_recording()
                self.after(600, self.destroy)
                return
        except Exception:
            pass
        self.destroy()

if __name__ == "__main__":
    app = ForceApp()
    app.mainloop()