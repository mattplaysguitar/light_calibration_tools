# VOCOlinc Python API

This package keeps local LAN control and future remote cloud control separate.

## Local Control

Local control uses VOCOlinc ALC TCP commands directly against the device IP on
port `12345`.

```python
from vocolinc import VocolincDevice

lamp = VocolincDevice.local_ip("10.0.1.4")

lamp.turn_on()
lamp.set_brightness(50)
lamp.set_color_temperature(300)
lamp.turn_off()
```

You can also use the lower-level local client:

```python
from vocolinc import VocolincLocalClient

client = VocolincLocalClient("10.0.1.4")

print(client.get_state())
client.set_on(True)
client.set_brightness(25)
client.set_color_temperature(300)
client.set_on(False)
```

## Remote Control

Remote control is intentionally isolated in `vocolinc.remote`.

```python
from vocolinc import VocolincRemoteClient

remote = VocolincRemoteClient(email="you@example.com", password="secret")
```

The remote client currently raises `VocolincRemoteError` because the VOCOlinc
cloud API endpoints, authentication, and signing/encryption still need to be
verified before any cloud login or cloud write is implemented.
