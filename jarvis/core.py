"""Piezas comunes de JARVIS: personalidad, herramientas, cerebro y voz.

Las usan tanto el agente de voz (`jarvis.agent`) como el bot de Telegram
(`jarvis.telegram_bot`), para que los dos sean el mismo JARVIS con la misma memoria.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime
from zoneinfo import ZoneInfo

import aiohttp
from dotenv import load_dotenv
from livekit.agents import Agent, RunContext, function_tool, llm, tts
from livekit.plugins import anthropic, deepgram, elevenlabs, openai

from .config import Plan
from .memory import MemoryStore
from .prompts import system_prompt

load_dotenv()
log = logging.getLogger("jarvis")

OWNER = os.getenv("JARVIS_OWNER_NAME", "Potro")
TZ = ZoneInfo("Europe/Madrid")
MAX_TOOL_STEPS = 5
# Palabras que Deepgram debe reconocer aunque no sean españolas ("Yarbi" -> "Jarvis")
KEYTERMS = ["Jarvis"]

DIAS = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]
MESES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio",
         "agosto", "septiembre", "octubre", "noviembre", "diciembre"]


def fecha_hora_texto(now: datetime | None = None) -> str:
    now = now or datetime.now(TZ)
    return f"{DIAS[now.weekday()]} {now.day} de {MESES[now.month - 1]} de {now.year}, {now:%H:%M}"


def nota_de_hora(now: datetime | None = None) -> str:
    """Se añade al contexto en cada turno para que el modelo nunca tenga que adivinar la hora."""
    return (
        f"Fecha y hora actuales en España: {fecha_hora_texto(now)} (hora de Madrid). "
        "Usa exactamente este dato si te preguntan la fecha o la hora; nunca te la inventes."
    )


class Jarvis(Agent):
    def __init__(self, memory: MemoryStore) -> None:
        self.memory = memory
        recent = [m.text for m in memory.recent(20)]
        super().__init__(instructions=system_prompt(OWNER, recent))

    @function_tool
    async def recordar(self, context: RunContext, hecho: str, categoria: str = "general") -> str:
        """Guarda un dato importante sobre el usuario para recordarlo siempre.

        Args:
            hecho: el dato en una frase, por ejemplo "Su madre se llama Carmen".
            categoria: personas, gustos, fechas, planes o general.
        """
        m = self.memory.remember(hecho, categoria)
        return f"Guardado (#{m.id})."

    @function_tool
    async def buscar_recuerdos(self, context: RunContext, consulta: str) -> str:
        """Busca en la memoria datos que el usuario contó antes.

        Args:
            consulta: palabras clave, por ejemplo "cumpleaños madre".
        """
        found = self.memory.recall(consulta)
        if not found:
            return "No tengo nada guardado sobre eso."
        return "\n".join(f"- {m.text} ({m.created_at[:10]})" for m in found)

    @function_tool
    async def fecha_y_hora(self, context: RunContext) -> str:
        """Devuelve la fecha y hora actuales en España."""
        return fecha_hora_texto()

    async def on_user_turn_completed(self, turn_ctx: llm.ChatContext, new_message: llm.ChatMessage) -> None:
        # Agente de voz: antes de cada respuesta le recordamos la hora real.
        turn_ctx.add_message(role="system", content=nota_de_hora())


def crear_cerebro(plan: Plan) -> llm.LLM:
    if plan.cerebro == "claude":
        return anthropic.LLM(model=os.getenv("JARVIS_MODEL", "claude-sonnet-5-5"), caching="ephemeral")
    if plan.cerebro == "groq":
        return openai.LLM(
            model=os.getenv("JARVIS_GROQ_MODEL", "qwen/qwen3.8-27b"),
            base_url="https://api.groq.com/openai/v1",
            api_key=os.environ["GROQ_API_KEY"].strip(),
        )
    return openai.LLM(
        model=os.getenv("JARVIS_GEMINI_MODEL", "gemini-2.5-flash"),
        base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
        api_key=os.environ["GEMINI_API_KEY"].strip(),
    )


def crear_voz(plan: Plan, http_session: aiohttp.ClientSession | None = None) -> tts.TTS:
    extra = {"http_session": http_session} if http_session else {}
    if plan.voz == "elevenlabs":
        return elevenlabs.TTS(
            model="eleven_flash_v2_5",
            language="es",
            **({"voice_id": v} if (v := os.getenv("ELEVEN_VOICE_ID")) else {}),
            **extra,
        )
    return deepgram.TTS(model=os.getenv("JARVIS_DEEPGRAM_VOICE", "aura-2-alvaro-es"), **extra)


async def responder(cerebro: llm.LLM, jarvis: Jarvis, historial: llm.ChatContext, texto: str) -> str:
    """Añade `texto` al historial, deja que JARVIS piense (usando herramientas) y devuelve su respuesta."""
    historial.add_message(role="user", content=texto)
    herramientas = {t.info.name: t for t in jarvis.tools}
    respuesta = ""
    for _ in range(MAX_TOOL_STEPS):
        ctx = historial.copy()
        ctx.items.insert(0, llm.ChatMessage(role="system", content=[jarvis.instructions, nota_de_hora()]))
        respuesta, llamadas = "", []
        async with cerebro.chat(chat_ctx=ctx, tools=list(herramientas.values())) as stream:
            async for chunk in stream:
                if chunk.delta:
                    respuesta += chunk.delta.content or ""
                    llamadas += chunk.delta.tool_calls or []
        if not llamadas:
            break
        for c in llamadas:
            historial.items.append(llm.FunctionCall(call_id=c.call_id, name=c.name, arguments=c.arguments))
            salida, error = await _ejecutar(herramientas, c.name, c.arguments)
            historial.items.append(
                llm.FunctionCallOutput(call_id=c.call_id, name=c.name, output=salida, is_error=error)
            )
    respuesta = respuesta.strip() or "Disculpe, señor, no he sabido qué responder."
    historial.add_message(role="assistant", content=respuesta)
    return respuesta


async def _ejecutar(herramientas: dict, nombre: str, argumentos: str) -> tuple[str, bool]:
    if nombre not in herramientas:
        return f"La herramienta {nombre} no existe.", True
    log.info("Herramienta usada: %s", nombre)
    try:
        args = json.loads(argumentos or "{}") or {}
        return str(await herramientas[nombre](None, **args)), False
    except Exception as e:  # el modelo puede mandar argumentos raros
        log.warning("Fallo en la herramienta %s: %s", nombre, e)
        return f"Error: {e}", True
