# Voice Keyboard

将语音实时转换为文字，直接输入到电脑任意输入框，并支持语音触发快捷键。

---

## 项目背景

市面上的无线麦克风（发射器 + 接收器）只做到了音频传输这一层。接收器插到电脑上，电脑收到的是音频流，用户还是要自己打字。

这个项目想往前再走几步：

```
传统无线麦克风：  说话 → 接收器 → 电脑听到声音

Voice Keyboard：  说话 → 接收器 → 语音识别 → 文字直接打进输入框
                                             → 特殊指令触发快捷键
```

接收器不再只是音频中转，而是变成一个「语音转键盘」的智能设备。

---

## 整体架构

```
┌─────────────┐    2.4G RF / 蓝牙    ┌──────────────────────────┐
│  无线麦克风  │ ──────────────────▶ │      接收器（ESP32-S3）    │
│   发射器     │                     │                          │
└─────────────┘                     │  ┌─────────────────────┐ │
                                    │  │  语音识别（STT）     │ │
                                    │  │  阿里云 NLS / Whisper│ │
                                    │  └──────────┬──────────┘ │
                                    │             │            │
                                    │  ┌──────────▼──────────┐ │
                                    │  │   USB 复合设备       │ │
                                    │  │  HID（快捷键）       │ │
                                    │  │  CDC 串口（文字）    │ │
                                    │  └──────────┬──────────┘ │
                                    └─────────────┼────────────┘
                                                  │ USB-C
                                    ┌─────────────▼────────────┐
                                    │       PC / Mac / Linux   │
                                    │                          │
                                    │  ┌──────────────────┐   │
                                    │  │   Agent（后台）   │   │
                                    │  │  读串口 → 打字    │   │
                                    │  └──────────────────┘   │
                                    │                          │
                                    │   任意输入框 ← 文字输入  │
                                    └──────────────────────────┘
```

---

## 核心技术选型

### 为什么用 USB HID + CDC 复合设备，而不是纯 HID 键盘

USB HID 键盘协议发送的是**按键码（keycode）**，不是字符。`A` 键有 keycode，`Ctrl` 键有 keycode，但**汉字没有 keycode**。所以纯 HID 键盘无法直接输入中文。

解决方案：让接收器同时呈现两个 USB 接口：

| 接口 | 用途 | 原因 |
|------|------|------|
| HID Keyboard | 发送快捷键 | 快捷键都是标准按键，有 keycode |
| CDC 串口 | 发送文字内容 | 串口可以传任意 Unicode 字符串 |

ESP32-S3 原生支持 USB Device 模式，可以同时呈现 HID + CDC，操作系统无需安装额外驱动。

---

### 为什么需要 PC Agent，而不是纯硬件

CDC 串口把文字送到电脑后，还需要一个程序把文字"打进"当前输入框。这件事操作系统提供了专门的 API，比任何硬件模拟都更可靠。

Agent 是一个极小的后台程序（打包后 < 15MB），开机自启，系统托盘常驻，用户感知不到它的存在。

---

### 为什么不直接用 pynput.type() 输入中文（macOS）

测试发现，在 macOS 上用 pynput 逐字发送按键事件时，若系统开着中文输入法，英文字母会被输入法拦截转换，导致中英文混排乱码：

```
期望：Voice Keyboard 项目
实际：V里侧Kkeyboard项目
```

根本原因：pynput 发的是键盘事件，会经过系统输入法（IME）处理层。

---

### 三平台打字方案

各平台采用不同的系统级 API，**完全绕过 IME**，逐字输出任意 Unicode 字符：

#### macOS — Quartz CGEvent

```python
evt = Quartz.CGEventCreateKeyboardEvent(src, 0, key_down)
Quartz.CGEventKeyboardSetUnicodeString(evt, len(char), char)
Quartz.CGEventPost(Quartz.kCGHIDEventTap, evt)
```

`CGEventKeyboardSetUnicodeString` 直接把 Unicode 字符写进键盘事件，绕过键盘布局映射和 IME，系统收到的就是字符本身。依赖 `pyobjc-framework-Quartz`，macOS 自带框架，无需额外系统安装。

#### Windows — SendInput + KEYEVENTF_UNICODE

```python
inp = _INPUT(type=INPUT_KEYBOARD,
             ki=_KEYBDINPUT(wVk=0, wScan=ord(char), dwFlags=KEYEVENTF_UNICODE))
user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(_INPUT))
```

`KEYEVENTF_UNICODE` 标志告诉 Windows：这是一个 Unicode 字符，不是物理按键。Windows 直接把字符发给当前焦点窗口的消息队列，不经过 IME。通过 `ctypes` 调用 Win32 API，**零额外依赖**。

#### Linux — pynput + X11 XTest

```python
for char in text:
    _kb.type(char)
    time.sleep(0.012)
```

pynput 在 Linux 底层走 X11 XTest 扩展，逐字发送 Unicode 键盘事件。XTest 是 X11 标准扩展，无需额外安装。

---

### 语音识别（STT）选型依据

| 方案 | 延迟 | 中文 | 离线 | 推荐场景 |
|------|------|------|------|---------|
| 阿里云 NLS | 200–400ms | 最优，支持方言 | 否 | 中文为主，生产环境 |
| 腾讯云 ASR | 300–500ms | 优 | 否 | 中文备选 |
| Azure Speech | 300–500ms | 良 | 否 | 国际化场景 |
| Whisper.cpp | < 100ms（本地） | 良 | 是 | 隐私敏感，离线场景 |

当前 MVP 阶段 STT 模块尚未接入，由模拟器替代。

---

## 当前状态

### 已完成

