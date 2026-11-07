"""Control del PC (Windows) para JARVIS.

Sin confirmación (no rompen nada): abrir programas y webs, buscar archivos y mandártelos,
volumen y música, captura de pantalla, estado del PC y bloquear la pantalla.

Con confirmación por botón en Telegram: cerrar programas, apagar/reiniciar/suspender,
mandar archivos a la papelera, escribir texto en la ventana activa y ejecutar comandos
de la lista permitida (pc_comandos.json). Nunca ejecuta comandos libres.

Todo lo que hace queda apuntado en jarvis_acciones.log.
"""

from __future__ import annotations

import ctypes
import json
import logging
import os
import re
import subprocess
import sys
import time
import unicodedata
import webbrowser
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Awaitable, Callable
from urllib.parse import quote_plus

from livekit.agents import RunContext, function_tool

from . import telegram_api

log = logging.getLogger("jarvis.pc")

CARPETAS_DEFECTO = ("Desktop", "Documents", "Downloads", "Pictures", "Videos", "Music", "OneDrive")
SALTAR_CARPETAS = {"node_modules", ".git", "__pycache__", ".venv", "venv", "AppData", "$RECYCLE.BIN"}
CADUCIDAD = timedelta(minutes=10)
ACCIONES_CON_CONFIRMACION = ("cerrar_programa", "apagar", "reiniciar", "suspender", "papelera", "escribir", "comando")
APPS_SISTEMA = {
    "calculadora": "calc.exe",
    "bloc de notas": "notepad.exe",
    "explorador de archivos": "explorer.exe",
    "explorador": "explorer.exe",
    "configuracion": "ms-settings:",
    "ajustes": "ms-settings:",
    "administrador de tareas": "taskmgr.exe",
    "paint": "mspaint.exe",
    "recortes": "ms-screenclip:",
}
TECLAS = {  # códigos de tecla virtual de Windows
    "subir_volumen": 0xAF, "bajar_volumen": 0xAE, "silenciar": 0xAD,
    "play_pausa": 0xB3, "siguiente": 0xB0, "anterior": 0xB1,
}


# --- Utilidades puras (probadas en tests/test_pc.py) -----------------------------------

def clave(texto: str) -> str:
    sin_tildes = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode().lower()
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]+", " ", sin_tildes)).strip()


def resolver_app(nombre: str, indice: dict[str, str]) -> tuple[str, str] | None:
    """Busca un programa por su nombre. `indice` es {nombre visible: destino}."""
    k = clave(nombre)
    if not k:
        return None
    claves = {clave(n): (n, d) for n, d in indice.items()}
    if k in claves:
        return claves[k]
    palabras = k.split()
    # Por orden de preferencia: palabras completas ("word" -> "Microsoft Word"), prefijo, y por último subcadena
    for criterio in (
        lambda c: all(p in c.split() for p in palabras),
        lambda c: c.startswith(k),
        lambda c: k in c,
    ):
        candidatos = [(n, d) for c, (n, d) in claves.items() if criterio(c)]
        if candidatos:
            return min(candidatos, key=lambda nd: len(nd[0]))
    return None


def es_url(texto: str) -> bool:
    t = texto.strip()
    return bool(re.match(r"^https?://", t)) or bool(re.fullmatch(r"[\w-]+(\.[\w-]+)+(/\S*)?", t))


def url_para(texto: str) -> str:
    t = texto.strip()
    if es_url(t):
        return t if t.startswith("http") else "https://" + t
    return "https://www.google.com/search?q=" + quote_plus(t)


def carpetas_permitidas() -> list[Path]:
    valor = os.getenv("JARVIS_CARPETAS", "").strip()
    if valor:
        rutas = [Path(os.path.expandvars(os.path.expanduser(p.strip()))) for p in valor.split(";") if p.strip()]
    else:
        rutas = [Path.home() / c for c in CARPETAS_DEFECTO]
    return [r.resolve() for r in rutas if r.exists()]


