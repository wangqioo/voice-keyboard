"""Simple JSON store for Reusable Text Memory."""

import json
import threading
from pathlib import Path
from typing import Optional


class ReusableTextMemoryStore:
    def __init__(self, path: Optional[Path] = None, legacy_path: Optional[Path] = None):
        self._path = path or Path.home() / ".voice-keyboard" / "reusable_text_memory.json"
        self._legacy_path = (
            legacy_path
            if legacy_path is not None
            else (Path.home() / ".voice-keyboard" / "memos.json" if path is None else None)
        )
        self._lock = threading.Lock()
        self._data: dict[str, str] = {}
        self._load()

    def _load(self) -> None:
        if self._path.exists():
            self._data = self._read_data(self._path)
            return
        if self._legacy_path is not None and self._legacy_path.exists():
            self._data = self._read_data(self._legacy_path)
            if self._data:
                self._save()

    def _read_data(self, path: Path) -> dict[str, str]:
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            return raw if isinstance(raw, dict) else {}
        except Exception as e:
            print(f"[reusable-text-memory] 读取失败 {path}: {e}")
            return {}

    def _save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(
            json.dumps(self._data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def save(self, key: str, value: str) -> None:
        with self._lock:
            self._data[key] = value
            self._save()

    def get(self, key: str) -> Optional[str]:
        return self._data.get(key)

    def delete(self, key: str) -> bool:
        with self._lock:
            if key in self._data:
                del self._data[key]
                self._save()
                return True
            return False

    def keys(self) -> list[str]:
        return list(self._data.keys())
