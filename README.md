# Voice Keyboard

语音直接打字，无需手动输入。说话即可在任意输入框输出文字，支持中文、英文、混排，支持语音触发快捷键，支持语音修改刚打出的内容。

---

## 两种使用方式

### 纯软件模式（今天就能用）

安装 Agent，接上任何麦克风，说话打字。适合已有麦克风的用户快速体验。

- 按住热键说话，松开自动识别并打字（Push-to-Talk）
- 兼容内置麦克风 / USB 麦克风 / Insta360 / 大疆 DJI Mic / 蓝牙耳机等
- 按 API 用量计费（自填 API Key，或订阅本服务）

### 硬件模式（完整体验）

购买 Voice Keyboard 无线设备，**API 费用全免**，包含在硬件售价中。

- **全程不碰键盘**：佩戴发射端，开口即唤醒，停顿自动结束，文字打进输入框
- **低声细语也能用**：近讲麦克风贴近嘴巴（3–5cm），在会议室、图书馆、公共场所正常工作
- 一键切换普通 USB 麦克风模式，Zoom / 微信 / 录音软件直接使用

**为什么硬件能做到全程免按键，软件不行？**

普通麦克风离嘴 30cm+，背景噪音和人声混在一起，语音活动检测（VAD）容易误触发，所以软件模式必须用 PTT 手动控制。近讲麦克风信噪比极高，VAD 可以精准区分你的声音和环境声，实现真正的自动唤醒。

---

## 功能列表

| 功能 | 软件模式 | 硬件模式 |
|------|---------|---------|
| 语音打字（中英文混排） | ✅ PTT 按键触发 | ✅ 自动唤醒，免手动 |
| 低声细语 | ❌ 麦克风太远 | ✅ 近讲麦克风 |
| 语音触发快捷键（截图/保存/复制…） | ✅ | ✅ |
| 语音修改上一句话 | ✅ | ✅ |
| 作为普通 USB 麦克风使用 | ❌ | ✅ 一键切换 |
| 需要安装软件 | ✅ 必须 | ✅ 必须（中文输入） |
| API 费用 | 按量计费 | 全免 |

---

## 整体架构

```
┌─────────────────────────────┐
│  发射端（佩戴，挂在身上）      │
│                             │
│  PDM 麦克风（近讲）          │
│       │                     │
│  nRF52840                   │
│  ├─ PDM 采集（16kHz mono）  │
│  └─ BLE GATT 发送 PCM 数据  │
└─────────────┬───────────────┘
              │ BLE 5.0
┌─────────────▼───────────────┐
│  接收端（插在电脑 USB 口上）   │
│                             │
│  ESP32-S3                   │
│  ├─ BLE Central 收音频      │
│  ├─ [按键] 切换模式          │
│  │                          │
│  │  Voice Keyboard 模式     │
│  │  ├─ HID → 快捷键 / 英文  │
│  │  ├─ CDC → 中文 → Agent   │
│  │  └─ UAC → 音频 → Agent   │
│  │                          │
│  │  麦克风模式               │
│  │  └─ UAC → 电脑当普通麦克风│
└─────────────┬───────────────┘
              │ USB-C
┌─────────────▼───────────────┐
│  PC / Mac / Linux           │
│                             │
│  Agent（后台常驻）           │
│  ├─ VAD 检测语音边界         │
│  ├─ STT API 转录文字         │
│  ├─ 逐字打入当前输入框        │
│  └─ LLM 语音编辑上一句       │
└─────────────────────────────┘
```

---

## 核心技术说明

### 为什么 STT 由 Agent 做，而不是设备联网

设备本身**不连 WiFi，不做语音识别**。音频通过 USB 传到电脑，由 Agent 调用云端 STT API，结果打字输入。

这样设计的原因：
- 设备无需 WiFi 配置，换办公室 / 换热点对设备零感知
- STT 提供商和 API Key 在配置文件里随时切换，无需刷固件
- 电脑本身就有网络，是最可靠的网络来源

### 为什么中文不能用 HID 直接打

USB HID 键盘只能发按键码，汉字没有 keycode。解决方案：ESP32-S3 同时呈现两个 USB 接口：

| 接口 | 用途 |
|------|------|
| HID Keyboard | 英文打字 + 快捷键（无需 Agent） |
| CDC 串口 | 中文文字传给 Agent |

### Agent 打字如何绕过输入法

Agent 调用各平台系统级 API，把 Unicode 字符直接写进键盘事件，完全不经过输入法（IME）：

| 平台 | API |
|------|-----|
| macOS | Quartz `CGEventKeyboardSetUnicodeString` |
| Windows | Win32 `SendInput` + `KEYEVENTF_UNICODE` |
| Linux | pynput + X11 XTest |

> macOS 用 pynput 打字会被输入法拦截导致中英文乱码，这是换 Quartz API 的原因。

### BLE 音频传输

