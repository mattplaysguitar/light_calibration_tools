#!/usr/bin/env python3
"""DomicileOS circadian lighting test: Meross/VOCOlinc + Sensus + TV observation.

Dry-run by default. --apply changes only lamps already ON, and never sends
an ON command. TV is measured as ambient light but is NOT controlled.
"""
import argparse
import json
import math
import os
import sys
import time
from datetime import datetime
from pathlib import Path
from urllib.request import urlopen

try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parent / '.env')
except ImportError:
    pass

HERE = Path(__file__).resolve().parent
DEFAULT_PROJECT = Path(os.getenv('LIGHT_PROJECT', '../meross-project/meross-bulb-lab'))
DEFAULT_SENSOR = os.getenv('SENSUS_URL', 'http://10.0.1.84/read')

# Local-clock anchors: time (HH:MM), brightness %, warm fraction (0=cool, 1=warm)
ANCHORS = [(0, 3, 1.0), (6, 3, 1.0), (7, 20, .85),
           (9, 65, .35), (12, 85, 0.0), (16, 70, .15),
           (18, 40, .65), (20, 17, .92), (22, 6, 1.0), (24, 3, 1.0)]


def interpolate(hour):
    for (a, b1, w1), (z, b2, w2) in zip(ANCHORS, ANCHORS[1:]):
        if a <= hour <= z:
            t = (hour - a) / (z-a)
            t = t*t*(3-2*t)  # smooth transitions
            return round(b1 + (b2-b1)*t), w1 + (w2-w1)*t
    return 3, 1.0


def sensor_read(url, timeout):
    try:
        with urlopen(url, timeout=timeout) as resp:
            data = json.load(resp)
        if not data.get('ok') or not isinstance(data.get('lux'), (int, float)):
            raise ValueError(f'Invalid Sensus response: {data}')
        return data
    except Exception as exc:
        print(f'[Sensus] Unavailable: {exc}', file=sys.stderr)
        return None


def discover(seconds):
    from zeroconf import Zeroconf, ServiceBrowser, ServiceListener

    class Listener(ServiceListener):
        def __init__(self): self.devices = {}
        def add_service(self, zc, kind, name): self.update_service(zc, kind, name)
        def update_service(self, zc, kind, name):
            info = zc.get_service_info(kind, name, timeout=1500)
            if not info: return
            service = name.removesuffix('._hap._tcp.local.')
            props = ' '.join(str(v) for v in info.properties.values()).lower()
            identity = (service + ' ' + str(info.server) + ' ' + props).lower()
            if 'msl120' in identity: vendor = 'meross'
            elif 'dl2201' in identity: vendor = 'vocolinc'
            else: return
            self.devices[name] = (vendor, service)
        def remove_service(self, zc, kind, name): self.devices.pop(name, None)

    listener = Listener()
    zc = Zeroconf()
    browser = ServiceBrowser(zc, '_hap._tcp.local.', listener)
    try:
        time.sleep(seconds)
        return sorted(set(listener.devices.values()))
    finally:
        browser.cancel()
        zc.close()


def power_state(vendor, state):
    if vendor == 'vocolinc':
        obj = state.get('state', {})
        value = obj.get('switch0')
        return bool(value) if value is not None else None
    toggle = state.get('togglex')
    if isinstance(toggle, list) and toggle:
        return bool(toggle[0]['onoff']) if 'onoff' in toggle[0] else None
    if isinstance(toggle, dict) and 'onoff' in toggle:
        return bool(toggle['onoff'])
    return None


def native_color(vendor, warm_fraction, args):
    if vendor == 'vocolinc':
        # Mireds: larger values = physically warmer white.
        return round(args.vocolinc_cool + warm_fraction * (args.vocolinc_warm-args.vocolinc_cool))
    # Meross 1-100: orientation is device-specific and must be calibrated.
    return round(args.meross_cool + warm_fraction * (args.meross_warm-args.meross_cool))


def set_on_lamp(vendor, light, brightness, color):
    if vendor == 'vocolinc':
        # Explicitly keep power ON. Avoid turn_on() and potential power-state toggles.
        light.device.local.put_state({'level0': brightness, 'k0': color, 'switch0': 1})
    else:
        # Existing adapter may switch on as a side effect: ONLY call for ON lamps.
        light.device.set_color_temperature(color, brightness=brightness)


