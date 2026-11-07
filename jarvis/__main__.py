"""Arranca JARVIS entero: el bot de Telegram y, si están configuradas, las llamadas.

Uso:
    python -m jarvis
"""

from __future__ import annotations

import subprocess
import sys
import time

from dotenv import load_dotenv

from . import telefono

load_dotenv()


def main() -> None:
    procesos = {"Telegram": [sys.executable, "-m", "jarvis.telegram_bot"]}
    faltan = telefono.llamadas_configuradas()
    if faltan:
        print("Llamadas desactivadas (faltan: " + ", ".join(faltan) + ")")
    else:
        procesos["Llamadas"] = [sys.executable, "-m", "jarvis.llamadas", "start"]

    vivos = {nombre: subprocess.Popen(cmd) for nombre, cmd in procesos.items()}
    print("JARVIS en marcha: " + ", ".join(vivos) + ". Ctrl+C para parar.")
    try:
        while True:
            for nombre, p in vivos.items():
                if p.poll() is not None:
                    print(f"{nombre} se ha parado (código {p.returncode}); lo vuelvo a arrancar en 5 s")
                    time.sleep(5)
                    vivos[nombre] = subprocess.Popen(procesos[nombre])
            time.sleep(2)
    except KeyboardInterrupt:
        pass
    finally:
        for p in vivos.values():
            p.terminate()


if __name__ == "__main__":
    main()
