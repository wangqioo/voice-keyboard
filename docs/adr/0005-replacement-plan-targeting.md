# Replacement plan targeting

Instruction Mode text changes should be modeled as locally verifiable replacement plans, not as direct rewrites of whichever text range was used as provider context.

The Voice Keyboard Engine first determines an Operation Window: the current text range it considers safe to inspect and use as context. An Explicit Selection is the strongest window. When there is no Explicit Selection, the default window is the current safe text range exposed by the Input Environment, such as the focused field, current paragraph, current sentence, or another platform-supported caret-local window. If that window is unavailable, a safe Tracked Segment may be used as a fallback. The window bounds what the engine may send to a Speech Interpretation Provider and what it may later modify.

The Operation Window is not automatically the Operation Target. A provider may use the whole window to understand the user's instruction, but it should return a Replacement Plan that identifies the specific target text or target spans to replace or remove. For example, when the caret is inside a paragraph and the user says "make the first sentence more formal", the paragraph can be the Operation Window while only the first sentence is the Operation Target.

The engine must verify a Replacement Plan locally before applying it:

- The target text must still be present inside the current Operation Window.
- The plan must not change text outside the Operation Window.
- Ambiguous, missing, or low-confidence targets should fail closed and ask the user to select or narrow the text.
- Applied changes should be recorded as operation effects so Operation Reversal can restore the previous text.

This keeps paid provider calls useful for semantic targeting and rewriting while keeping final authority over text mutation local to the Input Environment. It also avoids the unsafe fallback where "no Explicit Selection" means "rewrite arbitrary prior text"; the no-selection default must come from a current safe Operation Window supplied by the Input Environment.

The current implementation supports Explicit Selection, platform-provided caret-local windows, and safe Tracked Segment fallback. That behavior is an interim state until more platforms can expose focused-field or document-local windows consistently.
