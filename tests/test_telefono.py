from datetime import datetime, timedelta, timezone

import pytest

from jarvis import telefono
from jarvis.core import Jarvis
from jarvis.llamadas import formatear_informe
from jarvis.memory import MemoryStore
from jarvis.prompts import prompt_buzon, prompt_llamada
from jarvis.telegram_bot import decidir_boton, id_de_boton

YO = 123


@pytest.fixture
def memoria():
    m = MemoryStore()
    yield m
    m.close()


@pytest.fixture
def configurado(monkeypatch):
    monkeypatch.setenv("LIVEKIT_URL", "wss://jarvis.livekit.cloud")
    monkeypatch.setenv("LIVEKIT_API_KEY", "k")
    monkeypatch.setenv("LIVEKIT_API_SECRET", "s")
    monkeypatch.setenv("LIVEKIT_SIP_TRUNK_ID", "ST_x")
    monkeypatch.delenv("JARVIS_PREFIJOS_LLAMADA", raising=False)


# --- Números ---

@pytest.mark.parametrize("entrada", ["600 12 34 56", "600-123-456", "+34 600 123 456", "0034600123456"])
def test_normalizar_numero_espanol(entrada):
    assert telefono.normalizar_numero(entrada) == "+34600123456"


def test_normalizar_fijo_y_extranjero():
    assert telefono.normalizar_numero("91 123 45 67") == "+34911234567"
    assert telefono.normalizar_numero("+33 6 12 34 56 78") == "+33612345678"


@pytest.mark.parametrize("malo", ["", "hola", "12345", "+34", "1234567890123456789"])
def test_numeros_no_validos(malo):
    with pytest.raises(ValueError):
        telefono.normalizar_numero(malo)


def test_solo_espana_y_ue_por_defecto(monkeypatch):
    monkeypatch.delenv("JARVIS_PREFIJOS_LLAMADA", raising=False)
    assert telefono.numero_permitido("+34600123456")
    assert telefono.numero_permitido("+351912345678")
    assert not telefono.numero_permitido("+12025550123")  # EE. UU.
    assert not telefono.numero_permitido("+882123456789")  # satélite / tarificación especial


def test_prefijos_configurables(monkeypatch):
    monkeypatch.setenv("JARVIS_PREFIJOS_LLAMADA", "34")
    assert telefono.numero_permitido("+34600123456")
    assert not telefono.numero_permitido("+33612345678")


# --- Agenda ---

def test_clave_nombre():
    assert telefono.clave_nombre("A mi Mamá") == "mama"
    assert telefono.clave_nombre("  Carlos   del Trabajo ") == "carlos del trabajo"


def test_guardar_y_resolver_contacto(memoria):
    telefono.guardar_contacto(memoria, "Mamá", "600 12 34 56")
    assert telefono.resolver_destino(memoria, "mi mama") == ("Mamá", "+34600123456")
    assert telefono.resolver_destino(memoria, "a mamá") == ("Mamá", "+34600123456")


def test_resolver_por_numero_reconoce_el_contacto(memoria):
    telefono.guardar_contacto(memoria, "Carlos", "611111111")
    assert telefono.resolver_destino(memoria, "611 11 11 11") == ("Carlos", "+34611111111")
    assert telefono.resolver_destino(memoria, "622222222") == ("+34622222222", "+34622222222")


def test_resolver_parcial_solo_si_no_hay_ambiguedad(memoria):
    telefono.guardar_contacto(memoria, "Carlos del trabajo", "611111111")
    assert telefono.resolver_destino(memoria, "Carlos")[1] == "+34611111111"
    telefono.guardar_contacto(memoria, "Carlos primo", "622222222")
    with pytest.raises(LookupError):
        telefono.resolver_destino(memoria, "Carlos")


def test_contacto_desconocido(memoria):
    with pytest.raises(LookupError):
        telefono.resolver_destino(memoria, "el fontanero")


# --- La herramienta `llamar` nunca marca: solo pide confirmación ---

async def test_llamar_crea_pendiente_y_pide_confirmacion(memoria, configurado, monkeypatch):
    pedidas = []

    async def confirmar(llamada):
        pedidas.append(llamada)

    async def no_debe_llamar(_):
        raise AssertionError("llamar no debe marcar sin confirmación")

    monkeypatch.setattr(telefono, "iniciar_llamada", no_debe_llamar)
    telefono.guardar_contacto(memoria, "Mamá", "600123456")
    j = Jarvis(memoria, pedir_confirmacion=confirmar)
    respuesta = await j.llamar(None, destino="mamá", mensaje="que llego a las 8")

    assert len(pedidas) == 1
    assert pedidas[0]["estado"] == "pendiente"
    assert pedidas[0]["numero"] == "+34600123456"
    assert pedidas[0]["mensaje"] == "que llego a las 8"
    assert "NO hecho" in respuesta


