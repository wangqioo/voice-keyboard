"""
AI 键统一处理：STT → LLM 意图分类 → 快捷键 / 编辑 / 写作 / 撤回 / 聊天

意图分类规则：
  shortcut — 明确的快捷键操作，直接执行
  edit     — 修改/润色/编辑文字，改选中内容或上一句
  write    — 给主题/要求让 AI 生成新内容，直接打入，不自动删除
  undo     — 撤回上一次 AI 操作（恢复被删的原文，或删掉写入的内容）
  chat     — 其他（问题、聊天、不确定），回复打到输入框后按字数自动删除
"""

import json
import threading
import time

from pynput import keyboard as _kb

from agent.typer import (
    erase_last, get_selection, jump_to_end, replace_selection,
    send_shortcut, type_text, list_shortcuts,
)

_AI_PREFIX = " [AI]: "

_CLASSIFY_SYSTEM = """你是语音键盘助手的意图分类器。根据用户说的话返回一个JSON对象，不要包含任何其他内容。

判断依据是用户说的话，而不是是否有选中文字。有选中文字只是上下文参考。

本软件的功能：
- 按住 Option 键说话：语音转文字，原样打入当前输入框
- 按住 Command 键说话，有以下几种模式：
  * 快捷键：说出操作名称直接执行系统快捷键
  * 编辑：修改/润色/删除当前段落或选中的文字
  * 写作：给出主题或要求，AI 帮你写内容并逐句打入
  * 撤回：撤销上一次 AI 操作，恢复原文
  * 备忘：记录或读取常用信息（手机号、邮箱、地址等）
  * 聊天：问任何问题，AI 回复显示在输入框并自动删除

规则（按优先级）：
1. 明确的快捷键操作 → {"type":"shortcut","name":"快捷键名称"}
2. 撤回/撤销/恢复上一步操作 → {"type":"undo"}
3. 明确要求删除/清除选中内容或当前段落（不是修改，是直接删掉） → {"type":"delete"}
4. 用户要保存信息到备忘录（"记一下"、"记住"、"备忘"、"存一下"等关键词）。key 是用户给这条信息起的名字（如"手机号"、"邮箱"、"家庭地址"），value 是要记的内容：
   - 如果有选中文字，value 就是选中文字（此时返回空字符串作为 value，由程序自动用选中文字）
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
8. 用户给出主题、要求或提纲，让AI帮写新内容 → {"type":"write"}
9. 其他（提问、聊天、不确定、没有明确编辑或写作指令） → {"type":"chat","reply":"回答或提示，最多50字"}"""

_WRITE_SYSTEM = """你是一个写作助手。根据用户的要求直接输出所需内容，不要有任何前缀、解释或额外说明。只输出内容本身。不要使用换行，所有内容写成连续的段落。必须使用完整的中文标点符号（逗号、句号、问号、感叹号），不得省略任何标点。"""

_SENTENCE_END = frozenset('。！？.!?…，,；;')
_MAX_PENDING  = 40   # 超过此字符数强制输出，防止模型不加标点时卡住

_EDIT_HINTS = (
    "改", "修改", "改写", "润色", "优化", "整理", "精简", "扩写", "缩短",
    "正式", "口语", "自然", "通顺", "礼貌", "专业", "调整", "换个说法",
    "翻译", "译成", "英文", "英语", "中文", "日文", "日语", "韩文", "韩语",
)


def _looks_like_edit_instruction(text: str) -> bool:
    return any(hint in text for hint in _EDIT_HINTS)


