#!/usr/bin/env python3
"""Plot baseline-corrected illuminance vs brightness for each tested color."""
import argparse
import csv
from collections import defaultdict
from pathlib import Path

p=argparse.ArgumentParser();p.add_argument('csv_file',type=Path);p.add_argument('--output',type=Path);args=p.parse_args()
import matplotlib.pyplot as plt
series=defaultdict(list)
with args.csv_file.open(newline='') as f:
    for row in csv.DictReader(f):
        series[row['color_setting']].append((int(row['brightness_pct']),float(row['net_lux'])))
for color, values in series.items():
    values.sort()
    plt.plot([v[0] for v in values],[v[1] for v in values],marker='o',label=f'{color} ({row["color_unit"]})')
plt.xlabel('Brightness command (%)');plt.ylabel('Baseline-corrected lux at sensor')
plt.title('Light calibration sweep');plt.legend(title='Color setting');plt.grid(alpha=.2)
output=args.output or args.csv_file.with_suffix('.png')
plt.savefig(output,dpi=160,bbox_inches='tight');print(output)
