"""Voz en directo desde el móvil: las confirmaciones habladas no se pueden saltar."""

import pytest
from livekit.agents import llm

from jarvis import pc, telefono
from jarvis.memory import MemoryStore
from jarvis.telegram_bot import decidir, tipo_de_mensaje
from jarvis.voz import JarvisVoz, es_un_si


@pytest.mark.parametrize("frase, esperado", [
    ("Sí", True), ("sí, envíalo", True), ("vale, dale", True), ("Adelante", True), ("claro que sí", True),
    ("No", False), ("no, espera", False), ("sí... no, mejor no", False), ("¿qué hora es?", False), ("", False),
])
def test_es_un_si(frase, esperado):
    assert es_un_si(frase) is esperado


def _turno(agente, texto):
    msg = llm.ChatMessage(role="user", content=[texto])
    return agente.on_user_turn_completed(llm.ChatContext(), msg)


@pytest.fixture
def memoria():
    m = MemoryStore()
    yield m
    m.close()


async def test_no_se_puede_confirmar_sin_que_el_usuario_hable(memoria, monkeypatch):
    ejecutadas = []
    monkeypatch.setattr(pc, "ejecutar_accion", lambda d: ejecutadas.append(d) or "hecho")
    j = JarvisVoz(memoria)
    j.update_tools = _sin_efecto
    await _turno(j, "apaga el ordenador")
    r = await j.accion_pc_delicada(None, accion="apagar")
    assert "PENDIENTE" in r and "de viva voz" in r
    # El cerebro intenta confirmar él solo, sin que el usuario haya contestado: no vale
    assert "todavía no ha dicho" in await j.confirmar_pendiente(None, confirmar=True)
    assert ejecutadas == []
    # El usuario contesta algo que no es un sí: tampoco
    await _turno(j, "mmm no sé")
    assert "todavía no ha dicho" in await j.confirmar_pendiente(None, confirmar=True)
    assert ejecutadas == []
    # Ahora sí
    await _turno(j, "sí, apágalo")
    assert await j.confirmar_pendiente(None, confirmar=True) == "hecho"
    assert ejecutadas == [{"accion": "apagar"}]
    # Y no se puede repetir
    assert "No hay nada pendiente" in await j.confirmar_pendiente(None, confirmar=True)


async def test_cancelar_por_voz(memoria):
    j = JarvisVoz(memoria)
    j.update_tools = _sin_efecto
    await _turno(j, "apaga el ordenador")
    await j.accion_pc_delicada(None, accion="apagar")
    await _turno(j, "no, déjalo")
    assert await j.confirmar_pendiente(None, confirmar=False) == "Cancelado."
    assert memoria.get_action(1)["estado"] == "cancelada"


async def test_llamada_confirmada_por_voz(memoria, monkeypatch):
    monkeypatch.setenv("LIVEKIT_URL", "wss://x.livekit.cloud")
    monkeypatch.setenv("LIVEKIT_API_KEY", "k")
    monkeypatch.setenv("LIVEKIT_API_SECRET", "s")
    monkeypatch.setenv("LIVEKIT_SIP_TRUNK_ID", "ST_x")
    lanzadas = []

    async def iniciar(ll):
        lanzadas.append(ll)
    monkeypatch.setattr(telefono, "iniciar_llamada", iniciar)
    telefono.guardar_contacto(memoria, "Mamá", "600123456")
    j = JarvisVoz(memoria)
    j.update_tools = _sin_efecto
    await _turno(j, "llama a mamá y dile que llego tarde")
    await j.llamar(None, destino="mamá", mensaje="que llego tarde")
    assert lanzadas == []
    await _turno(j, "sí, llámala")
    assert "Llamando a Mamá" in await j.confirmar_pendiente(None, confirmar=True)
    assert len(lanzadas) == 1


def test_la_herramienta_de_confirmar_solo_existe_en_la_voz(memoria):
    from jarvis.core import Jarvis

    assert "confirmar_pendiente" in {t.info.name for t in JarvisVoz(memoria).tools}
    assert "confirmar_pendiente" not in {t.info.name for t in Jarvis(memoria).tools}  # en Telegram: botones


def test_comando_hablar():
    assert tipo_de_mensaje("/hablar", False) == "hablar"
    assert decidir(1, frozenset({1}), "hablar") == "hablar"
    assert decidir(2, frozenset({1}), "hablar") == "ignorar"


async def _sin_efecto(*a, **k):
    return None
