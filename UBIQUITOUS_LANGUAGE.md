# Ubiquitous Language

## Voice-driven keyboard efficiency

| Term | Definition | Aliases to avoid |
| --- | --- | --- |
| **Voice Keyboard Engine** | The local engine that turns speech into text changes or keyboard-style operations in the current input environment. | TypeUp Engine, Agent, AI assistant |
| **Voice Keyboard Operation** | A user-requested text change or keyboard-style action applied to the current input environment based on speech. | AI command, prompt, agent action |
| **Voice Text Operation** | A Voice Keyboard Operation that creates, changes, removes, restores, or recalls text. | Voice command, AI command |
| **Shortcut Invocation** | A Voice Keyboard Operation that triggers a named system or application shortcut. | Hotkey command, AI action |
| **Input Environment** | The application, field, cursor position, and selected text that will receive engine output. | App, editor, textbox |
| **Speech Interpretation Provider** | An external capability used to turn speech or text context into text or operation decisions. | STT provider, LLM provider, model, backend |

## Modes and capture

| Term | Definition | Aliases to avoid |
| --- | --- | --- |
| **Dictation Mode** | The mode where speech is treated as content to insert into the Input Environment. | Normal mode, PTT mode |
| **Instruction Mode** | The mode where speech is treated as an instruction for a Voice Keyboard Operation. | AI mode, AI key mode, command mode |
| **Capture Path** | The route by which speech enters the Voice Keyboard Engine. | Hardware mode, software mode |
| **Software Capture Path** | A Capture Path that records speech through a microphone already available to the computer. | Pure software mode |
| **Hardware Capture Path** | A Capture Path that records speech through a dedicated Voice Keyboard device. | Hardware mode |

## Text safety

| Term | Definition | Aliases to avoid |
| --- | --- | --- |
| **Explicit Selection** | Text the user has deliberately selected in the Input Environment. | Selection, selected text |
| **Tracked Segment** | Text recently inserted by the Voice Keyboard Engine that the engine still considers safe to replace or delete. | TextBuffer, current segment |
| **Operation Window** | The maximum text range the Voice Keyboard Engine currently considers safe to inspect and use as context for a replacement-style Voice Text Operation. | Prompt context, whole paragraph target |
| **Operation Target** | The specific text range inside an Operation Window that a Voice Text Operation intends to replace or remove. | Full context, selected text |
| **Replacement Plan** | A locally verifiable plan for replacing or removing one or more Operation Targets inside an Operation Window. | LLM edit result, rewritten paragraph |

## Relationships

- A **Voice Keyboard Engine** acts on exactly one current **Input Environment** at a time.
- A **Voice Keyboard Operation** is the general product unit; a **Voice Text Operation** is the subset that changes or recalls text.
- **Dictation Mode** produces **Dictation**, which is a **Voice Text Operation**.
- **Instruction Mode** interprets speech as a request for a **Voice Keyboard Operation**.
- A **Shortcut Invocation** is a **Voice Keyboard Operation** but not necessarily a **Voice Text Operation**.
- A **Speech Interpretation Provider** may help classify or generate an operation, but the product identity is voice-driven keyboard efficiency, not chat-first or AI-native interaction.

## Example dialogue

> **Dev:** "Should we describe this as an AI assistant that edits text?"
> **Domain expert:** "No. The product is a **Voice Keyboard Engine**: it lets ordinary users drive keyboard-style operations by voice."
> **Dev:** "So saying 'save', 'undo', or 'send' should be modeled beside editing text?"
> **Domain expert:** "Yes. Those are **Voice Keyboard Operations**. Text edits are **Voice Text Operations**, while app shortcuts are **Shortcut Invocations**."
> **Dev:** "Where does the model provider fit?"
> **Domain expert:** "A **Speech Interpretation Provider** can help understand speech, but it does not define the product boundary."

## Flagged ambiguities

- "AI-native" makes the product sound like a chat-first assistant; use **Voice Keyboard Engine** and **Voice Keyboard Operation** to keep the focus on ordinary keyboard efficiency.
- "Voice typing" is too narrow; **Dictation** is only one **Voice Text Operation**.
- "Voice command" is vague; use **Voice Keyboard Operation** for the general operation and **Shortcut Invocation** for named shortcut execution.
- "AI key mode" describes an implementation trigger; use **Instruction Mode** for the user intent.
