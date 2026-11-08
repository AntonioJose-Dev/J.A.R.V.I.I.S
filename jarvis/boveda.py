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
        from .memoria_indice import Indice

        # Índice de cada dato (palabras + significado). Va junto a la bóveda; la verdad son las notas.
        self.indice = Indice(Path(indice).with_name("jarvis_hechos.db") if indice
                             else self.ruta / ".obsidian" / "jarvis_hechos.db")

    def buscar_datos(self, consulta: str, limite: int = 6, incluir_antiguos: bool = False) -> list[dict]:
        """Los datos que mejor responden (búsqueda híbrida: palabras + significado + recientes + importantes)."""
        self.indice.reindexar(self.ruta)
        return self.indice.buscar(consulta, limite, incluir_antiguos)

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

    def _notas(self):
        for p in self.ruta.rglob("*.md"):
            if ".obsidian" not in p.parts and ".papelera" not in p.parts:
                yield p

    @staticmethod
    def alias_de(p: Path) -> list[str]:
        """Los otros nombres de una nota (propiedad «aliases» de Obsidian)."""
        m = re.search(r"(?m)^aliases:\s*\[(.*?)\]\s*$", p.read_text(encoding="utf-8", errors="replace")[:600])
        return [a.strip().strip("\"'") for a in m.group(1).split(",") if a.strip()] if m else []

    def buscar_archivo(self, nombre: str) -> Path | None:
        """Nota existente con ese nombre o alias (sin distinguir mayúsculas ni tildes), en cualquier carpeta."""
        objetivo = _clave(nombre_de_nota(nombre))
        if not objetivo:
            return None
        for p in self._notas():
            if _clave(p.stem) == objetivo:
                return p
        for p in self._notas():
            if p.parent != self.ruta and objetivo in (_clave(a) for a in self.alias_de(p)):
                return p
        return None

    def parecida(self, nombre: str, umbral: float = 0.78) -> str | None:
        """Una nota con un nombre MUY parecido (p. ej. «Albita» → «Alvita», error de oído). None si no hay."""
        import difflib

        objetivo = _clave(nombre_de_nota(nombre))
        if not objetivo or self.buscar_archivo(nombre):
            return None
        mejor, puntos = None, 0.0
        for p in self._notas():
            if p.parent == self.ruta or "Diario" in p.parts:
                continue
            for candidato in [p.stem] + self.alias_de(p):
                r = difflib.SequenceMatcher(None, objetivo, _clave(candidato)).ratio()
                if r > puntos:
                    mejor, puntos = p.stem, r
        return mejor if puntos >= umbral else None

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

    def dato_parecido(self, nota: Path, hecho: str, umbral: float = 0.88) -> str | None:
        """Un dato VIGENTE de la nota que dice casi lo mismo (para no guardar duplicados)."""
        import difflib

        from .memoria_indice import datos_de_nota

        objetivo = _clave(hecho)
        for d in datos_de_nota(nota.read_text(encoding="utf-8")):
            if d["vigente"] and difflib.SequenceMatcher(None, objetivo, _clave(d["texto"])).ratio() >= umbral:
                return d["texto"]
        return None

    def recordar(self, hecho: str, sobre: str = "", tipo: str = "general",
                 relacionados: list[str] | None = None, cuando: datetime | None = None,
                 importante: bool = False) -> str:
        """Guarda un dato en la nota de `sobre` (la crea si no existe) y lo enlaza con todo lo relacionado.
        Si ya lo sabía (dato casi igual), no lo repite."""
        hecho = re.sub(r"\s+", " ", (hecho or "")).strip()
        if not hecho:
            raise ValueError("No se puede guardar un recuerdo vacío")
        cuando = cuando or datetime.now()
        tipo = normalizar_tipo(tipo)
        relacionados = [r for r in (nombre_de_nota(x) for x in relacionados or []) if r]
        principal = nombre_de_nota(sobre) or None

        dia = cuando.strftime("%Y-%m-%d")
        if principal:
            existente = self.buscar_archivo(principal)
            if existente and self.dato_parecido(existente, hecho):
                return existente.stem  # ya lo sabía: no se duplica
            nota = self._nota(principal, tipo)
            enlaces = "".join(f" · [[{r}]]" for r in relacionados)
            self._anadir_linea(nota, f"- {hecho}{' ⭐' if importante else ''} ([[{dia}]]){enlaces}", "Datos")
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

    # --- Corregir, olvidar, unir ----------------------------------------------------------------

    def _linea_mas_parecida(self, nota: Path, texto: str) -> tuple[str, float] | None:
        """La línea de «## Datos» (vigente) que más se parece a `texto`."""
        import difflib

        objetivo = _clave(texto)
        mejor = None
        en_datos = False
        for linea in nota.read_text(encoding="utf-8").splitlines():
            if linea.startswith("## "):
                en_datos = linea.strip() == "## Datos"
                continue
            if en_datos and linea.startswith("- ") and not linea.startswith("- ~~"):
                cuerpo = re.sub(r"\s*\(\[\[\d{4}-\d{2}-\d{2}\]\]\).*$", "", linea[2:]).replace("⭐", "").strip()
                r = max(difflib.SequenceMatcher(None, objetivo, _clave(cuerpo)).ratio(),
                        0.9 if objetivo and objetivo in _clave(cuerpo) else 0.0)
                if mejor is None or r > mejor[1]:
                    mejor = (linea, r)
        return mejor

    def corregir(self, sobre: str, dato_viejo: str, dato_nuevo: str, cuando: datetime | None = None) -> str:
        """Lo nuevo sustituye a lo viejo: lo viejo queda TACHADO con fecha (historial), lo nuevo vigente."""
        nota = self.buscar_archivo(sobre)
        if not nota:
            raise LookupError(f"no tengo ninguna nota de «{sobre}»")
        cuando = cuando or datetime.now()
        dia = cuando.strftime("%Y-%m-%d")
        hallada = self._linea_mas_parecida(nota, dato_viejo) if dato_viejo else None
        texto = nota.read_text(encoding="utf-8")
        if hallada and hallada[1] >= 0.45:
            linea = hallada[0]
            cuerpo = re.sub(r"\s*\(\[\[\d{4}-\d{2}-\d{2}\]\]\).*$", "", linea[2:]).strip()
            fecha = re.search(r"\(\[\[(\d{4}-\d{2}-\d{2})\]\]\)", linea)
            tachada = f"- ~~{cuerpo}~~ (hasta [[{dia}]])" + (f" ([[{fecha.group(1)}]])" if fecha else "")
            texto = texto.replace(linea, tachada, 1)
            nota.write_text(texto, encoding="utf-8")
        self._anadir_linea(nota, f"- {dato_nuevo.strip()} ([[{dia}]])", "Datos")
        self._tocar_fecha(nota)
        self._anadir_linea(self._diario(cuando), f"- {cuando:%H:%M} Corregido en [[{nota.stem}]]: {dato_nuevo.strip()}")
        return nota.stem

    def olvidar(self, sobre: str, dato: str = "") -> str:
        """Olvida un dato (lo quita de la nota y del diario) o, sin dato, la nota entera (va a «.papelera»)."""
        nota = self.buscar_archivo(sobre)
        if not nota:
            raise LookupError(f"no tengo ninguna nota de «{sobre}»")
        if not dato.strip():
            papelera = self.ruta / ".papelera"
            papelera.mkdir(exist_ok=True)
            destino = papelera / f"{nota.stem} ({datetime.now():%Y-%m-%d %H%M}).md"
            nota.replace(destino)
            return f"he olvidado todo lo de «{nota.stem}» (por si acaso, queda en la carpeta .papelera de la bóveda)"
        hallada = self._linea_mas_parecida(nota, dato)
        if not hallada or hallada[1] < 0.45:
            raise LookupError(f"en la nota de «{nota.stem}» no encuentro nada parecido a «{dato}»")
        cuerpo = re.sub(r"\s*\(\[\[\d{4}-\d{2}-\d{2}\]\]\).*$", "", hallada[0][2:]).replace("⭐", "").strip()
        nota.write_text(nota.read_text(encoding="utf-8").replace(hallada[0] + "\n", "", 1)
                        .replace(hallada[0], "", 1), encoding="utf-8")
        for diario in (self.ruta / "Diario").glob("*.md"):  # también del diario: olvidar es olvidar
            t = diario.read_text(encoding="utf-8")
            nuevo = "\n".join(l for l in t.splitlines() if _clave(cuerpo) not in _clave(l))
            if nuevo != t.rstrip("\n"):
                diario.write_text(nuevo + "\n", encoding="utf-8")
        return f"olvidado: «{cuerpo}»"

    def anadir_alias(self, nota: Path, alias: str) -> None:
        texto = nota.read_text(encoding="utf-8")
        actuales = self.alias_de(nota)
        if _clave(alias) in (_clave(a) for a in actuales) or _clave(alias) == _clave(nota.stem):
            return
        lista = ", ".join(actuales + [alias])
        if re.search(r"(?m)^aliases:", texto):
            texto = re.sub(r"(?m)^aliases:.*$", f"aliases: [{lista}]", texto, count=1)
        elif texto.startswith("---\n"):
            texto = texto.replace("---\n", f"---\naliases: [{lista}]\n", 1)
        nota.write_text(texto, encoding="utf-8")

    def unir(self, buena: str, repetida: str) -> str:
        """Une dos notas de lo mismo (p. ej. «Albita» era «Alvita»): los datos van a la buena, el nombre repetido
        queda como alias, los enlaces se arreglan y la repetida va a «.papelera»."""
        a, b = self.buscar_archivo(buena), self.buscar_archivo(repetida)
        if not a or not b:
            raise LookupError("no encuentro alguna de las dos notas")
        if a == b:
            return a.stem
        from .memoria_indice import datos_de_nota

        texto_b = b.read_text(encoding="utf-8")
        for linea in texto_b.splitlines():
            if not linea.startswith("- "):
                continue
            seccion = "Relacionado" if linea.startswith("- [[") else "Datos"
            if seccion == "Relacionado" and f"[[{a.stem}]]" in linea:
                continue  # no enlazar la nota consigo misma
            dato = datos_de_nota(f"## Datos\n{linea}") if seccion == "Datos" else []
            if dato and dato[0]["vigente"] and self.dato_parecido(a, dato[0]["texto"]):
                continue  # ya lo sabía la buena
            self._anadir_linea(a, linea, seccion)
        for alias in [b.stem] + self.alias_de(b):
            self.anadir_alias(a, alias)
        for p in self._notas():  # los enlaces a la repetida apuntan ahora a la buena
            t = p.read_text(encoding="utf-8")
            nuevo = re.sub(r"\[\[" + re.escape(b.stem) + r"(\|[^\]]*)?\]\]", f"[[{a.stem}]]", t)
            if nuevo != t:
                p.write_text(nuevo, encoding="utf-8")
        papelera = self.ruta / ".papelera"
        papelera.mkdir(exist_ok=True)
        b.replace(papelera / f"{b.stem} (unida a {a.stem}).md")
        return a.stem

    # --- Compromisos («dile a mamá que la llamo mañana») -------------------------------------------

    def compromiso(self, texto: str, para: str = "", persona: str = "") -> str:
        archivo = self.ruta / "Compromisos.md"
        if not archivo.exists():
            archivo.write_text("---\ntags: [jarvis, indice]\n---\n# Compromisos\n\nLo que Potro ha prometido. "
                               "Vuelve a [[Inicio]].\n\n", encoding="utf-8")
            self._anadir_linea(self.ruta / "Inicio.md", "- [[Compromisos]]")
        linea = f"- [ ] {texto.strip()}" + (f" (para {para})" if para else "") + (f" → [[{nombre_de_nota(persona)}]]" if persona else "")
        self._anadir_linea(archivo, linea)
        return linea[6:]

    def compromisos(self) -> list[str]:
        archivo = self.ruta / "Compromisos.md"
        if not archivo.exists():
            return []
        return [l[6:] for l in archivo.read_text(encoding="utf-8").splitlines() if l.startswith("- [ ] ")]

    def cumplir(self, texto: str) -> str | None:
        import difflib

        archivo = self.ruta / "Compromisos.md"
        pendientes = [l for l in (archivo.read_text(encoding="utf-8").splitlines() if archivo.exists() else [])
                      if l.startswith("- [ ] ")]
        if not pendientes:
            return None
        mejor = max(pendientes, key=lambda l: difflib.SequenceMatcher(None, _clave(texto), _clave(l)).ratio())
        archivo.write_text(archivo.read_text(encoding="utf-8").replace(mejor, "- [x] " + mejor[6:] +
                                                                     f" (hecho {datetime.now():%Y-%m-%d})", 1),
                           encoding="utf-8")
        return mejor[6:]

    # --- Consolidación nocturna ---------------------------------------------------------------------

    def consolidar(self) -> dict:
        """Limpieza de cada noche: quita datos repetidos dentro de cada nota y repara los índices (MOC)."""
        import difflib

        repetidos = enlazadas = 0
        for p in self._notas():
            if p.parent == self.ruta or "Diario" in p.parts:
                continue
            lineas = p.read_text(encoding="utf-8").splitlines()
            vistos: list[str] = []
            salida = []
            en_datos = False
            for l in lineas:
                if l.startswith("## "):
                    en_datos = l.strip() == "## Datos"
                if en_datos and l.startswith("- ") and not l.startswith("- ~~"):
                    cuerpo = _clave(re.sub(r"\s*\(\[\[\d{4}-\d{2}-\d{2}\]\]\).*$", "", l[2:]).replace("⭐", ""))
                    if any(difflib.SequenceMatcher(None, cuerpo, v).ratio() >= 0.92 for v in vistos):
                        repetidos += 1
                        continue
                    vistos.append(cuerpo)
                salida.append(l)
            if len(salida) != len(lineas):
                p.write_text("\n".join(salida) + "\n", encoding="utf-8")
            carpeta = p.parent.name
            if carpeta in TIPOS.values() and self._anadir_linea(self.ruta / f"{carpeta}.md", f"- [[{p.stem}]]"):
                enlazadas += 1
        self.indexar()
        return {"repetidos": repetidos, "enlazadas": enlazadas}

    def hoy(self, cuando: datetime | None = None) -> str:
        p = self.ruta / "Diario" / f"{(cuando or datetime.now()):%Y-%m-%d}.md"
        if not p.exists():
            return ""
        return "\n".join(l for l in p.read_text(encoding="utf-8").splitlines() if l.startswith("- "))

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
        self.indice.close()


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
