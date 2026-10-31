#!/usr/bin/env python3
"""DomicileOS bulb sweep: existing local bulb adapters + ESP32 HTTP sensor."""
import argparse
import csv
import json
import os
import statistics
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import urlopen

from dotenv import load_dotenv
load_dotenv()

CHANNELS = ["f1_415nm", "f2_445nm", "f3_480nm", "f4_515nm", "f5_555nm",
            "f6_590nm", "f7_630nm", "f8_680nm", "clear", "nir"]
FIELDS = ["timestamp_utc", "device", "host", "room", "position", "step",
          "brightness_pct", "color_setting", "color_unit", "lux", "baseline_lux",
          "net_lux", "samples", *CHANNELS, "baseline_spectrum_json", "spectrum_json",
          "reported_state_json"]


def sensor_read(url, timeout):
    try:
        with urlopen(url, timeout=timeout) as response:
            data = json.load(response)
    except Exception as exc:
        raise TimeoutError(f"ESP32 HTTP sensor unavailable at {url}: {exc}") from exc
    if not isinstance(data, dict) or data.get("ok") is not True:
        raise RuntimeError(f"ESP32 sensor error: {data}")
    if not isinstance(data.get("lux"), (int, float)):
        raise RuntimeError("ESP32 reading does not include numeric lux")
    if any(not isinstance(data.get(c), (int, float)) for c in CHANNELS):
        raise RuntimeError("ESP32 reading is missing spectral channels")
    if any(data[c] >= 65535 for c in CHANNELS):
        print("WARNING: AS7341 channel saturated; spectral measurements may be inaccurate", flush=True)
    return data


def capture(url, timeout, count):
    readings = [sensor_read(url, timeout) for _ in range(count)]
    seqs = [r.get("seq") for r in readings]
    if all(s is not None for s in seqs) and len(set(seqs)) != len(seqs):
        raise RuntimeError("ESP32 returned duplicate sequence numbers")
    return {"lux": statistics.median(r["lux"] for r in readings),
            "spectrum": {c: statistics.median(r[c] for r in readings) for c in CHANNELS},
            "samples": len(readings)}


class Light:
    def __init__(self, kind, host, project, service_id):
        sys.path.insert(0, str(project.resolve()))
        self.kind = kind
        if kind == "meross":
            from meross import MerossDevice
            self.device = MerossDevice.local_ip(host, key=os.getenv("MEROSS_KEY"))
        else:
            from vocolinc_api import VocolincDevice
            self.device = VocolincDevice.local_ip(host, service_id=service_id)

    def state(self):
        return self.device.get_state()

    def off(self):
        return self.device.turn_off()

    def set(self, brightness, color):
        if self.kind == "meross":
            result = self.device.set_color_temperature(color, brightness=brightness)
            self.device.turn_on()
            return result
        self.device.set_color_temperature(color)
        return self.device.set_brightness(brightness)

    def restore(self, original):
        if self.kind == "meross":
            old = original.get("light") or {}
            if isinstance(old, dict):
                allowed = {k: old[k] for k in ("channel", "capacity", "temperature", "luminance", "rgb", "transform") if k in old}
                if allowed:
                    self.device.local.set_light(allowed)
            toggle = original.get("togglex")
            if isinstance(toggle, list) and toggle:
                self.device.set_on(bool(toggle[0].get("onoff", 1)))
            elif isinstance(toggle, dict):
                self.device.set_on(bool(toggle.get("onoff", 1)))
        else:
            old = original.get("state") or {}
            controls = {k: old[k] for k in ("level0", "k0") if k in old}
            if controls:
                self.device.local.put_state(controls)
            if "switch0" in old:
                self.device.set_on(bool(old["switch0"]))


def numbers(value, low, high):
    try:
        items = [int(s.strip()) for s in value.split(",") if s.strip()]
    except ValueError as exc:
        raise SystemExit(f"Invalid numeric list: {value}") from exc
    if not items or any(v < low or v > high for v in items) or len(set(items)) != len(items):
        raise SystemExit(f"Expected unique comma-separated integers in {low}..{high}")
    return items


