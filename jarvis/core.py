"""Piezas comunes de JARVIS: personalidad, herramientas, cerebro y voz.

Las usan tanto el agente de voz (`jarvis.agent`) como el bot de Telegram
(`jarvis.telegram_bot`), para que los dos sean el mismo JARVIS con la misma memoria.
"""

from __future__ import annotations

import json
import logging
import os
import re
from datetime import datetime
from typing import Awaitable, Callable
from zoneinfo import ZoneInfo

import aiohttp
from dotenv import load_dotenv
from livekit.agents import Agent, RunContext, function_tool, llm, tts
from livekit.plugins import anthropic, deepgram, elevenlabs, openai

from . import cerebros, telefono
from .internet import Internet
from .movil import ControlMovil
from .pc import ControlPC
from .config import Plan
from .memory import MemoryStore
from .prompts import system_prompt
from .recordatorios import Recordatorios
from .resumen import Resumen

load_dotenv()
log = logging.getLogger("jarvis")

OWNER = os.getenv("JARVIS_OWNER_NAME", "Potro")
TZ = ZoneInfo("Europe/Madrid")
MAX_TOOL_STEPS = 5
NOTA_MOVIL = (
    "Ahora mismo te habla desde su MÓVIL. Si pide abrir una app o una web, poner música, subir el volumen, "
    "una alarma o mandar un mensaje sin decir dónde, hazlo en el MÓVIL (movil_hacer, movil_mensaje). "
    "Usa el PC solo si dice 'en el PC' o 'en el ordenador'."
)
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


