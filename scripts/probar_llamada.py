"""Llamada de prueba a TU propio móvil, para comprobar que todo funciona.

Necesita que el agente de llamadas esté arrancado en otra terminal:
    python -m jarvis.llamadas start

Uso:
    python scripts/probar_llamada.py +34600123456
    python scripts/probar_llamada.py --comprobar      # solo revisa la configuración, no llama
"""

from __future__ import annotations

import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dotenv import load_dotenv  # noqa: E402

load_dotenv()
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from jarvis import telefono  # noqa: E402
from jarvis.memory import MemoryStore  # noqa: E402


async def main() -> None:
    faltan = telefono.llamadas_configuradas()
    if faltan:
        sys.exit("Faltan en .env: " + ", ".join(faltan))
    print("Configuración de llamadas: OK")
    if len(sys.argv) < 2 or sys.argv[1] == "--comprobar":
        return

    numero = telefono.normalizar_numero(sys.argv[1])
    if not telefono.numero_permitido(numero):
        sys.exit(f"{numero} no está entre los prefijos permitidos")
    memory = MemoryStore(os.getenv("JARVIS_MEMORY_PATH", "jarvis_memoria.db"))
    call_id = memory.create_call("Prueba", numero, "Esto es una llamada de prueba: si me oyes, las llamadas funcionan.")
    memory.set_call_status(call_id, "marcando")
    llamada = memory.get_call(call_id)
    memory.close()
    sala = await telefono.iniciar_llamada(llamada)
    print(f"Llamando a {numero} (sala {sala}). El resumen te llegará por Telegram.")


asyncio.run(main())
