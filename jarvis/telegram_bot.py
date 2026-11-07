"""JARVIS por Telegram: texto y notas de voz, con el mismo cerebro y memoria que el agente de voz.

Uso:
    python -m jarvis.telegram_bot

Variables en .env:
    TELEGRAM_BOT_TOKEN    token que te da @BotFather
    TELEGRAM_ALLOWED_IDS  IDs numéricos de Telegram que pueden hablar con JARVIS, separados por comas.
                          Escríbele /id al bot para saber el tuyo.
"""

from __future__ import annotations

import asyncio
import io
import re
import logging
import os
import sys
import time

import aiohttp
import av
import httpx
import numpy as np
from livekit.agents import llm
from telegram import BotCommand, InlineKeyboardButton, InlineKeyboardMarkup, Update, WebAppInfo
from telegram.constants import ChatAction
from telegram.ext import Application, CallbackQueryHandler, ContextTypes, MessageHandler, filters

from . import movil, pc, telefono

from .config import elegir_plan
from .core import (
    KEYTERMS,
    Jarvis,
    crear_cerebro,
    crear_voz,
    describir_voz,
    limpiar_para_voz,
    responder,
)
from .memory import MemoryStore

log = logging.getLogger("jarvis.telegram")
HISTORIAL_MAX = 16  # mensajes recientes que JARVIS recuerda de cada chat
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
    if comando in ("/hablar", "/llamame"):
        return "hablar"
    return "texto"


def que_enviar(me_mando_audio: bool, siempre_voz: bool) -> tuple[bool, bool]:
    """(texto, voz): a un audio se contesta solo con audio; a un texto, con texto (+ voz si /voz)."""
    if me_mando_audio:
        return False, True
    return True, siempre_voz


# Formatos de botón (y nada más): "llamar:<id>", "cancelar:<id>", "pc:<id>:si|no", "acc:<id>:si|no"
_BOTON = re.compile(r"^(?:(llamar|cancelar):(\d{1,9})|(pc|acc):(\d{1,9}):(si|no))$")
TIPO_DE_PREFIJO = {"pc": "pc", "acc": "movil"}  # cada prefijo solo vale para su tipo de acción


def parse_boton(data: str | None) -> tuple[str, int, str | None] | None:
    """('llamar', 7, None) · ('acc', 7, 'si') · None si el botón no tiene un formato válido."""
    m = _BOTON.match(data or "")
    if not m:
        return None
    if m.group(1):
        return m.group(1), int(m.group(2)), None
    return m.group(3), int(m.group(4)), m.group(5)


def decidir_boton(user_id: int | None, permitidos: frozenset[int], data: str | None,
                  llamada: dict | None, caducada: bool) -> str:
    """Qué hacer al pulsar un botón de llamada: 'llamar', 'cancelar', 'caducada', 'ya_gestionada' o 'ignorar'."""
    boton = parse_boton(data)
    if user_id is None or user_id not in permitidos or llamada is None or not boton:
        return "ignorar"
    accion, call_id, respuesta = boton
    if accion not in ("llamar", "cancelar") or call_id != llamada["id"]:
        return "ignorar"
    if llamada["estado"] != "pendiente":
        return "ya_gestionada"
    if accion == "llamar" and caducada:
        return "caducada"
    return accion


def decidir_boton_accion(user_id: int | None, permitidos: frozenset[int], data: str | None,
                         accion: dict | None, caducada: bool) -> str:
    """Botón Sí/No de una acción delicada del PC (`pc:<id>:si|no`) o del móvil (`acc:<id>:si|no`):
    'ejecutar', 'cancelar', 'caducada', 'ya_gestionada' o 'ignorar'."""
    boton = parse_boton(data)
    if user_id is None or user_id not in permitidos or accion is None or not boton or boton[2] is None:
        return "ignorar"
    prefijo, accion_id, respuesta = boton
    if accion_id != accion["id"] or TIPO_DE_PREFIJO.get(prefijo) != accion["tipo"]:
        return "ignorar"
    if accion["estado"] != "pendiente":
        return "ya_gestionada"
    if respuesta == "no":
        return "cancelar"
    return "caducada" if caducada else "ejecutar"


