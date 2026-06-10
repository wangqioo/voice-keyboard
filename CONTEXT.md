# Voice Keyboard Engine

Voice Keyboard Engine is the local voice-driven keyboard efficiency context. It turns a user's spoken intent into text changes or keyboard-style operations in the current input environment, so ordinary users can drive common typing, editing, shortcut, and recall workflows by voice. Account, subscription, payment, and cloud entitlement concepts belong outside this context.

## Language

**Voice Keyboard Engine**:
The local engine that captures speech and applies resulting text or text operations to the user's current input environment.
_Avoid_: TypeUp Engine, Voice Keyboard, Agent

**Input Environment**:
The application, field, cursor position, and selected text that will receive engine output.
_Avoid_: App, editor, textbox

**Voice Keyboard Operation**:
A user-requested local keyboard, text, or desktop efficiency action based on speech.
_Avoid_: AI command, prompt, agent action

**Atomic Operation Stack**:
A short ordered stack of **Voice Keyboard Operations** explicitly requested by the user in one spoken instruction.
_Avoid_: Agent plan, autonomous workflow, implicit operation sequence

**Voice Text Operation**:
A **Voice Keyboard Operation** that creates, changes, removes, restores, or recalls text in the current **Input Environment**.
_Avoid_: AI command, voice command, prompt

**High-Risk Operation**:
A **Voice Keyboard Operation** risk label for actions that may submit, send, delete, overwrite broad content, cross application boundaries, or be hard to reverse.
_Avoid_: Dangerous command, privileged action

**Dictation**:
A **Voice Text Operation** that inserts the user's spoken words as text with minimal cleanup.
_Avoid_: STT result, transcription

**Text Insertion**:
A **Voice Text Operation** that inserts user-provided or already resolved text into the current **Input Environment**.
_Avoid_: Dictation Mode, AI writing

**Dictation Mode**:
The mode where speech is treated as content to insert into the **Input Environment**.
_Avoid_: PTT mode, normal mode

**Instruction Mode**:
The mode where speech is treated as an instruction for a **Voice Keyboard Operation**.
_Avoid_: AI mode, AI key mode, command mode

**Capture Path**:
The route by which speech enters the **Voice Keyboard Engine**.
_Avoid_: Hardware mode, software mode

**Software Capture Path**:
A **Capture Path** that records speech through a microphone already available to the computer.
_Avoid_: Pure software mode

**Hardware Capture Path**:
A **Capture Path** that records speech through a dedicated Voice Keyboard device.
_Avoid_: Hardware mode

**Tracked Segment**:
Text recently inserted by the **Voice Keyboard Engine** that the engine still considers safe to replace or delete.
_Avoid_: TextBuffer, current segment, current_segment

**Explicit Selection**:
Text the user has deliberately selected in the **Input Environment**.
_Avoid_: Selection, selected text

**Operation Window**:
The current text range the **Voice Keyboard Engine** considers safe to inspect and use as context for a replacement-style **Voice Text Operation**.
_Avoid_: Prompt context, whole paragraph target

**Operation Target**:
The specific text range inside an **Operation Window** that a **Voice Text Operation** intends to replace or remove.
_Avoid_: Full context, selected text

**Replacement Plan**:
A locally verifiable plan for replacing or removing one or more **Operation Targets** inside an **Operation Window**.
_Avoid_: LLM edit result, rewritten paragraph

**Text Revision**:
A **Voice Text Operation** that changes existing text without changing the user's underlying intent.
_Avoid_: Edit, polish, rewrite

**Text Generation**:
A **Voice Text Operation** that creates insertable text from the user's spoken requirements for the current **Input Environment**.
_Avoid_: Writing, AI writing

**Text Removal**:
A **Voice Text Operation** that deletes an **Explicit Selection** or, for a generic delete request, the current safe text range exposed by the **Input Environment**.
_Avoid_: Delete command

**Shortcut Invocation**:
A **Voice Keyboard Operation** that triggers a named low-conflict local keyboard-style action.
_Avoid_: Macro, hotkey dump, power-user automation

**Application Launch**:
A **Voice Keyboard Operation** that opens a locally installed application by a discovered or configured name.
_Avoid_: App automation, provider-guessed executable

**System Window Action**:
A **Voice Keyboard Operation** that moves or resizes the current desktop window through local system capabilities.
_Avoid_: Window macro, layout automation

**Shortcut Catalog**:
A local catalog of named low-conflict keyboard-style actions available for the current system or application context.
_Avoid_: Provider-generated shortcut list, freeform hotkey map

**Global Shortcut Catalog**:
A **Shortcut Catalog** for common system or broadly reusable shortcut actions.
_Avoid_: Default hotkey dump

