#pragma once
#include <Arduino.h>

// 物理按键 GPIO（ESP32-S3 DevKit 板载 BOOT 按键 = GPIO0）
#define MODE_BUTTON_PIN 0
#define DEBOUNCE_MS     50

enum class Mode {
    VOICE_KEYBOARD,  // STT → 文字打进输入框
    MICROPHONE,      // 音频直通 → USB 麦克风
};

class ModeManager {
public:
    Mode current = Mode::VOICE_KEYBOARD;

    void begin() {
        pinMode(MODE_BUTTON_PIN, INPUT_PULLUP);
    }

    // 放在 loop() 里轮询，按键按下时切换模式并返回 true
    bool poll() {
        bool pressed = (digitalRead(MODE_BUTTON_PIN) == LOW);
        if (pressed && !_lastPressed && (millis() - _lastToggleMs > DEBOUNCE_MS)) {
            _lastToggleMs = millis();
            _toggle();
            _lastPressed = true;
            return true;
        }
        if (!pressed) _lastPressed = false;
        return false;
    }

    bool isVoiceKeyboard() const { return current == Mode::VOICE_KEYBOARD; }
    bool isMicrophone()    const { return current == Mode::MICROPHONE; }

    const char* name() const {
        return current == Mode::VOICE_KEYBOARD ? "Voice Keyboard" : "Microphone";
    }

private:
    bool     _lastPressed   = false;
    uint32_t _lastToggleMs  = 0;

    void _toggle() {
        current = (current == Mode::VOICE_KEYBOARD)
                  ? Mode::MICROPHONE
                  : Mode::VOICE_KEYBOARD;
    }
};
