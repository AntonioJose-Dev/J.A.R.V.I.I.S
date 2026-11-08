"""«Jarvis, para»: parada de emergencia."""

import asyncio
import sqlite3

import pytest

from jarvis import parada
from jarvis.memory import MemoryStore


@pytest.mark.parametrize("frase, es", [
    ("Jarvis, para", True), ("para", True), ("¡Para!", True), ("Jarvis para ya", True), ("detente", True),
    ("Cancela todo", True), ("stop", True), ("Oye Jarvis, para todo", True),
    ("Para mañana pon una alarma", False), ("¿Para qué sirve esto?", False), ("Para el coche en la gasolinera", False),
])
def test_reconoce_la_orden(frase, es):
    assert parada.es_parada(frase) is es


def test_cancela_lo_pendiente(tmp_path, monkeypatch):
    ruta = tmp_path / "m.db"
    monkeypatch.setenv("JARVIS_MEMORY_PATH", str(ruta))
    m = MemoryStore(ruta)
    m.create_action("movil", {"accion": "mensaje"}, "mandar un WhatsApp")
    m.create_call("Mamá", "+34600123456", "hola")
    m.close()
    from jarvis import app_movil

    app_movil.encargar("whatsapp", {"numero": "+34600123456", "texto": "hola"})
    r = parada.cancelar_pendientes()
    assert r == {"acciones": 1, "llamadas": 1, "movil": 1}
    assert app_movil._siguiente_trabajo(True) is None  # el móvil ya no lo recibe
    db = sqlite3.connect(ruta)
    assert db.execute("SELECT status FROM actions").fetchone()[0] == "cancelada"
    db.close()
    assert "cancelado 2 confirmación(es)" in parada.resumen(r, 0, 1) and "dejado lo que estaba haciendo" in parada.resumen(r, 0, 1)


async def test_para_corta_lo_que_esta_haciendo(monkeypatch, tmp_path):
    monkeypatch.setenv("JARVIS_MEMORY_PATH", str(tmp_path / "m.db"))
    MemoryStore(tmp_path / "m.db").close()
    from jarvis import telegram_bot

    async def lento(*a, **k):
        await asyncio.sleep(30)
        return "terminado"
    monkeypatch.setattr(telegram_bot, "responder", lento)

    async def sin_llamadas():
        return 0
    monkeypatch.setattr(parada, "colgar_llamadas", sin_llamadas)
    bot = telegram_bot.JarvisTelegram.__new__(telegram_bot.JarvisTelegram)
    bot.memory, bot.cerebro, bot.historiales = MemoryStore(), None, {}
    bot.jarvis_por_chat, bot.cerrojos, bot.en_curso = {1: type("J", (), {})()}, {}, {}
    pensando = asyncio.create_task(bot.pensar(1, "haz algo largo"))
    await asyncio.sleep(0.1)
    aviso = await bot.parar(1)
    assert await asyncio.wait_for(pensando, 2) == "Parado, señor." and "dejado lo que estaba haciendo" in aviso
