# Atomic Operation Stack boundary

Instruction Mode may resolve one spoken instruction to one primary Voice Keyboard Operation or to a short Atomic Operation Stack. A stack is a user-explicit ordered list of Voice Keyboard Operations, not an autonomous plan produced by a Speech Interpretation Provider.

The stack boundary is intentionally narrow. It supports simple atomic composition such as inserting explicit text and invoking one shortcut, or removing one target and then revising the remaining text when both operations are explicitly requested. It does not support open-ended agent workflows, implicit provider-added steps, cross-application automation, or broad high-risk side effects without a separate confirmation design.

An Atomic Operation Stack should contain two operations by default and at most three when every operation is explicit and low risk. The engine executes the stack in order. If one operation fails, later operations do not run. The engine does not auto-repair or auto-rollback a stack; reversible changes are handled by explicit Operation Reversal.

Operation Reversal applies to the most recent reversible atomic effect, not to an entire stack. Dictation Mode does not participate in stacks, although Instruction Mode may include a Text Insertion operation when the text is explicit or resolved from Reusable Text Memory.
