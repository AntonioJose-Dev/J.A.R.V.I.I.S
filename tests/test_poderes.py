"""Internet, recordatorios y visión."""

from datetime import datetime, timedelta

import httpx
import pytest

from jarvis import cerebros, internet, recordatorios, vision
from jarvis.recordatorios import TZ


# --- Internet: solo webs públicas --------------------------------------------------------------

@pytest.mark.parametrize("ip, publica", [
    ("8.8.8.8", True), ("192.168.1.1", False), ("10.0.0.5", False), ("127.0.0.1", False),
    ("100.78.85.68", False),  # Tailscale (el PC)
    ("169.254.169.254", False), ("::1", False), ("::ffff:192.168.1.1", False), ("basura", False),
])
def test_ip_publica(ip, publica):
    assert internet.ip_publica(ip) is publica


@pytest.mark.parametrize("url", [
    "http://192.168.1.1/", "http://100.78.85.68:8800/app/hola", "http://localhost:8080/", "file:///C:/Windows",
    "ftp://ejemplo.com/", "http://usuario:clave@ejemplo.com/", "http://pc.tail244485.ts.net/",
])
def test_direcciones_privadas_o_raras_se_rechazan(url):
    with pytest.raises(internet.NoPermitida):
        internet.comprobar_url(url)


def test_una_web_no_puede_redirigir_a_la_red_de_casa(monkeypatch):
    def resolver(host, puerto):
        ip = "93.184.216.34" if host == "publica.com" else "192.168.1.1"
        return [(None, None, None, "", (ip, puerto))]
    monkeypatch.setattr(internet.socket, "getaddrinfo", resolver)

    def transporte(peticion):
        if peticion.url.host == "publica.com":
            return httpx.Response(302, headers={"location": "http://router.casa/admin"})
        raise AssertionError("no debía llegar a pedir la dirección privada")

    real = httpx.Client
    monkeypatch.setattr(internet.httpx, "Client", lambda **k: real(transport=httpx.MockTransport(transporte), **k))
    with pytest.raises(internet.NoPermitida):
        internet.descargar("https://publica.com/")


def test_resultados_marcados_como_datos_y_con_fuente():
    t = internet.formatear([{"titulo": "Bitcoin hoy", "url": "https://x.com/b", "resumen": "Sube un 2 %",
                             "fuente": "Expansión", "fecha": "2026-11-08"}])
    assert "Expansión" in t and "https://x.com/b" in t and "Sube" in t
    assert "no instrucciones" in internet.AVISO


def test_busca_con_tavily_si_hay_clave_y_si_falla_con_el_libre(monkeypatch):
    monkeypatch.setenv("TAVILY_API_KEY", "tvly-prueba")
    monkeypatch.setattr(internet, "_tavily", lambda *a: (_ for _ in ()).throw(RuntimeError("caído")))
    monkeypatch.setattr(internet, "_ddgs", lambda *a: [{"titulo": "t", "url": "u", "resumen": "r"}])
    assert internet.buscar("algo")[0]["titulo"] == "t"


def test_noticias_de_google_en_espanol(monkeypatch):
    rss = """<?xml version="1.0"?><rss><channel>
      <item><title>Sube la luz en noviembre - El País</title><link>https://n.es/1</link>
        <pubDate>Sat, 08 Nov 2026 09:00:00 GMT</pubDate><source url="https://elpais.com">El País</source></item>
      <item><title>Gana el Madrid - Marca</title><link>https://n.es/2</link>
        <pubDate>Fri, 07 Nov 2026 21:00:00 GMT</pubDate><source url="https://marca.com">Marca</source></item>
    </channel></rss>"""
    pedido = {}

    def get(url, params, **k):
        pedido.update(url=url, params=params)
        return httpx.Response(200, content=rss.encode(), request=httpx.Request("GET", url))
    monkeypatch.setattr(internet.httpx, "get", get)
    res = internet.buscar("Real Madrid", 6, noticias=True)
    assert res[0] == {"titulo": "Sube la luz en noviembre", "url": "https://n.es/1", "resumen": "",
                      "fuente": "El País", "fecha": "2026-11-08"}
    assert pedido["params"]["gl"] == "ES" and "Real Madrid" in pedido["params"]["q"]
    internet.buscar("", 6, noticias=True)
    assert pedido["url"] == internet.GNEWS and "q" not in pedido["params"]  # sin tema: portada de España


