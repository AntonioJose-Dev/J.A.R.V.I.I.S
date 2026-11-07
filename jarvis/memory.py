"""Memoria a largo plazo de JARVIS.

Primera versión sobre SQLite con búsqueda de texto completo (FTS5), para que
funcione sin instalar nada. La interfaz (`remember`, `recall`, `recent`) es la
misma que tendrá la versión con PostgreSQL + pgvector y búsqueda semántica.
"""

from __future__ import annotations

import json
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
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS contacts (
                key TEXT PRIMARY KEY,          -- nombre normalizado (minúsculas, sin tildes)
                name TEXT NOT NULL,
                number TEXT NOT NULL           -- formato internacional E.164
            );
            CREATE TABLE IF NOT EXISTS calls (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                number TEXT NOT NULL,
                message TEXT NOT NULL,
                status TEXT NOT NULL,          -- pendiente | marcando | cancelada | caducada | hecha | fallida
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS actions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                kind TEXT NOT NULL,            -- p. ej. "pc"
                payload TEXT NOT NULL,         -- JSON con los datos de la acción
                description TEXT NOT NULL,     -- lo que se le enseña al dueño para confirmar
                status TEXT NOT NULL,          -- pendiente | ejecutando | hecha | cancelada | caducada | fallida
                created_at TEXT NOT NULL
            );
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

    def get_setting(self, key: str, default: str | None = None) -> str | None:
        row = self._db.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
        return row[0] if row else default

    def set_setting(self, key: str, value: str) -> None:
        self._db.execute(
            "INSERT INTO settings (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )
        self._db.commit()

    # --- Agenda -------------------------------------------------------------------

    def save_contact(self, key: str, name: str, number: str) -> None:
        self._db.execute(
            "INSERT INTO contacts (key, name, number) VALUES (?, ?, ?) "
            "ON CONFLICT(key) DO UPDATE SET name = excluded.name, number = excluded.number",
            (key, name, number),
        )
        self._db.commit()

    def contacts(self) -> list[tuple[str, str, str]]:
        """(key, nombre, número) de todos los contactos."""
        return self._db.execute("SELECT key, name, number FROM contacts ORDER BY name").fetchall()

    # --- Llamadas pendientes de confirmar -------------------------------------------

    def create_call(self, name: str, number: str, message: str) -> int:
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        cur = self._db.execute(
            "INSERT INTO calls (name, number, message, status, created_at) VALUES (?, ?, ?, 'pendiente', ?)",
            (name, number, message, now),
        )
        self._db.commit()
        return cur.lastrowid

    def get_call(self, call_id: int) -> dict | None:
        row = self._db.execute(
            "SELECT id, name, number, message, status, created_at FROM calls WHERE id = ?", (call_id,)
        ).fetchone()
        if not row:
            return None
        return dict(zip(("id", "nombre", "numero", "mensaje", "estado", "creada"), row))

    def set_call_status(self, call_id: int, status: str, only_if: str | None = None) -> bool:
        """Cambia el estado; con `only_if`, solo si estaba en ese estado (evita dobles pulsaciones)."""
        if only_if:
            cur = self._db.execute(
                "UPDATE calls SET status = ? WHERE id = ? AND status = ?", (status, call_id, only_if)
            )
        else:
            cur = self._db.execute("UPDATE calls SET status = ? WHERE id = ?", (status, call_id))
        self._db.commit()
        return cur.rowcount > 0

    # --- Acciones que necesitan confirmación (PC, móvil...) ------------------------------

    def create_action(self, kind: str, payload: dict, description: str) -> int:
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        cur = self._db.execute(
            "INSERT INTO actions (kind, payload, description, status, created_at) VALUES (?, ?, ?, 'pendiente', ?)",
            (kind, json.dumps(payload, ensure_ascii=False), description, now),
        )
        self._db.commit()
        return cur.lastrowid

    def get_action(self, action_id: int) -> dict | None:
        row = self._db.execute(
            "SELECT id, kind, payload, description, status, created_at FROM actions WHERE id = ?", (action_id,)
        ).fetchone()
        if not row:
            return None
        return {"id": row[0], "tipo": row[1], "datos": json.loads(row[2]), "descripcion": row[3],
                "estado": row[4], "creada": row[5]}

    def set_action_status(self, action_id: int, status: str, only_if: str | None = None) -> bool:
        sql, args = "UPDATE actions SET status = ? WHERE id = ?", [status, action_id]
        if only_if:
            sql, args = sql + " AND status = ?", args + [only_if]
        cur = self._db.execute(sql, args)
        self._db.commit()
        return cur.rowcount > 0

    def close(self) -> None:
        self._db.close()
