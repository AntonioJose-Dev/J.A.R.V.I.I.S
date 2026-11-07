"""Configura las llamadas: crea en LiveKit Cloud la "salida" (outbound trunk) hacia Telnyx.

Antes, en .env:
    LIVEKIT_URL, LIVEKIT_API_KEY, LIVEKIT_API_SECRET   (de tu proyecto en cloud.livekit.io)
    TELNYX_SIP_USUARIO, TELNYX_SIP_CLAVE              (credenciales de tu SIP Connection en Telnyx)
    JARVIS_CALLER_ID                                  (tu número de Telnyx, p. ej. +34910000000)

Uso:
    python scripts/configurar_llamadas.py              # comprueba y crea el trunk
    python scripts/configurar_llamadas.py --ver        # solo lista los trunks que ya existen

Al terminar te dice el LIVEKIT_SIP_TRUNK_ID que tienes que poner en .env.
"""

from __future__ import annotations

import asyncio
import os
import sys

from dotenv import load_dotenv
from livekit import api

load_dotenv()
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

NECESARIAS = ["LIVEKIT_URL", "LIVEKIT_API_KEY", "LIVEKIT_API_SECRET",
              "TELNYX_SIP_USUARIO", "TELNYX_SIP_CLAVE", "JARVIS_CALLER_ID"]


async def main() -> None:
    solo_ver = "--ver" in sys.argv
    faltan = [v for v in NECESARIAS[: 3 if solo_ver else None] if not os.getenv(v, "").strip()]
    if faltan:
        sys.exit("Faltan en .env: " + ", ".join(faltan))
    if "localhost" in os.environ["LIVEKIT_URL"] or "127.0.0.1" in os.environ["LIVEKIT_URL"]:
        sys.exit("LIVEKIT_URL apunta a tu PC; para llamar hace falta tu proyecto de LiveKit Cloud (wss://...livekit.cloud).")

    async with api.LiveKitAPI() as lk:
        existentes = (await lk.sip.list_outbound_trunk(api.ListSIPOutboundTrunkRequest())).items
        for t in existentes:
            print(f"Trunk existente: {t.name} | id={t.sip_trunk_id} | {t.address} | números={list(t.numbers)}")
        if solo_ver:
            return

        caller_id = os.environ["JARVIS_CALLER_ID"].strip()
        ya = next((t for t in existentes if t.address == "sip.telnyx.com" and caller_id in t.numbers), None)
        if ya:
            print(f"\nYa tienes un trunk para {caller_id}. Pon en .env:\nLIVEKIT_SIP_TRUNK_ID={ya.sip_trunk_id}")
            return

        trunk = await lk.sip.create_outbound_trunk(api.CreateSIPOutboundTrunkRequest(trunk=api.SIPOutboundTrunkInfo(
            name="JARVIS Telnyx",
            address="sip.telnyx.com",
            numbers=[caller_id],
            auth_username=os.environ["TELNYX_SIP_USUARIO"].strip(),
            auth_password=os.environ["TELNYX_SIP_CLAVE"].strip(),
        )))
        print(f"\n✅ Trunk creado. Pon en .env:\nLIVEKIT_SIP_TRUNK_ID={trunk.sip_trunk_id}")


asyncio.run(main())