def dentro_de(ruta: Path, carpetas: list[Path]) -> bool:
    try:
        r = ruta.resolve()
    except OSError:
        return False
    return any(r == c or c in r.parents for c in carpetas)


def coincide_archivo(nombre_archivo: str, consulta: str) -> bool:
    nombre = clave(nombre_archivo)
    return all(p in nombre for p in clave(consulta).split())


def cargar_comandos(ruta: str | None = None) -> dict[str, dict]:
    """Lista de comandos permitidos: {"nombre": {"descripcion": "...", "comando": ["prog", "arg"]}}."""
    p = Path(ruta or os.getenv("JARVIS_PC_COMANDOS", "pc_comandos.json"))
    if not p.exists():
        return {}
    datos = json.loads(p.read_text(encoding="utf-8"))
    validos = {}
    for nombre, c in datos.items():
        if isinstance(c, dict) and isinstance(c.get("comando"), list) and all(isinstance(x, str) for x in c["comando"]):
            validos[clave(nombre)] = {"descripcion": c.get("descripcion", nombre), "comando": c["comando"]}
    return validos


def caducada(accion: dict, ahora: datetime | None = None) -> bool:
    return (ahora or datetime.now(timezone.utc)) - datetime.fromisoformat(accion["creada"]) > CADUCIDAD


def registrar(evento: str, **datos) -> None:
    """Auditoría: una línea JSON por acción en jarvis_acciones.log."""
    linea = {"cuando": datetime.now().isoformat(timespec="seconds"), "evento": evento, **datos}
    try:
        with open(os.getenv("JARVIS_AUDITORIA", "jarvis_acciones.log"), "a", encoding="utf-8") as f:
            f.write(json.dumps(linea, ensure_ascii=False) + "\n")
    except OSError:
        log.exception("No pude escribir la auditoría")


# --- Acciones del sistema ---------------------------------------------------------------

_indice_cache: dict[str, str] | None = None


def indice_programas() -> dict[str, str]:
    global _indice_cache
    if _indice_cache is None:
        indice = dict(APPS_SISTEMA)
        for base in (os.environ.get("ProgramData", ""), os.environ.get("APPDATA", "")):
            menu = Path(base) / "Microsoft/Windows/Start Menu/Programs"
            if menu.exists():
                for p in list(menu.rglob("*.lnk")) + list(menu.rglob("*.url")):
                    if not re.search(r"uninstall|desinstalar|readme|release notes|documentation", p.stem, re.I):
                        indice.setdefault(p.stem, str(p))
        # Apps de la Microsoft Store (Spotify, WhatsApp...): no tienen acceso directo en esas carpetas
        try:
            r = subprocess.run(
                ["powershell", "-NoProfile", "-Command",
                 "Get-StartApps | ForEach-Object { $_.Name + [char]9 + $_.AppID }"],
                capture_output=True, text=True, timeout=20, encoding="utf-8", errors="replace",
            )
            for linea in r.stdout.splitlines():
                nombre, _, app_id = linea.partition("\t")
                if nombre and app_id:
                    indice.setdefault(nombre.strip(), "shell:AppsFolder\\" + app_id.strip())
        except (OSError, subprocess.SubprocessError):
            log.warning("No pude leer la lista de apps de Windows")
        _indice_cache = indice
    return _indice_cache


def pulsar_tecla(vk: int, veces: int = 1) -> None:
    user32 = ctypes.windll.user32
    for _ in range(max(1, min(veces, 25))):
        user32.keybd_event(vk, 0, 0, 0)
        user32.keybd_event(vk, 0, 2, 0)  # soltar


def captura_png() -> bytes:
    import mss
    import mss.tools

    with mss.mss() as s:
        img = s.grab(s.monitors[0])
        return mss.tools.to_png(img.rgb, img.size)


