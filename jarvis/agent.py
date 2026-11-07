"""Punto de entrada de JARVIS: agente de voz sobre LiveKit Agents.

Uso:
    python -m jarvis.agent console   # hablar con JARVIS desde el terminal
    python -m jarvis.agent dev       # conectarlo a un servidor LiveKit
"""

from __future__ import annotations

import logging
import os
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
from livekit.plugins import anthropic, deepgram, elevenlabs, silero
from livekit.plugins.turn_detector.multilingual import MultilingualModel

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


async def entrypoint(ctx: JobContext) -> None:
    await ctx.connect()
    memory = MemoryStore(os.getenv("JARVIS_MEMORY_PATH", "jarvis_memoria.db"))

    session = AgentSession(
        vad=silero.VAD.load(),
        stt=deepgram.STT(model="nova-3", language="es"),
        llm=anthropic.LLM(model=os.getenv("JARVIS_MODEL", "claude-sonnet-5-5"), caching="ephemeral"),
        tts=elevenlabs.TTS(
            model="eleven_flash_v2_5",
            language="es",
            **({"voice_id": v} if (v := os.getenv("ELEVEN_VOICE_ID")) else {}),
        ),
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
    cli.run_app(WorkerOptions(entrypoint_fnc=entrypoint))


if __name__ == "__main__":
    main()
