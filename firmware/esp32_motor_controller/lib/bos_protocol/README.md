Message framing (start byte, length, payload, CRC) and the motor-setting
messages exchanged with the Pi over the serial link. Keep it free of Arduino
headers so it can be unit-tested on the Pi and shared with the Pi-side code.
