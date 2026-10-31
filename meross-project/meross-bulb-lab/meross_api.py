from meross import MerossDevice


lamp = MerossDevice.local_ip("10.0.1.9")

print(lamp.get_state())

# Examples:
# lamp.turn_on()
# lamp.turn_off()
# lamp.set_brightness(50)
# lamp.set_rgb(255, 0, 0, brightness=10)
# lamp.set_color(0x00FF00, brightness=10)
# lamp.set_color_temperature(100, brightness=25)
# lamp.blink(seconds=5)
