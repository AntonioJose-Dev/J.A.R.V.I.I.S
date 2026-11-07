"""Elige qué cerebro y qué voz usa JARVIS según las claves disponibles.

Cerebro (en este orden):
- Claude (Anthropic) si hay ANTHROPIC_API_KEY.
- Groq (gratis, modelo Llama en la nube) si hay GROQ_API_KEY.
- Gemini (capa gratuita de Google) si hay GEMINI_API_KEY.

Voz: ElevenLabs si hay ELEVEN_API_KEY; si no, Deepgram Aura (misma clave que el oído).

JARVIS_MODO lo fuerza:
- "auto" (por defecto): decide cada pieza según las claves.
- "prueba": cerebro gratuito (Groq o Gemini) + voz de Deepgram, aunque haya otras claves.
- "completo": Claude + ElevenLabs; falla si falta alguna clave.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

MODOS = ("auto", "prueba", "completo")
NOMBRES = {
    "claude": "Claude",
    "groq": "Groq (gratis)",
    "gemini": "Gemini (gratis)",
    "elevenlabs": "ElevenLabs",
    "deepgram": "Deepgram Aura",
}


@dataclass(frozen=True)
class Plan:
    cerebro: str  # "claude" | "groq" | "gemini"
    voz: str  # "elevenlabs" | "deepgram"

    def describir(self) -> str:
        return f"cerebro={NOMBRES[self.cerebro]}, voz={NOMBRES[self.voz]}"


def _tiene(env: Mapping[str, str], clave: str) -> bool:
    return bool(env.get(clave, "").strip())


def _cerebro_gratuito(env: Mapping[str, str]) -> str:
    if _tiene(env, "GROQ_API_KEY"):
        return "groq"
    if _tiene(env, "GEMINI_API_KEY"):
        return "gemini"
    raise ValueError(
        "JARVIS no tiene cerebro: pon en .env ANTHROPIC_API_KEY, o una clave gratuita "
        "GROQ_API_KEY (console.groq.com) o GEMINI_API_KEY (aistudio.google.com)."
    )


def elegir_plan(env: Mapping[str, str]) -> Plan:
    modo = env.get("JARVIS_MODO", "auto").strip().lower() or "auto"
    if modo not in MODOS:
        raise ValueError(f"JARVIS_MODO debe ser uno de {MODOS}, no {modo!r}")

    if modo == "prueba":
        return Plan(_cerebro_gratuito(env), "deepgram")

    if modo == "completo":
        faltan = [k for k in ("ANTHROPIC_API_KEY", "ELEVEN_API_KEY") if not _tiene(env, k)]
        if faltan:
            raise ValueError(f"JARVIS_MODO=completo pero faltan en .env: {', '.join(faltan)}")
        return Plan("claude", "elevenlabs")

    return Plan(
        cerebro="claude" if _tiene(env, "ANTHROPIC_API_KEY") else _cerebro_gratuito(env),
        voz="elevenlabs" if _tiene(env, "ELEVEN_API_KEY") else "deepgram",
    )
