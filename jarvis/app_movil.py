"""Conexión directa entre la app JARVIS del móvil y JARVIS en el PC (por Tailscale).

- El PC escucha SOLO en su dirección de Tailscale (100.x), no en la Wi-Fi ni en internet.
- La app se conecta ella misma (no hace falta abrir nada en el móvil) y pregunta en bucle si hay trabajo
  ("long-poll"). Cada petición lleva el código secreto de la app (JARVIS_APP_TOKEN).
- Los trabajos (p. ej. enviar un WhatsApp YA confirmado por el dueño) se guardan en la base de datos, así
  cualquier parte de JARVIS (Telegram, /hablar, llamadas) puede encargarlos y esperar el resultado.
- La app informa de su estado y de sus errores; el PC los guarda para poder explicarlos sin capturas.
"""

from __future__ import annotations

import asyncio
import hmac
import json
import logging
import os
import re
import sqlite3
import subprocess
import time

from aiohttp import web

log = logging.getLogger("jarvis.app_movil")
PUERTO = int(os.getenv("JARVIS_APP_PUERTO", "8800"))
ESPERA_LARGA = 25          # segundos que la app espera por trabajo en cada petición
EN_LINEA_SI = 90           # la app cuenta como conectada si habló con el PC hace menos de esto
ESPERA_RESULTADO = 45      # cuánto espera JARVIS a que la app termine un envío
ESPERA_DESBLOQUEO = 230    # ...o, si el móvil está bloqueado, a que el dueño lo desbloquee (la app espera 3 min)


# --- Base de datos compartida (todas las partes de JARVIS usan el mismo archivo) -------------------

def _db() -> sqlite3.Connection:
    db = sqlite3.connect(os.getenv("JARVIS_MEMORY_PATH", "jarvis_memoria.db"), timeout=10)
    db.executescript(
        "CREATE TABLE IF NOT EXISTS app_trabajos (id INTEGER PRIMARY KEY AUTOINCREMENT, tipo TEXT, datos TEXT,"
        " estado TEXT, resultado TEXT, creado REAL);"
        "CREATE TABLE IF NOT EXISTS app_estado (clave TEXT PRIMARY KEY, valor TEXT);"
    )
    columnas = {c[1] for c in db.execute("PRAGMA table_info(app_trabajos)")}
    for col, tipo in (("entregado", "REAL"), ("paso", "TEXT")):
        if col not in columnas:
            db.execute(f"ALTER TABLE app_trabajos ADD COLUMN {col} {tipo}")
    return db


def guardar_estado(**valores) -> None:
    db = _db()
    with db:
        for k, v in valores.items():
            db.execute("INSERT OR REPLACE INTO app_estado (clave, valor) VALUES (?, ?)", (k, str(v)))
    db.close()


def estado() -> dict:
    db = _db()
    d = dict(db.execute("SELECT clave, valor FROM app_estado").fetchall())
    db.close()
    ultimo = float(d.get("ultimo_contacto", "0") or 0)
    d["en_linea"] = time.time() - ultimo < EN_LINEA_SI
    return d


def encargar(tipo: str, datos: dict) -> int:
    db = _db()
    with db:
        cur = db.execute("INSERT INTO app_trabajos (tipo, datos, estado, creado) VALUES (?, ?, 'pendiente', ?)",
                         (tipo, json.dumps(datos, ensure_ascii=False), time.time()))
    db.close()
    return cur.lastrowid


ACUSE_EN = 6  # si la app no confirma que lo recibió en estos segundos, se le vuelve a entregar
EN_CURSO = ("pendiente", "entregado", "recibido")


def _siguiente_trabajo(reentregar: bool = False) -> dict | None:
    """El trabajo pendiente más antiguo (de menos de 60 s); lo marca como 'entregado'.

    Una entrega puede perderse (la conexión del móvil murió sin que el PC se enterase: pantalla apagada,
    cambio de Wi-Fi a datos...). Por eso la app tiene que acusar recibo; si no lo hace, se reentrega.
    """
    ahora = time.time()
    db = _db()
    with db:
        db.execute("UPDATE app_trabajos SET estado='caducado' WHERE estado IN ('pendiente','entregado') AND creado < ?",
                   (ahora - 60,))
        if reentregar:  # solo con apps que acusan recibo (1.7+); si no, podría mandarse dos veces
            db.execute("UPDATE app_trabajos SET estado='pendiente' WHERE estado='entregado' AND entregado < ?",
                       (ahora - ACUSE_EN,))
        fila = db.execute("SELECT id, tipo, datos FROM app_trabajos WHERE estado='pendiente' ORDER BY id LIMIT 1").fetchone()
        if fila:
            db.execute("UPDATE app_trabajos SET estado='entregado', entregado=? WHERE id=?", (ahora, fila[0]))
    db.close()
    return {"id": fila[0], "tipo": fila[1], "datos": json.loads(fila[2])} if fila else None


