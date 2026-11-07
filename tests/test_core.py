from datetime import datetime

from jarvis.core import TZ, fecha_hora_texto, limpiar_para_voz, nota_de_hora
from jarvis.memory import MemoryStore


def test_fecha_hora_en_espanol():
    momento = datetime(2026, 11, 7, 13, 20, tzinfo=TZ)
    assert fecha_hora_texto(momento) == "sábado 7 de noviembre de 2026, 13:20"


def test_nota_de_hora_incluye_la_hora_real_y_prohibe_inventarla():
    nota = nota_de_hora(datetime(2026, 11, 7, 13, 20, tzinfo=TZ))
    assert "13:20" in nota
    assert "nunca te la inventes" in nota


def test_limpiar_para_voz_quita_markdown_emojis_y_enlaces():
    texto = "**Hecho**, señor 😊. Mire https://ejemplo.com\n- uno\n- dos"
    assert limpiar_para_voz(texto) == "Hecho, señor. Mire el enlace uno dos"


def test_limpiar_para_voz_dice_las_horas():
    assert limpiar_para_voz("Son las 13:23.") == "Son las 13 y 23."
    assert limpiar_para_voz("A las 09:05") == "A las 9 y 5"
    assert limpiar_para_voz("Quedamos a las 11:00") == "Quedamos a las 11 en punto"


def test_ajustes_persisten_entre_reinicios(tmp_path):
    db = tmp_path / "m.db"
    m = MemoryStore(db)
    assert m.get_setting("x", "0") == "0"
    m.set_setting("x", "1")
    m.set_setting("x", "2")
    m.close()
    assert MemoryStore(db).get_setting("x") == "2"
