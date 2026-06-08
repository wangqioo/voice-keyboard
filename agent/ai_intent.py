"""Instruction Mode intent classification.

This module keeps the LLM prompt, JSON cleanup, and deterministic fallbacks out
of AIHandler so the handler can stay focused on orchestration and side effects.
"""

import json
from dataclasses import dataclass
from typing import Literal, Protocol

from agent.intent_model import load_intent_model
from agent.intent_overrides import find_override
from agent.memo import (
    MemoRecord,
    resolve_memo_key,
)


class ChatLLM(Protocol):
    def chat(self, system: str, user: str) -> str:
        ...


class MemoEntries(Protocol):
    def keys(self) -> list[str]:
        ...

    def get(self, key: str) -> str | None:
        ...


@dataclass(frozen=True)
class IntentContext:
    text: str
    selected: str = ""
    recent_text: str = ""
    active_application: str = ""
    shortcuts: tuple[str, ...] = ()
    shortcut_entries: tuple["ShortcutIntentEntry", ...] = ()
    memo_records: tuple[MemoRecord, ...] = ()

    @property
    def memo_keys(self) -> tuple[str, ...]:
        return tuple(record.key for record in self.memo_records)


@dataclass(frozen=True)
class ShortcutIntentEntry:
    name: str
    aliases: tuple[str, ...] = ()
    risk: str = "normal"
    source: str = ""
    application: str = ""
    kind: str = "shortcut"


IntentSource = Literal["local", "llm", "cache"]
IntentConfidence = Literal["high", "medium", "low"]


@dataclass(frozen=True)
class IntentClassification:
    result: dict
    source: IntentSource
    confidence: IntentConfidence = "high"
    cache_hit: bool = False


@dataclass(frozen=True)
class LocalIntentMatch:
    result: dict
    confidence: IntentConfidence = "high"
    reason: str = ""


@dataclass(frozen=True)
class IntentFallbackOptions:
    multi_step_guard: bool = True
    selected_edit_override: bool = True
    memo_fuzzy_recall: bool = True
    llm_cache: bool = True
    intent_overrides: bool = True
    intent_overrides_path: str = ""
    intent_model: bool = False
    intent_model_path: str = ""
    intent_model_min_similarity: float = 1.0
    local_confidence_threshold: IntentConfidence = "high"

    @classmethod
    def from_config(cls, cfg: dict | None) -> "IntentFallbackOptions":
        if not isinstance(cfg, dict):
            return cls()
        memo_fuzzy_recall = cfg.get(
            "memo_fuzzy_recall",
            cfg.get("reusable_text_memory_fuzzy_recall", True),
        )
        return cls(
            multi_step_guard=bool(cfg.get("multi_step_guard", True)),
            selected_edit_override=bool(cfg.get("selected_edit_override", True)),
            memo_fuzzy_recall=bool(memo_fuzzy_recall),
            llm_cache=bool(cfg.get("llm_cache", True)),
            intent_overrides=bool(cfg.get("intent_overrides", True)),
            intent_overrides_path=str(cfg.get("intent_overrides_path", "")),
            intent_model=bool(cfg.get("intent_model", bool(cfg.get("intent_model_path", "")))),
            intent_model_path=str(cfg.get("intent_model_path", "")),
            intent_model_min_similarity=float(cfg.get("intent_model_min_similarity", 1.0)),
            local_confidence_threshold=str(cfg.get("local_confidence_threshold", "high")),
        )


