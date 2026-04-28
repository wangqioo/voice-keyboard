"""
ESP32 模拟器 —— 无硬件时用于本地测试。

用法：
  1. 运行本脚本，它会打印出虚拟串口路径，例如：
       [sim] 虚拟串口: /dev/ttys004
  2. 在另一个终端启动 Agent，并指定该路径：
       python -m agent.main --port /dev/ttys004
  3. 脚本会按提示发送测试消息，观察你的输入框是否出现文字。
"""

import os
import pty
import time
import sys


def main():
    master_fd, slave_fd = pty.openpty()
    slave_name = os.ttyname(slave_fd)
    print(f"[sim] 虚拟串口: {slave_name}")
    print("[sim] 请在另一个终端运行:")
    print(f"[sim]   python -m agent.main --port {slave_name}")
    print("[sim] 等待 3 秒后开始发送测试数据...\n")
    time.sleep(3)

    test_cases = [
        ("TEXT", "你好世界"),
        ("TEXT", "这是一段中文测试，Voice Keyboard 项目"),
        ("CMD",  "保存"),
        ("TEXT", "Hello, 混合中英文 input test 123"),
        ("CMD",  "截图"),
        ("TEXT", "今天天气真不错，适合写代码。"),
    ]

    for kind, payload in test_cases:
        msg = f"{kind}:{payload}\n"
        print(f"[sim] 发送 → {msg.strip()}")
        os.write(master_fd, msg.encode("utf-8"))
        time.sleep(2)

    print("[sim] 测试完成，按 Ctrl+C 退出。")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        os.close(master_fd)
        os.close(slave_fd)


if __name__ == "__main__":
    main()
