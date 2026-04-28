"""
Voice Keyboard Agent —— PC 端后台程序入口。

用法：
  python -m agent.main               # 自动搜索 ESP32 串口
  python -m agent.main --port /dev/ttys004  # 指定串口（测试用）
  python -m agent.main --install     # 注册开机自启动
  python -m agent.main --uninstall   # 移除开机自启动
"""

import argparse
import signal
import sys
import time

from agent.autostart import install, uninstall
from agent.serial_reader import SerialReader
from agent.typer import type_text, send_shortcut, list_shortcuts


def on_text(text: str):
    print(f"[agent] 打字: {text}")
    type_text(text)


def on_cmd(cmd: str):
    print(f"[agent] 指令: {cmd}")
    if not send_shortcut(cmd):
        print(f"[agent] 未知指令: {cmd}，已忽略")
        print(f"[agent] 支持的指令: {list_shortcuts()}")


def main():
    parser = argparse.ArgumentParser(description="Voice Keyboard Agent")
    parser.add_argument("--port",      default=None,  help="指定串口路径，不填则自动搜索 ESP32")
    parser.add_argument("--install",   action="store_true", help="注册开机自启动")
    parser.add_argument("--uninstall", action="store_true", help="移除开机自启动")
    args = parser.parse_args()

    if args.install:
        install()
        return
    if args.uninstall:
        uninstall()
        return

    print("[agent] Voice Keyboard Agent 启动")
    if args.port:
        print(f"[agent] 使用指定串口: {args.port}")
    else:
        print("[agent] 自动搜索 ESP32 串口...")

    reader = SerialReader(on_text=on_text, on_cmd=on_cmd, port=args.port)
    reader.start()

    def shutdown(sig, frame):
        print("\n[agent] 退出")
        reader.stop()
        sys.exit(0)

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    print("[agent] 运行中，Ctrl+C 退出\n")
    while True:
        time.sleep(1)


if __name__ == "__main__":
    main()
