"""
Voice Keyboard Agent —— PC 端后台程序入口。

用法：
  python -m agent.main                    # 正常启动
  python -m agent.main --no-serial        # 纯软件模式，不搜索 ESP32 串口
  python -m agent.main --list-devices     # 列出可用麦克风设备
  python -m agent.main --install          # 注册开机自启动
  python -m agent.main --uninstall        # 移除开机自启动
"""

import argparse
import ctypes
import os
import signal
import sys
import threading
import time

# 打包后显式指定 CA 证书路径，供 requests 等直接读取环境变量使用。
if getattr(sys, "frozen", False):
    try:
        import certifi
        from pathlib import Path

        exe_dir = Path(sys.executable).resolve().parent
        resources_dir = exe_dir.parent / "Resources"
        bundled_candidates = [
            resources_dir / "lib" / f"python{sys.version_info.major}.{sys.version_info.minor}" / "certifi" / "cacert.pem",
            resources_dir / "openssl.ca",
        ]
        _ca_path = None
        for p in bundled_candidates:
            if p.exists():
                _ca_path = str(p)
                break
        if _ca_path is None:
            _ca_path = certifi.where()

        os.environ.setdefault("SSL_CERT_FILE", _ca_path)
        os.environ.setdefault("REQUESTS_CA_BUNDLE", _ca_path)
        print(f"[agent] 使用 CA 证书: {_ca_path}")
    except ImportError:
        pass

# 打包模式下日志重定向到文件，必须在所有 print 之前
from agent import log_setup as _log_setup
_log_setup.setup()

import sounddevice as sd

from agent.autostart import install, uninstall
from agent.config import load as load_config
from agent.cloud_client import CloudClient
from agent.history import History
from agent.local_quota import QuotaManager, QuotaError
from agent.serial_reader import SerialReader
from agent.text_buffer import TextBuffer
from agent.typer import init as typer_init, list_shortcuts, send_shortcut, type_text


# ── 管理员提权（Windows 键盘钩子最高优先级）──────────────────────────

def _is_admin() -> bool:
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False

def _relaunch_as_admin() -> None:
    """以管理员身份重启进程，使 WH_KEYBOARD_LL 钩子优先级高于所有普通用户程序。"""
    if _is_admin():
        return
    params = " ".join(f'"{a}"' for a in sys.argv)
    ret = ctypes.windll.shell32.ShellExecuteW(None, "runas", sys.executable, params, None, 1)
    if ret > 32:
        sys.exit(0)
    print("[agent] 用户取消了管理员授权，热键优先级可能受其他程序影响")


# ── 串口回调 ───────────────────────────────────────────────────────

def make_serial_handlers(buf: TextBuffer, history: History | None = None):
    def on_text(text: str):
        print(f"[agent] 打字: {text!r}")
        try:
            type_text(text)
            buf.push(text)
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

_POLISH_SYSTEM = """你是文字润色助手。对用户说的话做最轻度的润色：
- 去掉口语填充词（嗯、啊、呃、那个、就是说、然后呢之类）
- 修正明显的错别字和不通顺的地方
- 加上合适的标点

严格遵守：保留原意和说话风格，不要扩写、不要总结、不要改写措辞。
直接输出润色后的文字，不要任何解释、前缀或引号。"""


