"""Compatibility import for the renamed Reusable Text Memory store."""

from agent.reusable_text_memory_store import ReusableTextMemoryStore


class MemoStore(ReusableTextMemoryStore):
    """Backward-compatible name for older imports."""
