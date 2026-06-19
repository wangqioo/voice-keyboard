"""SQLite storage for intent-training samples.

The API layer is intentionally separate so the store can later be replaced by
PostgreSQL without changing the client upload protocol.
"""

from __future__ import annotations

import json
import sqlite3
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


REVIEW_LABELS = {
    "",
    "correct",
    "wrong_intent",
    "wrong_target",
    "unsafe_should_confirm",
    "missing_shortcut",
    "unclear",
}


@dataclass(frozen=True)
class SampleQuery:
    limit: int = 100
    offset: int = 0
    review_label: str | None = None
    intent_type: str | None = None
    status: str | None = None
    text: str | None = None


class IntentTrainingStore:
    def __init__(self, path: Path | str):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def create_batch(self, *, source: str = "", meta: dict | None = None) -> int:
        with self._managed_connection() as conn:
            cursor = conn.execute(
                "insert into batches(created_at, source, meta_json) values (?, ?, ?)",
                (time.time(), source, json.dumps(meta or {}, ensure_ascii=False)),
            )
            return int(cursor.lastrowid)

    def insert_samples(self, batch_id: int, samples: Iterable[dict]) -> int:
        count = 0
        with self._managed_connection() as conn:
            for sample in samples:
                normalized = _normalize_sample(sample)
                conn.execute(
                    """
                    insert into samples(
                        batch_id, created_at, ts, text, text_hash, active_application,
                        has_selection, selected_length, has_recent_text, recent_text_length,
                        shortcut_count, intent_type, intent_name, intent_key,
                    intent_source, intent_confidence, intent_cache_hit,
                    status, detail, review_label, review_note, corrected_intent_json,
                    operation_risk, confirmation_triggered, user_cancelled, raw_json
                    ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        batch_id,
                        time.time(),
                        normalized["ts"],
                        normalized["text"],
                        normalized["text_hash"],
                        normalized["active_application"],
                        int(normalized["has_selection"]),
                        normalized["selected_length"],
                        int(normalized["has_recent_text"]),
                        normalized["recent_text_length"],
                        normalized["shortcut_count"],
                        normalized["intent_type"],
                        normalized["intent_name"],
                        normalized["intent_key"],
                        normalized["intent_source"],
                        normalized["intent_confidence"],
                        int(normalized["intent_cache_hit"]),
                        normalized["status"],
                        normalized["detail"],
                        normalized["review_label"],
                        normalized["review_note"],
                        json.dumps(normalized["corrected_intent"], ensure_ascii=False),
                        normalized["operation_risk"],
                        _nullable_bool_int(normalized["confirmation_triggered"]),
                        _nullable_bool_int(normalized["user_cancelled"]),
                        json.dumps(sample, ensure_ascii=False),
                    ),
                )
                count += 1
        return count

    def list_samples(self, query: SampleQuery | None = None) -> list[dict]:
        query = query or SampleQuery()
        clauses = []
        params: list[object] = []
        if query.review_label is not None:
            clauses.append("review_label = ?")
            params.append(query.review_label)
        if query.intent_type:
            clauses.append("intent_type = ?")
            params.append(query.intent_type)
        if query.status:
            clauses.append("status = ?")
            params.append(query.status)
        if query.text:
            clauses.append("text = ?")
            params.append(query.text)
        where = " where " + " and ".join(clauses) if clauses else ""
        params.extend([max(1, min(query.limit, 1000)), max(0, query.offset)])
        sql = f"select * from samples{where} order by id desc limit ? offset ?"
        with self._managed_connection() as conn:
            return [_row_to_dict(row) for row in conn.execute(sql, params).fetchall()]

    def list_corrected_samples(self, *, limit: int = 1000, offset: int = 0) -> list[dict]:
        with self._managed_connection() as conn:
            rows = conn.execute(
                """
                select * from samples
                where text != ''
                  and corrected_intent_json != '{}'
                  and corrected_intent_json != ''
                order by id desc
                limit ? offset ?
                """,
                (max(1, min(limit, 1000)), max(0, offset)),
            ).fetchall()
            return [_row_to_dict(row) for row in rows]

    def list_phrase_groups(self, *, limit: int = 30, offset: int = 0) -> list[dict]:
        with self._managed_connection() as conn:
            rows = conn.execute(
                """
                select
                    text,
                    count(*) as sample_count,
                    sum(case when review_label != '' then 1 else 0 end) as reviewed_count,
                    sum(
                        case
                            when corrected_intent_json != '{}'
                             and corrected_intent_json != ''
                            then 1
                            else 0
                        end
                    ) as corrected_count,
                    max(created_at) as last_seen_at
                from samples
                where text != ''
                group by text
                order by sample_count desc, last_seen_at desc, text asc
                limit ? offset ?
                """,
                (max(1, min(limit, 1000)), max(0, offset)),
            ).fetchall()
            groups = []
            for row in rows:
                text = str(row["text"])
                groups.append({
                    "text": text,
                    "count": int(row["sample_count"] or 0),
                    "reviewed_count": int(row["reviewed_count"] or 0),
                    "corrected_count": int(row["corrected_count"] or 0),
                    "last_seen_at": float(row["last_seen_at"] or 0),
                    "by_intent": _count_rows_for_text(conn, "intent_type", text),
                    "by_review": _count_rows_for_text(conn, "review_label", text),
                })
            return groups

    def review_sample(
        self,
        sample_id: int,
        *,
        label: str,
        note: str = "",
        corrected_intent: dict | None = None,
    ) -> dict:
        if label not in REVIEW_LABELS:
            raise ValueError(f"unsupported review label: {label}")
        with self._managed_connection() as conn:
            if corrected_intent is None:
                cursor = conn.execute(
                    "update samples set review_label = ?, review_note = ? where id = ?",
                    (label, note, sample_id),
                )
            else:
                cursor = conn.execute(
                    """
                    update samples
                    set review_label = ?, review_note = ?, corrected_intent_json = ?
                    where id = ?
                    """,
                    (label, note, json.dumps(corrected_intent, ensure_ascii=False), sample_id),
                )
            if cursor.rowcount == 0:
                raise KeyError(f"sample not found: {sample_id}")
            row = conn.execute("select * from samples where id = ?", (sample_id,)).fetchone()
            return _row_to_dict(row)

    def review_matching_text(
        self,
        text: str,
        *,
        label: str,
        note: str = "",
        corrected_intent: dict | None = None,
    ) -> dict:
        if label not in REVIEW_LABELS:
            raise ValueError(f"unsupported review label: {label}")
        clean_text = str(text or "")
        if not clean_text:
            raise ValueError("text is required")
        with self._managed_connection() as conn:
            if corrected_intent is None:
                cursor = conn.execute(
                    "update samples set review_label = ?, review_note = ? where text = ?",
                    (label, note, clean_text),
                )
            else:
                cursor = conn.execute(
                    """
                    update samples
                    set review_label = ?, review_note = ?, corrected_intent_json = ?
                    where text = ?
                    """,
                    (label, note, json.dumps(corrected_intent, ensure_ascii=False), clean_text),
                )
            return {"text": clean_text, "updated": int(cursor.rowcount)}

    def stats(self) -> dict:
        with self._managed_connection() as conn:
            total = conn.execute("select count(*) from samples").fetchone()[0]
            by_intent = _count_rows(conn, "intent_type")
            by_source = _count_rows(conn, "intent_source")
            by_status = _count_rows(conn, "status")
            by_review = _count_rows(conn, "review_label")
            by_operation_risk = _count_rows(conn, "operation_risk")
            confirmation_triggered_total = _count_where(conn, "confirmation_triggered = 1")
            user_cancelled_total = _count_where(conn, "user_cancelled = 1")
            high_risk_total = _count_where(conn, "operation_risk = 'high'")
            unsafe_should_confirm_total = _count_where(conn, "review_label = 'unsafe_should_confirm'")
            corrected_rows = conn.execute(
                """
                select corrected_intent_json from samples
                where corrected_intent_json != '{}'
                  and corrected_intent_json != ''
                """
            ).fetchall()
            by_corrected_type: dict[str, int] = {}
            corrected_total = 0
            for row in corrected_rows:
                corrected = _parse_json_object(row[0])
                corrected_type = str(corrected.get("type") or "")
                if not corrected_type:
                    continue
                corrected_total += 1
                by_corrected_type[corrected_type] = by_corrected_type.get(corrected_type, 0) + 1
            top_phrases = [
                {"text": row[0], "count": row[1]}
                for row in conn.execute(
                    """
                    select text, count(*) as n from samples
                    where text != ''
                    group by text
                    order by n desc, text asc
                    limit 30
                    """
                ).fetchall()
            ]
        return {
            "total": total,
            "by_intent": by_intent,
            "by_source": by_source,
            "by_status": by_status,
            "by_review": by_review,
            "by_operation_risk": by_operation_risk,
            "confirmation_triggered_total": confirmation_triggered_total,
            "user_cancelled_total": user_cancelled_total,
            "high_risk_total": high_risk_total,
            "unsafe_should_confirm_total": unsafe_should_confirm_total,
            "corrected_total": corrected_total,
            "by_corrected_type": by_corrected_type,
            "top_phrases": top_phrases,
        }

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        return conn

    @contextmanager
    def _managed_connection(self):
        conn = self._connect()
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def _init_schema(self) -> None:
        with self._managed_connection() as conn:
            conn.execute(
                """
                create table if not exists batches(
                    id integer primary key autoincrement,
                    created_at real not null,
                    source text not null default '',
                    meta_json text not null default '{}'
                )
                """
            )
            conn.execute(
                """
                create table if not exists samples(
                    id integer primary key autoincrement,
                    batch_id integer not null,
                    created_at real not null,
                    ts real not null default 0,
                    text text not null default '',
                    text_hash text not null default '',
                    active_application text not null default '',
                    has_selection integer not null default 0,
                    selected_length integer not null default 0,
                    has_recent_text integer not null default 0,
                    recent_text_length integer not null default 0,
                    shortcut_count integer not null default 0,
                    intent_type text not null default '',
                    intent_name text not null default '',
                    intent_key text not null default '',
                    intent_source text not null default '',
                    intent_confidence text not null default '',
                    intent_cache_hit integer not null default 0,
                    status text not null default '',
                    detail text not null default '',
                    review_label text not null default '',
                    review_note text not null default '',
                    corrected_intent_json text not null default '{}',
                    operation_risk text not null default '',
                    confirmation_triggered integer,
                    user_cancelled integer,
                    raw_json text not null default '{}',
                    foreign key(batch_id) references batches(id)
                )
                """
            )
            _ensure_column(conn, "samples", "corrected_intent_json", "text not null default '{}'")
            _ensure_column(conn, "samples", "operation_risk", "text not null default ''")
            _ensure_column(conn, "samples", "confirmation_triggered", "integer")
            _ensure_column(conn, "samples", "user_cancelled", "integer")
            conn.execute("create index if not exists idx_samples_intent on samples(intent_type)")
            conn.execute("create index if not exists idx_samples_review on samples(review_label)")
            conn.execute("create index if not exists idx_samples_operation_risk on samples(operation_risk)")
            conn.execute("create index if not exists idx_samples_hash on samples(text_hash)")

    def close(self) -> None:
        """Compatibility hook for tests and future pooled stores."""
        return None


def parse_jsonl(text: str) -> list[dict]:
    rows = []
    for line in str(text or "").splitlines():
        line = line.strip()
        if not line:
            continue
        parsed = json.loads(line)
        if not isinstance(parsed, dict):
            raise ValueError("each JSONL row must be an object")
        rows.append(parsed)
    return rows


def _normalize_sample(sample: dict) -> dict:
    return {
        "ts": float(sample.get("ts") or 0),
        "text": str(sample.get("text") or ""),
        "text_hash": str(sample.get("text_hash") or ""),
        "active_application": str(sample.get("active_application") or ""),
        "has_selection": bool(sample.get("has_selection")),
        "selected_length": int(sample.get("selected_length") or 0),
        "has_recent_text": bool(sample.get("has_recent_text")),
        "recent_text_length": int(sample.get("recent_text_length") or 0),
        "shortcut_count": int(sample.get("shortcut_count") or 0),
        "intent_type": str(sample.get("intent_type") or ""),
        "intent_name": str(sample.get("intent_name") or ""),
        "intent_key": str(sample.get("intent_key") or ""),
        "intent_source": str(sample.get("intent_source") or ""),
        "intent_confidence": str(sample.get("intent_confidence") or ""),
        "intent_cache_hit": bool(sample.get("intent_cache_hit")),
        "status": str(sample.get("status") or ""),
        "detail": str(sample.get("detail") or ""),
        "review_label": str(sample.get("review_label") or ""),
        "review_note": str(sample.get("review_note") or ""),
        "corrected_intent": _normalize_corrected_intent(sample.get("corrected_intent")),
        "operation_risk": str(sample.get("operation_risk") or ""),
        "confirmation_triggered": _normalize_optional_bool(sample.get("confirmation_triggered")),
        "user_cancelled": _normalize_optional_bool(sample.get("user_cancelled")),
    }


def _row_to_dict(row: sqlite3.Row) -> dict:
    out = {
        key: bool(row[key]) if key in {"has_selection", "has_recent_text", "intent_cache_hit"} else row[key]
        for key in row.keys()
        if key != "corrected_intent_json"
    }
    out["corrected_intent"] = _parse_json_object(row["corrected_intent_json"])
    return out


def _count_rows(conn: sqlite3.Connection, column: str) -> dict:
    rows = conn.execute(
        f"select {column}, count(*) from samples group by {column} order by count(*) desc"
    ).fetchall()
    return {str(row[0]): int(row[1]) for row in rows}


def _count_where(conn: sqlite3.Connection, where: str) -> int:
    return int(conn.execute(f"select count(*) from samples where {where}").fetchone()[0])


def _count_rows_for_text(conn: sqlite3.Connection, column: str, text: str) -> dict:
    rows = conn.execute(
        f"""
        select {column}, count(*) from samples
        where text = ?
        group by {column}
        order by count(*) desc, {column} asc
        """,
        (text,),
    ).fetchall()
    return {str(row[0]): int(row[1]) for row in rows}


def _normalize_corrected_intent(value) -> dict:
    if isinstance(value, dict):
        return value
    return {}


def _normalize_optional_bool(value) -> bool | None:
    if value is None:
        return None
    return bool(value)


def _nullable_bool_int(value: bool | None) -> int | None:
    if value is None:
        return None
    return int(value)


def _parse_json_object(text: str) -> dict:
    try:
        parsed = json.loads(text or "{}")
    except Exception:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _ensure_column(conn: sqlite3.Connection, table: str, column: str, definition: str) -> None:
    columns = {row[1] for row in conn.execute(f"pragma table_info({table})").fetchall()}
    if column not in columns:
        conn.execute(f"alter table {table} add column {column} {definition}")
