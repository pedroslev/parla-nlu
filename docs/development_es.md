# Desarrollo

[English](development.md) · **Español**

## Requisitos y dependencias

Python 3.11 o más nuevo (`scripts/setup.sh` busca `python3.13`, `3.12`, `3.11` o `python3`, o el que le pases en
`PYTHON=`). Pocas dependencias y a propósito: el servidor HTTP es el de la biblioteca estándar (`http.server`), sin
framework, y todo se guarda en archivos JSON.

| Paquete (`requirements.txt`) | Para qué |
|---|---|
| `fastembed` (+ `onnxruntime`), `numpy` | Vectores de las frases con `google/embeddinggemma-300m` (~1,2 GB, se guarda en `data/models/embeddings` o en `PARLA_EMBED_CACHE`). |
| `python-crfsuite` | Entidades aprendidas (CRF). |
| `cel-python` | Expresiones CEL en `{{ }}`, `set`, `if` y `saves`. |
| `pypdf` | PDFs de la base de conocimiento. |
| `mcp` | El servidor MCP. |
| `faster-whisper`, `piper-tts` (`requirements-voice.txt`) | Voz, opcional. Necesita `ffmpeg` en el sistema. |

La IA habla con Ollama por HTTP con `urllib` (`llm.py`), sin SDK. Node.js solo hace falta para funciones en
JavaScript.

## Comandos

| Comando | Qué hace |
|---|---|
| `scripts/setup.sh [--voice] [--ollama]` | Crea `.venv` e instala las dependencias; `--voice` suma la voz, `--ollama` baja `qwen2.5:0.5b` si Ollama está instalado. |
| `make setup` / `make setup-voice` | Lo mismo que `scripts/setup.sh` / `scripts/setup.sh --voice`. |
| `make run` (o `.venv/bin/python app.py [puerto]`) | Abre Parla en `http://127.0.0.1:8000` (`PORT=8080 make run` para otro puerto). |
| `make test` (o `.venv/bin/python tests/run_all.py [nombre ...]`) | Las pruebas. |
| `make mcp` | El servidor MCP por HTTP en `:8001/mcp`. Para stdio: `.venv/bin/python mcp_server.py`. |
| `make docker-build` / `make docker-run` | Imagen `parla:local` (`VOICE=1` suma la voz) y correrla en `127.0.0.1:8000`. Ver [deployment.md](deployment_es.md). |
| `make clean-pyc` | Borra los `__pycache__`. |

## Variables de entorno

Todas son opcionales. Nada carga `.env` solo: exportalas en tu shell.

| Variable | Por defecto | Para qué |
|---|---|---|
| `PARLA_DATA` | `<repo>/data` | Agentes, versiones, conversaciones, archivos, claves, `users.json` y modelos de voz. |
| `PARLA_USERS` | `$PARLA_DATA/users.json` | Archivo de usuarios. |
| `PARLA_HOST` | `127.0.0.1` | Dirección en la que escucha el servidor (la imagen de Docker usa `0.0.0.0`). |
| `PARLA_HOSTS` | vacío | Nombres (`host[:puerto]`) extra por los que se entra a Parla detrás de un proxy. Ver [deployment.md](deployment_es.md). |
| `PARLA_SECURE_COOKIE` | vacío | `1` agrega `Secure` a la cookie de sesión (también se agrega sola si un proxy de `PARLA_HOSTS` avisa HTTPS con `X-Forwarded-Proto`). |
| `PARLA_EMBED_CACHE` | `<repo>/data/models/embeddings` | Dónde se guarda el modelo de vectores. No sigue a `PARLA_DATA`, para que las pruebas no lo bajen cada vez. |
| `PARLA_FUNCTIONS` | `1` | `0`, `false`, `no` u `off` apagan las funciones de los agentes. |
| `PARLA_PUBLIC_URL` | vacío | Dirección pública con HTTPS para los webhooks de WhatsApp y Telegram (gana `channels.public_url` del agente). Ver [channels_es.md](channels_es.md). |
| `PARLA_WHATSAPP_API`, `PARLA_TELEGRAM_API` | `https://graph.facebook.com/v21.0`, `https://api.telegram.org` | Dirección base de esas APIs. Solo para pruebas (`tests/test_channels.py` las apunta a un servidor falso). |
| `PARLA_WHISPER` | `base` | Modelo de faster-whisper (`tiny` si la máquina es lenta). |
| `PARLA_URL` | `http://127.0.0.1:8000` | (MCP) dónde está Parla. |
| `PARLA_TOKEN` | vacío | (MCP) clave de API que se manda como `Authorization: Bearer`. |
| `PARLA_MCP_ALLOWED_HOSTS` | vacío | (MCP con `--http`) dominios públicos aceptados detrás de un proxy. |

## Código

