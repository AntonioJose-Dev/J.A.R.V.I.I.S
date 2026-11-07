"""El agente que corre en el móvil (movil/agente.py) y cómo lo usa el PC (jarvis/movil.py)."""

import importlib.util
import json
from pathlib import Path

import httpx
import pytest

from jarvis import movil

_spec = importlib.util.spec_from_file_location("agente", Path(__file__).parent.parent / "movil" / "agente.py")
agente = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(agente)

TOKEN = "ABCD2345EFGH6789JKLM"


# --- Agente del móvil ---

def test_sin_token_o_token_malo_no_hace_nada(monkeypatch):
    llamado = []
    monkeypatch.setitem(agente.ACCIONES, "estado", lambda v: llamado.append(v) or {})
    assert agente.atender(b'{"accion":"estado"}', None, TOKEN)[0] == 401
    assert agente.atender(b'{"accion":"estado"}', "otro", TOKEN)[0] == 401
    assert agente.atender(b'{"accion":"estado"}', TOKEN, "")[0] == 401  # sin token configurado, nadie entra
    assert llamado == []


@pytest.mark.parametrize("ip, permitido", [
    ("100.78.85.68", True),          # el PC por Tailscale
    ("127.0.0.1", True),             # el propio móvil
    ("::ffff:100.78.85.68", True),
    ("192.168.1.50", False),         # alguien en la misma Wi-Fi (p. ej. una cafetería)
    ("8.8.8.8", False),
    ("", False), (None, False), ("basura", False),
])
def test_solo_tailscale(ip, permitido):
    assert agente.red_permitida(ip) is permitido


def test_desde_otra_red_ni_con_el_token_correcto():
    assert agente.atender(b'{"accion":"ping"}', TOKEN, TOKEN, "192.168.1.50")[0] == 403
    assert agente.atender(b'{"accion":"ping"}', TOKEN, TOKEN, "100.78.85.68")[0] == 200


def test_ping_y_accion_valida(monkeypatch):
    monkeypatch.setitem(agente.ACCIONES, "estado", lambda v: {"bateria": 80, "cargando": False})
    assert agente.atender(b'{"accion":"ping"}', TOKEN, TOKEN) == (200, {"ok": True, "version": agente.VERSION})
    assert agente.atender(b'{"accion":"estado"}', TOKEN, TOKEN) == (200, {"bateria": 80, "cargando": False})


def test_accion_desconocida_y_json_malo():
    assert agente.atender(b'{"accion":"rm -rf"}', TOKEN, TOKEN)[0] == 400
    assert agente.atender(b"no es json", TOKEN, TOKEN)[0] == 400


def test_error_de_una_accion_vuelve_al_pc(monkeypatch):
    def falla(v):
        raise RuntimeError("sin GPS")
    monkeypatch.setitem(agente.ACCIONES, "ubicacion", falla)
    codigo, r = agente.atender(b'{"accion":"ubicacion"}', TOKEN, TOKEN)
    assert codigo == 500 and "sin GPS" in r["error"]


def test_whatsapp_firma_la_orden_para_la_app(tmp_path, monkeypatch):
    import hashlib
    import hmac as _hmac

    secreto = "s" * 64
    ruta = tmp_path / "companion"
    ruta.write_text(secreto)
    monkeypatch.setattr(agente, "RUTA_COMPANION", str(ruta))
    comandos = []

    def ejecutar(cmd, timeout=30):
        comandos.append(cmd)
        return "Broadcast completed: result=1" if cmd[:2] == ["am", "broadcast"] else ""
    monkeypatch.setattr(agente, "ejecutar", ejecutar)
    r = agente.whatsapp(json.dumps({"numero": "+34600123456", "texto": "Llego a las 8"}))
    assert r == {"ok": True, "automatico": True}
    orden = comandos[0]
    extras = dict(zip(orden[orden.index("--es") + 1::3], orden[orden.index("--es") + 2::3]))
    assert extras["texto"] == "Llego a las 8"
    # La misma firma que comprueba la app (Orden.java): HMAC-SHA256(secreto, marca + "\n" + texto) en hex
    esperada = _hmac.new(secreto.encode(), f"{extras['marca']}\nLlego a las 8".encode(), hashlib.sha256).hexdigest()
    assert extras["firma"] == esperada
    assert comandos[1][0] == "termux-open-url" and "wa.me/34600123456" in comandos[1][1]


