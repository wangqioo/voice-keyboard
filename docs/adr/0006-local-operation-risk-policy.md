# Local operation risk policy

Voice Keyboard Engine should treat High-Risk Operation as a local execution policy label, not as a provider-owned classification. A Speech Interpretation Provider may propose a Voice Keyboard Operation, but the local engine must keep final authority over whether that operation is high risk and whether it may run in the current execution path.

This is especially important for Atomic Operation Stack support. A stack may contain only user-explicit operations, and high-risk operations such as sending, submitting, broad deletion, broad overwrite, or cross-application state changes should not run in a stack without a separate confirmation design.

Keeping the risk policy local prevents provider output from bypassing execution safety. Shortcut catalogs, operation metadata, and Input Environment details may provide risk signals, but the executor and local adapters remain responsible for enforcement.
