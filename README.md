# DomicileOS light calibration — Python CLI

Uses the existing light-control adapters from your Meross project and Sensus's published MQTT sensor readings. No changes to firmware are necessary for the first pass. **Only works on a LAN with device and MQTT access; not tested against your actual equipment.**

## Install

Keep the existing `meross-project/meross-bulb-lab` directory. Copy this `light_calibration` folder alongside `meross-project` (or set `--project` to its actual directory).

```bash
cd light_calibration
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Set `MEROSS_KEY` in your shell for Meross bulbs. Never commit keys or credentials. You can use `--mqtt-host`, `--mqtt-user`, `--mqtt-password` or `MQTT_HOST`, `MQTT_USERNAME`, `MQTT_PASSWORD` environment variables. The script connects via ordinary MQTT TCP (default port 1883); if you only expose secure WSS, use a local broker/bridge or adjust the client transport.

## Discover lights (no static IPs)

```bash
python calibrate.py --list-lights --discovery-seconds 15
```

Device identity is the mDNS instance name, e.g. `MSL120-ba49`. The script filters non-light HomeKit devices and rejects known MSS smart plugs as calibration targets. It resolves current IPv4 addresses dynamically.

## Test without altering lights

```bash
python calibrate.py --device meross --service MSL120-ba49 --dry-run
python calibrate.py --device meross --service MSL120-ba49 --status
```

`--status` uses the existing Meross local adapter, which may require `MEROSS_KEY` and may fail even when discovery succeeds. Advertised HomeKit port `52432` is distinct from the Meross vendor HTTP protocol; mDNS isn't a way around authentication.

## Run sweep

```bash
python calibrate.py --device meross --service MSL120-ba49 --mqtt-host YOUR_BROKER --room bedroom --position bedside --brightness 10,25,50,75,100 --colors 1,25,50,75,100
```

The script asks you to type `SWEEP` before changing the light. Use a steady background, preferably after dark. VOCOlinc support remains experimental:

```bash
python calibrate.py --device vocolinc --service VOCOlinc-DL2201-1ea1e5 --status
```

The Meross temperature parameter is a native **1–100** scale, not Kelvin. VOCOlinc uses **mireds**.

### Outputs

- `results/YYYYMMDD_HHMMSS_meross_sweep.csv`: raw lux, baseline-adjusted lux, spectral channel counts, and returned light state for each step.
- Plot: `python plot.py results/YOUR_SWEEP.csv` to save a PNG curve.

### Measurement cautions

1. Keep sensor position and orientation fixed. Exclude direct sunlight or changing daylight; preferably calibrate at night. Turn off other controllable lights, and disable competing automations.
2. This script collects fresh packets after the settling interval, but because Sensus currently publishes environment and spectrum only every **10 seconds**, the default capture window is **11 seconds**; long sweeps are expected.
3. The AS7341 counts are not calibrated spectral power or reliable CCT by themselves. The current firmware sets gain/exposure at fixed values, and this script does not detect saturation or rescale varying gains.
4. Auto baseline is collected once at the beginning with only the target light turned off. Background changes later can bias results. Negative net-lux readings flag drift/noise.
5. Restoration is **best-effort** for Meross, not guaranteed. VOCOlinc ends on its last setting by default; use `--keep-off` to turn the target light off at the end. Keep physical controls accessible.
6. MQTT authentication and light control are local. This version does not configure TLS, WSS, or secured cloud access.
7. Commands and reads are device-specific. Verify basic `--status`/manual control before a full run. This is experimental calibration software, not a verified device-control integration.



## Secure MQTT over WebSockets
For Sensus using `mqtt.gnotelis.com:443` and MQTT_PATH `/`, first test telemetry without touching the lights:

```bash
python calibrate.py --sensor-check --mqtt-host mqtt.gnotelis.com --mqtt-port 443 --mqtt-transport websockets --mqtt-path /
```

The script requires fresh environment and spectrum messages before any sweep changes lights. The broker must allow access to these topics.
# light_calibration_tools
