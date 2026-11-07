"""Punto de entrada de JARVIS: agente de voz sobre LiveKit Agents.

Uso:
    python -m jarvis.agent console   # hablar con JARVIS desde el terminal
    python -m jarvis.agent dev       # conectarlo a un servidor LiveKit
"""

from __future__ import annotations

import asyncio
import json
import os
import sys

from livekit.agents import AgentSession, JobContext, WorkerOptions, cli
from livekit.agents.llm import mcp
from livekit.plugins import deepgram, silero
from livekit.plugins.turn_detector.multilingual import MultilingualModel

from .config import elegir_plan
from .core import KEYTERMS, MAX_TOOL_STEPS, OWNER, Jarvis, crear_cerebro, crear_voz, describir_voz, log
from .memory import MemoryStore


def _mcp_servers() -> list[mcp.MCPServer]:
    urls = [u.strip() for u in os.getenv("JARVIS_MCP_URLS", "").split(",") if u.strip()]
    return [mcp.MCPServerHTTP(url=u) for u in urls]


async def entrypoint(ctx: JobContext) -> None:
    await ctx.connect()
    plan = elegir_plan(os.environ)
    log.info("JARVIS arranca con %s; %s", plan.describir(), describir_voz(plan))
    memory = MemoryStore(os.getenv("JARVIS_MEMORY_PATH", "jarvis_memoria.db"))

    session = AgentSession(
        vad=silero.VAD.load(),
        stt=deepgram.STT(model="nova-3", language="es", keyterm=KEYTERMS),
        llm=crear_cerebro(plan),
        tts=crear_voz(plan),
        turn_detection=MultilingualModel(),
        mcp_servers=_mcp_servers(),
        max_tool_steps=MAX_TOOL_STEPS,
    )
    async def cerrar_memoria() -> None:
        memory.close()

    ctx.add_shutdown_callback(cerrar_memoria)

    desde_movil = ctx.room.name.startswith("voz-")  # sala creada por el bot de Telegram (Mini App)
    if desde_movil:
        from .voz import JarvisVoz

        agente = JarvisVoz(memory)

        @session.on("function_tools_executed")
        def _avisar_a_la_pagina(ev) -> None:
            # La página del móvil enseña qué está haciendo JARVIS ("abrir_app · Abriendo YouTube…")
            for llamada, salida in ev.zipped():
                datos = {"id": llamada.call_id, "nombre": llamada.name,
                         "estado": "error" if salida and salida.is_error else "ok",
                         "texto": (salida.output if salida else "")[:90]}
                asyncio.create_task(ctx.room.local_participant.publish_data(
                    json.dumps(datos, ensure_ascii=False).encode(), topic="jarvis", reliable=True))
    else:
        agente = Jarvis(memory)

    await session.start(room=ctx.room, agent=agente)
    await session.generate_reply(
        instructions=f"Saluda brevemente a {OWNER} según la hora del día y pregúntale en qué puedes ayudarle."
    )


def main() -> None:
    if "download-files" not in sys.argv:
        try:
            print(f"JARVIS: {elegir_plan(os.environ).describir()}")
        except ValueError as e:
            sys.exit(f"ERROR: {e}")
    # Con nombre propio: así no se mete en las salas de las llamadas telefónicas (jarvis-llamadas)
    cli.run_app(WorkerOptions(entrypoint_fnc=entrypoint, agent_name="jarvis-voz"))


if __name__ == "__main__":
    main()
