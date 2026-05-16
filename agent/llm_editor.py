"""
LLM 文字编辑器。

接收原文 + 语音修改指令，调用 LLM 返回修改后的文字。

支持的 provider：
  openai      — GPT-4o-mini（快、便宜）
  aliyun      — 通义千问 Qwen（中文优化）
  volcengine  — 豆包 Doubao（字节跳动）
  zhipuai     — 智谱 AI GLM（参考 transmission_assistant 项目的集成方式）
  typeup_backend — TypeUp 后端代理（账号、权益、额度由后端处理）

扩展新 provider：
  在 __init__ 的 elif 链中添加分支，或参照 openai / zhipuai 分支实现。
"""

import json
import pathlib
import ssl
import time

import certifi
import httpx
import requests

_SYSTEM_PROMPT = """你是一个专业的文字编辑助手。
用户会给你一段原文和一条修改指令。
请严格按照指令修改原文，只返回修改后的结果，不要添加任何解释或标点以外的内容。
如果指令不清晰，尽量按最合理的方式理解并修改。"""


def _build_ssl_context() -> ssl.SSLContext:
    """统一构造显式使用 certifi 的 SSLContext，避免 .app 中默认 CA 路径失效。"""
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    ctx.verify_mode = ssl.CERT_REQUIRED
    ctx.check_hostname = True
    ctx.load_verify_locations(cafile=certifi.where())
    return ctx


def _build_httpx_client() -> httpx.Client:
    return httpx.Client(verify=_build_ssl_context(), timeout=30.0)


class _TypeUpBackendLLM:
    def __init__(self, cfg: dict):
        self._api_base_url = str(cfg.get("api_base_url") or cfg.get("base_url") or "http://localhost:8000").rstrip("/")
        self._access_token = str(cfg.get("access_token") or cfg.get("api_key") or "").strip()
        self._refresh_token = str(cfg.get("refresh_token") or "").strip()
        self._cloud_bridge_path = str(cfg.get("cloud_bridge_path") or "").strip()
        self._reload_tokens_from_bridge()
        if not self._api_base_url:
            raise RuntimeError("TypeUp 后端地址未配置")
        if not self._access_token:
            raise RuntimeError("请先登录 TypeUp 后端账号")

    def chat(self, messages: list[dict], max_tokens: int = 1000) -> str:
        resp = self._post_chat(messages, max_tokens=max_tokens)
        if resp.status_code == 401 and self._reload_tokens_from_bridge():
            resp = self._post_chat(messages, max_tokens=max_tokens)
        if resp.status_code == 401 and self._refresh_token:
            self._refresh_access_token()
            resp = self._post_chat(messages, max_tokens=max_tokens)
        if not resp.ok:
            raise RuntimeError(self._error_message(resp, "TypeUp 后端 LLM 请求失败"))
        return (resp.json().get("text") or "").strip()

    def _post_chat(self, messages: list[dict], max_tokens: int):
        return requests.post(
            f"{self._api_base_url}/v1/llm/chat",
            headers={"Authorization": f"Bearer {self._access_token}"},
            json={"messages": messages, "temperature": 0.1, "max_tokens": max_tokens},
            timeout=65,
        )

    def _refresh_access_token(self) -> None:
        resp = requests.post(
            f"{self._api_base_url}/v1/auth/refresh",
            json={"refresh_token": self._refresh_token},
            timeout=15,
        )
        if not resp.ok:
            raise RuntimeError(self._error_message(resp, "TypeUp 后端登录已过期"))
        data = resp.json()
        self._access_token = data["access_token"]
        self._refresh_token = data["refresh_token"]
        self._persist_tokens()

    def _reload_tokens_from_bridge(self) -> bool:
        if not self._cloud_bridge_path:
            return False
        try:
            path = pathlib.Path(self._cloud_bridge_path)
            if not path.exists():
                return False
            payload = json.loads(path.read_text(encoding="utf-8") or "{}")
            changed = False
            api_base_url = str(payload.get("apiBaseUrl") or "").strip().rstrip("/")
            access_token = str(payload.get("accessToken") or "").strip()
            refresh_token = str(payload.get("refreshToken") or "").strip()
            if api_base_url and api_base_url != self._api_base_url:
                self._api_base_url = api_base_url
                changed = True
            if access_token and access_token != self._access_token:
                self._access_token = access_token
                changed = True
            if refresh_token and refresh_token != self._refresh_token:
                self._refresh_token = refresh_token
                changed = True
            if changed:
                print("[llm] 已同步最新后端登录凭证")
            return changed
        except Exception as e:
            print(f"[llm] 读取后端登录凭证失败: {e}")
            return False

    def _persist_tokens(self) -> None:
        if not self._cloud_bridge_path:
            return
        try:
            path = pathlib.Path(self._cloud_bridge_path)
            payload = {}
            if path.exists():
                payload = json.loads(path.read_text(encoding="utf-8") or "{}")
            payload["accessToken"] = self._access_token
            payload["refreshToken"] = self._refresh_token
            payload["updatedAt"] = int(time.time() * 1000)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception as e:
            print(f"[llm] 同步后端登录凭证失败: {e}")

    @staticmethod
    def _error_message(resp, fallback: str) -> str:
        try:
            data = resp.json()
            return data.get("error", {}).get("message") or data.get("detail") or fallback
        except Exception:
            return f"{fallback}: HTTP {resp.status_code} {resp.text}"


