# Desarrollo

[English](development.md) · **Español**

## Requisitos y dependencias

Python 3.11 o más nuevo (`scripts/setup.sh` busca `python3.13`, `3.12`, `3.11` o `python3`, o el que le pases en
`PYTHON=`). Pocas dependencias y a propósito: el servidor HTTP es el de la biblioteca estándar (`http.server`), sin
framework. Los agentes, las versiones y los usuarios son archivos JSON; las conversaciones, las sesiones de login y
la auditoría van en un archivo SQLite (`parla.db`, con el `sqlite3` de la biblioteca estándar).

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
| `make ui-test` (o `.venv/bin/python tests/ui/run.py`) | El barrido de la interfaz en Chrome sin ventana (ver abajo). |
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
| `PARLA_RETENTION_DAYS` | vacío | Días que se guardan las conversaciones sin movimiento, para los agentes sin `retention_days`. Vacío o `0`: para siempre. |
| `PARLA_AUDIT_DAYS` | `365` | Días que se guarda la auditoría. |
| `PARLA_SECURE_COOKIE` | vacío | `1` agrega `Secure` a la cookie de sesión (también se agrega sola si un proxy de `PARLA_HOSTS` avisa HTTPS con `X-Forwarded-Proto`). |
| `PARLA_EMBED_CACHE` | `<repo>/data/models/embeddings` | Dónde se guarda el modelo de vectores. No sigue a `PARLA_DATA`, para que las pruebas no lo bajen cada vez. |
| `PARLA_FUNCTIONS` | `1` | `0`, `false`, `no` u `off` apagan las funciones de los agentes. |
| `PARLA_PUBLIC_URL` | vacío | Dirección pública con HTTPS para los webhooks de WhatsApp y Telegram (gana `channels.public_url` del agente). Ver [channels_es.md](channels_es.md). |
| `PARLA_WHATSAPP_API`, `PARLA_TELEGRAM_API` | `https://graph.facebook.com/v21.0`, `https://api.telegram.org` | Dirección base de esas APIs. Solo para pruebas (`tests/test_channels.py` las apunta a un servidor falso). |
| `PARLA_TWILIO_API` | `https://api.twilio.com` | Dirección base de la API REST de Twilio para las llamadas salientes. Solo para pruebas (`tests/test_outbound.py`). |
| `PARLA_CAMPAIGN_MAX` | `10000` | Máximo de destinatarios por campaña, para los agentes sin `outbound.max_recipients`. |
| `PARLA_WHISPER` | `base` | Modelo de faster-whisper (`tiny` si la máquina es lenta). |
| `PARLA_LANG` | el del navegador | Idioma de la interfaz por defecto (`en`, `es` o `pt`); `scripts/setup.sh --lang` lo escribe en `.env`. |
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
| `parla/aserver.py` | El servidor HTTP/1.1 con asyncio: keep-alive, una fila por conversación, WebSocket (`/ws`) y SSE (`/stream`). Corre cada pedido por `server.Handler` en un pool de hilos. |
| `parla/bus.py` | Pub/sub en el proceso (`publish` desde cualquier hilo, `subscribe` desde el loop): temas `session:`, `inbox:`, `campaign:`. |
| `parla/db.py` | La base SQLite `parla.db` (WAL): una conexión de lectura por hilo y un hilo escritor con group commit; tablas `sessions`, `logins`, `audit`, campañas; `q`, `connect`, `audit`, `audit_list`. |
| `parla/pii.py` | Tapar datos personales en lo que se guarda (`pii_redaction`): `categories`, las reglas y los controles de Luhn y módulo 97. |
| `parla/brain.py` | IA encima del motor: `rescue_intent`, `fill_slot`, `understand`, `side_question`, `answer`, `fallback`, `agent_turn`. Ninguna función lanza. |
| `parla/llm.py` | Cliente de Ollama / compatible OpenAI / Anthropic / Gemini: `chat` (con `stream=` para tokens en vivo), `settle`, `status`, `pull`. |
| `parla/knowledge.py` | `extract` (texto, HTML, URL, PDF), `chunks`, `search`. |
| `parla/dates.py` | `extract`: fechas en lenguaje natural por reglas. |
| `parla/files.py` | Archivos del paso `file`: `save`, `listing`, `find`, `read`, `delete`. |
| `parla/insights.py` | `unrecognized` y `analytics`, calculados al vuelo sobre las conversaciones. |
| `parla/runner.py` | `run_function`: funciones en un proceso aparte. |
| `parla/telemetry.py` | Observabilidad: `count`, `observe`, `gauge` y `render` (Prometheus), `span` (OpenTelemetry, hilo que exporta por OTLP/HTTP JSON), `log_request` (logs JSON). Ver [observability.md](observability_es.md). |
| `parla/vault.py` | Claves por agente: `put`, `delete`, `names`, `values`, `mask`. |
| `parla/voice.py` | `transcribe`, `speak` y `prewarm` (caché de frases fijas). |
| `parla/connect.py` | «Conectar con IA». |
| `parla/mcp_server.py` | Servidor MCP: validador del formato (`validate`), guía del formato y herramientas. |
| `web/index.html` | La interfaz (JS sin build): editor, chat de prueba y llamada de voz. Cada sección grande en `web/static/*.js`. |
| `web/static/voice.js` | Dictado, leer en voz alta y la llamada (WebRTC local + detector de voz). |
| `web/static/files.js`, `sessions.js`, `functions.js`, … | Archivos del paso `file`; conversaciones (re-ejecutar como prueba, seguir como ese cliente); funciones (editor con colores, ejemplos y prueba); y el resto de las secciones. |
| `web/static/audit.js` | La página «Auditoría», solo para el dueño (`#/auditoria`). |
| `web/static/widget.js` | El widget, sin dependencias, en un Shadow DOM. |