_CLASSIFY_SYSTEM = """你是 Voice Keyboard Engine 的 Instruction Mode 意图分类器。根据用户说的话返回一个JSON对象，不要包含任何其他内容。

判断依据是用户说的话，而不是是否有 Explicit Selection（明确选区）。Explicit Selection 只是上下文参考。

本软件是通用的语音驱动键盘效率层：用户说出想完成的键盘式操作，引擎把它解释为当前输入环境里的打字、编辑、快捷键、撤回或备忘调用。它不是 chat-first 或 AI-native 产品，AI 只是把语音解释成用户操作的一种实现手段。

本软件的功能：
- Dictation Mode：语音转文字，原样打入当前输入框
- Instruction Mode，有以下几种 Voice Keyboard Operation：
  * 快捷键/系统动作：说出操作名称直接执行本地 Shortcut Catalog 里的快捷键或系统动作
  * 打开应用：打开本地应用，动作名称必须来自本地 Shortcut Catalog，例如"打开飞书"
  * 编辑：优先修改/润色/删除 Explicit Selection（明确选区）；没有明确选区时，默认修改最近一次由引擎输出的 Tracked Segment；用户明确说“全文/全部/整个输入框”等整体范围时处理当前输入环境窗口
  * 写作：给出主题或要求，由引擎生成内容并逐句打入
  * 撤回：触发当前输入环境的撤销快捷键，优先使用应用自己的撤销栈
  * 备忘：保存、读取、删除或列出用户常用文本片段（手机号、邮箱、地址、常用回复等）
- 辅助反馈：提问、聊天、不确定、没有明确编辑或写作指令时，只在状态框显示简短 feedback，不向输入框写入聊天内容

规则（按优先级）：
1. 当前运行时只执行一个主要 Voice Keyboard Operation。用户明确说出多个步骤（例如"先...再..."、"...然后..."、"...并且..."）时，返回 {"type":"chat","reply":"这个需要分步执行，请先说第一步"}，不要自行合并或规划。
2. 明确的快捷键或系统动作 → {"type":"shortcut","name":"动作名称"}。动作必须来自本地 Shortcut Catalog，表示触发该名称对应的本地动作；打开应用、打开系统设置也走这个类型。name 必须优先使用可用快捷键列表里的原始名称。
3. 撤回/撤销/恢复上一步操作 → {"type":"shortcut","name":"撤销"}。只有在本地 Shortcut Catalog 没有"撤销"时才返回 {"type":"undo"}。
4. 明确要求删除/清除 Explicit Selection（明确选区），或说“删除/清空/全部删除”等整体删除（不是修改，是直接删掉） → {"type":"delete"}
5. 用户要保存备忘片段（"记一下"、"记住"、"备忘"、"存一下"等关键词）。key 是用户给这条文本起的名字（如"手机号"、"邮箱"、"家庭地址"），value 是要保存的文本：
   - 如果有 Explicit Selection（明确选区），value 就是该明确选区（此时返回空字符串作为 value，由程序自动使用）
   - 如果用户在话里直接说出了内容（如"我的邮箱是 abc@xx.com"），value 就是那段内容
   → {"type":"memo_save","key":"...","value":"..."}
6. 用户要查询已保存的备忘（"我的xxx是什么"、"我的xxx"、"xxx是多少"、"xxx是啥"等问句）。
   匹配 key 时必须容忍以下情况：
   - STT 同音字错误：如"话"→"画"、"号"→"好"、"件"→"建"，根据上下文判断
   - 近义说法：如"最喜欢说"vs"最爱说"vs"常说"，"地址"vs"住址"
   - 部分省略：用户可能只说 key 的核心部分（如 key 是"白光宇最喜欢说的话"，用户说"白光宇说什么"也算）
   只要用户的问题在语义上对得上某个已保存的 key，就大胆返回 memo_recall。key 字段必须填【已保存列表里那个原始 key】，不要返回用户口述的版本。
   → {"type":"memo_recall","key":"已保存列表里的原始key"}
7. 用户要删除备忘（"忘记我的xxx"、"删掉xxx的记录"） → {"type":"memo_delete","key":"..."}
8. 用户要查看/列出所有备忘（"列出所有备忘"、"我都记了什么"、"导出记忆库"、"看一下我的记忆"等） → {"type":"memo_list"}
9. 用户说的话明确要求修改/润色/编辑已有文字 → {"type":"edit"}
10. 用户给出主题、要求或提纲，让引擎生成新内容 → {"type":"write"}
11. 其他（提问、聊天、不确定、没有明确编辑或写作指令） → {"type":"chat","reply":"回答或提示，最多50字"}"""

_EDIT_HINTS = (
    "改", "修改", "改写", "编辑", "润色", "优化", "整理", "精简", "扩写", "缩短",
    "正式", "口语", "自然", "通顺", "礼貌", "专业", "调整", "换个说法",
    "翻译", "译成", "英文", "英语", "中文", "日文", "日语", "韩文", "韩语",
    "合规", "合规性", "合法", "敏感词", "风控", "审核",
)

_MULTI_STEP_MARKERS = (
    "先", "再", "然后", "并且", "并", "接着", "之后", "最后",
)

