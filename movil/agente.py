"""Agente de JARVIS en el móvil Android (Termux + Termux:API).

Escucha órdenes del PC de JARVIS por la red privada de Tailscale (funciona en casa y fuera, con datos)
y las ejecuta con las herramientas de Termux:API. Cada petición debe traer el token secreto
(~/.jarvis_token), que se genera en el PC y se escribe a mano una vez al instalar.

Solo usa la biblioteca estándar de Python: no hay que instalar nada más.
"""

from __future__ import annotations

import base64
import hmac
import json
import os
import shlex
import subprocess
import sys
import tempfile
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PUERTO = int(os.environ.get("JARVIS_MOVIL_PUERTO", "8765"))
RUTA_TOKEN = os.path.expanduser("~/.jarvis_token")
VERSION = "2"


def ejecutar(cmd: list[str], timeout: float = 30) -> str:
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    if r.returncode != 0 and not r.stdout:
        raise RuntimeError((r.stderr or "error").strip()[:300])
    return r.stdout.strip()


def json_de(cmd: list[str], timeout: float = 30):
    salida = ejecutar(cmd, timeout)
    return json.loads(salida) if salida else None


def am(*args: str) -> str:
    return ejecutar(["am", *args])


# --- Acciones ------------------------------------------------------------------------------

def estado(_v: str) -> dict:
    b = json_de(["termux-battery-status"])
    return {"bateria": b.get("percentage"), "cargando": b.get("status") in ("CHARGING", "FULL"),
            "temperatura": b.get("temperature")}


def ubicacion(_v: str) -> dict:
    loc = None
    for proveedor, peticion in (("network", "last"), ("gps", "once"), ("network", "once")):
        try:
            loc = json_de(["termux-location", "-p", proveedor, "-r", peticion], timeout=40)
            if loc and loc.get("latitude"):
                break
        except Exception:
            continue
    if not loc or not loc.get("latitude"):
        raise RuntimeError("sin ubicación (¿GPS desactivado?)")
    return {"lat": loc["latitude"], "lon": loc["longitude"], "precision": loc.get("accuracy")}


def notificaciones(_v: str) -> dict:
    lista = json_de(["termux-notification-list"]) or []
    vistas, salida = set(), []
    for n in lista:
        clave = (n.get("packageName"), n.get("title"), n.get("content"))
        if (n.get("title") or n.get("content")) and clave not in vistas:
            vistas.add(clave)
            salida.append({"app": n.get("packageName", ""), "titulo": n.get("title", ""), "texto": n.get("content", "")})
    return {"notificaciones": salida[:20]}


def linterna(v: str) -> dict:
    ejecutar(["termux-torch", "on" if v.strip().lower() in ("on", "encender", "si", "sí", "1") else "off"])
    return {"ok": True}


