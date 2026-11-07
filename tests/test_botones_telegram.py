"""Los botones de confirmación de Telegram, de punta a punta (con objetos falsos de Telegram)."""

from types import SimpleNamespace

import pytest

from jarvis import movil, pc, telefono
from jarvis.memory import MemoryStore
from jarvis.telegram_bot import JarvisTelegram

YO = 123


class FalsoQuery:
    def __init__(self, data):
        self.data = data
        self.textos = []

    async def answer(self, *a, **k):
        pass

    async def edit_message_text(self, texto, *a, **k):
        self.textos.append(texto)

    async def edit_message_reply_markup(self, *a, **k):
        pass


def _update(data, user_id=YO):
    q = FalsoQuery(data)
    return SimpleNamespace(callback_query=q, effective_user=SimpleNamespace(id=user_id)), q


@pytest.fixture
def bot():
    b = SimpleNamespace(memory=MemoryStore(), permitidos=frozenset({YO}))
    yield b
    b.memory.close()


async def test_boton_si_de_mensaje_del_movil_lo_envia(bot, monkeypatch):
    enviados = []
    monkeypatch.setattr(movil, "ejecutar_accion", lambda d: enviados.append(d) or "Mensaje enviado.")
    aid = bot.memory.create_action("movil", {"accion": "mensaje", "app": "sms", "numero": "+34600123456",
                                             "texto": "hola"}, "mandar un SMS")
    update, q = _update(f"acc:{aid}:si")
    await JarvisTelegram.boton_accion(bot, update, None)
    assert len(enviados) == 1
    assert bot.memory.get_action(aid)["estado"] == "hecha"
    assert any("Mensaje enviado" in t for t in q.textos)


async def test_boton_no_cancela(bot, monkeypatch):
    monkeypatch.setattr(pc, "ejecutar_accion", lambda d: pytest.fail("no debe ejecutar"))
    aid = bot.memory.create_action("pc", {"accion": "apagar"}, "apagar el PC")
    update, q = _update(f"pc:{aid}:no")
    await JarvisTelegram.boton_accion(bot, update, None)
    assert bot.memory.get_action(aid)["estado"] == "cancelada"


async def test_boton_de_otra_persona_no_hace_nada(bot, monkeypatch):
    monkeypatch.setattr(pc, "ejecutar_accion", lambda d: pytest.fail("no debe ejecutar"))
    aid = bot.memory.create_action("pc", {"accion": "apagar"}, "apagar el PC")
    update, q = _update(f"pc:{aid}:si", user_id=999)
    await JarvisTelegram.boton_accion(bot, update, None)
    assert bot.memory.get_action(aid)["estado"] == "pendiente"


async def test_boton_llamar_inicia_la_llamada(bot, monkeypatch):
    lanzadas = []

    async def iniciar(ll):
        lanzadas.append(ll)
    monkeypatch.setattr(telefono, "iniciar_llamada", iniciar)
    cid = bot.memory.create_call("Mamá", "+34600123456", "que llego tarde")
    update, q = _update(f"llamar:{cid}")
    await JarvisTelegram.boton_llamada(bot, update, None)
    assert len(lanzadas) == 1 and bot.memory.get_call(cid)["estado"] == "marcando"
    # Pulsar otra vez no vuelve a llamar
    update, q = _update(f"llamar:{cid}")
    await JarvisTelegram.boton_llamada(bot, update, None)
    assert len(lanzadas) == 1
