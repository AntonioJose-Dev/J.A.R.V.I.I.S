"""Memoria de verdad: sin duplicados, lo nuevo sustituye a lo viejo, alias, correcciones, olvidar y compromisos."""

from datetime import datetime
from pathlib import Path

import pytest

from jarvis import boveda as bv
from jarvis import memoria_indice

AYER = datetime(2026, 11, 7, 10, 0)
HOY = datetime(2026, 11, 8, 10, 0)


@pytest.fixture
def b(tmp_path, monkeypatch):
    monkeypatch.setattr(memoria_indice, "modelo", lambda: None)  # en las pruebas: solo palabras (rápido, sin descargas)
    return bv.Boveda(tmp_path / "Cerebro", indice=tmp_path / "indice.db")


def test_no_guarda_duplicados(b):
    b.recordar("Cumple años el 3 de mayo", sobre="Carmen", tipo="persona", cuando=AYER)
    b.recordar("cumple años el 3 de Mayo.", sobre="Carmen", tipo="persona", cuando=HOY)
    datos = memoria_indice.datos_de_nota(b.buscar_archivo("Carmen").read_text(encoding="utf-8"))
    assert len(datos) == 1


def test_lo_nuevo_sustituye_a_lo_viejo_y_queda_el_historial(b):
    b.recordar("Vive en Madrid", sobre="Noe", tipo="persona", cuando=AYER)
    b.corregir("Noe", "vive en Madrid", "Vive en Sevilla", cuando=HOY)
    texto = b.buscar_archivo("Noe").read_text(encoding="utf-8")
    assert "~~Vive en Madrid~~ (hasta [[2026-11-08]])" in texto and "- Vive en Sevilla ([[2026-11-08]])" in texto
    vigentes = [r["texto"] for r in b.buscar_datos("dónde vive Noe")]
    assert any("Sevilla" in t for t in vigentes) and not any("Madrid" in t for t in vigentes)
    historial = [r["texto"] for r in b.buscar_datos("dónde vive Noe", incluir_antiguos=True)]
    assert any("Madrid" in t for t in historial)


def test_alias_y_unir_por_error_de_oido(b):
    b.recordar("Es amiga de Potro", sobre="Alvita", tipo="persona", cuando=AYER)
    b.recordar("Le gusta el café", sobre="Albita", tipo="persona", cuando=HOY)  # mal oído
    assert b.parecida("Albitta") in ("Alvita", "Albita")
    b.unir("Alvita", "Albita")
    nota = b.buscar_archivo("Albita")  # ahora el alias lleva a la buena
    assert nota is not None and nota.stem == "Alvita"
    texto = nota.read_text(encoding="utf-8")
    assert "aliases: [Albita]" in texto and "amiga" in texto and "café" in texto
    assert not (b.ruta / "Personas" / "Albita.md").exists() and (b.ruta / ".papelera").exists()


def test_olvidar_un_dato_tambien_del_diario(b):
    b.recordar("Está buscando trabajo", sobre="Cristian", tipo="persona", cuando=HOY)
    b.recordar("Juega al pádel", sobre="Cristian", tipo="persona", cuando=HOY)
    b.olvidar("Cristian", "busca trabajo")
    nota = b.buscar_archivo("Cristian").read_text(encoding="utf-8")
    diario = (b.ruta / "Diario" / "2026-11-08.md").read_text(encoding="utf-8")
    assert "trabajo" not in nota and "trabajo" not in diario and "pádel" in nota


def test_olvidar_todo_va_a_la_papelera(b):
    b.recordar("Es un compañero", sobre="Kevin", tipo="persona")
    assert "olvidado todo" in b.olvidar("Kevin")
    assert b.buscar_archivo("Kevin") is None and list((b.ruta / ".papelera").glob("Kevin*.md"))


def test_compromisos(b):
    b.compromiso("Llamar a mamá", para="mañana", persona="Carmen")
    b.compromiso("Devolver el taladro a Jorge")
    assert b.compromisos() == ["Llamar a mamá (para mañana) → [[Carmen]]", "Devolver el taladro a Jorge"]
    assert b.cumplir("llamar a mi madre").startswith("Llamar a mamá")
    assert b.compromisos() == ["Devolver el taladro a Jorge"]


def test_consolidacion_quita_repetidos(b):
    nota = b._nota("Peláez", "persona")
    b._anadir_linea(nota, "- Tiene un perro ([[2026-11-01]])", "Datos")
    b._anadir_linea(nota, "- Tiene un perro. ([[2026-11-05]])", "Datos")
    r = b.consolidar()
    assert r["repetidos"] == 1
    assert len(memoria_indice.datos_de_nota(nota.read_text(encoding="utf-8"))) == 1


def test_busqueda_por_palabras_y_lo_importante_primero(b):
    b.recordar("Le gusta el fútbol", sobre="Sebastián", tipo="persona", cuando=AYER)
    b.recordar("Es alérgico a los frutos secos", sobre="Sebastián", tipo="persona", cuando=AYER, importante=True)
    r = b.buscar_datos("Sebastián")
    assert r[0]["texto"].endswith("alérgico a los frutos secos")


@pytest.mark.skipif(not (Path("modelos").exists()), reason="sin el modelo local de significado")
def test_busqueda_por_significado(tmp_path):
    memoria_indice._modelo = None  # que lo cargue de verdad
    b = bv.Boveda(tmp_path / "Cerebro", indice=tmp_path / "indice.db")
    b.recordar("Cumple años el 3 de mayo", sobre="Carmen", tipo="persona", cuando=AYER)
    b.recordar("Le gusta el Real Madrid", sobre="Potro", tipo="persona", cuando=AYER)
    assert "Real Madrid" in b.buscar_datos("¿de qué equipo de fútbol soy?")[0]["texto"]


@pytest.mark.parametrize("frase, grupo", [
    ("No, eso no es así, Noe vive en Sevilla", "memoria"),
    ("Olvida que Cristian busca trabajo", "memoria"),
    ("¿Qué te he contado hoy?", "memoria"),
    ("Dile a mamá que la llamo mañana", "memoria"),
    ("Ya llamé a mi madre", "memoria"),
])
def test_frases_de_memoria_llevan_sus_herramientas(frase, grupo):
    from jarvis import cerebros

    assert grupo in cerebros.grupos_para(frase)


def test_las_herramientas_de_memoria_existen():
    from jarvis import cerebros
    from jarvis.core import Jarvis

    for h in cerebros.GRUPOS["memoria"]:
        assert hasattr(Jarvis, h), h


def test_compromisos_en_el_resumen():
    from jarvis import resumen

    t = resumen.texto_base({"fecha": HOY, "tiempo": "18 °C", "recordatorios": [], "noticias": [], "whatsapp": [],
                            "compromisos": ["Llamar a mamá (para mañana) → [[Carmen]]"]})
    assert "Compromisos pendientes: Llamar a mamá (para mañana) → Carmen" in t