En disco (`PARLA_DATA`): `agents/<id>.json` (el borrador), `<id>.model.json` y `<id>.crfsuite` (lo entrenado),
`<id>.versions/`, `<id>.files/`, `<id>.secrets.json`, `users.json`, `parla.db` (conversaciones, sesiones de login y
auditoría) y `models/` (voz y caché de audio). Al arrancar, `migrate_sessions` importa a `parla.db` cualquier
carpeta vieja `agents/<id>.sessions/` y la renombra a `<id>.sessions.migrated`; `cleanup` (al arrancar y cada
hora) aplica la retención.

## Arquitectura del servidor

```
socket ─► aserver (loop de eventos) ─► fila por conversación ─► pool de hilos: server.Handler (auth, límites, ruta)
                                                                     ├─► embeddings: cola de micro-batch ─► N llamadas a ONNX
                                                                     ├─► SQLite: lecturas en una conexión por hilo,
                                                                     │   escrituras ─► hilo escritor (group commit)
                                                                     └─► bus.publish ─► suscriptores WebSocket / SSE
```

- **Loop**: un loop de asyncio maneja todas las conexiones. Lo caliente queda en el loop (`/static/*.js` desde
  memoria, frames de WS/SSE); el resto corre el código de siempre del `Handler`, sin cambios, en `PARLA_THREADS` hilos.
- **Colas**: los turnos del mismo bot + `sessionId` esperan en un `asyncio.Lock` FIFO que se borra cuando queda vacío:
  una charla va en serie y charlas distintas en paralelo. Los embeddings de todas las charlas se juntan en lotes
  (`_jobs` en `server.py`); las escrituras a SQLite van a un escritor que commitea todo lo encolado en una transacción.
  `q()` vuelve después del COMMIT; una caída antes pierde solo escrituras no confirmadas (`tests/test_aserver.py`).
- **Bus**: `save_session` publica el registro guardado; WS/SSE mandan lo que está después del cursor del cliente.
  Durante un turno `converse` pone `llm.STREAM.sink` solo si alguien escucha: si no, el streaming no cuesta nada.