def volumen(v: str) -> dict:
    niveles = {s["stream"]: s for s in json_de(["termux-volume"])}
    musica = niveles.get("music", {"volume": 7, "max_volume": 15})
    actual, maximo = musica["volume"], musica["max_volume"]
    if v == "subir":
        nuevo = min(maximo, actual + max(1, maximo // 7))
    elif v == "bajar":
        nuevo = max(0, actual - max(1, maximo // 7))
    elif v in ("silenciar", "0"):
        nuevo = 0
    else:
        nuevo = max(0, min(maximo, round(maximo * int(v) / 100)))  # porcentaje
    ejecutar(["termux-volume", "music", str(nuevo)])
    return {"volumen": round(100 * nuevo / maximo)}


def sonar(_v: str) -> dict:
    """Para encontrar el móvil: volumen al máximo, vibra y habla."""
    maximo = {s["stream"]: s for s in json_de(["termux-volume"])}.get("music", {}).get("max_volume", 15)
    ejecutar(["termux-volume", "music", str(maximo)])
    for _ in range(3):
        ejecutar(["termux-vibrate", "-f", "-d", "800"])
        ejecutar(["termux-tts-speak", "-l", "es", "Estoy aquí, señor."], timeout=20)
        time.sleep(0.3)
    return {"ok": True}


def hablar(v: str) -> dict:
    ejecutar(["termux-tts-speak", "-l", "es", v[:500]], timeout=60)
    return {"ok": True}


def vibrar(_v: str) -> dict:
    ejecutar(["termux-vibrate", "-f", "-d", "1000"])
    return {"ok": True}


def alarma(v: str) -> dict:
    hora, _, mensaje = v.partition(" ")
    h, m = hora.replace(".", ":").split(":")
    am("start", "-a", "android.intent.action.SET_ALARM",
       "--ei", "android.intent.extra.alarm.HOUR", str(int(h)),
       "--ei", "android.intent.extra.alarm.MINUTES", str(int(m)),
       "--es", "android.intent.extra.alarm.MESSAGE", mensaje or "JARVIS",
       "--ez", "android.intent.extra.alarm.SKIP_UI", "true")
    return {"ok": True}


def temporizador(v: str) -> dict:
    am("start", "-a", "android.intent.action.SET_TIMER",
       "--ei", "android.intent.extra.alarm.LENGTH", str(int(float(v or "1") * 60)),
       "--ez", "android.intent.extra.alarm.SKIP_UI", "true")
    return {"ok": True}


def abrir_web(v: str) -> dict:
    ejecutar(["termux-open-url", v])
    return {"ok": True}


def abrir_app(v: str) -> dict:
    """v = nombre de paquete (lo resuelve el PC con la lista de `paquetes`)."""
    am("start", "-a", "android.intent.action.MAIN", "-c", "android.intent.category.LAUNCHER", "-p", v)
    return {"ok": True}


def paquetes(_v: str) -> dict:
    salida = ejecutar(["pm", "list", "packages"])
    return {"paquetes": [p.removeprefix("package:") for p in salida.splitlines()]}


def portapapeles(v: str) -> dict:
    if v:
        ejecutar(["termux-clipboard-set", v])
        return {"ok": True}
    return {"texto": ejecutar(["termux-clipboard-get"])}


def sms(v: str) -> dict:
    """v = JSON {"numero": "...", "texto": "..."}. El PC solo lo manda después de que el dueño confirme."""
    d = json.loads(v)
    ejecutar(["termux-sms-send", "-n", d["numero"], d["texto"]])
    return {"ok": True}


def whatsapp(v: str) -> dict:
    """Abre el chat con el texto escrito (fuera de casa no se puede pulsar 'enviar' automáticamente)."""
    from urllib.parse import quote

    d = json.loads(v)
    ejecutar(["termux-open-url", f"https://wa.me/{d['numero'].lstrip('+')}?text={quote(d['texto'])}"])
    return {"ok": True, "pendiente_enviar": True}


def foto(v: str) -> dict:
    camara = "1" if v.strip().lower() in ("frontal", "selfie", "1") else "0"
    with tempfile.TemporaryDirectory() as d:
        ruta = os.path.join(d, "foto.jpg")
        ejecutar(["termux-camera-photo", "-c", camara, ruta], timeout=40)
        with open(ruta, "rb") as f:
            return {"jpg_base64": base64.b64encode(f.read()).decode()}


URL_AGENTE = "https://raw.githubusercontent.com/AntonioJose-Dev/J.A.R.V.I.I.S/main/movil/agente.py"


def cambiar_token(v: str) -> dict:
    """Cambia el código secreto (la petición ya viene autenticada con el código actual)."""
    nuevo = v.strip().replace("-", "")
    if len(nuevo) < 16:
        raise ValueError("código demasiado corto")
    with open(RUTA_TOKEN, "w", encoding="utf-8") as f:
        f.write(nuevo)
    os.chmod(RUTA_TOKEN, 0o600)
    Manejador.token = nuevo
    return {"ok": True}


def actualizar(_v: str) -> dict:
    """Descarga la última versión del agente y se reinicia (el bucle de arranque lo vuelve a lanzar)."""
    import threading
    import urllib.request

    destino = os.path.abspath(__file__)
    with urllib.request.urlopen(URL_AGENTE, timeout=30) as r:
        codigo = r.read()
    compile(codigo, destino, "exec")  # no se instala nada que no sea Python válido
    with open(destino + ".nuevo", "wb") as f:
        f.write(codigo)
    os.replace(destino + ".nuevo", destino)
    threading.Timer(1.0, lambda: os._exit(0)).start()
    return {"ok": True, "reiniciando": True}


ACCIONES = {
    "cambiar_token": cambiar_token, "actualizar": actualizar,
    "estado": estado, "ubicacion": ubicacion, "notificaciones": notificaciones, "linterna": linterna,
    "volumen": volumen, "sonar": sonar, "hablar": hablar, "vibrar": vibrar, "alarma": alarma,
    "temporizador": temporizador, "abrir_web": abrir_web, "abrir_app": abrir_app, "paquetes": paquetes,
    "portapapeles": portapapeles, "sms": sms, "whatsapp": whatsapp, "foto": foto,
}


def token_valido(recibido: str | None, esperado: str) -> bool:
    return bool(esperado) and bool(recibido) and hmac.compare_digest(recibido.encode(), esperado.encode())


def atender(cuerpo: bytes, token_recibido: str | None, token: str) -> tuple[int, dict]:
    """Lógica de una petición (sin red): devuelve (código HTTP, respuesta)."""
    if not token_valido(token_recibido, token):
        return 401, {"error": "token incorrecto"}
    try:
        orden = json.loads(cuerpo or b"{}")
    except ValueError:
        return 400, {"error": "JSON no válido"}
    accion = orden.get("accion")
    if accion == "ping":
        return 200, {"ok": True, "version": VERSION}
    if accion not in ACCIONES:
        return 400, {"error": f"acción desconocida: {accion}"}
    try:
        return 200, ACCIONES[accion](str(orden.get("valor", "")))
    except Exception as e:  # el error vuelve al PC para que JARVIS lo explique
        return 500, {"error": f"{type(e).__name__}: {e}"[:300]}


class Manejador(BaseHTTPRequestHandler):
    token = ""

    def do_POST(self):  # noqa: N802
        largo = min(int(self.headers.get("Content-Length", "0")), 100_000)
        codigo, respuesta = atender(self.rfile.read(largo), self.headers.get("X-Jarvis-Token"), self.token)
        datos = json.dumps(respuesta, ensure_ascii=False).encode()
        self.send_response(codigo)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(datos)))
        self.end_headers()
        self.wfile.write(datos)

    def log_message(self, formato, *args):
        sys.stderr.write("%s %s\n" % (time.strftime("%H:%M:%S"), formato % args))


def main() -> None:
    if not os.path.exists(RUTA_TOKEN):
        sys.exit(f"Falta el token en {RUTA_TOKEN}. Vuelve a ejecutar el instalador.")
    Manejador.token = open(RUTA_TOKEN, encoding="utf-8").read().strip()
    servidor = ThreadingHTTPServer(("0.0.0.0", PUERTO), Manejador)
    print(f"Agente de JARVIS escuchando en el puerto {PUERTO}. Ctrl+C para parar.")
    servidor.serve_forever()


if __name__ == "__main__":
    main()
