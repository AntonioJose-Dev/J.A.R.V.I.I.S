import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from jarvis import pc
from jarvis.core import Jarvis
from jarvis.memory import MemoryStore
from jarvis.telegram_bot import decidir_boton_accion

YO = 123
INDICE = {
    "Spotify": r"C:\menu\Spotify.lnk",
    "Brave": r"C:\menu\Brave.lnk",
    "Microsoft Word": r"C:\menu\Word.lnk",
    "WordPad": r"C:\menu\WordPad.lnk",
    "Visual Studio Code": r"C:\menu\Code.lnk",
    "calculadora": "calc.exe",
}


@pytest.fixture
def memoria():
    m = MemoryStore()
    yield m
    m.close()


@pytest.fixture(autouse=True)
def auditoria_temporal(tmp_path, monkeypatch):
    monkeypatch.setenv("JARVIS_AUDITORIA", str(tmp_path / "acciones.log"))
    return tmp_path / "acciones.log"


# --- Programas y webs ---

@pytest.mark.parametrize("pedido, esperado", [
    ("spotify", "Spotify"),
    ("Brave", "Brave"),
    ("word", "Microsoft Word"),         # palabra completa gana a "WordPad"
    ("visual studio", "Visual Studio Code"),
    ("la calculadora", None),            # con artículo no lo adivina…
    ("calculadora", "calculadora"),      # …sin artículo sí
    ("photoshop", None),
])
def test_resolver_app(pedido, esperado):
    r = pc.resolver_app(pedido, INDICE)
    assert (r[0] if r else None) == esperado


def test_url_para():
    assert pc.url_para("youtube.com") == "https://youtube.com"
    assert pc.url_para("https://x.com/a") == "https://x.com/a"
    assert pc.url_para("tiempo en Madrid") == "https://www.google.com/search?q=tiempo+en+Madrid"


# --- Archivos y carpetas permitidas ---

def test_coincide_archivo():
    assert pc.coincide_archivo("Factura_Luz_Octubre.pdf", "factura luz")
    assert pc.coincide_archivo("Currículum Antonio.docx", "curriculum")
    assert not pc.coincide_archivo("factura_agua.pdf", "factura luz")


def test_solo_carpetas_permitidas(tmp_path, monkeypatch):
    permitida = tmp_path / "Documentos"
    permitida.mkdir()
    (permitida / "a.txt").write_text("x")
    fuera = tmp_path / "Windows"
    fuera.mkdir()
    (fuera / "b.txt").write_text("x")
    monkeypatch.setenv("JARVIS_CARPETAS", str(permitida))
    carpetas = pc.carpetas_permitidas()
    assert pc.dentro_de(permitida / "a.txt", carpetas)
    assert not pc.dentro_de(fuera / "b.txt", carpetas)
    assert not pc.dentro_de(permitida / ".." / "Windows" / "b.txt", carpetas)  # sin trucos con ..


# --- Comandos: solo los de la lista ---

def test_lista_de_comandos(tmp_path):
    f = tmp_path / "cmds.json"
    f.write_text(json.dumps({
        "Ver mi IP": {"descripcion": "ipconfig", "comando": ["ipconfig"]},
        "malo": {"comando": "rm -rf /"},  # texto libre: se descarta
    }), encoding="utf-8")
    cmds = pc.cargar_comandos(str(f))
    assert list(cmds) == ["ver mi ip"]


def test_comando_fuera_de_lista_se_rechaza(tmp_path, monkeypatch):
    monkeypatch.setenv("JARVIS_PC_COMANDOS", str(tmp_path / "no_existe.json"))
    with pytest.raises(ValueError, match="lista permitida"):
        pc.preparar_accion("comando", "format c:")


def test_accion_desconocida_se_rechaza():
    with pytest.raises(ValueError):
        pc.preparar_accion("formatear", "C:")


def test_papelera_solo_dentro_de_carpetas(tmp_path, monkeypatch):
    dentro = tmp_path / "Docs"
    dentro.mkdir()
    (dentro / "x.txt").write_text("x")
    (tmp_path / "y.txt").write_text("y")
    monkeypatch.setenv("JARVIS_CARPETAS", str(dentro))
    datos, desc = pc.preparar_accion("papelera", str(dentro / "x.txt"))
    assert datos["accion"] == "papelera" and "x.txt" in desc
    with pytest.raises(ValueError, match="permitidas"):
        pc.preparar_accion("papelera", str(tmp_path / "y.txt"))


# --- Las acciones delicadas nunca se ejecutan sin confirmación ---

async def test_accion_delicada_solo_pide_confirmacion(memoria, monkeypatch):
    pedidas = []

    async def confirmar(accion):
        pedidas.append(accion)

    monkeypatch.setattr(pc, "ejecutar_accion", lambda _: (_ for _ in ()).throw(AssertionError("¡ejecutada!")))
    j = Jarvis(memoria, pedir_confirmacion_pc=confirmar)
    respuesta = await j.accion_pc_delicada(None, accion="apagar")
    assert len(pedidas) == 1 and pedidas[0]["estado"] == "pendiente"
    assert pedidas[0]["datos"] == {"accion": "apagar"}
    assert "NO está hecho" in respuesta


def test_jarvis_tiene_las_herramientas_del_pc(memoria):
    nombres = {t.info.name for t in Jarvis(memoria).tools}
    assert {"abrir_programa", "abrir_web", "buscar_archivo", "enviar_archivo", "multimedia",
            "captura_pantalla", "estado_pc", "bloquear_pc", "accion_pc_delicada"} <= nombres


def test_boton_de_accion(memoria):
    aid = memoria.create_action("pc", {"accion": "apagar"}, "apagar el PC")
    a = memoria.get_action(aid)
    permitidos = frozenset({YO})
    assert decidir_boton_accion(YO, permitidos, f"pc:{aid}:si", a, caducada=False) == "ejecutar"
    assert decidir_boton_accion(YO, permitidos, f"pc:{aid}:no", a, caducada=False) == "cancelar"
    assert decidir_boton_accion(999, permitidos, f"pc:{aid}:si", a, caducada=False) == "ignorar"
    assert decidir_boton_accion(YO, permitidos, f"pc:{aid}:si", a, caducada=True) == "caducada"
    assert decidir_boton_accion(YO, permitidos, f"pc:{aid}:quizas", a, caducada=False) == "ignorar"
    memoria.set_action_status(aid, "ejecutando", only_if="pendiente")
    a = memoria.get_action(aid)
    assert decidir_boton_accion(YO, permitidos, f"pc:{aid}:si", a, caducada=False) == "ya_gestionada"


def test_caducidad():
    a = {"creada": datetime.now(timezone.utc).isoformat()}
    assert not pc.caducada(a)
    assert pc.caducada(a, datetime.now(timezone.utc) + timedelta(minutes=11))


def test_auditoria(auditoria_temporal):
    pc.registrar("prueba", x=1)
    linea = json.loads(Path(auditoria_temporal).read_text(encoding="utf-8").strip())
    assert linea["evento"] == "prueba" and linea["x"] == 1