_MULTI_STEP_FEEDBACK = "这个需要分步执行，请先说第一步"

_COMPACT_CLASSIFY_SYSTEM = """You classify Voice Keyboard instruction intent. Return only one JSON object.

Allowed type values: shortcut, undo, delete, edit, write, memo_save, memo_recall, memo_delete, memo_list, chat.
Rules:
1. Execute one primary operation only. For multi-step requests return chat and ask the user to say the first step.
2. shortcut.name must come from Shortcut Catalog.
3. Use edit for modifying selected or recently typed text. Use write for generating new content.
4. Use delete for direct selected-text or whole-content deletion.
5. Use memo_* for memory save, recall, delete, or list.
6. Use chat for questions or uncertainty; keep reply under 30 Chinese characters.
"""

_INTENT_CACHE_MAX = 64
_INTENT_CACHE: dict[tuple, dict] = {}
_INTENT_CACHE_ORDER: list[tuple] = []



def classify_intent(
    llm: ChatLLM,
    ctx: IntentContext,
    fallbacks: IntentFallbackOptions | None = None,
) -> dict:
    return _strip_intent_meta(classify_intent_details(llm, ctx, fallbacks).result)


def classify_intent_details(
    llm: ChatLLM,
    ctx: IntentContext,
    fallbacks: IntentFallbackOptions | None = None,
) -> IntentClassification:
    fallbacks = fallbacks or IntentFallbackOptions()
    local_match = classify_local_intent_match(ctx, fallbacks)
    if local_match is not None and _confidence_allows_local(local_match.confidence, fallbacks):
        return IntentClassification(
            _with_intent_meta(local_match.result, "local", local_match.confidence),
            "local",
            local_match.confidence,
        )

    cache_key = _intent_cache_key(ctx)
    if fallbacks.llm_cache:
        cached = _cache_get(cache_key)
        if cached is not None:
            return IntentClassification(
                _with_intent_meta(cached, "cache", "high", cache_hit=True),
                "cache",
                "high",
                cache_hit=True,
            )

    raw = llm.chat(_COMPACT_CLASSIFY_SYSTEM, _build_user_message(ctx))
    result = apply_intent_fallbacks(_parse_json_object(raw), ctx, fallbacks)
    if fallbacks.llm_cache:
        _cache_put(cache_key, result)
    return IntentClassification(_with_intent_meta(result, "llm", "high"), "llm", "high")


def classify_local_intent(
    ctx: IntentContext,
    fallbacks: IntentFallbackOptions | None = None,
) -> dict | None:
    match = classify_local_intent_match(ctx, fallbacks)
    return None if match is None else match.result


def classify_local_intent_match(
    ctx: IntentContext,
    fallbacks: IntentFallbackOptions | None = None,
) -> LocalIntentMatch | None:
    fallbacks = fallbacks or IntentFallbackOptions()
    override = _corrected_override_from_text(ctx, fallbacks)
    if override:
        return LocalIntentMatch(override, "high", "corrected_override")

    model_match = _model_intent_from_text(ctx, fallbacks)
    if model_match:
        return LocalIntentMatch(model_match, "high", "intent_model")

    if fallbacks.multi_step_guard and looks_like_multi_step_instruction(ctx.text):
        return LocalIntentMatch({"type": "chat", "reply": _MULTI_STEP_FEEDBACK}, "high", "multi_step")

    window_shortcut = _macos_window_shortcut_from_text(ctx.text, ctx.shortcuts)
    if window_shortcut:
        return LocalIntentMatch({"type": "shortcut", "name": window_shortcut}, "high", "window_shortcut")

    if _looks_like_open_app_instruction(ctx.text):
        shortcut_name = _open_app_shortcut_from_text(ctx.text, ctx.shortcuts)
        if shortcut_name:
            return LocalIntentMatch({"type": "shortcut", "name": shortcut_name}, "high", "open_app")
        return LocalIntentMatch({"type": "chat", "reply": "没有找到可打开的应用"}, "high", "open_app_missing")

    if _looks_like_undo_instruction(ctx.text) and "撤销" in ctx.shortcuts:
        return LocalIntentMatch({"type": "shortcut", "name": "撤销"}, "high", "undo")

    if looks_like_whole_delete_instruction(ctx.text):
        return LocalIntentMatch({"type": "delete"}, "high", "delete")

    if ctx.selected and looks_like_selected_delete_instruction(ctx.text):
        return LocalIntentMatch({"type": "delete"}, "high", "delete")

    if looks_like_write_instruction(ctx.text):
        return LocalIntentMatch({"type": "write"}, "high", "write")

    if (
        fallbacks.selected_edit_override
        and (ctx.selected or ctx.recent_text)
        and looks_like_edit_instruction(ctx.text)
    ):
        return LocalIntentMatch({"type": "edit"}, "high", "edit")

    shortcut_alias = _shortcut_alias_from_text(ctx.text, ctx.shortcuts, ctx.shortcut_entries)
    if shortcut_alias:
        return LocalIntentMatch({"type": "shortcut", "name": shortcut_alias}, "high", "shortcut_alias")

    exact_shortcut = _exact_shortcut_from_text(ctx.text, ctx.shortcuts)
    if exact_shortcut:
        return LocalIntentMatch({"type": "shortcut", "name": exact_shortcut}, "high", "exact_shortcut")

    if fallbacks.memo_fuzzy_recall and looks_like_memo_lookup(ctx.text):
        resolution = resolve_memo_key(ctx.text, ctx.memo_records)
        if resolution.can_recall:
            return LocalIntentMatch({"type": "memo_recall", "key": resolution.key}, "high", "memo_recall")
        return LocalIntentMatch({"type": "chat", "reply": resolution.feedback()}, "high", "memo_missing")

    return None


