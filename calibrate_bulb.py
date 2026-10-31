
#!/usr/bin/env python3
"""
DomicileOS - Automatic Single Bulb Calibration

Discovers one Meross or VOCOlinc bulb.
Uses calibrate.py for local bulb control.
Reads Sensus over HTTP (no MQTT).
Resumes interrupted sweeps.
Saves individual bulb profiles.

Requires:
    pip install zeroconf python-dotenv
"""

import argparse
import csv
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from zeroconf import (
    Zeroconf,
    ServiceBrowser,
    ServiceListener,
)


# ============================================
# CONFIGURATION
# ============================================

HERE = Path(__file__).resolve().parent
CALIBRATE = HERE / "calibrate.py"
PROFILE_DIR = HERE / "profiles"

# Set SENSUS_URL in .env:
# SENSUS_URL=http://YOUR_ESP32_IP/read


# ============================================
# BULB DISCOVERY
# ============================================

class Listener(ServiceListener):

    def __init__(self):
        self.devices = {}

    def add_service(self, zc, kind, name):
        self.update_service(zc, kind, name)

    def update_service(self, zc, kind, name):

        info = zc.get_service_info(
            kind,
            name,
            timeout=2000,
        )

        if not info:
            return

        props = {
            str(
                k.decode(errors="replace")
                if isinstance(k, bytes)
                else k
            ): str(
                v.decode(errors="replace")
                if isinstance(v, bytes)
                else v
            )
            for k, v in info.properties.items()
        }

        service = name.removesuffix(
            "._hap._tcp.local."
        )

        identity = (
            service
            + " "
            + str(info.server)
            + " "
            + str(props)
        ).lower()

        if "msl120" in identity:

            kind_name = "meross"
            model = "MSL120"

            colors = list(
                range(1, 101, 5)
            )

        elif "dl2201" in identity:

            kind_name = "vocolinc"
            model = "DL2201"

            colors = list(
                range(200, 501, 10)
            )

        else:
            return

        self.devices[name] = {
            "device": kind_name,
            "model": model,
            "service": service,
            "addresses": info.parsed_addresses(),
            "properties": props,
            "colors": colors,
        }

    def remove_service(self, zc, kind, name):
        self.devices.pop(name, None)


def discover(seconds):

    listener = Listener()
    zc = Zeroconf()

    browser = ServiceBrowser(
        zc,
        "_hap._tcp.local.",
        listener,
    )

    try:

        time.sleep(seconds)

        devices = list(
            listener.devices.values()
        )

    finally:

        browser.cancel()
        zc.close()

    if len(devices) != 1:

        names = ", ".join(
            d["service"] for d in devices
        ) or "none"

        raise RuntimeError(
            f"Expected ONE supported bulb, "
            f"found {len(devices)}: {names}"
        )

    return devices[0]


def values_text(seq):
    return ",".join(str(v) for v in seq)


# ============================================
# MAIN
# ============================================

