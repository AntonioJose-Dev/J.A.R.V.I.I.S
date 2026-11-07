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

## Modo prueba (gratis: Deepgram + Groq)

Si aún no tienes las claves de Anthropic o ElevenLabs, JARVIS arranca igual:

- **Cerebro:** sin `ANTHROPIC_API_KEY` usa un modelo gratuito en la nube:
  [Groq](https://console.groq.com/keys) (`GROQ_API_KEY`, Qwen 3.8 27B; también vale `openai/gpt-oss-120b`) o, como alternativa,
  [Gemini](https://aistudio.google.com/apikey) (`GEMINI_API_KEY`).
- **Voz:** sin `ELEVEN_API_KEY` habla con la voz española de Deepgram (`aura-2-alvaro-es`).

Pon `DEEPGRAM_API_KEY` y `GROQ_API_KEY` en `.env` y ejecuta:

```bash
python -m jarvis.agent console
```

Cada pieza cambia sola a la versión buena en cuanto pones su clave en `.env`.
`JARVIS_MODO=prueba` fuerza el modo prueba y `JARVIS_MODO=completo` exige Claude + ElevenLabs.
Otras voces de Deepgram en español: `aura-2-nestor-es`, `aura-2-javier-es`, `aura-2-sirio-es`, `aura-2-celeste-es`...

Las capas gratuitas tienen límites de uso por minuto y por día: de sobra para probar, pero no para uso diario.

Para probar solo el oído (Deepgram): `python scripts/prueba_oido.py`.

## Hablar con JARVIS por Telegram

El mismo JARVIS (mismo cerebro, herramientas y memoria) también responde por Telegram:
a un mensaje de texto contesta con texto, y a una nota de voz contesta solo con otra nota de voz.

1. En Telegram, abre **@BotFather**, envía `/newbot` y sigue los pasos. Copia el token en `.env` como `TELEGRAM_BOT_TOKEN`.
2. Arranca el bot:
   ```bash
   python -m jarvis.telegram_bot
   ```
3. Escríbele `/id` a tu bot. Te dirá tu número de Telegram. Ponlo en `.env` como `TELEGRAM_ALLOWED_IDS` y reinicia el bot.

Solo responde a los IDs de `TELEGRAM_ALLOWED_IDS`: a cualquier otro lo ignora (y lo apunta en el log).
`/olvida` reinicia la conversación (lo guardado con `recordar` se mantiene).
`/voz` activa o desactiva que conteste siempre también con nota de voz (por defecto, solo cuando le mandas un audio). Se recuerda aunque reinicies el bot.
El bot funciona mientras esté encendido el ordenador donde lo arrancas.

## Estructura

| Archivo | Para qué |
| --- | --- |
| `jarvis/core.py` | Lo común: personalidad, herramientas, cerebro y voz |
| `jarvis/agent.py` | Agente de voz en tiempo real (LiveKit) |
| `jarvis/telegram_bot.py` | Canal de Telegram (texto y notas de voz) |
| `jarvis/config.py` | Elige cerebro y voz según las claves (modo prueba / completo) |
| `jarvis/prompts.py` | Personalidad e instrucciones |
| `jarvis/memory.py` | Memoria a largo plazo (SQLite ahora, PostgreSQL + pgvector después) |
| `tests/` | Pruebas (`pytest`) |

## Próximo

1. Prueba de voces en español y elección de la voz de JARVIS.
2. Palabra de activación "Oye Jarvis" (openWakeWord).
3. Llamadas telefónicas con Telnyx.
4. Calendario, email, control del PC y Home Assistant por MCP.
