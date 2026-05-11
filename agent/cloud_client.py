"""
Voice Keyboard — 云端通信模块。

桌面客户端通过此模块与 Voice Keyboard Cloud 后端通信：
- 认证（登录/注册）
- STT 语音转文字（上传音频，返回文字）
- AI 处理（润色/写作/聊天/快捷键）
- 用量事件上报
- 订阅状态校验

使用方式：
    from agent.cloud_client import CloudClient
    
    client = CloudClient("https://your-api.com")
    await client.login("user@email.com", "password")
    
    text = await client.stt(pcm_bytes)
    result = await client.ai_process("帮我润色这段文字")
"""

import json
import time
from typing import Optional
from urllib.parse import urljoin

try:
    import httpx
    HAS_HTTPX = True
except ImportError:
    import requests
    HAS_HTTPX = False


class CloudError(Exception):
    """云端 API 错误"""
    pass


class CloudClient:
    """Voice Keyboard 云端通信客户端"""

    def __init__(self, base_url: str = "http://localhost:8000", timeout: int = 30):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.token: str = ""
        self.user: dict = {}
        self._cached_stats: Optional[dict] = None
        self._cache_time: float = 0

        if HAS_HTTPX:
            self._client = httpx.Client(timeout=timeout)
        else:
            self._session = requests.Session()

    # ── HTTP 请求 ─────────────────────────────────────────────────

    def _request(self, method: str, path: str, **kwargs) -> dict:
        url = urljoin(f"{self.base_url}/", path.lstrip("/"))
        headers = kwargs.pop("headers", {})
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"

        if HAS_HTTPX:
            resp = self._client.request(method, url, headers=headers, **kwargs)
        else:
            resp = self._session.request(method, url, headers=headers, **kwargs)

        if resp.status_code == 402:
            raise CloudError(resp.json().get("detail", "配额不足，请升级套餐"))
        if resp.status_code == 401:
            raise CloudError("登录已过期，请重新登录")

        try:
            data = resp.json()
        except json.JSONDecodeError:
            raise CloudError(f"API 返回非 JSON: {resp.text[:200]}")

        if not (200 <= resp.status_code < 300):
            raise CloudError(data.get("detail", f"HTTP {resp.status_code}"))

        return data

    def _get(self, path: str, **kwargs) -> dict:
        return self._request("GET", path, **kwargs)

    def _post(self, path: str, **kwargs) -> dict:
        return self._request("POST", path, **kwargs)

    def _put(self, path: str, **kwargs) -> dict:
        return self._request("PUT", path, **kwargs)

    # ── 认证 ───────────────────────────────────────────────────────

    def register(self, email: str, password: str, name: str = "") -> dict:
        """注册并自动登录"""
        data = self._post("/api/v1/auth/register", json={
            "email": email, "password": password, "name": name,
        })
        self.token = data["token"]
        self.user = data
        return data

    def login(self, email: str, password: str) -> dict:
        """登录"""
        data = self._post("/api/v1/auth/login", json={
            "email": email, "password": password,
        })
        self.token = data["token"]
        self.user = data
        return data

    def logout(self):
        """清除登录状态"""
        self.token = ""
        self.user = {}
        self._cached_stats = None

    def is_logged_in(self) -> bool:
        return bool(self.token)

    def get_me(self) -> dict:
        """获取当前用户信息"""
        data = self._get("/api/v1/auth/me")
        self.user = data
        return data

    def update_config(self, **kwargs) -> dict:
        """更新 STT/AI 配置"""
        return self._put("/api/v1/auth/config", json=kwargs)

    # ── STT ────────────────────────────────────────────────────────

    def stt(self, pcm: bytes) -> str:
        """
        上传 PCM 音频到云端进行语音识别。

        参数:
            pcm: 16kHz 16bit 单声道 PCM 音频数据

        返回:
            识别出的文字
        """
        data = self._post(
            "/api/v1/stt/transcribe",
            files={"audio": ("audio.pcm", pcm, "audio/L16;rate=16000")},
        )
        return data["text"]

    # ── AI 处理 ────────────────────────────────────────────────────

    def process_text(self, text: str, intent: str = "",
                     original: str = "") -> dict:
        """
        发送文字到云端进行 AI 处理。

        参数:
            text: 用户输入的文字
            intent: 意图（polish/write/chat/keyboard），自动检测可留空
            original: 润色模式的原文

        返回:
            {"result": str, "intent": str, "tokens": int}
        """
        return self._post("/api/v1/ai/process", json={
            "text": text, "intent": intent, "original": original,
        })

    def chat(self, message: str, history: list = None) -> dict:
        """
        聊天模式。

        返回:
            {"reply": str, "tokens": int}
        """
        return self._post("/api/v1/ai/chat", json={
            "message": message, "history": history or [],
        })

    def detect_intent(self, text: str) -> str:
        """仅检测意图，不处理文字"""
        data = self._post("/api/v1/ai/intent", json={"text": text})
        return data["intent"]

    # ── 用量事件上报 ──────────────────────────────────────────────

    def report_event(self, event_type: str, status: str = "success",
                     audio_duration: float = 0, input_chars: int = 0,
                     output_chars: int = 0, tokens: int = 0,
                     saved_time: int = 0, error: str = ""):
        """
        上报单条使用事件。

        可在客户端本地缓冲后批量上报，或单条实时上报。
        """
        return self._post("/api/v1/events/batch", json={
            "events": [{
                "type": event_type,
                "status": status,
                "audio_duration": audio_duration,
                "input_chars": input_chars,
                "output_chars": output_chars,
                "tokens": tokens,
                "saved_time": saved_time,
                "error": error,
            }],
        })

    def report_events_batch(self, events: list) -> dict:
        """
        批量上报事件（推荐方式）。

        events 格式:
            [{"type": "stt", "audio_duration": 3.5, "output_chars": 20}, ...]
        """
        return self._post("/api/v1/events/batch", json={"events": events})

    # ── 数据统计 ───────────────────────────────────────────────────

    def get_stats(self, force_refresh: bool = False) -> dict:
        """
        获取用户使用统计（带 30 秒缓存）。

        返回:
            total_stt_seconds, total_ai_calls, total_tokens,
            total_chars, total_saved_seconds,
            monthly_stt_seconds, monthly_ai_calls,
            monthly_stt_limit, monthly_ai_limit,
            usage_month,                           # ← 新增
            subscription_tier, subscription_expires_at
        """
        now = time.time()
        if not force_refresh and self._cached_stats and now - self._cache_time < 30:
            return self._cached_stats

        data = self._get("/api/v1/usage/summary")
        self._cached_stats = data
        self._cache_time = now
        return data

    def get_trends(self, days: int = 30) -> dict:
        """获取使用趋势数据"""
        return self._get(f"/api/v1/usage/trends?days={days}")

    def get_distribution(self, days: int = 30) -> dict:
        """获取功能使用分布"""
        return self._get(f"/api/v1/usage/distribution?days={days}")

    # ── 订阅 ───────────────────────────────────────────────────────

    def check_subscription(self) -> dict:
        """检查订阅状态"""
        return self._get("/api/v1/subscription/status")

    def get_plans(self) -> dict:
        """获取可用套餐列表"""
        return self._get("/api/v1/subscription/plans")

    def create_checkout(self, plan_id: str = "basic") -> dict:
        """
        创建结账链接。
        开发模式直接激活；生产模式返回 Lemon Squeezy 结账 URL。
        """
        return self._post(f"/api/v1/subscription/create-checkout?plan_id={plan_id}")

    # ── 健康检查 ───────────────────────────────────────────────────

    def health(self) -> dict:
        """检查服务器健康状态"""
        return self._get("/health")

    # ── 资源释放 ───────────────────────────────────────────────────

    def close(self):
        """关闭 HTTP 连接"""
        if HAS_HTTPX and hasattr(self, "_client"):
            self._client.close()
