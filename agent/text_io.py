"""Platform text I/O adapter for the Voice Keyboard Engine Input Environment."""

from dataclasses import dataclass
from typing import Protocol

from agent import typer


@dataclass(frozen=True)
class CaretTextWindow:
    text: str
    source: str = "caret"


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

    def send_shortcut(self, name: str) -> bool:
        ...

    def current_application_label(self) -> str:
        ...


@dataclass(frozen=True)
class TyperTextIO:
    """Adapter that keeps platform typing details out of Input Environment rules."""

    def can_insert_text(self) -> bool:
        return typer.has_focused_text_input()

    def confirm_paste_text(self, text: str) -> bool:
        return typer.confirm_paste_without_focused_input(text)

    def paste_text(self, text: str) -> None:
        typer.paste_text(text)

    def get_selection(self) -> str:
        return typer.get_selection()

    def get_caret_text_window(self) -> CaretTextWindow | None:
        window = typer.get_caret_text_window()
        if window is None:
            return None
        return CaretTextWindow(text=window.text, source=window.source)

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

    def send_shortcut(self, name: str) -> bool:
        return typer.send_shortcut(name)

    def current_application_label(self) -> str:
        return typer.current_application().label