| Archivo | Qué tiene |
|---|---|
| `app.py` | Entrada: arranca `parla/server.py` (`main`). |
| `parla/__init__.py` | `ROOT`, `DATA` (`PARLA_DATA`) y `__version__`. |
| `parla/server.py` | NLU (`classify`, `extract`, `parse`, `read_answer`), entrenamiento (`train`, `self_check`), versiones (`publish`, `deploy`, `target`, `diff`), plantillas (`cel`, `render`), el motor (`handle`, `run`, `begin`), conversaciones en disco (`converse`), `api_v1`, `audio_event`, la Bandeja (`human`) y el `Handler` HTTP. |
| `parla/auth.py` | Usuarios, roles, cookies, claves; `handle` (rutas `/api/auth`, `/api/users`) y `guard` (antes de cada `/api/`). |
| `parla/brain.py` | IA encima del motor: `rescue_intent`, `fill_slot`, `understand`, `side_question`, `answer`, `fallback`, `agent_turn`. Ninguna función lanza. |
| `parla/llm.py` | Cliente de Ollama / compatible OpenAI: `chat`, `status`, `pull`. |
| `parla/knowledge.py` | `extract` (texto, HTML, URL, PDF), `chunks`, `search`. |
| `parla/dates.py` | `extract`: fechas en lenguaje natural por reglas. |
| `parla/files.py` | Archivos del paso `file`: `save`, `listing`, `find`, `read`, `delete`. |
| `parla/insights.py` | `unrecognized` y `analytics`, calculados al vuelo sobre las conversaciones. |
| `parla/runner.py` | `run_function`: funciones en un proceso aparte. |
| `parla/vault.py` | Claves por agente: `put`, `delete`, `names`, `values`, `mask`. |
| `parla/voice.py` | `transcribe`, `speak` y `prewarm` (caché de frases fijas). |
| `parla/connect.py` | «Conectar con IA». |
| `parla/mcp_server.py` | Servidor MCP: validador del formato (`validate`), guía del formato y herramientas. |
| `web/index.html` | La interfaz (JS sin build): editor, chat de prueba y llamada de voz. Cada sección grande en `web/static/*.js`. |
| `web/static/voice.js` | Dictado, leer en voz alta y la llamada (WebRTC local + detector de voz). |
| `web/static/files.js`, `sessions.js`, `functions.js`, … | Archivos del paso `file`; conversaciones (re-ejecutar como prueba, seguir como ese cliente); funciones (editor con colores, ejemplos y prueba); y el resto de las secciones. |
| `web/static/widget.js` | El widget, sin dependencias, en un Shadow DOM. |

En disco (`PARLA_DATA`): `agents/<id>.json` (el borrador), `<id>.model.json` y `<id>.crfsuite` (lo entrenado),
`<id>.versions/`, `<id>.sessions/<sessionId>.json`, `<id>.files/`, `<id>.secrets.json`, `users.json` y
`models/` (voz y caché de audio).

## Cómo funciona el motor

El estado de una conversación (`st`) es un diccionario: `slots`, `flow` (flujo en curso), `pc` (paso), `stack`
(subflujos e interrupciones), `waiting` (slot preguntado), `lang`, `buttons`, `clarify`, `hint` (opción recién
explicada), `csat_waiting`, `handoff`, `agent` (estado del paso de IA), `last_bot` (para «repetí») y `recent`
(contexto para la IA). Se guarda dentro de `agents/<id>.sessions/<sid>.json`.

`begin(agent, st, data)` empieza: copia `data` a los slots que se llaman igual, elige el idioma y corre el flujo
con trigger `__start__`.

`handle(agent, st, text)` es un turno, en este orden:

1. Si la atiende una persona (`handoff.active`), el bot no habla.
2. Botón tocado, respuesta a la encuesta CSAT, respuesta a «¿quisiste decir…?».
3. `parse`: intención + entidades. Las entidades llenan sus slots (mientras espera una respuesta, solo el slot
   preguntado). Dos valores distintos para el slot preguntado = respuesta ambigua.
4. Intenciones del sistema (`__cancel__`, `__repeat__`, `__handoff__`): con el umbral del agente, o con
   `max(umbral, 0.75)` si está esperando un dato (0.92 si la pregunta es de texto libre), nunca por debajo de 0.65 y
   nunca si el mensaje ya contestó o se tocó un botón.
5. Un flujo con `interrupts: "always"` corta lo que esté esperando.
6. Si hay un paso `agent` activo, le toca a la IA. Si está esperando un dato: pregunta suelta (`side_question`),
   correcciones, `fill: "ai"`, `also`, opción recién explicada, `read_answer` (por significado), `brain.understand`
   (con IA), interrupción por otra intención (se apila y después vuelve) o «No reconocí ese dato».
7. Si no estaba en un flujo: rescate con IA, aclaración por empate, flujo por intención o fallback (conocimiento →
   repregunta con IA → `fallback`).
