"""Cerebros (modelos de lenguaje) de JARVIS y cómo ahorrar en cada mensaje.

1. Proveedores, por orden de preferencia: Claude (si hay clave) y después los gratuitos
   Gemini → Mistral → Cerebras → Groq. Si uno se queda sin cupo (error 429) o falla, JARVIS pasa
   al siguiente sin cortar la conversación, y vuelve al primero cuando se recupera.
2. El modelo de cada proveedor se elige solo, preguntando al proveedor qué modelos tiene
   (los nombres cambian a menudo). Se puede fijar a mano con JARVIS_<PROVEEDOR>_MODEL.
3. Herramientas por grupos: en cada mensaje solo se mandan las que hacen falta
   (las descripciones de herramientas son lo que más gasta).
"""

from __future__ import annotations

import logging
import os
import re
import unicodedata
from dataclasses import dataclass

import httpx

log = logging.getLogger("jarvis.cerebros")


@dataclass(frozen=True)
class Proveedor:
    nombre: str
    clave: str            # variable de entorno con la API key
    base_url: str
    modelo_env: str       # variable para fijar el modelo a mano
    preferencias: tuple[str, ...]  # patrones (regex) de modelos, del mejor al peor
    defecto: str          # si no se puede preguntar al proveedor


GRATUITOS = (
    Proveedor("gemini", "GEMINI_API_KEY", "https://generativelanguage.googleapis.com/v1beta/openai/",
              "JARVIS_GEMINI_MODEL", (r"gemini-[\d.]+-flash$", r"gemini-[\d.]+-flash-latest$",
                                      r"gemini-flash-latest$", r"gemini-[\d.]+-flash-preview"),
              "gemini-2.5-flash"),
    Proveedor("mistral", "MISTRAL_API_KEY", "https://api.mistral.ai/v1",
              "JARVIS_MISTRAL_MODEL", (r"^mistral-medium-latest$", r"^mistral-small-latest$", r"^mistral-large-latest$"),
              "mistral-medium-latest"),
    Proveedor("cerebras", "CEREBRAS_API_KEY", "https://api.cerebras.ai/v1",
              "JARVIS_CEREBRAS_MODEL", (r"^gpt-oss-120b$", r"qwen-3.*235b", r"llama-?3\.3-70b"),
              "gpt-oss-120b"),
    Proveedor("groq", "GROQ_API_KEY", "https://api.groq.com/openai/v1",
              "JARVIS_GROQ_MODEL", (r"^openai/gpt-oss-120b$", r"^qwen/qwen3", r"llama-?3\.3-70b"),
              "openai/gpt-oss-120b"),
    # En Groq cada modelo tiene su propio cupo diario: con la misma clave, otro modelo es otra reserva
    Proveedor("groq_qwen", "GROQ_API_KEY", "https://api.groq.com/openai/v1",
              "JARVIS_GROQ2_MODEL", (r"^qwen/qwen3",), "qwen/qwen3.8-27b"),
)
POR_NOMBRE = {p.nombre: p for p in GRATUITOS}
# "livekit": el servicio de modelos incluido en LiveKit Cloud (usa las mismas claves que la voz; sin clave extra)
ORDEN = ("claude", "livekit") + tuple(p.nombre for p in GRATUITOS)
CLAVES = {"claude": "ANTHROPIC_API_KEY", "livekit": "LIVEKIT_API_SECRET", **{p.nombre: p.clave for p in GRATUITOS}}
MODELO_LIVEKIT = "google/gemini-2.5-flash"


def livekit_cloud(env=os.environ) -> bool:
    return ".livekit.cloud" in env.get("LIVEKIT_URL", "") and bool(env.get("LIVEKIT_API_KEY", "").strip())


def disponibles(env=os.environ) -> list[str]:
    """Proveedores con clave, en orden de preferencia."""
    return [n for n in ORDEN if env.get(CLAVES[n], "").strip() and (n != "livekit" or livekit_cloud(env))]


def _version(modelo: str) -> tuple[float, ...]:
    return tuple(float(x) for x in re.findall(r"\d+(?:\.\d+)?", modelo)[:2]) or (0.0,)


def elegir_modelo(prov: Proveedor, ids: list[str]) -> str:
    """El mejor modelo de `ids` según las preferencias; a igualdad, el de versión más alta."""
    limpios = [i.removeprefix("models/") for i in ids]
    for patron in prov.preferencias:
        candidatos = [i for i in limpios if re.search(patron, i) and not re.search(r"lite|image|tts|audio|live|embed", i)]
        if candidatos:
            return max(candidatos, key=_version)
    return prov.defecto


_modelos_cache: dict[str, str] = {}


def modelo_de(prov: Proveedor) -> str:
    fijado = os.getenv(prov.modelo_env, "").strip()
    if fijado:
        return fijado
    if prov.nombre not in _modelos_cache:
        try:
            r = httpx.get(prov.base_url.rstrip("/") + "/models", timeout=10,
                          headers={"Authorization": f"Bearer {os.environ[prov.clave].strip()}"})
            r.raise_for_status()
            ids = [m["id"] for m in r.json().get("data", [])]
            _modelos_cache[prov.nombre] = elegir_modelo(prov, ids)
        except Exception as e:  # sin red o clave mala: el de por defecto (y el fallo se verá al usarlo)
            log.warning("No pude listar los modelos de %s (%s); uso %s", prov.nombre, type(e).__name__, prov.defecto)
            _modelos_cache[prov.nombre] = prov.defecto
    return _modelos_cache[prov.nombre]


