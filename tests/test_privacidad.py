"""Lo que dicen las personas no va a los registros."""

import json
import logging

from jarvis import privacidad


def test_los_campos_lk_pii_nunca_llegan_al_registro(caplog):
    privacidad.instalar()
    log = logging.getLogger("prueba.privacidad")
    with caplog.at_level(logging.INFO):
        log.info("amd prediction", extra={"lk.pii.transcript": "Hola, soy Carmen, dime", "category": "human"})
    r = caplog.records[-1]
    assert not hasattr(r, "lk.pii.transcript") and getattr(r, "category") == "human"


def test_jarvis_no_llama_a_tarificacion_especial_ni_emergencias():
    from jarvis import telefono

    for malo in ["+34905123456", "+34806123456", "+34807123456", "+34803123456", "+34902123456", "+34901123456",
                 "+34118221234", "112", "+34112", "091"]:
        assert telefono.numero_permitido(malo) is False, malo
    for bueno in ["+34664089414", "+34912345678", "+34900123456", "+34871234567"]:
        assert telefono.numero_permitido(bueno) is True, bueno


def test_limpiar_logs_antiguos(tmp_path):
    p = tmp_path / "telegram.log"
    linea_json = json.dumps({"message": "amd prediction", "lk.pii.transcript": "secreto de Carmen", "category": "human"})
    p.write_text("2026-11-08 INFO jarvis.telegram: Nota de voz transcrita: Llama a mi madre\n"
                 "2026-11-08 INFO jarvis.telegram: Voz desde el móvil: abre YouTube\n"
                 f"{linea_json}\n"
                 "2026-11-08 INFO otra cosa\n", encoding="utf-8")
    assert privacidad.limpiar_archivo(p) == 3
    t = p.read_text(encoding="utf-8")
    assert "madre" not in t and "YouTube" not in t and "Carmen" not in t
    assert "Nota de voz transcrita (16 caracteres)" in t and '"category": "human"' in t and "otra cosa" in t
