"""Atajos de órdenes comunes del móvil (sin pasar por el cerebro)."""

import pytest

from jarvis import atajos


@pytest.mark.parametrize("frase, tipo, contiene", [
    ("Abre YouTube y busca música relajante", "enlace", "youtube.com/results?search_query=m%C3%BAsica+relajante"),
    ("Jarvis, busca música relajante en YouTube.", "enlace", "search_query=m%C3%BAsica+relajante"),
    ("Abre YouTube en el móvil y busca música relajante", "enlace", "search_query=m%C3%BAsica+relajante"),
    ("Busca Queen en Spotify", "enlace", "spotify:search:Queen"),
    ("Llévame a Sevilla", "enlace", "google.navigation:q=Sevilla"),
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


@pytest.mark.parametrize("frase, esperado", [
    ("Pon Queen en Spotify", {"tipo": "reproducir", "consulta": "Queen", "app": "Spotify"}),
    ("Pausa la música", {"tipo": "media", "tecla": "pausa"}),
    ("Siguiente canción", {"tipo": "media", "tecla": "siguiente"}),
    ("Canción anterior", {"tipo": "media", "tecla": "anterior"}),
    ("Reanuda la música", {"tipo": "media", "tecla": "play"}),
    ("Llévame andando a la Plaza Mayor", {"tipo": "enlace", "url": "google.navigation:q=la+Plaza+Mayor&mode=w"}),
    ("Busca gasolineras cerca", {"tipo": "enlace", "url": "geo:0,0?q=gasolineras+cerca"}),
    ("Abre el perfil de cristiano en Instagram",
     {"tipo": "enlace", "url": "https://www.instagram.com/_u/cristiano", "app": "Instagram"}),
    ("Busca recetas de lentejas en Chrome",
     {"tipo": "enlace", "url": "https://www.google.com/search?q=recetas+de+lentejas", "app": "Chrome"}),
    ("Abre los ajustes de batería", {"tipo": "ajustes", "pantalla": "bateria"}),
    ("Activa el no molestar", {"tipo": "no_molestar", "estado": "on"}),
    ("Quita el modo no molestar", {"tipo": "no_molestar", "estado": "off"}),
    ("Pon el brillo al 70", {"tipo": "brillo", "nivel": 70}),
    ("Pon el brillo al máximo", {"tipo": "brillo", "nivel": 100}),
])
def test_atajos_de_las_apps(frase, esperado):
    assert atajos.resolver(frase)[0] == esperado


def test_para_la_musica_no_es_la_parada_de_emergencia():
    from jarvis.parada import es_parada

    assert not es_parada("Para la música") and atajos.resolver("Para la música")[0] == {"tipo": "media", "tecla": "pausa"}