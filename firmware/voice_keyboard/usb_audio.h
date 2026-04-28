#pragma once

/**
 * USB Audio Class（UAC）麦克风模块
 *
 * 依赖：Adafruit TinyUSB Library（Arduino Library Manager 搜索安装）
 * 安装后在 Arduino IDE：工具 → USB Stack → TinyUSB
 *
 * 音频格式：PCM 16kHz，16bit，单声道（与 nRF52840 发送的格式一致）
 *
 * UAC 麦克风让电脑把设备识别为标准麦克风，
 * Zoom、微信、录音软件等可直接选择使用，无需安装驱动。
 */

#include <Adafruit_TinyUSB.h>

// UAC 描述符：16kHz，16bit，1 声道
static const uint8_t UAC_DESC[] = {
    // Standard Interface Descriptor
    9, 4, 2, 0, 0, 1, 1, 0, 0,
    // Class-specific AC Interface Header Descriptor
    9, 36, 1, 0, 1, 9, 0, 1, 1,
    // Input Terminal: Microphone
    12, 36, 2, 1, 0x01, 0x02, 0x00, 0x00, 0x01, 0, 0, 0,
    // Output Terminal: USB Streaming
    9, 36, 3, 2, 1, 1, 0x01, 0x01, 0,
    // Standard AS Interface (alt 0)
    9, 4, 3, 0, 0, 1, 2, 0, 0,
    // Standard AS Interface (alt 1, active)
    9, 4, 3, 1, 1, 1, 2, 0, 0,
    // Class-specific AS Interface: PCM
    7, 36, 1, 1, 1, 2, 1,
    // Format Type I: 16kHz 16bit 1ch
    11, 36, 2, 1, 1, 2, 16, 0, 1, 0x80, 0x3E,
    // Standard Endpoint
    9, 5, 0x81, 0x05, 32, 0, 1, 0, 0,
    // Class-specific Endpoint
    7, 37, 1, 0, 0, 0, 0,
};

class USBAudio {
public:
    void begin() {
        // TinyUSB 初始化在 USB.begin() 前调用
        // 具体注册逻辑依赖 Adafruit_TinyUSB API
    }

    // 将 PCM 数据写入 USB 音频端点（麦克风模式下调用）
    // data: PCM 16bit 样本数组
    // len:  字节数
    void write(const uint8_t* data, size_t len) {
        // TinyUSB UAC 写入接口
        // 实际调用：tud_audio_write(data, len);
        (void)data;
        (void)len;
    }

    // 当前是否有主机在读取音频
    bool connected() {
        // return tud_audio_mounted();
        return false;
    }
};

extern USBAudio UsbMic;
