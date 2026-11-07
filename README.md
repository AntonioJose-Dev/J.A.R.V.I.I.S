# J.A.R.V.I.S.

Asistente personal por voz, en español, con memoria y herramientas.

## Qué hace ya (v0.1)

- Conversa por voz en tiempo real: Deepgram (oído) → Claude (cerebro) → ElevenLabs (voz).
- Detecta cuándo has terminado de hablar y te deja interrumpirle.
- Recuerda lo que le cuentas entre sesiones (`recordar`, `buscar_recuerdos`).
- Sabe la fecha y hora de España.
- Se conecta a cualquier servidor MCP (Home Assistant, calendario...) con `JARVIS_MCP_URLS`.

## Arrancarlo en tu ordenador

Necesitas Python 3.11 o superior.

```bash
python -m venv .venv
source .venv/bin/activate          # en Windows: .venv\Scripts\activate
pip install -e ".[dev]"
cp .env.example .env               # y rellena tus claves
python -m jarvis.agent download-files   # descarga los modelos locales (VAD, turnos)
python -m jarvis.agent console     # habla con JARVIS desde el terminal
```

## Estructura

| Archivo | Para qué |
| --- | --- |
| `jarvis/agent.py` | Sesión de voz, herramientas y arranque |
| `jarvis/prompts.py` | Personalidad e instrucciones |
| `jarvis/memory.py` | Memoria a largo plazo (SQLite ahora, PostgreSQL + pgvector después) |
| `tests/` | Pruebas (`pytest`) |

## Próximo

1. Prueba de voces en español y elección de la voz de JARVIS.
2. Palabra de activación "Oye Jarvis" (openWakeWord).
3. Llamadas telefónicas con Telnyx.
4. Calendario, email, control del PC y Home Assistant por MCP.
