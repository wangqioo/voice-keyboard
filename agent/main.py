"""
Voice Keyboard Agent —— PC 端后台程序入口。

用法：
  python -m agent.main                    # 正常启动
  python -m agent.main --no-serial        # 纯软件模式，不搜索 ESP32 串口
  python -m agent.main --list-devices     # 列出可用麦克风设备
  python -m agent.main --install          # 注册开机自启动
  python -m agent.main --uninstall        # 移除开机自启动
  python -m agent.main --headless         # 不启动悬浮状态窗（桌面端托管模式）
"""

import argparse
import atexit
import hashlib
import json
import os
import signal
import sys
import threading
import time
from pathlib import Path


def _configure_ssl_cert_file() -> None:
    """Point provider SDKs/WebSockets at certifi when the host OpenSSL lacks CA roots."""
    try:
        import certifi

        bundled_candidates = []
        if getattr(sys, "frozen", False):
            exe_dir = Path(sys.executable).resolve().parent
            resources_dir = exe_dir.parent / "Resources"
            bundled_candidates.extend([
                resources_dir / "lib" / f"python{sys.version_info.major}.{sys.version_info.minor}" / "certifi" / "cacert.pem",
                resources_dir / "openssl.ca",
            ])
        _ca_path = None
        for p in bundled_candidates:
            if p.exists():
                _ca_path = str(p)
                break
        if _ca_path is None:
            _ca_path = certifi.where()

        for _env_name in ("SSL_CERT_FILE", "REQUESTS_CA_BUNDLE"):
            _current = os.environ.get(_env_name)
            if not _current or not Path(_current).exists():
                os.environ[_env_name] = _ca_path
        print(f"[agent] 使用 CA 证书: {_ca_path}")
    except ImportError:
        pass


_configure_ssl_cert_file()

# 打包模式下日志重定向到文件，必须在所有 print 之前
from agent import log_setup as _log_setup
_log_setup.setup()

import sounddevice as sd

from agent.autostart import install, uninstall
from agent.dictation_mode import (
    _POLISH_SYSTEM,
    clean_generated_text as _clean_generated_text,
    clean_polished_text as _clean_polished_text,
    make_utterance_handler as _make_dictation_utterance_handler,
)
from agent.history import History
from agent.input_environment import TyperInputEnvironment
from agent.runtime_composition import RuntimeOptions, build_runtime_backend, options_from_args
from agent.text_buffer import TextBuffer

_RUNTIME_LOCK_FILE = None


def _runtime_lock_path() -> Path:
    key = hashlib.sha1(str(Path.cwd().resolve()).encode("utf-8")).hexdigest()[:12]
    return Path(os.environ.get("TMPDIR", "/tmp")) / f"voice-keyboard-{key}.lock"


def _acquire_runtime_lock() -> bool:
    """Keep one desktop runtime per checkout so hotkeys and HUDs do not stack."""
    global _RUNTIME_LOCK_FILE
    if _RUNTIME_LOCK_FILE is not None:
        return True
    path = _runtime_lock_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = path.open("a+", encoding="utf-8")
    try:
        import fcntl

        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        handle.seek(0)
        existing = handle.read().strip()
        detail = f" PID={existing}" if existing else ""
        print(f"[agent] 已有 Voice Keyboard 运行中{detail}，本次启动退出")
        handle.close()
        return False
    except ImportError:
        # Windows tray has its own lifecycle. On platforms without fcntl, avoid
        # blocking startup rather than pretending we have a reliable lock.
        handle.close()
        return True
    handle.seek(0)
    handle.truncate()
    handle.write(str(os.getpid()))
    handle.flush()
    _RUNTIME_LOCK_FILE = handle
    atexit.register(_release_runtime_lock)
    return True


def _release_runtime_lock() -> None:
    global _RUNTIME_LOCK_FILE
    if _RUNTIME_LOCK_FILE is None:
        return
    try:
        import fcntl

        fcntl.flock(_RUNTIME_LOCK_FILE.fileno(), fcntl.LOCK_UN)
    except Exception:
        pass
    try:
        _RUNTIME_LOCK_FILE.close()
    except Exception:
        pass
    _RUNTIME_LOCK_FILE = None


# ── 串口回调 ───────────────────────────────────────────────────────

def make_serial_handlers(buf: TextBuffer, history: History | None = None, input_environment=None):
    from agent.typer import list_shortcuts, send_shortcut
    env = input_environment or TyperInputEnvironment(buf)

    def on_text(text: str):
        print(f"[agent] 打字: {text!r}")
        try:
            env.insert_dictation(text)
            if history is not None:
                history.append("dictate", text, "ok")
        except Exception as e:
            print(f"[agent] 打字失败: {e}")
            if history is not None:
                history.append("dictate", text, "error", f"typing: {e}")

    def on_cmd(cmd: str):
        print(f"[agent] 指令: {cmd}")
        if not send_shortcut(cmd):
            print(f"[agent] 未知指令: {cmd}，支持: {list_shortcuts()}")

    return on_text, on_cmd


# ── STT 回调 ───────────────────────────────────────────────────────

def make_utterance_handler(stt_client, buf: TextBuffer, editor=None,
                           status_window=None, history: History | None = None,
                           input_environment=None):
    return _make_dictation_utterance_handler(
        stt_client,
        buf,
        editor=editor,
        status_window=status_window,
        history=history,
        input_environment=input_environment,
    )


def build_backend(args, buf: TextBuffer, status_window, history: History):
    return build_runtime_backend(options_from_args(args), buf, status_window, history)