def _corrected_override_from_text(
    ctx: IntentContext,
    fallbacks: IntentFallbackOptions,
) -> dict | None:
    if not fallbacks.intent_overrides:
        return None
    kwargs = {}
    if fallbacks.intent_overrides_path:
        kwargs["path"] = fallbacks.intent_overrides_path
    override = find_override(ctx.text, **kwargs)
    if not override:
        return None
    return override if _override_is_available(override, ctx) else None


def _override_is_available(intent: dict, ctx: IntentContext) -> bool:
    intent_type = str(intent.get("type") or "")
    if intent_type == "shortcut":
        return str(intent.get("name") or "") in ctx.shortcuts
    if intent_type in {"memo_recall", "memo_delete"}:
        return str(intent.get("key") or "") in ctx.memo_keys
    return True


def _model_intent_from_text(
    ctx: IntentContext,
    fallbacks: IntentFallbackOptions,
) -> dict | None:
    if not fallbacks.intent_model or not fallbacks.intent_model_path:
        return None
    model = load_intent_model(fallbacks.intent_model_path)
    if model is None:
        return None
    intent = model.match(ctx.text, min_similarity=fallbacks.intent_model_min_similarity)
    if not intent:
        return None
    return intent if _override_is_available(intent, ctx) else None


def apply_intent_fallbacks(
    result: dict,
    ctx: IntentContext,
    fallbacks: IntentFallbackOptions | None = None,
) -> dict:
    fallbacks = fallbacks or IntentFallbackOptions()
    intent = result.get("type", "chat")
    if fallbacks.multi_step_guard and looks_like_multi_step_instruction(ctx.text):
        return {"type": "chat", "reply": _MULTI_STEP_FEEDBACK}
    window_shortcut = _macos_window_shortcut_from_text(ctx.text, ctx.shortcuts)
    if window_shortcut:
        return {"type": "shortcut", "name": window_shortcut}
    if _looks_like_open_app_instruction(ctx.text):
        shortcut_name = _open_app_shortcut_from_text(ctx.text, ctx.shortcuts)
        if shortcut_name:
            return {"type": "shortcut", "name": shortcut_name}
        if result.get("type") == "shortcut":
            return LocalIntentMatch({"type": "chat", "reply": "没有找到可打开的应用"}, "high", "open_app_missing")
    if intent == "undo" and "撤销" in ctx.shortcuts:
        return LocalIntentMatch({"type": "shortcut", "name": "撤销"}, "high", "undo")
    if looks_like_whole_delete_instruction(ctx.text):
        return {"type": "delete"}
    if ctx.selected and looks_like_selected_delete_instruction(ctx.text):
        return {"type": "delete"}
    if looks_like_write_instruction(ctx.text):
        return {"type": "write"}
    if (
        fallbacks.selected_edit_override
        and (ctx.selected or ctx.recent_text)
        and intent in {"chat", "write"}
        and looks_like_edit_instruction(ctx.text)
    ):
        return {"type": "edit"}
    shortcut_alias = _shortcut_alias_from_text(ctx.text, ctx.shortcuts, ctx.shortcut_entries)
    if shortcut_alias and intent in {"chat", "shortcut"}:
        return {"type": "shortcut", "name": shortcut_alias}
    if fallbacks.memo_fuzzy_recall and intent == "memo_recall":
        resolution = resolve_memo_key(ctx.text, ctx.memo_records)
        if resolution.can_recall:
            return {"type": "memo_recall", "key": resolution.key}
        return {"type": "chat", "reply": resolution.feedback()}
    if fallbacks.memo_fuzzy_recall and looks_like_memo_lookup(ctx.text):
        resolution = resolve_memo_key(ctx.text, ctx.memo_records)
        if resolution.can_recall:
            return {"type": "memo_recall", "key": resolution.key}
        if intent == "chat":
            return {"type": "chat", "reply": resolution.feedback()}
    return result


