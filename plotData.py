import pandas as pd
import matplotlib.pyplot as plt

def plot_voltage_data(file_path):
    """
    Reads a CSV file with Index, V1, V2, V3, and V4 columns,
    and plots all four voltage values over the Index.
    """
    # Load the CSV file
    df = pd.read_csv(file_path)

    # Check if required columns exist
    required_columns = {"Index", "V1", "V2", "V3", "V4"}
    if not required_columns.issubset(df.columns):
        raise ValueError(f"CSV file must contain columns: {required_columns}")

    # Plot the voltage data
    plt.figure(figsize=(12, 6))
    plt.plot(df["Index"], df["V1"], label="V1", alpha=0.7)
    plt.plot(df["Index"], df["V2"], label="V2", alpha=0.7)
    plt.plot(df["Index"], df["V3"], label="V3", alpha=0.7)
    plt.plot(df["Index"], df["V4"], label="V4", alpha=0.7)

    # Formatting the plot
    plt.xlabel("Index")
    plt.ylabel("Voltage Values")
    plt.title("Voltage Readings Over Time")
    plt.legend()
    plt.grid(True)
    plt.show()

# Example usage:
file_path = "data_converted.csv"  # Change this to the actual file path
plot_voltage_data(file_path)