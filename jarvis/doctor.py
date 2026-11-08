"""JARVIS se revisa a sí mismo: qué funciona y qué no (sin enseñar ninguna clave).

Se usa con `/estado` en Telegram, preguntándole «¿cómo estás?» y con `python -m jarvis doctor`.
"""

from __future__ import annotations

import os
import sqlite3
import time
from pathlib import Path

CLAVES = {
    "TELEGRAM_BOT_TOKEN": "bot de Telegram", "TELEGRAM_ALLOWED_IDS": "tu ID de Telegram",
    "DEEPGRAM_API_KEY": "oído (Deepgram)", "LIVEKIT_URL": "LiveKit (voz en directo y cerebro incluido)",
    "LIVEKIT_API_KEY": "LiveKit (clave)", "LIVEKIT_API_SECRET": "LiveKit (secreto)",
    "JARVIS_APP_TOKEN": "app del móvil", "JARVIS_BOVEDA": "cerebro de Obsidian",
}


def revisar() -> list[tuple[str, bool, str]]:
    """(qué, ¿bien?, detalle) de cada pieza. Cada prueba es rápida y nunca lanza excepciones."""
    filas: list[tuple[str, bool, str]] = []

    def prueba(nombre, f):
        try:
            ok, detalle = f()
        except Exception as e:  # noqa: BLE001
            ok, detalle = False, f"{type(e).__name__}: {e}"[:160]
        filas.append((nombre, ok, detalle))

    faltan = [desc for k, desc in CLAVES.items() if not os.getenv(k, "").strip()]
    filas.append(("Configuración", not faltan, "todo puesto" if not faltan else "falta: " + ", ".join(faltan)))

    def cerebros():
        from . import cerebros as c
        from .config import elegir_plan

        plan = elegir_plan(os.environ)
        return True, f"principal {plan.describir()}; de reserva: {', '.join(c.disponibles(os.environ)) or 'ninguno'}"
    prueba("Cerebro", cerebros)

    def voz():
        from .config import elegir_plan
        from .core import describir_voz, estado_eleven

        plan = elegir_plan(os.environ)
        if plan.voz != "elevenlabs":
            return True, describir_voz(plan)
        ok, motivo = estado_eleven()
        return True, ("ElevenLabs (Daniel)" if ok else f"voz de reserva Deepgram (ElevenLabs: {motivo})")
    prueba("Voz", voz)

    def tailscale():
        from .app_movil import ip_tailscale

        ip = ip_tailscale()
        return bool(ip), ip or "Tailscale no está activo en el PC"
    prueba("Tailscale (PC)", tailscale)

    def app():
        from . import app_movil

        e = app_movil.estado()
        hace = time.time() - float(e.get("ultimo_contacto", "0") or 0)
        detalle = f"versión {e.get('version', '?')}, accesibilidad {'sí' if e.get('accesibilidad') == 'True' else 'NO'}"
        detalle += f", último contacto hace {int(hace)} s" if hace < 10 ** 8 else ", nunca conectada"
        if e.get("ultimo_error"):
            detalle += f"; último error: {e['ultimo_error'][:90]}"
        return bool(e["en_linea"]) and e.get("accesibilidad") == "True", detalle
    prueba("App JARVIS del móvil", app)

    def termux():
        from . import movil

        if not movil.agente_configurado():
            return False, "sin configurar"
        r = movil.agente("ping", timeout=4)
        return True, f"versión {r.get('version', '?')}"
    prueba("Agente Termux del móvil", termux)

    def memoria():
        ruta = os.getenv("JARVIS_MEMORY_PATH", "jarvis_memoria.db")
        db = sqlite3.connect(ruta, timeout=5)
        modo = db.execute("PRAGMA journal_mode").fetchone()[0]
        n = db.execute("SELECT count(*) FROM memories").fetchone()[0]
        db.close()
        boveda = os.getenv("JARVIS_BOVEDA", "").strip()
        notas = len(list(Path(boveda).rglob("*.md"))) if boveda and Path(boveda).exists() else 0
        return True, f"base de datos en modo {modo}; {notas} notas en Obsidian" + ("" if boveda else f"; {n} recuerdos")
    prueba("Memoria", memoria)

    def whatsapp():
        from . import app_movil, movil

        db = app_movil._db()
        n = db.execute("SELECT count(*) FROM app_trabajos WHERE tipo IN ('whatsapp','whatsapp_audio') "
                       "AND estado='enviado' AND creado > ?", (time.time() - 86400,)).fetchone()[0]
        db.close()
        return n < movil.WHATSAPP_AL_DIA, f"{n} de {movil.WHATSAPP_AL_DIA} enviados en 24 h"
    prueba("Límite de WhatsApp", whatsapp)

    def registros():
        logs = Path("logs")
        tam = sum(p.stat().st_size for p in logs.glob("*.log")) / 1e6 if logs.exists() else 0
        reinicios = 0
        f = logs / "reinicios.log"
        if f.exists():
            hoy = time.strftime("%Y-%m-%d")
            reinicios = sum(1 for l in f.read_text(encoding="utf-8", errors="replace").splitlines() if l.startswith(hoy))
        return reinicios < 3, f"{tam:.1f} MB de registros; {reinicios} reinicios hoy"
    prueba("Registros", registros)
    return filas


def texto(filas: list[tuple[str, bool, str]] | None = None) -> str:
    filas = filas if filas is not None else revisar()
    malos = sum(1 for _, ok, _ in filas if not ok)
    cabecera = "Todo en orden." if not malos else f"{malos} cosa(s) a revisar."
    return cabecera + "\n" + "\n".join(f"{'✅' if ok else '⚠️'} {n}: {d}" for n, ok, d in filas)


def main() -> None:
    import sys

    from dotenv import load_dotenv

    sys.stdout.reconfigure(encoding="utf-8")
    load_dotenv(".env", override=True)
    print("JARVIS · revisión\n" + texto())