def looks_like_edit_instruction(text: str) -> bool:
    return any(hint in text for hint in _EDIT_HINTS)


def looks_like_write_instruction(text: str) -> bool:
    compact = _compact_shortcut_text(text)
    if not compact:
        return False
    write_markers = (
        "\u5199\u4e00",
        "\u5199\u4e2a",
        "\u5199\u5c01",
        "\u5199\u4e00\u5c01",
        "\u5199\u4e00\u6bb5",
        "\u5199\u6bb5",
        "\u5e2e\u6211\u5199",
        "\u5e2e\u6211\u8d77\u8349",
        "\u8d77\u8349",
        "\u8349\u62df",
        "\u62df\u4e00\u5c01",
        "\u751f\u6210",
        "\u5e2e\u6211\u751f\u6210",
        "\u5199\u4e2a\u56de\u590d",
        "\u5e2e\u6211\u56de\u590d",
        "\u56de\u590d\u4e00\u4e0b",
    )
    if not any(marker in compact for marker in write_markers):
        return False
    edit_targets = (
        "\u8fd9\u6bb5",
        "\u8fd9\u53e5\u8bdd",
        "\u4e0a\u4e00\u53e5",
        "\u4e0a\u53e5\u8bdd",
        "\u4e0a\u9762\u8fd9\u6bb5",
        "\u9009\u4e2d",
        "\u5df2\u6709",
        "\u539f\u6587",
    )
    if compact.startswith("\u628a") and any(target in compact for target in edit_targets):
        return False
    return True


def looks_like_selected_delete_instruction(text: str) -> bool:
    compact = _compact_shortcut_text(text)
    if not compact:
        return False
    if compact in {"\u5220\u9664", "\u5220\u6389", "\u5220\u4e86", "\u6e05\u9664", "\u6e05\u7a7a"}:
        return True
    delete_markers = ("\u5220\u9664", "\u5220\u6389", "\u5220\u4e86", "\u6e05\u9664", "\u6e05\u7a7a")
    selection_markers = ("\u9009\u4e2d", "\u9009\u62e9", "\u8fd9\u6bb5", "\u8fd9\u53e5\u8bdd", "\u5f53\u524d\u8fd9\u6bb5", "\u5f53\u524d\u6587\u5b57")
    return any(marker in compact for marker in delete_markers) and any(
        marker in compact for marker in selection_markers
    )


def looks_like_whole_delete_instruction(text: str) -> bool:
    compact = "".join(str(text or "").split()).strip("。.!！？?，,；;：:")
    if compact in {
        "删除",
        "删掉",
        "删了",
        "清除",
        "清空",
        "全部删除",
        "删除全部",
        "删掉全部",
        "全部删掉",
        "清空全部",
        "全部清空",
        "都删掉",
        "都删除",
    }:
        return True
    delete_markers = ("删除", "删掉", "删了", "清除", "清空", "删光")
    scope_markers = (
        "全文",
        "全部",
        "整体",
        "整段",
        "整篇",
        "所有内容",
        "当前内容",
        "整个输入框",
        "输入框内容",
        "输入框里的内容",
        "输入框里面的内容",
    )
    return any(marker in compact for marker in delete_markers) and any(
        marker in compact for marker in scope_markers
    )


