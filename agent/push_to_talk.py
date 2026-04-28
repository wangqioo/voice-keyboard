"""
Push-to-Talk 录音模块。

按住热键开始录音，松开后把 PCM 音频回调给调用方（通常是 STTClient）。
热键默认 right_alt（macOS 右 Option，Windows/Linux 右 Alt），可在 config.yaml 配置。
"""

import threading
from typing import Callable, Optional

import sounddevice as sd
from pynput import keyboard as kb

from agent.audio_monitor import find_device

SAMPLE_RATE = 16000


def _parse_key(key_str: str):
    """把配置文件里的字符串解析成 pynput Key。"""
    try:
        return getattr(kb.Key, key_str)
    except AttributeError:
        # 单字符，如 "f"
        return kb.KeyCode.from_char(key_str)


class PushToTalk:
    """
    按住热键录音，松开时把 PCM bytes 传给 on_utterance 回调。
    STT 调用在独立线程里执行，不阻塞键盘监听。
    """

    def __init__(
        self,
        on_utterance: Callable[[bytes], None],
        ptt_key: str = "right_alt",
        device: Optional[str] = "auto",
    ):
        self._on_utterance = on_utterance
        self._key          = _parse_key(ptt_key)
        self._device_hint  = device
        self._device_idx   = None   # 延迟解析（start 时）
        self._recording    = False
        self._buf: list[bytes] = []
        self._stream: Optional[sd.RawInputStream] = None
        self._listener: Optional[kb.Listener] = None

    def start(self):
        self._device_idx = find_device(self._device_hint)
        if self._device_idx is None:
            print("[ptt] 使用系统默认麦克风")
        else:
            info = sd.query_devices(self._device_idx)
            print(f"[ptt] 使用麦克风: {info['name']}")

        self._listener = kb.Listener(
            on_press=self._on_press,
            on_release=self._on_release,
        )
        self._listener.start()
        print(f"[ptt] 按住 {self._key} 说话，松开识别")

    def stop(self):
        if self._listener:
            self._listener.stop()
        self._close_stream()

    # ── 键盘事件 ─────────────────────────────────────────────────

    def _on_press(self, key):
        if key == self._key and not self._recording:
            self._start_recording()

    def _on_release(self, key):
        if key == self._key and self._recording:
            self._stop_recording()

    # ── 录音控制 ─────────────────────────────────────────────────

    def _audio_callback(self, indata, frames, time_info, status):
        self._buf.append(bytes(indata))

    def _start_recording(self):
        self._recording = True
        self._buf = []
        self._stream = sd.RawInputStream(
            samplerate=SAMPLE_RATE,
            channels=1,
            dtype="int16",
            device=self._device_idx,
            blocksize=1024,
            callback=self._audio_callback,
        )
        self._stream.start()
        print("[ptt] 录音中... ", end="\r", flush=True)

    def _stop_recording(self):
        self._recording = False
        self._close_stream()

        pcm = b"".join(self._buf)
        self._buf = []

        if len(pcm) < SAMPLE_RATE * 2 * 0.3:  # 少于 0.3 秒，过滤误触
            print("[ptt] 录音太短，跳过    ")
            return

        print("[ptt] 识别中...    ", end="\r", flush=True)
        threading.Thread(
            target=self._on_utterance,
            args=(pcm,),
            daemon=True,
            name="PTT-STT",
        ).start()

    def _close_stream(self):
        if self._stream:
            try:
                self._stream.stop()
                self._stream.close()
            except Exception:
                pass
            self._stream = None