def test_whatsapp_sin_app_solo_lo_deja_escrito(tmp_path, monkeypatch):
    monkeypatch.setattr(agente, "RUTA_COMPANION", str(tmp_path / "no_existe"))
    monkeypatch.setattr(agente, "ejecutar", lambda cmd, timeout=30: "")
    assert agente.whatsapp(json.dumps({"numero": "+34600123456", "texto": "hola"})) == {"ok": True, "automatico": False}


def test_sms_usa_termux_sms_send_con_argumentos_separados(monkeypatch):
    ejecutados = []
    monkeypatch.setattr(agente, "ejecutar", lambda cmd, timeout=30: ejecutados.append(cmd) or "")
    agente.sms(json.dumps({"numero": "+34600123456", "texto": "hola; reboot"}))
    assert ejecutados == [["termux-sms-send", "-n", "+34600123456", "hola; reboot"]]  # sin shell: nada se ejecuta


# --- PC: agente primero, ADB después ---

@pytest.fixture
def con_agente(monkeypatch):
    monkeypatch.setenv("JARVIS_MOVIL_URL", "http://movil:8765")
    monkeypatch.setenv("JARVIS_MOVIL_TOKEN", TOKEN)


def test_agente_manda_token_y_accion(con_agente, monkeypatch):
    enviado = {}

    def post(url, json, headers, timeout):
        enviado.update(url=url, json=json, headers=headers)
        return httpx.Response(200, json={"bateria": 55, "cargando": True})

    monkeypatch.setattr(httpx, "post", post)
    assert movil.agente("estado") == {"bateria": 55, "cargando": True}
    assert enviado["json"] == {"accion": "estado", "valor": ""}
    assert enviado["headers"]["X-Jarvis-Token"] == TOKEN


def test_token_rechazado(con_agente, monkeypatch):
    monkeypatch.setattr(httpx, "post", lambda *a, **k: httpx.Response(401, json={"error": "token incorrecto"}))
    with pytest.raises(movil.ErrorAgente, match="código secreto"):
        movil.agente("estado")


def test_si_el_agente_no_responde_usa_adb(con_agente, monkeypatch):
    def caido(*a, **k):
        raise httpx.ConnectError("sin red")
    monkeypatch.setattr(httpx, "post", caido)
    assert movil.via_agente_o_adb(lambda: movil.agente("estado"), lambda: "por adb") == "por adb"


def test_sin_agente_ni_adb_explica_por_que(con_agente, monkeypatch):
    def caido(*a, **k):
        raise httpx.ConnectError("sin red")

    def sin_adb():
        raise movil.SinMovil("El móvil no está conectado por cable/Wi-Fi.")
    monkeypatch.setattr(httpx, "post", caido)
    with pytest.raises(movil.SinMovil, match="Tailscale"):
        movil.via_agente_o_adb(lambda: movil.agente("estado"), sin_adb)


def test_sin_configurar_va_directo_a_adb(monkeypatch):
    monkeypatch.delenv("JARVIS_MOVIL_URL", raising=False)
    assert movil.via_agente_o_adb(lambda: pytest.fail("no debe usar el agente"), lambda: "adb") == "adb"


def test_codigo_secreto_facil_de_teclear():
    import importlib

    spec = importlib.util.spec_from_file_location(
        "configurar_movil", Path(__file__).parent.parent / "scripts" / "configurar_movil.py")
    cfg = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cfg)
    t = cfg.nuevo_token()
    assert len(t) == 20 and not set(t) & set("01IO")
    assert cfg.agrupado(t).replace("-", "") == t and cfg.agrupado(t).count("-") == 4
