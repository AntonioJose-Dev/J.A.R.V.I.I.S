"""Llamadas telefónicas: agenda, validación de números y confirmación por Telegram.

Una llamada nunca se hace directamente: la herramienta `llamar` crea una llamada
*pendiente* y manda a Telegram un mensaje con botones "Llamar" / "Cancelar".
Solo cuando el dueño pulsa "Llamar" el bot de Telegram la pone en marcha.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import secrets
import unicodedata
from datetime import datetime, timedelta, timezone

from .memory import MemoryStore
from .telegram_api import chat_del_dueno, telegram  # noqa: F401 (las usan llamadas.py y el bot)

log = logging.getLogger("jarvis.telefono")

# Prefijos permitidos por defecto: España y resto de la UE/EEE (se cambia con JARVIS_PREFIJOS_LLAMADA)
PREFIJOS_UE = (
    "+34", "+351", "+33", "+49", "+39", "+32", "+31", "+352", "+353", "+43", "+45", "+46", "+358",
    "+30", "+357", "+356", "+48", "+420", "+421", "+36", "+40", "+359", "+385", "+386", "+370",
    "+371", "+372", "+354", "+47", "+423",
)
CADUCIDAD_CONFIRMACION = timedelta(minutes=10)
VARIABLES_LLAMADAS = ("LIVEKIT_URL", "LIVEKIT_API_KEY", "LIVEKIT_API_SECRET", "LIVEKIT_SIP_TRUNK_ID")


# --- Números ---------------------------------------------------------------------------

def normalizar_numero(texto: str, prefijo_pais: str = "+34") -> str:
    """'600 12 34 56' -> '+34600123456'. Lanza ValueError si no parece un teléfono."""
    limpio = re.sub(r"[\s\-\.\(\)/]", "", texto or "")
    if limpio.startswith("00"):
        limpio = "+" + limpio[2:]
    if not limpio.startswith("+"):
        # Número nacional español: 9 cifras empezando por 6, 7, 8 o 9
        if re.fullmatch(r"[6789]\d{8}", limpio):
            limpio = prefijo_pais + limpio
        else:
            raise ValueError(f"'{texto}' no parece un número de teléfono")
    if not re.fullmatch(r"\+\d{8,15}", limpio):
        raise ValueError(f"'{texto}' no parece un número de teléfono")
    return limpio


def prefijos_permitidos() -> tuple[str, ...]:
    valor = os.getenv("JARVIS_PREFIJOS_LLAMADA", "").strip()
    if not valor:
        return PREFIJOS_UE
    return tuple(p.strip() if p.strip().startswith("+") else "+" + p.strip() for p in valor.split(",") if p.strip())


def numero_permitido(numero: str, prefijos: tuple[str, ...] | None = None) -> bool:
    return numero.startswith(tuple(prefijos or prefijos_permitidos()))


# --- Agenda ----------------------------------------------------------------------------

_ARTICULOS = re.compile(r"^(a |al |a la |a mi |mi |el |la |los |las )+")


def clave_nombre(nombre: str) -> str:
    """'A mi Mamá' -> 'mama'."""
    sin_tildes = unicodedata.normalize("NFKD", nombre).encode("ascii", "ignore").decode()
    clave = re.sub(r"\s+", " ", sin_tildes.lower()).strip()
    return _ARTICULOS.sub("", clave).strip()


def guardar_contacto(memory: MemoryStore, nombre: str, numero: str) -> str:
    e164 = normalizar_numero(numero)
    memory.save_contact(clave_nombre(nombre), nombre.strip(), e164)
    return e164


def buscar_contacto(memory: MemoryStore, nombre: str) -> tuple[str, str] | None:
    clave = clave_nombre(nombre)
    if not clave:
        return None
    contactos = memory.contacts()
    for k, n, num in contactos:
        if k == clave:
            return n, num
    parecidos = [(n, num) for k, n, num in contactos if clave in k or k in clave]
    return parecidos[0] if len(parecidos) == 1 else None


def resolver_destino(memory: MemoryStore, destino: str) -> tuple[str, str]:
    """Devuelve (nombre, número E.164) a partir de un nombre de la agenda o de un número."""
    if re.search(r"\d{6,}", re.sub(r"[\s\-\.]", "", destino)):
        numero = normalizar_numero(destino)
        conocido = next((n for _, n, num in memory.contacts() if num == numero), None)
        return conocido or numero, numero
    encontrado = buscar_contacto(memory, destino)
    if not encontrado:
        raise LookupError(f"No tengo a '{destino}' en la agenda")
    return encontrado


# --- Configuración y confirmación --------------------------------------------------------

def llamadas_configuradas() -> list[str]:
    """Variables que faltan para poder llamar (vacía si está todo)."""
    faltan = [v for v in VARIABLES_LLAMADAS if not os.getenv(v, "").strip()]
    if os.getenv("LIVEKIT_URL", "").strip().startswith(("ws://localhost", "ws://127.0.0.1")):
        faltan.append("LIVEKIT_URL (debe ser tu proyecto de LiveKit Cloud, no localhost)")
    return faltan


def caducada(llamada: dict, ahora: datetime | None = None) -> bool:
    creada = datetime.fromisoformat(llamada["creada"])
    return (ahora or datetime.now(timezone.utc)) - creada > CADUCIDAD_CONFIRMACION


def texto_confirmacion(llamada: dict) -> str:
    return (
        f"📞 ¿Llamo a {llamada['nombre']} ({llamada['numero']})?\n\n"
        f"Le diré: «{llamada['mensaje']}»\n\n"
        "Me presentaré como su asistente de inteligencia artificial. Esta confirmación caduca en 10 minutos."
    )


async def pedir_confirmacion_telegram(llamada: dict) -> None:
    chat = chat_del_dueno()
    if chat is None:
        raise RuntimeError("Falta TELEGRAM_ALLOWED_IDS")
    await asyncio.to_thread(  # en segundo plano: no bloquea al bot ni a la voz mientras Telegram responde
        telegram,
        "sendMessage",
        chat_id=chat,
        text=texto_confirmacion(llamada),
        reply_markup={"inline_keyboard": [[
            {"text": "✅ Llamar", "callback_data": f"llamar:{llamada['id']}"},
            {"text": "❌ Cancelar", "callback_data": f"cancelar:{llamada['id']}"},
        ]]},
    )


# --- Poner en marcha la llamada ----------------------------------------------------------

async def iniciar_llamada(llamada: dict) -> str:
    """Envía al agente de llamadas (jarvis.llamadas) a una sala nueva para que marque. Devuelve la sala."""
    from livekit import api

    from .llamadas import NOMBRE_AGENTE

    sala = f"llamada-{llamada['id']}-{secrets.token_hex(3)}"
    datos = {**llamada, "chat_id": chat_del_dueno()}
    async with api.LiveKitAPI() as lk:
        await lk.agent_dispatch.create_dispatch(
            api.CreateAgentDispatchRequest(agent_name=NOMBRE_AGENTE, room=sala, metadata=json.dumps(datos))
        )
    log.info("Llamada %s enviada a la sala %s", llamada["id"], sala)
    return sala
