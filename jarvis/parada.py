"""«Jarvis, para»: parada de emergencia. Lo cancela TODO al momento.

- Lo que esté pensando o haciendo JARVIS en ese chat (la tarea se corta).
- Las confirmaciones pendientes (llamadas, WhatsApp, acciones del PC y del móvil): quedan canceladas.
- Los encargos al móvil que aún no se han hecho: cancelados (la app ya no los recibe).
- Las llamadas en curso: se cuelgan.
"""

from __future__ import annotations

import logging
import os
import re
import sqlite3

log = logging.getLogger("jarvis.parada")
_ORDEN = re.compile(r"^\W*(?:oye\W+)?(?:jarvis\W+)?(para|parate|detente|stop|basta|cancela(?:lo)? todo|"
                    r"para todo|alto|quieto)\W*(?:ya|jarvis)?\W*$")


def es_parada(texto: str) -> bool:
    import unicodedata

    t = unicodedata.normalize("NFKD", texto or "").encode("ascii", "ignore").decode().lower().strip()
    return bool(_ORDEN.match(t))


def cancelar_pendientes() -> dict:
    """Cancela confirmaciones y encargos pendientes en la base de datos. Devuelve cuántos de cada."""
    ruta = os.getenv("JARVIS_MEMORY_PATH", "jarvis_memoria.db")
    db = sqlite3.connect(ruta, timeout=10)
    r = {}
    with db:
        r["acciones"] = db.execute("UPDATE actions SET status='cancelada' WHERE status='pendiente'").rowcount
        r["llamadas"] = db.execute("UPDATE calls SET status='cancelada' WHERE status='pendiente'").rowcount
        try:
            r["movil"] = db.execute("UPDATE app_trabajos SET estado='cancelado', resultado='parado por el dueño' "
                                    "WHERE estado IN ('pendiente','entregado','recibido')").rowcount
        except sqlite3.OperationalError:
            r["movil"] = 0
    db.close()
    return r


async def colgar_llamadas() -> int:
    """Cuelga las llamadas en curso (cierra sus salas de LiveKit)."""
    if not all(os.getenv(k, "").strip() for k in ("LIVEKIT_URL", "LIVEKIT_API_KEY", "LIVEKIT_API_SECRET")):
        return 0
    from livekit import api

    n = 0
    lk = api.LiveKitAPI()
    try:
        salas = await lk.room.list_rooms(api.ListRoomsRequest())
        for sala in salas.rooms:
            if sala.name.startswith("llamada-"):
                await lk.room.delete_room(api.DeleteRoomRequest(room=sala.name))
                n += 1
    finally:
        await lk.aclose()
    return n


def resumen(r: dict, llamadas: int, tareas: int) -> str:
    partes = []
    if tareas:
        partes.append("he dejado lo que estaba haciendo")
    if llamadas:
        partes.append(f"he colgado {llamadas} llamada(s)")
    if r.get("acciones") or r.get("llamadas"):
        partes.append(f"he cancelado {r.get('acciones', 0) + r.get('llamadas', 0)} confirmación(es) pendiente(s)")
    if r.get("movil"):
        partes.append(f"he cancelado {r['movil']} encargo(s) al móvil")
    return "🛑 Parado, señor: " + (", ".join(partes) if partes else "no había nada en marcha") + "."