def _llm_configured(llm_cfg: dict) -> bool:
    from agent.typeup_backend_auth import is_typeup_backend_configured
    return is_typeup_backend_configured(llm_cfg)


# ── 入口 ───────────────────────────────────────────────────────────

def list_devices():
    print("\n可用麦克风设备：\n")
    for i, d in enumerate(sd.query_devices()):
        if d["max_input_channels"] > 0:
            default = " ← 系统默认" if i == sd.default.device[0] else ""
            print(f"  [{i:2d}] {d['name']}{default}")
    print(
        "\n在 config.yaml 中填写设备序号或名称片段：\n"
        "  audio:\n"
        "    device: 2\n"
        "    device: \"MacBook\"\n"
    )


def main():
    parser = argparse.ArgumentParser(description="Voice Keyboard Agent")
    parser.add_argument("--port",         default=None,        help="指定串口路径")
    parser.add_argument("--no-serial",    action="store_true", help="不搜索 ESP32 串口（纯软件模式）")
    parser.add_argument("--list-devices", action="store_true", help="列出可用麦克风设备后退出")
    parser.add_argument("--result-json",  default=None,        help="把一次性命令的 JSON 结果写入指定文件")
    parser.add_argument("--permissions-json", action="store_true", help="输出 macOS 权限状态 JSON 后退出")
    parser.add_argument("--request-accessibility", action="store_true", help="请求 macOS 辅助功能权限后退出")
    parser.add_argument("--request-input-monitoring", action="store_true", help="请求 macOS 输入监听权限后退出")
    parser.add_argument("--request-microphone", action="store_true", help="请求 macOS 麦克风权限后退出")
    parser.add_argument("--install",      action="store_true", help="注册开机自启动")
    parser.add_argument("--uninstall",    action="store_true", help="移除开机自启动")
    parser.add_argument("--no-ui",        action="store_true", help="不启动菜单栏/主窗口（纯命令行）")
    parser.add_argument("--headless",     action="store_true", help="不启动悬浮状态窗（供桌面端托管）")
    args = parser.parse_args()
    if getattr(sys, "frozen", False):
        args.no_serial = True

    def emit_json(payload):
        text = json.dumps(payload, ensure_ascii=False)
        if args.result_json:
            try:
                with open(args.result_json, "w", encoding="utf-8") as f:
                    f.write(text)
            except Exception as e:
                print(f"[agent] 写入 JSON 结果失败: {e}")
        print(text)

    if args.list_devices:
        list_devices()
        return
    if args.permissions_json:
        from agent import permissions as _perm
        emit_json(_perm.all_status())
        return
    if args.request_accessibility:
        from agent import permissions as _perm
        emit_json({"accessibility": _perm.request_accessibility()})
        return
    if args.request_input_monitoring:
        from agent import permissions as _perm
        emit_json({"input_monitoring": _perm.request_input_monitoring()})
        return
    if args.request_microphone:
        from agent import permissions as _perm
        emit_json({"microphone": _perm.request_microphone_sync()})
        return
    if args.install:
        install()
        return
    if args.uninstall:
        uninstall()
        return

    if not _acquire_runtime_lock():
        return

    from agent.config import ensure_user_config
    ensure_user_config()

    # 启动权限自检（仅 macOS）
    try:
        from agent import permissions as _perm
        print(f"[perm] {_perm.summary_log()}")
    except Exception as e:
        print(f"[perm] 自检失败: {e}")

    buf = TextBuffer()
    history = History()
    history.compact()

    # ── 状态悬浮窗 ───────────────────────────────────────────────
    status_window = None
    if not args.headless:
        try:
            if sys.platform == "win32":
                from agent.status_window_win import StatusWindow
            else:
                from agent.status_window import StatusWindow
            status_window = StatusWindow()
        except Exception as e:
            print(f"[agent] 状态悬浮窗启动失败（{e}），将以无窗口模式运行")

    print("[agent] Voice Keyboard Agent 启动")

    # ── 后端 ─────────────────────────────────────────────────────
    backend_lock = threading.Lock()
    backend = build_backend(args, buf, status_window, history)

    def reload_backend():
        with backend_lock:
            print("[agent] === 热重载后端 ===")
            backend.stop()
            new_bk = build_backend(args, buf, status_window, history)
            backend.cfg          = new_bk.cfg
            backend.reader       = new_bk.reader
            backend.audio        = new_bk.audio
            print("[agent] 热重载完成")

    def retype(text: str):
        # 历史 tab「再次打字」回调，UI 已隐藏后调度
        env = TyperInputEnvironment(buf)
        try:
            env.insert_dictation(text)
            history.append("dictate", text, "ok", detail="retype")
        except Exception as e:
            print(f"[agent] retype 失败: {e}")

    # ── UI（菜单栏 + 主窗口）───────────────────────────────────────
    ui_app = None
    if status_window is not None and not args.no_ui:
        try:
            from agent.ui.app import UIApp
            from agent.memo_store import MemoStore
            ui_app = UIApp(
                history=history,
                memos=MemoStore(),
                reload_backend=reload_backend,
                retype_callback=retype,
            )
            status_window.add_main_thread_setup(ui_app.build)
        except Exception as e:
            import traceback
            print(f"[agent] UI 初始化失败: {e}")
            traceback.print_exc()
            ui_app = None

    def shutdown(sig=None, frame=None):
        print("\n[agent] 退出")
        with backend_lock:
            backend.stop()
        if status_window:
            status_window.stop()
        sys.exit(0)

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    print("[agent] 运行中，Ctrl+C 退出\n")
    if status_window is not None:
        status_window.run()
    else:
        while True:
            time.sleep(1)


if __name__ == "__main__":
    main()
