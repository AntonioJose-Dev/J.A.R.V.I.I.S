"""Activa o quita el arranque automático de JARVIS al iniciar sesión en Windows.

    python scripts/arranque_automatico.py           # activar
    python scripts/arranque_automatico.py --quitar  # desactivar

Crea (o borra) un acceso directo "JARVIS" en la carpeta Inicio de tu usuario.
No necesita permisos de administrador. También puedes quitarlo a mano: Win+R → shell:startup → borra "JARVIS".
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
INICIO = Path(os.environ["APPDATA"]) / "Microsoft/Windows/Start Menu/Programs/Startup"
ACCESO = INICIO / "JARVIS.lnk"


def activar() -> None:
    pythonw = RAIZ / ".venv/Scripts/pythonw.exe"
    ps = (
        "$s = (New-Object -ComObject WScript.Shell).CreateShortcut($env:ACCESO);"
        "$s.TargetPath = $env:PYW; $s.Arguments = '-m jarvis'; $s.WorkingDirectory = $env:RAIZ;"
        "$s.Description = 'JARVIS: bot de Telegram y llamadas'; $s.Save()"
    )
    subprocess.run(["powershell", "-NoProfile", "-Command", ps], check=True,
                   env={**os.environ, "ACCESO": str(ACCESO), "PYW": str(pythonw), "RAIZ": str(RAIZ)})
    print(f"✅ JARVIS arrancará solo al iniciar sesión en Windows ({ACCESO}).")


def quitar() -> None:
    if ACCESO.exists():
        ACCESO.unlink()
        print("Arranque automático desactivado.")
    else:
        print("No estaba activado.")


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    quitar() if "--quitar" in sys.argv else activar()