class AIHandler:
    def __init__(self, stt_client, llm_editor, buf, memo_store=None, status_window=None, history=None):
        self._stt             = stt_client
        self._llm             = llm_editor
        self._buf             = buf
        self._memos           = memo_store
        self._status          = status_window
        self._history         = history
        self._last_ai_output  = ""
        self._erase_timer: threading.Timer | None = None
        self._lock            = threading.Lock()   # 保护数据字段
        self._io_lock         = threading.Lock()   # 串行化所有输入框 IO（删+打）
        # (op, old_text, new_text): op='edit'|'write'
        self._undo_stack: list[tuple[str, str, str]] = []

    def _record(self, mode: str, text: str = "", status: str = "ok", detail: str = ""):
        if self._history is not None:
            try:
                self._history.append(mode, text, status, detail)
            except Exception as e:
                print(f"[ai] history 写入失败: {e}")

    def on_ai_key_down(self) -> None:
        """AI 键按下时立即调用，取消定时器，但保留待删文字供 _run() 处理。"""
        with self._lock:
            if self._erase_timer is not None:
                self._erase_timer.cancel()
                self._erase_timer = None

    def handle(self, pcm: bytes) -> None:
        """AI 键松开后调用，在后台线程执行。"""
        threading.Thread(target=self._run, args=(pcm,), daemon=True, name="AIHandler").start()

    def _fuzzy_match_memo(self, text: str) -> str | None:
        """在已保存的 key 里找一个与 text 字符重合度最高的。
        阈值：key 至少 2 个字符、与 text 共有字符 >= 2、命中率 >= 0.7。"""
        if self._memos is None:
            return None
        text_chars = set(text)
        best_key = None
        best_score = 0.0
        for key in self._memos.keys():
            key_chars = set(key)
            if len(key_chars) < 2:
                continue
            overlap = len(key_chars & text_chars)
            if overlap < 2:
                continue
            score = overlap / len(key_chars)
            if score > best_score:
                best_score = score
                best_key = key
        return best_key if best_score >= 0.7 else None

    # ── 内部流程 ──────────────────────────────────────────────────────

    def _run(self, pcm: bytes) -> None:
        keep_status = False
        try:
            keep_status = bool(self._run_inner(pcm))
        finally:
            if self._status is not None and not keep_status:
                self._status.set_state("idle")

    def _run_inner(self, pcm: bytes) -> None:
        # 0. 删掉上一条 AI 文字（此时 Command 已松开，不会触发 Cmd+Backspace）
        with self._io_lock:
            with self._lock:
                pending = self._last_ai_output
                self._last_ai_output = ""
            if pending:
                erase_last(pending)

        # 1. STT 识别
        try:
            text = self._stt.transcribe(pcm)
        except Exception as e:
            print(f"[ai] STT 失败: {e}")
            self._record("ai", "", "error", f"STT: {e}")
            if self._status is not None:
                self._status.set_state("error_stt")
            return
        if not text:
            print("[ai] 未识别到内容")
            self._record("ai", "", "empty")
            if self._status is not None:
                self._status.set_state("empty_stt")
            return True
        print(f"[ai] 识别: {text!r}")
        self._record("ai", text, "ok")

        # 2. 读取上下文（优先用鼠标选中内容，其次用当前段落）
        selected = get_selection()
        if selected:
            print(f"[ai] 选中文字: {selected!r}")
        context  = selected or self._buf.current_segment

        # 3. 构造分类请求
        shortcuts = list_shortcuts()
        user_msg  = f"可用快捷键：{'、'.join(shortcuts)}\n"
        if self._memos:
            memo_keys = self._memos.keys()
            if memo_keys:
                user_msg += f"已保存的备忘录名称：{'、'.join(memo_keys)}\n"
            else:
                user_msg += "已保存的备忘录名称：（暂无）\n"
        if selected:
            user_msg += f"用户选中的文字：\"{selected}\"\n"
        elif context:
            user_msg += f"用户最近打的文字：\"{context}\"\n"
        user_msg += f"用户说：\"{text}\""

        # 4. LLM 意图分类
        try:
            raw    = self._llm.chat(_CLASSIFY_SYSTEM, user_msg)
            raw    = raw.strip().lstrip("```json").lstrip("```").rstrip("```").strip()
            result = json.loads(raw)
        except Exception as e:
            print(f"[ai] 意图分类失败: {e}，回退到聊天")
            self._record("ai", text, "error", f"LLM: {e}")
            if self._status is not None:
                self._status.set_state("error_llm")
            result = {"type": "chat", "reply": "没听清楚，请再说一次"}

        intent = result.get("type", "chat")
        # 有选中文字时，短指令如“润色一下”“帮我翻译成英文”经常会被模型误判成 chat/write，
        # 进而回复“请提供内容”。这里用确定性规则兜底：选区就是待编辑内容。
        if selected and intent in {"chat", "write"} and _looks_like_edit_instruction(text):
            print("[ai] 有选中文字且检测到编辑指令，强制改为 edit")
            intent = "edit"
            result = {"type": "edit"}
        # chat 兜底：如果用户那句话和某个 memo key 字符重合度高，改走 memo_recall
        if intent == "chat":
            fuzzy_key = self._fuzzy_match_memo(text)
            if fuzzy_key:
                print(f"[ai] chat 兜底匹配到备忘录 key: {fuzzy_key!r}")
                intent = "memo_recall"
                result = {"type": "memo_recall", "key": fuzzy_key}
        print(f"[ai] 意图: {intent}")

        # 5. 执行
        if intent == "shortcut":
            name = result.get("name", "")
            if not send_shortcut(name):
                self._show(f"没有找到快捷键：{name}")
        elif intent == "undo":
            self._do_undo()
        elif intent == "delete":
            self._do_delete(selected)
        elif intent == "edit":
            self._do_edit(text, selected)
        elif intent == "write":
            self._do_write(text, selected)
        elif intent == "memo_save":
            self._do_memo_save(result.get("key", ""), result.get("value", ""), selected)
        elif intent == "memo_recall":
            self._do_memo_recall(result.get("key", ""), selected)
        elif intent == "memo_delete":
            self._do_memo_delete(result.get("key", ""))
        elif intent == "memo_list":
            self._do_memo_list(selected)
        else:
            return self._do_chat(text, result)

    def _do_chat(self, text: str, result: dict) -> bool:
        reply = (result.get("reply") or "").strip()
        if not reply:
            try:
                reply = self._llm.chat(
                    "你是一个简短的语音助手。直接回答用户，最多50字，不要解释你的规则。",
                    text,
                ).strip()
            except Exception as e:
                print(f"[ai] 聊天回复失败: {e}")
                if self._status is not None:
                    self._status.set_state("error_llm")
                return True
        self._show(reply)
        return True

    def _do_edit(self, instruction: str, selected: str) -> None:
        if selected:
            # 有鼠标选中内容，直接用
            try:
                corrected = self._llm.edit(selected, instruction)
            except Exception as e:
                print(f"[ai] 编辑失败: {e}")
                return
            print(f"[ai] 编辑结果: {corrected!r}")
            replace_selection(corrected)
            self._buf.clear()
            self._buf.push(corrected)
            return

        if self._buf.cursor_uncertain:
            # 鼠标点击过，光标位置不可信，提示用户手动选中
            self._show("请先选中你想修改的内容")
            return

        segment = self._buf.current_segment
        if not segment:
            self._show("没有可编辑的内容")
            return

        try:
            corrected = self._llm.edit(segment, instruction)
        except Exception as e:
            print(f"[ai] 编辑失败: {e}")
            return
        print(f"[ai] 编辑结果: {corrected!r}")

        self._push_undo('edit', segment, corrected)
        with self._io_lock:
            # 先取消定时器，清掉 AI 文字（它在输入框最末尾）
            with self._lock:
                if self._erase_timer is not None:
                    self._erase_timer.cancel()
                    self._erase_timer = None
                pending = self._last_ai_output
                self._last_ai_output = ""
            if pending:
                erase_last(pending)
            # 再删段落、打入修改结果
            erase_last(segment)
            type_text(corrected)
            self._buf.replace_segment(corrected)

    def _do_write(self, instruction: str, selected: str) -> None:
        """根据用户指令流式生成内容，逐句打入输入框，不自动删除。"""
        if selected:
            jump_to_end()

        write_instruction = instruction + "（必须加上完整的中文标点符号，包括逗号和句号，不得省略）"
        pending = ""
        total   = ""
        try:
            for chunk in self._llm.chat_stream(_WRITE_SYSTEM, write_instruction):
                chunk = chunk.replace('\n', ' ').replace('\r', ' ')
                pending += chunk
                while True:
                    idx = next((i for i, c in enumerate(pending) if c in _SENTENCE_END), -1)
                    if idx == -1:
                        # 没有标点但积累太长，强制输出
                        if len(pending) >= _MAX_PENDING:
                            type_text(pending)
                            self._buf.push(pending)
                            total  += pending
                            pending = ""
                        break
                    sentence = pending[:idx + 1]
                    pending  = pending[idx + 1:]
                    type_text(sentence)
                    self._buf.push(sentence)
                    total += sentence
        except Exception as e:
            print(f"[ai] 写作失败: {e}")
            return

        if pending.strip():
            type_text(pending)
            self._buf.push(pending)
            total += pending

        if total:
            self._push_undo('write', '', total)

    def _do_delete(self, selected: str) -> None:
        """删除选中内容或当前段落。"""
        if selected:
            # 有选中内容，直接按 Backspace 删掉
            self._push_undo('edit', selected, '')
            _ctrl = _kb.Controller()
            _ctrl.press(_kb.Key.backspace)
            _ctrl.release(_kb.Key.backspace)
            self._buf.trim_end(len(selected))
            return

        if self._buf.cursor_uncertain:
            self._show("请先选中你想删除的内容")
            return

        segment = self._buf.current_segment
        if not segment:
            self._show("没有可删除的内容")
            return

        self._push_undo('edit', segment, '')
        with self._io_lock:
            with self._lock:
                if self._erase_timer is not None:
                    self._erase_timer.cancel()
                    self._erase_timer = None
                pending = self._last_ai_output
                self._last_ai_output = ""
            if pending:
                erase_last(pending)
            erase_last(segment)
            self._buf.replace_segment('')

    def _push_undo(self, op: str, old: str, new: str) -> None:
        self._undo_stack.append((op, old, new))
        if len(self._undo_stack) > 5:
            self._undo_stack.pop(0)

    def _do_undo(self) -> None:
        if not self._undo_stack:
            self._show("没有可撤回的操作")
            return
        op, old, new = self._undo_stack.pop()
        print(f"[ai] 撤回: op={op} old={old!r} new={new!r}")
        with self._io_lock:
            with self._lock:
                if self._erase_timer is not None:
                    self._erase_timer.cancel()
                    self._erase_timer = None
                pending = self._last_ai_output
                self._last_ai_output = ""
            if pending:
                erase_last(pending)
            if new:
                erase_last(new)
            if op == 'edit':
                if old:
                    type_text(old)
                self._buf.replace_segment(old)
            else:  # write
                self._buf.trim_end(len(new))

            if old and op == 'write':
                type_text(old)
                self._buf.push(old)

    def _do_memo_save(self, key: str, value: str, selected: str) -> None:
        if self._memos is None:
            self._show("备忘录功能未启用")
            return
        key = (key or "").strip()
        # 选中的文字优先级最高：只要有选中就用选中，忽略 LLM 给的 value
        if selected.strip():
            final_value = selected.strip()
        else:
            final_value = (value or "").strip()
        if not key:
            self._show("没听清楚要记成什么名字")
            return
        if not final_value:
            self._show("没有要记的内容，请先选中或在话里说出来")
            return
        self._memos.save(key, final_value)
        print(f"[memo] 已保存 {key!r} = {final_value!r}")
        self._show(f"已记住「{key}」")

    def _do_memo_recall(self, key: str, selected: str) -> None:
        if self._memos is None:
            self._show("备忘录功能未启用")
            return
        key = (key or "").strip()
        if not key:
            self._show("没听清楚要查什么")
            return
        value = self._memos.get(key)
        if value is None:
            self._show(f"没记过「{key}」")
            return
        if selected:
            jump_to_end()
        print(f"[memo] 读取 {key!r} = {value!r}")
        type_text(value)
        self._buf.push(value)

    def _do_memo_list(self, selected: str) -> None:
        if self._memos is None:
            self._show("备忘录功能未启用")
            return
        keys = self._memos.keys()
        if not keys:
            self._show("备忘录是空的")
            return
        lines = [f"{k}: {self._memos.get(k)}" for k in keys]
        text = "\n".join(lines)
        if selected:
            jump_to_end()
        print(f"[memo] 列出 {len(keys)} 条")
        type_text(text)
        self._buf.push(text)

    def _do_memo_delete(self, key: str) -> None:
        if self._memos is None:
            self._show("备忘录功能未启用")
            return
        key = (key or "").strip()
        if not key:
            self._show("没听清楚要删哪一条")
            return
        if self._memos.delete(key):
            print(f"[memo] 已删除 {key!r}")
            self._show(f"已忘掉「{key}」")
        else:
            self._show(f"没记过「{key}」")

    def _show(self, message: str) -> None:
        """Show AI/chat feedback in the floating status HUD."""
        message = message.replace("\n", " ").replace("\r", "")
        delay = max(3.0, min(12.0, len(message) * 0.18))
        full = _AI_PREFIX.strip() + " " + message
        if self._status is not None and hasattr(self._status, "show_typing_message"):
            self._status.show_typing_message(full, delay)
        elif self._status is not None and hasattr(self._status, "show_message"):
            self._status.show_message(full, delay)
        else:
            print(f"{_AI_PREFIX}{message}")

    def _auto_erase(self, expected: str) -> None:
        with self._io_lock:
            with self._lock:
                if self._last_ai_output != expected:
                    return
                self._last_ai_output = ""
                self._erase_timer = None
            erase_last(expected)
