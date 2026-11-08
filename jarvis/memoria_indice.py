"""Índice de la memoria: cada DATO de la bóveda de Obsidian, buscable por palabras y por significado.

La bóveda (las notas .md) es la única fuente de verdad; esto es solo un índice que se rehace solo.
- Búsqueda híbrida: palabras (FTS5) + significado (embeddings con un modelo local multilingüe, sin enviar nada
  fuera del PC) + lo reciente + lo importante (⭐).
- Los datos tachados (~~así~~) son antiguos: no salen en las búsquedas normales, pero quedan en la nota.
"""

from __future__ import annotations

import hashlib
import logging
import os
import re
import sqlite3
import threading
import unicodedata
from datetime import date
from pathlib import Path

log = logging.getLogger("jarvis.memoria")
MODELO = os.getenv("JARVIS_MODELO_MEMORIA", "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2")
CARPETA_MODELOS = Path(os.getenv("JARVIS_MODELOS", "modelos"))

_FECHA = re.compile(r"\(\[\[(\d{4}-\d{2}-\d{2})\]\]\)")


def leer_dato(linea: str) -> dict | None:
    """'- Vive en Sevilla ⭐ ([[2026-11-08]]) · [[Noe]]' → texto, fecha, vigente, importante.
    Tachado ('- ~~Vive en Madrid~~ (hasta [[2026-11-08]]) ([[2026-11-01]])') = dato antiguo."""
    linea = linea.strip()
    if not linea.startswith("- ") or linea.startswith("- [[") or linea.startswith("- [ ]") or linea.startswith("- [x]"):
        return None
    cuerpo = linea[2:]
    tachado = cuerpo.startswith("~~")
    if tachado:
        fin = cuerpo.find("~~", 2)
        texto = cuerpo[2:fin] if fin > 0 else cuerpo[2:]
        resto = cuerpo[fin + 2:] if fin > 0 else ""
    else:
        m = _FECHA.search(cuerpo)
        texto, resto = (cuerpo[: m.start()], cuerpo[m.start():]) if m else (cuerpo, "")
    fechas = _FECHA.findall(resto)
    texto = texto.replace("⭐", "").strip()
    if not texto:
        return None
    return {"texto": texto, "fecha": fechas[-1] if fechas else "", "vigente": not tachado, "importante": "⭐" in linea}

_modelo = None
_modelo_cerrojo = threading.Lock()


def _clave(t: str) -> str:
    return unicodedata.normalize("NFKD", t or "").encode("ascii", "ignore").decode().lower().strip()


def modelo():
    """El modelo de significado (se carga una vez; si no está instalado, la memoria busca solo por palabras)."""
    global _modelo
    with _modelo_cerrojo:
        if _modelo is None:
            try:
                os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
                from fastembed import TextEmbedding

                _modelo = TextEmbedding(MODELO, cache_dir=str(CARPETA_MODELOS))
            except Exception as e:  # noqa: BLE001 (sin modelo: búsqueda por palabras, que también funciona)
                log.warning("Memoria sin búsqueda por significado (%s)", type(e).__name__)
                _modelo = False
        return _modelo or None


def vectores(textos: list[str]):
    import numpy as np

    m = modelo()
    if m is None or not textos:
        return None
    v = np.array(list(m.embed(textos)), dtype="float32")
    return v / np.maximum(np.linalg.norm(v, axis=1, keepdims=True), 1e-9)


def datos_de_nota(texto: str) -> list[dict]:
    """Los datos de la sección «## Datos» de una nota: texto, fecha, si está vigente y si es importante."""
    salida, en_datos = [], False
    for linea in texto.splitlines():
        if linea.startswith("## "):
            en_datos = linea.strip() == "## Datos"
            continue
        if not en_datos:
            continue
        d = leer_dato(linea)
        if d:
            salida.append(d)
    return salida


