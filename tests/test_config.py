import pytest

from jarvis.config import Plan, elegir_plan

GROQ = {"GROQ_API_KEY": "g"}


def test_sin_ningun_cerebro_falla_con_mensaje_claro():
    with pytest.raises(ValueError, match="GROQ_API_KEY"):
        elegir_plan({})


def test_solo_groq_usa_groq_y_voz_de_deepgram():
    assert elegir_plan(GROQ) == Plan("groq", "deepgram")


def test_gemini_es_la_alternativa_a_groq():
    assert elegir_plan({"GEMINI_API_KEY": "m"}) == Plan("gemini", "deepgram")
    assert elegir_plan({**GROQ, "GEMINI_API_KEY": "m"}).cerebro == "groq"


def test_auto_elige_cada_pieza_por_separado():
    assert elegir_plan({**GROQ, "ELEVEN_API_KEY": "x"}) == Plan("groq", "elevenlabs")
    assert elegir_plan({"ANTHROPIC_API_KEY": "x"}) == Plan("claude", "deepgram")
    assert elegir_plan({"ANTHROPIC_API_KEY": "x", "ELEVEN_API_KEY": "y"}) == Plan("claude", "elevenlabs")


def test_clave_en_blanco_cuenta_como_vacia():
    assert elegir_plan({**GROQ, "ANTHROPIC_API_KEY": "  "}).cerebro == "groq"


def test_modo_prueba_ignora_claude_y_elevenlabs():
    env = {**GROQ, "JARVIS_MODO": "prueba", "ANTHROPIC_API_KEY": "x", "ELEVEN_API_KEY": "y"}
    assert elegir_plan(env) == Plan("groq", "deepgram")


def test_modo_completo_exige_claves():
    with pytest.raises(ValueError, match="ELEVEN_API_KEY"):
        elegir_plan({"JARVIS_MODO": "completo", "ANTHROPIC_API_KEY": "x"})


def test_modo_desconocido_falla():
    with pytest.raises(ValueError):
        elegir_plan({**GROQ, "JARVIS_MODO": "turbo"})
