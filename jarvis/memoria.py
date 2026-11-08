"""Herramientas de la memoria de verdad: corregir, olvidar, unir, lo de hoy y los compromisos."""

from __future__ import annotations

import asyncio

from livekit.agents import RunContext, function_tool


def _boveda():
    from .core import boveda_activa

    b = boveda_activa()
    if b is None:
        raise RuntimeError("la memoria de Obsidian no está activada (JARVIS_BOVEDA en .env)")
    return b


class Memoria:
    """Mezcla para el agente."""

    @function_tool
    async def corregir_recuerdo(self, context: RunContext, sobre: str, dato_viejo: str, dato_nuevo: str) -> str:
        """Corrige o actualiza algo que JARVIS sabía: "no, eso no es así", "se ha mudado a Sevilla", "ya no trabaja
        allí". Lo viejo queda tachado con su fecha (historial) y lo nuevo pasa a ser lo que vale.

        Args:
            sobre: de quién o de qué (nombre de la nota), p. ej. "Noe".
            dato_viejo: lo que ya no es verdad, p. ej. "vive en Madrid".
            dato_nuevo: lo correcto ahora, en una frase, p. ej. "Vive en Sevilla".
        """
        try:
            nota = await asyncio.to_thread(_boveda().corregir, sobre, dato_viejo, dato_nuevo)
        except (LookupError, RuntimeError) as e:
            return f"No he podido: {e}."
        return f"Corregido en la nota «{nota}»: ahora sé que {dato_nuevo} (lo anterior queda como historial)."

    @function_tool
    async def olvidar(self, context: RunContext, sobre: str, dato: str = "") -> str:
        """Olvida algo cuando el usuario lo pide ("olvida que…", "borra lo de…"). Con `dato`, solo ese dato; sin
        `dato`, TODO lo de esa persona o cosa (solo si lo pide así de claro).

        Args:
            sobre: de quién o de qué (nombre de la nota).
            dato: lo que hay que olvidar. Vacío = todo lo de `sobre`.
        """
        try:
            return "Hecho: " + await asyncio.to_thread(_boveda().olvidar, sobre, dato) + "."
        except (LookupError, RuntimeError) as e:
            return f"No he podido: {e}."

    @function_tool
    async def unir_personas(self, context: RunContext, nombre_bueno: str, nombre_repetido: str) -> str:
        """Une dos notas que son la misma persona o cosa (p. ej. «Albita» era «Alvita», un error de oído). Úsalo
        solo cuando el usuario lo confirme.

        Args:
            nombre_bueno: el nombre correcto, que se queda.
            nombre_repetido: el otro, que pasa a ser un alias.
        """
        try:
            nota = await asyncio.to_thread(_boveda().unir, nombre_bueno, nombre_repetido)
        except (LookupError, RuntimeError) as e:
            return f"No he podido: {e}."
        return f"Unidas: todo está ahora en «{nota}» (y «{nombre_repetido}» queda como otro nombre suyo)."

    @function_tool
    async def que_te_conte_hoy(self, context: RunContext) -> str:
        """Lo que JARVIS ha aprendido hoy (el diario de hoy). Para "¿qué te he contado hoy?"."""
        try:
            hoy = await asyncio.to_thread(_boveda().hoy)
        except RuntimeError as e:
            return str(e)
        return hoy or "Hoy no me ha contado nada nuevo que haya guardado."

    @function_tool
    async def apuntar_compromiso(self, context: RunContext, texto: str, para: str = "", persona: str = "") -> str:
        """Apunta algo que el usuario ha prometido ("dile a mamá que la llamo mañana" → "Llamar a mamá").
        Saldrá en el resumen de la mañana hasta que esté hecho. Ofrécele además un recordatorio.

        Args:
            texto: el compromiso, en infinitivo: "Llamar a mamá".
            para: cuándo, si lo dijo: "mañana", "el viernes".
            persona: con quién, si hay alguien: "Carmen".
        """
        try:
            c = await asyncio.to_thread(_boveda().compromiso, texto, para, persona)
        except RuntimeError as e:
            return str(e)
        return f"Apuntado en tus compromisos: {c}. Pregúntale si quiere también un recordatorio a una hora concreta."

    @function_tool
    async def ver_compromisos(self, context: RunContext) -> str:
        """Los compromisos pendientes del usuario."""
        try:
            lista = await asyncio.to_thread(_boveda().compromisos)
        except RuntimeError as e:
            return str(e)
        return "\n".join(f"- {c}" for c in lista) if lista else "No tiene compromisos pendientes."

    @function_tool
    async def cumplir_compromiso(self, context: RunContext, texto: str) -> str:
        """Marca como hecho un compromiso ("ya llamé a mamá").

        Args:
            texto: el compromiso, aunque sea aproximado.
        """
        try:
            hecho = await asyncio.to_thread(_boveda().cumplir, texto)
        except RuntimeError as e:
            return str(e)
        return f"Marcado como hecho: {hecho}." if hecho else "No tenía compromisos pendientes."