class Jarvis(ControlPC, ControlMovil, Internet, Recordatorios, Resumen, Agent):
    def __init__(
        self,
        memory: MemoryStore,
        pedir_confirmacion: Callable[[dict], Awaitable[None]] | None = None,
        pedir_confirmacion_pc: Callable[[dict], Awaitable[None]] | None = None,
    ) -> None:
        self.memory = memory
        self._pedir_confirmacion = pedir_confirmacion or telefono.pedir_confirmacion_telegram
        self._pedir_confirmacion_pc = pedir_confirmacion_pc
        recent = [m.text for m in memory.recent(20)]
        super().__init__(instructions=system_prompt(OWNER, recent))

    @function_tool
    async def guardar_contacto(self, context: RunContext, nombre: str, numero: str) -> str:
        """Guarda en la agenda el teléfono de una persona para poder llamarla después.

        Args:
            nombre: cómo la llama el usuario, por ejemplo "mamá" o "Carlos del trabajo".
            numero: su teléfono, por ejemplo "600 12 34 56" o "+34 600 12 34 56".
        """
        try:
            e164 = telefono.guardar_contacto(self.memory, nombre, numero)
        except ValueError as e:
            return f"No lo he guardado: {e}."
        return f"Guardado: {nombre} → {e164}."

    @function_tool
    async def llamar(self, context: RunContext, destino: str, mensaje: str) -> str:
        """Prepara una llamada telefónica real para transmitir un mensaje. El usuario debe confirmarla en Telegram.

        Args:
            destino: nombre de la agenda (por ejemplo "mamá") o número de teléfono.
            mensaje: lo que hay que decirle, en una o dos frases, por ejemplo "que llego a las 8".
        """
        faltan = telefono.llamadas_configuradas()
        if faltan:
            return "Las llamadas todavía no están configuradas (faltan: " + ", ".join(faltan) + ")."
        try:
            nombre, numero = telefono.resolver_destino(self.memory, destino)
        except (LookupError, ValueError) as e:
            return f"No puedo llamar: {e}. Pide el número y guárdalo con guardar_contacto."
        if not telefono.numero_permitido(numero):
            return f"No puedo llamar a {numero}: solo se permiten números de España y la UE."
        call_id = self.memory.create_call(nombre, numero, mensaje.strip())
        await self._pedir_confirmacion(self.memory.get_call(call_id))
        return self._texto_pendiente(f"llamar a {nombre} ({numero}) para decirle: «{mensaje.strip()}»")

    confirmacion_por_voz = False
    preferir_movil = False  # hablando desde el móvil: "abre X" es en el móvil
    siempre_disponibles: frozenset[str] = frozenset()

    def _texto_pendiente(self, descripcion: str) -> str:
        """Qué decirle al cerebro cuando una acción queda pendiente de confirmar."""
        if self.confirmacion_por_voz:
            return (f"PENDIENTE de confirmar: {descripcion}. Pregúntale a {OWNER} de viva voz si lo haces "
                    "(una frase corta). Solo si responde que sí, usa confirmar_pendiente.")
        return (f"Preparado, pero NO hecho todavía: {descripcion}. {OWNER} tiene en Telegram un botón "
                "para confirmarlo. Díselo así.")

    @function_tool
    async def recordar(self, context: RunContext, hecho: str, sobre: str = "", tipo: str = "general",
                       relacionados: str = "") -> str:
        """Guarda un dato importante para recordarlo siempre, en el cerebro de JARVIS (notas enlazadas).

        Args:
            hecho: el dato en una frase, por ejemplo "Es la madre de Potro y cumple años el 3 de mayo".
            sobre: de quién o de qué trata (será su nota), por ejemplo "Carmen". Vacío si no es de nada concreto.
            tipo: persona, lugar, proyecto, gusto, evento o general.
            relacionados: otras personas, lugares o cosas que aparecen, separadas por comas, p. ej. "Madrid, Potro".
        """
        m = self.memory.remember(f"{sobre}: {hecho}" if sobre else hecho, tipo)
        b = boveda_activa()
        if b is None:
            return f"Guardado (#{m.id})."
        nota = b.recordar(hecho, sobre=sobre, tipo=tipo, relacionados=[r for r in relacionados.split(",") if r.strip()])
        return f"Guardado en la nota «{nota}»."

    @function_tool
    async def buscar_recuerdos(self, context: RunContext, consulta: str) -> str:
        """Busca en la memoria (el cerebro de JARVIS) lo que el usuario contó antes. Úsala antes de responder
        sobre su vida, su familia, sus planes o sus gustos.

        Args:
            consulta: palabras clave o nombres, por ejemplo "Carmen cumpleaños".
        """
        b = boveda_activa()
        if b is None:
            found = self.memory.recall(consulta)
            if not found:
                return "No tengo nada guardado sobre eso."
            return "\n".join(f"- {m.text} ({m.created_at[:10]})" for m in found)
        resultados = b.buscar(consulta)
        if not resultados:
            return "No tengo nada guardado sobre eso."
        lineas = [f"- Nota «{n}»: {s}" for n, s in resultados]
        principal = b.leer(resultados[0][0]) or ""
        enlazadas = [e for e in b.enlaces(principal) if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", e)][:8]
        if enlazadas:
            lineas.append("Notas enlazadas (usa leer_nota para ver más): " + ", ".join(enlazadas))
        return "\n".join(lineas)

    @function_tool
    async def leer_nota(self, context: RunContext, nombre: str) -> str:
        """Lee una nota entera del cerebro de JARVIS (por ejemplo la de una persona) para tener todo el contexto.

        Args:
            nombre: nombre de la nota, por ejemplo "Carmen".
        """
        b = boveda_activa()
        texto = b.leer(nombre) if b else None
        return texto or f"No hay ninguna nota llamada «{nombre}»."

    @function_tool
    async def fecha_y_hora(self, context: RunContext) -> str:
        """Devuelve la fecha y hora actuales en España."""
        return fecha_hora_texto()

    async def on_user_turn_completed(self, turn_ctx: llm.ChatContext, new_message: llm.ChatMessage) -> None:
        # Agente de voz: antes de cada respuesta le recordamos la hora real…
        turn_ctx.add_message(role="system", content=nota_de_hora())
        if self.preferir_movil:
            turn_ctx.add_message(role="system", content=NOTA_MOVIL)
        # …y le damos solo las herramientas que hacen falta para esta frase (gasta mucho menos)
        if not hasattr(self, "_todas"):
            self._todas, self._grupos_previos = list(self.tools), set()
        grupos = cerebros.grupos_para(new_message.text_content or "", self._grupos_previos, self.preferir_movil)
        self._grupos_previos = grupos - {"basicas"}
        permitidas = cerebros.herramientas_de(grupos) | self.siempre_disponibles
        await self.update_tools([t for t in self._todas if t.info.name in permitidas])


_boveda = None


def boveda_activa():
    """La bóveda de Obsidian si está configurada (JARVIS_BOVEDA en .env); si no, None (memoria SQLite)."""
    global _boveda
    if _boveda is None and os.getenv("JARVIS_BOVEDA", "").strip():
        from .boveda import Boveda, migrar

        _boveda = Boveda(os.environ["JARVIS_BOVEDA"].strip())
        try:
            memoria = MemoryStore(os.getenv("JARVIS_MEMORY_PATH", "jarvis_memoria.db"))
            n = migrar(_boveda, memoria)
            memoria.close()
            if n:
                log.info("Migrados %d recuerdos y contactos a la bóveda", n)
        except Exception:  # noqa: BLE001
            log.exception("No pude migrar la memoria antigua a la bóveda")
    return _boveda


def _un_cerebro(nombre: str) -> llm.LLM:
    if nombre == "claude":
        return anthropic.LLM(model=os.getenv("JARVIS_MODEL", "claude-sonnet-5-5"), caching="ephemeral")
    if nombre == "livekit":
        from livekit.agents import inference

        modelo = os.getenv("JARVIS_LIVEKIT_MODEL", "").strip() or cerebros.MODELO_LIVEKIT
        log.info("Cerebro livekit: modelo %s", modelo)
        return inference.LLM(model=modelo)
    prov = cerebros.POR_NOMBRE[nombre]
    modelo = cerebros.modelo_de(prov)
    log.info("Cerebro %s: modelo %s", nombre, modelo)
    return openai.LLM(model=modelo, base_url=prov.base_url, api_key=os.environ[prov.clave].strip())


def cerebros_disponibles(plan: Plan, env=os.environ) -> list[str]:
    """El elegido primero y, de reserva, los demás que tengan clave (por si se agota el límite gratuito)."""
    return [plan.cerebro] + [c for c in cerebros.disponibles(env) if c != plan.cerebro]


def crear_cerebro(plan: Plan) -> llm.LLM:
    nombres = cerebros_disponibles(plan)
    if len(nombres) == 1:
        return _un_cerebro(nombres[0])
    # Si uno falla (p. ej. límite por minuto), sigue con el siguiente sin cortar la conversación.
    # El que falló queda "en reposo" y LiveKit lo vuelve a probar en segundo plano hasta que se recupera.
    adaptador = llm.FallbackAdapter([_un_cerebro(n) for n in nombres], attempt_timeout=20.0)
    etiquetas = {id(m): n for m, n in zip(adaptador._llm_instances, nombres)} if hasattr(adaptador, "_llm_instances") else {}

    def _aviso(ev) -> None:
        quien = etiquetas.get(id(getattr(ev, "llm", None)), "un cerebro")
        log.warning("%s %s", quien, "vuelve a estar disponible" if ev.available else "no responde (límite o error): paso al siguiente")

    adaptador.on("llm_availability_changed", _aviso)
    return adaptador


# ElevenLabs: voz por defecto (la del plugin) hasta que se elija una con ELEVEN_VOICE_ID
VOZ_ELEVEN_POR_DEFECTO = "hpp4J3VqNfWAUOO0d1Us"
# Un solo modelo para todo (llamadas, voz del PC y notas de Telegram), para que JARVIS suene
# exactamente igual en todas partes. eleven_v4_turbo: familia v4 (la más realista) y tan rápida como flash.
MODELO_ELEVEN = "eleven_v4_turbo"


def voz_eleven() -> str:
    return os.getenv("ELEVEN_VOICE_ID", "").strip() or VOZ_ELEVEN_POR_DEFECTO


def modelo_eleven() -> str:
    return os.getenv("ELEVEN_MODEL", "").strip() or MODELO_ELEVEN


def describir_voz(plan: Plan) -> str:
    if plan.voz == "elevenlabs":
        return f"ElevenLabs voz={voz_eleven()} modelo={modelo_eleven()}"
    return f"Deepgram {os.getenv('JARVIS_DEEPGRAM_VOICE', 'aura-2-alvaro-es')}"


def ajustes_eleven() -> dict:
    """Ajustes para que suene natural: algo de variación (estabilidad media) y fiel a la voz original."""
    return {
        "stability": float(os.getenv("ELEVEN_STABILITY", "0.4")),
        "similarity_boost": float(os.getenv("ELEVEN_SIMILARITY", "0.8")),
        "style": float(os.getenv("ELEVEN_STYLE", "0.3")),
        "use_speaker_boost": True,
    }


_MARKDOWN = re.compile(r"[*_`#>|~]+")
_URL = re.compile(r"https?://\S+")
_EMOJI = re.compile("[\U0001F000-\U0001FAFF☀-➿️‍]+")
_HORA = re.compile(r"\b(\d{1,2}):(\d{2})\b")


def limpiar_para_voz(texto: str) -> str:
    """Quita lo que no se debe leer en voz alta (markdown, emojis, enlaces) y escribe las horas como se dicen."""
    texto = _URL.sub("el enlace", texto)
    texto = _EMOJI.sub("", texto)
    texto = _MARKDOWN.sub("", texto)
    texto = _HORA.sub(lambda m: f"{int(m[1])} en punto" if m[2] == "00" else f"{int(m[1])} y {int(m[2])}", texto)
    texto = re.sub(r"^\s*[-•]\s+", "", texto, flags=re.M)  # viñetas
    texto = re.sub(r"\s+", " ", texto)
    return re.sub(r"\s+([.,;:!?])", r"\1", texto).strip()


def voz_de_reserva(http_session: aiohttp.ClientSession | None = None) -> tts.TTS:
    """Voz castellana de Deepgram (usa la misma clave que el oído): siempre disponible de reserva."""
    extra = {"http_session": http_session} if http_session else {}
    return deepgram.TTS(model=os.getenv("JARVIS_DEEPGRAM_VOICE", "aura-2-alvaro-es"), **extra)


def crear_voz(plan: Plan, http_session: aiohttp.ClientSession | None = None) -> tts.TTS:
    """La voz de JARVIS. Es la misma para llamadas, voz del PC y notas de voz de Telegram.
    Si ElevenLabs falla (clave, permisos o cupo), habla con la voz de reserva en vez de quedarse mudo."""
    extra = {"http_session": http_session} if http_session else {}
    if plan.voz == "elevenlabs":
        modelo = modelo_eleven()
        if not modelo.startswith("eleven_v4"):  # los v4 no admiten estos ajustes (usan otra API)
            extra["voice_settings"] = elevenlabs.VoiceSettings(**ajustes_eleven())
        voz: tts.TTS = elevenlabs.TTS(model=modelo, language="es", voice_id=voz_eleven(), **extra)
        if modelo.startswith("eleven_v4"):
            # Los v4 en tiempo real cortan la conexión tras 20 s sin texto (lo normal mientras
            # el usuario habla). Frase a frase por HTTP no hay conexión que se pueda caducar.
            voz = tts.StreamAdapter(tts=voz)
        return tts.FallbackAdapter([voz, voz_de_reserva(http_session)], max_retry_per_tts=0)
    return voz_de_reserva(http_session)


async def responder(cerebro: llm.LLM, jarvis: Jarvis, historial: llm.ChatContext, texto: str) -> str:
    """Añade `texto` al historial, deja que JARVIS piense (usando herramientas) y devuelve su respuesta."""
    # Solo las herramientas que hacen falta (más las usadas hace poco, para "mándamelo", "sí, ese", etc.)
    recientes = {i.name for i in historial.items[-8:] if getattr(i, "type", None) == "function_call"}
    preferir_movil = getattr(jarvis, "preferir_movil", False)
    jarvis._ultima_frase = texto  # las herramientas del PC miran si se nombró el PC
    grupos = cerebros.grupos_para(texto, cerebros.grupos_de_herramientas(recientes), preferir_movil)
    permitidas = cerebros.herramientas_de(grupos)
    historial.add_message(role="user", content=texto)
    herramientas = {t.info.name: t for t in jarvis.tools if t.info.name in permitidas}
    log.info("Grupos de herramientas: %s (%d herramientas)", ",".join(sorted(grupos)), len(herramientas))
    respuesta = ""
    reintentado = False
    for _ in range(MAX_TOOL_STEPS + 1):
        ctx = historial.copy()
        sistema = [jarvis.instructions, nota_de_hora()] + ([NOTA_MOVIL] if preferir_movil else [])
        ctx.items.insert(0, llm.ChatMessage(role="system", content=sistema))
        respuesta, llamadas = "", []
        async with cerebro.chat(chat_ctx=ctx, tools=list(herramientas.values())) as stream:
            async for chunk in stream:
                if chunk.delta:
                    respuesta += chunk.delta.content or ""
                    llamadas += chunk.delta.tool_calls or []
        if not llamadas and not respuesta.strip() and not reintentado:
            reintentado = True  # a veces el modelo devuelve una respuesta vacía: un reintento basta
            continue
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
    args: dict = {}
    try:
        args = json.loads(argumentos or "{}") or {}
        # Los modelos pequeños a veces mandan null en campos opcionales: mejor usar el valor por defecto
        args = {k: v for k, v in args.items() if v is not None}
        return str(await herramientas[nombre](None, **args)), False
    except Exception as e:  # el modelo puede mandar argumentos raros
        log.warning("Fallo en la herramienta %s (campos %s): %s", nombre, sorted(args), e)
        return (f"Error: {e}. NO se ha hecho. Revisa los datos y vuelve a intentarlo, "
                "o dile al usuario que ha fallado; nunca digas que está hecho."), True
