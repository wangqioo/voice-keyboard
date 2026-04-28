"""
VAD-based audio monitor.

从 USB UAC 麦克风（ESP32-S3）持续读取 PCM 16kHz 单声道音频，
用 webrtcvad 检测语音边界，把完整的一句话（bytes）回调给调用方。
"""

import threading
import time
from typing import Callable, Optional

import sounddevice as sd
import webrtcvad

SAMPLE_RATE   = 16000
FRAME_MS      = 30                                  # webrtcvad 支持 10/20/30ms
FRAME_SAMPLES = int(SAMPLE_RATE * FRAME_MS / 1000)  # 480 samples
FRAME_BYTES   = FRAME_SAMPLES * 2                   # int16 = 2 bytes/sample

# 连续多少帧静音 → 判定为句子结束（30ms × 12 = 360ms）
SILENCE_FRAMES = 12
# 最少多少帧语音才触发 STT，过滤单帧噪音（30ms × 4 = 120ms）
MIN_SPEECH_FRAMES = 4


def find_device(hint: Optional[str]) -> Optional[int]:
    """按名称片段查找输入设备，找不到返回 None（使用系统默认）。"""
    if hint and hint != "auto":
        # 用户直接指定设备序号
        if hint.isdigit():
            return int(hint)
        # 用户指定设备名称片段
        for i, d in enumerate(sd.query_devices()):
            if hint.lower() in d["name"].lower() and d["max_input_channels"] > 0:
                return i
        return None

    # 自动搜索：优先找 ESP32 / Voice Keyboard UAC 设备
    keywords = ["esp32", "voice keyboard", "voicekeyboard", "usb audio", "usb mic"]
    for i, d in enumerate(sd.query_devices()):
        if d["max_input_channels"] > 0:
            name = d["name"].lower()
            if any(k in name for k in keywords):
                return i
    return None  # 回退到系统默认麦克风


class AudioMonitor:
    """
    启动后在后台线程持续监听麦克风。
    检测到完整句子时调用 on_utterance(pcm_bytes)。
    """

    def __init__(
        self,
        on_utterance: Callable[[bytes], None],
        device: Optional[str] = "auto",
        vad_level: int = 2,
    ):
        self._on_utterance = on_utterance
        self._device_hint  = device
        self._vad          = webrtcvad.Vad(vad_level)
        self._thread: Optional[threading.Thread] = None
        self._stop         = threading.Event()

    def start(self):
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, daemon=True, name="AudioMonitor")
        self._thread.start()

    def stop(self):
        self._stop.set()

    def _run(self):
        device = find_device(self._device_hint)
        if device is None:
            print("[audio] 未找到 ESP32 UAC 麦克风，使用系统默认麦克风")
        else:
            info = sd.query_devices(device)
            print(f"[audio] 使用麦克风: {info['name']}")

        raw_buf        = bytearray()
        speech_frames  = []
        silent_count   = 0
        in_speech      = False

        def callback(indata, frames, time_info, status):
            raw_buf.extend(indata.tobytes())

        try:
            with sd.RawInputStream(
                samplerate=SAMPLE_RATE,
                channels=1,
                dtype="int16",
                device=device,
                blocksize=FRAME_SAMPLES,
                callback=callback,
            ):
                print("[audio] 开始监听，等待语音...")
                while not self._stop.is_set():
                    if len(raw_buf) < FRAME_BYTES:
                        time.sleep(0.005)
                        continue

                    frame = bytes(raw_buf[:FRAME_BYTES])
                    del raw_buf[:FRAME_BYTES]

                    is_speech = self._vad.is_speech(frame, SAMPLE_RATE)

                    if is_speech:
                        in_speech    = True
                        silent_count = 0
                        speech_frames.append(frame)
                    elif in_speech:
                        speech_frames.append(frame)
                        silent_count += 1
                        if silent_count >= SILENCE_FRAMES:
                            if len(speech_frames) >= MIN_SPEECH_FRAMES:
                                pcm = b"".join(speech_frames)
                                try:
                                    self._on_utterance(pcm)
                                except Exception as e:
                                    print(f"[audio] STT 回调异常: {e}")
                            speech_frames.clear()
                            silent_count = 0
                            in_speech    = False
        except Exception as e:
            print(f"[audio] 麦克风错误: {e}")