# --- Herramientas por grupos -------------------------------------------------------------------

GRUPOS = {
    "basicas": {"recordar", "buscar_recuerdos", "leer_nota", "fecha_y_hora", "estado_jarvis"},
    "llamadas": {"guardar_contacto", "llamar"},
    "pc": {"abrir_programa", "abrir_web", "buscar_archivo", "enviar_archivo", "multimedia", "captura_pantalla",
           "estado_pc", "bloquear_pc", "accion_pc_delicada"},
    "movil": {"movil_info", "movil_hacer", "movil_mensaje", "guardar_contacto", "leer_whatsapp", "leer_chat_whatsapp", "usar_movil"},
    "internet": {"buscar_en_internet", "leer_pagina", "noticias", "tiempo"},
    "memoria": {"corregir_recuerdo", "olvidar", "unir_personas", "que_te_conte_hoy", "apuntar_compromiso",
                "ver_compromisos", "cumplir_compromiso", "leer_nota"},
    "recordatorios": {"programar_recordatorio", "ver_recordatorios", "borrar_recordatorio", "configurar_resumen"},
}
PALABRAS = {
    "llamadas": r"llam|telefon|contacto|agenda|numero",
    "movil": r"movil|celular|whats|sms|mensaje|notificaci|linterna|alarma|despierta|temporizador|ubicaci|donde esta"
             r"|donde estoy|suena|sonar|vibra|foto|camara|bateria del|escrito|me ha(n)? dicho|sin leer|respond|contesta",
    "pc": r"\bpc\b|ordenador|portatil|abre|abrir|programa|\bweb\b|pagina|busca|archivo|fichero|documento|pdf|carpeta"
          r"|volumen|musica|cancion|pausa|siguiente|pantalla|captura|bloquea|apaga|reinicia|suspende|cierra|escribe"
          r"|comando|google|youtube|navegador|descarga|manda(me)?l|envia(me)?l|bateria|memoria|disco",
    "internet": r"internet|busca|buscar|google|noticia|actualidad|tiempo hace|que tiempo|el tiempo|clima|llover|llueve"
                r"|temperatura|precio|cuesta|cuanto vale|cotiza|bitcoin|bolsa|resultado|partido|gano|quien gan|marcador"
                r"|quien es|que es |que son|como se|donde esta (el|la)|horario|abre hoy|cierra hoy|pelicula|estreno"
                r"|receta|ultim|hoy|ahora mismo|actual|web|pagina|http|www\.|\.com|investiga|averigua|informa(me|cion)",
    "memoria": r"olvida|corrig|no es asi|eso no es|te equivocas|se ha mudado|ya no (vive|trabaja|esta)|que sabes de"
               r"|que te he contado|que te conte|compromiso|prometi|le he dicho que|le dije que|dile a .* que (le|la|lo)"
               r"|es la misma persona|son la misma|apunta que|cumplido|ya (le |la )?llame|ya lo hice",
    "recordatorios": r"recuerda(me|le)|recordatorio|avisa(me)?|no se me olvide|no me dejes olvidar|alarma de"
                     r"|dentro de \d+|en \d+ (minuto|hora)|a las \d|resumen",
}


def _normalizar(texto: str) -> str:
    return unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode().lower()


MENCIONA_PC = r"\bpc\b|ordenador|portatil|computador"
MENSAJE_ESCRITO = r"whats|wasap|\bsms\b|mensaje|escribele|escribirle|mandale|enviale|mandarle|enviarle|dile por|respondele|contestale|responde a|contesta a"


def grupos_para(texto: str, usados_antes: set[str] = frozenset(), preferir_movil: bool = False) -> set[str]:
    """Qué grupos de herramientas necesita un mensaje (más los del turno anterior, para seguir el hilo).

    Con `preferir_movil` (hablando desde el móvil), "abre YouTube" o "sube el volumen" van al móvil
    salvo que se diga "en el PC" / "en el ordenador".
    """
    t = _normalizar(texto)
    grupos = {"basicas"} | {g for g, patron in PALABRAS.items() if re.search(patron, t)}
    es_mensaje = bool(re.search(MENSAJE_ESCRITO, t))
    if es_mensaje:
        grupos |= {"movil"}  # "escríbele a mamá…", "mándale un mensaje a Juan…" son mensajes del móvil
        grupos.discard("pc")
    elif "llamadas" in grupos and re.search(r"\bllam|telefonea", t):
        # "Llama a…" es una llamada: no arrastrar los mensajes del móvil del turno anterior
        usados_antes = set(usados_antes) - {"movil"}
    if preferir_movil and "pc" in grupos and not re.search(MENCIONA_PC, t):
        grupos = (grupos - {"pc"}) | {"movil"}
        usados_antes = set(usados_antes) - {"pc"}
    if "movil" in grupos and not re.search(r"\bpc\b|ordenador|portatil", t):
        # "sube el volumen del móvil", "abre whatsapp en el móvil": no hace falta el PC
        if re.search(r"movil|celular", t):
            grupos.discard("pc")
    return grupos | set(usados_antes)


def herramientas_de(grupos: set[str]) -> set[str]:
    return set().union(*(GRUPOS[g] for g in grupos))


def grupos_de_herramientas(nombres: set[str]) -> set[str]:
    return {g for g, hs in GRUPOS.items() if g != "basicas" and hs & nombres}
