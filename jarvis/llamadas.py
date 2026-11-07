"""Agente de llamadas telefónicas reales (LiveKit + Telnyx).

Se arranca aparte y se queda esperando encargos:
    python -m jarvis.llamadas start

Cada vez que confirmas una llamada en Telegram, LiveKit le manda a este agente
una sala nueva con los datos (a quién, qué decirle). El agente marca, habla,
cuelga y te manda a Telegram el resumen y la transcripción.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
import time

from google.protobuf.duration_pb2 import Duration
from livekit import api
from livekit.agents import (
    AMD,
    AMDCategory,
    Agent,
    AgentSession,
    JobContext,
    RunContext,
    WorkerOptions,
    cli,
    function_tool,
    get_job_context,
    room_io,
)
from livekit.plugins import deepgram, silero
from livekit.plugins.turn_detector.multilingual import MultilingualModel

from . import telefono
from .config import elegir_plan
from .core import KEYTERMS, OWNER, crear_cerebro, crear_voz, describir_voz, nota_de_hora
from .memory import MemoryStore
from .prompts import prompt_buzon, prompt_llamada

log = logging.getLogger("jarvis.llamadas")
NOMBRE_AGENTE = "jarvis-llamadas"
DURACION_MAXIMA = int(os.getenv("JARVIS_LLAMADA_MAX_SEGUNDOS", "180"))
TIEMPO_TIMBRE = 40  # segundos sonando antes de darse por vencido

RESULTADOS = {
    "persona": "contestó una persona",
    "buzon": "saltó el contestador y dejé el mensaje",
    "no_disponible": "no se pudo dejar mensaje (buzón lleno o sin configurar)",
    "centralita": "contestó una centralita automática",
    "sin_respuesta": "no contestó",
    "error": "no se pudo llamar",
}


class AgenteLlamada(Agent):
    def __init__(self, nombre: str, mensaje: str) -> None:
        super().__init__(instructions=prompt_llamada(OWNER, nombre, mensaje) + "\n\n" + nota_de_hora())
        self.resumen: str | None = None

    @function_tool
    async def colgar(self, context: RunContext, resumen: str) -> str:
        """Termina la llamada cuando ya te has despedido.

        Args:
            resumen: en una o dos frases, qué te han contestado o qué ha pasado.
        """
        self.resumen = resumen
        await context.wait_for_playout()  # que termine de decir la despedida
        await get_job_context().delete_room()
        return "Llamada terminada."


def formatear_informe(datos: dict, resultado: str, segundos: float, resumen: str | None,
                      transcripcion: list[tuple[str, str]]) -> str:
    lineas = [
        f"📞 Llamada a {datos['nombre']} ({datos['numero']})",
        f"Resultado: {RESULTADOS.get(resultado, resultado)} · {int(segundos)} s",
    ]
    if resumen:
        lineas += ["", f"Resumen: {resumen}"]
    if transcripcion:
        lineas += ["", "Transcripción:"]
        lineas += [f"{'JARVIS' if rol == 'assistant' else datos['nombre']}: {texto}" for rol, texto in transcripcion]
    informe = "\n".join(lineas)
    return informe if len(informe) <= 4000 else informe[:3990] + "\n…"


def _transcripcion(session: AgentSession) -> list[tuple[str, str]]:
    salida = []
    for item in session.history.items:
        if getattr(item, "type", None) == "message" and item.role in ("user", "assistant"):
            texto = (item.text_content or "").strip()
            if texto:
                salida.append((item.role, texto))
    return salida


def _guardar_estado(call_id: int, estado: str) -> None:
    try:
        m = MemoryStore(os.getenv("JARVIS_MEMORY_PATH", "jarvis_memoria.db"))
        m.set_call_status(call_id, estado)
        m.close()
    except Exception:
        log.exception("No pude guardar el estado de la llamada")


async def entrypoint(ctx: JobContext) -> None:
    datos = json.loads(ctx.job.metadata or "{}")
    if not datos.get("numero"):
        log.error("Encargo de llamada sin número; lo ignoro")
        return
    await ctx.connect()

    plan = elegir_plan(os.environ)
    log.info("Llamada %s: %s; %s", datos["id"], plan.describir(), describir_voz(plan))
    agente = AgenteLlamada(datos["nombre"], datos["mensaje"])
    session = AgentSession(
        vad=silero.VAD.load(),
        stt=deepgram.STT(model="nova-3", language="es", keyterm=KEYTERMS),
        llm=crear_cerebro(plan),
        tts=crear_voz(plan),
        turn_detection=MultilingualModel(),
    )
    identidad = f"telefono-{datos['id']}"
    estado = {"resultado": "error", "inicio": time.monotonic()}

    async def informar() -> None:
        segundos = time.monotonic() - estado["inicio"] if estado["resultado"] in ("persona", "buzon") else 0
        _guardar_estado(datos["id"], "hecha" if estado["resultado"] in ("persona", "buzon") else "fallida")
        if datos.get("chat_id"):
            try:
                telefono.telegram("sendMessage", chat_id=datos["chat_id"], text=formatear_informe(
                    datos, estado["resultado"], segundos, agente.resumen, _transcripcion(session)))
            except Exception:
                log.exception("No pude mandar el informe a Telegram")

    ctx.add_shutdown_callback(informar)

    await session.start(
        agent=agente,
        room=ctx.room,
        room_options=room_io.RoomOptions(participant_identity=identidad, delete_room_on_close=True),
    )

    try:
        async with AMD(session, llm=None, stt=None) as detector:
            await ctx.api.sip.create_sip_participant(api.CreateSIPParticipantRequest(
                room_name=ctx.room.name,
                sip_trunk_id=os.environ["LIVEKIT_SIP_TRUNK_ID"],
                sip_call_to=datos["numero"],
                participant_identity=identidad,
                participant_name=datos["nombre"],
                wait_until_answered=True,
                ringing_timeout=Duration(seconds=TIEMPO_TIMBRE),
                max_call_duration=Duration(seconds=DURACION_MAXIMA + 30),  # tope duro del lado telefónico
            ))
            estado["inicio"] = time.monotonic()
            veredicto = await detector.execute()
    except api.TwirpError as e:
        sip = (e.metadata or {}).get("sip_status_code")
        log.warning("La llamada no se pudo completar: %s (SIP %s)", e.message, sip)
        estado["resultado"] = "sin_respuesta" if sip in ("408", "480", "486", "487", "603") else "error"
        ctx.shutdown()
        return

    log.info("Detector de contestador: %s", veredicto.category)
    if veredicto.category == AMDCategory.MACHINE_VM:
        estado["resultado"] = "buzon"
        await session.generate_reply(instructions=prompt_buzon(OWNER, datos["nombre"], datos["mensaje"]))
        await asyncio.sleep(0.5)
        await ctx.delete_room()
        return
    if veredicto.category in (AMDCategory.MACHINE_UNAVAILABLE, AMDCategory.MACHINE_IVR):
        estado["resultado"] = "no_disponible" if veredicto.category == AMDCategory.MACHINE_UNAVAILABLE else "centralita"
        await ctx.delete_room()
        return

    estado["resultado"] = "persona"
    await session.generate_reply(instructions="Te acaban de contestar. Preséntate como se te ha indicado y da el mensaje.")

    async def limite() -> None:
        await asyncio.sleep(DURACION_MAXIMA)
        log.info("Tiempo máximo de llamada alcanzado")
        await session.generate_reply(instructions="Se acaba el tiempo: despídete en una frase.")
        await asyncio.sleep(6)
        await ctx.delete_room()

    tarea = asyncio.create_task(limite())

    async def cancelar_limite() -> None:
        tarea.cancel()

    ctx.add_shutdown_callback(cancelar_limite)


def main() -> None:
    faltan = telefono.llamadas_configuradas()
    if faltan and "download-files" not in sys.argv:
        sys.exit("ERROR: faltan datos en .env para las llamadas: " + ", ".join(faltan))
    cli.run_app(WorkerOptions(entrypoint_fnc=entrypoint, agent_name=NOMBRE_AGENTE))


if __name__ == "__main__":
    main()
