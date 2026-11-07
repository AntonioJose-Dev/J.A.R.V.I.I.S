import pytest

from jarvis.memory import MemoryStore


def test_remember_and_recall():
    store = MemoryStore()
    store.remember("Su madre se llama Carmen", "personas")
    store.remember("Le gusta el café solo", "gustos")
    found = store.recall("¿cómo se llama mi madre?")
    assert found and found[0].text == "Su madre se llama Carmen"


def test_prefix_match():
    store = MemoryStore()
    store.remember("El cumpleaños de Carmen es el 12 de marzo", "fechas")
    assert store.recall("cumple")


def test_recent_and_forget():
    store = MemoryStore()
    a = store.remember("uno")
    store.remember("dos")
    assert [m.text for m in store.recent()] == ["dos", "uno"]
    assert store.forget(a.id)
    assert [m.text for m in store.recent()] == ["dos"]
    assert store.recall("uno") == []


def test_empty_inputs():
    store = MemoryStore()
    with pytest.raises(ValueError):
        store.remember("   ")
    assert store.recall("¿?") == []
