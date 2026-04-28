"""
Voice Keyboard Agent —— PC 端后台程序入口。

用法：
  python -m agent.main                    # 正常启动（自动选择 PTT / VAD 模式）
  python -m agent.main --no-serial        # 纯软件模式，不搜索 ESP32 串口
  python -m agent.main --list-devices     # 列出可用麦克风设备
  python -m agent.main --port /dev/ttyX   # 指定串口（测试用）
  python -m agent.main --install          # 注册开机自启动
  python -m agent.main --uninstall        # 移除开机自启动
"""

import argparse
import signal
import sys
import time

import sounddevice as sd

from agent.autostart import install, uninstall
from agent.config import load as load_config
from agent.serial_reader import SerialReader
from agent.typer import type_text, send_shortcut, list_shortcuts


# ── 串口回调 ───────────────────────────────────────────────────────

def on_text(text: str):
    print(f"[agent] 打字: {text!r}")
    type_text(text)


def on_cmd(cmd: str):
    print(f"[agent] 指令: {cmd}")
    if not send_shortcut(cmd):
        print(f"[agent] 未知指令: {cmd}")
        print(f"[agent] 支持的指令: {list_shortcuts()}")


# ── 音频 STT 公共回调 ──────────────────────────────────────────────

def _make_utterance_handler(stt_client):
    def on_utterance(pcm: bytes):
        try:
            text = stt_client.transcribe(pcm)
            if text:
                print(f"[stt] {text!r}")
                type_text(text)
            else:
                print("[stt] 识别结果为空")
        except Exception as e:
            print(f"[stt] 请求失败: {e}")
    return on_utterance


# ── 音频管线构建 ───────────────────────────────────────────────────

def _build_audio(cfg: dict):
    """
    根据 config.yaml 构建音频管线。
    返回已启动的 monitor/ptt 对象，或 None（配置缺失 / 依赖不足时）。
    """
    stt_cfg = cfg.get("stt", {})
    if not stt_cfg.get("api_key"):
        print("[agent] 未配置 stt.api_key（config.yaml），跳过音频 STT")
        print("[agent] 提示: cp config.yaml.example config.yaml 然后填入 API Key")
        return None

    try:
        from agent.stt import STTClient
    except ImportError as e:
        print(f"[agent] 依赖缺失（{e}），请运行: pip install openai")
        return None

    try:
        client = STTClient(stt_cfg)
    except Exception as e:
        print(f"[agent] STT 初始化失败: {e}")
        return None

    on_utterance = _make_utterance_handler(client)
    audio_cfg    = cfg.get("audio", {})
    mode         = audio_cfg.get("mode", "ptt")   # ptt | vad
    device       = audio_cfg.get("device", "auto")

    if mode == "ptt":
        try:
            from agent.push_to_talk import PushToTalk
        except ImportError as e:
            print(f"[agent] PTT 依赖缺失（{e}），请运行: pip install sounddevice pynput")
            return None
        ptt_key = audio_cfg.get("ptt_key", "right_alt")
        monitor = PushToTalk(on_utterance=on_utterance, ptt_key=ptt_key, device=device)
    else:
        try:
            from agent.audio_monitor import AudioMonitor
        except ImportError as e:
            print(f"[agent] VAD 依赖缺失（{e}），请运行: pip install sounddevice webrtcvad")
            return None
        vad_level = audio_cfg.get("vad_aggressiveness", 2)
        monitor   = AudioMonitor(on_utterance=on_utterance, device=device, vad_level=vad_level)

    monitor.start()
    return monitor


# ── 入口 ───────────────────────────────────────────────────────────

def list_devices():
    print("\n可用麦克风设备：\n")
    for i, d in enumerate(sd.query_devices()):
        if d["max_input_channels"] > 0:
            default = " ← 系统默认" if i == sd.default.device[0] else ""
            print(f"  [{i:2d}] {d['name']}{default}")
    print("\n在 config.yaml 中填写设备序号或名称片段，如:\n  audio:\n    device: 2\n    device: \"MacBook\"\n")


def main():
    parser = argparse.ArgumentParser(description="Voice Keyboard Agent")
    parser.add_argument("--port",         default=None,        help="指定串口路径")
    parser.add_argument("--no-serial",    action="store_true", help="不搜索 ESP32 串口（纯软件模式）")
    parser.add_argument("--list-devices", action="store_true", help="列出可用麦克风设备后退出")
    parser.add_argument("--install",      action="store_true", help="注册开机自启动")
    parser.add_argument("--uninstall",    action="store_true", help="移除开机自启动")
    args = parser.parse_args()

    if args.list_devices:
        list_devices()
        return
    if args.install:
        install()
        return
    if args.uninstall:
        uninstall()
        return

    cfg = load_config()
    print("[agent] Voice Keyboard Agent 启动")

    # ── 串口（HID 快捷键 + 有硬件时的备用文字输入）────────────────
    reader = None
    if not args.no_serial:
        reader = SerialReader(on_text=on_text, on_cmd=on_cmd, port=args.port)
        reader.start()
    else:
        print("[agent] 串口已禁用（纯软件模式）")

    # ── 音频 STT ─────────────────────────────────────────────────
    monitor = _build_audio(cfg)

    def shutdown(sig, frame):
        print("\n[agent] 退出")
        if reader:
            reader.stop()
        if monitor:
            monitor.stop()
        sys.exit(0)

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    print("[agent] 运行中，Ctrl+C 退出\n")
    while True:
        time.sleep(1)


if __name__ == "__main__":
    main()