async def test_llamar_sin_configurar_no_crea_nada(memoria, monkeypatch):
    monkeypatch.delenv("LIVEKIT_SIP_TRUNK_ID", raising=False)
    j = Jarvis(memoria, pedir_confirmacion=lambda _: (_ for _ in ()).throw(AssertionError()))
    respuesta = await j.llamar(None, destino="600123456", mensaje="hola")
    assert "no están configuradas" in respuesta
    assert memoria.get_call(1) is None


async def test_llamar_rechaza_numero_no_permitido(memoria, configurado):
    j = Jarvis(memoria, pedir_confirmacion=lambda _: (_ for _ in ()).throw(AssertionError()))
    respuesta = await j.llamar(None, destino="+12025550123", mensaje="hola")
    assert "solo se permiten" in respuesta
    assert memoria.get_call(1) is None


def test_localhost_no_vale_para_llamar(configurado, monkeypatch):
    monkeypatch.setenv("LIVEKIT_URL", "ws://localhost:7880")
    assert any("LIVEKIT_URL" in f for f in telefono.llamadas_configuradas())


# --- Botones de confirmación en Telegram ---

def _llamada(memoria, estado="pendiente"):
    call_id = memoria.create_call("Mamá", "+34600123456", "hola")
    if estado != "pendiente":
        memoria.set_call_status(call_id, estado)
    return memoria.get_call(call_id)


def test_boton_llamar_del_dueno(memoria):
    ll = _llamada(memoria)
    assert decidir_boton(YO, frozenset({YO}), f"llamar:{ll['id']}", ll, caducada=False) == "llamar"
    assert decidir_boton(YO, frozenset({YO}), f"cancelar:{ll['id']}", ll, caducada=False) == "cancelar"


def test_boton_de_otro_usuario_se_ignora(memoria):
    ll = _llamada(memoria)
    assert decidir_boton(999, frozenset({YO}), f"llamar:{ll['id']}", ll, caducada=False) == "ignorar"


def test_boton_dos_veces_no_llama_dos_veces(memoria):
    ll = _llamada(memoria)
    assert memoria.set_call_status(ll["id"], "marcando", only_if="pendiente") is True
    assert memoria.set_call_status(ll["id"], "marcando", only_if="pendiente") is False
    ll = memoria.get_call(ll["id"])
    assert decidir_boton(YO, frozenset({YO}), f"llamar:{ll['id']}", ll, caducada=False) == "ya_gestionada"


def test_confirmacion_caducada(memoria):
    ll = _llamada(memoria)
    assert decidir_boton(YO, frozenset({YO}), f"llamar:{ll['id']}", ll, caducada=True) == "caducada"
    assert telefono.caducada(ll, datetime.now(timezone.utc) + timedelta(minutes=11))
    assert not telefono.caducada(ll, datetime.now(timezone.utc) + timedelta(minutes=5))


def test_id_de_boton():
    assert id_de_boton("llamar:42") == 42
    # Los botones Sí/No de acciones del PC y del móvil llevan tres partes (fallo real del 07/11)
    assert id_de_boton("acc:5:si") == 5
    assert id_de_boton("pc:7:no") == 7
    assert id_de_boton("basura") is None
    assert id_de_boton(None) is None


# --- Lo que dice JARVIS por teléfono ---

def test_prompt_de_llamada_se_presenta_como_ia_y_lleva_el_mensaje():
    p = prompt_llamada("Potro", "Mamá", "que llego a las 8")
    assert "asistente de inteligencia artificial de Potro" in p
    assert "lo primero" in p.lower()
    assert "que llego a las 8" in p
    assert "colgar" in p
    assert "No prometas" in p


def test_prompt_de_buzon():
    p = prompt_buzon("Potro", "Mamá", "que llego a las 8")
    assert "inteligencia artificial de Potro" in p and "que llego a las 8" in p


def test_informe_de_llamada():
    datos = {"nombre": "Mamá", "numero": "+34600123456"}
    texto = formatear_informe(datos, "persona", 42.7, "Dice que vale.",
                              [("assistant", "Hola, soy JARVIS"), ("user", "Hola, dime")])
    assert "contestó una persona" in texto and "42 s" in texto
    assert "Resumen: Dice que vale." in texto
    assert "JARVIS: Hola, soy JARVIS" in texto and "Mamá: Hola, dime" in texto
