"""Atajos: órdenes de móvil muy comunes que se hacen al momento, SIN pasar por el cerebro (de ~30 s a ~3 s).

"abre YouTube", "busca música relajante en YouTube", "pon Queen en Spotify", "llévame a Sevilla",
"busca recetas de lentejas en Google". Si la frase no encaja exactamente, no se usa atajo (lo piensa JARVIS).
Ningún atajo hace nada irreversible: solo abre apps y búsquedas.
"""

from __future__ import annotations

import re
import unicodedata
from urllib.parse import quote, quote_plus

_COMIENZO = r"^(?:oye\s+)?(?:jarvis[\s,.]+)?(?:por favor\s+)?"
_MOVIL = r"(?:\s+(?:en|del)\s+(?:el\s+)?movil)?"


def _norm(t: str) -> str:
    t = unicodedata.normalize("NFKD", t or "").encode("ascii", "ignore").decode().lower()
    return re.sub(r"[¿?¡!.,;]+", " ", t).strip()


def _limpio(original: str, normalizado_trozo: str) -> str:
    """Devuelve el trozo con sus acentos originales (para buscar «música», no «musica»)."""
    o = re.sub(r"[¿?¡!.,;]+", " ", original or "").strip()
    i = _norm(o).find(normalizado_trozo)
    return o[i:i + len(normalizado_trozo)].strip() if i >= 0 else normalizado_trozo


_NUMEROS = {"una": 1, "un": 1, "dos": 2, "tres": 3, "cuatro": 4, "cinco": 5, "seis": 6, "siete": 7, "ocho": 8,
            "nueve": 9, "diez": 10, "once": 11, "doce": 12, "quince": 15, "veinte": 20, "treinta": 30,
            "cuarenta": 40, "cuarenta y cinco": 45, "media": 30}


def _num(s: str) -> int | None:
    s = (s or "").strip()
    return int(s) if s.isdigit() else _NUMEROS.get(s)


def hora_de(h: str, m: str | None, parte: str | None) -> str | None:
    """'7', 'media', 'tarde' → '19:30'."""
    hh = _num(h)
    if hh is None or hh > 23:
        return None
    mm = 0 if not m else (30 if m == "media" else 15 if m == "cuarto" else _num(m))
    if mm is None or mm > 59:
        return None
    if parte in ("tarde", "noche") and hh < 12:
        hh += 12
    return f"{hh:02d}:{mm:02d}"