def main():

    parser = argparse.ArgumentParser(
        description=(
            "Automatically discover and calibrate "
            "one connected bulb"
        )
    )

    parser.add_argument(
        "--sensor-url",
        default=None,
    )

    parser.add_argument(
        "--project",
        type=Path,
        help="Directory with existing bulb adapters",
    )

    parser.add_argument(
        "--discovery-seconds",
        type=float,
        default=8,
    )

    parser.add_argument(
        "--settle",
        type=float,
        default=0.5,
    )

    parser.add_argument(
        "--samples",
        type=int,
        default=2,
    )

    parser.add_argument(
        "--timeout",
        type=float,
        default=10,
    )

    parser.add_argument(
        "--sensor-retries",
        type=int,
        default=2,
    )

    parser.add_argument(
        "--dry-run",
        action="store_true",
    )

    parser.add_argument(
        "--yes",
        action="store_true",
        help="Skip confirmation",
    )

    args = parser.parse_args()

    # Load local .env settings.
    try:
        from dotenv import load_dotenv
        load_dotenv(HERE / ".env")
    except ImportError:
        pass

    sensor_url = (
        args.sensor_url
        or os.getenv("SENSUS_URL")
    )

    if not sensor_url:
        raise SystemExit(
            "Set SENSUS_URL in .env:\n"
            "SENSUS_URL=http://YOUR_ESP32_IP/read"
        )

    if (
        args.samples < 1
        or args.settle < 0
        or args.timeout <= 0
        or args.sensor_retries < 0
    ):
        parser.error("Invalid timing options")

    if not CALIBRATE.is_file():
        raise SystemExit(
            f"Missing calibration engine: {CALIBRATE}"
        )

    print()
    print("===================================")
    print(" DOMICILE OS")
    print(" AUTOMATIC BULB CALIBRATION")
    print("===================================")

    print("\nSearching network for bulbs...")

    bulb = discover(
        args.discovery_seconds
    )

    print("\nBulb identified:")
    print(" Manufacturer:", bulb["device"])
    print(" Model:       ", bulb["model"])
    print(" Service:     ", bulb["service"])
    print(
        " Address:     ",
        ", ".join(bulb["addresses"])
    )

    print("\nSensus HTTP sensor:")
    print(sensor_url)

    device_id = re.sub(
        r"[^a-z0-9]+",
        "-",
        bulb["service"].lower(),
    ).strip("-")

    folder = PROFILE_DIR / device_id

    folder.mkdir(
        parents=True,
        exist_ok=True,
    )

    brightness = list(
        range(5, 101, 5)
    )

    colors = bulb["colors"]

    total = (
        len(brightness)
        * len(colors)
    )

    print("\nCalibration configuration")
    print("-------------------------")
    print("Device:", device_id)
    print("Brightness levels:", len(brightness))
    print("Color levels:", len(colors))
    print("Total measurements:", total)
    print("Settling delay:", args.settle)
    print("Sensor readings per step:", args.samples)

    # ========================================
    # AUTOMATIC RESUME
    # ========================================

    expected = {
        (b, c)
        for c in colors
        for b in brightness
    }

    incomplete = []

    for file in folder.glob("*_sweep.csv"):

        try:

            with file.open(
                newline="",
                encoding="utf-8",
            ) as f:

                rows = list(
                    csv.DictReader(f)
                )

            if not rows:
                continue

            # Only resume measurements belonging
            # to this exact bulb and calibration.
            if any(
                r.get("device") != bulb["device"]
                or r.get("host") != bulb["service"]
                or r.get("room") != "calibration_closet"
                or r.get("position") != "fixed_sensor"
                for r in rows
            ):
                continue

            points = {
                (
                    int(r["brightness_pct"]),
                    int(r["color_setting"]),
                )
                for r in rows
            }

            if (
                len(points) == len(rows)
                and points.issubset(expected)
                and len(points) < total
            ):

                incomplete.append(
                    (
                        file.stat().st_mtime,
                        file,
                        len(points),
                    )
                )

        except (
            ValueError,
            KeyError,
            OSError,
        ):
            continue

    if incomplete:

        _, csv_file, done = max(
            incomplete,
            key=lambda item: item[0],
        )

        print(
            f"\nResuming existing calibration: "
            f"{done}/{total} measurements"
        )

        output_option = [
            "--resume",
            str(csv_file),
        ]

    else:

        stamp = datetime.now().strftime(
            "%Y%m%d_%H%M%S"
        )

        csv_file = folder / (
            f"{stamp}_sweep.csv"
        )

        output_option = [
            "--output",
            str(csv_file),
        ]

        print(
            f"\nStarting new calibration: "
            f"{total} measurements"
        )

    # ========================================
    # LAUNCH CALIBRATE.PY
    # ========================================

    command = [
        sys.executable,
        str(CALIBRATE),

        "--device",
        bulb["device"],

        "--service",
        bulb["service"],

        "--sensor-url",
        sensor_url,

        "--brightness",
        values_text(brightness),

        "--colors",
        values_text(colors),

        "--room",
        "calibration_closet",

        "--position",
        "fixed_sensor",

        "--settle",
        str(args.settle),

        "--samples",
        str(args.samples),

        "--timeout",
        str(args.timeout),

        "--sensor-retries",
        str(args.sensor_retries),

        # Skip second SWEEP confirmation.
        "--yes",

        *output_option,
    ]

    if args.project:
        command.extend([
            "--project",
            str(args.project),
        ])

    if args.dry_run:

        import shlex

        print("\nCommand:")
        print(shlex.join(command))

        return

    print("\nConfirm setup:")
    print(" - One supported bulb connected")
    print(" - Bulb inside dark closet")
    print(" - Sensus sensor positioned")
    print(" - ESP32 connected to Wi-Fi")

    if not args.yes:

        answer = input(
            "\nBegin calibration? [y/N]: "
        )

        if answer.strip().lower() not in (
            "y",
            "yes",
        ):

            print("Cancelled")
            return

    print("\nStarting calibration...\n")

    result = subprocess.run(
        command,
        cwd=HERE,
        check=False,
    )

    if result.returncode != 0:

        raise SystemExit(
            f"Calibration failed with exit code "
            f"{result.returncode}. "
            "Existing CSV retained for resume."
        )

    # ========================================
    # VERIFY MEASUREMENTS
    # ========================================

    with csv_file.open(
        newline="",
        encoding="utf-8",
    ) as f:

        rows = list(
            csv.DictReader(f)
        )

    points = {
        (
            int(r["brightness_pct"]),
            int(r["color_setting"]),
        )
        for r in rows
    }

    if (
        len(points) != total
        or not points.issubset(expected)
    ):

        raise RuntimeError(
            f"Incomplete measurement data: "
            f"{len(points)}/{total}. "
            "Profile not overwritten."
        )

    # ========================================
    # SAVE DEVICE PROFILE
    # ========================================

    profile = {

        "schema_version": 1,

        "device_id": device_id,

        "manufacturer": bulb["device"],

        "model": bulb["model"],

        "service": bulb["service"],

        "addresses_at_discovery":
            bulb["addresses"],

        "calibrated_at":
            datetime.now(
                timezone.utc
            ).isoformat(),

        "sensor_url": sensor_url,

        "sensor":
            "Sensus AS7341 + VEML7700 (HTTP)",

        "environment": {
            "room": "calibration_closet",
            "position": "fixed_sensor",
        },

        "color_unit": (
            "percent_native"
            if bulb["device"] == "meross"
            else "mired"
        ),

        "brightness_values": brightness,

        "color_values": colors,

        "measurements": total,

        "csv": str(
            csv_file.resolve()
        ),

        "note": (
            "Measured illuminance at the sensor "
            "position, not absolute bulb lumens."
        ),
    }

    profile_path = (
        folder / "profile.json"
    )

    temporary = (
        folder / "profile.json.tmp"
    )

    temporary.write_text(
        json.dumps(
            profile,
            indent=2,
        ),
        encoding="utf-8",
    )

    temporary.replace(
        profile_path
    )

    print()
    print("===================================")
    print(" CALIBRATION COMPLETE")
    print("===================================")

    print("Bulb:", bulb["service"])
    print("Measurements:", total)
    print("Profile:", profile_path)
    print("CSV:", csv_file)


if __name__ == "__main__":

    try:
        main()

    except KeyboardInterrupt:
        raise SystemExit(
            "Interrupted. Re-run to resume "
            "the partial calibration."
        )

    except RuntimeError as exc:
        raise SystemExit(
            f"ERROR: {exc}"
        )
