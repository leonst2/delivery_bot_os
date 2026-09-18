#include <Arduino.h>

// Placeholder that proves flashing and the USB serial link work: echoes every
// byte received from the Pi and blinks the on-board LED. Replace with the
// motor-command handling once the protocol in lib/bos_protocol exists.
void setup() {
  Serial.begin(115200);  // UART0 (GPIO1 TX / GPIO3 RX), wired to the USB bridge
  pinMode(LED_BUILTIN, OUTPUT);
}

void loop() {
  while (Serial.available()) {
    Serial.write(Serial.read());
  }
  digitalWrite(LED_BUILTIN, (millis() / 500) % 2);
}