- **Medir**: `tests/perf/load.py` (no está en `run_all`; CI corre un smoke de 10 s). El techo es el modelo de
  embeddings; ver [deployment_es.md](deployment_es.md#rendimiento-y-ajustes).

## Cómo funciona el motor

El estado de una conversación (`st`) es un diccionario: `slots`, `flow` (flujo en curso), `pc` (paso), `stack`
(subflujos e interrupciones), `waiting` (slot preguntado), `lang`, `buttons`, `clarify`, `hint` (opción recién
explicada), `csat_waiting`, `handoff`, `agent` (estado del paso de IA), `last_bot` (para «repetí») y `recent`
(contexto para la IA). Se guarda dentro del registro de la conversación (columna `record` de la tabla `sessions`
de `parla.db`, con `load_session` / `save_session`).

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
| `test_storage.py` | Nada externo: `parla.db`, la migración, la retención, la auditoría y el tapado; levanta su propio servidor dos veces sobre los mismos datos temporales (los logins sobreviven al reinicio). |
| `test_ai.py` | Ollama para la parte con modelo; si no está, la saltea con un aviso. Las fechas se prueban siempre. |
| `test_voice.py` | Los extras de voz y `ffmpeg`; si faltan, se saltea. |
| `test_mcp.py` | El paquete `mcp` y el modelo de vectores: levanta su propio Parla temporal y prueba el validador y las herramientas punta a punta. |

### Barrido de la interfaz

`tests/ui/run.py` (no está en `run_all`; CI lo corre en su propio job) levanta un Parla temporal, crea un dueño, un
editor, un analista y un usuario de atención, importa los dos ejemplos, entrena y deja unas charlas (una pasada a una
persona, un par que el bot no entendió). Después `tests/ui/sweep.mjs` maneja Chrome sin ventana por CDP, un proceso
por rol en paralelo, por cada idioma (es, en, pt) × agente × sección del menú de ese rol, y falla con: excepciones de
JS, errores de consola, HTTP ≥ 400, avisos `[role=alert]` a la vista, «null»/«undefined»/«NaN»/«[object …]» en pantalla
(fuera de `<pre>`/`<code>`), palabras de la interfaz en español en en/pt y que alguien que no es dueño llegue a la
auditoría. Lo del agente (frases, globos del chat, textos del bot) queda afuera marcando su contenedor con
`data-content`: sumalo cuando una vista nueva muestre lo que escribió el bot o la persona. Necesita Node 22+ y Chrome:
`CHROME=/ruta/a/chrome` si no está en el lugar de siempre (`google-chrome` en Linux); `LANGS=en` barre un solo idioma.

## Estilo

- **Funciones chicas** que hacen una cosa y se leen de arriba abajo.
- **Comentarios en español**, para explicar el porqué, no el qué. Los mensajes al usuario también, en
  rioplatense y diciendo qué hacer («Revisá que los slots que usa existan»).
- **Lo más simple que funcione**: biblioteca estándar antes que una dependencia nueva, archivos JSON antes que una
  base de datos (las conversaciones son la excepción: van en SQLite, que igual es biblioteca estándar), sin
  abstracciones que nadie pidió.
- **Comentarios `ponytail:`** cuando se toma un atajo con un límite conocido, nombrando el límite y cómo
  mejorarlo. Ejemplos reales del código:
  ```python
  # ponytail: un hilo por pedido (la IA y la voz tardan segundos); dos mensajes a la vez en la MISMA conversación
  # pueden pisarse: agregar un lock por sessionId si algún canal los manda en paralelo
  # ponytail: una conexión y un lock para todo el proceso (ThreadingHTTPServer); alcanza para un servidor.
  # Con mucho tráfico: una conexión por hilo (WAL ya deja leer mientras otro escribe)
  ```
  Buscalos con `grep -rn "ponytail:" parla web` para ver la deuda técnica asumida.
- Un error de un módulo opcional (IA, voz, fechas) nunca corta una conversación.
- Toda lógica no trivial deja una prueba en `tests/`.
