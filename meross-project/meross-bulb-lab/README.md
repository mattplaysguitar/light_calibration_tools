# Meross Bulb Lab

Minimal local-control test project for a Meross MSL120D bulb at `10.0.1.9`.

This project is intentionally read-only for the first milestone. It does not factory-reset the bulb, alter HomeKit pairing, change Wi-Fi settings, or send light state changes.

## Protocol Evidence

The implementation follows the current `krahabb/meross_lan` source:

- LAN HTTP requests are sent with `POST` to `http://<host>/config`.
- The request body is JSON with top-level `header` and `payload`.
- `messageId` is generated as 16 random bytes rendered as 32 lowercase hex characters.
- `timestamp` is Unix seconds; `timestampMs` is `0`.
- `sign` is `md5(messageId + key + timestamp)`.
- `triggerSrc` and `from` default to `MerossClient`.
- `Appliance.System.Ability`, `Appliance.System.All`, and `Appliance.Control.Light` are declared as GET-capable namespaces.
- The current source still contains an HTTP-only key-reply hack for some invalid-key cases, but this probe does not use it automatically. If no key is available, it stops before sending requests.
- Meross error code `5001` is treated as an invalid key/signature error.

Relevant upstream files:

- `custom_components/meross_lan/merossclient/httpclient.py`
- `custom_components/meross_lan/merossclient/protocol/message.py`
- `custom_components/meross_lan/merossclient/protocol/namespaces/__init__.py`
- `custom_components/meross_lan/merossclient/protocol/const.py`

## Setup

Use a current Python 3 version. Python 3.11+ is fine.

```bash
cd meross-bulb-lab
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

There are no third-party dependencies for the read-only probe.

## Meross Key

Set the Meross device/account key with:

```bash
export MEROSS_KEY="your-meross-key"
```

Or put it in a local `.env` file:

```bash
MEROSS_KEY=your-meross-key
```

Do not put the key in source code. The HomeKit setup code is not the Meross key.

If the bulb is still paired to the Meross app/cloud and you do not know the key, the least disruptive next step is to recover it from the Meross cloud account profile, as documented by `meross_lan`; do not reset or re-pair the bulb.

## Read-Only Probe

```bash
python meross_probe.py
```

Optional flags:

```bash
python meross_probe.py --host 10.0.1.9 --timeout 10
python meross_probe.py --key "temporary-key-for-this-run"
python meross_probe.py --allow-empty-key
```

`--allow-empty-key` sends exactly one read-only pass signed with an empty key. Use it only to test whether this firmware still allows historical keyless/empty-key local access.

## Discovery

If bulb IP addresses change, scan the local subnet with read-only `Appliance.System.All` requests:

```bash
python meross_discover.py --subnet 10.0.1.0/24
```

Discovery results are saved to:

```bash
captures/discovered_devices.json
```

Each discovered device includes `localNames` when reverse DNS, mDNS, or the local resolver can provide names for the IP.

Known names can also be pinned in:

```bash
local_names.json
```

This is useful for IoT devices whose `.local` names are visible in Bonjour but do not answer reverse DNS reliably.

Then probe a discovered bulb:

```bash
python meross_probe.py --host 10.0.1.9
```

## Captures

Responses and request metadata are written to:

- `captures/<host>/system_ability.json`
- `captures/<host>/system_all.json`
- `captures/<host>/control_light.json`

The raw response body is saved before parsing, and parsed JSON is saved separately in the same capture file.

## Interactive Raw Light Tests

After read-only probing succeeds, run one manually selected `Appliance.Control.Light` SET:

```bash
python raw_light_test.py --host 10.0.1.9
```

The tool shows the exact JSON request, sends the selected SET, immediately reads back state, then returns to the menu until you choose `q`.

- `Appliance.Control.Light`
- `Appliance.Control.ToggleX`

Initial tests are limited to:

- red, 10% luminance
- green, 10% luminance
- blue, 10% luminance
- warmest white, 10% luminance
- coolest white, 10% luminance

Captures are saved under:

```bash
captures/<host>/raw_light_tests/
```

## Meross Python API

The `meross` package provides a small import-friendly API similar to the
VOCOlinc wrapper:

```python
from meross import MerossDevice

lamp = MerossDevice.local_ip("10.0.1.9")

print(lamp.get_state())
lamp.turn_on()
lamp.set_brightness(50)
lamp.set_rgb(255, 0, 0, brightness=10)
lamp.set_color_temperature(100, brightness=25)
lamp.turn_off()
```

It reads `MEROSS_KEY` from the environment or the local `.env` file. You can
also pass `key=` directly:

```python
lamp = MerossDevice.local_ip("10.0.1.9", key="your-meross-key")
```

Low-level raw namespace access is available through `MerossLocalClient`.

## Spectral Records

`spectral_test.py` supports a read-only mode and a single manually selected spectral SET workflow.

Read current state only:

```bash
python spectral_test.py --read --host 10.0.1.9
```

Interactive menu:

```bash
python spectral_test.py --host 10.0.1.9
```

The menu supports:

- read current light state only
- red, green, or blue at 10% luminance
- warmest or coolest white at 10% luminance
- one custom raw light object
- exit

Before any SET, the tool shows the exact signed JSON and asks for confirmation. Pressing Enter defaults to no.

```bash
python spectral_test.py \
  --requested-light-object '{"channel":0,"capacity":4,"luminance":50}' \
  --spectrometer-file "measurement_0001.csv" \
  --notes "manual baseline"
```

Records append to `captures/spectral_tests.jsonl`. Unknown fields remain `null`.

## VOCOlinc HomeKit Probe

For the VOCOlinc DL2201 HomeKit lamp, use the unauthenticated read-only probe:

```bash
python vocolinc_probe.py --host 10.0.1.4 --port 8080
```

This checks TCP connectivity and attempts only unauthenticated `GET` reads from HAP endpoints. It does not run Pair-Setup, touch `/pairings`, or write characteristics.

Notes on authenticated HomeKit access are in [HOMEKIT_NOTES.md](HOMEKIT_NOTES.md).
