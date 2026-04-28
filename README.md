# Voice Keyboard

无线语音输入设备，支持两种模式，按键一键切换：

- **Voice Keyboard 模式**：语音 → 实时识别 → 文字直接打进任意输入框，支持语音触发快捷键
- **麦克风模式**：音频直通，电脑将其识别为标准 USB 麦克风，Zoom、微信、录音软件直接使用

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

## 硬件设计

### 发射端（挂在身上）

| 组件 | 型号 | 说明 |
|------|------|------|
| 主控 | nRF52840 | 低功耗蓝牙 SoC，BLE 5.0 |
| 麦克风 | MSM261D3526H1CPM | PDM 数字 MEMS 麦克风 |
| 电池 | 500mAh LiPo | 续航约 50 小时 |

电路参考 [Seeed XIAO nRF52840 Sense](https://wiki.seeedstudio.com/XIAO-BLE-Sense-PDM-Usage/) 开源原理图，该板已集成 nRF52840 + MSM261D3526H1CPM，PDM 接口直连，无需外部音频芯片。

**为什么选 nRF52840 而不是 ESP32：**
- ESP32 工作电流 80–150mA，500mAh 电池只能撑 3–4 小时
- nRF52840 工作电流约 12–18mA（含 BLE + PDM 采集），同等电池可用 50 小时以上

**为什么选 PDM 麦克风：**
- nRF52840 内置 PDM 控制器和硬件降采样滤波器，2 根线（CLK + DATA）直连，无需外部音频芯片
- 语音识别只需 16kHz 单声道，PDM 完全满足，成本和体积均优于 I2S 方案

### 接收端（插在电脑上）

| 组件 | 型号 | 说明 |
|------|------|------|
| 主控 | ESP32-S3 | 原生 USB OTG，支持 BLE 5.0 |
| 接口 | USB-C | 连接电脑，USB 由电脑供电 |
| 按键 | 板载 BOOT 键（GPIO0） | 切换 Voice Keyboard / 麦克风模式 |

**为什么选 ESP32-S3：**
- 原生 USB Device 模式，可同时呈现 HID 键盘 + CDC 串口 + UAC 麦克风（三合一复合设备）
- 支持 BLE 5.0，可作为 BLE Central 接收 nRF52840 发来的音频
- 接收端插在电脑上有 USB 供电，功耗不是问题

---

## 整体架构

```
┌──────────────────────────────┐
│  发射端（挂在身上）            │
│                              │
│  MSM261D3526H1CPM            │
│  PDM 麦克风                  │
│       │ PDM                  │
│  nRF52840                    │
│  ├─ PDM 采集（16kHz mono）   │
│  └─ BLE GATT 发送 PCM 数据   │
└──────────────┬───────────────┘
               │ BLE 5.0 自定义 GATT
               │ PCM 16kHz mono
┌──────────────▼───────────────┐
│  接收端（插在电脑上）          │
│                              │
│  ESP32-S3                    │
│  ├─ BLE Central 接收音频     │
│  ├─ [按键] 模式切换           │
│  │                           │
│  │  模式一：Voice Keyboard   │
│  │  ├─ STT 语音识别          │
│  │  └─ USB 复合设备          │
│  │      ├─ HID  → 快捷键/英文│
│  │      └─ CDC  → 中文 → Agent
│  │                           │
│  │  模式二：麦克风            │
│  │  └─ USB UAC              │  → 电脑识别为标准麦克风
│  │      （Zoom/微信/录音等）  │
└──────────────┬───────────────┘
               │ USB-C
┌──────────────▼───────────────┐
│  PC / Mac / Linux            │
│                              │
│  Agent（后台，开机自启）       │  ← Voice Keyboard 模式使用
│  读 CDC 串口 → 逐字打字       │
│                              │
│  任意输入框 ← 文字输入         │
└──────────────────────────────┘
```

### 模式说明

| 模式 | 触发 | LED | 效果 |
|------|------|-----|------|
| Voice Keyboard | 默认 / 按键切换 | 常亮 | 语音 → STT → 文字打进输入框 |
| 麦克风 | 按键切换 | 慢闪 | 音频直通，电脑当普通麦克风用 |

---

## 核心技术选型

### BLE 音频传输：自定义 GATT 传 PCM 裸数据

nRF52840 不支持 LE Audio（运行 LC3 编解码算力不足，需要 nRF5340），采用自定义 GATT Service 传输 PCM 裸数据：

- 采样率：16kHz，单声道，16bit → 码率 256kbps
- BLE 5.0 有效带宽约 1.4Mbps，256kbps 仅占 18%，余量充足
- MTU 协商到 128–250 字节，减少数据包碎片

nRF52840 与 ESP32-S3 均支持 BLE 5.0 标准协议，完全互通，无兼容性问题。

### USB 复合设备：HID + CDC

USB HID 键盘只能发**按键码**，汉字没有 keycode，无法直接输入中文。解决方案：接收端同时呈现两个 USB 接口：

| 接口 | 用途 |
|------|------|
| HID Keyboard | 快捷键触发 + 纯英文输入（无 Agent 也可用） |
| CDC 串口 | 中文文字传输给 Agent |

**两种模式自动共存：**
- **未安装 Agent**：纯 HID 模式，英文正常打，快捷键正常触发
- **已安装 Agent**：HID 负责快捷键，CDC 负责中文输入

### PC Agent：三平台逐字输入（均已验证）

CDC 串口把文字送到电脑后，Agent 调用系统 API 逐字输入，**完全绕过输入法（IME）**：

| 平台 | API | 原理 |
|------|-----|------|
| macOS | Quartz `CGEventKeyboardSetUnicodeString` | 直接把 Unicode 字符写进键盘事件，绕过 IME |
| Windows | Win32 `SendInput` + `KEYEVENTF_UNICODE` | Unicode 字符直发焦点窗口消息队列，绕过 IME |
| Linux | pynput + X11 XTest | XTest 扩展逐字发送 Unicode 键盘事件 |

> macOS 直接用 pynput 打字会被输入法拦截，导致中英文混排乱码（已验证），故改用 Quartz API。

Agent 打包后 < 15MB，开机自启，系统托盘常驻，用户无感。首次运行需授权一次系统权限。

### STT 选型

| 方案 | 延迟 | 中文 | 离线 | 推荐场景 |
|------|------|------|------|---------|
| 阿里云 NLS | 200–400ms | 最优，支持方言 | 否 | 中文为主，生产环境 |
| 腾讯云 ASR | 300–500ms | 优 | 否 | 中文备选 |
| Azure Speech | 300–500ms | 良 | 否 | 国际化场景 |
| Whisper.cpp | < 100ms（本地） | 良 | 是 | 离线 / 隐私场景 |

---

## 开发计划

### 阶段一：PC Agent（已完成）

- [x] 核心打字模块（macOS / Windows / Linux 三平台逐字输入，均已验证）
- [x] 串口读取模块（自动识别设备，断线自动重连）
- [x] 语音指令 → 快捷键映射（支持运行时注册）
- [x] 开机自启动注册（`--install` / `--uninstall`）
- [x] ESP32 模拟器（macOS / Linux 无硬件联调）
- [x] TEXT / CMD 串口协议设计

### 阶段二：ESP32-S3 固件（进行中）

- [x] USB HID + CDC 复合设备框架
- [x] 文字路由逻辑（ASCII → HID，中文 → CDC，CMD → HID 快捷键）
- [x] 模式切换框架（Voice Keyboard / 麦克风，按键 + LED 指示）
- [x] USB UAC 麦克风接口框架（Adafruit TinyUSB）
- [ ] BLE Central：扫描并连接 nRF52840
- [ ] BLE GATT Client：接收 PCM 音频数据
- [ ] 音频缓冲与预处理
- [ ] STT 接入（阿里云 NLS 流式识别）
- [ ] UAC 音频直通：BLE 收到的 PCM 写入 USB 音频端点
- [ ] Wi-Fi 配网（Captive Portal）
- [ ] 设备状态 LED 优化

### 阶段三：nRF52840 固件（待开发）

- [ ] PDM 麦克风采集（16kHz mono，参考 XIAO nRF52840 Sense 示例）
- [ ] BLE GATT Server：自定义 Service + Characteristic
- [ ] PCM 数据分包发送（MTU 协商 128–250 字节）
- [ ] 连接状态指示（LED）
- [ ] 低功耗优化（连接间隔调优）

### 阶段四：Agent 完善（待开发）

- [ ] 快捷键配置文件（`commands.yaml`，用户可自定义）
- [ ] 系统托盘 UI（状态显示、开关控制）
- [ ] Windows 模拟器（pty 替代方案）

### 阶段五：打包发布（待开发）

- [ ] PyInstaller 打包脚本（单文件 exe / app）
- [ ] macOS 辅助功能权限引导
- [ ] Windows 代码签名（避免 Defender 误报）
- [ ] PCB 设计与打样

---

## PC Agent 本地测试

### 环境要求

| 平台 | Python | 系统版本 | 备注 |
|------|--------|---------|------|
| macOS | 3.11+ | macOS 12+ | 需授权辅助功能 |
| Windows | 3.11+ | Windows 10+ | 需通过 UAC 弹窗 |
| Linux | 3.11+ | 主流发行版 | 需 X11 桌面环境 |

> **关于 `python` 命令：** macOS / Linux 不一定有 `python` 命令，本项目统一使用虚拟环境内的 Python，无需关心系统命令是否存在。

### 安装

```bash
git clone https://github.com/wangqioo/voice-keyboard.git
cd voice-keyboard
```

**macOS / Linux：**
```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

**Windows（命令提示符）：**
```bat
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
```

> `pyobjc-framework-Quartz` 是 macOS 专属依赖，Windows / Linux 安装时自动跳过。

---

### macOS 测试

> **首次运行前必须授权辅助功能（只做一次）：**
> 系统设置 → 隐私与安全性 → 辅助功能 → 点击 `+` → 选择「终端」→ 打开开关
> 不授权的话程序正常运行，但不会有任何文字输出。

**验证打字模块：**

把光标点进任意输入框，然后运行：

```bash
.venv/bin/python test/test_typing.py
```

等 3 秒，输入框内逐字打出中英文混排文本，并触发一次「保存」快捷键。

**完整串口联调（模拟 ESP32）：**

```bash
# 终端 1
.venv/bin/python test/simulate_device.py
# 示例输出：[sim] 虚拟串口: /dev/ttys009

# 终端 2（路径替换为终端 1 打印的实际值）
.venv/bin/python -m agent.main --port /dev/ttys009
```

**注册开机自启动：**
```bash
.venv/bin/python -m agent.main --install
# 撤销：.venv/bin/python -m agent.main --uninstall
```

---

### Windows 测试

> **首次运行会弹出 UAC 弹窗**，点「是」即可，只弹一次。
> **注意：** Windows 路径用反斜杠 `\`，不是 `/`。

**验证打字模块：**

把光标点进任意输入框，然后运行：

```bat
.venv\Scripts\python test\test_typing.py
```

等 3 秒，输入框内逐字打出中英文混排文本，并触发一次「保存」快捷键（Ctrl+S）。

**完整串口联调：**

Windows 不支持 `pty` 虚拟串口，有两种替代方式：
- **方式一（推荐）：** 直接接 ESP32-S3 硬件，烧录固件后插入 USB，Agent 自动识别连接
- **方式二：** 安装 [com0com](https://com0com.sourceforge.net/) 创建虚拟 COM 口对，用 PuTTY 向其中一个口发送测试数据

```bat
rem COM 口编号在设备管理器 → 端口 中查看
.venv\Scripts\python -m agent.main --port COM3
```

**注册开机自启动：**
```bat
.venv\Scripts\python -m agent.main --install
rem 撤销：.venv\Scripts\python -m agent.main --uninstall
```

---

### Linux 测试

> 需要 X11 桌面环境，Wayland 下 pynput XTest 不可用，登录时请选择 X11 会话。

**验证打字模块：**

```bash
.venv/bin/python test/test_typing.py
```

**完整串口联调（步骤与 macOS 相同）：**

```bash
# 终端 1
.venv/bin/python test/simulate_device.py
# 示例输出：[sim] 虚拟串口: /dev/pts/3

# 终端 2
.venv/bin/python -m agent.main --port /dev/pts/3
```

**注册开机自启动：**
```bash
.venv/bin/python -m agent.main --install
# 写入 ~/.config/autostart/voice-keyboard.desktop
# 撤销：.venv/bin/python -m agent.main --uninstall
```

---

## ESP32-S3 固件烧录

Arduino IDE 配置：

| 选项 | 值 |
|------|-----|
| Board | ESP32S3 Dev Module |
| USB Mode | USB-OTG (TinyUSB) |
| USB CDC On Boot | Disabled |
| Upload Mode | UART0 / Hardware CDC |

烧录后通过硬件 UART（TX=GPIO43, RX=GPIO44）发送测试数据验证路由：

```
TEXT:Hello World  → HID 直接打出（纯 ASCII）
TEXT:你好世界     → CDC 串口转发给 Agent
CMD:保存          → HID 触发 Ctrl+S
```

---

## nRF52840 固件开发

**开发工具链：** nRF Connect SDK + VS Code（nRF5 SDK 已停止维护，不要用）

**原型开发板：** Seeed XIAO nRF52840 Sense（已集成 MSM261D3526H1CPM PDM 麦克风，有现成示例代码）

**参考项目：**
- [BLE_Audio_Stream_NRF52840](https://github.com/aapatni/BLE_Audio_Stream_NRF52840) — BLE GATT 音频流参考实现
- [Seeed XIAO nRF52840 Sense PDM 示例](https://wiki.seeedstudio.com/XIAO-BLE-Sense-PDM-Usage/) — PDM 麦克风采集参考

---

## 串口协议

ESP32-S3 通过 CDC 串口向 Agent 发送消息，每条消息一行：

| 格式 | 含义 | 示例 |
|------|------|------|
| `TEXT:<内容>` | 打字输出 | `TEXT:今天天气真不错` |
| `CMD:<指令>` | 触发快捷键 | `CMD:保存` |

**固件路由规则：**
- `CMD:` → 始终走 HID，无 Agent 也可用
- `TEXT:` 纯 ASCII → 走 HID 直接打，无 Agent 也可用
- `TEXT:` 含中文 → 走 CDC 串口发给 Agent

### 内置指令表

| 指令 | macOS | Windows / Linux |
|------|-------|----------------|
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
| 空格 | Space | Space |

---

## License

MIT
