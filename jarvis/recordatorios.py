"""Recordatorios: "recuérdame en 20 minutos que…", "avísame mañana a las 8 de…".

Se guardan en la base de datos (sobreviven a reinicios). El bot de Telegram los vigila y, a su hora,
manda una nota de voz. También quedan apuntados en el cerebro de Obsidian.
"""

from __future__ import annotations

import logging
import os
import sqlite3
import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from livekit.agents import RunContext, function_tool

log = logging.getLogger("jarvis.recordatorios")
TZ = ZoneInfo("Europe/Madrid")


def _db() -> sqlite3.Connection:
    db = sqlite3.connect(os.getenv("JARVIS_MEMORY_PATH", "jarvis_memoria.db"), timeout=10)
    db.execute("CREATE TABLE IF NOT EXISTS recordatorios (id INTEGER PRIMARY KEY AUTOINCREMENT, texto TEXT NOT NULL,"
               " cuando REAL NOT NULL, estado TEXT NOT NULL DEFAULT 'pendiente', creado REAL)")
    return db


def cuando_desde(fecha_hora: str = "", en_minutos: float = 0, ahora: datetime | None = None) -> datetime:
    """La hora del aviso (Madrid). `fecha_hora` = "AAAA-MM-DD HH:MM"; o `en_minutos` desde ahora."""
    ahora = ahora or datetime.now(TZ)
    if en_minutos and en_minutos > 0:
        return ahora + timedelta(minutes=float(en_minutos))
    texto = (fecha_hora or "").strip().replace("T", " ")
    for formato in ("%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S", "%d/%m/%Y %H:%M"):
        try:
            cuando = datetime.strptime(texto, formato).replace(tzinfo=TZ)
            break
        except ValueError:
            continue
    else:
        raise ValueError("no entiendo la hora; usa AAAA-MM-DD HH:MM o en_minutos")
    if cuando <= ahora:
        raise ValueError(f"esa hora ({cuando:%d/%m %H:%M}) ya ha pasado")
    if cuando - ahora > timedelta(days=366):
        raise ValueError("como mucho, recordatorios a un año vista")
    return cuando


def crear(texto: str, cuando: datetime) -> int:
    db = _db()
    with db:
        cur = db.execute("INSERT INTO recordatorios (texto, cuando, creado) VALUES (?, ?, ?)",
                         (texto.strip()[:500], cuando.timestamp(), time.time()))
    db.close()
    return cur.lastrowid


def por_avisar(ahora: float | None = None) -> list[tuple[int, str]]:
    """Los que ya tocan (sin marcarlos: se marcan con `marcar_avisado` DESPUÉS de avisar de verdad)."""
    ahora = ahora or time.time()
    db = _db()
    filas = db.execute("SELECT id, texto FROM recordatorios WHERE estado='pendiente' AND cuando <= ? ORDER BY cuando",
                       (ahora,)).fetchall()
    db.close()
    return filas


def marcar_avisado(rid: int) -> None:
    db = _db()
    with db:
        db.execute("UPDATE recordatorios SET estado='avisado' WHERE id=?", (rid,))
    db.close()


def vencidos(ahora: float | None = None) -> list[tuple[int, str]]:
    """Los que ya tocan, y los marca como avisados (cada uno se avisa una sola vez)."""
    filas = por_avisar(ahora)
    for rid, _t in filas:
        marcar_avisado(rid)
    return filas


def devolver(rid: int) -> None:
    """Si no se pudo avisar (Telegram caído), vuelve a pendiente para reintentarlo."""
    db = _db()
    with db:
        db.execute("UPDATE recordatorios SET estado='pendiente' WHERE id=?", (rid,))
    db.close()


def pendientes() -> list[tuple[int, str, datetime]]:
    db = _db()
    filas = db.execute("SELECT id, texto, cuando FROM recordatorios WHERE estado='pendiente' ORDER BY cuando").fetchall()
    db.close()
    return [(i, t, datetime.fromtimestamp(c, TZ)) for i, t, c in filas]


def borrar(rid: int) -> bool:
    db = _db()
    with db:
        n = db.execute("UPDATE recordatorios SET estado='borrado' WHERE id=? AND estado='pendiente'", (rid,)).rowcount
    db.close()
    return n > 0


def bonito(cuando: datetime, ahora: datetime | None = None) -> str:
    ahora = ahora or datetime.now(TZ)
    dias = (cuando.date() - ahora.date()).days
    dia = {0: "hoy", 1: "mañana", 2: "pasado mañana"}.get(dias, f"el {cuando:%d/%m}")
    return f"{dia} a las {cuando:%H:%M}"


class Recordatorios:
    """Mezcla para el agente: recordatorios con aviso por Telegram."""

    @function_tool
    async def programar_recordatorio(self, context: RunContext, texto: str, fecha_hora: str = "",
                                     en_minutos: float = 0) -> str:
        """Programa un aviso: a esa hora JARVIS le manda al usuario una nota de voz por Telegram.
        Úsalo para "recuérdame…", "avísame…", "que no se me olvide…". Usa la fecha y hora actuales que te doy.

        Args:
            texto: qué hay que recordar, p. ej. "llamar al dentista".
            fecha_hora: cuándo, en formato "AAAA-MM-DD HH:MM" (hora de España). Vacío si usas en_minutos.
            en_minutos: dentro de cuántos minutos (p. ej. 20, o 120 para dos horas). 0 si usas fecha_hora.
        """
        try:
            cuando = cuando_desde(fecha_hora, en_minutos)
        except ValueError as e:
            return f"No puedo programarlo: {e}."
        rid = crear(texto, cuando)
        try:
            from .core import boveda_activa

            b = boveda_activa()
            if b:
                b.recordar(f"⏰ Recordatorio para {cuando:%d/%m/%Y %H:%M}: {texto}", sobre="Recordatorios")
        except Exception:
            log.exception("No pude apuntar el recordatorio en Obsidian")
        return f"Hecho (#{rid}): te lo recordaré {bonito(cuando)} con una nota de voz en Telegram."

    @function_tool
    async def ver_recordatorios(self, context: RunContext) -> str:
        """Lista los recordatorios pendientes."""
        lista = pendientes()
        if not lista:
            return "No hay recordatorios pendientes."
        return "\n".join(f"#{i}: {bonito(c)} — {t}" for i, t, c in lista)

    @function_tool
    async def borrar_recordatorio(self, context: RunContext, numero: int) -> str:
        """Cancela un recordatorio pendiente (mira antes su número con ver_recordatorios).

        Args:
            numero: el número del recordatorio, p. ej. 3.
        """
        return "Cancelado." if borrar(int(numero)) else f"No hay ningún recordatorio pendiente con el número {numero}."