nRF52840 不支持 LE Audio（需要 nRF5340），采用自定义 GATT Service 传 PCM 裸数据：
- 格式：16kHz，单声道，16bit → 码率 256kbps
- BLE 5.0 有效带宽约 1.4Mbps，占用率仅 18%
- nRF52840 与 ESP32-S3 均支持 BLE 5.0，完全互通

### STT 提供商

| provider | 延迟 | 中文 | 控制台 |
|----------|------|------|--------|
| `zhipuai` | 500–800ms | ★★★ GLM-4-Voice | [智谱 AI](https://open.bigmodel.cn/) |
| `aliyun` | 200–400ms | ★★★ 支持方言 | [阿里云 NLS](https://nls-portal.console.aliyun.com/) |
| `volcengine` | 200–400ms | ★★★ 中文优化 | [火山引擎](https://console.volcengine.com/speech/service/16) |
| `openai` | 500–1000ms | ★★ 多语言 | [OpenAI](https://platform.openai.com/api-keys) |

> `zhipuai` 只需一个 API Key 同时覆盖 STT + LLM，适合快速上手。

### LLM 编辑提供商

| provider | 模型 | 控制台 |
|----------|------|--------|
| `zhipuai` | glm-4-flash（推荐，快且便宜） | [智谱 AI](https://open.bigmodel.cn/) |
| `openai` | gpt-4o-mini | [OpenAI](https://platform.openai.com/api-keys) |
| `aliyun` | qwen-turbo | [DashScope](https://dashscope.console.aliyun.com/) |
| `volcengine` | doubao-lite-4k | [火山引擎](https://console.volcengine.com/ark) |

---

## 硬件选型

### 发射端（佩戴）

| 组件 | 型号 | 说明 |
|------|------|------|
| 主控 | nRF52840 | BLE 5.0，工作电流 12–18mA，500mAh 电池可用 50h+ |
| 麦克风 | MSM261D3526H1CPM | PDM 数字 MEMS，2 根线直连，nRF52840 内置 PDM 控制器 |
| 电池 | 500mAh LiPo | 约 50 小时续航 |

电路参考 [Seeed XIAO nRF52840 Sense](https://wiki.seeedstudio.com/XIAO-BLE-Sense-PDM-Usage/)（已集成两者，有现成 PDM 示例）。

> 为什么不用 ESP32 做发射端：ESP32 工作电流 80–150mA，同等电池只能用 3–4 小时。

### 接收端（插电脑）

| 组件 | 型号 | 说明 |
|------|------|------|
| 主控 | ESP32-S3 | 原生 USB OTG，BLE 5.0，USB 复合设备支持 |
| 接口 | USB-C | 电脑供电，无需电池 |
| 按键 | GPIO0（板载 BOOT） | 切换 Voice Keyboard / 麦克风模式 |

---

## 开发进度

### Agent（已完成）

- [x] 三平台打字（macOS Quartz / Windows SendInput / Linux XTest）
- [x] 串口自动识别 + 断线重连
- [x] TEXT / CMD 协议路由
- [x] 语音指令 → 快捷键映射
- [x] 开机自启动（macOS LaunchAgent / Windows 注册表 / Linux .desktop）
- [x] Push-to-Talk 录音（ptt_key 按住说话）
- [x] 常开 VAD 模式（webrtcvad 检测语音边界）
- [x] STT 接入（智谱 GLM-4-Voice / 阿里云 NLS / 火山引擎 / OpenAI Whisper）
- [x] LLM 语音编辑（edit_key 按住说修改指令，自动擦掉原文打入新文字）
- [x] 多麦克风支持（任意 USB / 内置 / 蓝牙设备）
- [x] `--no-serial` 纯软件模式
- [x] `--list-devices` 枚举麦克风
- [x] 全局 Backspace 监听，实时同步文字账本（30s 窗口，避免其他 App 误扣）
- [x] 鼠标点击检测，光标移动后自动切换行选择纠错模式
- [x] 行选择纠错（Home→Shift+End→剪贴板）：鼠标乱点后仍能准确拿到当前行原文
- [x] .env 文件配置支持（与 python-dotenv 兼容）

### ESP32-S3 固件（进行中）

- [x] USB HID + CDC 复合设备
- [x] 文字路由（ASCII→HID，中文→CDC，CMD→HID）
- [x] 模式切换（Voice Keyboard / 麦克风，按键 + LED）
- [x] USB UAC 麦克风接口框架
- [ ] BLE Central：扫描连接 nRF52840
- [ ] BLE GATT Client：接收 PCM 数据
- [ ] UAC 音频直通（BLE PCM → USB 音频端点）

### nRF52840 固件（待开发）

- [ ] PDM 麦克风采集（16kHz mono）
- [ ] BLE GATT Server + 自定义 Service
- [ ] PCM 分包发送（MTU 128–250 字节）
- [ ] 低功耗优化

### 待开发

- [ ] 快捷键自定义配置文件
- [ ] 系统托盘 UI
- [ ] PyInstaller 打包（单文件 exe / app）
- [ ] PCB 设计与打样

---

## 安装与使用

### 环境要求

| 平台 | Python | 备注 |
|------|--------|------|
| macOS | 3.11+ | 需授权辅助功能权限 |
| Windows | 3.11+ | 首次运行需通过 UAC；建议用 venv 避免权限问题 |
| Linux | 3.11+ | 需 X11 会话（非 Wayland） |

> **VAD 模式（常开自动检测）** 依赖 `webrtcvad`，目前仅有 Python 3.12 及以下的预编译包。Python 3.13+ 请使用 PTT 模式（`audio.mode: ptt`），VAD 模式暂不可用。

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

**Windows：**
```bat
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
```

> `pyobjc-framework-Quartz` 是 macOS 专属依赖，Windows / Linux 安装时自动跳过。

### 配置

**方式一：config.yaml（推荐）**

```bash
cp config.yaml.example config.yaml
# 编辑 config.yaml，填入 STT / LLM 的 API Key
```

**方式二：.env 文件（适合部署 / 不想维护 YAML 的场景）**

```bash
cp .env.example .env
# 只需填一行，STT 和 LLM 共用同一个 Key
# GLM_API_KEY=你的智谱AI_API_Key
```

智谱 AI 一个 Key 即可同时启用 STT（GLM-4-Voice）和 LLM（GLM-4-Flash）。

查看可用麦克风：

```bash
.venv/bin/python -m agent.main --list-devices  # macOS / Linux
.venv\Scripts\python -m agent.main --list-devices  # Windows
```

### 启动

**纯软件模式（无 ESP32 硬件）：**
```bash
.venv/bin/python -m agent.main --no-serial
```

**有 ESP32 硬件：**
```bash
.venv/bin/python -m agent.main
```

### 热键说明

| 热键 | 默认按键 | 功能 |
|------|---------|------|
| `ptt_key` | 右 Alt / Option | 按住说话，松开识别打字 |
| `edit_key` | 右 Ctrl | 按住说修改指令，松开自动修改上一句 |

热键可在 `config.yaml` 中修改。硬件模式建议改为 `mode: vad`（无需按键，自动唤醒）。

### 语音编辑示例

| 你说的 | 效果 |
|--------|------|
| "把会议改成会谈" | 替换关键词 |
| "去掉最后一句" | 删除末尾内容 |
| "在后面加上请及时回复" | 追加文字 |
| "改成更正式的表达" | LLM 润色重写 |

### 注册开机自启动

```bash
.venv/bin/python -m agent.main --install    # 注册
.venv/bin/python -m agent.main --uninstall  # 撤销
```

---

## 测试

### macOS

> **首次运行前：** 系统设置 → 隐私与安全性 → 辅助功能 → 添加终端并打开开关。

**验证打字：** 光标点进任意输入框，运行：
```bash
.venv/bin/python test/test_typing.py
```
等 3 秒，输入框内逐字打出中英文混排测试文本。

**模拟 ESP32 串口联调：**
```bash
# 终端 1
.venv/bin/python test/simulate_device.py
# 输出：[sim] 虚拟串口: /dev/ttys009

# 终端 2（填入终端 1 打印的实际路径）
.venv/bin/python -m agent.main --port /dev/ttys009
```

### Windows

> **首次运行：** UAC 弹窗点「是」即可。

```bat
.venv\Scripts\python test\test_typing.py
```

Windows 无虚拟串口，串口联调请直接接 ESP32-S3 硬件，或用 [com0com](https://com0com.sourceforge.net/) 创建虚拟 COM 口对。

### Linux

> 需要 X11 会话，Wayland 下 XTest 不可用。

```bash
.venv/bin/python test/test_typing.py

# 模拟串口联调
.venv/bin/python test/simulate_device.py   # 终端 1
.venv/bin/python -m agent.main --port /dev/pts/3  # 终端 2
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

烧录后通过硬件 UART（TX=GPIO43, RX=GPIO44）发送测试数据：

```
TEXT:Hello World   → HID 直接打出
TEXT:你好世界      → CDC 串口转发给 Agent
CMD:保存           → HID 触发 Ctrl+S（或 Cmd+S）
```

---

## 串口协议

| 格式 | 含义 | 示例 |
|------|------|------|
| `TEXT:<内容>` | 打字输出 | `TEXT:今天天气真不错` |
| `CMD:<指令>` | 触发快捷键 | `CMD:保存` |

路由规则：
- `CMD:` → 始终走 HID
- `TEXT:` 纯 ASCII → 走 HID
- `TEXT:` 含中文 → 走 CDC 串口发给 Agent

### 内置指令

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

---

## nRF52840 固件参考

- 开发工具链：nRF Connect SDK + VS Code（nRF5 SDK 已停止维护）
- 原型开发板：Seeed XIAO nRF52840 Sense（集成 PDM 麦克风，有现成示例）
- BLE 音频参考：[BLE_Audio_Stream_NRF52840](https://github.com/aapatni/BLE_Audio_Stream_NRF52840)
- PDM 采集参考：[Seeed XIAO PDM Usage](https://wiki.seeedstudio.com/XIAO-BLE-Sense-PDM-Usage/)

---

## License

MIT
