"""El "cerebro" de JARVIS: una bóveda de Obsidian (notas Markdown enlazadas).

Estructura (se ve como un grafo en Obsidian → Vista de grafo):

    JARVIS - Cerebro/
      Inicio.md                    índice principal: enlaza a todos los índices
      Personas.md, Lugares.md…     índices (MOC) de cada tipo
      Personas/Carmen.md           una nota por persona, lugar, proyecto, gusto o evento
      Diario/2026-11-07.md         lo que JARVIS ha aprendido cada día

Cada nota tiene propiedades (tipo, etiquetas, fechas), los datos con su fecha y enlaces [[…]] a las notas
relacionadas, al índice de su tipo y al día del diario. JARVIS actualiza las notas que ya existen en vez de
duplicarlas, y busca en toda la bóveda (búsqueda de texto rápida con SQLite) antes de contestar sobre tu vida.
"""

from __future__ import annotations

import os
import re
import sqlite3
import unicodedata
from datetime import datetime
from pathlib import Path

TIPOS = {  # tipo → carpeta e índice
    "persona": "Personas", "lugar": "Lugares", "proyecto": "Proyectos", "gusto": "Gustos",
    "evento": "Eventos", "general": "Notas",
}
SINONIMOS = {
    "personas": "persona", "familia": "persona", "amigo": "persona", "contacto": "persona",
    "lugares": "lugar", "sitio": "lugar", "proyectos": "proyecto", "trabajo": "proyecto",
    "gustos": "gusto", "preferencia": "gusto", "preferencias": "gusto",
    "eventos": "evento", "fechas": "evento", "fecha": "evento", "plan": "evento", "planes": "evento",
    "cita": "evento", "cumpleanos": "evento",
}
_PROHIBIDOS = re.compile(r'[\\/:*?"<>|#^\[\]]')


def ruta_por_defecto() -> Path:
    return Path(os.getenv("JARVIS_BOVEDA", "").strip() or Path.home() / "Documents" / "JARVIS - Cerebro")


def normalizar_tipo(tipo: str | None) -> str:
    t = unicodedata.normalize("NFKD", (tipo or "general")).encode("ascii", "ignore").decode().lower().strip()
    return t if t in TIPOS else SINONIMOS.get(t, "general")


def nombre_de_nota(nombre: str) -> str:
    """Nombre válido de archivo/enlace: 'carmen (mi madre)' → 'Carmen (mi madre)'."""
    limpio = re.sub(r"\s+", " ", _PROHIBIDOS.sub("", nombre or "")).strip(" .")
    return (limpio[:1].upper() + limpio[1:])[:80] if limpio else ""


def _clave(texto: str) -> str:
    return unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode().lower().strip()


