import pytest

from jarvis import cerebros
from jarvis.core import Jarvis
from jarvis.memory import MemoryStore


def test_orden_de_preferencia():
    env = {"GROQ_API_KEY": "g", "GEMINI_API_KEY": "m", "MISTRAL_API_KEY": "x", "CEREBRAS_API_KEY": "c"}
    assert cerebros.disponibles(env) == ["gemini", "mistral", "cerebras", "groq", "groq_qwen"]
    assert cerebros.disponibles({**env, "ANTHROPIC_API_KEY": "a"})[0] == "claude"
    assert cerebros.disponibles({"GROQ_API_KEY": " "}) == []


def test_elige_el_mejor_modelo_de_gemini():
    ids = ["models/gemini-2.5-flash", "models/gemini-3.0-flash", "models/gemini-3.0-flash-lite",
           "models/gemini-3.0-pro", "models/text-embedding-004", "models/gemini-3.0-flash-image"]
    assert cerebros.elegir_modelo(cerebros.POR_NOMBRE["gemini"], ids) == "gemini-3.0-flash"


def test_mistral_y_cerebras_y_groq():
    assert cerebros.elegir_modelo(cerebros.POR_NOMBRE["mistral"],
                                  ["mistral-small-latest", "mistral-medium-latest", "codestral-latest"]) == "mistral-medium-latest"
    assert cerebros.elegir_modelo(cerebros.POR_NOMBRE["cerebras"], ["llama3.1-8b", "gpt-oss-120b"]) == "gpt-oss-120b"
    assert cerebros.elegir_modelo(cerebros.POR_NOMBRE["groq"], ["openai/gpt-oss-120b", "qwen/qwen3.8-27b"]) == "openai/gpt-oss-120b"


def test_si_no_hay_ninguno_conocido_usa_el_de_defecto():
    assert cerebros.elegir_modelo(cerebros.POR_NOMBRE["gemini"], ["otro-modelo"]) == "gemini-2.5-flash"


def test_modelo_fijado_a_mano(monkeypatch):
    monkeypatch.setenv("JARVIS_MISTRAL_MODEL", "mistral-large-latest")
    assert cerebros.modelo_de(cerebros.POR_NOMBRE["mistral"]) == "mistral-large-latest"


@pytest.mark.parametrize("texto, esperados, no_esperados", [
    ("¿Qué hora es?", {"basicas"}, {"pc", "movil", "llamadas"}),
    ("Abre Brave", {"pc"}, {"movil"}),
    ("Sube el volumen del móvil", {"movil"}, {"pc"}),
    ("Abre WhatsApp en el móvil", {"movil"}, {"pc"}),
    ("Llama a mamá y dile que llego tarde", {"llamadas"}, {"pc"}),
    ("Mándale un WhatsApp a Carlos", {"movil"}, set()),
    ("¿Dónde está mi móvil?", {"movil"}, set()),
    ("Apaga el ordenador", {"pc"}, {"movil"}),
    ("Recuerda que mi madre se llama Carmen", {"basicas"}, {"pc", "movil"}),
])
def test_grupos_de_herramientas(texto, esperados, no_esperados):
    g = cerebros.grupos_para(texto)
    assert esperados <= g and not (no_esperados & g)


@pytest.mark.parametrize("texto, va_al_movil", [
    ("Abre YouTube", True),
    ("Sube el volumen", True),
    ("Pon música", True),
    ("Busca en Google el tiempo", True),
    ("Abre YouTube en el PC", False),
    ("Abre Brave en el ordenador", False),
    ("¿Cómo está el portátil?", False),
])
def test_desde_el_movil_lo_ambiguo_va_al_movil(texto, va_al_movil):
    g = cerebros.grupos_para(texto, preferir_movil=True)
    assert ("movil" in g and "pc" not in g) if va_al_movil else ("pc" in g)


def test_desde_el_movil_no_arrastra_el_pc_del_turno_anterior():
    g = cerebros.grupos_para("abre youtube", {"pc"}, preferir_movil=True)
    assert "pc" not in g and "movil" in g


def test_desde_el_pc_abre_sigue_siendo_el_pc():
    assert "pc" in cerebros.grupos_para("Abre YouTube")


@pytest.mark.parametrize("texto", ["Escríbele a mamá que llego tarde", "Mándale un mensaje a Juan",
                                   "Envíale un whatsapp a Carlos", "Dile por WhatsApp a Ana que sí"])
def test_mensajes_escritos_van_al_movil_y_no_al_teclado_del_pc(texto):
    g = cerebros.grupos_para(texto)  # también desde el PC
    assert "movil" in g and "pc" not in g


def test_llamar_no_arrastra_los_mensajes_del_turno_anterior():
    g = cerebros.grupos_para("Llama a José y dile que llego tarde", {"movil"})
    assert "llamadas" in g and "movil" not in g


def test_sigue_el_hilo_del_turno_anterior():
    # "busca el archivo factura" (pc) y luego "mándamelo": el grupo pc se mantiene
    assert "pc" in cerebros.grupos_para("vale, ese", cerebros.grupos_de_herramientas({"buscar_archivo"}))


def test_todas_las_herramientas_estan_en_algun_grupo():
    m = MemoryStore()
    todas = {t.info.name for t in Jarvis(m).tools}
    m.close()
    agrupadas = set().union(*cerebros.GRUPOS.values())
    assert todas == agrupadas, f"sin grupo: {todas - agrupadas}; sobran: {agrupadas - todas}"


def test_un_mensaje_simple_lleva_pocas_herramientas():
    assert len(cerebros.herramientas_de(cerebros.grupos_para("¿qué tal estás?"))) == 4
