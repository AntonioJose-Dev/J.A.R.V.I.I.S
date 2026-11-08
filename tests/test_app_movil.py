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
    estado_, motivo = app_movil.esperar_resultado(tid, 0.6)
    assert estado_ == "sin_respuesta" and "no llegó al móvil" in motivo


def test_entrega_perdida_se_reentrega_solo_si_la_app_acusa_recibo(monkeypatch):
    reloj = [1000.0]
    monkeypatch.setattr(app_movil.time, "time", lambda: reloj[0])
    tid = app_movil.encargar("whatsapp", {"numero": "+34600123456", "texto": "hola"})
    assert app_movil._siguiente_trabajo(True)["id"] == tid   # entrega que se pierde por el camino
    reloj[0] += 3
    assert app_movil._siguiente_trabajo(True) is None         # aún dentro del plazo del acuse
    reloj[0] += app_movil.ACUSE_EN
    assert app_movil._siguiente_trabajo(False) is None        # app antigua (sin acuses): nunca dos veces
    assert app_movil._siguiente_trabajo(True)["id"] == tid    # app 1.7+: se le vuelve a entregar
    app_movil._guardar_resultado(tid, "recibido", "")
    reloj[0] += 30
    assert app_movil._siguiente_trabajo(True) is None         # con acuse ya no se reentrega


def test_recibido_y_ultimo_paso_explican_un_atasco():
    tid = app_movil.encargar("whatsapp", {"numero": "+34600123456", "texto": "hola"})
    app_movil._siguiente_trabajo(True)
    app_movil._guardar_resultado(tid, "recibido", "")
    app_movil._guardar_paso(tid, "WhatsApp abierto en pantalla")
    estado_, motivo = app_movil.esperar_resultado(tid, 0.6)
    assert estado_ == "sin_respuesta" and "WhatsApp abierto en pantalla" in motivo


def test_movil_bloqueado_avisa_y_espera_mas(monkeypatch):
    avisos = []
    monkeypatch.setattr(app_movil, "avisar_desbloqueo", lambda: avisos.append(1))
    monkeypatch.setattr(app_movil, "ESPERA_DESBLOQUEO", 2.5)
    tid = app_movil.encargar("whatsapp", {"numero": "+34600123456", "texto": "hola"})
    app_movil._siguiente_trabajo(True)
    app_movil._guardar_resultado(tid, "recibido", "")
    app_movil._guardar_paso(tid, "esperando desbloqueo del móvil")

    def desbloquea_y_envia():
        import time
        time.sleep(1.5)  # más que la espera normal (1 s): sin la ampliación se daría por fallido
        app_movil._guardar_resultado(tid, "enviado", "WhatsApp enviado")
    threading.Thread(target=desbloquea_y_envia).start()
    assert app_movil.esperar_resultado(tid, 1) == ("enviado", "WhatsApp enviado")


async def test_paso_de_bloqueo_avisa_por_telegram(monkeypatch):
    avisos = []
    monkeypatch.setattr(app_movil, "avisar_desbloqueo", lambda: avisos.append(1))
    c = await _cliente()
    tid = app_movil.encargar("whatsapp", {"numero": "+34600123456", "texto": "hola"})
    await c.post("/app/hola", json={"id": tid, "paso": "esperando desbloqueo del móvil"}, headers={"X-Jarvis-Token": TOKEN})
    assert avisos == [1]
    await c.close()


def test_lo_que_cuenta_la_app_no_guarda_los_mensajes_de_los_chats():
    paso = ("mientras grabo: [voice_note_info|0:00||[1,2][3,4]] [message_text|Mi secreto jaja||[5,6][7,8]] "
            "[main_layout||Alvita, mensaje de voz, 6 segundos, 13:33|[1,1][2,2]] [single_msg_tv|Te quiero|]")
    limpio = app_movil.privado(paso)
    assert "secreto" not in limpio and "Te quiero" not in limpio and "Alvita" not in limpio
    assert "voice_note_info|0:00" in limpio and "message_text|(oculto)" in limpio


def test_leer_chat_devuelve_los_mensajes_y_no_los_deja_guardados():
    app_movil.guardar_estado(ultimo_contacto=__import__("time").time())
    chat = '[{"de":"el_otro","texto":"¿Vienes esta noche?","hora":"13:22"},{"de":"yo","texto":"jaja ya veremos","hora":"13:23"}]'

    def app_falsa():
        import time
        for _ in range(40):
            t = app_movil._siguiente_trabajo()
            if t:
                assert t["tipo"] == "leer_chat" and t["datos"] == {"numero": "+34600123456"}
                app_movil._guardar_resultado(t["id"], "leido", chat)
                return
            time.sleep(0.1)
    threading.Thread(target=app_falsa).start()
    mensajes = app_movil.leer_chat("+34600123456", 5)
    assert [m["texto"] for m in mensajes] == ["¿Vienes esta noche?", "jaja ya veremos"]
    db = app_movil._db()
    assert db.execute("SELECT resultado FROM app_trabajos").fetchall() == [(None,)]  # nada guardado
    db.close()