**Application Shortcut Catalog**:
A **Shortcut Catalog** for named shortcut actions in the current application context.
_Avoid_: App macro list, provider shortcut guess

**Memo Operation**:
A **Voice Text Operation** that saves, recalls, deletes, or lists user-provided memos.
_Avoid_: Memory Operation, memory command

**Memo**:
A short user-provided text snippet saved for later insertion into the **Input Environment**.
_Avoid_: Knowledge base, long-term memory, user profile

**Speech Interpretation Provider**:
An external capability used by the **Voice Keyboard Engine** to turn speech or text context into text or operation decisions.
_Avoid_: STT provider, LLM provider, model, backend

## Relationships

- A **Voice Keyboard Engine** acts on exactly one current **Input Environment** at a time.
- A **Voice Keyboard Operation** is atomic at the user-visible workflow level.
- Internal implementation steps do not make a **Voice Keyboard Operation** non-atomic when they serve one user-visible intent.
- **Dictation** is one kind of **Voice Text Operation**, and every **Voice Text Operation** is a **Voice Keyboard Operation**.
- **Dictation** produces a **Text Insertion** from recognized speech.
- **Dictation Mode** produces **Dictation**.
- **Instruction Mode** interprets speech as a request for a **Voice Keyboard Operation**.
- **Atomic Operation Stack** belongs to **Instruction Mode**; **Dictation Mode** does not participate in stacks.
- A **Capture Path** supplies speech to either **Dictation Mode** or **Instruction Mode**.
- A **Software Capture Path** and a **Hardware Capture Path** are both **Capture Paths**.
- An **Explicit Selection** takes precedence for operations that modify existing text.
- When there is no **Explicit Selection**, replacement-style edit operations default to the current **Tracked Segment** when one exists.
- Without an **Explicit Selection** or **Tracked Segment**, local partial replacement should fail closed and ask the user to select the text.
- Local partial removal without an **Explicit Selection** should fail closed and ask the user to select the text unless the user asks for the whole scope.
- An **Operation Window** is context for a replacement-style operation; it is not automatically the **Operation Target**.
- A **Replacement Plan** must be checked against the current **Operation Window** before the engine applies it.
- **Instruction Mode** may produce a **Text Revision**, **Text Generation**, **Text Removal**, **Shortcut Invocation**, **Application Launch**, **System Window Action**, or **Memo Operation**.
- Spoken undo is a **Shortcut Invocation** of the current **Input Environment** undo action, not a separate local text history feature.
- A **Shortcut Invocation** is a **Voice Keyboard Operation** but not a **Voice Text Operation** unless it changes text in the **Input Environment**.
- **Shortcut Invocation** is a core operation type for common repeated keyboard-style work, not an exhaustive automation surface.
- A **Shortcut Invocation** is atomic when it names one user-visible shortcut action, even if the implementation sends multiple low-level key events.
- **Shortcut Invocation** should target a named action from a local **Shortcut Catalog**.
- A **Speech Interpretation Provider** may choose from a **Shortcut Catalog** but should not invent shortcut actions or key sequences.
- **Application Launch** is core only for locally discovered or explicitly configured applications.
- **System Window Action** is core only when it affects the current local desktop window through a local adapter.
- A **Global Shortcut Catalog** supplies common actions; an **Application Shortcut Catalog** supplies current-application actions.
- When shortcut names conflict, the **Application Shortcut Catalog** takes precedence over the **Global Shortcut Catalog**.
- A **Memo Operation** acts on **Memo**.
- **Text Generation** is core only when the generated text is meant to enter the **Input Environment**.
- **Text Insertion** inserts text that is already provided or resolved; **Text Generation** creates new insertable text from requirements.
- **Memo Operation** recall may produce a **Text Insertion** after it resolves a saved text snippet.
- **High-Risk Operation** is an execution policy label, not a separate operation type.
- Auxiliary feedback is not a core **Voice Keyboard Operation** unless it changes or drives the current **Input Environment**.
- A **Voice Keyboard Engine** may rely on a **Speech Interpretation Provider** but does not own that provider's account, billing, quota, or model lifecycle.
- **Voice Keyboard Engine** does not own account, subscription, payment, or cloud entitlement concepts.

## Example dialogue

> **Dev:** "Should **Voice Keyboard Engine** know whether the user has paid for TypeUp?"
> **Domain expert:** "No. It may call a provider that enforces access, but payment and entitlement are outside this context."

## Flagged ambiguities