def looks_like_memo_lookup(text: str) -> bool:
    if any(hint in text for hint in ("什么意思", "什么含义", "这个词", "这个概念")):
        return False
    return (
        "我的" in text
        or text.startswith(("查询", "查一下", "插入", "输入", "填入"))
        or text.endswith(("是什么", "是多少", "是啥"))
        or "打出来" in text
    )


def _macos_window_shortcut_from_text(text: str, shortcuts: tuple[str, ...]) -> str:
    compact = _compact_shortcut_text(text)
    if not _looks_like_window_action(compact, shortcuts):
        return ""
    candidates: tuple[str, ...] = ()
    if "左" in compact:
        candidates = ("窗口左半屏", "窗口左移")
    elif "右" in compact:
        candidates = ("窗口右半屏", "窗口右移")
    elif "最大化" in compact or "放大" in compact:
        candidates = ("窗口最大化",)
    elif "居中" in compact or "中间" in compact:
        candidates = ("窗口居中",)
    for candidate in candidates:
        if candidate in shortcuts:
            return candidate
    return ""


def _looks_like_window_action(compact_text: str, shortcuts: tuple[str, ...]) -> bool:
    if not any(shortcut.startswith("窗口") for shortcut in shortcuts):
        return False
    if "窗口" in compact_text:
        return True
    has_direction = any(marker in compact_text for marker in ("左", "右", "最大化", "放大", "居中", "中间"))
    has_move_marker = any(marker in compact_text for marker in ("放到", "放在", "移到", "移至", "移动", "靠"))
    return has_direction and has_move_marker


def _looks_like_open_app_instruction(text: str) -> bool:
    return bool(_open_app_target(text))


def _looks_like_undo_instruction(text: str) -> bool:
    compact = _compact_shortcut_text(text)
    return compact in {"撤销", "撤回", "恢复上一步", "退回上一步"}


def _exact_shortcut_from_text(text: str, shortcuts: tuple[str, ...]) -> str:
    compact = _compact_shortcut_text(text).lower()
    if not compact:
        return ""
    for shortcut in shortcuts:
        if _compact_shortcut_text(shortcut).lower() == compact:
            return shortcut
    return ""




def _shortcut_alias_from_text(text: str, shortcuts: tuple[str, ...], shortcut_entries: tuple[ShortcutIntentEntry, ...] = ()) -> str:
    compact = _compact_shortcut_text(text).lower()
    if not compact:
        return ""
    alias_groups = (
        ("\u4fdd\u5b58", ("\u4fdd\u5b58", "\u4fdd\u5b58\u4e00\u4e0b", "\u5e2e\u6211\u4fdd\u5b58", "\u4fdd\u5b58\u5f53\u524d", "\u5b58\u4e00\u4e0b")),
        ("\u53d1\u9001", ("\u53d1\u9001", "\u53d1\u9001\u4e00\u4e0b", "\u53d1\u51fa\u53bb", "\u5e2e\u6211\u53d1\u9001", "\u53d1\u4e00\u4e0b", "\u63d0\u4ea4\u53d1\u9001")),
        ("\u5168\u9009", ("\u5168\u9009", "\u5168\u90e8\u9009\u4e2d", "\u9009\u4e2d\u5168\u90e8", "\u5168\u90fd\u9009\u4e2d")),
        ("\u590d\u5236", ("\u590d\u5236", "\u590d\u5236\u4e00\u4e0b", "\u5e2e\u6211\u590d\u5236")),
        ("\u7c98\u8d34", ("\u7c98\u8d34", "\u8d34\u4e0a", "\u8d34\u4e00\u4e0b", "\u5e2e\u6211\u7c98\u8d34")),
        ("\u56de\u8f66", ("\u56de\u8f66", "\u6309\u56de\u8f66", "\u6572\u56de\u8f66", "\u786e\u8ba4\u4e00\u4e0b")),
        ("\u786e\u8ba4", ("\u786e\u8ba4", "\u786e\u8ba4\u4e00\u4e0b", "\u786e\u5b9a", "\u786e\u5b9a\u4e00\u4e0b")),
        ("\u63d0\u4ea4", ("\u63d0\u4ea4", "\u63d0\u4ea4\u4e00\u4e0b", "\u5e2e\u6211\u63d0\u4ea4")),
        ("\u5173\u95ed", ("\u5173\u95ed", "\u5173\u95ed\u4e00\u4e0b", "\u5173\u6389", "\u5173\u4e00\u4e0b")),
    )
    normalized_shortcuts = {
        _compact_shortcut_text(shortcut).lower(): shortcut for shortcut in shortcuts
    }
    command_prefixes = ("\u5e2e\u6211", "\u8bf7", "\u9ebb\u70e6", "\u7ed9\u6211")
    for entry in shortcut_entries:
        entry_name = getattr(entry, "name", "")
        if entry_name not in shortcuts:
            continue
        aliases = tuple(getattr(entry, "aliases", ()) or ())
        normalized_aliases = tuple(_compact_shortcut_text(alias).lower() for alias in aliases if alias)
        if compact in normalized_aliases or (
            compact.startswith(command_prefixes)
            and any(alias in compact for alias in normalized_aliases)
        ):
            return entry_name
    for canonical, aliases in alias_groups:
        normalized_aliases = tuple(alias.lower() for alias in aliases)
        if compact not in normalized_aliases and not (
            compact.startswith(command_prefixes)
            and any(alias in compact for alias in normalized_aliases)
        ):
            continue
        shortcut = normalized_shortcuts.get(_compact_shortcut_text(canonical).lower())
        if shortcut:
            return shortcut
    return ""


