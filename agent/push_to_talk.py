"""
Push-to-Talk 录音模块，支持三个热键：
  ptt_key  — 普通听写（dictation），松开后调 on_utterance
  edit_key — 语音编辑（edit），松开后调 on_edit_utterance
  ai_key   — AI 编程指令（ai），松开后调 on_ai_utterance

三个键互斥：一个按下时另两个无效。

dictation 模式支持实时分句：按住说话过程中，检测到句子间停顿即立刻触发 STT，
无需等到松键，适合连续说多句话的场景。
"""

import threading
import time
from typing import Callable, Optional

import sounddevice as sd
from pynput import keyboard as kb

from agent.audio_monitor import find_device, FRAME_BYTES, SILENCE_FRAMES, MIN_SPEECH_FRAMES
from agent.capture_path import UtteranceEvent
from agent.capture_path_runtime import CapturePathRuntime, PolishToggle
import agent.typer as _typer

SAMPLE_RATE = 16000

try:
    import webrtcvad as _webrtcvad
except ImportError:
    _webrtcvad = None


def _parse_key(key_str: str):
    try:
        return getattr(kb.Key, key_str)
    except AttributeError:
        return kb.KeyCode.from_char(key_str)


def _parse_keys(key_input) -> list:
    """支持单个字符串或字符串列表，统一返回 pynput key 列表。"""
    if isinstance(key_input, list):
        return [_parse_key(k) for k in key_input]
    return [_parse_key(key_input)]


