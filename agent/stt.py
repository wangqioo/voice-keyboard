"""
STT（语音转文字）客户端，支持多家云服务。

支持的 provider：
  openai      — OpenAI Whisper API（多语言通用）
  aliyun      — 阿里云智能语音 NLS（中文最优，支持方言）
  volcengine  — 火山引擎 ASR（字节跳动，中文优化）
  zhipuai     — 智谱 AI GLM-4-Voice（参考 transmission_assistant 项目的集成方式）

调用方只需：
    client = STTClient(cfg["stt"])
    text   = client.transcribe(pcm_bytes)   # pcm: 16kHz 16bit mono

扩展新 provider：
    1. 实现一个类，提供 transcribe(pcm: bytes) -> str 方法
    2. 在文件末尾的 _PROVIDERS 字典中注册
    3. 在 config.yaml / .env 中指定 provider 名称即可
"""

import base64
import io
import json
import time
import uuid
import wave

import requests

SAMPLE_RATE = 16000


def _pcm_to_wav(pcm: bytes) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SAMPLE_RATE)
        w.writeframes(pcm)
    return buf.getvalue()


# ── OpenAI Whisper ────────────────────────────────────────────────

class _OpenAISTT:
    def __init__(self, cfg: dict):
        from openai import OpenAI
        self._client   = OpenAI(api_key=cfg["api_key"])
        self._model    = cfg.get("model", "whisper-1")
        self._language = cfg.get("language", "zh")

    def transcribe(self, pcm: bytes) -> str:
        wav  = _pcm_to_wav(pcm)
        resp = self._client.audio.transcriptions.create(
            model=self._model,
            file=("audio.wav", wav, "audio/wav"),
            language=self._language,
        )
        return resp.text.strip()


# ── 阿里云 NLS ────────────────────────────────────────────────────