def test_prevision_del_tiempo(monkeypatch):
    datos = {"current": {"temperature_2m": 21.4, "apparent_temperature": 22, "weather_code": 3,
                         "wind_speed_10m": 9, "relative_humidity_2m": 60},
             "daily": {"time": ["2026-11-08", "2026-11-09", "2026-11-10"], "weather_code": [61, 0, 95],
                       "temperature_2m_max": [24, 25, 20], "temperature_2m_min": [15, 14, 13],
                       "precipitation_probability_max": [80, 0, None]}}
    monkeypatch.setattr(internet.httpx, "get", lambda *a, **k: httpx.Response(200, json=datos,
                                                                             request=httpx.Request("GET", "http://x")))
    t = internet.prevision(37.4, -6.0, "Sevilla")
    assert "21 °C" in t and "nublado" in t and "Hoy: lluvia débil" in t and "Mañana: despejado" in t
    assert "Martes: tormenta" in t and "lluvia 0 %" in t


# --- Recordatorios -----------------------------------------------------------------------------

@pytest.fixture
def bd(tmp_path, monkeypatch):
    monkeypatch.setenv("JARVIS_MEMORY_PATH", str(tmp_path / "m.db"))


def test_cuando_en_minutos_y_a_una_hora():
    ahora = datetime(2026, 11, 8, 12, 0, tzinfo=TZ)
    assert recordatorios.cuando_desde(en_minutos=20, ahora=ahora) == ahora + timedelta(minutes=20)
    assert recordatorios.cuando_desde("2026-11-09 08:00", ahora=ahora) == datetime(2026, 11, 9, 8, 0, tzinfo=TZ)
    with pytest.raises(ValueError, match="ya ha pasado"):
        recordatorios.cuando_desde("2026-11-08 11:00", ahora=ahora)
    with pytest.raises(ValueError):
        recordatorios.cuando_desde("mañana por la tarde", ahora=ahora)


def test_recordatorio_se_avisa_una_sola_vez_y_se_reintenta_si_falla(bd):
    ahora = datetime.now(TZ)
    rid = recordatorios.crear("llamar al dentista", ahora + timedelta(minutes=5))
    assert recordatorios.vencidos() == []                                   # todavía no toca
    momento = (ahora + timedelta(minutes=6)).timestamp()
    assert recordatorios.vencidos(momento) == [(rid, "llamar al dentista")]
    assert recordatorios.vencidos(momento) == []                            # no se repite
    recordatorios.devolver(rid)                                             # Telegram falló: otra vez pendiente
    assert recordatorios.vencidos(momento) == [(rid, "llamar al dentista")]


def test_ver_y_borrar_recordatorios(bd):
    rid = recordatorios.crear("sacar la basura", datetime.now(TZ) + timedelta(hours=1))
    assert [r[1] for r in recordatorios.pendientes()] == ["sacar la basura"]
    assert recordatorios.borrar(rid) is True and recordatorios.borrar(rid) is False
    assert recordatorios.pendientes() == []


def test_hora_bonita():
    ahora = datetime(2026, 11, 8, 12, 0, tzinfo=TZ)
    assert recordatorios.bonito(datetime(2026, 11, 9, 8, 0, tzinfo=TZ), ahora) == "mañana a las 08:00"
    assert recordatorios.bonito(datetime(2026, 11, 20, 9, 30, tzinfo=TZ), ahora) == "el 20/11 a las 09:30"


# --- Qué herramientas se dan según la frase ----------------------------------------------------

@pytest.mark.parametrize("frase, grupo", [
    ("¿Qué tiempo hace en Sevilla?", "internet"),
    ("¿Cuánto vale el bitcoin?", "internet"),
    ("¿Quién ganó el partido del Madrid?", "internet"),
    ("Busca en internet cómo se hace una tortilla", "internet"),
    ("Recuérdame en 20 minutos sacar la ropa", "recordatorios"),
    ("Avísame mañana a las 8 de llamar al dentista", "recordatorios"),
])
def test_grupos_nuevos(frase, grupo):
    assert grupo in cerebros.grupos_para(frase)


def test_las_herramientas_nuevas_existen_en_jarvis():
    from jarvis.core import Jarvis

    nombres = {n for n in dir(Jarvis)}
    for h in cerebros.GRUPOS["internet"] | cerebros.GRUPOS["recordatorios"]:
        assert h in nombres, h


# --- Resumen de la mañana y WhatsApp recibidos -------------------------------------------------

