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
VERSION = "12"


def ejecutar(cmd: list[str], timeout: float = 30) -> str:
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    if r.returncode != 0 and not r.stdout:
        raise RuntimeError((r.stderr or "error").strip()[:300])
    return r.stdout.strip()


def json_de(cmd: list[str], timeout: float = 30):
    salida = ejecutar(cmd, timeout)
    if "not yet available on Google Play" in salida:
        raise RuntimeError("tu Termux es el de Google Play y no admite Termux:API: desinstálalo e instala "
                           "Termux, Termux:API y Termux:Boot desde F-Droid")
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
        raise RuntimeError("sin ubicación: activa la ubicación del móvil y da a Termux:API el permiso "
                           "de Ubicación 'Permitir siempre' (Ajustes > Aplicaciones > Termux:API > Permisos)")
    return {"lat": loc["latitude"], "lon": loc["longitude"], "precision": loc.get("accuracy")}


def notificaciones(_v: str) -> dict:
    try:
        lista = json_de(["termux-notification-list"], timeout=20) or []
    except (ValueError, RuntimeError, subprocess.TimeoutExpired):
        raise RuntimeError("falta permiso: Ajustes > Notificaciones > Acceso a notificaciones > activar Termux:API")
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


RUTA_COMPANION = os.path.expanduser("~/.jarvis_companion")
COMPONENTE = "com.jarvis.companion/.Receptor"


def _difundir_crudo(accion: str, extras: dict[str, str] | None = None) -> tuple[int | None, str, str]:
    """`am broadcast` a la app JARVIS → (código de resultado, datos devueltos, salida completa)."""
    import re as _re

    cmd = ["am", "broadcast", "-a", f"com.jarvis.companion.{accion}", "-n", COMPONENTE]
    for k, v in (extras or {}).items():
        cmd += ["--es", k, v]
    salida = ejecutar(cmd)
    m = _re.search(r"result=(-?\d+)", salida)
    d = _re.search(r'data="([^"]*)"', salida)
    return (int(m.group(1)) if m else None), (d.group(1) if d else ""), salida


def _difundir(accion: str, extras: dict[str, str]) -> bool:
    """`am broadcast` a la app JARVIS; devuelve True si la app aceptó (result=1)."""
    return _difundir_crudo(accion, extras)[0] == 1


# Avisos firmados que manda la app JARVIS desde este mismo móvil: {(evento, marca)}
_AVISOS: set[tuple[str, str]] = set()
_AVISOS_LOCK = __import__("threading").Lock()


def recibir_aviso(cuerpo: bytes, ip: str | None, secreto: str | None) -> int:
    """POST /companion desde la app (solo desde el propio móvil y con la firma del secreto compartido)."""
    import ipaddress

    try:
        if not ipaddress.ip_address((ip or "").removeprefix("::ffff:")).is_loopback:
            return 403
        d = json.loads(cuerpo or b"{}")
        evento, marca, firma = str(d["evento"]), str(d["marca"]), str(d["firma"])
    except (ValueError, KeyError):
        return 400
    esperada = hmac.new((secreto or "").encode(), f"{evento}\n{marca}".encode(), "sha256").hexdigest()
    if not secreto or not hmac.compare_digest(esperada, firma):
        return 401
    with _AVISOS_LOCK:
        _AVISOS.add((evento, marca))
    return 200


def _esperar_aviso(eventos: tuple[str, ...], marca: str, segundos: float) -> str | None:
    fin = time.time() + segundos
    while time.time() < fin:
        with _AVISOS_LOCK:
            for e in eventos:
                if (e, marca) in _AVISOS:
                    return e
        time.sleep(0.3)
    return None


def _secreto_companion() -> str | None:
    if os.path.exists(RUTA_COMPANION):
        return open(RUTA_COMPANION, encoding="utf-8").read().strip()
    return None


# --- Emparejado y órdenes: siempre los PIDE la app (por 127.0.0.1); el agente no le manda nada -----------
# (el `am` de Termux envía "a ciegas" y no se puede saber si la app recibió algo; así no hace falta)
_PEDIDO: dict = {}          # la orden de WhatsApp confirmada que espera a que la app la recoja
_PEDIDO_LOCK = __import__("threading").Lock()
_PETICIONES_APP = {"emparejar": 0, "orden": 0, "aviso": 0}  # para el diagnóstico


