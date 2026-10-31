#!/usr/bin/env python3
"""DomicileOS 24-hour circadian controller: Meross, VOCOlinc, Vizio, Sensus.

Dry run unless --apply. Only modifies devices that are confirmed ON.
The TV backlight uses the previously verified SmartCast MODIFY endpoint.
TV color temperature remains unchanged until separately verified.
"""
import argparse
import json
import os
import ssl
import sys
import time
from datetime import datetime
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import URLError

HERE = Path(__file__).resolve().parent
try:
    from dotenv import load_dotenv
    load_dotenv(HERE / '.env')
except ImportError:
    pass

# hour, bulb brightness%, warmth [0=cool, 1=warm], TV backlight [0..100]
# Tentative starting schedule; not clinical melanopic-EDI targets.
ANCHORS = [
    (0, 3, 1.00, 12),
    (6, 3, 1.00, 12),
    (7, 20, .85, 35),
    (9, 65, .35, 75),
    (12, 85, .10, 90),
    (16, 70, .20, 75),
    (18, 40, .65, 55),
    (20, 17, .92, 35),
    (22, 6, 1.00, 18),
    (24, 3, 1.00, 12),
]


def targets(hour):
    for (h0, b0, w0, t0), (h1, b1, w1, t1) in zip(ANCHORS, ANCHORS[1:]):
        if h0 <= hour <= h1:
            f = (hour-h0)/(h1-h0)
            f = f*f*(3-2*f)
            return round(b0+(b1-b0)*f), w0+(w1-w0)*f, round(t0+(t1-t0)*f)
    return 3, 1.0, 12


def sensor_read(url, timeout):
    try:
        with urlopen(url, timeout=timeout) as r:
            d = json.load(r)
        return d if d.get('ok') is True else None
    except Exception as e:
        print(f'  Sensus unavailable: {e}')
        return None


def discover_lamps(seconds):
    from zeroconf import Zeroconf, ServiceBrowser, ServiceListener

    class Listener(ServiceListener):
        def __init__(self):
            self.devices = {}
        def add_service(self, z, k, n):
            self.update_service(z, k, n)
        def update_service(self, z, k, n):
            info = z.get_service_info(k, n, timeout=1500)
            if not info:
                return
            name = n.removesuffix('._hap._tcp.local.')
            ident = name.lower()
            if 'msl120' in ident:
                self.devices[name] = ('meross', name)
            elif 'dl2201' in ident:
                self.devices[name] = ('vocolinc', name)
        def remove_service(self, z, k, n):
            self.devices.pop(n.removesuffix('._hap._tcp.local.'), None)

    zc = Zeroconf()
    listener = Listener()
    browser = ServiceBrowser(zc, '_hap._tcp.local.', listener)
    try:
        time.sleep(seconds)
        return sorted(listener.devices.values())
    finally:
        browser.cancel()
        zc.close()


def lamp_is_on(vendor, state):
    if not isinstance(state, dict):
        return None
    if vendor == 'vocolinc':
        nested = state.get('state', state)
        val = nested.get('switch0') if isinstance(nested, dict) else None
        return bool(val) if val is not None else None
    toggle = state.get('togglex')
    if isinstance(toggle, list) and toggle:
        toggle = toggle[0]
    if isinstance(toggle, dict) and 'onoff' in toggle:
        return bool(toggle['onoff'])
    # Some Meross adapters expose this normalized value.
    if isinstance(state.get('state'), dict) and 'onoff' in state['state']:
        return bool(state['state']['onoff'])
    return None


def zone_for(vendor):
    return 'bedroom' if vendor == 'vocolinc' else 'tvroom'


def run_lamps(args, brightness, warmth):
    lamps = discover_lamps(args.discovery_seconds)
    if not lamps:
        print('No supported lamps discovered.')
        return
    for vendor, service in lamps:
        zone = zone_for(vendor)
        if args.zone != 'all' and args.zone != zone:
            continue
        if vendor == 'vocolinc':
            color = round(args.vocolinc_cool + warmth*(args.vocolinc_warm-args.vocolinc_cool))
        else:
            color = round(args.meross_cool + warmth*(args.meross_warm-args.meross_cool))
        print(f'  {zone:7} {service}: brightness {brightness}%, native color {color}', end='')
        if not args.apply:
            print(' [dry run]')
            continue
        try:
            from discovery import resolve_device
            from calibrate import Light
            resolved = resolve_device(args.project, service, vendor, args.discovery_seconds)
            light = Light(vendor, resolved['address'], args.project, args.service_id)
            on = lamp_is_on(vendor, light.state())
            if on is not True:
                print(' [skipped: OFF or unknown state]')
                continue
            if vendor == 'vocolinc':
                # Existing VOCOlinc adapter's local-state API. Keep switch0 ON.
                light.device.local.put_state({'level0': brightness, 'k0': color, 'switch0': 1})
            else:
                light.device.set_color_temperature(color, brightness=brightness)
            print(' [applied]')
        except Exception as e:
            print(f' [error: {e}]')


