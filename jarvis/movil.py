"""Conexión con el móvil Android por ADB inalámbrico (depuración inalámbrica, Android 11+).

Funciona cuando el móvil y el PC están en la misma red Wi-Fi.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path


def adb_path() -> str:
    """Ruta de adb.exe: el del PATH, o el que instala winget (Google.PlatformTools)."""
    encontrado = os.getenv("JARVIS_ADB", "").strip() or shutil.which("adb")
    if encontrado:
        return encontrado
    paquetes = Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft/WinGet/Packages"
    for p in paquetes.glob("Google.PlatformTools*/platform-tools/adb.exe"):
        return str(p)
    raise FileNotFoundError("No encuentro adb. Instálalo con: winget install -e --id Google.PlatformTools")


def adb(*args: str, timeout: float = 20, serial: str | None = None) -> subprocess.CompletedProcess:
    cmd = [adb_path()] + (["-s", serial] if serial else []) + list(args)
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, encoding="utf-8", errors="replace")


def dispositivos() -> list[str]:
    """Números de serie de los móviles conectados y autorizados."""
    salida = adb("devices").stdout
    return [linea.split()[0] for linea in salida.splitlines()[1:] if re.search(r"\tdevice$", linea)]


def es_direccion(texto: str) -> bool:
    return bool(re.fullmatch(r"\d{1,3}(\.\d{1,3}){3}:\d{2,5}", texto.strip()))