def estado() -> str:
    import psutil

    partes = []
    bat = psutil.sensors_battery()
    if bat:
        partes.append(f"batería {bat.percent:.0f}%" + (" (enchufado)" if bat.power_plugged else ""))
    partes.append(f"procesador {psutil.cpu_percent(interval=0.3):.0f}%")
    ram = psutil.virtual_memory()
    partes.append(f"memoria {ram.percent:.0f}% usada de {ram.total / 2**30:.0f} GB")
    disco = psutil.disk_usage(str(Path.home().anchor))
    partes.append(f"disco {disco.free / 2**30:.0f} GB libres de {disco.total / 2**30:.0f} GB")
    horas = (time.time() - psutil.boot_time()) / 3600
    partes.append(f"encendido desde hace {horas:.0f} h" if horas >= 1 else "encendido hace menos de una hora")
    return ", ".join(partes)


def _escribir_unicode(texto: str) -> None:
    """Teclea `texto` en la ventana activa (SendInput con caracteres Unicode)."""
    class KEYBDINPUT(ctypes.Structure):
        _fields_ = [("wVk", ctypes.c_ushort), ("wScan", ctypes.c_ushort), ("dwFlags", ctypes.c_ulong),
                    ("time", ctypes.c_ulong), ("dwExtraInfo", ctypes.c_size_t)]

    class INPUT(ctypes.Structure):
        class _U(ctypes.Union):
            _fields_ = [("ki", KEYBDINPUT), ("pad", ctypes.c_byte * 32)]
        _anonymous_ = ("u",)
        _fields_ = [("type", ctypes.c_ulong), ("u", _U)]

    for ch in texto:
        for flags in (0x0004, 0x0004 | 0x0002):  # KEYEVENTF_UNICODE, + KEYUP
            i = INPUT(type=1)
            i.ki = KEYBDINPUT(0, ord(ch), flags, 0, 0)
            ctypes.windll.user32.SendInput(1, ctypes.byref(i), ctypes.sizeof(INPUT))


def preparar_accion(accion: str, objetivo: str) -> tuple[dict, str]:
    """Valida una acción delicada y devuelve (datos, descripción para confirmar). Lanza ValueError si no vale."""
    objetivo = (objetivo or "").strip()
    if accion not in ACCIONES_CON_CONFIRMACION:
        raise ValueError(f"acción desconocida: {accion}")
    if accion == "cerrar_programa":
        if not objetivo:
            raise ValueError("falta el nombre del programa")
        return {"accion": accion, "objetivo": objetivo}, f"cerrar «{objetivo}»"
    if accion in ("apagar", "reiniciar", "suspender"):
        verbo = {"apagar": "apagar", "reiniciar": "reiniciar", "suspender": "suspender"}[accion]
        return {"accion": accion}, f"{verbo} el PC" + ("" if accion == "suspender" else " (en 30 segundos)")
    if accion == "papelera":
        ruta = Path(objetivo)
        if not ruta.exists():
            raise ValueError(f"no existe {objetivo}")
        if not dentro_de(ruta, carpetas_permitidas()):
            raise ValueError("solo puedo tocar archivos de tus carpetas permitidas")
        return {"accion": accion, "objetivo": str(ruta.resolve())}, f"mandar a la papelera «{ruta.name}»"
    if accion == "escribir":
        if not objetivo:
            raise ValueError("falta el texto")
        corto = objetivo if len(objetivo) <= 120 else objetivo[:117] + "…"
        return {"accion": accion, "objetivo": objetivo[:2000]}, f"escribir en la ventana activa: «{corto}»"
    comandos = cargar_comandos()
    k = clave(objetivo)
    if k not in comandos:
        raise ValueError("ese comando no está en la lista permitida (pc_comandos.json)")
    return {"accion": accion, "objetivo": k}, f"ejecutar «{comandos[k]['descripcion']}»"


