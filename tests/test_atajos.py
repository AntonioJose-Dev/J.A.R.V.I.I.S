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