def cycle(args):
    from discovery import resolve_device
    from calibrate import Light

    now = datetime.now().astimezone()
    hour = (args.at_hour if args.at_hour is not None else
            now.hour + now.minute/60 + now.second/3600)
    level, warmth = interpolate(hour)
    print(f'\nCircadian target at {hour:05.2f}h: {level}% brightness, warmth={warmth:.2f}')
    print('TV: observation only. Picture modes and power will NOT be changed.')
    print('NOTE: Lamp color values are device-native estimates, not calibrated kelvin.')
    before = sensor_read(args.sensor_url, args.timeout) if not args.no_sensor else None
    if before: print(f'Sensus before: {before["lux"]:.2f} lux')

    devices = discover(args.discovery_seconds)
    if not devices:
        print('No supported Meross MSL120 / VOCOlinc DL2201 lamps found.')
        return

    if args.apply and not args.project.exists():
        raise SystemExit(f'Missing existing adapter project: {args.project}')

    applied = 0
    for vendor, service in devices:
        setting = native_color(vendor, warmth, args)
        print(f'  {vendor:8s} {service:28s} => brightness={level}% color={setting}', end='')
        if not args.apply:
            print(' [DRY RUN]')
            continue
        try:
            info = resolve_device(args.project, service, vendor, args.discovery_seconds)
            light = Light(vendor, info['address'], args.project, args.service_id)
            state = light.state()
            on = power_state(vendor, state)
            if on is not True:
                print(f' [SKIPPED: {"OFF" if on is False else "unknown power state"}]')
                continue
            set_on_lamp(vendor, light, level, setting)
            applied += 1
            print(' [SET; already ON]')
        except Exception as exc:
            print(f' [ERROR: {exc}]')
    if args.apply and applied and args.settle:
        time.sleep(args.settle)
    after = sensor_read(args.sensor_url, args.timeout) if args.apply and not args.no_sensor else None
    if after:
        print(f'Sensus after: {after["lux"]:.2f} lux (TV + lamps + other light)')
    print(f'Devices discovered: {len(devices)}; changed: {applied}.')


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--apply', action='store_true', help='Send actual changes to lamps that are already ON')
    p.add_argument('--at', help='Simulate target at HH:MM; with --apply, actually apply that target')
    p.add_argument('--watch', type=float, default=0, metavar='MINUTES', help='Repeat every N minutes; Ctrl+C to stop')
    p.add_argument('--sensor-url', default=DEFAULT_SENSOR)
    p.add_argument('--no-sensor', action='store_true')
    p.add_argument('--timeout', type=float, default=8)
    p.add_argument('--discovery-seconds', type=float, default=5)
    p.add_argument('--settle', type=float, default=2)
    p.add_argument('--project', type=Path, default=DEFAULT_PROJECT)
    p.add_argument('--service-id', default='0')
    p.add_argument('--meross-warm', type=int, default=1, help='Calibrated warm endpoint, 1..100')
    p.add_argument('--meross-cool', type=int, default=100, help='Calibrated cool endpoint, 1..100')
    p.add_argument('--vocolinc-warm', type=int, default=500, help='Warm endpoint in mireds')
    p.add_argument('--vocolinc-cool', type=int, default=200, help='Cool endpoint in mireds')
    args = p.parse_args()
    if args.at:
        try:
            h, m = map(int, args.at.split(':'))
            if not (0 <= h <= 23 and 0 <= m <= 59): raise ValueError
        except ValueError:
            p.error('--at must be HH:MM, 00:00 through 23:59')
        args.at_hour = h + m/60
    else:
        args.at_hour = None
    if args.watch < 0 or args.timeout <= 0 or args.discovery_seconds <= 0:
        p.error('Invalid timing')
    if not all(1 <= n <= 100 for n in (args.meross_warm, args.meross_cool)):
        p.error('Meross endpoints must be 1..100')
    if not all(1 <= n <= 1000 for n in (args.vocolinc_warm, args.vocolinc_cool)):
        p.error('VOCOlinc endpoints must be 1..1000')
    while True:
        cycle(args)
        if not args.watch: break
        time.sleep(args.watch * 60)

if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        print('\nStopped.')
