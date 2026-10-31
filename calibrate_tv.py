
#!/usr/bin/env python3
"""
DomicileOS - Vizio TV Light Calibration

Displays test patterns through AirPlay or HDMI.
Reads AS7341 and VEML7700 over ESP32 HTTP.
Saves lux and spectral measurements to CSV.

Keys:
    F       Toggle fullscreen
    S       Start automatic calibration
    SPACE   Start automatic calibration
    ESC     Exit fullscreen
    Q       Quit

Run:
    python calibrate_tv.py
    python calibrate_tv.py --position screen
    python calibrate_tv.py --position viewing
"""

import argparse
import csv
import json
import statistics
import threading
import tkinter as tk
from datetime import datetime
from pathlib import Path
from urllib.request import urlopen

DEFAULT_SENSOR = "http://10.0.1.84/read"
OUTPUT_DIR = Path("tv_calibration")

CHANNELS = [
    "f1_415nm", "f2_445nm", "f3_480nm",
    "f4_515nm", "f5_555nm", "f6_590nm",
    "f7_630nm", "f8_680nm", "clear", "nir"
]

# Colors are sRGB code values, not linear light.
PATTERNS = [
    ("black", "#000000"),
    ("white", "#ffffff"),
    ("gray_10", "#1a1a1a"),
    ("gray_20", "#333333"),
    ("gray_30", "#4c4c4c"),
    ("gray_40", "#666666"),
    ("gray_50", "#808080"),
    ("gray_60", "#999999"),
    ("gray_70", "#b3b3b3"),
    ("gray_80", "#cccccc"),
    ("gray_90", "#e6e6e6"),
    ("red", "#ff0000"),
    ("green", "#00ff00"),
    ("blue", "#0000ff"),
    ("cyan", "#00ffff"),
    ("magenta", "#ff00ff"),
    ("yellow", "#ffff00"),
    ("color_bars", None),
]

BAR_COLORS = [
    "#ffffff",
    "#ffff00",
    "#00ffff",
    "#00ff00",
    "#ff00ff",
    "#ff0000",
    "#0000ff",
]


def read_sensor(url, timeout):
    with urlopen(url, timeout=timeout) as response:
        data = json.load(response)

    if data.get("ok") is not True:
        raise RuntimeError(f"Sensor error: {data}")

    for key in ["lux", *CHANNELS]:
        if not isinstance(data.get(key), (int, float)):
            raise RuntimeError(f"Invalid sensor field: {key}")

    return data


def average_readings(readings):
    return {
        field: statistics.mean(r[field] for r in readings)
        for field in ["lux", *CHANNELS]
    }