def make_utterance_handler(stt_client, buf: TextBuffer, kbd_mon=None, editor=None,
                           status_window=None, history: History | None = None,
                           quota: QuotaManager = None):
    def on_utterance(pcm: bytes, polish: bool = False):
        mode = "polish" if polish else "dictate"
        duration_seconds = len(pcm) / (16000 * 2)

        # ── 本地额度检查 ──
        if quota:
            can, reason = quota.can_stt(duration_seconds)
            if not can:
                print(f"[quota] STT 拒绝: {reason}")
                return

        try:
            text = stt_client.transcribe(pcm)
        except Exception as e:
            print(f"[stt] 请求失败: {e}")
            if history is not None:
                history.append(mode, "", "error", f"STT: {e}")
            if status_window is not None:
                status_window.set_state("error_stt")
            return
        if not text:
            print("[stt] 识别结果为空")
            if history is not None:
                history.append(mode, "", "empty")
            return
        print(f"[stt] {text!r}")
        if polish and editor is not None:
            if status_window is not None:
                status_window.set_state("polishing")
            try:
                polished = editor.chat(_POLISH_SYSTEM, text).strip()
                if polished:
                    print(f"[stt] 微润色 → {polished!r}")
                    text = polished
            except Exception as e:
                print(f"[stt] 润色失败，回退原文: {e}")
        try:
            type_text(text)
            buf.push(text)
        except Exception as e:
            print(f"[stt] 打字失败: {e}")
            if status_window is not None:
                status_window.set_state("error_typing")
            if history is not None:
                history.append(mode, text, "error", f"typing: {e}")
            return

        # ── 本地额度扣减 ──
        if quota:
            quota.deduct_stt(duration_seconds)
            quota.sync_to_cloud()

        if history is not None:
            history.append(mode, text, "ok")
        if kbd_mon is not None:
            kbd_mon.notify_voice_output()
        if status_window is not None:
            status_window.set_state("idle")
    return on_utterance


# ── 后端组件容器（供热重载使用）─────────────────────────────────────

class _Backend:
    """所有可重启的后端组件，热重载时整体停掉再重建。"""
    def __init__(self):
        self.cfg = None
        self.kbd_monitor = None
        self.mouse_monitor = None
        self.reader = None
        self.audio = None  # PushToTalk or AudioMonitor

    def stop(self):
        for attr in ("audio", "reader", "mouse_monitor", "kbd_monitor"):
            comp = getattr(self, attr, None)
            if comp is None:
                continue
            try:
                comp.stop()
            except Exception as e:
                print(f"[agent] 停止 {attr} 失败: {e}")
            setattr(self, attr, None)


def build_backend(args, buf: TextBuffer, status_window, history: History,
                  quota: QuotaManager = None) -> _Backend:
    bk = _Backend()
    bk.cfg = load_config()
    typer_init(bk.cfg.get("typing", {}))

    try:
        from agent.keyboard_monitor import KeyboardMonitor
        bk.kbd_monitor = KeyboardMonitor(buf)
        bk.kbd_monitor.start()
    except Exception as e:
        print(f"[agent] 键盘监听启动失败（{e}），退格同步不可用")

    try:
        from agent.mouse_monitor import MouseMonitor
        bk.mouse_monitor = MouseMonitor(buf)
        bk.mouse_monitor.start()
    except Exception as e:
        print(f"[agent] 鼠标监听启动失败（{e}），行选择模式不可用")

    if not args.no_serial:
        on_text, on_cmd = make_serial_handlers(buf, history=history)
        bk.reader = SerialReader(on_text=on_text, on_cmd=on_cmd, port=args.port)
        bk.reader.start()
    else:
        print("[agent] 串口已禁用（纯软件模式）")

    bk.audio = _build_audio(bk.cfg, buf, kbd_monitor=bk.kbd_monitor,
                            status_window=status_window, history=history,
                            quota=quota)
    return bk


