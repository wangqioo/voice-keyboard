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
A user-requested text change or keyboard-style action applied to the current **Input Environment** based on speech.
_Avoid_: AI command, prompt, agent action

**Voice Text Operation**:
A **Voice Keyboard Operation** that creates, changes, removes, restores, or recalls text in the current **Input Environment**.
_Avoid_: AI command, voice command, prompt

**Dictation**:
A **Voice Text Operation** that inserts the user's spoken words as text with minimal cleanup.
_Avoid_: STT result, transcription

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
The maximum text range the **Voice Keyboard Engine** currently considers safe to inspect and use as context for a replacement-style **Voice Text Operation**.
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
A **Voice Text Operation** that creates new text from the user's spoken requirements.
_Avoid_: Writing, AI writing

**Text Removal**:
A **Voice Text Operation** that deletes an **Explicit Selection** or a safe **Tracked Segment**.
_Avoid_: Delete command

**Operation Reversal**:
A **Voice Text Operation** that restores the previous state affected by the last reversible engine operation.
_Avoid_: Undo, Ctrl+Z

**Shortcut Invocation**:
A **Voice Keyboard Operation** that triggers a named system or application shortcut.
_Avoid_: Command, hotkey command

**Memory Operation**:
A **Voice Text Operation** that saves, recalls, deletes, or lists user-provided reusable text snippets.
_Avoid_: Memo feature, memory command

**Reusable Text Memory**:
A short user-provided text snippet saved for later insertion into the **Input Environment**.
_Avoid_: Knowledge base, long-term memory, user profile

**Speech Interpretation Provider**:
An external capability used by the **Voice Keyboard Engine** to turn speech or text context into text or operation decisions.
_Avoid_: STT provider, LLM provider, model, backend

## Relationships

- A **Voice Keyboard Engine** acts on exactly one current **Input Environment** at a time.
- **Dictation** is one kind of **Voice Text Operation**, and every **Voice Text Operation** is a **Voice Keyboard Operation**.
- **Dictation Mode** produces **Dictation**.
- **Instruction Mode** interprets speech as a request for a **Voice Keyboard Operation**.
- A **Capture Path** supplies speech to either **Dictation Mode** or **Instruction Mode**.
- A **Software Capture Path** and a **Hardware Capture Path** are both **Capture Paths**.
- An **Explicit Selection** takes precedence over a **Tracked Segment** for operations that modify existing text.
- A **Tracked Segment** can be modified only while the engine still considers it safe.
- An **Operation Window** is context for a replacement-style operation; it is not automatically the **Operation Target**.
- A **Replacement Plan** must be checked against the current **Operation Window** before the engine applies it.
- **Instruction Mode** may produce a **Text Revision**, **Text Generation**, **Text Removal**, **Operation Reversal**, **Shortcut Invocation**, or **Memory Operation**.
- A **Shortcut Invocation** is a **Voice Keyboard Operation** but not a **Voice Text Operation** unless it changes text in the **Input Environment**.
- A **Memory Operation** acts on **Reusable Text Memory**.
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
- "hardware mode" and "software mode" were used as product modes; resolved: they are **Capture Path** variants, not separate operation modes.
- `TextBuffer`, `current_segment`, and `cursor_uncertain` are implementation terms; resolved: the domain terms are **Tracked Segment** and safe/unsafe operation on it.
- "operation object" can mean either the safe context range or the text actually changed; resolved: use **Operation Window** for the safe context and **Operation Target** for the replace/remove span.
- "chat" exists as an auxiliary response behavior, but is not a core **Voice Text Operation** unless it changes the **Input Environment**.
- "memory" is limited to **Reusable Text Memory**; it does not mean chat memory, user profiling, cross-device knowledge sync, or a personal knowledge base.
- Provider names such as Xunfei, OpenAI, Aliyun, Volcengine, ZhipuAI, and TypeUp Backend are integration choices, not domain terms.
- "Agent" names a local process and code package, not a domain concept; resolved: domain language uses **Voice Keyboard Engine**.
