"""Empareja tu móvil Android con el PC por Wi-Fi (una sola vez).

En el móvil: Ajustes > Opciones para desarrolladores > Depuración inalámbrica (activada)
             > "Vincular dispositivo con código de vinculación".
Luego ejecuta en el PC (desde la carpeta de JARVIS):
    .venv\\Scripts\\python.exe scripts\\emparejar_movil.py

El código de vinculación lo escribes aquí, en tu PC: no hace falta mandárselo a nadie.
"""

from __future__ import annotations

import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from jarvis import movil  # noqa: E402


def preguntar_direccion(texto: str) -> str:
    while True:
        d = input(texto).strip()
        if movil.es_direccion(d):
            return d
        print("   Tiene que ser así: 192.168.1.23:37000 (IP, dos puntos y puerto)")


def main() -> None:
    print("adb:", movil.adb_path())
    if movil.dispositivos():
        print("✅ Ya hay un móvil conectado:", movil.dispositivos())
        return

    print("\n1) En el móvil, dentro de 'Depuración inalámbrica', pulsa 'Vincular dispositivo con código'.")
    direccion = preguntar_direccion("   Escribe la IP y puerto que salen en esa ventana (ej. 192.168.1.23:37000): ")
    codigo = input("   Escribe el código de 6 cifras: ").strip()
    r = movil.adb("pair", direccion, codigo, timeout=30)
    print("  ", (r.stdout or r.stderr).strip())
    if "Successfully paired" not in r.stdout:
        sys.exit("❌ No se pudo vincular. Revisa que el móvil y el PC estén en la misma Wi-Fi y vuelve a probar.")

    print("\n2) Conectando… (el móvil se anuncia solo en la red)")
    for _ in range(10):
        if movil.dispositivos():
            break
        time.sleep(1)
    if not movil.dispositivos():
        print("   En la pantalla principal de 'Depuración inalámbrica' sale 'Dirección IP y puerto'.")
        direccion = preguntar_direccion("   Escríbela aquí (ej. 192.168.1.23:41234): ")
        print("  ", movil.adb("connect", direccion).stdout.strip())

    if movil.dispositivos():
        modelo = movil.adb("shell", "getprop", "ro.product.model", serial=movil.dispositivos()[0]).stdout.strip()
        print(f"\n✅ ¡Conectado! Móvil: {modelo}. Ya puedes decirle a JARVIS que lo controle.")
    else:
        sys.exit("❌ Se vinculó pero no conecta. Desactiva y activa 'Depuración inalámbrica' y vuelve a ejecutar esto.")


if __name__ == "__main__":
    main()
