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
  [Groq](https://console.groq.com/keys) (`GROQ_API_KEY`, `openai/gpt-oss-120b`: el que mejor usa las herramientas; también vale `qwen/qwen3.8-27b`) o, como alternativa,
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

## Llamadas de teléfono

Pídele a JARVIS (por Telegram o por voz) *"llama a mamá y dile que llego a las 8"*:

1. Busca a "mamá" en su agenda (guárdala antes: *"el teléfono de mi madre es 600 12 34 56"*).
2. Te manda a Telegram una confirmación con botones **Llamar** / **Cancelar**. Sin pulsar *Llamar* no marca nunca (caduca a los 10 minutos).
3. Llama de verdad desde tu número. Lo primero que dice es que es **el asistente de inteligencia artificial de Potro** y que llama de tu parte.
   Da el mensaje, escucha la respuesta, se despide y cuelga. Si salta el contestador, deja un mensaje corto.
4. Te manda a Telegram el resultado, un resumen y la transcripción.

Por seguridad: solo llama a números de España y la UE (`JARVIS_PREFIJOS_LLAMADA`), una llamada cada vez,
con un máximo de 3 minutos (`JARVIS_LLAMADA_MAX_SEGUNDOS`), y no promete ni acepta nada en tu nombre.

### Configurarlo (una sola vez)

**Telnyx** (la línea telefónica), en [portal.telnyx.com](https://portal.telnyx.com):
1. Crea la cuenta y actívala (*Upgrade*). Para seguir llamando cuando acabe el saldo de prueba, añade saldo (*Add credit*).
2. El número que verá quien recibe la llamada (elige una):
   - **Tu propio móvil** (gratis): *Voice Suite → Verified Numbers → Verify Number*. Verá tu número y te podrá devolver la llamada.
   - **Un número de Telnyx**: *Numbers → Search & Buy*. Los españoles (+34) piden un justificante de dirección.
3. *Voice → Outbound Voice Profiles → Add*: crea un perfil y permite llamar a España/UE.
4. *Voice → SIP Trunking → Create*: tipo **Credentials**. Apunta el usuario y la contraseña.
   En la pestaña *Outbound* asígnale el perfil del paso 3 (y, si compraste número, asígnaselo en *Numbers*).

**LiveKit Cloud** (conecta la llamada con JARVIS), en [cloud.livekit.io](https://cloud.livekit.io):
5. Crea un proyecto (plan gratuito). En *Settings → Keys* copia la URL (`wss://...livekit.cloud`), la API key y el secret.

**En `.env`**:
6. Pon `LIVEKIT_URL`, `LIVEKIT_API_KEY`, `LIVEKIT_API_SECRET` (los de LiveKit Cloud), `TELNYX_SIP_USUARIO`,
   `TELNYX_SIP_CLAVE` y `JARVIS_CALLER_ID` (el número del paso 2, p. ej. `+34600000000`).
7. Crea la conexión entre LiveKit y Telnyx y copia el ID que te da en `LIVEKIT_SIP_TRUNK_ID`:
   ```bash
   python scripts/configurar_llamadas.py
   ```
8. Arranca JARVIS entero (Telegram + llamadas):
   ```bash
   python -m jarvis
   ```
9. Primera prueba, a tu propio móvil:
   ```bash
   python scripts/probar_llamada.py +34600000000
   ```

## La voz

- **En directo** (`jarvis.agent`): `ELEVEN_MODEL_VIVO` (por defecto `eleven_flash_v2_5`, el más rápido).
- **Notas de voz de Telegram**: `ELEVEN_MODEL_NOTAS` (por defecto `eleven_v4`, el más realista).
- La voz se elige con `ELEVEN_VOICE_ID`; `ELEVEN_STABILITY`, `ELEVEN_SIMILARITY` y `ELEVEN_STYLE` ajustan la naturalidad.
- Antes de hablar se limpia el texto (sin markdown, emojis ni enlaces; horas dichas como "13 y 45").
- Con el plan gratuito de ElevenLabs solo se pueden usar por API las voces incluidas en la cuenta.
  Las voces de la biblioteca (castellano nativo) y crear voces nuevas por API requieren plan de pago.

## Estructura

| Archivo | Para qué |
| --- | --- |
| `jarvis/core.py` | Lo común: personalidad, herramientas, cerebro y voz |
| `jarvis/agent.py` | Agente de voz en tiempo real (LiveKit) |
| `jarvis/telegram_bot.py` | Canal de Telegram (texto y notas de voz) |
| `jarvis/telefono.py` | Agenda, números permitidos y confirmación de llamadas |
| `jarvis/llamadas.py` | Agente que hace las llamadas de teléfono (LiveKit + Telnyx) |
| `jarvis/__main__.py` | `python -m jarvis`: arranca Telegram y llamadas a la vez |
| `jarvis/config.py` | Elige cerebro y voz según las claves (modo prueba / completo) |
| `jarvis/prompts.py` | Personalidad e instrucciones |
| `jarvis/memory.py` | Memoria a largo plazo (SQLite ahora, PostgreSQL + pgvector después) |
| `tests/` | Pruebas (`pytest`) |

## Próximo

1. Prueba de voces en español y elección de la voz de JARVIS.
2. Palabra de activación "Oye Jarvis" (openWakeWord).
3. Llamadas telefónicas con Telnyx.
4. Calendario, email, control del PC y Home Assistant por MCP.
