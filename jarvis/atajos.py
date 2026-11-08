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


def resolver(texto: str) -> tuple[dict, str] | None:
    """(acción de las «manos», frase para decir) o None si no hay atajo seguro."""
    t = _norm(texto)
    m = (re.match(_COMIENZO + r"(?:abre youtube y\s+)?(?:busca(?:me)?|pon(?:me)?|reproduce)\s+(.+?)\s+en youtube" + _MOVIL + r"$", t)
         or re.match(_COMIENZO + r"abre youtube" + _MOVIL + r"\s+y\s+(?:busca(?:me)?|pon(?:me)?)\s+(.+)$", t))
    if m:
        q = _limpio(texto, m.group(1))
        return ({"tipo": "enlace", "url": "https://www.youtube.com/results?search_query=" + quote_plus(q)},
                f"Buscando {q} en YouTube, señor.")
    m = re.match(_COMIENZO + r"(?:pon(?:me)?|reproduce|busca)\s+(.+?)\s+en spotify" + _MOVIL + r"$", t)
    if m:
        q = _limpio(texto, m.group(1))
        return {"tipo": "enlace", "url": "spotify:search:" + quote(q)}, f"Buscando {q} en Spotify, señor."
    m = re.match(_COMIENZO + r"(?:llevame|como llego|navega|vamos)\s+(?:a|hasta|hacia)\s+(.+)$", t)
    if m:
        q = _limpio(texto, m.group(1))
        return ({"tipo": "enlace", "url": "https://www.google.com/maps/dir/?api=1&destination=" + quote_plus(q)},
                f"Le llevo a {q}, señor.")
    m = re.match(_COMIENZO + r"busca(?:me)?\s+(.+?)\s+en google" + _MOVIL + r"$", t)
    if m:
        q = _limpio(texto, m.group(1))
        return {"tipo": "enlace", "url": "https://www.google.com/search?q=" + quote_plus(q)}, f"Buscando {q}, señor."
    m = re.match(_COMIENZO + r"abre(?:me)?\s+(?:la\s+app\s+(?:de\s+)?|la\s+aplicacion\s+(?:de\s+)?|el\s+|la\s+)?"
                 r"([a-z0-9][a-z0-9 +]{1,24}?)" + _MOVIL + r"$", t)
    if m and not re.search(r"\b(y|que|para|con|a|de)\b", m.group(1)) and m.group(1) not in ("pc", "ordenador"):
        app = _limpio(texto, m.group(1))
        return {"tipo": "abrir", "app": app}, f"Abriendo {app}, señor."
    return None
