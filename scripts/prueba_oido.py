"""Prueba del oído de JARVIS: graba 5 segundos y los transcribe con Deepgram.

Uso (desde la carpeta del proyecto):
    .venv\\Scripts\\python.exe scripts\\prueba_oido.py
    .venv\\Scripts\\python.exe scripts\\prueba_oido.py --segundos 8
    .venv\\Scripts\\python.exe scripts\\prueba_oido.py --dispositivos
"""

from __future__ import annotations

import argparse
import io
import os
import sys
import time
import wave

import httpx
import numpy as np
import sounddevice as sd
from dotenv import load_dotenv

RATE = 16_000
URL = "https://api.deepgram.com/v1/listen"


def grabar(segundos: float) -> bytes:
    print(f"🎙️  Habla ahora durante {segundos:g} segundos...")
    audio = sd.rec(int(segundos * RATE), samplerate=RATE, channels=1, dtype="int16")
    sd.wait()
    print("✅ Grabación terminada. Enviando a Deepgram...")
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes(np.asarray(audio).tobytes())
    return buf.getvalue()


def transcribir(wav: bytes, key: str) -> tuple[str, float, float]:
    params = {"model": "nova-3", "language": "es", "smart_format": "true"}
    headers = {"Authorization": f"Token {key}", "Content-Type": "audio/wav"}
    t0 = time.perf_counter()
    r = httpx.post(URL, params=params, headers=headers, content=wav, timeout=30)
    dt = time.perf_counter() - t0
    if r.status_code != 200:
        raise SystemExit(f"❌ Deepgram respondió con error {r.status_code}. Revisa DEEPGRAM_API_KEY en .env.")
    alt = r.json()["results"]["channels"][0]["alternatives"][0]
    return alt.get("transcript", ""), alt.get("confidence", 0.0), dt


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description="Prueba del oído con Deepgram")
    ap.add_argument("--segundos", type=float, default=5)
    ap.add_argument("--dispositivos", action="store_true", help="lista los micrófonos y sale")
    args = ap.parse_args()

    if args.dispositivos:
        print(sd.query_devices())
        return

    load_dotenv()
    key = os.getenv("DEEPGRAM_API_KEY", "").strip()
    if not key:
        sys.exit("❌ Falta DEEPGRAM_API_KEY en el archivo .env")

    texto, confianza, dt = transcribir(grabar(args.segundos), key)
    print()
    print(f"📝 Has dicho: {texto or '(no se entendió nada)'}")
    print(f"   Confianza: {confianza:.0%} · Tiempo de Deepgram: {dt:.2f} s")


if __name__ == "__main__":
    main()
