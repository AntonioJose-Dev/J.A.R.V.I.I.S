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


MAX_LOG = 5 * 1024 * 1024  # al pasar de 5 MB, el log se guarda como .1 y se empieza otro


def _rotar(ruta: Path) -> None:
    if ruta.exists() and ruta.stat().st_size > MAX_LOG:
        viejo = ruta.with_suffix(".1.log")
        viejo.unlink(missing_ok=True)
        ruta.rename(viejo)


def _arrancar(nombre: str, args: list[str]) -> subprocess.Popen:
    LOGS.mkdir(exist_ok=True)
    _rotar(LOGS / f"{nombre.lower()}.log")
    log = open(LOGS / f"{nombre.lower()}.log", "a", encoding="utf-8", buffering=1)
    log.write(f"\n===== {datetime.now():%Y-%m-%d %H:%M:%S} arrancando {nombre} =====\n")
    flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
    return subprocess.Popen([_python(), "-m", *args], cwd=RAIZ, stdout=log, stderr=subprocess.STDOUT,
                            env={**os.environ, "PYTHONIOENCODING": "utf-8"}, creationflags=flags)


def _avisar_reinicio(nombre: str, codigo: int | None, reinicios: dict[str, list[float]]) -> None:
    """Un reinicio ya no es silencioso: queda en el log y, si se repite (3 en 10 min), avisa por Telegram (una vez/h)."""
    ahora = time.time()
    lista = [t for t in reinicios.get(nombre, []) if ahora - t < 600] + [ahora]
    reinicios[nombre] = lista
    with open(LOGS / "reinicios.log", "a", encoding="utf-8") as f:
        f.write(f"{datetime.now():%Y-%m-%d %H:%M:%S} {nombre} se cayó (código {codigo}) y se ha vuelto a arrancar\n")
    clave = f"_aviso_{nombre}"
    if len(lista) >= 3 and ahora - reinicios.get(clave, [0])[0] > 3600:
        reinicios[clave] = [ahora]
        try:
            from . import telegram_api

            telegram_api.telegram("sendMessage", chat_id=telegram_api.chat_del_dueno(),
                                  text=f"⚠️ JARVIS: la parte «{nombre}» se ha caído {len(lista)} veces en 10 minutos. "
                                       f"Mira logs\\{nombre.lower()}.log o pídeme un /estado.")
        except Exception:  # noqa: BLE001 (el aviso es una ayuda)
            pass


def main() -> None:
    os.chdir(RAIZ)
    load_dotenv(RAIZ / ".env")
    from . import telefono

    procesos = {"Telegram": ["jarvis.telegram_bot"]}
    # La voz en directo (/hablar) solo necesita LiveKit; las llamadas, además, el troncal SIP
    if all(os.getenv(k, "").strip() for k in ("LIVEKIT_URL", "LIVEKIT_API_KEY", "LIVEKIT_API_SECRET")):
        procesos["Voz"] = ["jarvis.agent", "start"]
    faltan = telefono.llamadas_configuradas()
    if faltan:
        print("Llamadas desactivadas (faltan: " + ", ".join(faltan) + ")")
    else:
        procesos["Llamadas"] = ["jarvis.llamadas", "start"]

    vivos = {nombre: _arrancar(nombre, args) for nombre, args in procesos.items()}
    print("JARVIS en marcha: " + ", ".join(vivos) + f". Registros en {LOGS}. Ctrl+C para parar.")
    reinicios: dict[str, list[float]] = {}
    try:
        while True:
            for nombre, p in list(vivos.items()):
                if p.poll() is not None:
                    codigo = p.returncode
                    time.sleep(5)
                    vivos[nombre] = _arrancar(nombre, procesos[nombre])
                    _avisar_reinicio(nombre, codigo, reinicios)
            time.sleep(2)
    except KeyboardInterrupt:
        pass
    finally:
        for p in vivos.values():
            p.terminate()


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "doctor":  # python -m jarvis doctor: revisión de todo
        os.chdir(RAIZ)
        from .doctor import main as doctor

        doctor()
    else:
        main()
