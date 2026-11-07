"""JARVIS por Telegram: texto y notas de voz, con el mismo cerebro y memoria que el agente de voz.

Uso:
    python -m jarvis.telegram_bot

Variables en .env:
    TELEGRAM_BOT_TOKEN    token que te da @BotFather
    TELEGRAM_ALLOWED_IDS  IDs numéricos de Telegram que pueden hablar con JARVIS, separados por comas.
                          Escríbele /id al bot para saber el tuyo.
"""

from __future__ import annotations

import io
import logging
import os
import sys
import time

import aiohttp
import av
import httpx
import numpy as np
from livekit.agents import llm
from telegram import Update
from telegram.constants import ChatAction
from telegram.ext import Application, ContextTypes, MessageHandler, filters

from .config import elegir_plan
from .core import KEYTERMS, Jarvis, crear_cerebro, crear_voz, responder
from .memory import MemoryStore

log = logging.getLogger("jarvis.telegram")
HISTORIAL_MAX = 30  # mensajes recientes que JARVIS recuerda de cada chat
DEEPGRAM_URL = "https://api.deepgram.com/v1/listen"


# --- Decisiones (sin red, probadas en tests/test_telegram.py) ---------------------------

def parse_ids(valor: str | None) -> frozenset[int]:
    ids = set()
    for parte in (valor or "").replace(";", ",").split(","):
        parte = parte.strip()
        if parte.lstrip("-").isdigit():
            ids.add(int(parte))
        elif parte:
            log.warning("TELEGRAM_ALLOWED_IDS: ignoro %r (no es un número)", parte)
    return frozenset(ids)


def tipo_de_mensaje(texto: str | None, tiene_voz: bool) -> str | None:
    if tiene_voz:
        return "voz"
    if not texto or not texto.strip():
        return None
    comando = texto.strip().split()[0].split("@")[0].lower()
    if comando == "/id":
        return "id"
    if comando in ("/olvida", "/reset"):
        return "olvida"
    if comando == "/start":
        return "start"
    if comando == "/voz":
        return "alternar_voz"
    return "texto"


def que_enviar(me_mando_audio: bool, siempre_voz: bool) -> tuple[bool, bool]:
    """(texto, voz): a un audio se contesta solo con audio; a un texto, con texto (+ voz si /voz)."""
    if me_mando_audio:
        return False, True
    return True, siempre_voz


def decidir(user_id: int | None, permitidos: frozenset[int], tipo: str | None) -> str:
    """Qué hacer con un mensaje: 'id', 'start', 'olvida', 'alternar_voz', 'texto', 'voz' o 'ignorar'."""
    if tipo is None or user_id is None:
        return "ignorar"
    if tipo == "id":
        return "id"  # cualquiera puede saber su propio ID; no da acceso a nada
    if user_id not in permitidos:
        return "ignorar"
    return tipo


# --- Audio ---------------------------------------------------------------------------

def pcm_a_ogg_opus(pcm: bytes, sample_rate: int, canales: int) -> bytes:
    """Convierte audio PCM 16 bits a OGG/Opus, el formato de las notas de voz de Telegram."""
    buf = io.BytesIO()
    with av.open(buf, "w", format="ogg") as out:
        stream = out.add_stream("libopus", rate=48000)
        stream.layout = "mono"
        layout = "mono" if canales == 1 else "stereo"
        frame = av.AudioFrame.from_ndarray(
            np.frombuffer(pcm, dtype=np.int16).reshape(1, -1), format="s16", layout=layout
        )
        frame.sample_rate = sample_rate
        resampler = av.AudioResampler(format="s16", layout="mono", rate=48000)
        for f in resampler.resample(frame) + resampler.resample(None):
            for packet in stream.encode(f):
                out.mux(packet)
        for packet in stream.encode(None):
            out.mux(packet)
    return buf.getvalue()


async def transcribir(audio: bytes, mime: str, key: str) -> str:
    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.post(
            DEEPGRAM_URL,
            params={"model": "nova-3", "language": "es", "smart_format": "true", "keyterm": KEYTERMS},
            headers={"Authorization": f"Token {key}", "Content-Type": mime},
            content=audio,
        )
    r.raise_for_status()
    return r.json()["results"]["channels"][0]["alternatives"][0].get("transcript", "").strip()


# --- Bot -----------------------------------------------------------------------------

