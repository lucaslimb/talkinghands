#include <FastLED.h>
#include <string.h>

#define DATA_PIN 7
// Limite usado pelo controlador. Se a fita tiver mais de 60 LEDs, aumente este
// valor; se tiver menos, os dados excedentes não produzem luz.
#define NUM_LEDS 165
#define LED_TYPE WS2812B
#define COLOR_ORDER GRB

// Velocidade deslocaamento do padrao
const uint8_t IDLE_SPEED = 1;
// Intervalo entre quadros: maior valor deixa o movimento mais sutil.
const uint16_t IDLE_FRAME_INTERVAL_MS = 50;
CRGB leds[NUM_LEDS];
String command;
bool idleEnabled = false;
uint8_t idlePhase = 0;
unsigned long lastIdleFrame = 0;
bool flashEnabled = false;
CRGB flashColor = CRGB::Black;
uint16_t flashDurationMs = 1000;
unsigned long flashStartedAt = 0;
bool keyboardKeys[64] = {false};
uint8_t keyboardKeyCount = 0;
uint8_t keyboardActiveCount = 0;

void clearKeyboardKeys() {
  for (uint8_t i = 0; i < 64; i++) keyboardKeys[i] = false;
  keyboardKeyCount = 0;
  keyboardActiveCount = 0;
}

void renderKeyboard() {
  fill_solid(leds, NUM_LEDS, CRGB::Black);
  if (keyboardKeyCount == 0) {
    FastLED.show();
    return;
  }

  for (uint8_t key = 0; key < keyboardKeyCount; key++) {
    if (!keyboardKeys[key]) continue;
    int start = (key * (long)NUM_LEDS) / keyboardKeyCount;
    int end = ((key + 1) * (long)NUM_LEDS) / keyboardKeyCount;
    for (int led = start; led < end; led++) leds[led] = CRGB(0, 255, 0);
  }
  FastLED.show();
}

void renderKeyboardActivity() {
  fill_solid(leds, NUM_LEDS, CRGB::Black);
  if (keyboardActiveCount == 0 || keyboardKeyCount == 0) {
    FastLED.show();
    return;
  }

  uint16_t width = ((uint32_t)NUM_LEDS * keyboardActiveCount) / keyboardKeyCount;
  width = constrain(width, 1, NUM_LEDS);
  int start = (NUM_LEDS - width) / 2;
  uint8_t brightness = map(keyboardActiveCount, 1, keyboardKeyCount, 45, 255);
  CRGB color = CRGB(0, 255, 0);
  color.nscale8_video(brightness);
  for (int led = start; led < start + width; led++) leds[led] = color;
  FastLED.show();
}

void setup() {
  FastLED.addLeds<LED_TYPE, DATA_PIN, COLOR_ORDER>(leds, NUM_LEDS);
  FastLED.setBrightness(255);
  FastLED.clear(true);
  Serial.begin(115200);
  command.reserve(40);
}

void applyCommand(const String& value) {
  if (value == "OFF") {
    idleEnabled = false;
    flashEnabled = false;
    clearKeyboardKeys();
    fill_solid(leds, NUM_LEDS, CRGB::Black);
    FastLED.show();
    return;
  }

  if (value == "IDLE ON") {
    flashEnabled = false;
    clearKeyboardKeys();
    idleEnabled = true;
    return;
  }

  if (value == "IDLE OFF") {
    idleEnabled = false;
    flashEnabled = false;
    clearKeyboardKeys();
    fill_solid(leds, NUM_LEDS, CRGB::Black);
    FastLED.show();
    return;
  }

  int red, green, blue;
  int duration;
  int brightness;
  char keyState[4];
  int keyIndex, keyTotal;
  int activeCount;
  if (sscanf(value.c_str(), "KEYCOUNT %d %d", &activeCount, &keyTotal) == 2) {
    idleEnabled = false;
    flashEnabled = false;
    keyboardKeyCount = constrain(keyTotal, 1, 64);
    keyboardActiveCount = constrain(activeCount, 0, keyboardKeyCount);
    renderKeyboardActivity();
    return;
  }

  if (sscanf(value.c_str(), "KEY %3s %d %d", keyState, &keyIndex, &keyTotal) == 3) {
    idleEnabled = false;
    flashEnabled = false;
    keyboardKeyCount = constrain(keyTotal, 1, 64);
    keyIndex = constrain(keyIndex, 0, keyboardKeyCount - 1);
    keyboardKeys[keyIndex] = (strcmp(keyState, "ON") == 0);
    renderKeyboard();
    return;
  }

  if (sscanf(value.c_str(), "MAESTRO %d %d %d %d", &red, &green, &blue, &brightness) == 4) {
    idleEnabled = false;
    flashEnabled = false;
    clearKeyboardKeys();
    CRGB color = CRGB(constrain(red, 0, 255), constrain(green, 0, 255), constrain(blue, 0, 255));
    color.nscale8_video(constrain(brightness, 0, 255));
    fill_solid(leds, NUM_LEDS, color);
    FastLED.show();
    return;
  }

  if (sscanf(value.c_str(), "FLASH %d %d %d %d", &red, &green, &blue, &duration) == 4) {
    idleEnabled = false;
    flashEnabled = true;
    clearKeyboardKeys();
    flashColor = CRGB(constrain(red, 0, 255), constrain(green, 0, 255), constrain(blue, 0, 255));
    flashDurationMs = constrain(duration, 1, 5000);
    flashStartedAt = millis();
    fill_solid(leds, NUM_LEDS, flashColor);
    FastLED.show();
    return;
  }

  if (sscanf(value.c_str(), "COLOR %d %d %d", &red, &green, &blue) == 3) {
    flashEnabled = false;
    clearKeyboardKeys();
    red = constrain(red, 0, 255);
    green = constrain(green, 0, 255);
    blue = constrain(blue, 0, 255);
    fill_solid(leds, NUM_LEDS, CRGB(red, green, blue));
    FastLED.show();
  }
}

void loop() {
  while (Serial.available() > 0) {
    char character = static_cast<char>(Serial.read());
    if (character == '\n' || character == '\r') {
      if (command.length() > 0) {
        applyCommand(command);
        command = "";
      }
    } else if (command.length() < 39) {
      command += character;
    }
  }

  if (flashEnabled) {
    unsigned long elapsed = millis() - flashStartedAt;
    if (elapsed >= flashDurationMs) {
      flashEnabled = false;
      fill_solid(leds, NUM_LEDS, CRGB::Black);
    } else {
      uint8_t brightness = 255 - (uint8_t)((elapsed * 255UL) / flashDurationMs);
      CRGB faded = flashColor;
      faded.nscale8_video(brightness);
      fill_solid(leds, NUM_LEDS, faded);
    }
    FastLED.show();
  }

  if (idleEnabled && millis() - lastIdleFrame >= IDLE_FRAME_INTERVAL_MS) {
    lastIdleFrame = millis();
    // Cores saturadas para um roxo e um verde mais vivos.
    const CRGB purple = CRGB(190, 0, 255);
    const CRGB green = CRGB(0, 255, 35);

    for (int index = 0; index < NUM_LEDS; index++) {
      uint8_t position = (uint8_t)((index * 255L) / max(1, NUM_LEDS - 1));
      // sin8 cria uma transição simétrica: o fade acontece nos dois lados
      // da faixa, sem deixar um lado mais forte que o outro.
      uint8_t mix = sin8(position + idlePhase);
      leds[index] = blend(purple, green, mix);
    }
    FastLED.show();
    idlePhase += IDLE_SPEED;
  }
}
