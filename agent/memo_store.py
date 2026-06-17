"""Simple JSON store for Memo."""

import json
import threading
from pathlib import Path
from typing import Optional

from agent.memo import MemoRecord


class MemoStore:
    def __init__(self, path: Optional[Path] = None, legacy_path: Optional[Path] = None):
        self._path = path or Path.home() / ".voice-keyboard" / "memo.json"
        if legacy_path is not None:
            self._legacy_paths = (legacy_path,)
        elif path is None:
            root = Path.home() / ".voice-keyboard"
            self._legacy_paths = (
                root / "reusable_text_memory.json",
                root / "memos.json",
            )
        else:
            self._legacy_paths = ()
        self._lock = threading.Lock()
        self._data: dict[str, MemoRecord] = {}
        self._mtime_ns: int | None = None
        self._load()

    def _load(self) -> None:
        if self._path.exists():
            self._data = self._read_data(self._path)
            self._mtime_ns = self._path.stat().st_mtime_ns
            return
        for legacy_path in self._legacy_paths:
            if not legacy_path.exists():
                continue
            self._data = self._read_data(legacy_path)
            if self._data:
                self._save()
            elif self._path.exists():
                self._mtime_ns = self._path.stat().st_mtime_ns
            return

    def _reload_if_changed(self) -> None:
        try:
            mtime_ns = self._path.stat().st_mtime_ns
        except FileNotFoundError:
            if self._mtime_ns is not None:
                self._data = {}
                self._mtime_ns = None
            return
        if self._mtime_ns is None or mtime_ns != self._mtime_ns:
            self._data = self._read_data(self._path)
            self._mtime_ns = mtime_ns

    def _read_data(self, path: Path) -> dict[str, MemoRecord]:
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(raw, dict):
                return {}
            return {
                str(key): record
                for key, value in raw.items()
                if (record := self._read_record(str(key), value)) is not None
            }
        except Exception as e:
            print(f"[memo] 读取失败 {path}: {e}")
            return {}

    def _read_record(self, key: str, raw) -> MemoRecord | None:
        if isinstance(raw, str):
            return MemoRecord(key=key, value=raw)
        if not isinstance(raw, dict):
            return None
        value = raw.get("value", "")
        aliases = raw.get("aliases", ())
        if isinstance(aliases, str):
            aliases = (aliases,)
        elif not isinstance(aliases, (list, tuple)):
            aliases = ()
        return MemoRecord(
            key=key,
            value=str(value) if value is not None else "",
            aliases=tuple(str(alias) for alias in aliases if str(alias).strip()),
            value_type=str(raw.get("value_type") or ""),
            sensitive=bool(raw.get("sensitive", False)),
        )

    def _save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(
            json.dumps(self._canonical_data(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        self._mtime_ns = self._path.stat().st_mtime_ns

    def _canonical_data(self) -> dict[str, dict]:
        return {
            key: {
                "value": record.value,
                "aliases": list(record.aliases),
                "value_type": record.value_type,
                "sensitive": record.sensitive,
            }
            for key, record in self._data.items()
        }

    def save(self, key: str, value: str) -> None:
        with self._lock:
            self._reload_if_changed()
            existing = self._data.get(key)
            self._data[key] = MemoRecord(
                key=key,
                value=value,
                aliases=existing.aliases if existing is not None else (),
                value_type=existing.value_type if existing is not None else "",
                sensitive=existing.sensitive if existing is not None else False,
            )
            self._save()

    def save_record(self, key: str, value: str, *, aliases: tuple[str, ...] = ()) -> None:
        with self._lock:
            self._reload_if_changed()
            existing = self._data.get(key)
            self._data[key] = MemoRecord(
                key=key,
                value=value,
                aliases=_normalized_aliases(aliases),
                value_type=existing.value_type if existing is not None else "",
                sensitive=existing.sensitive if existing is not None else False,
            )
            self._save()

    def get(self, key: str) -> Optional[str]:
        with self._lock:
            self._reload_if_changed()
            record = self._data.get(key)
            return None if record is None else record.value

    def delete(self, key: str) -> bool:
        with self._lock:
            self._reload_if_changed()
            if key in self._data:
                del self._data[key]
                self._save()
                return True
            return False

    def keys(self) -> list[str]:
        with self._lock:
            self._reload_if_changed()
            return list(self._data.keys())

    def records(self) -> tuple[MemoRecord, ...]:
        with self._lock:
            self._reload_if_changed()
            return tuple(self._data.values())


def _normalized_aliases(raw_aliases: tuple[str, ...]) -> tuple[str, ...]:
    aliases = []
    for alias in raw_aliases:
        text = str(alias or "").strip()
        if text and text not in aliases:
            aliases.append(text)
    return tuple(aliases)