class Boveda:
    def __init__(self, ruta: str | Path | None = None, indice: str | Path | None = None) -> None:
        self.ruta = Path(ruta) if ruta else ruta_por_defecto()
        self.ruta.mkdir(parents=True, exist_ok=True)
        self._preparar()
        self._db = sqlite3.connect(str(indice or self.ruta / ".obsidian" / "jarvis_indice.db"), check_same_thread=False)
        self._db.executescript(
            "CREATE VIRTUAL TABLE IF NOT EXISTS notas USING fts5(nombre, ruta UNINDEXED, texto);"
            "CREATE TABLE IF NOT EXISTS fechas (ruta TEXT PRIMARY KEY, mtime REAL);"
        )

    # --- Estructura -------------------------------------------------------------------------

    def _preparar(self) -> None:
        (self.ruta / ".obsidian").mkdir(exist_ok=True)
        for carpeta in list(TIPOS.values()) + ["Diario"]:
            (self.ruta / carpeta).mkdir(exist_ok=True)
        inicio = self.ruta / "Inicio.md"
        if not inicio.exists():
            indices = "\n".join(f"- [[{c}]]" for c in TIPOS.values())
            inicio.write_text(
                "---\ntags: [jarvis, indice]\n---\n# 🧠 Cerebro de JARVIS\n\n"
                "Todo lo que JARVIS sabe, enlazado. Abre la **Vista de grafo** para verlo conectado.\n\n"
                f"## Índices\n{indices}\n- [[Diario]]\n", encoding="utf-8")
        for carpeta in list(TIPOS.values()) + ["Diario"]:
            moc = self.ruta / f"{carpeta}.md"
            if not moc.exists():
                moc.write_text(f"---\ntags: [jarvis, indice]\n---\n# {carpeta}\n\nVuelve a [[Inicio]].\n\n", encoding="utf-8")

    def buscar_archivo(self, nombre: str) -> Path | None:
        """Nota existente con ese nombre (sin distinguir mayúsculas ni tildes), en cualquier carpeta."""
        objetivo = _clave(nombre_de_nota(nombre))
        if not objetivo:
            return None
        for p in self.ruta.rglob("*.md"):
            if _clave(p.stem) == objetivo and ".obsidian" not in p.parts:
                return p
        return None

    def _nota(self, nombre: str, tipo: str) -> Path:
        existente = self.buscar_archivo(nombre)
        if existente:
            return existente
        nombre = nombre_de_nota(nombre)
        carpeta = TIPOS[tipo]
        p = self.ruta / carpeta / f"{nombre}.md"
        hoy = datetime.now().strftime("%Y-%m-%d")
        p.write_text(
            f"---\ntipo: {tipo}\ncreado: {hoy}\nactualizado: {hoy}\ntags: [jarvis, {tipo}]\n---\n"
            f"# {nombre}\n\nTipo: [[{carpeta}]]\n\n## Datos\n\n## Relacionado\n", encoding="utf-8")
        self._anadir_linea(self.ruta / f"{carpeta}.md", f"- [[{nombre}]]")
        return p

    @staticmethod
    def _anadir_linea(archivo: Path, linea: str, seccion: str | None = None) -> bool:
        """Añade `linea` (si no estaba) al final de la sección indicada o del archivo."""
        texto = archivo.read_text(encoding="utf-8") if archivo.exists() else ""
        if linea.strip() in (l.strip() for l in texto.splitlines()):
            return False
        if seccion and f"## {seccion}" in texto:
            antes, _, despues = texto.partition(f"## {seccion}")
            siguiente = despues.find("\n## ")
            cuerpo, resto = (despues, "") if siguiente == -1 else (despues[:siguiente], despues[siguiente:])
            texto = f"{antes}## {seccion}{cuerpo.rstrip()}\n{linea}\n{resto}"
        else:
            texto = texto.rstrip("\n") + f"\n{linea}\n"
        archivo.write_text(texto, encoding="utf-8")
        return True

    @staticmethod
    def _tocar_fecha(archivo: Path) -> None:
        texto = archivo.read_text(encoding="utf-8")
        hoy = datetime.now().strftime("%Y-%m-%d")
        archivo.write_text(re.sub(r"(?m)^actualizado: .*$", f"actualizado: {hoy}", texto, count=1), encoding="utf-8")

    def _diario(self, cuando: datetime) -> Path:
        dia = cuando.strftime("%Y-%m-%d")
        p = self.ruta / "Diario" / f"{dia}.md"
        if not p.exists():
            p.write_text(f"---\ntipo: diario\ntags: [jarvis, diario]\n---\n# {dia}\n\nParte del [[Diario]].\n\n",
                         encoding="utf-8")
            self._anadir_linea(self.ruta / "Diario.md", f"- [[{dia}]]")
        return p

    # --- Escribir ---------------------------------------------------------------------------

    def recordar(self, hecho: str, sobre: str = "", tipo: str = "general",
                 relacionados: list[str] | None = None, cuando: datetime | None = None) -> str:
        """Guarda un dato en la nota de `sobre` (la crea si no existe) y lo enlaza con todo lo relacionado."""
        hecho = re.sub(r"\s+", " ", (hecho or "")).strip()
        if not hecho:
            raise ValueError("No se puede guardar un recuerdo vacío")
        cuando = cuando or datetime.now()
        tipo = normalizar_tipo(tipo)
        relacionados = [r for r in (nombre_de_nota(x) for x in relacionados or []) if r]
        principal = nombre_de_nota(sobre) or None

        dia = cuando.strftime("%Y-%m-%d")
        if principal:
            nota = self._nota(principal, tipo)
            enlaces = "".join(f" · [[{r}]]" for r in relacionados)
            self._anadir_linea(nota, f"- {hecho} ([[{dia}]]){enlaces}", "Datos")
            for r in relacionados:
                self._anadir_linea(nota, f"- [[{r}]]", "Relacionado")
                otra = self._nota(r, "general") if not self.buscar_archivo(r) else self.buscar_archivo(r)
                self._anadir_linea(otra, f"- [[{nota.stem}]]", "Relacionado")
            self._tocar_fecha(nota)
            destino = nota.stem
        else:
            destino = None
        enlace = f" → [[{destino}]]" if destino else "".join(f" [[{r}]]" for r in relacionados)
        self._anadir_linea(self._diario(cuando), f"- {cuando:%H:%M} {hecho}{enlace}")
        self.indexar()
        return destino or f"Diario {dia}"

    # --- Leer ---------------------------------------------------------------------------------

    def indexar(self) -> None:
        """Pone al día el índice de búsqueda con las notas nuevas o cambiadas (también las que edites tú)."""
        vistos = set()
        for p in self.ruta.rglob("*.md"):
            if ".obsidian" in p.parts:
                continue
            rel = str(p.relative_to(self.ruta))
            vistos.add(rel)
            mtime = p.stat().st_mtime
            fila = self._db.execute("SELECT mtime FROM fechas WHERE ruta = ?", (rel,)).fetchone()
            if fila and fila[0] == mtime:
                continue
            self._db.execute("DELETE FROM notas WHERE ruta = ?", (rel,))
            self._db.execute("INSERT INTO notas (nombre, ruta, texto) VALUES (?, ?, ?)",
                             (p.stem, rel, p.read_text(encoding="utf-8", errors="replace")))
            self._db.execute("INSERT OR REPLACE INTO fechas (ruta, mtime) VALUES (?, ?)", (rel, mtime))
        for (rel,) in self._db.execute("SELECT ruta FROM fechas").fetchall():
            if rel not in vistos:
                self._db.execute("DELETE FROM notas WHERE ruta = ?", (rel,))
                self._db.execute("DELETE FROM fechas WHERE ruta = ?", (rel,))
        self._db.commit()

    def buscar(self, consulta: str, limite: int = 5) -> list[tuple[str, str]]:
        """(nombre de nota, fragmento) de las notas que mejor encajan."""
        self.indexar()
        palabras = re.findall(r"\w+", _clave(consulta))
        if not palabras:
            return []
        match = " OR ".join(f'"{w}"*' for w in palabras)
        filas = self._db.execute(
            "SELECT nombre, snippet(notas, 2, '«', '»', '…', 24) FROM notas WHERE notas MATCH ? "
            "ORDER BY bm25(notas, 5.0, 0.0, 1.0) LIMIT ?", (match, limite)).fetchall()
        return [(n, s.replace("\n", " ")) for n, s in filas]

    def leer(self, nombre: str, max_caracteres: int = 2500) -> str | None:
        p = self.buscar_archivo(nombre)
        if not p:
            return None
        texto = re.sub(r"(?s)^---.*?---\n", "", p.read_text(encoding="utf-8"))
        return texto if len(texto) <= max_caracteres else texto[:max_caracteres] + "\n…"

    @staticmethod
    def enlaces(texto: str) -> list[str]:
        return list(dict.fromkeys(re.findall(r"\[\[([^\]|#]+)", texto or "")))

    def close(self) -> None:
        self._db.close()


def migrar(boveda: Boveda, memory) -> int:
    """Pasa a la bóveda los recuerdos y contactos antiguos (de la base de datos SQLite). Solo una vez."""
    marca = boveda.ruta / ".obsidian" / "jarvis_migrado"
    if marca.exists():
        return 0
    n = 0
    for m in reversed(memory.recent(1000)):
        cuando = datetime.fromisoformat(m.created_at).astimezone()
        boveda.recordar(m.text, tipo=m.category, cuando=cuando)
        n += 1
    for _clave_, nombre, numero in memory.contacts():
        if _clave(nombre) in ("yo", "mi movil", "movil"):
            continue
        boveda.recordar(f"Teléfono: {numero}", sobre=nombre, tipo="persona")
        n += 1
    marca.write_text(datetime.now().isoformat(), encoding="utf-8")
    return n
