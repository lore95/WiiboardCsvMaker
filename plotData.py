import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
from scipy.signal import savgol_filter, butter, filtfilt
from scipy.stats import zscore

def hampel_filter(series, window_size=5, n_sigmas=3):
    """
    Hampel filter: replaces outliers in a sliding window with the window median.
    """
    new_series = series.copy()
    k = 1.4826  # scale factor for Gaussian
    L = len(series)
    for i in range(window_size, L - window_size):
        window = series[i - window_size : i + window_size + 1]
        med = window.median()
        mad = k * np.median(np.abs(window - med))
        if abs(series.iat[i] - med) > n_sigmas * mad:
            new_series.iat[i] = med
    return new_series

def plot_voltage_data(file_path):
    df = pd.read_csv(file_path)
    required = {"Index", "V1", "V2", "V3", "V4"}
    if not required.issubset(df.columns):
        raise ValueError(f"CSV must contain columns: {required}")
    cols = ["V1", "V2", "V3", "V4"]

    # 1) Remove negatives
    df_f = df.copy()
    for c in cols:
        df_f[c] = df_f[c].where(df_f[c] >= 0, np.nan)

    # 2) Hampel filter
    for c in cols:
        df_f[c] = hampel_filter(df_f[c], window_size=5, n_sigmas=3)

    # 3) Savitzky–Golay smoothing (must fill NaNs first):
    for c in cols:
        # interpolate nearest neighbor, then back/forward-fill edges
        filled = df_f[c].interpolate(method="nearest").bfill().ffill()
        df_f[c] = savgol_filter(filled, window_length=7, polyorder=2, mode="mirror")

    # 4) Exponential moving average
    alpha = 0.2
    for c in cols:
        df_f[c] = pd.Series(df_f[c]).ewm(alpha=alpha).mean().values

    # 5) Butterworth low-pass filter
    b, a = butter(N=2, Wn=0.1, btype="low")
    for c in cols:
        df_f[c] = filtfilt(b, a, df_f[c])

    # 6) Z-score clipping + linear interpolation
    zs = df_f[cols].apply(zscore)
    mask = zs.abs() > 3
    df_f[cols] = df_f[cols].mask(mask)
    df_f[cols] = df_f[cols].interpolate().bfill().ffill()

    # Plot
    plt.figure(figsize=(12, 6))
    for c in cols:
        plt.plot(df["Index"], df_f[c], label=c, alpha=0.8)
    plt.xlabel("Index")
    plt.ylabel("Filtered Voltage")
    plt.title("Voltage Readings with Multiple Spike-Reducing Filters")
    plt.legend()
    plt.grid(True)
    plt.tight_layout()
    plt.show()

if __name__ == "__main__":
    plot_voltage_data("data_converted.csv")