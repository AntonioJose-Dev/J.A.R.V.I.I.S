import pytest

from jarvis import movil, telefono
from jarvis.core import Jarvis
from jarvis.memory import MemoryStore

BATERIA = """Current Battery Service state:
  AC powered: false
  USB powered: true
  Wireless powered: false
  status: 2
  level: 87
  temperature: 312
"""

NOTIFICACIONES = """
  NotificationRecord(0x0abc: pkg=com.whatsapp user=UserHandle{0} id=1 tag=null importance=4 key=0|com.whatsapp|1)
      android.title=String (Mamá)
      android.text=String (¿Vienes a cenar?)
  NotificationRecord(0x0abd: pkg=com.google.android.gm user=UserHandle{0} id=2)
      android.title=String (Banco)
      android.text=SpannableString (Su recibo está disponible)
  NotificationRecord(0x0abe: pkg=android user=UserHandle{0} id=3)
      android.subText=String (sin título)
  NotificationRecord(0x0abc: pkg=com.whatsapp user=UserHandle{0} id=1)
      android.title=String (Mamá)
      android.text=String (¿Vienes a cenar?)
"""

UBICACION = "  last location=Location[fused 40.416775,-3.703790 hAcc=12 et=+1d2h mock=false]"


def test_bateria():
    assert movil.parse_bateria(BATERIA) == {"nivel": 87, "cargando": True, "temperatura": 31.2}


def test_notificaciones_sin_duplicados_ni_vacias():
    assert movil.parse_notificaciones(NOTIFICACIONES) == [
        ("com.whatsapp", "Mamá", "¿Vienes a cenar?"),
        ("com.google.android.gm", "Banco", "Su recibo está disponible"),
    ]


def test_ubicacion():
    assert movil.parse_ubicacion(UBICACION) == (40.416775, -3.70379)
    assert movil.parse_ubicacion("nada") is None


@pytest.mark.parametrize("pedido, esperado", [
    ("WhatsApp", "com.whatsapp"),
    ("spotify", "com.spotify.music"),
    ("cámara", "com.sec.android.app.camera"),
    ("mapas", "com.google.android.apps.maps"),
    ("juego inventado", None),
])
def test_resolver_paquete(pedido, esperado):
    paquetes = ["com.whatsapp", "com.whatsapp.w4b", "com.spotify.music", "com.sec.android.app.camera",
                "com.google.android.apps.maps", "com.android.chrome"]
    assert movil.resolver_paquete(pedido, paquetes) == esperado


def test_comillas_para_la_shell_del_movil():
    assert movil.q("hola") == "'hola'"
    assert movil.q("l'Hospitalet; rm -rf /") == "'l'\\''Hospitalet; rm -rf /'"  # nada se ejecuta fuera de las comillas


def test_direcciones():
    assert movil.es_direccion("192.168.1.23:37000")
    assert not movil.es_direccion("192.168.1.23")


def test_preparar_mensaje():
    datos, desc = movil.preparar_mensaje("whatsapp", "Mamá", "+34600123456", "Llego a las 8")
    assert datos == {"accion": "mensaje", "app": "whatsapp", "numero": "+34600123456", "texto": "Llego a las 8"}
    assert "WhatsApp a Mamá" in desc
    with pytest.raises(ValueError):
        movil.preparar_mensaje("email", "Mamá", "+34600123456", "x")
    with pytest.raises(ValueError):
        movil.preparar_mensaje("sms", "Mamá", "+34600123456", "  ")


async def test_mensaje_nunca_se_manda_sin_confirmacion(monkeypatch):
    memoria = MemoryStore()
    telefono.guardar_contacto(memoria, "Mamá", "600123456")
    monkeypatch.setattr(movil, "ejecutar_accion", lambda _: (_ for _ in ()).throw(AssertionError("¡enviado!")))
    pedidas = []

    async def confirmar(a):
        pedidas.append(a)

    j = Jarvis(memoria)
    j._pedir_confirmacion_movil = confirmar
    r = await j.movil_mensaje(None, app="whatsapp", destino="mamá", texto="Llego a las 8")
    assert len(pedidas) == 1 and pedidas[0]["tipo"] == "movil" and pedidas[0]["estado"] == "pendiente"
    assert "NO está enviado" in r
    memoria.close()


def test_jarvis_tiene_las_herramientas_del_movil():
    m = MemoryStore()
    nombres = {t.info.name for t in Jarvis(m).tools}
    assert {"movil_info", "movil_hacer", "movil_mensaje"} <= nombres
    m.close()