class LLMEditor:
    def __init__(self, cfg: dict):
        provider = cfg.get("provider", "openai")

        if provider == "openai":
            from openai import OpenAI
            self._client = OpenAI(api_key=cfg["api_key"], http_client=_build_httpx_client())
            self._model  = cfg.get("model", "gpt-4o-mini")
            self._edit   = self._openai_edit

        elif provider == "aliyun":
            # 通义千问，兼容 OpenAI SDK
            from openai import OpenAI
            self._client = OpenAI(
                api_key=cfg["api_key"],
                base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
                http_client=_build_httpx_client(),
            )
            self._model = cfg.get("model", "qwen-turbo")
            self._edit  = self._openai_edit

        elif provider == "volcengine":
            # 豆包，兼容 OpenAI SDK
            from openai import OpenAI
            self._client = OpenAI(
                api_key=cfg["api_key"],
                base_url="https://ark.cn-beijing.volces.com/api/v3",
                http_client=_build_httpx_client(),
            )
            self._model = cfg.get("model", "doubao-lite-4k")
            self._edit  = self._openai_edit

        elif provider == "zhipuai":
            # 智谱 AI GLM，使用原生 zhipuai SDK，但显式注入带 certifi 的 httpx client，
            # 避免打包成 .app 后默认 CA 路径失效。
            try:
                from zhipuai import ZhipuAI
            except ImportError:
                raise ImportError(
                    "使用 zhipuai provider 需要安装 zhipuai：pip install zhipuai"
                )
            self._zhipu_client = ZhipuAI(
                api_key=cfg["api_key"],
                http_client=_build_httpx_client(),
            )
            self._model        = cfg.get("model", "glm-4-flash")
            self._edit         = self._zhipu_edit

        elif provider == "typeup_backend":
            self._backend_client = _TypeUpBackendLLM(cfg)
            self._edit = self._backend_edit

        else:
            raise ValueError(
                f"未知 LLM provider: {provider!r}，"
                f"支持: openai / aliyun / volcengine / zhipuai / typeup_backend"
            )

    def edit(self, original: str, instruction: str) -> str:
        """用 instruction 修改 original，返回修改后的文字。"""
        return self._edit(original, instruction)

    def chat_stream(self, system_prompt: str, user_message: str):
        """流式调用，逐 token yield 文字片段。"""
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user",   "content": user_message},
        ]
        if hasattr(self, "_backend_client"):
            yield self._backend_client.chat(messages, max_tokens=1000)
            return
        if hasattr(self, "_zhipu_client"):
            stream = self._zhipu_client.chat.completions.create(
                model=self._model, messages=messages,
                stream=True, temperature=0.7, max_tokens=1000,
            )
        else:
            stream = self._client.chat.completions.create(
                model=self._model, messages=messages,
                stream=True, temperature=0.7, max_tokens=1000,
            )
        for chunk in stream:
            delta = chunk.choices[0].delta.content
            if delta:
                yield delta

    def chat(self, system_prompt: str, user_message: str) -> str:
        """通用 LLM 调用，返回模型回复文字。"""
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user",   "content": user_message},
        ]
        if hasattr(self, "_backend_client"):
            return self._backend_client.chat(messages, max_tokens=200)
        if hasattr(self, "_zhipu_client"):
            resp = self._zhipu_client.chat.completions.create(
                model=self._model,
                messages=messages,
                temperature=0.1,
                max_tokens=200,
            )
        else:
            resp = self._client.chat.completions.create(
                model=self._model,
                messages=messages,
                temperature=0.1,
                max_tokens=200,
            )
        return resp.choices[0].message.content.strip()

    def _openai_edit(self, original: str, instruction: str) -> str:
        resp = self._client.chat.completions.create(
            model=self._model,
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user",   "content": f"原文：{original}\n\n修改指令：{instruction}"},
            ],
            temperature=0.1,
            max_tokens=2000,
        )
        return resp.choices[0].message.content.strip()

    def _zhipu_edit(self, original: str, instruction: str) -> str:
        resp = self._zhipu_client.chat.completions.create(
            model=self._model,
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user",   "content": f"原文：{original}\n\n修改指令：{instruction}"},
            ],
            temperature=0.1,
            max_tokens=2000,
        )
        return resp.choices[0].message.content.strip()

    def _backend_edit(self, original: str, instruction: str) -> str:
        return self._backend_client.chat(
            [
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": f"原文：{original}\n\n修改指令：{instruction}"},
            ],
            max_tokens=2000,
        )