def resolver(texto: str) -> tuple[dict, str] | None:
    """(acción, frase para decir) o None si no hay atajo seguro.
    La acción es de las «manos» ({"tipo": ...}) o del agente del móvil ({"via": "agente", "accion": ..., "valor": ...})."""
    t = _norm(texto)
    m = re.match(_COMIENZO + r"(?:pon(?:me)?|programa|ponme)\s+(?:una\s+)?alarma\s+(?:a|para)\s+las?\s+(\w+)"
                 r"(?:\s*(?::|y|\.)\s*(\w+))?(?:\s+de\s+la\s+(manana|tarde|noche))?" + _MOVIL + r"$", t)
    if m:
        hora = hora_de(m.group(1), m.group(2), m.group(3))
        if hora:
            return {"via": "agente", "accion": "alarma", "valor": hora}, f"Alarma puesta a las {hora}, señor."
    m = re.match(_COMIENZO + r"(?:pon(?:me)?)\s+(?:un\s+)?temporizador\s+de\s+([\w ]+?)\s+(minutos?|horas?)" + _MOVIL + r"$", t)
    if m and _num(m.group(1)):
        minutos = _num(m.group(1)) * (60 if m.group(2).startswith("hora") else 1)
        return ({"via": "agente", "accion": "temporizador", "valor": str(minutos)},
                f"Temporizador de {minutos} minutos en marcha, señor.")
    m = re.match(_COMIENZO + r"(enciende|activa|apaga|desactiva)\s+(?:la\s+)?linterna" + _MOVIL + r"$", t)
    if m:
        on = m.group(1) in ("enciende", "activa")
        return {"via": "agente", "accion": "linterna", "valor": "on" if on else "off"}, \
            f"Linterna {'encendida' if on else 'apagada'}."
    m = re.match(_COMIENZO + r"(sube|baja)(?:me)?\s+(?:el\s+)?volumen" + _MOVIL + r"$", t)
    if m:
        accion = "subir_volumen" if m.group(1) == "sube" else "bajar_volumen"
        return {"via": "agente", "accion": accion, "valor": ""}, "Hecho, señor."
    m = re.match(_COMIENZO + r"(?:haz(?:me)?|saca(?:me)?)\s+(?:una\s+)?captura(?:\s+de\s+pantalla)?" + _MOVIL + r"$", t)
    if m:
        return {"tipo": "captura"}, "Captura hecha, señor."
    m = re.match(_COMIENZO + r"(?:abre|activa|desactiva|enciende|apaga|pon|quita)\s+(?:el\s+|la\s+)?(wifi|wi fi|bluetooth|"
                 r"datos|datos moviles|brillo)" + _MOVIL + r"$", t)
    if m:
        cual = {"wi fi": "wifi", "datos moviles": "datos"}.get(m.group(1), m.group(1))
        return {"tipo": "panel", "panel": cual}, f"Le dejo abierto el {cual}, señor: tóquelo usted o dígame qué hago."
    m = (re.match(_COMIENZO + r"(?:abre youtube y\s+)?(?:busca(?:me)?|pon(?:me)?|reproduce)\s+(.+?)\s+en youtube" + _MOVIL + r"$", t)
         or re.match(_COMIENZO + r"abre youtube" + _MOVIL + r"\s+y\s+(?:busca(?:me)?|pon(?:me)?)\s+(.+)$", t))
    if m:
        q = _limpio(texto, m.group(1))
        return ({"tipo": "enlace", "url": "https://www.youtube.com/results?search_query=" + quote_plus(q)},
                f"Buscando {q} en YouTube, señor.")
    # --- Spotify y música -----------------------------------------------------------------------------
    m = re.match(_COMIENZO + r"(?:pon(?:me)?|reproduce|toca)\s+(.+?)\s+en spotify" + _MOVIL + r"$", t)
    if m:
        q = _limpio(texto, m.group(1))
        return {"tipo": "reproducir", "consulta": q, "app": "Spotify"}, f"Poniendo {q} en Spotify, señor."
    m = re.match(_COMIENZO + r"busca\s+(.+?)\s+en spotify" + _MOVIL + r"$", t)
    if m:
        q = _limpio(texto, m.group(1))
        return {"tipo": "enlace", "url": "spotify:search:" + quote(q)}, f"Buscando {q} en Spotify, señor."
    tecla = None
    if re.match(_COMIENZO + r"(?:pausa|pausa la musica|para la musica|deten la musica|pon pausa|quita la musica)" + _MOVIL + r"$", t):
        tecla, decir = "pausa", "Música en pausa."
    elif re.match(_COMIENZO + r"(?:reanuda|continua|sigue)(?:\s+(?:la\s+)?musica)?" + _MOVIL + r"$", t) or re.match(
            _COMIENZO + r"pon la musica" + _MOVIL + r"$", t):
        tecla, decir = "play", "Seguimos con la música."
    elif re.match(_COMIENZO + r"(?:siguiente(?:\s+cancion)?|pasa(?:\s+de)?\s+(?:la\s+)?cancion|salta(?:\s+la\s+cancion)?|"
                  r"pon la siguiente)" + _MOVIL + r"$", t):
        tecla, decir = "siguiente", "Siguiente canción."
    elif re.match(_COMIENZO + r"(?:(?:la\s+)?cancion anterior|anterior|vuelve a la anterior|pon la anterior)" + _MOVIL + r"$", t):
        tecla, decir = "anterior", "Canción anterior."
    if tecla:
        return {"tipo": "media", "tecla": tecla}, decir
    # --- Maps -----------------------------------------------------------------------------------------
    m = re.match(_COMIENZO + r"(?:llevame|como llego|navega|vamos|guiame)\s+(andando|a pie|en bici|en bicicleta|en coche)?\s*"
                 r"(?:a|hasta|hacia)\s+(.+?)(?:\s+(andando|a pie|en bici|en bicicleta|en coche))?$", t)
    if m:
        q = _limpio(texto, m.group(2))
        modo = (m.group(1) or m.group(3) or "").strip()
        sufijo = "&mode=w" if modo in ("andando", "a pie") else "&mode=b" if "bici" in modo else ""
        return ({"tipo": "enlace", "url": "google.navigation:q=" + quote_plus(q) + sufijo},
                f"Le llevo a {q}, señor.")
    m = re.match(_COMIENZO + r"(?:busca(?:me)?\s+)?(.+?)\s+cerca(?:\s+de\s+(?:mi|aqui))?" + _MOVIL + r"$", t)
    if m and not re.search(r"\b(que|quien|como)\b", m.group(1)):
        q = _limpio(texto, m.group(1))
        return {"tipo": "enlace", "url": "geo:0,0?q=" + quote_plus(q + " cerca")}, f"Buscando {q} cerca, señor."
    m = re.match(_COMIENZO + r"busca(?:me)?\s+(.+?)\s+en (?:google )?maps" + _MOVIL + r"$", t)
    if m:
        q = _limpio(texto, m.group(1))
        return {"tipo": "enlace", "url": "geo:0,0?q=" + quote_plus(q)}, f"Buscando {q} en el mapa, señor."
    # --- Instagram ------------------------------------------------------------------------------------
    m = re.match(_COMIENZO + r"(?:abre|busca(?:me)?|ensename|enseñame|mira)\s+(?:el\s+perfil\s+de\s+|a\s+)?@?([a-z0-9._]{2,30})"
                 r"\s+en instagram" + _MOVIL + r"$", t)
    if m:
        usuario = m.group(1)
        return ({"tipo": "enlace", "url": f"https://www.instagram.com/_u/{usuario}", "app": "Instagram"},
                f"Abriendo el perfil de {usuario} en Instagram, señor.")
    # --- Chrome / Google --------------------------------------------------------------------------------
    m = re.match(_COMIENZO + r"busca(?:me)?\s+(.+?)\s+en (google|chrome|internet)" + _MOVIL + r"$", t)
    if m:
        q = _limpio(texto, m.group(1))
        accion = {"tipo": "enlace", "url": "https://www.google.com/search?q=" + quote_plus(q)}
        if m.group(2) == "chrome":
            accion["app"] = "Chrome"
        return accion, f"Buscando {q}, señor."
    # --- Ajustes ----------------------------------------------------------------------------------------
    m = re.match(_COMIENZO + r"(?:abre|ve a|llevame a)\s+(?:los\s+)?ajustes\s+(?:de\s+|del\s+|de la\s+)?(\w[\w ]*?)" + _MOVIL + r"$", t)
    if m:
        return {"tipo": "ajustes", "pantalla": m.group(1)}, f"Le abro los ajustes de {m.group(1)}, señor."
    m = re.match(_COMIENZO + r"(activa|pon|quita|desactiva)\s+(?:el\s+)?(?:modo\s+)?no molestar" + _MOVIL + r"$", t)
    if m:
        on = m.group(1) in ("activa", "pon")
        return {"tipo": "no_molestar", "estado": "on" if on else "off"}, f"No molestar {'activado' if on else 'desactivado'}."
    m = re.match(_COMIENZO + r"(?:pon|sube|baja)\s+el\s+brillo\s+(?:al|a)\s+(\d{1,3}|maximo|minimo|medio)(?:\s*%|\s+por\s*ciento)?" + _MOVIL + r"$", t)
    if m:
        nivel = {"maximo": 100, "minimo": 5, "medio": 50}.get(m.group(1)) or min(100, int(m.group(1)))
        return {"tipo": "brillo", "nivel": nivel}, f"Brillo al {nivel} por ciento."
    m = re.match(_COMIENZO + r"abre(?:me)?\s+(?:la\s+app\s+(?:de\s+)?|la\s+aplicacion\s+(?:de\s+)?|el\s+|la\s+)?"
                 r"([a-z0-9][a-z0-9 +]{1,24}?)" + _MOVIL + r"$", t)
    if m and not re.search(r"\b(y|que|para|con|a|de)\b", m.group(1)) and m.group(1) not in ("pc", "ordenador"):
        app = _limpio(texto, m.group(1))
        return {"tipo": "abrir", "app": app}, f"Abriendo {app}, señor."
    return None