def _build_audio(cfg: dict, buf: TextBuffer, kbd_monitor=None, status_window=None,
                 history: History | None = None, quota: QuotaManager = None):
    stt_cfg = cfg.get("stt", {})
    provider = stt_cfg.get("provider", "")
    _no_api_key_providers = {"volcengine", "aliyun"}
    if not stt_cfg.get("api_key") and provider not in _no_api_key_providers:
        print("[agent] 未配置 stt.api_key，跳过音频 STT")
        print("[agent] 提示: cp config.yaml.example config.yaml 然后填入 API Key")
        return None

    try:
        from agent.stt import STTClient
    except ImportError as e:
        print(f"[agent] STT 依赖缺失（{e}）")
        return None

    try:
        stt = STTClient(stt_cfg)
    except Exception as e:
        print(f"[agent] STT 初始化失败: {e}")
        return None

    editor = None
    llm_cfg = cfg.get("llm", {})
    if llm_cfg.get("api_key"):
        try:
            from agent.llm_editor import LLMEditor
            editor = LLMEditor(llm_cfg)
            print("[agent] LLM 编辑功能已启用")
        except Exception as e:
            import traceback
            print(f"[agent] LLM 初始化失败: {e}")
            traceback.print_exc()

    audio_cfg = cfg.get("audio", {})
    mode      = audio_cfg.get("mode", "ptt")
    device    = audio_cfg.get("device", "auto")

    ai_handler = None
    if editor:
        try:
            from agent.ai_handler import AIHandler
            from agent.memo_store import MemoStore
            memo_store = MemoStore()
            ai_handler = AIHandler(stt, editor, buf, memo_store=memo_store,
                                   status_window=status_window, history=history)
            ai_key_name = audio_cfg.get("ai_key", "cmd_r")
            existing = memo_store.keys()
            if existing:
                print(f"[memo] 已加载 {len(existing)} 条备忘录: {'、'.join(existing)}")
            print(f"[agent] AI 键已启用，热键: {ai_key_name}")
        except Exception as e:
            print(f"[agent] AIHandler 初始化失败: {e}")

    on_utterance = make_utterance_handler(stt, buf, kbd_mon=kbd_monitor, editor=editor,
                                          status_window=status_window, history=history,
                                          quota=quota)

    if mode == "ptt":
        try:
            from agent.push_to_talk import PushToTalk
        except ImportError as e:
            print(f"[agent] PTT 依赖缺失（{e}）")
            return None

        on_ai         = ai_handler.handle        if ai_handler else None
        on_ai_key_dwn = ai_handler.on_ai_key_down if ai_handler else None

        on_edit = None
        if editor:
            from agent.edit_handler import make_edit_handler
            on_edit = make_edit_handler(stt, editor, buf, vad_monitor=None, quota=quota)

        ptt = PushToTalk(
            on_utterance=on_utterance,
            on_edit_utterance=on_edit,
            on_ai_utterance=on_ai,
            on_ai_key_down=on_ai_key_dwn,
            ptt_key=audio_cfg.get("ptt_key", "right_alt"),
            ai_key=audio_cfg.get("ai_key", "cmd_r"),
            device=device,
            status_window=status_window,
            kbd_monitor=kbd_monitor,
        )
        ptt.start()
        return ptt

    else:
        try:
            from agent.audio_monitor import AudioMonitor
        except ImportError as e:
            print(f"[agent] VAD 依赖缺失（{e}）")
            return None

        monitor = AudioMonitor(
            on_utterance=on_utterance,
            device=device,
            vad_level=audio_cfg.get("vad_aggressiveness", 2),
        )
        monitor.start()

        # VAD 模式下，编辑键仍用 PTT 方式（避免 VAD 误触发）
        if editor:
            try:
                from agent.push_to_talk import PushToTalk
                from agent.edit_handler import make_edit_handler
                on_edit = make_edit_handler(stt, editor, buf, vad_monitor=monitor, quota=quota)

                edit_ptt = PushToTalk(
                    on_utterance=on_utterance,
                    on_edit_utterance=on_edit,
                    ptt_key=audio_cfg.get("ptt_key", "right_alt"),
                    edit_key=audio_cfg.get("edit_key", "right_ctrl"),
                    device=device,
                )

                _orig_press = edit_ptt._on_press

                def _patched_press(key):
                    from pynput.keyboard import Key
                    edit_key_obj = edit_ptt._edit_key
                    if key == edit_key_obj:
                        monitor.pause()
                    _orig_press(key)

                edit_ptt._listener
                edit_ptt._on_press = _patched_press
                edit_ptt.start()
                return monitor
            except ImportError:
                pass

        return monitor


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
    parser.add_argument("--no-serial",    action="store_true", default=True,
                                                               help="不搜索 ESP32 串口（默认，纯软件模式）")
    parser.add_argument("--serial",       action="store_false", dest="no_serial",
                                                               help="启用串口搜索（有 ESP32 硬件时使用）")
    parser.add_argument("--list-devices", action="store_true", help="列出可用麦克风设备后退出")
    parser.add_argument("--install",      action="store_true", help="注册开机自启动")
    parser.add_argument("--uninstall",    action="store_true", help="移除开机自启动")
    parser.add_argument("--no-ui",        action="store_true", help="不启动菜单栏/主窗口（纯命令行）")
    parser.add_argument("--no-elevate",   action="store_true", help="不自动请求管理员权限（由父进程统一提权时使用）")
    args = parser.parse_args()
    if getattr(sys, "frozen", False):
        args.no_serial = True

    # Windows：以管理员身份运行，确保键盘钩子优先级高于所有普通用户程序
    if sys.platform == "win32" and not args.no_elevate:
        _relaunch_as_admin()

    if args.list_devices:
        list_devices()
        return
    if args.install:
        install()
        return
    if args.uninstall:
        uninstall()
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
    try:
        if sys.platform == "win32":
            from agent.status_window_win import StatusWindow
        else:
            from agent.status_window import StatusWindow
        status_window = StatusWindow()
    except Exception as e:
        print(f"[agent] 状态悬浮窗启动失败（{e}），将以无窗口模式运行")

    print("[agent] Voice Keyboard Agent 启动")

    # ── 云端登录 + 本地额度初始化 ─────────────────────────
    quota = None
    cfg = load_config()
    cloud_cfg = cfg.get("cloud", {})
    if cloud_cfg.get("email") and cloud_cfg.get("password"):
        base_url = cloud_cfg.get("base_url", "http://localhost:8000")
        try:
            cloud = CloudClient(base_url=base_url)
            cloud.login(cloud_cfg["email"], cloud_cfg["password"])
            print(f"[cloud] 已登录云端（{cloud_cfg['email']}）")
            quota = QuotaManager(cloud_client=cloud)
            success = quota.initialize()
            if success:
                print(f"[quota] {quota.status_str()}")
            else:
                print("[quota] 初始化失败，使用本地缓存限额")
        except Exception as e:
            print(f"[cloud] 云端登录失败: {e}")
            print("[cloud] 继续以无额度限制模式运行")
    else:
        print("[cloud] 未配置云端账号，无额度管理")

    # ── 后端 ─────────────────────────────────────────────────────
    backend_lock = threading.Lock()
    backend = build_backend(args, buf, status_window, history, quota=quota)

    def reload_backend():
        with backend_lock:
            print("[agent] === 热重载后端 ===")
            backend.stop()
            new_bk = build_backend(args, buf, status_window, history, quota=quota)
            backend.cfg          = new_bk.cfg
            backend.kbd_monitor  = new_bk.kbd_monitor
            backend.mouse_monitor= new_bk.mouse_monitor
            backend.reader       = new_bk.reader
            backend.audio        = new_bk.audio
            print("[agent] 热重载完成")

    def retype(text: str):
        # 历史 tab「再次打字」回调，UI 已隐藏后调度
        try:
            type_text(text)
            buf.push(text)
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
        if quota:
            quota.close()
        if status_window:
            status_window.stop()
        sys.exit(0)

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    print("[agent] 运行中，Ctrl+C 退出\n")
    if status_window is not None:
        status_window.run()
    else:
        sync_counter = 0
        while True:
            time.sleep(1)
            sync_counter += 1
            # 每 30 秒同步一次额度到云端
            if quota and sync_counter >= 30:
                quota.sync_to_cloud()
                sync_counter = 0


if __name__ == "__main__":
    main()