- [x] PC Agent 核心打字模块（macOS / Windows / Linux 三平台逐字输入）
- [x] 串口读取模块（自动识别 ESP32 设备，断线自动重连）
- [x] 语音指令 → 快捷键映射（支持运行时注册）
- [x] 开机自启动注册（三平台，`--install` / `--uninstall`）
- [x] ESP32 模拟器（macOS / Linux 无硬件联调）
- [x] 协议设计（`TEXT:` / `CMD:` 串口协议）
- [x] ESP32-S3 固件框架（USB HID + CDC 复合设备 + 路由逻辑）

### 待开发

#### STT 接入
- [ ] 阿里云 NLS 流式语音识别接入（`agent/stt.py`）
- [ ] Whisper.cpp 本地离线方案接入
- [ ] 流式识别边说边出字（partial result 处理）

#### ESP32-S3 固件
- [ ] 无线麦克风接收（2.4G RF 或蓝牙音频）
- [ ] 音频采集与预处理（降噪、增益）
- [ ] Wi-Fi 配网（Captive Portal 或蓝牙配对）
- [ ] 设备状态 LED 指示

#### Agent 完善
- [ ] 快捷键配置文件（`commands.yaml`，用户可自定义）
- [ ] 系统托盘 UI（状态显示、开关控制）
- [ ] Windows 模拟器（pty 替代方案，当前模拟器仅支持 Unix）

#### 打包发布
- [ ] PyInstaller 打包脚本（输出单文件 exe / app）
- [ ] macOS 辅助功能权限引导
- [ ] Windows 代码签名（避免 Defender 误报）

---

## 本地测试

### 环境要求

| 平台 | 要求 |
|------|------|
| macOS | Python 3.11+，macOS 12+ |
| Windows | Python 3.11+，Windows 10+ |
| Linux | Python 3.11+，X11 桌面环境 |

### 安装

```bash
git clone https://github.com/wangqioo/voice-keyboard.git
cd voice-keyboard
```

**macOS / Linux：**
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

**Windows（命令提示符）：**
```bat
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

---

### macOS 测试

> **首次运行必须授权辅助功能：**
> 系统设置 → 隐私与安全性 → 辅助功能 → 添加终端（或打包后的 .app）→ 开启
> 授权一次后永久生效。

**第一步：验证打字模块**（最简单，推荐先跑这个）

```bash
# 把光标点进任意输入框，然后运行：
python test/test_typing.py
```

等 3 秒，输入框内会逐字打出中英文混排测试文本，并触发一次「保存」快捷键。

**第二步：完整串口联调**（模拟真实 ESP32）

开两个终端：

```bash
# 终端 1 — 启动模拟器，记下打印的串口路径
python test/simulate_device.py
# 示例输出：[sim] 虚拟串口: /dev/ttys009
```

```bash
# 终端 2 — 把路径替换成上面打印的
python -m agent.main --port /dev/ttys009
```

把光标点进任意输入框，等 3 秒，文字逐字打出。

**注册开机自启动：**

```bash
python -m agent.main --install
# 之后开机自动运行，无需手动启动
```

---

### Windows 测试

> **首次运行会弹出 UAC 弹窗**，点「是」即可，只弹一次。

**第一步：验证打字模块**

```bat
# 把光标点进任意输入框，然后运行：
python test\test_typing.py
```

等 3 秒，输入框内会逐字打出中英文混排测试文本。

**第二步：完整串口联调**

Windows 暂无虚拟串口模拟器（`pty` 是 Unix 专有）。
有以下两种方式替代：

- **方式一（推荐）：直接接 ESP32-S3 硬件**，烧录固件后插入 USB，Agent 会自动识别并连接。
- **方式二：使用 [com0com](https://com0com.sourceforge.net/)** 创建虚拟 COM 口对，再用串口调试工具（如 PuTTY）向其中一个口发送测试数据。

```bat
# 指定串口运行 Agent（COM 口编号以设备管理器为准）
python -m agent.main --port COM3
```

**注册开机自启动：**

```bat
python -m agent.main --install
```

---

### Linux 测试

> 需要 X11 桌面环境（Wayland 下 pynput XTest 不可用）。

**第一步：验证打字模块**

```bash
# 把光标点进任意输入框，然后运行：
python test/test_typing.py
```

**第二步：完整串口联调**（与 macOS 步骤相同，Linux 同样支持 pty）

```bash
# 终端 1
python test/simulate_device.py
# 示例输出：[sim] 虚拟串口: /dev/pts/3
```

```bash
# 终端 2
python -m agent.main --port /dev/pts/3
```

**注册开机自启动（GNOME / KDE 均支持）：**

```bash
python -m agent.main --install
# 写入 ~/.config/autostart/voice-keyboard.desktop
```

---

## 串口协议

ESP32 通过 CDC 串口向 Agent 发送文本，每条消息一行：

| 格式 | 含义 | 示例 |
|------|------|------|
| `TEXT:<内容>` | 打字输出 | `TEXT:今天天气真不错` |
| `CMD:<指令>` | 触发快捷键 | `CMD:保存` |

### 内置指令表

| 指令 | macOS | Windows |
|------|-------|---------|
| 截图 | Cmd+Shift+4 | Win+Shift+S |
| 保存 | Cmd+S | Ctrl+S |
| 复制 | Cmd+C | Ctrl+C |
| 粘贴 | Cmd+V | Ctrl+V |
| 撤销 | Cmd+Z | Ctrl+Z |
| 全选 | Cmd+A | Ctrl+A |
| 新标签 | Cmd+T | Ctrl+T |
| 关闭标签 | Cmd+W | Ctrl+W |
| 回车 | Enter | Enter |
| 删除 | Backspace | Backspace |

---

## License

MIT