class PushToTalk:
    def __init__(
        self,
        on_utterance:      Callable[[bytes], None],
        on_edit_utterance: Optional[Callable[[bytes], None]] = None,
        on_ai_utterance:   Optional[Callable[[bytes], None]] = None,
        on_ai_key_down:    Optional[Callable[[], None]] = None,
        ptt_key:           str = "right_alt",
        edit_key:          str = "right_ctrl",
        ai_key:            str = "right_shift",
        toggle_key:        Optional[str] = None,
        device:            Optional[str] = "auto",
        status_window=None,
        kbd_monitor=None,
    ):
        self._on_utterance      = on_utterance
        self._on_edit_utterance = on_edit_utterance
        self._on_ai_utterance   = on_ai_utterance
        self._on_ai_key_down    = on_ai_key_down
        self._kbd_monitor       = kbd_monitor
        self._ptt_keys          = _parse_keys(ptt_key)
        self._edit_keys         = _parse_keys(edit_key) if on_edit_utterance else []
        self._ai_keys           = _parse_keys(ai_key)   if on_ai_utterance   else []
        self._toggle_keys       = _parse_keys(toggle_key) if toggle_key else []
        self._device_hint       = device
        self._status            = status_window
        self._device_idx        = None
        self._capture_runtime   = CapturePathRuntime()
        self._buf: list[bytes]  = []
        self._stream: Optional[sd.RawInputStream] = None
        self._listener: Optional[kb.Listener]     = None

        # 双击 PTT 切换微润色模式
        self._double_tap_window       = self._capture_runtime.double_tap_window

        # 实时分句 VAD 状态（仅 dictate 模式使用）
        self._vad                            = None
        self._vad_raw: bytearray            = bytearray()
        self._vad_speech_frames: list[bytes] = []
        self._vad_in_speech                  = False
        self._vad_silent_count               = 0
        self._vad_sent_count                 = 0  # 本次按键已分句发出的数量

    def start(self):
        self._device_idx = find_device(self._device_hint)
        if self._device_idx is None:
            print("[ptt] 使用系统默认麦克风")
        else:
            info = sd.query_devices(self._device_idx)
            print(f"[ptt] 使用麦克风: {info['name']}")

        if _webrtcvad is not None:
            self._vad = _webrtcvad.Vad(2)
            print("[ptt] 实时分句已启用（说话中停顿可提前输出）")
        else:
            print("[ptt] webrtcvad 未安装，实时分句不可用")

        self._listener = kb.Listener(
            on_press=self._on_press,
            on_release=self._on_release,
        )
        self._listener.start()

        hints = [f"{'/'.join(str(k) for k in self._ptt_keys)} 说话（双击切换微润色）"]
        if self._edit_keys:
            hints.append(f"{'/'.join(str(k) for k in self._edit_keys)} 语音编辑")
        if self._ai_keys:
            hints.append(f"{'/'.join(str(k) for k in self._ai_keys)} AI编程")
        if self._toggle_keys:
            hints.append(f"{'/'.join(str(k) for k in self._toggle_keys)} 启停")
        print(f"[ptt] 按住 {' | '.join(hints)}")

    def stop(self):
        if self._listener:
            self._listener.stop()
        self._close_stream()

    def _set_status(self, state: str) -> None:
        if self._status is not None:
            self._status.set_state(state)

    # ── 键盘事件 ─────────────────────────────────────────────────

    def _on_press(self, key):
        if _typer.is_simulating():
            return  # 程序自身发出的按键，忽略
        if self._toggle_keys and key in self._toggle_keys:
            self._toggle_enabled()
            return
        # 顺手把退格/Delete/Enter 同步给 KeyboardMonitor，避免再开一个 CGEventTap
        if self._kbd_monitor is not None:
            try:
                self._kbd_monitor.process_press(key)
            except Exception:
                pass
        if key in self._ptt_keys:
            now = time.monotonic()
            start = self._capture_runtime.press_dictation(key, now)
            if isinstance(start, PolishToggle):
                mode_name = "微润色" if start.polish else "原文"
                self._set_status("polish_mode" if start.polish else "dictation_mode")
                print(f"[ptt] 切换为「{mode_name}」模式")
                return
            if start is None:
                return
            self._start_recording()
        elif self._edit_keys and key in self._edit_keys:
            start = self._capture_runtime.press_instruction_edit(key)
            if start is None:
                return
            self._start_recording()
        elif self._ai_keys and key in self._ai_keys:
            start = self._capture_runtime.press_instruction(key)
            if start is None:
                return
            if self._on_ai_key_down:
                self._on_ai_key_down()
            self._start_recording()

    def _on_release(self, key):
        if _typer.is_simulating():
            return
        mode = self._capture_runtime.release(key)
        if mode == "dictate":
            self._stop_recording(mode="dictate")
        elif mode == "edit":
            self._stop_recording(mode="edit")
        elif mode == "ai":
            self._stop_recording(mode="ai")

    # ── 录音控制 ─────────────────────────────────────────────────

    def _audio_callback(self, indata, frames, time_info, status):
        data = bytes(indata)
        self._buf.append(data)
        if self._capture_runtime.active_mode == "dictate" and self._vad is not None:
            self._vad_raw.extend(data)
            self._process_vad()

    def _process_vad(self):
        """消费 _vad_raw 中所有完整的 30ms 帧，检测句子边界。"""
        while len(self._vad_raw) >= FRAME_BYTES:
            frame = bytes(self._vad_raw[:FRAME_BYTES])
            del self._vad_raw[:FRAME_BYTES]

            is_speech = self._vad.is_speech(frame, SAMPLE_RATE)

            if is_speech:
                self._vad_in_speech    = True
                self._vad_silent_count = 0
                self._vad_speech_frames.append(frame)
            elif self._vad_in_speech:
                self._vad_speech_frames.append(frame)
                self._vad_silent_count += 1
                if self._vad_silent_count >= SILENCE_FRAMES:
                    self._dispatch_mid_sentence()

    def _dispatch_mid_sentence(self):
        """把当前积累的语音帧作为一句话立刻发出去，重置 VAD 状态。"""
        if len(self._vad_speech_frames) >= MIN_SPEECH_FRAMES:
            pcm = b"".join(self._vad_speech_frames)
            self._vad_sent_count += 1
            n = self._vad_sent_count
            print(f"[ptt] 分句{n} 识别中...    ", end="\r", flush=True)
            self._dispatch_utterance(
                UtteranceEvent.dictation(pcm, self._capture_runtime.polish_mode),
                name=f"PTT-mid-{n}",
            )
        self._vad_speech_frames = []
        self._vad_silent_count  = 0
        self._vad_in_speech     = False

    def _start_recording(self):
        self._buf = []
        self._vad_raw           = bytearray()
        self._vad_speech_frames = []
        self._vad_in_speech     = False
        self._vad_silent_count  = 0
        self._vad_sent_count    = 0
        self._stream = sd.RawInputStream(
            samplerate=SAMPLE_RATE,
            channels=1,
            dtype="int16",
            device=self._device_idx,
            blocksize=1024,
            callback=self._audio_callback,
        )
        self._stream.start()
        if self._capture_runtime.active_mode == "dictate":
            if self._capture_runtime.polish_mode:
                label = "微润色 录音中"
                self._set_status("polish_recording")
            else:
                label = "录音中"
                self._set_status("recording")
        elif self._capture_runtime.active_mode == "ai":
            label = "AI 指令录音中"
            self._set_status("ai_recording")
        else:
            label = "编辑指令录音中"
            self._set_status("recording")
        print(f"[ptt] {label}... ", end="\r", flush=True)

    def _stop_recording(self, mode: str):
        self._close_stream()

        if mode == "dictate" and self._vad is not None:
            self._process_vad()  # 处理流关闭前残留的音频字节

            # 松键时若仍在句子中间，把尾巴也发出去
            if self._vad_in_speech and len(self._vad_speech_frames) >= MIN_SPEECH_FRAMES:
                pcm = b"".join(self._vad_speech_frames)
                self._vad_sent_count += 1
                n = self._vad_sent_count
                print(f"[ptt] 分句{n} 识别中...    ", end="\r", flush=True)
                self._set_status("recognizing")
                self._dispatch_utterance(
                    UtteranceEvent.dictation(pcm, self._capture_runtime.polish_mode),
                    name=f"PTT-mid-{n}",
                )
            elif self._vad_sent_count == 0:
                # 全程未检测到任何句子（录音极短或全静音），回退到原有整段发送逻辑
                pcm = b"".join(self._buf)
                if len(pcm) < SAMPLE_RATE * 2 * 0.3:
                    print("[ptt] 录音太短，跳过    ")
                    self._set_status("idle")
                else:
                    print("[ptt] 识别中...    ", end="\r", flush=True)
                    self._set_status("recognizing")
                    self._dispatch_utterance(
                        UtteranceEvent.dictation(pcm, self._capture_runtime.polish_mode),
                        name="PTT-dictate",
                    )
            else:
                self._set_status("idle")
            self._buf = []
            return

        # dictate / edit / ai 模式（VAD 不可用时 dictate 也走这里）
        pcm = b"".join(self._buf)
        self._buf = []

        if len(pcm) < SAMPLE_RATE * 2 * 0.3:
            print("[ptt] 录音太短，跳过    ")
            self._set_status("idle")
            return

        if mode == "dictate":
            label    = "识别中"
            event    = UtteranceEvent.dictation(pcm, self._capture_runtime.polish_mode)
            self._set_status("recognizing")
        elif mode == "edit":
            label    = "解析编辑指令"
            event    = UtteranceEvent.instruction_edit(pcm)
            self._set_status("recognizing")
        else:
            label    = "解析AI指令"
            event    = UtteranceEvent.instruction(pcm)
            self._set_status("ai_processing")
        print(f"[ptt] {label}...    ", end="\r", flush=True)
        self._dispatch_utterance(event, name=f"PTT-{mode}")

    def _dispatch_utterance(self, event: UtteranceEvent, name: str) -> None:
        if event.mode == "dictation":
            callback = self._on_utterance
            args = (event.pcm, event.polish)
        elif event.mode == "instruction_edit":
            callback = self._on_edit_utterance
            args = (event.pcm,)
        else:
            callback = self._on_ai_utterance
            args = (event.pcm,)
        if callback is None:
            return
        threading.Thread(
            target=callback,
            args=args,
            daemon=True,
            name=name,
        ).start()

    def _close_stream(self):
        if self._stream:
            try:
                self._stream.stop()
                self._stream.close()
            except Exception:
                pass
            self._stream = None

    def _toggle_enabled(self) -> None:
        enabled = self._capture_runtime.toggle_enabled()
        if not enabled:
            self._buf = []
            self._close_stream()
            self._set_status("dictation_disabled")
            print("[ptt] 语音转写已关闭")
        else:
            self._set_status("dictation_enabled")
            print("[ptt] 语音转写已开启")
