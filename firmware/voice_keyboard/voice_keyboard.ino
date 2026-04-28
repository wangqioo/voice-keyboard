/**
 * Voice Keyboard — ESP32-S3 固件
 *
 * USB 复合设备：HID 键盘 + CDC 串口
 *
 * 烧录配置（Arduino IDE）：
 *   Board:              ESP32S3 Dev Module
 *   USB Mode:           USB-OTG (TinyUSB)
 *   USB CDC On Boot:    Disabled
 *   Upload Mode:        UART0 / Hardware CDC
 *
 * 调试/测试：
 *   通过硬件 UART（TX=43, RX=44）发送 TEXT:/CMD: 协议模拟 STT 输出
 *   例：TEXT:Hello World\n  或  CMD:保存\n
 */

#include "USB.h"
#include "USBHIDKeyboard.h"
#include "USBCDC.h"
#include "text_router.h"

USBHIDKeyboard Keyboard;
USBCDC         AgentSerial;   // CDC 串口，Agent 从这里读文字

// 硬件 UART：调试输出 + 测试时模拟 STT 输入
// ESP32-S3 默认 UART0：TX=GPIO43, RX=GPIO44
#define DEBUG_SERIAL Serial0

void setup() {
    DEBUG_SERIAL.begin(115200);

    // 初始化 USB 复合设备
    USB.begin();
    Keyboard.begin();
    AgentSerial.begin(115200);

    DEBUG_SERIAL.println("[vk] Voice Keyboard ready");
    DEBUG_SERIAL.println("[vk] 发送 TEXT:<内容> 或 CMD:<指令> 进行测试");
}

void loop() {
    // ── 阶段一（当前）：从硬件 UART 读取 STT 结果（测试用）
    // ── 阶段二（待开发）：从 STT 模块（阿里云 NLS / Whisper）获取结果
    if (DEBUG_SERIAL.available()) {
        String line = DEBUG_SERIAL.readStringUntil('\n');
        line.trim();
        if (line.length() > 0) {
            DEBUG_SERIAL.println("[vk] 收到: " + line);
            dispatch(line, Keyboard, AgentSerial);
        }
    }
}
