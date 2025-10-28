import csv
import matplotlib.pyplot as plt

# Read CSV data manually (without pandas)
index = []
v1_raw, v2_raw, v3_raw, v4_raw = [], [], [], []
v1_force, v2_force, v3_force, v4_force = [], [], [], []
total_force = []

with open('Readings/session_20251028_102703.csv', 'r') as file:
    reader = csv.DictReader(file)
    for i, row in enumerate(reader):
        index.append(i)
        v1_raw.append(float(row['v1_raw']))
        v2_raw.append(float(row['v2_raw']))
        v3_raw.append(float(row['v3_raw']))
        v4_raw.append(float(row['v4_raw']))
        v1_force.append(float(row['v1_force_N']))
        v2_force.append(float(row['v2_force_N']))
        v3_force.append(float(row['v3_force_N']))
        v4_force.append(float(row['v4_force_N']))
        total_force.append(float(row['total_force_N']))

# Plot using matplotlib
plt.figure(figsize=(10, 6))
plt.plot(index, v1_force, label='v1')
plt.plot(index, v2_force, label='v2')
plt.plot(index, v3_force, label='v3')
plt.plot(index, v4_force, label='v4')
plt.plot(index, total_force, label='total_force_N', linewidth=2, linestyle='--')

plt.title('Forces over Index')
plt.xlabel('Index')
plt.ylabel('Value')
plt.legend()
plt.grid(True)
plt.tight_layout()

plt.show()