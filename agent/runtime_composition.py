"""Runtime composition for the desktop Voice Keyboard Engine."""

from dataclasses import dataclass

from agent.config import load as load_config
from agent.history import History
from agent.input_environment import TyperInputEnvironment
from agent.serial_reader import SerialReader
from agent.speech_interpretation_providers import SpeechInterpretationProviderFactory
from agent.text_buffer import TextBuffer


@dataclass(frozen=True)
class RuntimeOptions:
    no_serial: bool = False
    port: str | None = None


class RuntimeBackend:
    """Restartable runtime components."""

    def __init__(self):
        self.cfg = None
        self.kbd_monitor = None
        self.mouse_monitor = None
        self.reader = None
        self.audio = None
        self.input_environment = None

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


def options_from_args(args) -> RuntimeOptions:
    return RuntimeOptions(
        no_serial=bool(getattr(args, "no_serial", False)),
        port=getattr(args, "port", None),
    )


def build_runtime_backend(
    options: RuntimeOptions,
    buf: TextBuffer,
    status_window,
    history: History,
) -> RuntimeBackend:
    bk = RuntimeBackend()
    bk.cfg = load_config()
    from agent.typer import init as typer_init
    typer_init(bk.cfg.get("typing", {}))
    instruction_cfg = bk.cfg.get("instruction_mode", {})
    bk.input_environment = TyperInputEnvironment(
        buf,
        require_selection_for_instruction=instruction_cfg.get(
            "require_selection_for_edit", False
        ),
    )

    if not instruction_cfg.get("require_selection_for_edit", False):
        try:
            from agent.keyboard_monitor import KeyboardMonitor
            from agent.mouse_monitor import MouseMonitor
            bk.kbd_monitor = KeyboardMonitor(bk.input_environment)
            bk.kbd_monitor.start()
            bk.mouse_monitor = MouseMonitor(bk.input_environment)
            bk.mouse_monitor.start()
        except Exception as e:
            print(f"[agent] 追踪监听启动失败（{e}），Tracked Segment 安全检测不可用")
    else:
        print("[agent] 编辑/删除仅使用 Explicit Selection，已关闭鼠标/回车/退格追踪检测")

    if not options.no_serial:
        from agent.main import make_serial_handlers
        on_text, on_cmd = make_serial_handlers(
            buf,
            history=history,
            input_environment=bk.input_environment,
        )
        bk.reader = SerialReader(on_text=on_text, on_cmd=on_cmd, port=options.port)
        bk.reader.start()
    else:
        print("[agent] 串口已禁用（纯软件模式）")

    bk.audio = build_audio_runtime(
        bk.cfg,
        buf,
        kbd_monitor=bk.kbd_monitor,
        status_window=status_window,
        history=history,
        input_environment=bk.input_environment,
    )
    return bk


def build_audio_runtime(
    cfg: dict,
    buf: TextBuffer,
    kbd_monitor=None,
    status_window=None,
    history: History | None = None,
    input_environment=None,
):
    audio_cfg = cfg.get("audio", {})
    mode = audio_cfg.get("mode", "ptt")
    device = audio_cfg.get("device", "auto")
    providers = SpeechInterpretationProviderFactory().create_provider_set(cfg)
    if providers is None:
        return None

    ai_handler = None
    if providers.text_operation_editor is not None and providers.instruction_stt is not None:
        try:
            from agent.ai_handler import AIHandler
            from agent.memo_store import MemoStore
            memo_store = MemoStore()
            ai_handler = AIHandler(
                providers.instruction_stt,
                providers.text_operation_editor,
                buf,
                memo_store=memo_store,
                status_window=status_window,
                history=history,
                input_environment=input_environment,
            )
            ai_key_name = audio_cfg.get("ai_key", "cmd_r")
            existing = memo_store.keys()
            if existing:
                print(f"[memo] 已加载 {len(existing)} 条可复用文本: {'、'.join(existing)}")
            print(f"[agent] AI 键已启用，热键: {ai_key_name}")
        except Exception as e:
            print(f"[agent] AIHandler 初始化失败: {e}")

    from agent.main import make_utterance_handler
    on_utterance = make_utterance_handler(
        providers.utterance_stt,
        buf,
        kbd_mon=kbd_monitor,
        editor=providers.text_operation_editor,
        status_window=status_window,
        history=history,
        input_environment=input_environment,
    )

    if mode == "ptt":
        try:
            from agent.push_to_talk import PushToTalk
        except ImportError as e:
            print(f"[agent] PTT 依赖缺失（{e}）")
            return None

        on_ai = ai_handler.handle if ai_handler else None

        ptt = PushToTalk(
            on_utterance=on_utterance,
            on_ai_utterance=on_ai,
            ptt_key=audio_cfg.get("ptt_key", "right_alt"),
            ai_key=audio_cfg.get("ai_key", "cmd_r"),
            toggle_key=audio_cfg.get("toggle_key"),
            device=device,
            status_window=status_window,
            kbd_monitor=kbd_monitor,
        )
        ptt.start()
        return ptt

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
    return monitor