8. `run`, y al terminar CSAT o «¿algo más?».
9. `turn` arma el resultado (`messages`, `buttons`, `replies`, `nlu`, `slots`, `trace`, `via`, `sources`, …).

`run(agent, st, nlu, text, out, trace)` ejecuta pasos hasta `done`, `wait`, `handoff` o `error`. Antes, `flatten`
convierte los `if` anidados en una lista plana con etiquetas y saltos. Límites: 200 pasos seguidos
(`MAX_STEPS`) y 5 flujos apilados (`MAX_DEPTH`). Un paso que falla no tira el servidor: el chat muestra
«⚠ Hay un problema en el flujo…» y la conversación se corta.

Los módulos enchufables (IA, fechas, claves, lectura por significado) se llaman con `hook()`: si explotan, el bot
sigue como si no estuvieran.

`converse` es el puente entre la API/chat y `handle`: carga la versión con la que empezó la conversación, usa su
modelo entrenado, guarda el historial (hasta 500 mensajes) y las clasificaciones.

`store` guarda el agente y, si hay voces de piper bajadas, lanza `voice.prewarm` en un hilo con las frases de
`spoken_texts`.

## Cómo sumar un tipo de paso

Ejemplo: un paso `wait` que dice «un momento».

1. **Motor** (`parla/server.py`): agregá el nombre a `STEP_NAMES` y una rama en `run()`:
   ```python
   elif kind == "wait":
       out.append(render(localized(step, st), ctx) or "Un momento…")
   ```
   Si el paso tiene que esperar a la persona, devolvé `"wait"`; si corta la charla, `"done"`. Si dice un texto fijo,
   sumalo en `spoken_texts` para que la llamada de voz lo tenga pregenerado.
2. **Validador del MCP** (`parla/mcp_server.py`): sumalo a `STEP_TYPES`, validá sus campos en `validate()` y
   documentalo en la guía del formato (`GUIDE`).
3. **Interfaz** (`web/index.html`): sumalo a `STEP_MENU` y armá su editor.
4. **Prueba** (`tests/test_app.py`): una conversación que lo use y un `assert` sobre lo que dice.
5. **Docs**: [concepts.md](concepts_es.md#tipos-de-paso).

## Pruebas

```sh
make test                                # todas: tests/run_all.py
.venv/bin/python tests/run_all.py app mcp   # algunas, por nombre
.venv/bin/python tests/test_app.py       # una sola, a mano
```

Son scripts con `assert`, sin framework: si algo no se cumple, el script falla en ese `assert`. `run_all.py` corre
cada una en su propio proceso, muestra el tiempo y marca «saltado» las de voz o IA cuando falta lo que necesitan
(no cuenta como falla). `tests/support.py` arma una carpeta de datos temporal y, para las que lo necesitan, levanta
una copia propia del servidor en un puerto libre: nunca tocan tu `data/`.

| Archivo | Necesita |
|---|---|
| `test_app.py` | Nada: el motor con un NLU falso y vectores de juguete, sin modelo ni red. |
| `test_insights.py` | Nada. |
| `test_connect.py` | Nada (usa un HOME temporal y un `PATH` vacío). |
| `test_knowledge.py` | El modelo de vectores. |
| `test_auth.py` | Nada externo: levanta su propio servidor con un `users.json` temporal. |
| `test_ai.py` | Ollama para la parte con modelo; si no está, la saltea con un aviso. Las fechas se prueban siempre. |
| `test_voice.py` | Los extras de voz y `ffmpeg`; si faltan, se saltea. |
| `test_mcp.py` | El paquete `mcp` y el modelo de vectores: levanta su propio Parla temporal y prueba el validador y las herramientas punta a punta. |

## Estilo

- **Funciones chicas** que hacen una cosa y se leen de arriba abajo.
- **Comentarios en español**, para explicar el porqué, no el qué. Los mensajes al usuario también, en
  rioplatense y diciendo qué hacer («Revisá que los slots que usa existan»).
- **Lo más simple que funcione**: biblioteca estándar antes que una dependencia nueva, archivos JSON antes que una
  base de datos, sin abstracciones que nadie pidió.
- **Comentarios `ponytail:`** cuando se toma un atajo con un límite conocido, nombrando el límite y cómo
  mejorarlo. Ejemplos reales del código:
  ```python
  # ponytail: un hilo por pedido (la IA y la voz tardan segundos); dos mensajes a la vez en la MISMA conversación
  # pueden pisarse: agregar un lock por sessionId si algún canal los manda en paralelo
  # ponytail: sesiones en memoria (se pierden al reiniciar el servidor: hay que volver a entrar); a disco si molesta
  ```
  Buscalos con `grep -rn "ponytail:" parla web` para ver la deuda técnica asumida.
- Un error de un módulo opcional (IA, voz, fechas) nunca corta una conversación.
- Toda lógica no trivial deja una prueba en `tests/`.