async def test_un_chat_leido_no_va_al_log(caplog):
    c = await _cliente()
    tid = app_movil.encargar("leer_chat", {"numero": "+34600123456"})
    app_movil._siguiente_trabajo(True)
    with caplog.at_level("INFO"):
        await c.post("/app/resultado", json={"id": tid, "estado": "leido", "detalle": '[{"texto":"secreto"}]'},
                     headers={"X-Jarvis-Token": TOKEN})
    assert "secreto" not in caplog.text and "chat leído" in caplog.text
    await c.close()


def test_un_acuse_tardio_no_pisa_el_resultado():
    tid = app_movil.encargar("whatsapp", {"numero": "+34600123456", "texto": "hola"})
    app_movil._siguiente_trabajo(True)
    app_movil._guardar_resultado(tid, "enviado", "WhatsApp enviado")
    app_movil._guardar_resultado(tid, "recibido", "")
    assert app_movil.esperar_resultado(tid, 0.6) == ("enviado", "WhatsApp enviado")


async def test_la_app_cuenta_sus_pasos():
    c = await _cliente()
    tid = app_movil.encargar("whatsapp", {"numero": "+34600123456", "texto": "hola"})
    r = await c.post("/app/hola", json={"id": tid, "paso": "pedí abrir el chat"}, headers={"X-Jarvis-Token": TOKEN})
    assert r.status == 200
    db = app_movil._db()
    assert db.execute("SELECT paso FROM app_trabajos WHERE id=?", (tid,)).fetchone()[0] == "pedí abrir el chat"
    db.close()
    await c.close()


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


def test_audio_de_whatsapp_se_prepara_con_su_texto():
    datos, desc = movil.preparar_mensaje("whatsapp", "madre", "+34600123456", "Llego a las 8", audio=True)
    assert datos["audio"] is True and datos["formato"] == "nota" and "NOTA DE VOZ" in desc and "«Llego a las 8»" in desc
    datos, desc = movil.preparar_mensaje("whatsapp", "madre", "+34600123456", "Hola", audio=True, como_archivo=True)
    assert datos["formato"] == "archivo" and "AUDIO (archivo)" in desc
    with pytest.raises(ValueError, match="solo"):
        movil.preparar_mensaje("sms", "madre", "+34600123456", "hola", audio=True)


def test_audio_va_a_la_app_con_su_huella_y_se_comprueba(monkeypatch, tmp_path):
    from jarvis import audio

    monkeypatch.setattr(audio, "CARPETA", tmp_path / "audios")
    monkeypatch.setattr(audio, "generar", lambda texto: audio.guardar(b"OggS-audio-de-prueba"))
    app_movil.guardar_estado(ultimo_contacto=__import__("time").time())
    vistos = {}

    def app_falsa():
        import time
        for _ in range(40):
            t = app_movil._siguiente_trabajo()
            if t:
                vistos.update(t)
                app_movil._guardar_resultado(t["id"], "enviado", "Audio enviado")
                return
            time.sleep(0.1)
    threading.Thread(target=app_falsa).start()
    r = movil.ejecutar_accion({"accion": "mensaje", "app": "whatsapp", "numero": "+34600123456",
                               "texto": "Llego a las 8", "audio": True})
    assert "Audio" in r and vistos["tipo"] == "whatsapp_audio"
    import hashlib
    assert vistos["datos"]["sha256"] == hashlib.sha256(b"OggS-audio-de-prueba").hexdigest()
    assert "texto" not in vistos["datos"]  # al móvil solo le llega el audio, no hace falta más


async def test_el_audio_solo_se_entrega_si_hay_un_encargo_en_marcha(monkeypatch, tmp_path):
    from jarvis import audio

    monkeypatch.setattr(audio, "CARPETA", tmp_path / "audios")
    huella = audio.guardar(b"OggS-123")
    app = web.Application()
    app.add_routes([web.post("/app/audio", app_movil._audio)])
    c = TestClient(TestServer(app))
    await c.start_server()
    h = {"X-Jarvis-Token": TOKEN}
    assert (await c.post("/app/audio", json={"sha256": huella})).status == 401          # sin código
    assert (await c.post("/app/audio", json={"sha256": huella}, headers=h)).status == 404  # sin encargo
    app_movil.encargar("whatsapp_audio", {"numero": "+34600123456", "sha256": huella})
    app_movil._siguiente_trabajo(True)
    r = await c.post("/app/audio", json={"sha256": huella}, headers=h)
    assert r.status == 200 and await r.read() == b"OggS-123"
    assert (await c.post("/app/audio", json={"sha256": "../../.env"}, headers=h)).status == 404
    await c.close()


def test_sin_app_no_hay_audio(monkeypatch):
    with pytest.raises(RuntimeError, match="NO se ha enviado el audio"):
        movil.ejecutar_accion({"accion": "mensaje", "app": "whatsapp", "numero": "+34600123456",
                               "texto": "hola", "audio": True})


def test_sin_app_ni_adb_no_se_envia(monkeypatch):
    monkeypatch.setattr(movil, "dispositivos_seguro", lambda: [])
    with pytest.raises(RuntimeError, match="NO se ha enviado"):
        movil.ejecutar_accion({"accion": "mensaje", "app": "whatsapp", "numero": "+34600123456", "texto": "hola"})
