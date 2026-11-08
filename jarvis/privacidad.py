"""Privacidad de los registros (logs): lo que dicen las personas no se guarda en ellos.

- LiveKit añade a algunos registros lo que se ha dicho en una llamada (campos «lk.pii.*», p. ej. el detector de
  contestador). `instalar()` los quita antes de que lleguen a ningún sitio.
- `limpiar_archivo()` borra de un log ya escrito las transcripciones (de logs antiguos).
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path

_instalado = False


def instalar() -> None:
    """Desde ahora, ningún registro lleva campos «lk.pii.*» (datos personales de las conversaciones)."""
    global _instalado
    if _instalado:
        return
    original = logging.Logger.makeRecord

    def sin_datos_personales(self, name, level, fn, lno, msg, args, exc_info, func=None, extra=None, sinfo=None):
        if extra:
            extra = {k: v for k, v in extra.items() if not str(k).startswith("lk.pii")}
        return original(self, name, level, fn, lno, msg, args, exc_info, func, extra, sinfo)

    logging.Logger.makeRecord = sin_datos_personales
    _instalado = True


_TRANSCRITO = re.compile(r"(Nota de voz transcrita|Voz desde el móvil): (.*)$")


def limpiar_linea(linea: str) -> str:
    m = _TRANSCRITO.search(linea)
    if m:
        return linea[: m.start()] + f"{m.group(1)} ({len(m.group(2).strip())} caracteres)" + ("\n" if linea.endswith("\n") else "")
    if '"lk.pii.' in linea:
        try:
            datos = json.loads(linea)
            return json.dumps({k: v for k, v in datos.items() if not k.startswith("lk.pii")}, ensure_ascii=False) + "\n"
        except ValueError:
            return re.sub(r'"lk\.pii\.[^"]*":\s*"(?:[^"\\]|\\.)*",?\s*', "", linea)
    return linea


def limpiar_archivo(ruta: str | Path) -> int:
    """Quita las transcripciones de un log ya escrito. Devuelve cuántas líneas ha cambiado."""
    p = Path(ruta)
    if not p.exists():
        return 0
    lineas = p.read_text(encoding="utf-8", errors="replace").splitlines(keepends=True)
    nuevas = [limpiar_linea(l) for l in lineas]
    cambios = sum(a != b for a, b in zip(lineas, nuevas))
    if cambios:
        p.write_text("".join(nuevas), encoding="utf-8")
    return cambios
