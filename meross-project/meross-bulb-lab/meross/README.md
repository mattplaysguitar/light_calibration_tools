# Meross Python API

This package mirrors the small VOCOlinc API shape while speaking the Meross LAN
HTTP protocol.

## Local Control

Set `MEROSS_KEY` in your shell or pass `key=` directly.

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

You can also use the lower-level client:

```python
from meross import MerossLocalClient

client = MerossLocalClient("10.0.1.9", key="your-meross-key")

print(client.get_light())
print(client.get_togglex())
client.set_on(True)
client.set_color(0x00FF00, brightness=10)
client.set_color_temperature(1, brightness=10)
```

## Notes

- On/off uses `Appliance.Control.ToggleX`.
- Brightness, RGB, and white temperature use `Appliance.Control.Light`.
- Meross white temperature is represented as the device's 1-100 value, not
  VOCOlinc/HomeKit mireds.
- Remote/cloud control is deliberately left as a placeholder until cloud auth is
  verified.
