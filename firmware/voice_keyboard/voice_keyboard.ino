/**
 * Voice Keyboard — ESP32-S3 固件
 *
 * USB 复合设备：HID 键盘 + CDC 串口 + UAC 麦克风
 *
 * 模式切换：按 BOOT 键（GPIO0）在两种模式间切换
 *   - Voice Keyboard：语音 → STT → 文字输入
 *   - Microphone：音频直通 → USB 麦克风（Zoom、微信等可直接使用）
 *
 * 烧录配置（Arduino IDE）：
 *   Board:              ESP32S3 Dev Module
 *   USB Mode:           USB-OTG (TinyUSB)
 *   USB CDC On Boot:    Disabled
 *   USB Stack:          TinyUSB（安装 Adafruit TinyUSB Library 后可见）
 *   Upload Mode:        UART0 / Hardware CDC
 */

#include "USB.h"
#include "USBHIDKeyboard.h"
#include "USBCDC.h"
#include "text_router.h"
#include "mode_manager.h"
#include "usb_audio.h"

USBHIDKeyboard Keyboard;
USBCDC         AgentSerial;
ModeManager    Modes;
USBAudio       UsbMic;

#define DEBUG_SERIAL Serial0
#define LED_PIN      21    // 板载 LED，根据实际板子调整

void updateLed() {
    // Voice Keyboard 模式：LED 常亮
    // Microphone 模式：LED 慢闪
    static uint32_t lastBlink = 0;
    static bool     ledState  = false;

    if (Modes.isVoiceKeyboard()) {
        digitalWrite(LED_PIN, HIGH);
    } else {
        if (millis() - lastBlink > 800) {
            lastBlink = millis();
            ledState  = !ledState;
            digitalWrite(LED_PIN, ledState);
        }
    }
}

void setup() {
    DEBUG_SERIAL.begin(115200);
    pinMode(LED_PIN, OUTPUT);

    Modes.begin();
    USB.begin();
    Keyboard.begin();
    AgentSerial.begin(115200);
    UsbMic.begin();

    DEBUG_SERIAL.println("[vk] Voice Keyboard ready");
    DEBUG_SERIAL.println("[vk] 当前模式: Voice Keyboard");
    DEBUG_SERIAL.println("[vk] 按 BOOT 键切换模式");
}

void loop() {
    updateLed();

    // ── 模式切换 ──────────────────────────────────────────────
    if (Modes.poll()) {
        DEBUG_SERIAL.print("[vk] 切换到: ");
        DEBUG_SERIAL.println(Modes.name());

        if (Modes.isMicrophone()) {
            // 切换为麦克风模式：暂停 STT，音频直通 USB
            DEBUG_SERIAL.println("[vk] 电脑可在音频设置中选择此设备作为麦克风");
        } else {
            // 切换为 Voice Keyboard 模式：恢复 STT
            DEBUG_SERIAL.println("[vk] 恢复语音识别输入模式");
        }
    }

    // ── 模式一：Voice Keyboard ────────────────────────────────
    if (Modes.isVoiceKeyboard()) {
        // 阶段一（当前）：从硬件 UART 读取模拟 STT 结果
        // 阶段二（待开发）：从 BLE 接收 nRF52840 音频 → 调用 STT API
        if (DEBUG_SERIAL.available()) {
            String line = DEBUG_SERIAL.readStringUntil('\n');
            line.trim();
            if (line.length() > 0) {
                DEBUG_SERIAL.println("[vk] 收到: " + line);
                dispatch(line, Keyboard, AgentSerial);
            }
        }
    }

    // ── 模式二：Microphone ────────────────────────────────────
    if (Modes.isMicrophone()) {
        // 阶段三（待开发）：
        //   1. 从 BLE 收取 nRF52840 的 PCM 数据
        //   2. 写入 USB UAC 端点：UsbMic.write(pcm_data, len)
        //   电脑收到后像普通麦克风一样使用
    }
}