def _solo_desde_el_movil(ip: str | None) -> bool:
    import ipaddress

    try:
        return ipaddress.ip_address((ip or "").removeprefix("::ffff:")).is_loopback
    except ValueError:
        return False


def app_emparejar(ip: str | None) -> tuple[int, dict]:
    """POST /companion/emparejar: la app pide el secreto. Solo si aún no hay ninguna app emparejada
    (para cambiarla, 'olvidar' desde JARVIS con companion_olvidar)."""
    import secrets as _secrets

    _PETICIONES_APP["emparejar"] += 1
    if not _solo_desde_el_movil(ip):
        return 403, {"error": "solo desde el móvil"}
    if os.path.exists(RUTA_COMPANION):
        return 409, {"error": "ya hay una app emparejada: pide a JARVIS que la olvide primero"}
    secreto = _secrets.token_hex(32)
    with open(RUTA_COMPANION, "w", encoding="utf-8") as f:
        f.write(secreto)
    os.chmod(RUTA_COMPANION, 0o600)
    return 200, {"secreto": secreto}


def app_orden(cuerpo: bytes, ip: str | None) -> tuple[int, dict]:
    """POST /companion/orden: la app (firmando con el secreto) pregunta si hay un WhatsApp confirmado."""
    _PETICIONES_APP["orden"] += 1
    secreto = _secreto_companion()
    if not _solo_desde_el_movil(ip) or not secreto:
        return 403, {}
    try:
        d = json.loads(cuerpo or b"{}")
        marca_peticion, firma = str(d["ts"]), str(d["firma"])
    except (ValueError, KeyError):
        return 400, {}
    esperada = hmac.new(secreto.encode(), f"orden\n{marca_peticion}".encode(), "sha256").hexdigest()
    if not hmac.compare_digest(esperada, firma) or abs(time.time() * 1000 - int(marca_peticion)) > 60_000:
        return 401, {}
    with _PEDIDO_LOCK:
        if not _PEDIDO or time.time() > _PEDIDO["caduca"]:
            return 204, {}
        p = dict(_PEDIDO)
    return 200, {"texto": p["texto"], "marca": p["marca"], "firma": p["firma"]}


def companion_olvidar(_v: str) -> dict:
    """Olvida la app emparejada (para volver a emparejar)."""
    if os.path.exists(RUTA_COMPANION):
        os.remove(RUTA_COMPANION)
    return {"ok": True}


def companion_estado(_v: str) -> dict:
    return {"emparejada": os.path.exists(RUTA_COMPANION), "peticiones_app": dict(_PETICIONES_APP),
            "avisos": len(_AVISOS)}


def whatsapp(v: str) -> dict:
    """Abre el chat con el texto escrito y deja la orden firmada para que la app JARVIS pulse Enviar."""
    from urllib.parse import quote

    d = json.loads(v)
    secreto = _secreto_companion()
    marca = str(int(time.time() * 1000))
    if secreto:
        firma = hmac.new(secreto.encode(), f"{marca}\n{d['texto']}".encode(), "sha256").hexdigest()
        with _PEDIDO_LOCK:
            _PEDIDO.clear()
            _PEDIDO.update(texto=d["texto"], marca=marca, firma=firma, caduca=time.time() + 60)
    ejecutar(["termux-open-url", f"https://wa.me/{d['numero'].lstrip('+')}?text={quote(d['texto'])}"])
    if not secreto:
        return {"ok": True, "automatico": False, "enviado": False}
    # Comprobar de verdad que la app pulsó "Enviar" para ESTA orden: la app lo avisa firmado
    resultado = _esperar_aviso(("enviado", "fallo_pulsar"), marca, ESPERA_ENVIO)
    with _PEDIDO_LOCK:
        _PEDIDO.clear()  # una orden, un intento
    return {"ok": True, "automatico": True, "enviado": resultado == "enviado", "estado_app": resultado or "sin aviso"}


ESPERA_ENVIO = 20  # segundos que se espera a que WhatsApp se abra y la app pulse "Enviar"


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