def vizio_api(host, port, token, path, method='GET', payload=None, timeout=8):
    # SmartCast on the local LAN normally uses a self-signed certificate.
    url = f'https://{host}:{port}{path}'
    headers = {'AUTH': token, 'Content-Type': 'application/json'}
    raw = json.dumps(payload).encode() if payload is not None else None
    req = Request(url, data=raw, headers=headers, method=method)
    with urlopen(req, timeout=timeout, context=ssl._create_unverified_context()) as r:
        response = json.load(r)
    status = response.get('STATUS', {}).get('RESULT')
    if status != 'SUCCESS':
        raise RuntimeError(f'SmartCast {path}: {status}: {response.get("STATUS", {}).get("DETAIL")}')
    return response


def tv_control(args, backlight):
    if args.zone == 'bedroom' or args.no_tv:
        return
    if not args.tv_token:
        print('  Vizio: VIZIO_AUTH_TOKEN not configured; skipping.')
        return
    try:
        power = vizio_api(args.tv_host, args.tv_port, args.tv_token,
                          '/state/device/power_mode', timeout=args.timeout)
        items = power.get('ITEMS', [])
        code = next((x.get('VALUE') for x in items if x.get('CNAME') == 'power_mode'), None)
        # 0 was observed while TV was on during the confirmed backlight test.
        if code != args.tv_on_code:
            print(f'  Vizio: power code {code!r}; not confirmed ON, skipping.')
            return
        picture = vizio_api(args.tv_host, args.tv_port, args.tv_token,
                            '/menu_native/dynamic/tv_settings/picture', timeout=args.timeout)
        item = next((x for x in picture.get('ITEMS', []) if x.get('CNAME') == 'backlight'), None)
        if not item or not isinstance(item.get('VALUE'), (int, float)) or not isinstance(item.get('HASHVAL'), int):
            print('  Vizio: backlight setting/hash missing, skipping.')
            return
        old = round(item['VALUE'])
        print(f'  Vizio: backlight {old} -> {backlight}', end='')
        if abs(old-backlight) < args.tv_deadband:
            print(' [within deadband]')
        elif not args.apply:
            print(' [dry run]')
        else:
            vizio_api(args.tv_host, args.tv_port, args.tv_token,
                      '/menu_native/dynamic/tv_settings/picture/backlight',
                      method='PUT', payload={'REQUEST':'MODIFY', 'HASHVAL':item['HASHVAL'], 'VALUE':backlight},
                      timeout=args.timeout)
            print(' [applied]')
    except Exception as e:
        print(f'  Vizio error: {e}')


def cycle(args):
    now = datetime.now().astimezone()
    if args.at:
        hh, mm = map(int, args.at.split(':'))
        hour = hh + mm/60
    else:
        hour = now.hour + now.minute/60 + now.second/3600
    brightness, warmth, tv_backlight = targets(hour)
    print(f'\n[{now.isoformat(timespec="seconds")}] target {hour:05.2f}h | '
          f'bulbs {brightness}% | warmth {warmth:.2f} | TV backlight {tv_backlight}'
          f' | {"APPLY" if args.apply else "DRY RUN"}')
    if not args.no_sensor and args.zone != 'bedroom':
        d = sensor_read(args.sensor_url, args.timeout)
        if d:
            print(f'  Sensus (current sensor position): {d.get("lux")} lux')
    run_lamps(args, brightness, warmth)
    tv_control(args, tv_backlight)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--apply', action='store_true', help='Send changes; otherwise preview')
    p.add_argument('--watch', type=float, default=0, metavar='MINUTES', help='Repeat every N minutes; Ctrl+C to stop')
    p.add_argument('--at', help='Preview or apply a simulated time HH:MM')
    p.add_argument('--zone', choices=('all', 'tvroom', 'bedroom'), default='all')
    p.add_argument('--project', type=Path, default=Path(os.getenv('LIGHT_PROJECT','../meross-project/meross-bulb-lab')))
    p.add_argument('--service-id', default='0')
    p.add_argument('--sensor-url', default=os.getenv('SENSUS_URL','http://10.0.1.84/read'))
    p.add_argument('--no-sensor', action='store_true')
    p.add_argument('--no-tv', action='store_true')
    p.add_argument('--tv-host', default=os.getenv('VIZIO_HOST', '10.0.1.3'))
    p.add_argument('--tv-port', type=int, default=int(os.getenv('VIZIO_PORT', '7345')))
    p.add_argument('--tv-token', default=os.getenv('VIZIO_AUTH_TOKEN', ''))
    p.add_argument('--tv-on-code', type=int, default=0, help='Power code observed with TV on (previously 0)')
    p.add_argument('--tv-deadband', type=int, default=3)
    p.add_argument('--meross-warm', type=int, default=1, help='Verify native endpoints against profile')
    p.add_argument('--meross-cool', type=int, default=100)
    p.add_argument('--vocolinc-warm', type=int, default=500)
    p.add_argument('--vocolinc-cool', type=int, default=200)
    p.add_argument('--discovery-seconds', type=float, default=4)
    p.add_argument('--timeout', type=float, default=8)
    args = p.parse_args()
    if args.at:
        try:
            h, m = map(int, args.at.split(':'))
            assert 0 <= h <= 23 and 0 <= m <= 59
        except (ValueError, AssertionError):
            p.error('--at must be HH:MM (00:00-23:59)')
    if args.watch < 0 or args.tv_deadband < 0:
        p.error('Invalid watch or deadband value')
    try:
        while True:
            cycle(args)
            if not args.watch:
                break
            time.sleep(args.watch * 60)
    except KeyboardInterrupt:
        print('\nStopped.')


if __name__ == '__main__':
    main()
