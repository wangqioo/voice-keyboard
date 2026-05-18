"""Reversible effects produced by Instruction Mode operations."""

from dataclasses import dataclass
from typing import Literal

EffectKind = Literal["replace", "insert", "delete"]


@dataclass(frozen=True)
class OperationEffect:
    kind: EffectKind
    old_text: str = ""
    new_text: str = ""

    @classmethod
    def replace(cls, old_text: str, new_text: str) -> "OperationEffect":
        return cls("replace", old_text=old_text, new_text=new_text)

    @classmethod
    def insert(cls, text: str) -> "OperationEffect":
        return cls("insert", new_text=text)

    @classmethod
    def delete(cls, text: str) -> "OperationEffect":
        return cls("delete", old_text=text)


class OperationHistory:
    def __init__(self, limit: int = 5):
        self._limit = limit
        self._effects: list[OperationEffect] = []

    def push(self, effect: OperationEffect) -> None:
        self._effects.append(effect)
        if len(self._effects) > self._limit:
            self._effects.pop(0)

    def pop(self) -> OperationEffect | None:
        if not self._effects:
            return None
        return self._effects.pop()

    def __len__(self) -> int:
        return len(self._effects)

    def snapshot(self) -> tuple[OperationEffect, ...]:
        return tuple(self._effects)
