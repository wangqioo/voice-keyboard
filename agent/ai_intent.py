"""Instruction Mode intent classification.

This module keeps the LLM prompt, JSON cleanup, and deterministic fallbacks out
of AIHandler so the handler can stay focused on orchestration and side effects.
"""

import json
from dataclasses import dataclass
from typing import Protocol

from agent.reusable_text_memory import fuzzy_match_memory_key


class ChatLLM(Protocol):
    def chat(self, system: str, user: str) -> str:
        ...


class MemoKeys(Protocol):
    def keys(self) -> list[str]:
        ...


@dataclass(frozen=True)
class IntentContext:
    text: str
    selected: str = ""
    recent_text: str = ""
    active_application: str = ""
    shortcuts: tuple[str, ...] = ()
    memo_keys: tuple[str, ...] = ()


_CLASSIFY_SYSTEM = """你是 Voice Keyboard Engine 的 Instruction Mode 意图分类器。根据用户说的话返回一个JSON对象，不要包含任何其他内容。

判断依据是用户说的话，而不是是否有 Explicit Selection（明确选区）。Explicit Selection 只是上下文参考。

本软件是通用的语音驱动键盘效率层：用户说出想完成的键盘式操作，引擎把它解释为当前输入环境里的打字、编辑、快捷键、撤回或可复用文本调用。它不是 chat-first 或 AI-native 产品，AI 只是把语音解释成用户操作的一种实现手段。

本软件的功能：
- Dictation Mode：语音转文字，原样打入当前输入框
- Instruction Mode，有以下几种 Voice Keyboard Operation：
  * 快捷键：说出操作名称直接执行系统快捷键
  * 编辑：修改/润色/删除 Tracked Segment（已追踪文本段）或 Explicit Selection（明确选区）
  * 写作：给出主题或要求，由引擎生成内容并逐句打入
  * 撤回：撤销上一次 Instruction Mode operation，恢复原文
  * 备忘：记录或读取常用信息（手机号、邮箱、地址等）
- 辅助反馈：提问、聊天、不确定、没有明确编辑或写作指令时，只在状态框显示简短 feedback，不向输入框写入聊天内容

规则（按优先级）：
1. 明确的快捷键操作 → {"type":"shortcut","name":"快捷键名称"}。快捷键目前是实验性能力，表示在当前活动应用里触发该名称对应的快捷键，name 必须优先使用可用快捷键列表里的原始名称。
2. 撤回/撤销/恢复上一步操作 → {"type":"undo"}
3. 明确要求删除/清除 Explicit Selection（明确选区）或 Tracked Segment（已追踪文本段）（不是修改，是直接删掉） → {"type":"delete"}
4. 用户要保存信息到备忘录（"记一下"、"记住"、"备忘"、"存一下"等关键词）。key 是用户给这条信息起的名字（如"手机号"、"邮箱"、"家庭地址"），value 是要记的内容：
   - 如果有 Explicit Selection（明确选区），value 就是该明确选区（此时返回空字符串作为 value，由程序自动使用）
   - 如果用户在话里直接说出了内容（如"我的邮箱是 abc@xx.com"），value 就是那段内容
   → {"type":"memo_save","key":"...","value":"..."}
5. 用户要查询已保存的备忘录（"我的xxx是什么"、"我的xxx"、"xxx是多少"、"xxx是啥"等问句）。
   匹配 key 时必须容忍以下情况：
   - STT 同音字错误：如"话"→"画"、"号"→"好"、"件"→"建"，根据上下文判断
   - 近义说法：如"最喜欢说"vs"最爱说"vs"常说"，"地址"vs"住址"
   - 部分省略：用户可能只说 key 的核心部分（如 key 是"白光宇最喜欢说的话"，用户说"白光宇说什么"也算）
   只要用户的问题在语义上对得上某个已保存的 key，就大胆返回 memo_recall。key 字段必须填【已保存列表里那个原始 key】，不要返回用户口述的版本。
   → {"type":"memo_recall","key":"已保存列表里的原始key"}
6. 用户要删除备忘录（"忘记我的xxx"、"删掉xxx的记录"） → {"type":"memo_delete","key":"..."}
6.5. 用户要查看/列出所有备忘录（"列出所有备忘"、"我都记了什么"、"导出记忆库"、"看一下我的记忆"等） → {"type":"memo_list"}
7. 用户说的话明确要求修改/润色/编辑已有文字 → {"type":"edit"}
8. 用户给出主题、要求或提纲，让引擎生成新内容 → {"type":"write"}
9. 其他（提问、聊天、不确定、没有明确编辑或写作指令） → {"type":"chat","reply":"回答或提示，最多50字"}"""

_EDIT_HINTS = (
    "改", "修改", "改写", "润色", "优化", "整理", "精简", "扩写", "缩短",
    "正式", "口语", "自然", "通顺", "礼貌", "专业", "调整", "换个说法",
    "翻译", "译成", "英文", "英语", "中文", "日文", "日语", "韩文", "韩语",
)


def classify_intent(llm: ChatLLM, ctx: IntentContext) -> dict:
    raw = llm.chat(_CLASSIFY_SYSTEM, _build_user_message(ctx))
    result = _parse_json_object(raw)
    return apply_intent_fallbacks(result, ctx)


def apply_intent_fallbacks(result: dict, ctx: IntentContext) -> dict:
    intent = result.get("type", "chat")
    if (ctx.selected or ctx.recent_text) and intent in {"chat", "write"} and looks_like_edit_instruction(ctx.text):
        return {"type": "edit"}
    if intent == "chat":
        fuzzy_key = fuzzy_match_memory_key(ctx.text, ctx.memo_keys)
        if fuzzy_key:
            return {"type": "memo_recall", "key": fuzzy_key}
    return result


def looks_like_edit_instruction(text: str) -> bool:
    return any(hint in text for hint in _EDIT_HINTS)


def memo_keys(memos: MemoKeys | None) -> tuple[str, ...]:
    if memos is None:
        return ()
    return tuple(memos.keys())


def _build_user_message(ctx: IntentContext) -> str:
    user_msg = f"当前活动应用：{ctx.active_application or '未知'}\n"
    user_msg += f"当前活动应用可用快捷键（实验性）：{'、'.join(ctx.shortcuts)}\n"
    if ctx.memo_keys:
        user_msg += f"已保存的备忘录名称：{'、'.join(ctx.memo_keys)}\n"
    else:
        user_msg += "已保存的备忘录名称：（暂无）\n"
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
