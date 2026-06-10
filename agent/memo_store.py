"""Simple JSON store for Memo."""

import json
import threading
from pathlib import Path
from typing import Optional


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
        self._data: dict[str, str] = {}
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

    def _read_data(self, path: Path) -> dict[str, str]:
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            return raw if isinstance(raw, dict) else {}
        except Exception as e:
            print(f"[memo] 读取失败 {path}: {e}")
            return {}

    def _save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(
            json.dumps(self._data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        self._mtime_ns = self._path.stat().st_mtime_ns

    def save(self, key: str, value: str) -> None:
        with self._lock:
            self._reload_if_changed()
            self._data[key] = value
            self._save()

    def get(self, key: str) -> Optional[str]:
        with self._lock:
            self._reload_if_changed()
            return self._data.get(key)

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
