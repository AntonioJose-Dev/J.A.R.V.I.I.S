from datetime import datetime

import pytest

from jarvis.boveda import Boveda, migrar, nombre_de_nota, normalizar_tipo
from jarvis.memory import MemoryStore

DIA = datetime(2026, 11, 7, 18, 30)


@pytest.fixture
def b(tmp_path):
    bv = Boveda(tmp_path / "Cerebro")
    yield bv
    bv.close()


def test_estructura_de_obsidian(b):
    for f in ("Inicio.md", "Personas.md", "Lugares.md", "Diario.md"):
        assert (b.ruta / f).exists()
    assert (b.ruta / ".obsidian").is_dir() and (b.ruta / "Personas").is_dir()


def test_recordar_crea_nota_enlazada(b):
    b.recordar("Es la madre de Potro y cumple el 3 de mayo", sobre="Carmen", tipo="persona",
               relacionados=["Potro", "Madrid"], cuando=DIA)
    carmen = (b.ruta / "Personas" / "Carmen.md").read_text(encoding="utf-8")
    assert "tipo: persona" in carmen and "[[Personas]]" in carmen
    assert "- Es la madre de Potro y cumple el 3 de mayo ([[2026-11-07]]) · [[Potro]] · [[Madrid]]" in carmen
    assert "## Relacionado\n- [[Potro]]\n- [[Madrid]]" in carmen
    # Las relacionadas existen y enlazan de vuelta (para el grafo)
    assert "[[Carmen]]" in b.leer("Madrid")
    # Índice y diario
    assert "- [[Carmen]]" in (b.ruta / "Personas.md").read_text(encoding="utf-8")
    diario = (b.ruta / "Diario" / "2026-11-07.md").read_text(encoding="utf-8")
    assert "18:30 Es la madre de Potro" in diario and "[[Carmen]]" in diario
    assert "- [[2026-11-07]]" in (b.ruta / "Diario.md").read_text(encoding="utf-8")


def test_actualiza_en_vez_de_duplicar(b):
    b.recordar("Le gusta el café solo", sobre="Carmen", tipo="persona", cuando=DIA)
    b.recordar("Vive en Madrid", sobre="carmen", tipo="persona", cuando=DIA)  # minúsculas: misma nota
    b.recordar("Vive en Madrid", sobre="Carmen", tipo="persona", cuando=DIA)  # repetido: no se duplica
    assert len(list(b.ruta.rglob("Carmen.md"))) == 1
    texto = b.leer("Carmen")
    assert texto.count("Vive en Madrid") == 1 and "café solo" in texto
    assert (b.ruta / "Personas.md").read_text(encoding="utf-8").count("[[Carmen]]") == 1


def test_buscar_sin_tildes_y_por_contenido(b):
    b.recordar("Su cumpleaños es el 3 de mayo", sobre="Carmen", tipo="persona", cuando=DIA)
    b.recordar("Le encanta el sushi", sobre="Comida", tipo="gusto", cuando=DIA)
    resultados = b.buscar("cumpleanos carmen")
    assert resultados and resultados[0][0] == "Carmen"
    assert b.buscar("sushi")[0][0] == "Comida"
    assert b.buscar("") == []


def test_ve_lo_que_edites_a_mano_en_obsidian(b):
    (b.ruta / "Notas" / "Ideas.md").write_text("# Ideas\nMontar una startup de drones", encoding="utf-8")
    assert b.buscar("drones")[0][0] == "Ideas"


def test_dato_sin_sobre_va_al_diario(b):
    assert b.recordar("Hoy ha llovido mucho", cuando=DIA) == "Diario 2026-11-07"
    assert "Hoy ha llovido mucho" in (b.ruta / "Diario" / "2026-11-07.md").read_text(encoding="utf-8")


def test_nombres_y_tipos():
    assert nombre_de_nota("carmen / mamá: [x]") == "Carmen mamá x"
    assert normalizar_tipo("Personas") == "persona" and normalizar_tipo("cumpleaños") == "evento"
    assert normalizar_tipo("cualquiera") == "general"


def test_migrar_una_sola_vez(b):
    m = MemoryStore()
    m.remember("Le gusta el sushi")
    m.save_contact("mama", "Mamá", "+34600123456")
    m.save_contact("yo", "yo", "+34611111111")
    assert migrar(b, m) == 2  # el recuerdo y Mamá ("yo" no es una persona)
    assert "+34600123456" in b.leer("Mamá")
    assert migrar(b, m) == 0
    m.close()


def test_herramientas_de_jarvis_con_boveda(tmp_path, monkeypatch):
    import asyncio

    from jarvis import core

    monkeypatch.setenv("JARVIS_BOVEDA", str(tmp_path / "Cerebro"))
    monkeypatch.setenv("JARVIS_MEMORY_PATH", str(tmp_path / "m.db"))
    monkeypatch.setattr(core, "_boveda", None)
    m = MemoryStore()
    j = core.Jarvis(m)

    async def probar():
        r = await j.recordar(None, hecho="Es la madre de Potro", sobre="Carmen", tipo="persona", relacionados="Potro")
        assert "Carmen" in r
        busqueda = await j.buscar_recuerdos(None, consulta="madre")
        assert "Carmen" in busqueda and "Potro" in busqueda
        assert "Es la madre de Potro" in await j.leer_nota(None, nombre="carmen")

    asyncio.run(probar())
    core._boveda.close()
    monkeypatch.setattr(core, "_boveda", None)
    m.close()
