# Voice Keyboard — 开发者指南

## 项目概述

语音打字工具。PTT 按住说话 → 讯飞 STT 识别 → 自动打字进当前输入框。
支持纯软件模式（任意麦克风）和 ESP32-S3 硬件模式。

## 启动方式

```bash
# 激活虚拟环境
.venv\Scripts\activate          # Windows
source .venv/bin/activate       # macOS / Linux

# 纯软件模式（无 ESP32）
python -m agent.main --no-serial

# 列出可用麦克风
python -m agent.main --list-devices
```

## 核心文件

| 文件 | 职责 |
|------|------|
| `agent/main.py` | 入口，串联所有模块 |
| `agent/push_to_talk.py` | PTT 录音，pynput 键盘监听 |
| `agent/stt.py` | STT 多 provider（xunfei/openai/aliyun/volcengine/zhipuai） |
| `agent/typer.py` | 三平台打字（Unicode / 剪贴板），退格擦除，行选择 |
| `agent/audio_monitor.py` | VAD 常开模式（PTT 模式不用此文件） |
| `agent/keyboard_monitor.py` | 退格监听，同步 TextBuffer |
| `agent/mouse_monitor.py` | 鼠标点击检测（光标不可信时切行选择模式） |
| `agent/text_buffer.py` | 文字账本，供语音编辑用 |
| `agent/llm_editor.py` | LLM 语音编辑（GLM-4-Flash） |
| `agent/config.py` | 加载 config.yaml / .env |

## 配置文件

`config.yaml`（从 `config.yaml.example` 复制）：

```yaml
stt:
  provider: xunfei          # 推荐：xunfei / aliyun
  app_id: "..."
  api_key: "..."
  api_secret: "..."
  language: zh_cn

llm:
  provider: zhipuai
  api_key: "..."
  model: glm-4-flash

typing:
  method: clip              # clip=剪贴板（微信）/ unicode=逐字（记事本/Word）

audio:
  mode: ptt                 # ptt=按键触发 / vad=自动检测
  ptt_key: alt_gr           # Windows 中文键盘右Alt
  edit_key: ctrl_r          # 右Ctrl
  device: 1                 # 麦克风序号，auto=自动
```

## 打字方式选择

| 应用类型 | 推荐方式 | 原因 |
|----------|---------|------|
| 微信、钉钉、Electron 应用 | `method: clip` | 这类应用过滤 SendInput Unicode 事件 |
| 记事本、Word、VS Code | `method: unicode` | 逐字更精确，不占用剪贴板 |

## STT Provider 对比

| provider | 适合场景 | 特点 |
|----------|---------|------|
| `xunfei` | **推荐**，中文日常使用 | 原话逐字转写，数字自动阿拉伯数字，WebSocket 流式 |
| `aliyun` | 方言、多语言 | 支持方言，REST API |
| `volcengine` | 备选 | HTTP API，需 streaming_common 集群 |
| `zhipuai` | 不推荐做 STT | 对话模型，会改写内容而非原样转写 |
| `openai` | 英文 / 多语言 | Whisper，中文效果一般 |

## 已知约束

- **VAD 模式**：依赖 `webrtcvad`，Python 3.13+ 暂无预编译包，请用 PTT 模式
- **Windows 中文键盘**：右 Alt = `alt_gr`，右 Ctrl = `ctrl_r`（非 `right_alt` / `right_ctrl`）
- **Volcengine**：`/api/v1/asr` 端点不支持 `volcengine_input_common` 集群，若用火山引擎需换 WebSocket v2 协议
- **GLM-4-Voice**：是对话模型，不适合做 STT，会用自己的措辞回复

## 性能说明

| 阶段 | 典型耗时 | 说明 |
|------|---------|------|
| 讯飞 STT | 300–600ms | WebSocket 握手 + 服务端识别 |
| 剪贴板粘贴 | ~60ms | 写入 30ms + 粘贴 30ms |
| LLM 编辑 | 500–1000ms | GLM-4-Flash，仅语音编辑时触发 |

> `stt.py` 中发包间隔设为 5ms（非实时速率），PTT 音频已录完无需按实时速率发包，
> 可大幅减少长句的等待时间（3 秒录音节省约 2.6 秒）。

## 依赖安装

```bash
pip install -r requirements.txt
```

主要依赖：`sounddevice` `pynput` `websocket-client` `zhipuai` `requests` `pyyaml`

## 热键检测（Windows）

不确定按键名称时，运行：

```bat
.venv\Scripts\python -c "from pynput import keyboard; l = keyboard.Listener(on_press=lambda k: print(k)); l.start(); input()"
```

按目标键，控制台打印的即为 config.yaml 中应填的名称。
