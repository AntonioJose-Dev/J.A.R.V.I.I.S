"""Mandar cosas al Telegram del dueño desde cualquier parte de JARVIS (bot, voz del PC, llamadas).

Usa la API HTTP de Telegram directamente, así funciona aunque el bot esté en otro proceso.
Solo escribe al chat del dueño (el primer ID de TELEGRAM_ALLOWED_IDS).
"""

from __future__ import annotations

import os

import httpx

MAX_ARCHIVO = 49 * 1024 * 1024  # límite de los bots de Telegram: 50 MB


def chat_del_dueno() -> int | None:
    from .telegram_bot import parse_ids  # import tardío: evita ciclo

    ids = sorted(parse_ids(os.getenv("TELEGRAM_ALLOWED_IDS")))
    return ids[0] if ids else None


def _url(metodo: str) -> str:
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    if not token:
        raise RuntimeError("Falta TELEGRAM_BOT_TOKEN")
    return f"https://api.telegram.org/bot{token}/{metodo}"


def telegram(metodo: str, **datos) -> dict:
    r = httpx.post(_url(metodo), json=datos, timeout=30)
    if r.status_code != 200:
        raise RuntimeError(f"Telegram {metodo}: {r.status_code}")
    return r.json()


def enviar_archivo(nombre: str, contenido: bytes, caption: str = "", como_foto: bool = False) -> None:
    chat = chat_del_dueno()
    if chat is None:
        raise RuntimeError("Falta TELEGRAM_ALLOWED_IDS")
    if len(contenido) > MAX_ARCHIVO:
        raise ValueError("El archivo pasa de 50 MB, Telegram no lo admite")
    metodo, campo = ("sendPhoto", "photo") if como_foto else ("sendDocument", "document")
    r = httpx.post(_url(metodo), data={"chat_id": chat, "caption": caption[:1000]},
                   files={campo: (nombre, contenido)}, timeout=120)
    if r.status_code != 200:
        raise RuntimeError(f"Telegram {metodo}: {r.status_code}")


def pedir_confirmacion(texto: str, prefijo: str, ident: int, si: str = "✅ Sí", no: str = "❌ No") -> None:
    """Mensaje con dos botones. Al pulsar llega al bot `<prefijo>:<ident>:si` o `<prefijo>:<ident>:no`."""
    chat = chat_del_dueno()
    if chat is None:
        raise RuntimeError("Falta TELEGRAM_ALLOWED_IDS")
    telegram("sendMessage", chat_id=chat, text=texto, reply_markup={"inline_keyboard": [[
        {"text": si, "callback_data": f"{prefijo}:{ident}:si"},
        {"text": no, "callback_data": f"{prefijo}:{ident}:no"},
    ]]})
