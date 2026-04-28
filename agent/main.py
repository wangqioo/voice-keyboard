"""
Voice Keyboard Agent —— PC 端后台程序入口。

用法：
  python -m agent.main                    # 正常启动（串口 + 音频 STT）
  python -m agent.main --port /dev/ttyX   # 指定串口（测试用）
  python -m agent.main --no-audio         # 仅串口模式，不启动音频监听
  python -m agent.main --install          # 注册开机自启动
  python -m agent.main --uninstall        # 移除开机自启动
"""

import argparse
import signal
import sys
import time

from agent.autostart import install, uninstall
from agent.config import load as load_config
from agent.serial_reader import SerialReader
from agent.typer import type_text, send_shortcut, list_shortcuts


def on_text(text: str):
    print(f"[agent] 打字: {text!r}")
    type_text(text)


def on_cmd(cmd: str):
    print(f"[agent] 指令: {cmd}")
    if not send_shortcut(cmd):
        print(f"[agent] 未知指令: {cmd}")
        print(f"[agent] 支持的指令: {list_shortcuts()}")


def _build_audio_pipeline(cfg: dict):
    """
    构建 AudioMonitor + STTClient 管线。
    返回已 start() 的 AudioMonitor，或 None（依赖缺失 / 未配置时）。
    """
    stt_cfg = cfg.get("stt", {})
    if not stt_cfg.get("api_key"):
        print("[agent] 未配置 STT API key（config.yaml → stt.api_key），跳过音频 STT")
        return None

    try:
        from agent.audio_monitor import AudioMonitor
        from agent.stt import STTClient
    except ImportError as e:
        print(f"[agent] 音频依赖缺失（{e}），跳过音频 STT")
        print("[agent] 安装依赖：pip install sounddevice webrtcvad openai")
        return None

    audio_cfg = cfg.get("audio", {})

    try:
        client = STTClient(stt_cfg)
    except Exception as e:
        print(f"[agent] STT 初始化失败: {e}")
        return None

    def on_utterance(pcm: bytes):
        print("[audio] 识别中...")
        try:
            text = client.transcribe(pcm)
            if text:
                print(f"[audio] 识别结果: {text!r}")
                type_text(text)
            else:
                print("[audio] 识别结果为空，跳过")
        except Exception as e:
            print(f"[audio] STT 请求失败: {e}")

    monitor = AudioMonitor(
        on_utterance=on_utterance,
        device=audio_cfg.get("device", "auto"),
        vad_level=audio_cfg.get("vad_aggressiveness", 2),
    )
    monitor.start()
    return monitor


def main():
    parser = argparse.ArgumentParser(description="Voice Keyboard Agent")
    parser.add_argument("--port",      default=None,        help="指定串口路径，不填则自动搜索 ESP32")
    parser.add_argument("--no-audio",  action="store_true", help="禁用音频 STT（仅串口模式）")
    parser.add_argument("--install",   action="store_true", help="注册开机自启动")
    parser.add_argument("--uninstall", action="store_true", help="移除开机自启动")
    args = parser.parse_args()

    if args.install:
        install()
        return
    if args.uninstall:
        uninstall()
        return

    cfg = load_config()
    print("[agent] Voice Keyboard Agent 启动")

    # ── 串口（HID 快捷键 + 备用文字输入）────────────────────────
    reader = SerialReader(on_text=on_text, on_cmd=on_cmd, port=args.port)
    reader.start()

    # ── 音频 STT（主要语音输入路径）─────────────────────────────
    monitor = None
    if not args.no_audio:
        monitor = _build_audio_pipeline(cfg)

    def shutdown(sig, frame):
        print("\n[agent] 退出")
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