class Indice:
    def __init__(self, ruta_db: str | Path) -> None:
        self._db = sqlite3.connect(str(ruta_db), check_same_thread=False, timeout=10)
        self._db.executescript(
            "CREATE TABLE IF NOT EXISTS hechos (id INTEGER PRIMARY KEY, nota TEXT, texto TEXT, fecha TEXT,"
            " vigente INTEGER, importante INTEGER, huella TEXT);"
            "CREATE VIRTUAL TABLE IF NOT EXISTS hechos_fts USING fts5(texto, nota, content='hechos', content_rowid='id');"
            "CREATE TABLE IF NOT EXISTS vectores (huella TEXT PRIMARY KEY, v BLOB);"
            "CREATE TABLE IF NOT EXISTS notas_vistas (ruta TEXT PRIMARY KEY, mtime REAL);")
        self._cerrojo = threading.Lock()

    def reindexar(self, raiz: Path) -> None:
        """Pone al día los datos de las notas nuevas o cambiadas (también las que edites tú en Obsidian)."""
        import numpy as np

        with self._cerrojo:
            vistas, nuevos = set(), []
            for p in raiz.rglob("*.md"):
                if ".obsidian" in p.parts or ".papelera" in p.parts or p.parent == raiz:
                    continue  # los índices (Inicio, Personas…) no son datos
                rel = str(p.relative_to(raiz))
                vistas.add(rel)
                mtime = p.stat().st_mtime
                fila = self._db.execute("SELECT mtime FROM notas_vistas WHERE ruta=?", (rel,)).fetchone()
                if fila and fila[0] == mtime:
                    continue
                self._borrar_nota(rel)
                texto = p.read_text(encoding="utf-8", errors="replace")
                datos = datos_de_nota(texto) if "Diario" not in p.parts else []
                for d in datos:
                    frase = f"{p.stem}: {d['texto']}"
                    h = hashlib.sha1(frase.encode()).hexdigest()
                    cur = self._db.execute("INSERT INTO hechos (nota, texto, fecha, vigente, importante, huella) "
                                           "VALUES (?,?,?,?,?,?)", (rel, frase, d["fecha"], int(d["vigente"]),
                                                                    int(d["importante"]), h))
                    self._db.execute("INSERT INTO hechos_fts (rowid, texto, nota) VALUES (?,?,?)",
                                     (cur.lastrowid, _clave(frase), _clave(p.stem)))
                    nuevos.append((h, frase))
                self._db.execute("INSERT OR REPLACE INTO notas_vistas (ruta, mtime) VALUES (?,?)", (rel, mtime))
            for (rel,) in self._db.execute("SELECT ruta FROM notas_vistas").fetchall():
                if rel not in vistas:
                    self._borrar_nota(rel)
                    self._db.execute("DELETE FROM notas_vistas WHERE ruta=?", (rel,))
            faltan = [(h, f) for h, f in dict(nuevos).items()
                      if not self._db.execute("SELECT 1 FROM vectores WHERE huella=?", (h,)).fetchone()]
            if faltan:
                v = vectores([f for _, f in faltan])
                if v is not None:
                    self._db.executemany("INSERT OR REPLACE INTO vectores (huella, v) VALUES (?,?)",
                                         [(h, np.asarray(x, dtype="float32").tobytes()) for (h, _), x in zip(faltan, v)])
            self._db.commit()

    def _borrar_nota(self, rel: str) -> None:
        for (i, texto, nota) in self._db.execute("SELECT id, texto, nota FROM hechos WHERE nota=?", (rel,)).fetchall():
            self._db.execute("INSERT INTO hechos_fts (hechos_fts, rowid, texto, nota) VALUES ('delete', ?, ?, ?)",
                             (i, _clave(texto), _clave(Path(nota).stem)))
        self._db.execute("DELETE FROM hechos WHERE nota=?", (rel,))

    def buscar(self, consulta: str, limite: int = 6, incluir_antiguos: bool = False) -> list[dict]:
        """Los datos que mejor responden a la consulta (palabras + significado + recientes + importantes)."""
        import numpy as np

        with self._cerrojo:
            filas = self._db.execute("SELECT id, nota, texto, fecha, vigente, importante, huella FROM hechos"
                                     + ("" if incluir_antiguos else " WHERE vigente=1")).fetchall()
            if not filas:
                return []
            puntos = {f[0]: 0.0 for f in filas}
            palabras = re.findall(r"\w{3,}", _clave(consulta))
            if palabras:
                match = " OR ".join(f'"{w}"*' for w in palabras)
                try:
                    res = self._db.execute("SELECT rowid, bm25(hechos_fts) FROM hechos_fts WHERE hechos_fts MATCH ? "
                                           "ORDER BY bm25(hechos_fts) LIMIT 30", (match,)).fetchall()
                except sqlite3.OperationalError:
                    res = []
                if res:
                    mejor = min(b for _, b in res)
                    for rid, b in res:
                        if rid in puntos:
                            puntos[rid] += 0.45 * (b / mejor if mejor else 1.0)
            q = vectores([consulta])
            if q is not None:
                huellas = {f[6]: f[0] for f in filas}
                vs = self._db.execute(f"SELECT huella, v FROM vectores WHERE huella IN ({','.join('?' * len(huellas))})",
                                      list(huellas)).fetchall()
                for h, blob in vs:
                    sim = float(np.frombuffer(blob, dtype="float32") @ q[0])
                    puntos[huellas[h]] += 0.55 * max(0.0, sim)
            hoy = date.today()
            resultado = []
            for i, nota, texto, fecha, vigente, importante, _h in filas:
                base = puntos[i]
                if base <= 0.05:
                    continue
                try:
                    dias = (hoy - date.fromisoformat(fecha)).days if fecha else 365
                except ValueError:
                    dias = 365
                base += 0.08 * max(0.0, 1 - dias / 365) + (0.07 if importante else 0.0)
                resultado.append({"nota": Path(nota).stem, "texto": texto, "fecha": fecha, "vigente": bool(vigente),
                                  "puntos": round(base, 3)})
            resultado.sort(key=lambda r: r["puntos"], reverse=True)
            return resultado[:limite]

    def close(self) -> None:
        self._db.close()
