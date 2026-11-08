"""Audios de WhatsApp con la voz de JARVIS: se generan en el PC (OGG/Opus) y la app del móvil los descarga."""

from __future__ import annotations

import asyncio
import hashlib
import os
import time
from pathlib import Path

CARPETA = Path(os.getenv("JARVIS_AUDIOS", "logs/audios"))
DURA = 30 * 60  # segundos que se guarda cada audio (luego se borra)


async def _sintetizar(texto: str) -> bytes:
    import aiohttp

    from .config import elegir_plan
    from .core import crear_voz, limpiar_para_voz
    from .telegram_bot import pcm_a_ogg_opus

    async with aiohttp.ClientSession() as http:
        voz = crear_voz(elegir_plan(os.environ), http)  # la misma voz de JARVIS (y su voz de reserva)
        frames = [ev.frame async for ev in voz.synthesize(limpiar_para_voz(texto))]
    if not frames:
        raise RuntimeError("la voz no generó audio")
    pcm = b"".join(bytes(f.data) for f in frames)
    return pcm_a_ogg_opus(pcm, frames[0].sample_rate, frames[0].num_channels)


def generar(texto: str) -> str:
    """Genera el audio y lo guarda; devuelve su huella SHA-256 (con ella la app lo pide y comprueba que está entero)."""
    ogg = asyncio.run(_sintetizar(texto))
    return guardar(ogg)


def guardar(ogg: bytes) -> str:
    huella = hashlib.sha256(ogg).hexdigest()
    CARPETA.mkdir(parents=True, exist_ok=True)
    (CARPETA / f"{huella}.ogg").write_bytes(ogg)
    limpiar()
    return huella


def leer(huella: str) -> bytes | None:
    if len(huella) != 64 or not all(c in "0123456789abcdef" for c in huella):
        return None  # nada de rutas raras: solo huellas
    p = CARPETA / f"{huella}.ogg"
    return p.read_bytes() if p.exists() else None


def limpiar() -> None:
    if not CARPETA.exists():
        return
    for p in CARPETA.glob("*.ogg"):
        if time.time() - p.stat().st_mtime > DURA:
            p.unlink(missing_ok=True)
