"""Memoria a largo plazo de JARVIS.

Primera versión sobre SQLite con búsqueda de texto completo (FTS5), para que
funcione sin instalar nada. La interfaz (`remember`, `recall`, `recent`) es la
misma que tendrá la versión con PostgreSQL + pgvector y búsqueda semántica.
"""

from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


@dataclass(frozen=True)
class Memory:
    id: int
    text: str
    category: str
    created_at: str


class MemoryStore:
    def __init__(self, path: str | Path = ":memory:") -> None:
        self._db = sqlite3.connect(str(path), check_same_thread=False)
        self._db.executescript(
            """
            CREATE TABLE IF NOT EXISTS memories (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                text TEXT NOT NULL,
                category TEXT NOT NULL DEFAULT 'general',
                created_at TEXT NOT NULL
            );
            CREATE VIRTUAL TABLE IF NOT EXISTS memories_fts
                USING fts5(text, content='memories', content_rowid='id');
            CREATE TRIGGER IF NOT EXISTS memories_ai AFTER INSERT ON memories BEGIN
                INSERT INTO memories_fts(rowid, text) VALUES (new.id, new.text);
            END;
            CREATE TRIGGER IF NOT EXISTS memories_ad AFTER DELETE ON memories BEGIN
                INSERT INTO memories_fts(memories_fts, rowid, text)
                VALUES ('delete', old.id, old.text);
            END;
            """
        )
        self._db.commit()

    def remember(self, text: str, category: str = "general") -> Memory:
        text = text.strip()
        if not text:
            raise ValueError("No se puede guardar un recuerdo vacío")
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        cur = self._db.execute(
            "INSERT INTO memories (text, category, created_at) VALUES (?, ?, ?)",
            (text, category, now),
        )
        self._db.commit()
        return Memory(cur.lastrowid, text, category, now)

    def recall(self, query: str, limit: int = 5) -> list[Memory]:
        words = re.findall(r"\w+", query.lower())
        if not words:
            return []
        # OR entre palabras con prefijo: "madre cumple" encuentra "cumpleaños de mi madre"
        match = " OR ".join(f'"{w}"*' for w in words)
        rows = self._db.execute(
            """
            SELECT m.id, m.text, m.category, m.created_at
            FROM memories_fts f JOIN memories m ON m.id = f.rowid
            WHERE memories_fts MATCH ?
            ORDER BY bm25(memories_fts) LIMIT ?
            """,
            (match, limit),
        ).fetchall()
        return [Memory(*r) for r in rows]

    def recent(self, limit: int = 10) -> list[Memory]:
        rows = self._db.execute(
            "SELECT id, text, category, created_at FROM memories ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [Memory(*r) for r in rows]

    def forget(self, memory_id: int) -> bool:
        cur = self._db.execute("DELETE FROM memories WHERE id = ?", (memory_id,))
        self._db.commit()
        return cur.rowcount > 0

    def close(self) -> None:
        self._db.close()