def _guardar_resultado(trabajo_id: int, estado_: str, detalle: str) -> None:
    db = _db()
    with db:
        if estado_ == "recibido":  # acuse de recibo: solo cuenta mientras el trabajo sigue sin empezar
            db.execute("UPDATE app_trabajos SET estado='recibido' WHERE id=? AND estado IN ('pendiente','entregado')",
                       (trabajo_id,))
        else:
            # Lo leído de un chat se guarda un momento (lo recoge leer_chat y lo borra); lo demás, sin texto de chats
            guardado = detalle[:20000] if estado_ == "leido" else privado(detalle)[:500]
            db.execute("UPDATE app_trabajos SET estado=?, resultado=? WHERE id=? AND estado IN ('pendiente','entregado','recibido')",
                       (estado_, guardado, trabajo_id))
    db.close()


def leer_chat(numero: str, segundos: float = 40) -> list[dict]:
    """Pide a la app que lea los últimos mensajes del chat con `numero`. El texto NO se queda guardado:
    se borra de la base de datos en cuanto se recoge (va solo al cerebro, para esta petición)."""
    trabajo = encargar("leer_chat", {"numero": numero})
    estado_, detalle = esperar_resultado(trabajo, segundos)
    db = _db()
    with db:
        db.execute("UPDATE app_trabajos SET resultado=NULL WHERE id=?", (trabajo,))
    db.close()
    if estado_ != "leido":
        raise RuntimeError(detalle or estado_)
    try:
        mensajes = json.loads(detalle)
    except ValueError as e:
        raise RuntimeError("la app devolvió algo ilegible") from e
    return [m for m in mensajes if isinstance(m, dict) and m.get("texto")]


_PRIVADO = re.compile(r"\[(message_text|single_msg_tv|conversations_row_message_view|caption|quoted_text)\|[^|\]]*")
_PRIVADO_DESC = re.compile(r"\[(main_layout|contact_row_container|contact_selector)\|([^|\]]*)\|[^|\]]*")


def privado(texto: str) -> str:
    """Quita de lo que cuenta la app el contenido de los chats (mensajes, vistas previas): solo deja los botones."""
    texto = _PRIVADO.sub(lambda m: f"[{m.group(1)}|(oculto)", texto)
    return _PRIVADO_DESC.sub(lambda m: f"[{m.group(1)}|{m.group(2)}|(oculto)", texto)


def _guardar_paso(trabajo_id: int, paso: str) -> None:
    paso = privado(paso)
    db = _db()
    with db:
        db.execute("UPDATE app_trabajos SET paso=? WHERE id=?", (paso[:1500], trabajo_id))
    db.close()


def esperar_resultado(trabajo_id: int, segundos: float = ESPERA_RESULTADO) -> tuple[str, str]:
    """(estado, detalle) cuando la app termine; ('sin_respuesta', motivo) si no contesta a tiempo."""
    inicio = time.time()
    fin = inicio + segundos
    fila = None
    while time.time() < fin:
        db = _db()
        fila = db.execute("SELECT estado, resultado, paso FROM app_trabajos WHERE id=?", (trabajo_id,)).fetchone()
        db.close()
        if fila and fila[0] not in EN_CURSO:
            return fila[0], fila[1] or ""
        if fila and (fila[2] or "").startswith(("esperando desbloqueo", "móvil desbloqueado")):
            fin = max(fin, inicio + ESPERA_DESBLOQUEO)  # la app espera a que el dueño desbloquee (máx. 3 min)
        time.sleep(0.5)
    if fila and fila[0] == "recibido":
        motivo = f"la app lo recibió pero no terminó a tiempo (último paso: {fila[2] or 'ninguno'})"
    else:
        motivo = "el encargo no llegó al móvil (¿sin internet, o la app JARVIS dormida por el ahorro de batería?)"
    _guardar_resultado(trabajo_id, "sin_respuesta", motivo)
    return "sin_respuesta", motivo


# --- Servidor (vive dentro del proceso del bot de Telegram) --------------------------------------------

def ip_tailscale() -> str | None:
    try:
        r = subprocess.run([r"C:\Program Files\Tailscale\tailscale.exe" if os.name == "nt" else "tailscale", "ip", "-4"],
                           capture_output=True, text=True, timeout=10)
        ip = r.stdout.strip().splitlines()[0] if r.stdout.strip() else ""
        return ip if ip.startswith("100.") else None
    except (OSError, subprocess.SubprocessError, IndexError):
        return None


def token_valido(recibido: str | None) -> bool:
    esperado = os.getenv("JARVIS_APP_TOKEN", "").strip()
    return bool(esperado) and bool(recibido) and hmac.compare_digest(recibido.encode(), esperado.encode())


async def _leer(request: web.Request) -> dict | None:
    if not token_valido(request.headers.get("X-Jarvis-Token")):
        log.warning("Petición de la app con código incorrecto desde %s", request.remote)
        return None
    try:
        datos = await request.json()
    except (ValueError, json.JSONDecodeError):
        datos = {}
    guardar_estado(ultimo_contacto=time.time(), version=datos.get("version", "?"),
                   accesibilidad=datos.get("accesibilidad", "?"))
    return datos


