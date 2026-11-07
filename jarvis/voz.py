"""JARVIS por voz en directo desde el móvil (Mini App de Telegram + LiveKit).

- El bot crea una sala, manda allí al agente de voz y te da un enlace con un permiso de un solo uso.
- La página (docs/index.html, en GitHub Pages) abre el micrófono y conversas en directo.
- Las acciones delicadas se confirman de viva voz: JARVIS pregunta y solo las hace si tu última
  frase fue un "sí" (lo comprueba el programa, no solo el cerebro).
"""

from __future__ import annotations

import asyncio
import os
import re
import secrets
import unicodedata
from datetime import timedelta
from urllib.parse import urlencode

from livekit import api
from livekit.agents import RunContext, function_tool, llm

from . import movil, pc, telefono
from .core import Jarvis, log

NOMBRE_AGENTE = "jarvis-voz"
URL_PAGINA = "https://antoniojose-dev.github.io/J.A.R.V.I.I.S/"
DURACION_PERMISO = timedelta(hours=2)

_SI = re.compile(r"\b(si|vale|dale|hazlo|adelante|confirmo|confirmado|envialo|mandalo|llama|llamale|claro|ok|okay"
                 r"|de acuerdo|por supuesto|venga|correcto|eso es|exacto)\b")
_NO = re.compile(r"\b(no|cancela|cancelalo|espera|para|nada|mejor no|olvidalo)\b")


def _normalizar(texto: str) -> str:
    return unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode().lower()


def es_un_si(texto: str) -> bool:
    """¿La frase es una confirmación clara? ("sí, envíalo" sí; "no, espera" o "sí... no, mejor no" no)."""
    t = _normalizar(texto)
    return bool(_SI.search(t)) and not _NO.search(t)


class JarvisVoz(Jarvis):
    """JARVIS en una conversación de voz en directo: las confirmaciones se hacen hablando."""

    confirmacion_por_voz = True
    preferir_movil = True  # habla desde la Mini App de Telegram, en el móvil
    siempre_disponibles = frozenset({"confirmar_pendiente"})

    def __init__(self, memory) -> None:
        super().__init__(memory, pedir_confirmacion=self._pendiente_llamada,
                         pedir_confirmacion_pc=self._pendiente_accion)
        self._pedir_confirmacion_movil = self._pendiente_accion
        if isinstance(getattr(self, "_instructions", None), str):  # habla desde el móvil: que lo sepa siempre
            from .core import NOTA_MOVIL

            self._instructions = f"{self._instructions}\n\n{NOTA_MOVIL}"
        self._pendiente: tuple[str, dict, int] | None = None
        self._turno = 0
        self._ultima_frase = ""

    async def _pendiente_llamada(self, llamada: dict) -> None:
        self._pendiente = ("llamada", llamada, self._turno)

    async def _pendiente_accion(self, accion: dict) -> None:
        self._pendiente = ("accion", accion, self._turno)

    async def on_user_turn_completed(self, turn_ctx: llm.ChatContext, new_message: llm.ChatMessage) -> None:
        self._turno += 1
        self._ultima_frase = new_message.text_content or ""
        await super().on_user_turn_completed(turn_ctx, new_message)

    @function_tool
    async def confirmar_pendiente(self, context: RunContext, confirmar: bool) -> str:
        """Hace (o cancela) la acción que está pendiente de confirmar: llamada, mensaje o acción del PC.
        Úsala SOLO justo después de que el usuario haya respondido a tu pregunta de confirmación.

        Args:
            confirmar: true si el usuario ha dicho que sí; false si ha dicho que no.
        """
        if not self._pendiente:
            return "No hay nada pendiente de confirmar."
        tipo, datos, turno = self._pendiente
        if not confirmar:
            self._pendiente = None
            if tipo == "llamada":
                self.memory.set_call_status(datos["id"], "cancelada", only_if="pendiente")
            else:
                self.memory.set_action_status(datos["id"], "cancelada", only_if="pendiente")
            return "Cancelado."
        # La comprobación la hace el programa: el usuario tiene que haber hablado DESPUÉS y haber dicho que sí
        if self._turno <= turno or not es_un_si(self._ultima_frase):
            return "El usuario todavía no ha dicho claramente que sí. Pregúntaselo y espera su respuesta."
        self._pendiente = None
        if tipo == "llamada":
            if not self.memory.set_call_status(datos["id"], "marcando", only_if="pendiente"):
                return "Esa llamada ya no está pendiente."
            await telefono.iniciar_llamada(datos)
            return f"Llamando a {datos['nombre']}. Te contaré cómo ha ido por Telegram."
        if not self.memory.set_action_status(datos["id"], "ejecutando", only_if="pendiente"):
            return "Esa acción ya no está pendiente."
        ejecutor = movil.ejecutar_accion if datos["tipo"] == "movil" else pc.ejecutar_accion
        try:
            resultado = await asyncio.to_thread(ejecutor, datos["datos"])
            self.memory.set_action_status(datos["id"], "hecha")
            return resultado
        except Exception as e:  # noqa: BLE001
            self.memory.set_action_status(datos["id"], "fallida")
            return f"No se pudo: {type(e).__name__}."


async def crear_sesion(user_id: int, nombre: str = "Potro") -> str:
    """Crea una sala, envía allí a JARVIS y devuelve el enlace de la página con un permiso de un solo uso."""
    sala = f"voz-{user_id}-{secrets.token_hex(4)}"
    async with api.LiveKitAPI() as lk:
        await lk.agent_dispatch.create_dispatch(api.CreateAgentDispatchRequest(agent_name=NOMBRE_AGENTE, room=sala))
    permiso = (
        api.AccessToken(os.environ["LIVEKIT_API_KEY"].strip(), os.environ["LIVEKIT_API_SECRET"].strip())
        .with_identity(f"tg-{user_id}")
        .with_name(nombre)
        .with_grants(api.VideoGrants(room_join=True, room=sala, can_publish=True, can_subscribe=True,
                                     can_publish_data=False))
        .with_ttl(DURACION_PERMISO)
        .to_jwt()
    )
    url_lk = os.environ["LIVEKIT_URL"].strip()
    pagina = os.getenv("JARVIS_WEB_URL", "").strip() or URL_PAGINA
    log.info("Sesión de voz creada: sala %s", sala)
    return pagina + "#" + urlencode({"url": url_lk, "token": permiso})