class _AliyunSTT:
    """
    阿里云智能语音·一句话识别（REST）。

    所需配置：
      access_key_id      阿里云 AccessKey ID
      access_key_secret  阿里云 AccessKey Secret
      app_key            NLS 应用的 Appkey（控制台创建项目后可见）
      region             地域，默认 cn-shanghai（也支持 cn-beijing）
      language           zh（中文，默认）/ en（英文）
    """

    _TOKEN_URL = "https://nls-gateway.{region}.aliyuncs.com/token"
    _ASR_URL   = "https://nls-gateway.{region}.aliyuncs.com/stream/v1/asr"

    def __init__(self, cfg: dict):
        self._access_key_id     = cfg["access_key_id"]
        self._access_key_secret = cfg["access_key_secret"]
        self._app_key           = cfg["app_key"]
        self._region            = cfg.get("region", "cn-shanghai")
        self._language          = cfg.get("language", "zh")
        self._token             = None
        self._token_expiry      = 0.0

    def _get_token(self) -> str:
        if self._token and time.time() < self._token_expiry - 60:
            return self._token
        url  = self._TOKEN_URL.format(region=self._region)
        resp = requests.post(url, json={
            "AccessKeyId":     self._access_key_id,
            "AccessKeySecret": self._access_key_secret,
        }, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        self._token        = data["Token"]["Id"]
        self._token_expiry = float(data["Token"]["ExpireTime"])
        return self._token

    def transcribe(self, pcm: bytes) -> str:
        token = self._get_token()
        wav   = _pcm_to_wav(pcm)
        url   = self._ASR_URL.format(region=self._region)
        resp  = requests.post(
            url,
            params={
                "appkey":                          self._app_key,
                "format":                          "wav",
                "sample_rate":                     SAMPLE_RATE,
                "enable_punctuation_prediction":   "true",
                "enable_inverse_text_normalization":"true",
            },
            headers={
                "X-NLS-Token":  token,
                "Content-Type": "application/octet-stream",
            },
            data=wav,
            timeout=15,
        )
        resp.raise_for_status()
        result = resp.json()
        if result.get("status") == 20000000:
            return result.get("result", "").strip()
        raise RuntimeError(f"阿里云 NLS 错误: {result.get('message', result)}")


# ── 火山引擎 ASR（字节跳动）─────────────────────────────────────────

class _VolcengineSTT:
    """
    火山引擎语音识别·录音文件识别（HTTP）。

    所需配置：
      app_id   火山引擎应用 ID（控制台 → 语音技术 → 应用管理）
      token    访问令牌（控制台生成的长期 Token）
      cluster  集群，默认 volcengine_streaming_common
      language 语言，默认 zh-CN
    """

    _ASR_URL = "https://openspeech.bytedance.com/api/v1/asr"

    def __init__(self, cfg: dict):
        self._app_id   = cfg["app_id"]
        self._token    = cfg["token"]
        self._cluster  = cfg.get("cluster", "volcengine_streaming_common")
        self._language = cfg.get("language", "zh-CN")

    def transcribe(self, pcm: bytes) -> str:
        import struct, tempfile, os
        samples = struct.unpack(f'{len(pcm)//2}h', pcm)
        print(f"[stt] PCM {len(pcm)}B, 时长{len(pcm)/16000/2:.2f}s, 幅度 min={min(samples)} max={max(samples)}")
        wav = _pcm_to_wav(pcm)
        tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
        tmp.write(wav); tmp.close()
        print(f"[stt] WAV 已保存至 {tmp.name}（可用播放器验证）")
        audio_b64 = base64.b64encode(wav).decode()
        print(f"[stt] base64 长度: {len(audio_b64)}")

        payload = {
            "app": {
                "appid":   self._app_id,
                "token":   self._token,
                "cluster": self._cluster,
            },
            "user":  {"uid": "voice-keyboard"},
            "audio": {
                "format":  "wav",
                "rate":    SAMPLE_RATE,
                "bits":    16,
                "channel": 1,
                "codec":   "raw",
            },
            "request": {
                "reqid":          str(uuid.uuid4()),
                "nbest":          1,
                "show_utterances": False,
                "result_type":    "single",
                "sequence":       -1,
                "audio":          audio_b64,
            },
        }
        resp = requests.post(
            self._ASR_URL,
            data=json.dumps(payload),
            headers={
                "Authorization": f"Bearer; {self._token}",
            },
            timeout=15,
        )
        if not resp.ok:
            raise RuntimeError(f"火山引擎 ASR HTTP {resp.status_code}: {resp.text}")
        resp.raise_for_status()
        result = resp.json()
        if result.get("code") == 1000:
            utterances = result.get("utterances") or []
            return "".join(u.get("text", "") for u in utterances).strip()
        raise RuntimeError(f"火山引擎 ASR 错误: {result.get('message', result)}")


# ── GLM 前缀清理 ─────────────────────────────────────────────────

_GLM_PREAMBLE_STARTS = (
    "好的", "明白", "收到", "当然", "没问题", "知道了", "了解", "好！", "好，",
)

def _strip_glm_preamble(text: str) -> str:
    """去掉 GLM-4-Voice 可能在转写结果前加的对话性前缀。

    两种情形：
      1. 冒号型：前 25 字内出现「：」→ 截取冒号后内容
         例："好的，请听逐字转录：明天九点出发"
      2. 句末型：以常见客套词开头且第一句较短 → 截取第一个句末标点后内容
         例："好的，我会记录的。明天早上10点出发去高铁站。"
    """
    if not text:
        return text
    # 情形1：冒号
    colon_pos = text.find("：")
    if 0 < colon_pos < 25:
        return text[colon_pos + 1:].strip()
    # 情形2：句末标点
    if any(text.startswith(s) for s in _GLM_PREAMBLE_STARTS):
        import re
        m = re.search(r'[。！？]', text)
        if m and m.end() < len(text):
            return text[m.end():].strip()
    return text


# ── 智谱 AI GLM-4-Voice ───────────────────────────────────────────
#
# 参考：transmission_assistant 项目（github.com/wangqioo/transmission_assistant）
# 该项目使用 zhipuai SDK 与智谱 AI 交互，此处以同样方式接入语音转写能力。
#
# GLM-4-Voice 通过 chat.completions 接口接收 base64 编码的音频，
# 返回转写文字。相比其他 provider，无需额外 STT 服务，一个 API Key 全搞定。
#
# 所需配置：
#   api_key  智谱 AI API Key（https://open.bigmodel.cn/）
#   model    默认 glm-4-voice（也可指定其他支持音频的模型）
#   language 语言提示，默认 zh（仅作为 prompt 提示，不影响 API 参数）

class _ZhipuSTT:
    """
    智谱 AI GLM-4-Voice 语音转写。

    使用 zhipuai Python SDK，与 transmission_assistant 项目的集成方式一致：
      from zhipuai import ZhipuAI
      client = ZhipuAI(api_key=api_key)

    音频以 base64 WAV 格式通过 chat completions 发送给 GLM-4-Voice，
    模型直接返回转写文字。
    """

    _PROMPT_ZH = (
        "把这段录音里说的话抄写下来。"
        "只写说话内容本身，不要加任何开头语，不要加冒号，不要任何引导语或说明。"
        "数字用阿拉伯数字（如7、10、100）。"
    )
    _PROMPT_EN = "Write down exactly what is said in this audio. Output only the spoken words, no intro, no colon, no explanation."

    def __init__(self, cfg: dict):
        try:
            from zhipuai import ZhipuAI
        except ImportError:
            raise ImportError(
                "使用 zhipuai provider 需要安装 zhipuai：pip install zhipuai"
            )
        self._client   = ZhipuAI(api_key=cfg["api_key"])
        self._model    = cfg.get("model", "glm-4-voice")
        self._language = cfg.get("language", "zh")

    def transcribe(self, pcm: bytes) -> str:
        wav      = _pcm_to_wav(pcm)
        audio_b64 = base64.b64encode(wav).decode()

        prompt = self._PROMPT_ZH if self._language.startswith("zh") else self._PROMPT_EN

        resp = self._client.chat.completions.create(
            model=self._model,
            messages=[{
                "role": "user",
                "content": [
                    {
                        "type": "input_audio",
                        "input_audio": {
                            "data":   audio_b64,
                            "format": "wav",
                        },
                    },
                    {
                        "type": "text",
                        "text": prompt,
                    },
                ],
            }],
        )
        result = resp.choices[0].message.content.strip()
        result = _strip_glm_preamble(result)
        return result


# ── 科大讯飞语音听写（流式 WebSocket）────────────────────────────

class _XunfeiSTT:
    """
    科大讯飞语音听写（流式版）WebSocket API。

    所需配置：
      app_id     讯飞应用 APPID
      api_key    讯飞 APIKey
      api_secret 讯飞 APISecret
      language   语言，默认 zh_cn

    需要安装：pip install websocket-client
    """

    _HOST = "iat-api.xfyun.cn"
    _PATH = "/v2/iat"

    def __init__(self, cfg: dict):
        try:
            import websocket as _ws
            self._ws = _ws
        except ImportError:
            raise ImportError("使用 xunfei provider 需要安装：pip install websocket-client")
        self._app_id     = cfg["app_id"]
        self._api_key    = cfg["api_key"]
        self._api_secret = cfg["api_secret"]
        self._language   = cfg.get("language", "zh_cn")

    def _build_url(self) -> str:
        import hashlib, hmac as _hmac
        from datetime import datetime, timezone
        from urllib.parse import urlencode

        date = datetime.now(timezone.utc).strftime("%a, %d %b %Y %H:%M:%S GMT")
        sig_origin = f"host: {self._HOST}\ndate: {date}\nGET {self._PATH} HTTP/1.1"
        sig = base64.b64encode(
            _hmac.new(self._api_secret.encode(), sig_origin.encode(), hashlib.sha256).digest()
        ).decode()
        auth = base64.b64encode(
            f'api_key="{self._api_key}", algorithm="hmac-sha256", '
            f'headers="host date request-line", signature="{sig}"'.encode()
        ).decode()
        return f"wss://{self._HOST}{self._PATH}?" + urlencode({
            "authorization": auth, "date": date, "host": self._HOST,
        })

    def transcribe(self, pcm: bytes) -> str:
        import threading

        CHUNK  = 1280  # 40ms @ 16kHz 16bit mono
        chunks = [pcm[i:i + CHUNK] for i in range(0, len(pcm), CHUNK)]
        segments: dict[int, str] = {}
        err     = [None]
        done    = threading.Event()

        def on_open(ws):
            def _send():
                n = len(chunks)
                for idx, chunk in enumerate(chunks):
                    status = 0 if idx == 0 else (2 if idx == n - 1 else 1)
                    # 单块音频：status=2 仍须携带 common/business
                    frame: dict = {"data": {
                        "status":   status,
                        "format":   "audio/L16;rate=16000",
                        "encoding": "raw",
                        "audio":    base64.b64encode(chunk).decode(),
                    }}
                    if idx == 0:
                        frame["common"]   = {"app_id": self._app_id}
                        frame["business"] = {
                            "language": self._language,
                            "domain":   "iat",
                            "accent":   "mandarin",
                            "ptt":      1,
                            "nunum":    1,
                            "dwa":      "wpgs",
                        }
                    ws.send(json.dumps(frame))
                    time.sleep(0.04)
                if n == 1:
                    # 单块时补发一个空的 status=2 关闭帧
                    ws.send(json.dumps({"data": {
                        "status": 2, "format": "audio/L16;rate=16000",
                        "encoding": "raw", "audio": "",
                    }}))
            threading.Thread(target=_send, daemon=True).start()

        def on_message(ws, msg):
            data   = json.loads(msg)
            code   = data.get("code", -1)
            if code != 0:
                err[0] = f"讯飞 code={code}: {data.get('message', '')}"
                ws.close(); return
            body   = data.get("data", {})
            result = body.get("result", {})
            pgs    = result.get("pgs", "apd")
            rg     = result.get("rg", [])
            sn     = result.get("sn", 0)
            text   = "".join(
                cw.get("w", "")
                for w in result.get("ws", [])
                for cw in w.get("cw", [])
            )
            if pgs == "rpl" and len(rg) >= 2:
                for i in range(rg[0], rg[1] + 1):
                    segments.pop(i, None)
            segments[sn] = text
            if body.get("status") == 2:
                ws.close(); done.set()

        def on_error(ws, e):
            err[0] = str(e); done.set()

        def on_close(ws, *_):
            done.set()

        app = self._ws.WebSocketApp(
            self._build_url(),
            on_open=on_open, on_message=on_message,
            on_error=on_error, on_close=on_close,
        )
        threading.Thread(target=app.run_forever, daemon=True).start()
        done.wait(timeout=15)

        if err[0]:
            raise RuntimeError(err[0])
        return "".join(segments[k] for k in sorted(segments)).strip()


# ── 统一入口 ──────────────────────────────────────────────────────
#
# 注册新 provider：在此 dict 中添加 "name": ClassName 即可，
# config.yaml / .env 中填写对应 provider 名称后自动生效。

_PROVIDERS: dict[str, type] = {
    "openai":     _OpenAISTT,
    "aliyun":     _AliyunSTT,
    "volcengine": _VolcengineSTT,
    "zhipuai":    _ZhipuSTT,
    "xunfei":     _XunfeiSTT,
}


class STTClient:
    def __init__(self, cfg: dict):
        provider = cfg.get("provider", "openai")
        cls = _PROVIDERS.get(provider)
        if cls is None:
            raise ValueError(
                f"未知 STT provider: {provider!r}，"
                f"支持: {', '.join(_PROVIDERS)}"
            )
        self._impl = cls(cfg)

    def transcribe(self, pcm: bytes) -> str:
        return self._impl.transcribe(pcm)
