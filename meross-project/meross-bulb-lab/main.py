from vocolinc import VocolincDevice


lamp = VocolincDevice.local_ip("10.0.1.4")

print(lamp.get_state())

# Examples:
# lamp.turn_on()
# lamp.turn_off()
# lamp.set_brightness(50)
# lamp.set_color_temperature(300)
# lamp.blink(seconds=5)
