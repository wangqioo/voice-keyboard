#pragma once
#include "USBHIDKeyboard.h"

// 三键组合快捷键（修饰键1 + 修饰键2 + 普通键）
struct Shortcut {
    const char* name;
    uint8_t     mod1;   // 第一个修饰键，0 表示无
    uint8_t     mod2;   // 第二个修饰键，0 表示无
    uint8_t     key;    // 普通键
};

// 无 Agent 时走 HID 直接触发
// 修饰键统一用 Ctrl（Windows/Linux），macOS 用户装 Agent 后由 Agent 处理 Cmd 版本
static const Shortcut SHORTCUTS[] = {
    {"保存",    KEY_LEFT_CTRL,  0,               's'},
    {"复制",    KEY_LEFT_CTRL,  0,               'c'},
    {"粘贴",    KEY_LEFT_CTRL,  0,               'v'},
    {"撤销",    KEY_LEFT_CTRL,  0,               'z'},
    {"全选",    KEY_LEFT_CTRL,  0,               'a'},
    {"新标签",  KEY_LEFT_CTRL,  0,               't'},
    {"关闭标签",KEY_LEFT_CTRL,  0,               'w'},
    {"截图",    KEY_LEFT_GUI,   KEY_LEFT_SHIFT,  's'},  // Win+Shift+S
    {"回车",    0,              0,               KEY_RETURN},
    {"删除",    0,              0,               KEY_BACKSPACE},
    {"空格",    0,              0,               ' '},
};

static const int SHORTCUT_COUNT = sizeof(SHORTCUTS) / sizeof(SHORTCUTS[0]);

// 按名称触发快捷键，返回是否命中
inline bool triggerShortcut(const String& name, USBHIDKeyboard& kb) {
    for (int i = 0; i < SHORTCUT_COUNT; i++) {
        if (name == SHORTCUTS[i].name) {
            if (SHORTCUTS[i].mod1) kb.press(SHORTCUTS[i].mod1);
            if (SHORTCUTS[i].mod2) kb.press(SHORTCUTS[i].mod2);
            kb.press(SHORTCUTS[i].key);
            delay(50);
            kb.releaseAll();
            return true;
        }
    }
    return false;
}
