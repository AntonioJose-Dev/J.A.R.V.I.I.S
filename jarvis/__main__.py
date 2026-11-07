"""Arranca JARVIS entero: el bot de Telegram y, si están configuradas, las llamadas.

Uso:
    python -m jarvis          (con ventana)
    pythonw -m jarvis         (sin ventana; es lo que usa el arranque automático de Windows)

Si alguna parte se cae, la vuelve a arrancar. Los registros quedan en la carpeta logs/.
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

RAIZ = Path(__file__).resolve().parent.parent
LOGS = RAIZ / "logs"


def _python() -> str:
    """El python.exe del mismo entorno (no pythonw), para que los hijos escriban sus registros."""
    exe = Path(sys.executable)
    consola = exe.with_name("python.exe")
    return str(consola if consola.exists() else exe)


def _arrancar(nombre: str, args: list[str]) -> subprocess.Popen:
    LOGS.mkdir(exist_ok=True)
    log = open(LOGS / f"{nombre.lower()}.log", "a", encoding="utf-8", buffering=1)
    log.write(f"\n===== {datetime.now():%Y-%m-%d %H:%M:%S} arrancando {nombre} =====\n")
    flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
    return subprocess.Popen([_python(), "-m", *args], cwd=RAIZ, stdout=log, stderr=subprocess.STDOUT,
                            env={**os.environ, "PYTHONIOENCODING": "utf-8"}, creationflags=flags)


def main() -> None:
    os.chdir(RAIZ)
    load_dotenv(RAIZ / ".env")
    from . import telefono

    procesos = {"Telegram": ["jarvis.telegram_bot"]}
    faltan = telefono.llamadas_configuradas()
    if faltan:
        print("Llamadas desactivadas (faltan: " + ", ".join(faltan) + ")")
    else:
        procesos["Llamadas"] = ["jarvis.llamadas", "start"]

    vivos = {nombre: _arrancar(nombre, args) for nombre, args in procesos.items()}
    print("JARVIS en marcha: " + ", ".join(vivos) + f". Registros en {LOGS}. Ctrl+C para parar.")
    try:
        while True:
            for nombre, p in list(vivos.items()):
                if p.poll() is not None:
                    time.sleep(5)
                    vivos[nombre] = _arrancar(nombre, procesos[nombre])
            time.sleep(2)
    except KeyboardInterrupt:
        pass
    finally:
        for p in vivos.values():
            p.terminate()


if __name__ == "__main__":
    main()
