"""Configura el agente de JARVIS en el móvil (funciona en casa y fuera, por Tailscale).

Ejecuta en el PC, desde la carpeta de JARVIS:
    .venv\\Scripts\\python.exe scripts\\configurar_movil.py

1. Te enseña un código secreto (se guarda solo en tu .env). Lo escribes en el móvil cuando el instalador lo pida.
2. Te pregunta el nombre del móvil en Tailscale y comprueba que JARVIS llega hasta él.
El código secreto no hay que mandárselo a nadie.
"""

from __future__ import annotations

import os
import re
import secrets
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from dotenv import load_dotenv  # noqa: E402

ENV = RAIZ / ".env"
INSTALAR = ("curl -fsSL https://raw.githubusercontent.com/AntonioJose-Dev/J.A.R.V.I.I.S/main/movil/instalar.sh"
            " | bash")
ALFABETO = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # sin 0/O ni 1/I para que no haya confusiones al teclear


def nuevo_token() -> str:
    return "".join(secrets.choice(ALFABETO) for _ in range(20))


def agrupado(token: str) -> str:
    return "-".join(token[i:i + 4] for i in range(0, len(token), 4))


def guardar_en_env(clave: str, valor: str) -> None:
    texto = ENV.read_text(encoding="utf-8") if ENV.exists() else ""
    linea = f"{clave}={valor}"
    if re.search(rf"(?m)^{clave}=.*$", texto):
        texto = re.sub(rf"(?m)^{clave}=.*$", linea, texto)
    else:
        texto = texto.rstrip("\n") + f"\n{linea}\n"
    ENV.write_text(texto, encoding="utf-8")


def main() -> None:
    load_dotenv(ENV)
    token = os.getenv("JARVIS_MOVIL_TOKEN", "").strip()
    if not token or "--nuevo-codigo" in sys.argv:
        token = nuevo_token()
        guardar_en_env("JARVIS_MOVIL_TOKEN", token)
        os.environ["JARVIS_MOVIL_TOKEN"] = token

    print("== 1) En el móvil, abre Termux y pega este comando ==\n")
    print("   " + INSTALAR + "\n")
    print("Cuando te pida el código secreto, escribe este (los guiones dan igual):\n")
    print("   " + agrupado(token) + "\n")
    input("Pulsa Enter aquí cuando el instalador del móvil diga 'Listo'… ")

    print("\n== 2) Nombre del móvil en Tailscale ==")
    print("En la app de Tailscale del móvil (o en la del PC) sale el nombre del móvil, p. ej. 'galaxy-s23',")
    print("o su IP de Tailscale, que empieza por 100. (p. ej. 100.101.102.103).")
    while True:
        nombre = input("Nombre o IP del móvil: ").strip()
        if re.fullmatch(r"[\w.-]+", nombre):
            break
        print("   Solo el nombre o la IP, sin espacios.")
    url = f"http://{nombre}:8765"
    guardar_en_env("JARVIS_MOVIL_URL", url)
    os.environ["JARVIS_MOVIL_URL"] = url

    from jarvis import movil

    print("\nProbando la conexión…")
    try:
        movil.agente("ping", timeout=15)
        b = movil.agente("estado")
        print(f"✅ ¡Conectado! Batería del móvil: {b['bateria']}%. Ya funciona en casa y fuera.")
        print("   Reinicia JARVIS para que lo use (o dile a Claude que lo reinicie).")
    except Exception as e:  # noqa: BLE001
        print(f"❌ No conecta: {e}")
        print("   Revisa: Tailscale activo en el PC y en el móvil (misma cuenta) y el agente arrancado en Termux.")


if __name__ == "__main__":
    main()