def _open_app_shortcut_from_text(text: str, shortcuts: tuple[str, ...]) -> str:
    target = _open_app_target(text)
    if not target:
        return ""
    normalized_target = target.lower()
    fuzzy_matches: list[tuple[int, str]] = []
    for shortcut in shortcuts:
        shortcut_target = _open_app_target(shortcut)
        if not shortcut_target:
            continue
        normalized_shortcut_target = shortcut_target.lower()
        if normalized_shortcut_target == normalized_target:
            return shortcut
        if normalized_shortcut_target in normalized_target or normalized_target in normalized_shortcut_target:
            fuzzy_matches.append((len(shortcut_target), shortcut))
    if fuzzy_matches:
        return max(fuzzy_matches)[1]
    return ""


def _open_app_target(text: str) -> str:
    compact = _compact_shortcut_text(text).replace("\u7684", "")
    markers = (
        "\u6253\u5f00",
        "\u6253\u4e2a",
        "\u5207\u6362\u5230",
        "\u5207\u5230",
        "\u5207\u53bb",
    )
    marker = -1
    marker_len = 0
    for candidate in markers:
        marker = compact.find(candidate)
        if marker >= 0:
            marker_len = len(candidate)
            break
    if marker < 0:
        return ""
    target = compact[marker + marker_len:]
    for suffix in (
        "\u4e00\u4e0b",
        "\u5e94\u7528\u7a0b\u5e8f",
        "\u5e94\u7528",
        "\u8f6f\u4ef6",
        "app",
        "App",
        "APP",
    ):
        if target.endswith(suffix):
            target = target[:-len(suffix)]
    return target

def _compact_shortcut_text(text: str) -> str:
    return "".join(
        char for char in str(text or "").strip()
        if char not in " \t\r\n。.!！?？,，;；:：\"'“”‘’"
    )


def looks_like_multi_step_instruction(text: str) -> bool:
    if not any(marker in text for marker in _MULTI_STEP_MARKERS):
        return False
    if _mentions_multiple_operation_kinds(text):
        return True
    return _mentions_multiple_explicit_operations(text)


def _mentions_multiple_operation_kinds(text: str) -> bool:
    kinds = 0
    if any(hint in text for hint in ("删", "删除", "清除")):
        kinds += 1
    if any(hint in text for hint in _EDIT_HINTS):
        kinds += 1
    if any(hint in text for hint in ("输入", "打上", "写上", "插入")):
        kinds += 1
    if any(hint in text for hint in ("打开", "保存", "发送", "复制", "粘贴", "关闭", "提交", "回车")):
        kinds += 1
    if any(hint in text for hint in ("记住", "记一下", "存一下", "忘记", "列出")):
        kinds += 1
    return kinds >= 2


def _mentions_multiple_explicit_operations(text: str) -> bool:
    operation_markers = (
        "打开", "保存", "发送", "复制", "粘贴", "关闭", "提交", "回车",
        "删除", "清除", "删掉", "记住", "记一下", "存一下", "忘记",
    )
    matches = 0
    for marker in operation_markers:
        if marker in text:
            matches += 1
        if matches >= 2:
            return True
    return False



