"""Lo que ve el usuario en la pantalla de /hablar y la regla 'en el móvil salvo que diga PC'."""

from jarvis.agent import FALLOS, etiqueta_accion
from jarvis.core import Jarvis
from jarvis.memory import MemoryStore
from jarvis.pc import AVISO_ESTA_EN_EL_MOVIL, pidio_el_pc


def test_etiquetas_legibles():
    assert etiqueta_accion("movil_hacer", '{"accion": "abrir_app", "valor": "YouTube"}') == "📱 abrir_app YouTube"
    assert etiqueta_accion("estado_pc", "{}") == "🖥️ Estado del PC"
    assert etiqueta_accion("desconocida", "no es json") == "desconocida"


def test_fallos_se_reconocen():
    assert AVISO_ESTA_EN_EL_MOVIL.startswith(FALLOS)
    assert "Abriendo YouTube en el móvil.".startswith(FALLOS) is False


def test_pidio_el_pc():
    assert pidio_el_pc("abre la calculadora en el ordenador")
    assert pidio_el_pc("Abre YouTube en el PC")
    assert not pidio_el_pc("abre youtube")
    assert not pidio_el_pc("")


async def test_desde_el_movil_el_pc_no_abre_nada_sin_nombrarlo(monkeypatch):
    from jarvis import pc

    abiertos = []
    monkeypatch.setattr(pc.webbrowser, "open", lambda u: abiertos.append(u))
    m = MemoryStore()
    j = Jarvis(m)
    j.preferir_movil = True
    j._ultima_frase = "abre youtube"
    assert await j.abrir_web(None, direccion_o_busqueda="youtube.com") == AVISO_ESTA_EN_EL_MOVIL
    assert abiertos == []
    j._ultima_frase = "abre youtube en el ordenador"
    assert (await j.abrir_web(None, direccion_o_busqueda="youtube.com")).startswith("Abierto")
    assert abiertos == ["https://youtube.com"]
    m.close()


async def test_desde_el_pc_todo_sigue_igual(monkeypatch):
    from jarvis import pc

    abiertos = []
    monkeypatch.setattr(pc.webbrowser, "open", lambda u: abiertos.append(u))
    m = MemoryStore()
    j = Jarvis(m)  # consola del PC: preferir_movil = False
    assert (await j.abrir_web(None, direccion_o_busqueda="youtube.com")).startswith("Abierto")
    m.close()