def id_de_boton(data: str | None) -> int | None:
    """El número de la acción en un botón: 'llamar:7' → 7, 'acc:7:si' → 7, 'pc:7:no' → 7."""
    boton = parse_boton(data)
    return boton[1] if boton else None


def decidir(user_id: int | None, permitidos: frozenset[int], tipo: str | None) -> str:
    """Qué hacer con un mensaje: 'id', 'start', 'olvida', 'alternar_voz', 'hablar', 'texto', 'voz' o 'ignorar'."""
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


def audio_a_ogg_opus(audio: bytes) -> bytes:
    """Convierte cualquier audio (MP3, WAV...) a nota de voz OGG/Opus."""
    with av.open(io.BytesIO(audio)) as f:
        resampler = av.AudioResampler(format="s16", layout="mono", rate=48000)
        pcm = b"".join(
            bytes(fr.planes[0])[: fr.samples * 2]
            for frame in f.decode(f.streams.audio[0])
            for fr in resampler.resample(frame)
        )
    return pcm_a_ogg_opus(pcm, 48000, 1)


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
        log.info("Bot @%s listo (%s; %s). Usuarios permitidos: %d",
                 me.username, self.plan.describir(), describir_voz(self.plan), len(self.permitidos))
        if not self.permitidos:
            log.warning("TELEGRAM_ALLOWED_IDS está vacío: escribe /id al bot y pon tu número en .env")
        await app.bot.set_my_commands([
            BotCommand("hablar", "Hablar con JARVIS en directo"),
            BotCommand("voz", "Contestar también con nota de voz"),
            BotCommand("olvida", "Empezar la conversación de cero"),
            BotCommand("id", "Ver tu ID de Telegram"),
        ])

    async def cerrar(self, app: Application) -> None:
        if self.http:
            await self.http.close()
        self.memory.close()

    def siempre_voz(self, chat_id: int) -> bool:
        return self.memory.get_setting(f"telegram.siempre_voz.{chat_id}", "0") == "1"

    async def pensar(self, chat_id: int, texto: str) -> str:
        historial = self.historiales.setdefault(chat_id, llm.ChatContext())
        t0 = time.perf_counter()
        jarvis = Jarvis(self.memory)
        jarvis.preferir_movil = True  # en Telegram estás con el móvil: "abre X" es en el móvil
        respuesta = await responder(self.cerebro, jarvis, historial, texto)
        historial.truncate(max_items=HISTORIAL_MAX)
        log.info("Respuesta en %.2f s", time.perf_counter() - t0)
        return respuesta

    async def hablar(self, texto: str) -> bytes:
        texto = limpiar_para_voz(texto)
        voz = crear_voz(self.plan, self.http)  # la misma voz que en las llamadas y en el PC
        frames = [ev.frame async for ev in voz.synthesize(texto)]
        pcm = b"".join(bytes(f.data) for f in frames)
        return pcm_a_ogg_opus(pcm, frames[0].sample_rate, frames[0].num_channels)

    async def boton_llamada(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        q, user = update.callback_query, update.effective_user
        call_id = id_de_boton(q.data)
        llamada = self.memory.get_call(call_id) if call_id is not None else None
        accion = decidir_boton(user.id if user else None, self.permitidos, q.data, llamada,
                               bool(llamada) and telefono.caducada(llamada))
        if accion == "ignorar":
            log.warning("Botón de llamada ignorado: usuario=%s datos=%r", user.id if user else "?", q.data)
            await q.answer("No puedo usar este botón (no es tuyo o ya no es válido).", show_alert=True)
            return
        await q.answer()
        quien = f"{llamada['nombre']} ({llamada['numero']})"
        if accion == "ya_gestionada":
            await q.edit_message_reply_markup(None)
            return
        if accion == "cancelar":
            self.memory.set_call_status(call_id, "cancelada", only_if="pendiente")
            await q.edit_message_text(f"❌ Llamada a {quien} cancelada.")
            return
        if accion == "caducada":
            self.memory.set_call_status(call_id, "caducada", only_if="pendiente")
            await q.edit_message_text(f"⌛ La confirmación para llamar a {quien} ha caducado. Pídemelo otra vez.")
            return
        # accion == "llamar": marcamos como 'marcando' solo si seguía pendiente (evita dobles pulsaciones)
        if not self.memory.set_call_status(call_id, "marcando", only_if="pendiente"):
            await q.edit_message_reply_markup(None)
            return
        await q.edit_message_text(f"📞 Llamando a {quien}… Te cuento cuando termine.")
        try:
            await telefono.iniciar_llamada(llamada)
        except Exception as e:
            log.exception("No pude iniciar la llamada")
            self.memory.set_call_status(call_id, "fallida")
            await q.message.reply_text(f"No he podido iniciar la llamada: {type(e).__name__}. Revisa la configuración.")

    async def boton_accion(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        q, user = update.callback_query, update.effective_user
        accion_id = id_de_boton(q.data)
        accion = self.memory.get_action(accion_id) if accion_id is not None else None
        decision = decidir_boton_accion(user.id if user else None, self.permitidos, q.data, accion,
                                        bool(accion) and pc.caducada(accion))
        if decision == "ignorar":
            log.warning("Botón de acción ignorado: usuario=%s datos=%r", user.id if user else "?", q.data)
            await q.answer("No puedo usar este botón (no es tuyo o ya no es válido).", show_alert=True)
            return
        await q.answer()
        desc = accion["descripcion"]
        if decision == "ya_gestionada":
            await q.edit_message_reply_markup(None)
            return
        if decision == "cancelar":
            self.memory.set_action_status(accion_id, "cancelada", only_if="pendiente")
            pc.registrar("cancelada", id=accion_id)
            await q.edit_message_text(f"❌ Cancelado: {desc}.")
            return
        if decision == "caducada":
            self.memory.set_action_status(accion_id, "caducada", only_if="pendiente")
            await q.edit_message_text(f"⌛ Caducado: {desc}. Pídemelo otra vez.")
            return
        if not self.memory.set_action_status(accion_id, "ejecutando", only_if="pendiente"):
            await q.edit_message_reply_markup(None)
            return
        try:
            await q.edit_message_text(f"⏳ Haciendo: {desc}…")
        except Exception:  # noqa: BLE001 (no poder editar el mensaje no debe impedir la acción)
            log.warning("No pude actualizar el mensaje del botón")
        donde = "del móvil" if accion["tipo"] == "movil" else "del PC"
        try:
            ejecutor = movil.ejecutar_accion if accion["tipo"] == "movil" else pc.ejecutar_accion
            resultado = await asyncio.to_thread(ejecutor, accion["datos"])
        except Exception as e:
            log.exception("Falló una acción %s", donde)
            self.memory.set_action_status(accion_id, "fallida")
            pc.registrar("fallida", id=accion_id, tipo=accion["tipo"], error=type(e).__name__)
            await q.edit_message_text(f"⚠️ No he podido {desc}: {e}")
            return
        # Ya está hecho: aunque falle el aviso, el estado es 'hecha' (no se debe repetir)
        self.memory.set_action_status(accion_id, "hecha")
        try:
            await q.edit_message_text(f"✅ {desc}\n{resultado}")
        except Exception:  # noqa: BLE001
            log.warning("Acción %s hecha, pero no pude actualizar el mensaje", donde)

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
        if accion == "hablar":
            faltan = telefono.llamadas_configuradas()
            if any(f.startswith("LIVEKIT") for f in faltan):
                await msg.reply_text("Para hablar en directo hace falta LiveKit Cloud en el .env.")
                return
            from . import voz

            url = await voz.crear_sesion(user.id, user.first_name or "Potro")
            await msg.reply_text(
                "🎙 Pulsa el botón, luego toca el círculo y habla. Te escucho mientras la pantalla esté abierta.\n"
                "(El enlace vale para una conversación; para otra, vuelve a escribir /hablar.)",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🎙 Hablar con JARVIS", web_app=WebAppInfo(url))]]),
            )
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
        except Exception as e:
            log.exception("Error atendiendo un mensaje")
            if "429" in str(e) or "rate limit" in str(e).lower():
                await msg.reply_text("Estoy al límite de uso gratuito por minuto, señor. Inténtelo en un minuto.")
            else:
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
    app.add_handler(CallbackQueryHandler(bot.boton_llamada, pattern=r"^(llamar|cancelar):"))
    app.add_handler(CallbackQueryHandler(bot.boton_accion, pattern=r"^(pc|acc):"))
    app.add_handler(MessageHandler(filters.ALL, bot.manejar))
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