def options():
    p = argparse.ArgumentParser(description="Meross/VOCOlinc + Sensus ESP32 HTTP calibration")
    p.add_argument("--device", choices=["meross", "vocolinc"])
    p.add_argument("--service")
    p.add_argument("--list-lights", action="store_true")
    p.add_argument("--discovery-seconds", type=float, default=8)
    p.add_argument("--project", type=Path, default=Path(os.getenv("LIGHT_PROJECT", "../meross-project/meross-bulb-lab")))
    p.add_argument("--service-id", default="0")
    p.add_argument("--sensor-url", default=os.getenv("SENSUS_URL"))
    p.add_argument("--sensor-check", action="store_true")
    p.add_argument("--room", default="calibration_closet")
    p.add_argument("--position", default="fixed_sensor")
    p.add_argument("--brightness", default="5,10,15,20,25,30,35,40,45,50,55,60,65,70,75,80,85,90,95,100")
    p.add_argument("--colors")
    p.add_argument("--settle", type=float, default=0.5)
    p.add_argument("--samples", type=int, default=2)
    p.add_argument("--timeout", type=float, default=5)
    p.add_argument("--sensor-retries", type=int, default=2)
    p.add_argument("--output", type=Path, default=Path("results"))
    p.add_argument("--resume", type=Path)
    p.add_argument("--no-baseline", action="store_true")
    p.add_argument("--keep-off", action="store_true")
    p.add_argument("--status", action="store_true")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--yes", action="store_true")
    # Accepted for compatibility with older calibrate_bulb.py versions.
    p.add_argument("--capture", type=float, help="Ignored: HTTP reads are on demand")
    args = p.parse_args()
    if args.settle < 0 or args.samples < 1 or args.timeout <= 0 or args.sensor_retries < 0:
        p.error("Invalid timing or sensor sample settings")
    return args


