"""
LLM 文字编辑器。

接收 Operation Window + 语音修改指令，调用 LLM 返回 Replacement Plan。

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
import re
import ssl

import certifi
import httpx
import requests
from agent.input_environment import ReplacementPlan
from agent.typeup_backend_auth import TypeUpBackendAuth

_SYSTEM_PROMPT = """你是一个专业的文字编辑助手。
用户会给你一段原文和一条修改指令。
请严格按照指令修改原文，只返回修改后的结果，不要添加任何解释或标点以外的内容。
如果指令不清晰，尽量按最合理的方式理解并修改。"""

_REPLACEMENT_PLAN_PROMPT = """你是 Voice Keyboard Engine 的 Replacement Plan 生成器。
用户会给你一个 Operation Window 和一条语音修改/删除指令。
你只能选择 Operation Window 内已经存在的一段连续原文作为 target_text。
如果指令要求删除，replacement_text 必须为空字符串。
如果指令要求修改，replacement_text 是替换 target_text 后的新文本。
不要改写整个 Operation Window，除非用户明确要求修改全部内容。
如果无法确定唯一目标，返回 confidence 为 low。
只返回 JSON，不要 Markdown，不要解释：
{"target_text":"Operation Window 中的原文片段","replacement_text":"替换文本","confidence":"high|medium|low"}"""


def _build_ssl_context() -> ssl.SSLContext:
    """统一构造显式使用 certifi 的 SSLContext，避免 .app 中默认 CA 路径失效。"""
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    ctx.verify_mode = ssl.CERT_REQUIRED
    ctx.check_hostname = True
    ctx.load_verify_locations(cafile=certifi.where())
    return ctx


def _build_httpx_client() -> httpx.Client:
    return httpx.Client(verify=_build_ssl_context(), timeout=30.0)


def _parse_replacement_plan(text: str) -> ReplacementPlan:
    cleaned = _strip_json_fence(text)
    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError:
        return ReplacementPlan(target_text="", confidence="low")
    if not isinstance(data, dict):
        return ReplacementPlan(target_text="", confidence="low")
    confidence = data.get("confidence", "high")
    if confidence not in {"high", "medium", "low"}:
        confidence = "low"
    target_text = data.get("target_text", "")
    replacement_text = data.get("replacement_text", "")
    return ReplacementPlan(
        target_text=target_text.strip() if isinstance(target_text, str) else "",
        replacement_text=replacement_text.strip() if isinstance(replacement_text, str) else "",
        confidence=confidence,
    )


def _strip_json_fence(text: str) -> str:
    stripped = text.strip()
    match = re.search(r"```(?:json)?\s*(.*?)\s*```", stripped, re.S)
    return match.group(1).strip() if match else stripped


class _TypeUpBackendLLM:
    def __init__(self, cfg: dict):
        self._auth = TypeUpBackendAuth(cfg, log_prefix="llm")
        self._auth.require_configured()

    def chat(self, messages: list[dict], max_tokens: int = 1000) -> str:
        resp = self._post_chat(messages, max_tokens=max_tokens)
        if resp.status_code == 401 and self._auth.reload_from_bridge():
            resp = self._post_chat(messages, max_tokens=max_tokens)
        if resp.status_code == 401 and self._auth.refresh_token:
            self._auth.refresh_access_token()
            resp = self._post_chat(messages, max_tokens=max_tokens)
        if not resp.ok:
            raise RuntimeError(self._auth.error_message(resp, "TypeUp 后端 LLM 请求失败"))
        return (resp.json().get("text") or "").strip()

    def _post_chat(self, messages: list[dict], max_tokens: int):
        return requests.post(
            f"{self._auth.api_base_url}/v1/llm/chat",
            headers=self._auth.auth_header(),
            json={"messages": messages, "temperature": 0.1, "max_tokens": max_tokens},
            timeout=65,
        )


class LLMEditor:
    def __init__(self, cfg: dict):
        provider = cfg.get("provider", "openai")

        if provider == "openai":
            from openai import OpenAI
            kwargs = {"api_key": cfg["api_key"], "http_client": _build_httpx_client()}
            if cfg.get("base_url"):
                kwargs["base_url"] = cfg["base_url"]
            self._client = OpenAI(**kwargs)
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

    def plan_replacement(self, window_text: str, instruction: str) -> ReplacementPlan:
        """Return a provider-proposed plan that the Input Environment verifies locally."""
        text = self.chat(
            _REPLACEMENT_PLAN_PROMPT,
            f"Operation Window：{window_text}\n\n语音指令：{instruction}",
        )
        return _parse_replacement_plan(text)

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
