"""Platform text I/O adapter for the Voice Keyboard Engine Input Environment."""

from dataclasses import dataclass
from typing import Protocol

from agent.correction_memory import CorrectionTextSnapshot
from agent.focused_text_capture import FocusedTextCapture, TyperFocusedTextCapture
from agent import typer


@dataclass(frozen=True)
class CaretTextWindow:
    text: str
    source: str = "caret"


@dataclass(frozen=True)
class ShortcutCatalogEntry:
    name: str
    source: str
    risk: str = "normal"
    application: str = ""
    kind: str = "shortcut"
    aliases: tuple[str, ...] = ()


@dataclass(frozen=True)
class ShortcutPolicyDecision:
    name: str
    found: bool
    allowed: bool
    risk: str = "normal"
    source: str = ""
    application: str = ""
    reason: str = ""
    kind: str = "shortcut"

    @classmethod
    def missing(cls, name: str) -> "ShortcutPolicyDecision":
        return cls(
            name=name,
            found=False,
            allowed=False,
            reason="not_in_shortcut_catalog",
        )


class TextIO(Protocol):
    def can_insert_text(self) -> bool:
        ...

    def confirm_paste_text(self, text: str) -> bool:
        ...

    def paste_text(self, text: str) -> None:
        ...

    def get_selection(self) -> str:
        ...

    def get_caret_text_window(self) -> CaretTextWindow | None:
        ...

    def get_full_focused_text_snapshot(self) -> CorrectionTextSnapshot:
        ...

    def get_screen_text_snapshot(self, expected_text: str = "") -> CorrectionTextSnapshot:
        ...

    def type_text(self, text: str) -> None:
        ...

    def jump_to_end(self) -> None:
        ...

    def replace_selection(self, text: str, original: str = "") -> None:
        ...

    def replace_text_window(self, original: str, replacement: str) -> bool:
        ...

    def delete_selection(self, original: str = "") -> None:
        ...

    def erase_last(self, text: str) -> None:
        ...

    def list_shortcuts(self) -> list[str]:
        ...

    def shortcut_catalog(self) -> list[ShortcutCatalogEntry]:
        ...

    def shortcut_policy_for_invocation(
        self,
        name: str,
        *,
        in_atomic_stack: bool = False,
    ) -> ShortcutPolicyDecision:
        ...

    def send_shortcut(self, name: str) -> bool:
        ...

    def current_application_label(self) -> str:
        ...


class TyperTextIO:
    """Adapter that keeps platform typing details out of Input Environment rules."""

    def __init__(self, focused_text_capture: FocusedTextCapture | None = None):
        self._focused_text_capture = focused_text_capture or TyperFocusedTextCapture()

    def can_insert_text(self) -> bool:
        return typer.has_focused_text_input()

    def confirm_paste_text(self, text: str) -> bool:
        return typer.confirm_paste_without_focused_input(text)

    def paste_text(self, text: str) -> None:
        typer.paste_text(text)

    def get_selection(self) -> str:
        return typer.get_selection()

    def get_caret_text_window(self) -> CaretTextWindow | None:
        window = self._focused_text_capture.caret_window()
        if window is None:
            return None
        return CaretTextWindow(text=window.text, source=window.source)

    def get_full_focused_text_snapshot(self) -> CorrectionTextSnapshot:
        return self._focused_text_capture.full_focused_snapshot()

    def get_screen_text_snapshot(self, expected_text: str = "") -> CorrectionTextSnapshot:
        return self._focused_text_capture.screen_snapshot(expected_text)

    def type_text(self, text: str) -> None:
        typer.type_text(text)

    def jump_to_end(self) -> None:
        typer.jump_to_end()

    def replace_selection(self, text: str, original: str = "") -> None:
        typer.replace_selection(text, original=original)

    def replace_text_window(self, original: str, replacement: str) -> bool:
        return typer.replace_text_window(original, replacement)

    def delete_selection(self, original: str = "") -> None:
        typer.delete_selection(original=original)

    def erase_last(self, text: str) -> None:
        typer.erase_last(text)

    def list_shortcuts(self) -> list[str]:
        return typer.list_shortcuts()

    def shortcut_catalog(self) -> list[ShortcutCatalogEntry]:
        return [
            ShortcutCatalogEntry(
                name=entry.name,
                source=entry.source,
                risk=entry.risk,
                application=entry.application,
                kind=entry.kind,
                aliases=tuple(getattr(entry, "aliases", ()) or ()),
            )
            for entry in typer.shortcut_catalog()
        ]

    def shortcut_policy_for_invocation(
        self,
        name: str,
        *,
        in_atomic_stack: bool = False,
    ) -> ShortcutPolicyDecision:
        decision = typer.shortcut_policy_for_invocation(
            name,
            in_atomic_stack=in_atomic_stack,
        )
        return ShortcutPolicyDecision(
            name=decision.name,
            found=decision.found,
            allowed=decision.allowed,
            risk=decision.risk,
            source=decision.source,
            application=decision.application,
            reason=decision.reason,
            kind=decision.kind,
        )

    def send_shortcut(self, name: str) -> bool:
        return typer.send_shortcut(name)

    def current_application_label(self) -> str:
        return typer.current_application().label
