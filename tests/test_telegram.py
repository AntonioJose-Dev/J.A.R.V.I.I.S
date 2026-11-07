import io

import av
import numpy as np

from jarvis.telegram_bot import (
    decidir,
    parse_ids,
    pcm_a_ogg_opus,
    que_enviar,
    tipo_de_mensaje,
)

YO = 123456789
PERMITIDOS = frozenset({YO})


def test_parse_ids():
    assert parse_ids("123, 456;789") == {123, 456, 789}
    assert parse_ids("") == frozenset()
    assert parse_ids(None) == frozenset()
    assert parse_ids("abc, 42") == {42}


def test_tipo_de_mensaje():
    assert tipo_de_mensaje("hola", False) == "texto"
    assert tipo_de_mensaje(None, True) == "voz"
    assert tipo_de_mensaje("/id", False) == "id"
    assert tipo_de_mensaje("/id@JarvisBot", False) == "id"
    assert tipo_de_mensaje("/start", False) == "start"
    assert tipo_de_mensaje("/olvida", False) == "olvida"
    assert tipo_de_mensaje("   ", False) is None
    assert tipo_de_mensaje(None, False) is None  # foto, sticker...


def test_usuario_permitido_recibe_respuesta():
    assert decidir(YO, PERMITIDOS, "texto") == "texto"
    assert decidir(YO, PERMITIDOS, "voz") == "voz"
    assert decidir(YO, PERMITIDOS, "olvida") == "olvida"


def test_desconocido_es_ignorado():
    for tipo in ("texto", "voz", "start", "olvida"):
        assert decidir(999, PERMITIDOS, tipo) == "ignorar"


def test_id_funciona_para_cualquiera_aunque_la_lista_este_vacia():
    assert decidir(999, PERMITIDOS, "id") == "id"
    assert decidir(999, frozenset(), "id") == "id"


def test_lista_vacia_no_deja_pasar_a_nadie():
    assert decidir(YO, frozenset(), "texto") == "ignorar"


def test_mensajes_sin_contenido_o_sin_usuario_se_ignoran():
    assert decidir(YO, PERMITIDOS, None) == "ignorar"
    assert decidir(None, PERMITIDOS, "texto") == "ignorar"


def test_comando_voz():
    assert tipo_de_mensaje("/voz", False) == "alternar_voz"
    assert decidir(YO, PERMITIDOS, "alternar_voz") == "alternar_voz"
    assert decidir(999, PERMITIDOS, "alternar_voz") == "ignorar"


def test_por_defecto_siempre_con_audio():
    assert que_enviar(me_mando_audio=True, modo_texto=False) == (False, True)
    assert que_enviar(me_mando_audio=False, modo_texto=False) == (False, True)  # aunque escriba


def test_modo_texto_con_voz():
    assert que_enviar(me_mando_audio=False, modo_texto=True) == (True, False)
    assert que_enviar(me_mando_audio=True, modo_texto=True) == (False, True)  # a un audio, siempre audio


def test_pcm_a_ogg_opus_genera_audio_valido():
    rate = 24000
    t = np.arange(rate) / rate
    pcm = (np.sin(2 * np.pi * 440 * t) * 8000).astype(np.int16).tobytes()  # 1 s de tono
    ogg = pcm_a_ogg_opus(pcm, rate, 1)
    assert ogg[:4] == b"OggS"
    with av.open(io.BytesIO(ogg)) as f:
        s = f.streams.audio[0]
        assert s.codec_context.name == "opus"
        dur = sum(fr.samples for fr in f.decode(s)) / s.codec_context.sample_rate
    assert 0.9 < dur < 1.2
