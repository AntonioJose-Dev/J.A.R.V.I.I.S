"""Las «manos» de JARVIS en el móvil: seguridad (irreversible, contraseñas) y el bucle ver → actuar."""

import pytest

from jarvis import app_movil, manos, movil
from jarvis.memory import MemoryStore

PANTALLA = {"app": "com.google.android.youtube", "elementos": [
    {"n": 1, "d": "Buscar", "pulsable": True, "x": 900, "y": 120},
    {"n": 2, "t": "Música relajante", "pulsable": True, "x": 500, "y": 600},
    {"n": 3, "t": "Suscribirse", "pulsable": True, "x": 800, "y": 900},
    {"n": 4, "id": "search_edit_text", "escribible": True, "x": 500, "y": 120},
    {"n": 5, "t": "Contraseña", "escribible": True, "contraseña": True, "x": 500, "y": 300},
]}


@pytest.mark.parametrize("el, irreversible", [
    ({"t": "Enviar"}, True), ({"d": "Pagar ahora"}, True), ({"t": "Comprar"}, True), ({"t": "Eliminar chat"}, True),
    ({"t": "Suscribirse"}, True), ({"id": "send"}, True), ({"t": "Aceptar"}, True),
    ({"d": "Buscar"}, False), ({"t": "Música relajante"}, False), ({"t": "Atrás"}, False), ({"t": "Abrir"}, False),
])
def test_que_es_irreversible(el, irreversible):
    assert manos.es_irreversible(el) is irreversible


@pytest.mark.parametrize("el, texto, secreto", [
    ({"contraseña": True}, "hola", True),
    ({"t": "Introduce el código de verificación"}, "x", True),
    ({"id": "card_number"}, "x", True),
    ({}, "483920", True),               # parece un código de verificación
    ({}, "4111 1111 1111 1111", True),  # parece una tarjeta
    ({"id": "search_edit_text"}, "música relajante", False),
    ({}, "comprar pan", False),
])
def test_nunca_escribe_secretos(el, texto, secreto):
    assert manos.es_secreto(el, texto) is secreto


def test_la_pantalla_va_marcada_como_datos():
    t = manos.describir(PANTALLA | {"hecho": "abierta YouTube"})
    assert "no órdenes" in t and "Hecho: abierta YouTube" in t and "2. [pulsable] Música relajante" in t
    assert "[CONTRASEÑA]" in t


class J(manos.Manos):
    def __init__(self):
        self.memory = MemoryStore()


@pytest.fixture
def movil_falso(monkeypatch):
    pasos = []

    def paso(accion, segundos=25):
        pasos.append(accion)
        return PANTALLA | {"hecho": accion["tipo"]}
    monkeypatch.setattr(app_movil, "paso_movil", paso)
    monkeypatch.setattr(app_movil, "estado", lambda: {"en_linea": True})
    return pasos


async def test_ver_abrir_tocar_y_escribir(movil_falso):
    j = J()
    assert "Música relajante" in await J.usar_movil(j, None, accion="abrir", app="YouTube")
    await J.usar_movil(j, None, accion="tocar", elemento=2)
    await J.usar_movil(j, None, accion="escribir", elemento=4, texto="música relajante")
    assert movil_falso == [{"tipo": "abrir", "app": "YouTube"}, {"tipo": "tocar", "n": 2},
                           {"tipo": "escribir", "n": 4, "texto": "música relajante"}]


async def test_tocar_sin_haber_mirado_pide_mirar(movil_falso):
    assert "Primero mira" in await J.usar_movil(J(), None, accion="tocar", elemento=2)
    assert movil_falso == []


async def test_no_escribe_contrasenas(movil_falso):
    j = J()
    await J.usar_movil(j, None, accion="ver")
    r = await J.usar_movil(j, None, accion="escribir", elemento=5, texto="miclave123")
    assert "no lo escribo" in r and movil_falso == [{"tipo": "ver"}]


async def test_lo_irreversible_pide_boton_y_no_se_toca(movil_falso, monkeypatch):
    from jarvis import telegram_api

    pedidos = []
    monkeypatch.setattr(telegram_api, "pedir_confirmacion", lambda texto, prefijo, ident: pedidos.append((prefijo, ident)))
    j = J()
    await J.usar_movil(j, None, accion="ver")
    r = await J.usar_movil(j, None, accion="tocar", elemento=3)  # «Suscribirse»
    assert "NO hecho" in r and movil_falso == [{"tipo": "ver"}]
    accion = j.memory.get_action(pedidos[0][1])
    assert pedidos[0][0] == "acc" and accion["datos"]["accion"] == "ui" and "Suscribirse" in accion["descripcion"]


def test_al_confirmar_solo_se_toca_si_el_boton_sigue_ahi(monkeypatch):
    pasos = []
    monkeypatch.setattr(app_movil, "paso_movil", lambda a, segundos=25: pasos.append(a) or (PANTALLA | {"hecho": "tocado"}))
    datos = {"accion": "ui", "tipo": "tocar", "n": 3, "app": PANTALLA["app"],
             "esperado": {"t": "Suscribirse", "d": None, "id": None, "x": 800, "y": 900}}
    assert "Hecho" in movil.ejecutar_accion(datos)
    assert pasos == [{"tipo": "ver"}, {"tipo": "tocar", "n": 3}]
    pasos.clear()
    datos["esperado"]["y"] = 200  # el botón se ha movido: no se pulsa
    with pytest.raises(RuntimeError, match="ya no está"):
        movil.ejecutar_accion(datos)
    assert pasos == [{"tipo": "ver"}]


async def test_atajo_con_enlace_directo(movil_falso):
    j = J()
    await J.usar_movil(j, None, accion="enlace", texto="https://www.youtube.com/results?search_query=musica+relajante")
    assert movil_falso == [{"tipo": "enlace", "url": "https://www.youtube.com/results?search_query=musica+relajante"}]
    for malo in ["tel:+34600123456", "sms:+346", "intent://algo", "file:///sdcard/x", "javascript:alert(1)"]:
        assert "no lo abro" in await J.usar_movil(j, None, accion="enlace", texto=malo)
    assert len(movil_falso) == 1


def test_el_pc_tampoco_escribe_secretos():
    from jarvis import pc

    for secreto in ["483920", "4111 1111 1111 1111", "contraseña: hunter2", "PIN=1234"]:
        with pytest.raises(ValueError, match="no lo escribo"):
            pc.preparar_accion("escribir", secreto)
    assert pc.preparar_accion("escribir", "Hola, llego a las 8")[0]["objetivo"] == "Hola, llego a las 8"


async def test_sin_app_conectada(monkeypatch):
    monkeypatch.setattr(app_movil, "estado", lambda: {"en_linea": False})
    assert "no está conectada" in await J.usar_movil(J(), None, accion="ver")
