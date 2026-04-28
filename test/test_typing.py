"""
打字模块直接测试 —— 三平台通用，不依赖串口和模拟器。

用法：
  python test/test_typing.py

运行后把光标点进任意输入框（记事本、浏览器地址栏、VSCode 等），
等 3 秒后文字会自动逐字打出。
"""

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from agent.typer import type_text, send_shortcut

TEST_CASES = [
    ("text", "你好世界"),
    ("text", "这是一段中文测试，Voice Keyboard 项目"),
    ("text", "Hello, 混合中英文 input test 123"),
    ("text", "今天天气真不错，适合写代码。"),
    ("cmd",  "保存"),
]

print("3 秒后开始测试，请把光标点进任意输入框...")
time.sleep(3)

for kind, content in TEST_CASES:
    if kind == "text":
        print(f"[test] 打字: {content}")
        type_text(content)
    else:
        print(f"[test] 指令: {content}")
        send_shortcut(content)
    time.sleep(2)

print("[test] 完成")
