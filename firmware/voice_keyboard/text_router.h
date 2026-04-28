#pragma once
#include "USBHIDKeyboard.h"
#include "USBCDC.h"
#include "shortcuts.h"

// UTF-8 中只要出现字节 > 127 就说明有非 ASCII 字符（中文、全角标点等）
static bool isAsciiOnly(const String& text) {
    for (size_t i = 0; i < text.length(); i++) {
        if ((uint8_t)text[i] > 127) return false;
    }
    return true;
}

// 解析一行串口协议并路由
//
// 协议格式：
//   TEXT:<内容>  → 打字输出
//   CMD:<指令>   → 快捷键触发
//
// 路由规则：
//   CMD        → 无论是否有 Agent，优先走 HID 快捷键
//   TEXT ASCII → 无 Agent 也能用，HID 直接打英文
//   TEXT 含中文 → 走 CDC 发给 Agent（无 Agent 时数据被忽略）
static void dispatch(const String& line, USBHIDKeyboard& kb, USBCDC& agentSerial) {
    if (line.startsWith("CMD:")) {
        String cmd = line.substring(4);
        cmd.trim();
        if (!triggerShortcut(cmd, kb)) {
            // 未知指令同时转发给 Agent 尝试处理
            agentSerial.println("CMD:" + cmd);
        }

    } else if (line.startsWith("TEXT:")) {
        String text = line.substring(5);
        text.trim();
        if (text.length() == 0) return;

        if (isAsciiOnly(text)) {
            // 纯英文/数字/ASCII 标点 → HID 直接打，无 Agent 也能用
            kb.print(text);
        } else {
            // 含中文或全角字符 → CDC 串口转给 Agent
            agentSerial.println("TEXT:" + text);
        }
    }
    // 其他格式忽略
}
