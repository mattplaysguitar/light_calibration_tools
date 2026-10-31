
#!/usr/bin/env python3
"""
DomicileOS - VOCOlinc Lamp Settings

Change brightness and color temperature
without issuing a turn_on command.

Usage:
    python set_vocolinc.py --list
    python set_vocolinc.py --brightness 30 --kelvin 2700
    python set_vocolinc.py --brightness 70 --kelvin 5000
    python set_vocolinc.py --brightness 15 --kelvin 3000 --all

NOTE:
The lamp firmware may not allow settings to be
changed while powered off. This script never
intentionally switches a lamp on.
"""

import argparse
import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

HERE = Path(__file__).resolve().parent

PROJECT = Path(
    os.getenv(
        "LIGHT_PROJECT",
        "../meross-project/meross-bulb-lab"
    )
)

sys.path.insert(0, str(PROJECT.resolve()))


def kelvin_to_mired(kelvin):
    return round(1_000_000 / kelvin)


def get_devices():
    from discovery import discover

    result = discover(PROJECT, 8)

    if isinstance(result, dict):
        result = list(result.values())

    return [
        d for d in result
        if "vocolinc" in str(d).lower()
        or "dl2201" in str(d).lower()
    ]


def get_service(device):
    if isinstance(device, str):
        return device

    for key in ("service", "name", "service_name"):
        if device.get(key):
            return device[key]

    raise ValueError(f"No service name: {device}")


def main():
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--brightness",
        type=int,
        default=30,
        help="Brightness 1-100 percent"
    )

    parser.add_argument(
        "--kelvin",
        type=int,
        default=2700,
        help="White color temperature in Kelvin"
    )

    parser.add_argument(
        "--service",
        help="Exact Bonjour service to modify"
    )

    parser.add_argument(
        "--all",
        action="store_true",
        help="Change all discovered VOCOlinc lamps"
    )

    parser.add_argument(
        "--list",
        action="store_true",
        help="List discovered lamps without changing them"
    )

    parser.add_argument(
        "--service-id",
        default="0"
    )

    args = parser.parse_args()

    if not 1 <= args.brightness <= 100:
        parser.error("Brightness must be 1-100")

    if not 2700 <= args.kelvin <= 6500:
        parser.error("Kelvin must be 2700-6500")

    mired = kelvin_to_mired(args.kelvin)

    print("\nDOMICILE OS - VOCOLINC")
    print("------------------------")

    devices = get_devices()

    if args.list:
        for d in devices:
            print(json.dumps(d, indent=2, default=str))
        return

    services = (
        [args.service]
        if args.service
        else [get_service(d) for d in devices]
    )

    if not services:
        raise SystemExit("No VOCOlinc lamps found")

    if len(services) > 1 and not args.all:
        raise SystemExit(
            "Multiple lamps detected. "
            "Specify --service NAME or --all."
        )

    from discovery import resolve_device
    from vocolinc_api import VocolincDevice

    for service in services:

        found = resolve_device(
            PROJECT,
            service,
            "vocolinc",
            8
        )

        address = found["address"]

        lamp = VocolincDevice.local_ip(
            address,
            service_id=args.service_id
        )

        before = lamp.get_state()
        state = before.get("state", {})

        was_on = bool(state.get("switch0", 0))

        print(f"\nLamp: {service}")
        print(f"Address: {address}")
        print(f"Originally on: {was_on}")

        # Write brightness and temperature
        # directly without calling turn_on().
        #
        # level0 = brightness
        # k0 = color temperature in mireds
        #
        # Explicitly preserve switch0 state.

        update = {
            "level0": args.brightness,
            "k0": mired,
            "switch0": 1 if was_on else 0
        }

        print("Sending:", update)

        try:
            lamp.local.put_state(update)
        except Exception as exc:
            print("Failed:", exc)
            continue

        after = lamp.get_state()
        new_state = after.get("state", {})

        is_on = bool(
            new_state.get("switch0", 0)
        )

        # Safety: restore OFF if the lamp
        # unexpectedly changes power state.
        if not was_on and is_on:
            print(
                "WARNING: Lamp switched on; "
                "turning it back off."
            )
            lamp.turn_off()

        print("Updated state:")
        print(json.dumps(after, indent=2, default=str))


if __name__ == "__main__":
    main()

