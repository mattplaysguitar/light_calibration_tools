#!/usr/bin/env python3

import argparse
import csv
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import urlopen

FIELDS = [
    "timestamp_utc", "elapsed_s", "lux",
    "f1_415nm", "f2_445nm", "f3_480nm", "f4_515nm",
    "f5_555nm", "f6_590nm", "f7_630nm", "f8_680nm",
    "clear", "nir", "seq", "acquisition_ms"
]

parser = argparse.ArgumentParser()
parser.add_argument("--url", default="http://10.0.1.84/read")
parser.add_argument("--minutes", type=float, default=5)
parser.add_argument("--interval", type=float, default=3)
parser.add_argument("--backlight", type=int, default=70)
parser.add_argument("--content", default="tv")
args = parser.parse_args()

folder = Path("tv_calibration")
folder.mkdir(exist_ok=True)

stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
label = "".join(
    c if c.isalnum() or c in "-_" else "_"
    for c in args.content.lower()
)

path = folder / f"{label}_backlight_{args.backlight}_{stamp}.csv"

start = time.monotonic()
next_sample = start
deadline = start + args.minutes * 60

count = 0
errors = 0
last_seq = None

print(f"Recording: {path}")
print(f"Sensor: {args.url}")
print(f"Content: {args.content}")
print(f"TV backlight: {args.backlight} (not changed)")
print("Press Ctrl+C to stop.\n")

try:
    with path.open("w", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=FIELDS)
        writer.writeheader()

        while time.monotonic() < deadline:
            delay = next_sample - time.monotonic()
            if delay > 0:
                time.sleep(delay)

            next_sample += args.interval

            try:
                with urlopen(args.url, timeout=10) as response:
                    data = json.load(response)

                if data.get("ok") is not True:
                    raise ValueError("Sensor returned ok=false")

                seq = data.get("seq")
                if seq is not None and seq == last_seq:
                    raise ValueError("Duplicate sensor sequence")
                last_seq = seq

                row = {
                    "timestamp_utc": datetime.now(
                        timezone.utc
                    ).isoformat(),
                    "elapsed_s": round(
                        time.monotonic() - start, 2
                    )
                }

                for field in FIELDS:
                    if field not in row:
                        row[field] = data.get(field, "")

                writer.writerow(row)
                file.flush()
                count += 1

                print(
                    f"{row['elapsed_s']:7.1f}s | "
                    f"lux {float(row['lux']):8.2f} | "
                    f"445nm {row['f2_445nm']} | "
                    f"630nm {row['f7_630nm']}",
                    flush=True
                )

            except Exception as exc:
                errors += 1
                print(f"Sensor error: {exc}", flush=True)

except KeyboardInterrupt:
    print("\nRecording stopped.")

print(f"\nSaved: {path}")
print(f"Samples: {count}; errors: {errors}")