class TVCalibration:
    def __init__(self, root, args):
        self.root = root
        self.args = args

        self.index = 0
        self.running = False
        self.fullscreen = False
        self.results = []

        OUTPUT_DIR.mkdir(exist_ok=True)

        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")

        self.csv_path = OUTPUT_DIR / (
            f"{stamp}_{args.position}.csv"
        )

        self.root.title("DomicileOS - TV Calibration")
        self.root.geometry("1280x720")
        self.root.configure(bg="black")

        self.canvas = tk.Canvas(
            root,
            bg="black",
            highlightthickness=0
        )
        self.canvas.pack(fill="both", expand=True)

        self.label = tk.Label(
            root,
            text=(
                "DOMICILE OS - TV CALIBRATION\n\n"
                "Move this window to the Vizio TV.\n"
                "Press F for fullscreen.\n"
                "Press S to begin measurement.\n"
                "Press Q to quit."
            ),
            fg="white",
            bg="#111111",
            font=("Helvetica", 20),
            justify="left",
            padx=24,
            pady=20
        )

        self.label.place(relx=0.5, rely=0.5, anchor="center")

        root.bind("f", self.toggle_fullscreen)
        root.bind("<Escape>", self.exit_fullscreen)
        root.bind("s", self.start)
        root.bind("<space>", self.start)
        root.bind("q", self.quit)

        root.protocol("WM_DELETE_WINDOW", self.quit)
        root.bind("<Configure>", self.on_resize)

    def toggle_fullscreen(self, event=None):
        self.fullscreen = not self.fullscreen
        self.root.attributes("-fullscreen", self.fullscreen)

    def exit_fullscreen(self, event=None):
        self.fullscreen = False
        self.root.attributes("-fullscreen", False)

    def on_resize(self, event=None):
        if self.running and self.index < len(PATTERNS):
            self.draw_pattern(*PATTERNS[self.index])

    def draw_pattern(self, name, color):
        self.label.place_forget()
        self.canvas.delete("all")

        width = max(self.canvas.winfo_width(), 1)
        height = max(self.canvas.winfo_height(), 1)

        if name == "color_bars":
            width_per_bar = width / len(BAR_COLORS)

            for i, bar_color in enumerate(BAR_COLORS):
                self.canvas.create_rectangle(
                    i * width_per_bar,
                    0,
                    (i + 1) * width_per_bar,
                    height,
                    fill=bar_color,
                    outline=""
                )
        else:
            self.canvas.create_rectangle(
                0, 0, width, height,
                fill=color,
                outline=""
            )

        print(
            f"[{self.index + 1}/{len(PATTERNS)}] "
            f"Displaying {name}",
            flush=True
        )

    def start(self, event=None):
        if self.running:
            return

        self.running = True
        self.index = 0
        self.results = []

        print("\n================================")
        print("DOMICILE OS - TV CALIBRATION")
        print("================================")
        print("Sensor:", self.args.sensor)
        print("Position:", self.args.position)
        print("Patterns:", len(PATTERNS))
        print("Output:", self.csv_path)

        print("\nBeginning automated measurements...")

        self.next_pattern()

    def next_pattern(self):
        if not self.running:
            return

        if self.index >= len(PATTERNS):
            self.finish()
            return

        name, color = PATTERNS[self.index]
        self.draw_pattern(name, color)

        # Allow AirPlay and the TV to settle.
        self.root.after(
            int(self.args.settle * 1000),
            lambda: self.capture_pattern(name, color)
        )

    def capture_pattern(self, name, color):
        def worker():
            try:
                readings = [
                    read_sensor(
                        self.args.sensor,
                        self.args.timeout
                    )
                    for _ in range(self.args.samples)
                ]

                result = average_readings(readings)
                result.update({
                    "timestamp": datetime.now().isoformat(),
                    "pattern": name,
                    "color_hex": color or "bars",
                    "position": self.args.position,
                    "samples": len(readings),
                })

                self.root.after(
                    0,
                    lambda: self.save_and_continue(result)
                )

            except Exception as exc:
                self.root.after(
                    0,
                    lambda error=str(exc): self.failed(error)
                )

        threading.Thread(
            target=worker,
            daemon=True
        ).start()

    def save_and_continue(self, result):
        self.results.append(result)

        fields = [
            "timestamp", "pattern", "color_hex",
            "position", "samples", "lux",
            *CHANNELS
        ]

        # Save each successful measurement immediately.
        # An interruption won't lose completed patterns.
        new_file = not self.csv_path.exists()

        with self.csv_path.open(
            "a", newline="", encoding="utf-8"
        ) as file:
            writer = csv.DictWriter(
                file, fieldnames=fields
            )

            if new_file:
                writer.writeheader()

            writer.writerow(result)
            file.flush()

        print(
            f"  lux={result['lux']:.2f} "
            f"blue445={result['f2_445nm']:.0f} "
            f"blue480={result['f3_480nm']:.0f}",
            flush=True
        )

        self.index += 1

        self.root.after(
            100,
            self.next_pattern
        )

    def failed(self, error):
        print("\nMEASUREMENT FAILED:", error)
        print("Completed measurements saved:", self.csv_path)
        self.running = False

        self.label.config(
            text=(
                "Measurement failed.\n"
                "See terminal for details.\n"
                "Press S to start a new run."
            )
        )
        self.label.place(
            relx=0.5, rely=0.5, anchor="center"
        )

    def finish(self):
        self.running = False

        print("\n================================")
        print("TV CALIBRATION COMPLETE")
        print("================================")
        print("Measurements:", len(self.results))
        print("CSV:", self.csv_path)

        summary = {
            "device": "Vizio TV",
            "sensor": self.args.sensor,
            "position": self.args.position,
            "settle_seconds": self.args.settle,
            "patterns": len(self.results),
            "completed_at": datetime.now().isoformat(),
            "measurements": self.results,
        }

        profile_path = self.csv_path.with_suffix(".json")

        profile_path.write_text(
            json.dumps(summary, indent=2),
            encoding="utf-8"
        )

        print("Profile:", profile_path)

        self.label.config(
            text=(
                "CALIBRATION COMPLETE\n\n"
                f"{len(self.results)} patterns measured.\n"
                "Results saved to tv_calibration/\n\n"
                "Press Q to quit."
            )
        )

        self.label.place(
            relx=0.5, rely=0.5, anchor="center"
        )

    def quit(self, event=None):
        self.running = False
        self.root.destroy()


def main():
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--sensor",
        default=DEFAULT_SENSOR
    )

    parser.add_argument(
        "--position",
        choices=["screen", "viewing"],
        default="viewing"
    )

    parser.add_argument(
        "--settle",
        type=float,
        default=3.0
    )

    parser.add_argument(
        "--samples",
        type=int,
        default=2
    )

    parser.add_argument(
        "--timeout",
        type=float,
        default=10
    )

    args = parser.parse_args()

    if args.settle < 0 or args.samples < 1 or args.timeout <= 0:
        parser.error("Invalid measurement settings")

    root = tk.Tk()
    TVCalibration(root, args)
    root.mainloop()


if __name__ == "__main__":
    main()

