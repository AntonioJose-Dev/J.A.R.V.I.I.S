"""Servidor del PC para la app JARVIS del móvil: código secreto, entrega de trabajos y resultados."""

import asyncio
import threading

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from jarvis import app_movil, movil

TOKEN = "t" * 43


@pytest.fixture(autouse=True)
def entorno(tmp_path, monkeypatch):
    monkeypatch.setenv("JARVIS_MEMORY_PATH", str(tmp_path / "m.db"))
    monkeypatch.setenv("JARVIS_APP_TOKEN", TOKEN)
    monkeypatch.setattr(app_movil, "ESPERA_LARGA", 2)


async def _cliente():
    app = web.Application()
    app.add_routes([web.post("/app/hola", app_movil._hola), web.post("/app/espera", app_movil._espera),
                    web.post("/app/resultado", app_movil._resultado)])
    c = TestClient(TestServer(app))
    await c.start_server()
    return c


async def test_sin_codigo_o_con_codigo_malo_no_entra():
    c = await _cliente()
    assert (await c.post("/app/hola", json={})).status == 401
    assert (await c.post("/app/espera", json={}, headers={"X-Jarvis-Token": "malo"})).status == 401
    assert app_movil.estado()["en_linea"] is False
    await c.close()


async def test_hola_marca_la_app_como_conectada_y_guarda_errores():
    c = await _cliente()
    r = await c.post("/app/hola", json={"version": "1.5", "error": "sin red"}, headers={"X-Jarvis-Token": TOKEN})
    assert r.status == 200
    e = app_movil.estado()
    assert e["en_linea"] is True and e["version"] == "1.5" and "sin red" in e["ultimo_error"]
    await c.close()


async def test_trabajo_completo_entrega_y_resultado():
    c = await _cliente()
    h = {"X-Jarvis-Token": TOKEN}
    assert (await c.post("/app/espera", json={}, headers=h)).status == 204  # nada pendiente
    tid = app_movil.encargar("whatsapp", {"numero": "+34600123456", "texto": "hola"})
    r = await c.post("/app/espera", json={}, headers=h)
    t = await r.json()
    assert t == {"id": tid, "tipo": "whatsapp", "datos": {"numero": "+34600123456", "texto": "hola"}}
    assert (await c.post("/app/espera", json={}, headers=h)).status == 204  # no se entrega dos veces
    await c.post("/app/resultado", json={"id": tid, "estado": "enviado", "detalle": "ok"}, headers=h)
    assert app_movil.esperar_resultado(tid, 2) == ("enviado", "ok")
    await c.close()


def test_sin_respuesta_de_la_app_no_es_exito(monkeypatch):
    tid = app_movil.encargar("whatsapp", {"numero": "+34600123456", "texto": "hola"})
    assert app_movil.esperar_resultado(tid, 0.6)[0] == "sin_respuesta"


def test_el_movil_usa_la_app_si_esta_conectada(monkeypatch):
    app_movil.guardar_estado(ultimo_contacto=__import__("time").time())

    def app_falsa():  # simula a la app: recoge el trabajo y dice que lo envió
        import time
        for _ in range(40):
            t = app_movil._siguiente_trabajo()
            if t:
                app_movil._guardar_resultado(t["id"], "enviado", "WhatsApp enviado")
                return
            time.sleep(0.1)
    threading.Thread(target=app_falsa).start()
    r = movil.ejecutar_accion({"accion": "mensaje", "app": "whatsapp", "numero": "+34600123456", "texto": "hola"})
    assert "comprobado" in r


def test_si_la_app_falla_se_dice_y_no_se_da_por_enviado(monkeypatch):
    app_movil.guardar_estado(ultimo_contacto=__import__("time").time())

    def app_falsa():
        import time
        for _ in range(40):
            t = app_movil._siguiente_trabajo()
            if t:
                app_movil._guardar_resultado(t["id"], "error", "WhatsApp no llegó a abrirse")
                return
            time.sleep(0.1)
    threading.Thread(target=app_falsa).start()
    with pytest.raises(RuntimeError, match="no llegó a abrirse"):
        movil.ejecutar_accion({"accion": "mensaje", "app": "whatsapp", "numero": "+34600123456", "texto": "hola"})


def test_sin_app_ni_adb_no_se_envia(monkeypatch):
    monkeypatch.setattr(movil, "dispositivos_seguro", lambda: [])
    with pytest.raises(RuntimeError, match="NO se ha enviado"):
        movil.ejecutar_accion({"accion": "mensaje", "app": "whatsapp", "numero": "+34600123456", "texto": "hola"})