def diagnostico(_v: str) -> dict:
    """Prueba los comandos de Termux:API que más fallan y devuelve solo códigos y errores (no el contenido)."""
    salida = {"termux": {"origen": os.environ.get("TERMUX_APK_RELEASE", "?"),
                         "version": os.environ.get("TERMUX_VERSION", "?")}}
    try:  # qué tienda instaló cada app de Termux
        r = subprocess.run(["pm", "list", "packages", "-i", "com.termux"], capture_output=True, text=True, timeout=20)
        salida["instaladas"] = [l.removeprefix("package:") for l in r.stdout.split("\n") if l.strip()]
    except Exception as e:  # noqa: BLE001
        salida["instaladas"] = f"error {type(e).__name__}"
    for nombre, cmd, tiempo in (
        ("notificaciones", ["termux-notification-list"], 25),
        ("ubicacion_red", ["termux-location", "-p", "network", "-r", "last"], 25),
        ("ubicacion_gps", ["termux-location", "-p", "gps", "-r", "once"], 45),
    ):
        t0 = time.time()
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=tiempo)
            salida[nombre] = {"codigo": r.returncode, "bytes": len(r.stdout), "error": r.stderr.strip()[:200],
                              "empieza": r.stdout.strip()[:1], "segundos": round(time.time() - t0, 1)}
            if r.stdout.strip()[:1] not in ("{", "["):  # no son datos sino un aviso de Termux:API: se puede ver
                salida[nombre]["aviso"] = r.stdout.strip()[:200]
        except subprocess.TimeoutExpired:
            salida[nombre] = {"timeout": tiempo}
    return salida


ACCIONES = {
    "cambiar_token": cambiar_token, "actualizar": actualizar, "diagnostico": diagnostico,
    "companion_olvidar": companion_olvidar, "companion_estado": companion_estado,
    "estado": estado, "ubicacion": ubicacion, "notificaciones": notificaciones, "linterna": linterna,
    "volumen": volumen, "sonar": sonar, "hablar": hablar, "vibrar": vibrar, "alarma": alarma,
    "temporizador": temporizador, "abrir_web": abrir_web, "abrir_app": abrir_app, "paquetes": paquetes,
    "portapapeles": portapapeles, "sms": sms, "whatsapp": whatsapp, "foto": foto,
}


def token_valido(recibido: str | None, esperado: str) -> bool:
    return bool(esperado) and bool(recibido) and hmac.compare_digest(recibido.encode(), esperado.encode())


def red_permitida(ip: str | None) -> bool:
    """Solo la red privada de Tailscale (100.64.0.0/10) y el propio móvil: nada de Wi-Fi públicas."""
    import ipaddress

    try:
        direccion = ipaddress.ip_address((ip or "").removeprefix("::ffff:"))
    except ValueError:
        return False
    return direccion.is_loopback or direccion in ipaddress.ip_network("100.64.0.0/10")


def atender(cuerpo: bytes, token_recibido: str | None, token: str, ip: str | None = "127.0.0.1") -> tuple[int, dict]:
    """Lógica de una petición (sin red): devuelve (código HTTP, respuesta)."""
    if not red_permitida(ip):
        return 403, {"error": "solo por Tailscale"}
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
        ip = self.client_address[0]
        if self.path.startswith("/companion"):  # la app JARVIS de este mismo móvil
            cuerpo = self.rfile.read(largo)
            if self.path == "/companion/emparejar":
                codigo, respuesta = app_emparejar(ip)
            elif self.path == "/companion/orden":
                codigo, respuesta = app_orden(cuerpo, ip)
            else:  # /companion (aviso firmado: configurada / enviado / fallo_pulsar)
                _PETICIONES_APP["aviso"] += 1
                codigo, respuesta = recibir_aviso(cuerpo, ip, _secreto_companion()), {}
            datos = json.dumps(respuesta).encode() if respuesta else b""
            self.send_response(codigo)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(datos)))
            self.end_headers()
            self.wfile.write(datos)
            return
        codigo, respuesta = atender(self.rfile.read(largo), self.headers.get("X-Jarvis-Token"), self.token,
                                    self.client_address[0])
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
