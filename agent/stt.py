"""
STT（语音转文字）客户端。

支持的 provider：
  openai  — OpenAI Whisper API（默认）
  aliyun  — 阿里云 NLS（待接入）

调用方只需：
    client = STTClient(cfg["stt"])
    text   = client.transcribe(pcm_bytes)
"""

import io
import wave

SAMPLE_RATE = 16000


def _pcm_to_wav(pcm: bytes) -> bytes:
    """把原始 PCM（16kHz, 16bit, mono）打包成 WAV bytes。"""
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SAMPLE_RATE)
        w.writeframes(pcm)
    return buf.getvalue()


class STTClient:
    def __init__(self, cfg: dict):
        provider = cfg.get("provider", "openai")
        self._language = cfg.get("language", "zh")

        if provider == "openai":
            from openai import OpenAI
            self._model  = cfg.get("model", "whisper-1")
            self._client = OpenAI(api_key=cfg.get("api_key", ""))
            self._transcribe = self._openai_transcribe
        elif provider == "aliyun":
            raise NotImplementedError("阿里云 NLS 接入待开发，请先使用 openai")
        else:
            raise ValueError(f"未知 STT provider: {provider}，支持: openai")

    def transcribe(self, pcm: bytes) -> str:
        """传入 PCM bytes，返回识别文本（去除首尾空白）。"""
        return self._transcribe(pcm)

    def _openai_transcribe(self, pcm: bytes) -> str:
        wav = _pcm_to_wav(pcm)
        resp = self._client.audio.transcriptions.create(
            model=self._model,
            file=("audio.wav", wav, "audio/wav"),
            language=self._language,
        )
        return resp.text.strip()