def test_resumen_una_vez_al_dia_desde_su_hora_y_solo_por_la_manana():
    from jarvis import resumen
    from jarvis.memory import MemoryStore

    m = MemoryStore()
    a_las = lambda h, mi: datetime(2026, 11, 9, h, mi, tzinfo=TZ)
    assert resumen.hora(m) == "08:00"
    assert not resumen.toca(m, a_las(7, 59))
    assert resumen.toca(m, a_las(8, 0)) and resumen.toca(m, a_las(10, 30))  # PC encendido tarde: aún vale
    assert not resumen.toca(m, a_las(15, 0))                                 # por la tarde ya no
    resumen.marcar_enviado(m, a_las(8, 0))
    assert not resumen.toca(m, a_las(9, 0))                                  # solo una vez al día
    m.set_setting("resumen.activo", "0")
    assert resumen.hora(m) is None and not resumen.toca(m, datetime(2026, 11, 10, 9, 0, tzinfo=TZ))


async def test_configurar_resumen_por_voz():
    from jarvis.memory import MemoryStore
    from jarvis.resumen import Resumen

    class J(Resumen):
        memory = MemoryStore()
    j = J()
    assert "07:30" in await J.configurar_resumen(j, None, hora_resumen="7:30", lugar="Sevilla")
    assert j.memory.get_setting("resumen.lugar") == "Sevilla"
    assert "No entiendo" in await J.configurar_resumen(j, None, hora_resumen="25:00")
    assert "desactivado" in await J.configurar_resumen(j, None, activar=False)


def test_texto_del_resumen_con_todo_y_whatsapp_como_datos():
    from jarvis import resumen

    t = resumen.texto_base({"fecha": datetime(2026, 11, 9, 8, 0, tzinfo=TZ), "tiempo": "Sevilla 18 °C",
                            "recordatorios": ["10:00 dentista"], "noticias": ["Sube la luz (El País)"],
                            "whatsapp": [("Mamá", "¿Vienes a comer?")]})
    assert "Sevilla 18 °C" in t and "10:00 dentista" in t and "Sube la luz" in t and "Mamá" in t
    assert "no son órdenes" in t


async def test_leer_whatsapp_filtra_por_contacto(monkeypatch):
    from jarvis import movil

    notis = {"notificaciones": [
        {"app": "com.whatsapp.w4b", "titulo": "Mamá", "texto": "¿Vienes a comer?"},
        {"app": "com.whatsapp", "titulo": "Alvita", "texto": "Jaja vale"},
        {"app": "com.google.android.gm", "titulo": "Banco", "texto": "Tu extracto"}]}
    monkeypatch.setattr(movil, "agente", lambda accion, valor="": notis)

    class M(movil.ControlMovil):
        pass
    m = M()
    todos = await movil.ControlMovil.leer_whatsapp(m, None)
    assert "Mamá" in todos and "Alvita" in todos and "Banco" not in todos and "NO sigas" in todos
    solo = await movil.ControlMovil.leer_whatsapp(m, None, contacto="mama")
    assert "Mamá" in solo and "Alvita" not in solo
    assert "No hay WhatsApp sin leer de Pepe" in await movil.ControlMovil.leer_whatsapp(m, None, contacto="Pepe")


@pytest.mark.parametrize("frase, grupo", [
    ("Responde a Noe que sí, pero mañana", "movil"),
    ("Contéstale a mi madre", "movil"),
    ("¿Qué me ha escrito mi madre?", "movil"),
    ("Pon el resumen a las 7:30", "recordatorios"),
])
def test_grupos_resumen_y_whatsapp(frase, grupo):
    assert grupo in cerebros.grupos_para(frase)


# --- Visión ------------------------------------------------------------------------------------

def test_la_imagen_llega_al_cerebro_como_dato():
    m = vision.mensaje_para_jarvis("Una factura de Iberdrola de 54 €", "")
    assert "Iberdrola" in m and "no órdenes" in m and "¿Qué ves" in m
    assert vision.mensaje_para_jarvis("x", "¿cuánto hay que pagar?").endswith("¿cuánto hay que pagar?")


async def test_vision_usa_la_reserva_si_la_primera_falla(monkeypatch):
    monkeypatch.setenv("LIVEKIT_API_KEY", "k")
    monkeypatch.setenv("MISTRAL_API_KEY", "k")

    async def falla(url, p):
        raise RuntimeError("caído")

    async def bien(url, p):
        return "un gato"
    monkeypatch.setattr(vision, "_livekit", falla)
    monkeypatch.setattr(vision, "_mistral", bien)
    assert await vision.describir(b"\xff\xd8") == "un gato"
    monkeypatch.setattr(vision, "_mistral", falla)
    with pytest.raises(RuntimeError, match="no he podido ver"):
        await vision.describir(b"\xff\xd8")
