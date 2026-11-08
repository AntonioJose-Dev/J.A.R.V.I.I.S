"""Atajos de órdenes comunes del móvil (sin pasar por el cerebro)."""

import pytest

from jarvis import atajos


@pytest.mark.parametrize("frase, tipo, contiene", [
    ("Abre YouTube y busca música relajante", "enlace", "youtube.com/results?search_query=m%C3%BAsica+relajante"),
    ("Jarvis, busca música relajante en YouTube.", "enlace", "search_query=m%C3%BAsica+relajante"),
    ("Abre YouTube en el móvil y busca música relajante", "enlace", "search_query=m%C3%BAsica+relajante"),
    ("Pon Queen en Spotify", "enlace", "spotify:search:Queen"),
    ("Llévame a Sevilla", "enlace", "destination=Sevilla"),
    ("Busca recetas de lentejas en Google", "enlace", "google.com/search?q=recetas+de+lentejas"),
    ("Abre YouTube", "abrir", "YouTube"),
    ("Abre la app de Notas", "abrir", "Notas"),
    ("Oye Jarvis, abre Instagram", "abrir", "Instagram"),
])
def test_atajos(frase, tipo, contiene):
    accion, decir = atajos.resolver(frase)
    assert accion["tipo"] == tipo and contiene in (accion.get("url") or accion.get("app")) and decir


@pytest.mark.parametrize("frase, accion, valor", [
    ("Pon una alarma a las 7", "alarma", "07:00"),
    ("Ponme una alarma a las siete y media", "alarma", "07:30"),
    ("Pon una alarma para las 8:15 de la tarde", "alarma", "20:15"),
    ("Pon un temporizador de 10 minutos", "temporizador", "10"),
    ("Ponme un temporizador de cinco minutos", "temporizador", "5"),
    ("Pon un temporizador de una hora", "temporizador", "60"),
    ("Enciende la linterna", "linterna", "on"),
    ("Apaga la linterna", "linterna", "off"),
    ("Sube el volumen", "subir_volumen", ""),
    ("Baja el volumen del móvil", "bajar_volumen", ""),
])
def test_atajos_del_agente(frase, accion, valor):
    a, decir = atajos.resolver(frase)
    assert a == {"via": "agente", "accion": accion, "valor": valor} and decir


@pytest.mark.parametrize("frase, tipo", [
    ("Haz una captura de pantalla", "captura"), ("Hazme una captura", "captura"),
    ("Activa el wifi", "panel"), ("Abre el bluetooth", "panel"), ("Sube el brillo", None),
])
def test_atajos_de_las_manos(frase, tipo):
    r = atajos.resolver(frase)
    assert (r[0]["tipo"] if r else None) == tipo


@pytest.mark.parametrize("frase", [
    "Abre YouTube y dime qué vídeo es el más visto",      # no es una búsqueda simple: lo piensa JARVIS
    "Abre la puerta del garaje y enciende la luz",
    "Abre el PC",                                          # el PC no es una app del móvil
    "Mándale un WhatsApp a mi madre",
    "¿Qué tiempo hace?",
    "Abre WhatsApp y escríbele a Noe",
])
def test_sin_atajo(frase):
    assert atajos.resolver(frase) is None