def main():
    args = options()
    if args.list_lights:
        from discovery import discover
        print(json.dumps(discover(args.project, args.discovery_seconds), indent=2))
        return
    if not args.sensor_url or not args.sensor_url.startswith("http://"):
        raise SystemExit("Set SENSUS_URL=http://ESP32_IP/read in .env, or pass --sensor-url")
    if args.sensor_check:
        print(json.dumps(capture(args.sensor_url, args.timeout, args.samples), indent=2))
        return
    if not args.device or not args.service:
        raise SystemExit("Supply --device and --service (or run calibrate_bulb.py)")
    if not args.project.exists():
        raise SystemExit(f"Light adapter folder missing: {args.project}")

    from discovery import resolve_device
    found = resolve_device(args.project, args.service, args.device, args.discovery_seconds)
    print(f"Resolved {args.service} -> {found['address']}", flush=True)
    br = numbers(args.brightness, 1, 100)
    default_colors = "1,25,50,75,100" if args.device == "meross" else "500,370,250,200"
    colors = numbers(args.colors or default_colors, 1, 100 if args.device == "meross" else 1000)
    plan = [(b, c) for c in colors for b in br]
    finished = set()
    baseline = None

    if args.resume:
        outfile = args.resume
        if not outfile.is_file():
            raise SystemExit(f"Resume CSV not found: {outfile}")
        with outfile.open(newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            if reader.fieldnames != FIELDS:
                raise SystemExit("Resume CSV columns do not match")
            old = list(reader)
        if not old:
            raise SystemExit("Resume CSV has no measurements")
        valid = set(plan)
        for row in old:
            for field, val in (("device", args.device), ("host", args.service),
                               ("room", args.room), ("position", args.position)):
                if row[field] != val:
                    raise SystemExit(f"Resume CSV mismatch: {field}")
            point = (int(row["brightness_pct"]), int(row["color_setting"]))
            if point not in valid or point in finished:
                raise SystemExit(f"Invalid or duplicate resume point {point}")
            finished.add(point)
        baseline = {"lux": float(old[0]["baseline_lux"]),
                    "spectrum": json.loads(old[0]["baseline_spectrum_json"] or "{}")}
        print(f"Resuming {outfile} ({len(finished)}/{len(plan)} done)", flush=True)
    elif args.output.suffix.lower() == ".csv":
        outfile = args.output
        if outfile.exists():
            raise SystemExit(f"Output already exists: {outfile}. Use --resume instead.")
    else:
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        outfile = args.output / f"{stamp}_{args.device}_{args.service}_sweep.csv"
    if args.dry_run:
        print(json.dumps({"sensor_url": args.sensor_url, "device": args.device,
                          "service": args.service, "steps": len(plan),
                          "remaining": len(plan)-len(finished), "output": str(outfile)}, indent=2))
        return

    # Verify sensor before touching the bulb or opening an output CSV.
    def read_retry(label):
        for attempt in range(args.sensor_retries + 1):
            try:
                return capture(args.sensor_url, args.timeout, args.samples)
            except (TimeoutError, RuntimeError) as exc:
                print(f"Sensor {label} attempt {attempt+1}/{args.sensor_retries+1}: {exc}", flush=True)
                if attempt == args.sensor_retries:
                    raise
                time.sleep(0.25)

    print("Checking ESP32 sensor...", flush=True)
    read_retry("preflight")
    light = Light(args.device, found["address"], args.project, args.service_id)
    original = light.state()
    print("Original bulb state:", json.dumps(original, default=str)[:500])
    if args.status:
        return
    print(f"Ready: {len(plan)-len(finished)} remaining of {len(plan)} settings.")
    if not args.yes and input("Type SWEEP to proceed: ").strip().upper() != "SWEEP":
        return
    outfile.parent.mkdir(parents=True, exist_ok=True)
    logpath = outfile.with_name(outfile.stem + "_events.jsonl")

    def event(kind, **data):
        with logpath.open("a", encoding="utf-8") as f:
            f.write(json.dumps({"utc": datetime.now(timezone.utc).isoformat(), "event": kind, **data}, default=str) + "\n")

    altered = False
    count = len(finished)
    try:
        with outfile.open("a" if args.resume else "w", newline="", encoding="utf-8") as fp:
            writer = csv.DictWriter(fp, fieldnames=FIELDS)
            if not args.resume:
                writer.writeheader()
                fp.flush()
            if baseline is None and not args.no_baseline:
                print("Measuring bulb-OFF baseline...", flush=True)
                altered = True
                light.off()
                time.sleep(max(args.settle, 0.25))
                baseline = read_retry("baseline")
                print(f"Baseline: {baseline['lux']:.3f} lux", flush=True)
            if baseline is None:
                baseline = {"lux": 0, "spectrum": {}}
            for step, (brightness, color) in enumerate(plan, 1):
                if (brightness, color) in finished:
                    continue
                print(f"[{step}/{len(plan)}] brightness={brightness} color={color}", flush=True)
                altered = True
                light.set(brightness, color)
                time.sleep(args.settle)
                measurement = read_retry(f"step_{step}")
                spectrum = measurement["spectrum"]
                row = dict(timestamp_utc=datetime.now(timezone.utc).isoformat(),
                           device=args.device, host=args.service, room=args.room,
                           position=args.position, step=step, brightness_pct=brightness,
                           color_setting=color, color_unit="percent_native" if args.device == "meross" else "mired",
                           lux=measurement["lux"], baseline_lux=baseline["lux"],
                           net_lux=round(measurement["lux"]-baseline["lux"], 3),
                           samples=measurement["samples"],
                           **{c: spectrum.get(c) for c in CHANNELS},
                           baseline_spectrum_json=json.dumps(baseline["spectrum"]),
                           spectrum_json=json.dumps(spectrum), reported_state_json="{}")
                writer.writerow(row)
                fp.flush()
                os.fsync(fp.fileno())
                count += 1
                print(f"  lux={row['lux']:.2f} net={row['net_lux']:.2f}", flush=True)
        event("completed", rows=count)
        print(f"Complete: {outfile} ({count}/{len(plan)})", flush=True)
    except BaseException as exc:
        event("interrupted", rows=count, error=str(exc))
        raise
    finally:
        if altered:
            try:
                if args.keep_off:
                    light.off()
                else:
                    light.restore(original)
            except Exception as exc:
                print(f"WARNING: Could not restore bulb state: {exc}", file=sys.stderr)


if __name__ == "__main__":
    try:
        main()
    except (KeyboardInterrupt, TimeoutError, RuntimeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(2)