async def _hola(request: web.Request) -> web.Response:
    datos = await _leer(request)
    if datos is None:
        return web.json_response({"error": "código incorrecto"}, status=401)
    if datos.get("error"):
        guardar_estado(ultimo_error=f"{time.strftime('%H:%M:%S')} {datos['error'][:300]}")
        log.warning("La app JARVIS informa de un error: %s", datos["error"][:300])
    if datos.get("evento"):
        log.info("App JARVIS (%s): %s", datos.get("version", "?"), str(datos["evento"])[:200])
    if datos.get("paso") and str(datos.get("id", "")).isdigit():
        await asyncio.to_thread(_guardar_paso, int(datos["id"]), str(datos["paso"]))
        log.info("App, trabajo %s: %s", datos["id"], privado(str(datos["paso"]))[:1500])
        if str(datos["paso"]).startswith("esperando desbloqueo"):
            await asyncio.to_thread(avisar_desbloqueo)
    return web.json_response({"ok": True})


def avisar_desbloqueo() -> None:
    """El WhatsApp está confirmado pero el móvil está bloqueado: se le pide al dueño que lo desbloquee."""
    from . import telegram_api

    try:
        chat = telegram_api.chat_del_dueno()
        if chat is not None:
            telegram_api.telegram("sendMessage", chat_id=chat,
                                  text="🔒 Desbloquea el móvil y JARVIS enviará el WhatsApp (tienes 3 minutos).")
    except Exception as e:  # el aviso es una ayuda; si falla, el envío sigue esperando igual
        log.warning("No pude avisar por Telegram de que desbloquee el móvil: %s", e)


async def _espera(request: web.Request) -> web.Response:
    datos = await _leer(request)
    if datos is None:
        return web.json_response({"error": "código incorrecto"}, status=401)
    reentregar = datos.get("acuse") is True
    fin = time.time() + ESPERA_LARGA
    while time.time() < fin:
        if request.transport is None or request.transport.is_closing():
            return web.Response(status=204)  # el móvil ya colgó: no le entregues nada por aquí
        trabajo = await asyncio.to_thread(_siguiente_trabajo, reentregar)
        if trabajo:
            log.info("Trabajo %s entregado a la app (%s)", trabajo["id"], trabajo["tipo"])
            return web.json_response(trabajo)
        await asyncio.sleep(0.7)
    return web.Response(status=204)


async def _resultado(request: web.Request) -> web.Response:
    datos = await _leer(request)
    if datos is None:
        return web.json_response({"error": "código incorrecto"}, status=401)
    try:
        await asyncio.to_thread(_guardar_resultado, int(datos["id"]), str(datos["estado"]), str(datos.get("detalle", "")))
    except (KeyError, ValueError):
        return web.json_response({"error": "faltan datos"}, status=400)
    if datos["estado"] == "leido":  # el contenido de un chat nunca va al log
        log.info("La app terminó el trabajo %s: chat leído", datos["id"])
    else:
        log.info("La app terminó el trabajo %s: %s %s", datos["id"], datos["estado"], privado(str(datos.get("detalle", "")))[:300])
    return web.json_response({"ok": True})


def _audio_en_curso(huella: str) -> bool:
    """Solo se entrega un audio si pertenece a un encargo que está ahora mismo en marcha."""
    db = _db()
    filas = db.execute("SELECT datos FROM app_trabajos WHERE tipo='whatsapp_audio' AND estado IN ('entregado','recibido')"
                       ).fetchall()
    db.close()
    return any(json.loads(d).get("sha256") == huella for (d,) in filas)


async def _audio(request: web.Request) -> web.Response:
    datos = await _leer(request)
    if datos is None:
        return web.json_response({"error": "código incorrecto"}, status=401)
    from . import audio

    huella = str(datos.get("sha256", ""))
    contenido = audio.leer(huella) if await asyncio.to_thread(_audio_en_curso, huella) else None
    if contenido is None:
        return web.json_response({"error": "no hay ese audio"}, status=404)
    log.info("Audio %s… entregado a la app (%d KB)", huella[:8], len(contenido) // 1024)
    return web.Response(body=contenido, content_type="audio/ogg")


async def arrancar_servidor() -> web.AppRunner | None:
    """Arranca el servidor en la IP de Tailscale. Sin Tailscale o sin código, no arranca (y lo dice)."""
    if not os.getenv("JARVIS_APP_TOKEN", "").strip():
        log.info("Servidor de la app desactivado (falta JARVIS_APP_TOKEN)")
        return None
    ip = ip_tailscale()
    if not ip:
        log.warning("Servidor de la app desactivado: Tailscale no está activo en el PC")
        return None
    app = web.Application(client_max_size=64 * 1024)
    app.add_routes([web.post("/app/hola", _hola), web.post("/app/espera", _espera),
                    web.post("/app/resultado", _resultado), web.post("/app/audio", _audio)])
    runner = web.AppRunner(app, access_log=None)
    await runner.setup()
    await web.TCPSite(runner, ip, PUERTO).start()
    log.info("Servidor de la app JARVIS escuchando en %s:%d (solo Tailscale)", ip, PUERTO)
    return runner