def ejecutar_accion(datos: dict) -> str:
    """Ejecuta una acción YA confirmada por el dueño."""
    accion, objetivo = datos["accion"], datos.get("objetivo", "")
    registrar("ejecutar", accion=accion, objetivo=objetivo)
    if accion == "cerrar_programa":
        import psutil

        k = clave(objetivo)
        cerrados = 0
        for p in psutil.process_iter(["name"]):
            nombre = clave(Path(p.info["name"] or "").stem)
            if nombre and (nombre == k or k in nombre):
                try:
                    p.terminate()
                    cerrados += 1
                except psutil.Error:
                    pass
        return f"He cerrado {cerrados} proceso(s) de {objetivo}." if cerrados else f"No encontré {objetivo} abierto."
    if accion == "apagar":
        subprocess.run(["shutdown", "/s", "/t", "30"], check=True)
        return "El PC se apagará en 30 segundos (para cancelarlo: shutdown /a)."
    if accion == "reiniciar":
        subprocess.run(["shutdown", "/r", "/t", "30"], check=True)
        return "El PC se reiniciará en 30 segundos (para cancelarlo: shutdown /a)."
    if accion == "suspender":
        subprocess.Popen(["rundll32.exe", "powrprof.dll,SetSuspendState", "0,1,0"])
        return "Suspendiendo el PC."
    if accion == "papelera":
        from send2trash import send2trash

        send2trash(objetivo)
        return f"«{Path(objetivo).name}» está en la papelera (se puede recuperar)."
    if accion == "escribir":
        time.sleep(0.3)
        _escribir_unicode(objetivo)
        return "Texto escrito."
    if accion == "comando":
        comando = cargar_comandos()[objetivo]["comando"]
        r = subprocess.run(comando, capture_output=True, text=True, timeout=60, shell=False,
                           encoding="utf-8", errors="replace")
        salida = (r.stdout or r.stderr or "").strip()
        salida = salida if len(salida) <= 1500 else salida[:1500] + "\n…"
        return f"Hecho (código {r.returncode}).\n{salida}".strip()
    raise ValueError(f"acción desconocida: {accion}")


# --- Herramientas para el cerebro --------------------------------------------------------

