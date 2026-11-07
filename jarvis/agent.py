"""Punto de entrada de JARVIS: agente de voz sobre LiveKit Agents.

Uso:
    python -m jarvis.agent console   # hablar con JARVIS desde el terminal
    python -m jarvis.agent dev       # conectarlo a un servidor LiveKit
"""

from __future__ import annotations

import logging
import os
import sys
from datetime import datetime
from zoneinfo import ZoneInfo

from dotenv import load_dotenv
from livekit.agents import (
    Agent,
    AgentSession,
    JobContext,
    RunContext,
    WorkerOptions,
    cli,
    function_tool,
)
from livekit.agents.llm import mcp
from livekit.plugins import anthropic, deepgram, elevenlabs, openai, silero
from livekit.plugins.turn_detector.multilingual import MultilingualModel

from .config import Plan, elegir_plan
from .memory import MemoryStore
from .prompts import system_prompt

load_dotenv()
log = logging.getLogger("jarvis")

OWNER = os.getenv("JARVIS_OWNER_NAME", "Potro")
TZ = ZoneInfo("Europe/Madrid")


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
        now = datetime.now(TZ)
        dias = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]
        meses = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio",
                 "agosto", "septiembre", "octubre", "noviembre", "diciembre"]
        return f"{dias[now.weekday()]} {now.day} de {meses[now.month - 1]} de {now.year}, {now:%H:%M}"


def _mcp_servers() -> list[mcp.MCPServer]:
    urls = [u.strip() for u in os.getenv("JARVIS_MCP_URLS", "").split(",") if u.strip()]
    return [mcp.MCPServerHTTP(url=u) for u in urls]


def _cerebro(plan: Plan):
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


def _voz(plan: Plan):
    if plan.voz == "elevenlabs":
        return elevenlabs.TTS(
            model="eleven_flash_v2_5",
            language="es",
            **({"voice_id": v} if (v := os.getenv("ELEVEN_VOICE_ID")) else {}),
        )
    return deepgram.TTS(model=os.getenv("JARVIS_DEEPGRAM_VOICE", "aura-2-alvaro-es"))


async def entrypoint(ctx: JobContext) -> None:
    await ctx.connect()
    plan = elegir_plan(os.environ)
    log.info("JARVIS arranca con %s", plan.describir())
    memory = MemoryStore(os.getenv("JARVIS_MEMORY_PATH", "jarvis_memoria.db"))

    session = AgentSession(
        vad=silero.VAD.load(),
        stt=deepgram.STT(model="nova-3", language="es"),
        llm=_cerebro(plan),
        tts=_voz(plan),
        turn_detection=MultilingualModel(),
        mcp_servers=_mcp_servers(),
        max_tool_steps=5,
    )
    ctx.add_shutdown_callback(lambda: memory.close())

    await session.start(room=ctx.room, agent=Jarvis(memory))
    await session.generate_reply(
        instructions=f"Saluda brevemente a {OWNER} según la hora del día y pregúntale en qué puedes ayudarle."
    )


def main() -> None:
    if "download-files" not in sys.argv:
        try:
            print(f"JARVIS: {elegir_plan(os.environ).describir()}")
        except ValueError as e:
            sys.exit(f"ERROR: {e}")
    cli.run_app(WorkerOptions(entrypoint_fnc=entrypoint))


if __name__ == "__main__":
    main()