def _confidence_allows_local(
    confidence: IntentConfidence,
    fallbacks: IntentFallbackOptions,
) -> bool:
    order = {"low": 0, "medium": 1, "high": 2}
    threshold = str(fallbacks.local_confidence_threshold or "high")
    return order.get(confidence, 0) >= order.get(threshold, 2)


def _strip_intent_meta(result: dict) -> dict:
    return {k: v for k, v in result.items() if not str(k).startswith("_intent_")}


def _with_intent_meta(
    result: dict,
    source: IntentSource,
    confidence: IntentConfidence,
    *,
    cache_hit: bool = False,
) -> dict:
    out = dict(result)
    out["_intent_source"] = source
    out["_intent_confidence"] = confidence
    if cache_hit:
        out["_intent_cache_hit"] = True
    return out


def _intent_cache_key(ctx: IntentContext) -> tuple:
    return (
        _compact_shortcut_text(ctx.text).lower(),
        bool(ctx.selected),
        bool(ctx.recent_text),
        ctx.active_application,
        tuple(ctx.shortcuts),
        tuple(ctx.memo_keys),
    )


def _cache_get(key: tuple) -> dict | None:
    cached = _INTENT_CACHE.get(key)
    return None if cached is None else dict(cached)


def _cache_put(key: tuple, result: dict) -> None:
    clean = {k: v for k, v in result.items() if not str(k).startswith("_intent_")}
    if key not in _INTENT_CACHE:
        _INTENT_CACHE_ORDER.append(key)
    _INTENT_CACHE[key] = dict(clean)
    while len(_INTENT_CACHE_ORDER) > _INTENT_CACHE_MAX:
        oldest = _INTENT_CACHE_ORDER.pop(0)
        _INTENT_CACHE.pop(oldest, None)


def _shortcut_alias_summary(entries: tuple[ShortcutIntentEntry, ...]) -> str:
    parts = []
    for entry in entries:
        aliases = tuple(getattr(entry, "aliases", ()) or ())
        if aliases:
            parts.append(f"{entry.name}={'/'.join(aliases[:5])}")
    return "?".join(parts[:20])


def shortcut_intent_entries(catalog_entries) -> tuple[ShortcutIntentEntry, ...]:
    entries = []
    for entry in catalog_entries or ():
        entries.append(ShortcutIntentEntry(
            name=getattr(entry, "name", ""),
            aliases=tuple(getattr(entry, "aliases", ()) or ()),
            risk=getattr(entry, "risk", "normal"),
            source=getattr(entry, "source", ""),
            application=getattr(entry, "application", ""),
            kind=getattr(entry, "kind", "shortcut"),
        ))
    return tuple(entry for entry in entries if entry.name)

def memo_records(
    entries: MemoEntries | None,
) -> tuple[MemoRecord, ...]:
    if entries is None:
        return ()
    records = []
    for key in entries.keys():
        records.append(MemoRecord(
            key=key,
            value=entries.get(key) or "",
        ))
    return tuple(records)


def _build_user_message(ctx: IntentContext) -> str:
    user_msg = f"当前活动应用：{ctx.active_application or '未知'}\n"
    user_msg += f"当前活动应用可用 Shortcut Catalog：{'、'.join(ctx.shortcuts)}\n"
    if ctx.memo_keys:
        user_msg += (
            "已保存的备忘名称："
            f"{'、'.join(ctx.memo_keys)}\n"
        )
    else:
        user_msg += "已保存的备忘名称：（暂无）\n"
    if ctx.selected:
        user_msg += f"用户的 Explicit Selection（明确选区）：\"{ctx.selected}\"\n"
    elif ctx.recent_text:
        user_msg += f"用户最近的 Tracked Segment（已追踪文本段）：\"{ctx.recent_text}\"\n"
    user_msg += f"用户说：\"{ctx.text}\""
    return user_msg


def _parse_json_object(raw: str) -> dict:
    text = raw.strip().lstrip("```json").lstrip("```").rstrip("```").strip()
    parsed = json.loads(text)
    if not isinstance(parsed, dict):
        raise ValueError("intent classifier did not return a JSON object")
    return parsed
