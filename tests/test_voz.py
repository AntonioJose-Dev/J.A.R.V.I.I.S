"""JARVIS debe sonar igual en todas partes: llamadas, voz del PC y notas de Telegram."""

import inspect

from livekit.plugins import elevenlabs

from jarvis import llamadas, telegram_bot
from jarvis.config import Plan
from jarvis.core import MODELO_ELEVEN, crear_voz, describir_voz

DANIEL = "onwK4e9ZLuTAKqWW03F9"
PLAN = Plan("groq", "elevenlabs")


def _opts(tts):
    tts = getattr(tts, "_tts_instances", [tts])[0]  # la principal (la de reserva va detrás)
    tts = getattr(tts, "_wrapped_tts", tts)  # los v4 van envueltos frase a frase
    return tts._opts.voice_id, tts._opts.model


def test_misma_voz_y_modelo_en_todos_los_canales(monkeypatch):
    monkeypatch.setenv("ELEVEN_VOICE_ID", DANIEL)
    monkeypatch.delenv("ELEVEN_MODEL", raising=False)
    # Todos los canales construyen la voz con crear_voz(plan): mismo voice_id y mismo modelo
    voces = {_opts(crear_voz(PLAN)) for _ in range(3)}
    assert voces == {(DANIEL, MODELO_ELEVEN)}
    assert isinstance(crear_voz(PLAN)._tts_instances[0]._wrapped_tts, elevenlabs.TTS)


def test_v4_va_frase_a_frase_sin_conexion_que_caduque(monkeypatch):
    from livekit.agents import tts

    monkeypatch.setenv("ELEVEN_VOICE_ID", DANIEL)
    monkeypatch.delenv("ELEVEN_MODEL", raising=False)
    assert isinstance(crear_voz(PLAN)._tts_instances[0], tts.StreamAdapter)
    monkeypatch.setenv("ELEVEN_MODEL", "eleven_flash_v2_5")
    assert isinstance(crear_voz(PLAN)._tts_instances[0], elevenlabs.TTS)


def test_los_canales_usan_crear_voz_y_no_otra_cosa():
    assert "crear_voz(" in inspect.getsource(llamadas.entrypoint)
    assert "crear_voz(" in inspect.getsource(telegram_bot.JarvisTelegram.hablar)
    assert "api.elevenlabs.io" not in inspect.getsource(telegram_bot)  # ninguna vía paralela


def test_modelo_rapido_de_la_familia_v4_por_defecto():
    assert MODELO_ELEVEN == "eleven_v4_turbo"


def test_describir_voz_para_el_log(monkeypatch):
    monkeypatch.setenv("ELEVEN_VOICE_ID", DANIEL)
    assert DANIEL in describir_voz(PLAN) and "eleven_v4_turbo" in describir_voz(PLAN)


def test_si_elevenlabs_falla_hay_voz_de_reserva(monkeypatch):
    from livekit.agents import tts
    from livekit.plugins import deepgram

    monkeypatch.setenv("ELEVEN_VOICE_ID", DANIEL)
    v = crear_voz(PLAN)
    assert isinstance(v, tts.FallbackAdapter) and isinstance(v._tts_instances[1], deepgram.TTS)