- "Voice Keyboard" was used to mean the hardware product, the local agent, and the repository; resolved: the bounded context is **Voice Keyboard Engine**.
- The project was described as "voice typing"; resolved: the broader intent is **Voice Keyboard Operation**, with **Dictation** as one text operation type.
- "AI key mode" was used for intent-driven behavior; resolved: the domain term is **Instruction Mode** because AI is an implementation detail.
- "AI-native" can overstate the product identity; resolved: the product is a general-purpose voice-driven keyboard efficiency layer, and AI is only one implementation technique for interpreting speech into user operations.
- "operation sequence" would make permissions, confirmation, and rollback too broad for the current product; resolved: allow only an **Atomic Operation Stack** of user-explicit operations, not autonomous planning.
- "hardware mode" and "software mode" were used as product modes; resolved: they are **Capture Path** variants, not separate operation modes.
- `TextBuffer` and `current_segment` are implementation terms; resolved: the domain term is **Tracked Segment**.
- "operation object" can mean either the safe context range or the text actually changed; resolved: use **Operation Window** for the safe context and **Operation Target** for the replace/remove span.
- "chat" exists as an auxiliary feedback behavior, but is not a core **Voice Keyboard Operation** unless it changes or drives the **Input Environment**.
- Older reusable-snippet operation names were ambiguous; resolved: the domain term is **Memo Operation**.
- "memory" is limited to **Memo**; it does not mean chat memory, user profiling, cross-device knowledge sync, or a personal knowledge base.
- "shortcut" can sound like power-user hotkey automation; resolved: inside this context, **Shortcut Invocation** means a curated low-conflict keyboard-style action for ordinary repeated work.
- Provider names such as Xunfei, OpenAI, Aliyun, Volcengine, ZhipuAI, and TypeUp Backend are integration choices, not domain terms.
- "Agent" names a local process and code package, not a domain concept; resolved: domain language uses **Voice Keyboard Engine**.
# Development Notes - Memo Library Intent Work

Last updated: 2026-06-10

Current focus: AI key memo library input/query reliability.

User requirements confirmed:
- Saving a memo must require selected text.
- The selected text is the memo value.
- Spoken command text is only used to infer the memo key/name, preferably with LLM extraction rather than hard-coded parsing.
- Memo library should update live in the main window after saves/deletes.
- Memo input/query keywords should be visible and editable in the main window Memo Library tab.
- Edited keywords must sync into intent classification without requiring code changes.
- Query trigger words such as `查一下`, `查询`, `调出`, `调取`, `读取` should wake memo lookup directly. The user does not want to always say `记忆库` or `备忘录`.

Implemented in this session:
- Added configurable `MemoTriggerConfig` in `agent/ai_intent.py`.
- Added `instruction_mode.intent_fallbacks.memo_triggers` support in config.
- Added memo trigger keyword fields to the main window Memo Library tab:
  - save words
  - lookup actions
  - wake words
  - delete words
- Saving those fields writes config and reloads runtime config.
- Fixed main window crash where generic config loading tried to split non-config UI variable names like `memo_save_words` as `section.key`.
- Added memo store reload behavior so existing `MemoStore` instances see external file changes.
- Added main window memo polling/refresh for live memory library updates.
- Added save fallback in `AIHandler`: if selected text exists and spoken text looks like memo-save, force memo save and use LLM/fallback key extraction.
- Tightened save behavior: without selected text, memo save commands prompt the user to select text first.

Important latest change:
- Memo lookup was too strict: it required both a query action and a memory wake word.
- This made natural commands such as `查一下我的手机号` and `查一下我家地址` classify as chat.
- The intended fix is now: any configured lookup action should enter memo lookup. The lookup query should be cleaned before fuzzy key matching by removing action words and filler words like `我的`, `我家`, `是什么`, `是多少`.

Potential files touched:
- `agent/ai_intent.py`
- `agent/ai_handler.py`
- `agent/memo_store.py`
- `agent/windows_main_window.py`
- `agent/runtime_composition.py`
- `config.yaml.example`
- tests under `test/`

Verified follow-up:
- Re-ran tests after the latest lookup-trigger edit; verification now passes on Windows.
- Verified specifically:
  - `查一下我的手机号` recalls memo key `手机号`
  - `查一下我家地址` recalls memo key `地址`
  - `调出我的地址` recalls memo key `地址`
  - plain `我的手机号是多少` remains chat unless configured otherwise
- Verified commands:
  - `.\.venv\Scripts\python.exe -m unittest discover -s test -p "test_ai_intent.py"`
  - `.\.venv\Scripts\python.exe -m unittest discover -s test -p "test_ai_handler_runtime.py"`
  - `.\.venv\Scripts\python.exe -m unittest discover -s test -p "test_windows_main_window.py"`
  - `.\.venv\Scripts\python.exe -m unittest discover -s test -p "test_runtime_composition.py"`
  - `.\.venv\Scripts\python.exe -m compileall -q agent test`

CMD startup command:

```cmd
cd /d C:\Users\100448405\voice-keyboard
.\.venv\Scripts\python.exe -m agent.windows_tray
```
