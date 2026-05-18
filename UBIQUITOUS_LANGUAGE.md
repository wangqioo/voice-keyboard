# Ubiquitous Language

## Voice-driven keyboard efficiency

| Term | Definition | Aliases to avoid |
| --- | --- | --- |
| **Voice Keyboard Engine** | The local engine that turns speech into text changes or keyboard-style operations in the current input environment. | TypeUp Engine, Agent, AI assistant |
| **Voice Keyboard Operation** | A user-requested text change or keyboard-style action applied to the current input environment based on speech. | AI command, prompt, agent action |
| **Atomic Operation Stack** | A short ordered stack of Voice Keyboard Operations explicitly requested by the user in one spoken instruction. | Agent plan, autonomous workflow, implicit operation sequence |
| **Voice Text Operation** | A Voice Keyboard Operation that creates, changes, removes, restores, or recalls text. | Voice command, AI command |
| **High-Risk Operation** | A Voice Keyboard Operation risk label for actions that may submit, send, delete, overwrite broad content, cross application boundaries, or be hard to reverse. | Dangerous command, privileged action |
| **Text Insertion** | A Voice Text Operation that inserts user-provided or already resolved text into the current Input Environment. | Dictation Mode, AI writing |
| **Shortcut Invocation** | A Voice Keyboard Operation that triggers one named user-visible system or application shortcut action. | Macro, hotkey command, AI action |
| **Shortcut Catalog** | A local catalog of named user-visible shortcut actions available for the current system or application context. | Provider-generated shortcut list, freeform hotkey map |
| **Global Shortcut Catalog** | A Shortcut Catalog for common system or broadly reusable shortcut actions. | Default hotkey dump |
| **Application Shortcut Catalog** | A Shortcut Catalog for named shortcut actions in the current application context. | App macro list, provider shortcut guess |
| **Reusable Text Operation** | A Voice Text Operation that saves, recalls, deletes, or lists user-provided reusable text snippets. | Memory Operation, memo feature, memory command |
| **Reusable Text Memory** | A short user-provided text snippet saved for later insertion into the Input Environment. | Knowledge base, long-term memory, user profile |
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
| **Operation Window** | The current text range the Voice Keyboard Engine considers safe to inspect and use as context for a replacement-style Voice Text Operation. | Prompt context, whole paragraph target |
| **Operation Target** | The specific text range inside an Operation Window that a Voice Text Operation intends to replace or remove. | Full context, selected text |
| **Replacement Plan** | A locally verifiable plan for replacing or removing one or more Operation Targets inside an Operation Window. | LLM edit result, rewritten paragraph |

## Relationships

- A **Voice Keyboard Engine** acts on exactly one current **Input Environment** at a time.
- A **Voice Keyboard Operation** is the general product unit; a **Voice Text Operation** is the subset that changes or recalls text.
- A **Voice Keyboard Operation** is atomic at the user-visible workflow level.
- Internal implementation steps do not make a **Voice Keyboard Operation** non-atomic when they serve one user-visible intent.
- **Instruction Mode** may resolve one spoken instruction to one primary **Voice Keyboard Operation** or an **Atomic Operation Stack**.
- An **Atomic Operation Stack** may contain only user-explicit operations in the order the user requested.
- A **Speech Interpretation Provider** must not add implicit operations to an **Atomic Operation Stack**.
- An **Atomic Operation Stack** is short: two operations by default, up to three only when every operation is explicit and low risk.
- Cross-application workflows and **High-Risk Operations** should not run as an **Atomic Operation Stack** without a separate confirmation design.
- An **Atomic Operation Stack** executes in order; if one operation fails, later operations do not run.
- An **Atomic Operation Stack** does not auto-repair or auto-rollback; reversible changes rely on explicit **Operation Reversal**.
- **Operation Reversal** restores the most recent reversible atomic effect, not an entire **Atomic Operation Stack**.
- **Dictation Mode** produces **Dictation**, which is a **Voice Text Operation**.
- **Dictation** produces a **Text Insertion** from recognized speech.
- **Text Insertion** inserts text that is already provided or resolved; **Text Generation** creates new insertable text from requirements.
- **Reusable Text Operation** recall may produce a **Text Insertion** after it resolves a saved text snippet.
- In an **Atomic Operation Stack**, **Text Insertion** should come from explicit user text or resolved **Reusable Text Memory**.
- An **Atomic Operation Stack** should not combine **Text Generation** with high-risk submission shortcuts without a separate confirmation design.
- **High-Risk Operation** is an execution policy label, not a separate operation type.
- Local execution policy has final authority over whether a **Voice Keyboard Operation** is high risk.
- A **Speech Interpretation Provider** may propose an operation but must not bypass **High-Risk Operation** policy.
- **Atomic Operation Stack** belongs to **Instruction Mode**; **Dictation Mode** does not participate in stacks.
- **Instruction Mode** interprets speech as a request for a **Voice Keyboard Operation**.
- An **Explicit Selection** takes precedence for operations that modify existing text.
- When there is no **Explicit Selection**, the default **Operation Window** is the current safe text range exposed by the **Input Environment**.
- A **Shortcut Invocation** is a **Voice Keyboard Operation** but not necessarily a **Voice Text Operation**.
- A **Shortcut Invocation** is atomic when it names one user-visible shortcut action, even if implementation sends multiple low-level key events.
- **Shortcut Invocation** should target a named action from a local **Shortcut Catalog**.
- A **Speech Interpretation Provider** may choose from a **Shortcut Catalog** but should not invent shortcut actions or key sequences.
- A **Global Shortcut Catalog** supplies common actions; an **Application Shortcut Catalog** supplies current-application actions.
- When shortcut names conflict, the **Application Shortcut Catalog** takes precedence over the **Global Shortcut Catalog**.
- A **Reusable Text Operation** acts on **Reusable Text Memory** and is not AI memory, user profiling, or a personal knowledge base.
- A **Speech Interpretation Provider** may help classify or generate an operation, but the product identity is voice-driven keyboard efficiency, not chat-first or AI-native interaction.

## Example dialogue

> **Dev:** "Should we describe this as an AI assistant that edits text?"
> **Domain expert:** "No. The product is a **Voice Keyboard Engine**: it lets ordinary users drive keyboard-style operations by voice."
> **Dev:** "So saying 'save', 'undo', or 'send' should be modeled beside editing text?"
> **Domain expert:** "Yes. Those are **Voice Keyboard Operations**. Text edits are **Voice Text Operations**, while app shortcuts are **Shortcut Invocations**."
> **Dev:** "What about saving my email or a common reply?"
> **Domain expert:** "That is a **Reusable Text Operation** over **Reusable Text Memory**, not AI memory."
> **Dev:** "Where does the model provider fit?"
> **Domain expert:** "A **Speech Interpretation Provider** can help understand speech, but it does not define the product boundary."

## Flagged ambiguities

- "AI-native" makes the product sound like a chat-first assistant; use **Voice Keyboard Engine** and **Voice Keyboard Operation** to keep the focus on ordinary keyboard efficiency.
- "Voice typing" is too narrow; **Dictation** is only one **Voice Text Operation**.
- "Voice command" is vague; use **Voice Keyboard Operation** for the general operation and **Shortcut Invocation** for named shortcut execution.
- "AI key mode" describes an implementation trigger; use **Instruction Mode** for the user intent.
- "Memory Operation" implies AI memory; use **Reusable Text Operation** for saving, recalling, deleting, and listing reusable text snippets.
- "Operation Sequence" makes permission, confirmation, and rollback too broad when it implies autonomous planning; use **Atomic Operation Stack** only for user-explicit ordered operations.
