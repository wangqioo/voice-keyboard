# Replacement plan targeting

Instruction Mode text changes should be modeled as locally verifiable replacement plans, not as direct rewrites of whichever text range was used as provider context.

The Voice Keyboard Engine first determines an Operation Window: the largest text range it currently considers safe to inspect and use as context. An Explicit Selection is the strongest window. A safe Tracked Segment may be a window. Future platform adapters may expose a caret-local window such as the current sentence, paragraph, or focused field neighborhood. The window bounds what the engine may send to a Speech Interpretation Provider and what it may later modify.

The Operation Window is not automatically the Operation Target. A provider may use the whole window to understand the user's instruction, but it should return a Replacement Plan that identifies the specific target text or target spans to replace or remove. For example, when the caret is inside a paragraph and the user says "make the first sentence more formal", the paragraph can be the Operation Window while only the first sentence is the Operation Target.

The engine must verify a Replacement Plan locally before applying it:

- The target text must still be present inside the current Operation Window.
- The plan must not change text outside the Operation Window.
- Ambiguous, missing, or low-confidence targets should fail closed and ask the user to select or narrow the text.
- Applied changes should be recorded as operation effects so Operation Reversal can restore the previous text.

This keeps paid provider calls useful for semantic targeting and rewriting while keeping final authority over text mutation local to the Input Environment. It also avoids the unsafe fallback where "no Explicit Selection" means "rewrite the whole paragraph".

The current implementation still treats an Explicit Selection or whole Tracked Segment as the edit input and replacement unit. That behavior is a conservative interim state, not the final model.