class ControlPC:
    """Herramientas del PC. Se mezcla en la clase Jarvis (necesita self.memory)."""

    _pedir_confirmacion_pc: Callable[[dict], Awaitable[None]] | None = None

    @function_tool
    async def abrir_programa(self, context: RunContext, nombre: str) -> str:
        """Abre un programa del PC por su nombre, por ejemplo "Spotify", "Brave" o "calculadora".

        Args:
            nombre: nombre del programa.
        """
        encontrado = resolver_app(nombre, indice_programas())
        if not encontrado:
            return f"No encuentro ningún programa que se llame {nombre}."
        visible, destino = encontrado
        registrar("abrir_programa", nombre=visible)
        os.startfile(destino)  # noqa: S606 (destino viene del menú Inicio o de la lista fija)
        return f"Abriendo {visible}."

    @function_tool
    async def abrir_web(self, context: RunContext, direccion_o_busqueda: str) -> str:
        """Abre una web en el navegador, o busca en Google si no es una dirección.

        Args:
            direccion_o_busqueda: por ejemplo "youtube.com" o "tiempo en Madrid mañana".
        """
        url = url_para(direccion_o_busqueda)
        registrar("abrir_web", url=url)
        webbrowser.open(url)
        return f"Abierto: {url}"

    @function_tool
    async def buscar_archivo(self, context: RunContext, nombre: str) -> str:
        """Busca archivos por su nombre en las carpetas del usuario (Escritorio, Documentos, Descargas, Imágenes...).

        Args:
            nombre: palabras del nombre del archivo, por ejemplo "factura luz".
        """
        encontrados = []
        inicio = time.monotonic()
        for carpeta in carpetas_permitidas():
            for raiz, dirs, archivos in os.walk(carpeta):
                dirs[:] = [d for d in dirs if d not in SALTAR_CARPETAS and not d.startswith(".")]
                encontrados += [Path(raiz) / a for a in archivos if coincide_archivo(a, nombre)]
                if time.monotonic() - inicio > 6:
                    break
        registrar("buscar_archivo", consulta=nombre, resultados=len(encontrados))
        if not encontrados:
            return f"No he encontrado archivos con «{nombre}»."
        encontrados.sort(key=lambda p: p.stat().st_mtime, reverse=True)
        lineas = [f"- {p} ({datetime.fromtimestamp(p.stat().st_mtime):%d/%m/%Y})" for p in encontrados[:8]]
        extra = f"\n(y {len(encontrados) - 8} más)" if len(encontrados) > 8 else ""
        return "Encontrados (más recientes primero):\n" + "\n".join(lineas) + extra

    @function_tool
    async def enviar_archivo(self, context: RunContext, ruta: str) -> str:
        """Manda un archivo del PC al Telegram del usuario. Usa la ruta exacta que dio buscar_archivo.

        Args:
            ruta: ruta completa del archivo.
        """
        p = Path(ruta)
        if not p.is_file():
            return "Ese archivo no existe."
        if not dentro_de(p, carpetas_permitidas()):
            return "Solo puedo mandar archivos de las carpetas permitidas."
        registrar("enviar_archivo", ruta=str(p))
        telegram_api.enviar_archivo(p.name, p.read_bytes(), caption=p.name)
        return f"Te he mandado «{p.name}» por Telegram."

    @function_tool
    async def multimedia(self, context: RunContext, accion: str, veces: int = 1) -> str:
        """Controla el volumen y la música del PC.

        Args:
            accion: subir_volumen, bajar_volumen, silenciar, play_pausa, siguiente o anterior.
            veces: cuántas veces (para el volumen, cada vez son 2 puntos).
        """
        if accion not in TECLAS:
            return "Acción no válida. Usa: " + ", ".join(TECLAS)
        registrar("multimedia", accion=accion, veces=veces)
        pulsar_tecla(TECLAS[accion], veces if "volumen" in accion else 1)
        return "Hecho."

    @function_tool
    async def captura_pantalla(self, context: RunContext) -> str:
        """Hace una captura de la pantalla del PC y se la manda al usuario por Telegram."""
        registrar("captura_pantalla")
        telegram_api.enviar_archivo("pantalla.png", captura_png(), caption="Tu pantalla ahora mismo", como_foto=True)
        return ("Captura enviada por Telegram. (Todavía no puedo ver la imagen yo mismo: "
                "el cerebro actual no entiende imágenes.)")

    @function_tool
    async def estado_pc(self, context: RunContext) -> str:
        """Dice cómo está el PC: batería, procesador, memoria, disco y tiempo encendido."""
        registrar("estado_pc")
        return estado()

    @function_tool
    async def bloquear_pc(self, context: RunContext) -> str:
        """Bloquea la pantalla del PC (para volver hay que poner la contraseña o PIN)."""
        registrar("bloquear_pc")
        ctypes.windll.user32.LockWorkStation()
        return "PC bloqueado."

    @function_tool
    async def accion_pc_delicada(self, context: RunContext, accion: str, objetivo: str = "") -> str:
        """Pide permiso al usuario (botón en Telegram) para una acción delicada en el PC. No la hace todavía.

        Args:
            accion: cerrar_programa, apagar, reiniciar, suspender, papelera (borrar un archivo),
                escribir (teclear texto en la ventana activa) o comando (de la lista permitida).
            objetivo: el programa, la ruta del archivo, el texto o el nombre del comando, según la acción.
        """
        try:
            datos, descripcion = preparar_accion(accion, objetivo)
        except ValueError as e:
            return f"No puedo: {e}."
        accion_id = self.memory.create_action("pc", datos, descripcion)
        registrar("pedir_confirmacion", id=accion_id, accion=accion, objetivo=datos.get("objetivo", ""))
        pedir = self._pedir_confirmacion_pc or _pedir_por_telegram
        await pedir(self.memory.get_action(accion_id))
        return (f"He pedido confirmación en Telegram para {descripcion}. NO está hecho todavía: "
                "se hará cuando el usuario pulse Sí.")


async def _pedir_por_telegram(accion: dict) -> None:
    telegram_api.pedir_confirmacion(
        f"🖥️ JARVIS quiere {accion['descripcion']} en tu PC. ¿Le dejas?\n(Caduca en 10 minutos.)",
        "pc", accion["id"],
    )


if sys.platform != "win32":  # en otros sistemas no hay control del PC
    ControlPC = type("ControlPC", (), {})  # type: ignore[misc]