class JarvisTelegram:
    def __init__(self) -> None:
        self.plan = elegir_plan(os.environ)
        self.cerebro = crear_cerebro(self.plan)
        self.memory = MemoryStore(os.getenv("JARVIS_MEMORY_PATH", "jarvis_memoria.db"))
        self.permitidos = parse_ids(os.getenv("TELEGRAM_ALLOWED_IDS"))
        self.deepgram_key = os.getenv("DEEPGRAM_API_KEY", "").strip()
        self.historiales: dict[int, llm.ChatContext] = {}
        self.http: aiohttp.ClientSession | None = None

    async def iniciar(self, app: Application) -> None:
        self.http = aiohttp.ClientSession()
        me = await app.bot.get_me()
        log.info("Bot @%s listo (%s). Usuarios permitidos: %d", me.username, self.plan.describir(), len(self.permitidos))
        if not self.permitidos:
            log.warning("TELEGRAM_ALLOWED_IDS está vacío: escribe /id al bot y pon tu número en .env")

    async def cerrar(self, app: Application) -> None:
        if self.http:
            await self.http.close()
        self.memory.close()

    def siempre_voz(self, chat_id: int) -> bool:
        return self.memory.get_setting(f"telegram.siempre_voz.{chat_id}", "0") == "1"

    async def pensar(self, chat_id: int, texto: str) -> str:
        historial = self.historiales.setdefault(chat_id, llm.ChatContext())
        t0 = time.perf_counter()
        respuesta = await responder(self.cerebro, Jarvis(self.memory), historial, texto)
        historial.truncate(max_items=HISTORIAL_MAX)
        log.info("Respuesta en %.2f s", time.perf_counter() - t0)
        return respuesta

    async def hablar(self, texto: str) -> bytes:
        voz = crear_voz(self.plan, self.http)
        frames = [ev.frame async for ev in voz.synthesize(texto)]
        pcm = b"".join(bytes(f.data) for f in frames)
        return pcm_a_ogg_opus(pcm, frames[0].sample_rate, frames[0].num_channels)

    async def manejar(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        msg, user = update.effective_message, update.effective_user
        if msg is None:
            return
        tipo = tipo_de_mensaje(msg.text, msg.voice is not None)
        accion = decidir(user.id if user else None, self.permitidos, tipo)

        if accion == "ignorar":
            if tipo is not None:
                log.warning("Mensaje ignorado de un usuario no permitido: id=%s @%s",
                            user.id if user else "?", user.username if user else "?")
            return
        if accion == "id":
            await msg.reply_text(f"Tu ID de Telegram es {user.id}")
            return
        if accion == "start":
            await msg.reply_text("A su servicio, señor. Escríbame o mándeme una nota de voz.")
            return
        if accion == "olvida":
            self.historiales.pop(msg.chat_id, None)
            await msg.reply_text("Conversación reiniciada. Lo que me pidió recordar sigue guardado.")
            return
        if accion == "alternar_voz":
            nuevo = not self.siempre_voz(msg.chat_id)
            self.memory.set_setting(f"telegram.siempre_voz.{msg.chat_id}", "1" if nuevo else "0")
            await msg.reply_text(
                "A partir de ahora a sus mensajes de texto le contestaré también con una nota de voz. /voz para desactivarlo."
                if nuevo else
                "Entendido: solo le contestaré con voz cuando usted me mande un audio. /voz para cambiarlo."
            )
            return

        await context.bot.send_chat_action(msg.chat_id, ChatAction.TYPING)
        try:
            if accion == "texto":
                respuesta = await self.pensar(msg.chat_id, msg.text)
            else:
                archivo = await context.bot.get_file(msg.voice.file_id)
                audio = bytes(await archivo.download_as_bytearray())
                texto = await transcribir(audio, msg.voice.mime_type or "audio/ogg", self.deepgram_key)
                if not texto:
                    await msg.reply_text("No le he entendido, señor. ¿Puede repetirlo?")
                    return
                log.info("Nota de voz transcrita: %s", texto)
                respuesta = await self.pensar(msg.chat_id, texto)

            con_texto, con_voz = que_enviar(accion == "voz", self.siempre_voz(msg.chat_id))
            if con_texto:
                await msg.reply_text(respuesta)
            if con_voz:
                await context.bot.send_chat_action(msg.chat_id, ChatAction.RECORD_VOICE)
                try:
                    await msg.reply_voice(voice=await self.hablar(respuesta))
                except Exception:
                    log.exception("No pude generar la nota de voz")
                    if not con_texto:  # que la respuesta no se pierda
                        await msg.reply_text(respuesta)
        except Exception:
            log.exception("Error atendiendo un mensaje")
            await msg.reply_text("He tenido un problema técnico, señor. Inténtelo de nuevo en un momento.")


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)  # sus logs incluyen el token en la URL
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    if not token:
        sys.exit("ERROR: falta TELEGRAM_BOT_TOKEN en .env (créalo con @BotFather en Telegram).")
    try:
        bot = JarvisTelegram()
    except ValueError as e:
        sys.exit(f"ERROR: {e}")
    print(f"JARVIS en Telegram: {bot.plan.describir()}. Ctrl+C para parar.")
    app = Application.builder().token(token).post_init(bot.iniciar).post_shutdown(bot.cerrar).build()
    app.add_handler(MessageHandler(filters.ALL, bot.manejar))
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
