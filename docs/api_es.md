# API HTTP

[English](api.md) · **Español**

Parla expone dos APIs en el mismo puerto:

- **La API pública `/api/v1`**: la que usan tu web, tu sistema, un IVR o un CRM para hablar con un bot. Es estable.
  La misma referencia, con ejemplos para cada bot, está en la interfaz en **Publicar → API**.
- **La API interna** (`/api/agents`, `/api/auth`, `/api/users`, `/api/ai`, `/api/voice`, `/api/connect`): la que usan
  la interfaz web y el servidor MCP. Está documentada [más abajo](#api-interna), pero puede cambiar entre versiones.

Generalidades:

- Base: `http://127.0.0.1:8000` (o el puerto que le pasaste a `app.py`).
- Cuerpo y respuestas en JSON. El cuerpo tiene que ser un objeto JSON (si no, 400). Tamaño máximo (si no, 413):
  25 MB para subir archivos, documentos de conocimiento, audios y proyectos de Rasa; 2 MB para un audio del widget público; 1 MB para
  lo demás.
- Errores: `{"error": "mensaje en castellano"}` con 400, 401, 403, 404, 405, 413, 415 o 429. Una excepción adentro
  de una ruta (por ejemplo, pedir una versión que no existe) vuelve como 400 con el mensaje.
- `{bot}` puede ser el id (`654a0008`), el nombre exacto (sin importar mayúsculas) o el slug (`pizzeria`). Si el
  nombre es ambiguo, usá el id.
- `sessionId`: hasta 100 caracteres, letras sin tildes, números y `. @ + - _`, sin espacios y sin empezar con
  punto. Si no lo mandás en `start` o `message`, Parla genera uno y lo devuelve.

## Autenticación y roles

Mientras no exista ningún usuario, todo está abierto (no se pide login ni clave).

Con usuarios, cada pedido a `/api/` (salvo `/api/auth/*`) necesita una de estas dos:

- **Clave de API** (para tu sistema, el MCP o `curl`): `Authorization: Bearer parla_xxxxxxxx`. Se crea en
  **Usuarios → tu usuario → Claves de API**.
- **Cookie de sesión** `parla_session` (la usa la interfaz): dura 12 horas y vive en la memoria del servidor (se
  pierde al reiniciarlo).

Sin ninguna de las dos: 401. Lo que se puede hacer depende del rol del usuario:

| Rol | Puede |
|---|---|
| `owner` (dueño) | Todo, incluido manejar usuarios (`/api/users*`). Ve todos los bots. |
| `editor` | Todo menos manejar usuarios. |
| `analyst` (analista) | Solo pedidos `GET` (mirar). Cualquier otro método: 403. |
| `agent` (atención) | Solo la Bandeja: `GET /api/agents`, `GET /api/agents/{id}`, `GET /api/agents/{id}/inbox`, `POST /api/agents/{id}/sessions/{sid}/take\|reply\|release` y `GET /api/v1/bots/{bot}/sessions/{sid}[/messages]`. |

Los usuarios que no son dueños pueden tener una lista de bots visibles (`bots`). Un pedido a un bot que no ve
responde 404, como si no existiera. `GET /api/v1/bots` y `GET /api/agents` listan solo los que ve.

**Excepción: el widget.** Si el bot tiene el widget prendido, `POST /api/v1/bots/{bot}/events` y
`POST /api/v1/bots/{bot}/audio` son públicos (es el chat de tu web), y también
`GET /api/v1/bots/{bot}/sessions/{sid}/messages` para conversaciones del canal `web`. Un pedido público (sin
sesión o de alguien que no ve ese bot) queda limitado: siempre canal `web` y entorno `production`, sin `data` de
inicio, sin `trace` en la respuesta, y no puede seguir una conversación de otro canal (403). Ver
[security.md](security_es.md).

## API pública `/api/v1`

### `GET /api/v1/bots`

```sh
curl -s http://127.0.0.1:8000/api/v1/bots
```
```json
{"bots": [{"id": "654a0008", "name": "Pizzería", "slug": "pizzeria", "online": true,
           "trained_at": "2026-11-24 22:10", "intents": ["Saludar", "Pedir pizza"],
           "environments": {"production": 3, "staging": 4}}]}
```

### `GET /api/v1/bots/{bot}`

El mismo objeto, para un bot.

### `POST /api/v1/bots/{bot}/events`

Una conversación es una serie de eventos con el mismo `sessionId`.

Campos comunes:

| Campo | Qué es |
|---|---|
| `type` | `start` (o `online`), `message` o `end`. Si falta y hay `text`, es `message`. |
| `sessionId` | La conversación. |
| `channel` | Texto libre para filtrar después (`web`, `ivr`, `whatsapp`…), hasta 30 caracteres. Por defecto `api`. |
| `environment` | `production` (por defecto), `staging` o `draft`. Pedir `staging` sin nada publicado ahí da 400. |

#### `start`: empezar (con datos precargados)

```sh
curl -s http://127.0.0.1:8000/api/v1/bots/pizzeria/events \
  -H 'Content-Type: application/json' \
  -d '{"type": "start", "sessionId": "cliente-42", "channel": "ivr",
       "data": {"nombre": "Ana", "dni": "30123456", "idioma": "es"}}'
```

- `data` (objeto): los campos que se llaman como un slot se guardan en ese slot; el resto vuelve en
  `ignored_data`. `idioma`, `language` o `lang` eligen el idioma de la charla si el bot lo tiene en `languages`.
- Corre el flujo con trigger `__start__`, si hay.
- Si ese `sessionId` ya existía, empieza de cero (memoria en blanco, con la versión que tiene el entorno ahora)
  pero conserva el historial.

#### `message`: un mensaje de la persona

```sh
curl -s http://127.0.0.1:8000/api/v1/bots/pizzeria/events \
  -H 'Content-Type: application/json' \
  -d '{"type": "message", "sessionId": "cliente-42", "text": "quiero dos de muzza"}'
```

`text` es obligatorio (se recorta a 4000 caracteres). Para tocar un botón, mandá su `value` (o su `label`). Si la
conversación no existía, se crea en ese momento (sin correr el flujo de inicio).

Respuesta de `start` y `message`:

```json
{
  "bot": {"id": "654a0008", "name": "Pizzería"},
  "sessionId": "cliente-42", "channel": "ivr",
  "started": "2026-11-25T10:00:00", "updated": "2026-11-25T10:00:05", "ended": false,
  "messages": ["Listo: 2 de muzzarella. ¡Ya sale!"],
  "buttons": [],
  "replies": [{"text": "Listo: 2 de muzzarella. ¡Ya sale!", "buttons": []}],
  "understood": {"intent": "Pedir pizza", "confidence": 0.91,
                 "entities": [{"entity": "cantidad", "value": "dos"}, {"entity": "gusto", "value": "muzzarella"}],
                 "answer_to": null},
  "slots": {"gusto": "muzzarella", "cantidad": "dos"},
  "waiting_for": null, "flow": null,
  "classifications": [], "environment": "production", "version": 3,
  "handoff": false, "language": "es", "via": null, "sources": [], "next": 6
}
```

| Campo | Qué es |
|---|---|
| `messages` | Lo que dice el bot, en orden (solo el texto). |
| `buttons` | Botones del último mensaje: `[{"label", "value"}]`. |
| `replies` | Lo mismo que `messages` con detalle: `[{"text", "buttons", "file"?}]`. `file` aparece cuando un paso manda un archivo: `{"id", "name", "mime", "size", "url"}` (ver [concepts.md](concepts_es.md#file-enviar-un-archivo)). |
| `understood` | (solo `message`) intención, confianza, entidades y `answer_to`: el slot al que respondió, si el mensaje se tomó como respuesta a una pregunta. En `start` es `null`. |
| `slots` | La memoria de la conversación. |
| `waiting_for` | El slot que está preguntando, o `null`. |
| `flow` | El flujo en curso, o `null`. |
| `classifications` | Las clasificaciones de la conversación. |
| `environment`, `version` | Contra qué responde (`version: null` = borrador). |
| `handoff` | `true` si la atiende una persona: el bot no va a contestar; leé las respuestas con `/messages`. |
| `language` | Idioma de la charla. |
| `via` | Quién resolvió el turno: `null` (el motor), `ia`, `knowledge` (base de conocimiento) o `significado` (una respuesta entendida por significado, ver [ai-and-voice.md](ai-and-voice_es.md#entender-respuestas-por-significado)). |
| `sources` | Si respondió la base de conocimiento: `[{"title", "doc", "score"}]`. |
| `next` | Índice para pedir mensajes nuevos con `/messages?after=`. |
| `ignored_data`, `trace` | (solo `start`) datos que no eran slots y traza del flujo de inicio. |

#### `end`: terminar

```sh
curl -s http://127.0.0.1:8000/api/v1/bots/pizzeria/events \
  -H 'Content-Type: application/json' -d '{"type": "end", "sessionId": "cliente-42"}'
```
```json
{"sessionId": "cliente-42", "ended": true}
```

404 si no existe. Un `message` a una conversación terminada empieza con la memoria en blanco.

### `POST /api/v1/bots/{bot}/audio`

Necesita los extras de voz. Transcribe localmente, lo atiende como un `message` y, con `speak`, devuelve la
respuesta en audio.

```sh
curl -s http://127.0.0.1:8000/api/v1/bots/pizzeria/audio \
  -H 'Content-Type: application/json' \
  -d "{\"sessionId\": \"cliente-42\", \"mime\": \"audio/webm\", \"speak\": true, \"audio\": \"$(base64 < nota.webm)\"}"
```

- `audio`: base64 (acepta también `data:audio/webm;base64,...`). Entre 0,3 y 60 segundos.
- `mime`: por defecto `audio/webm`.
- `speak`: `true` para recibir la respuesta en audio.
- `sessionId`, `channel`, `environment` como en `message`.

Respuesta: la misma de `message` más `heard` (lo transcripto) y, con `speak: true`, `audio` (WAV en base64). Sin
voz instalada, con un audio que no se puede leer o sin palabras: 400 con el motivo.

### `GET /api/v1/bots/{bot}/sessions`

Filtros: `channel`, `classification` (`__none__` = sin clasificar), `from` y `to` (`YYYY-MM-DD`, por el día en
que empezó). La de actividad más reciente primero.

```sh
curl -s 'http://127.0.0.1:8000/api/v1/bots/pizzeria/sessions?channel=ivr&from=2026-11-01'
```
```json
{"sessions": [{"sessionId": "cliente-42", "channel": "ivr", "started": "...", "updated": "...", "ended": false,
               "messages": 6, "first_message": "quiero dos de muzza", "last_message": "Listo: ...",
               "data": {"nombre": "Ana", "dni": "30123456"}, "classifications": ["Venta"],
               "environment": "production", "version": 3}]}
```

### `GET /api/v1/bots/{bot}/sessions/{sessionId}`

El estado (`bot`, `sessionId`, `channel`, fechas, `ended`, `slots`, `waiting_for`, `flow`, `classifications`,
`environment`, `version`, `language`, `next`) más `history`. Acá `handoff` es el objeto completo
(`{"active", "since", "reason", "by", "until"?}`) o `null`.

Cada entrada de `history` tiene `from` (`user`, `bot`, `event` o `human`), `text` y `at`. Las de `user` traen
`intent`, `confidence`, `entities`, `answer_to`, `fallback`, `via` y `flow`/`waiting` (dónde estaba la charla); las
de `bot`, `buttons` y `file` si tenían; las de `human`, `by`; las de `event` pueden traer `data` (los datos de
inicio) o `classification`. Se guardan los últimos 500 mensajes.

### `GET /api/v1/bots/{bot}/sessions/{sessionId}/messages?after=N`

Lo nuevo desde el índice `N` (el `next` de la respuesta anterior). Sirve para recibir lo que escribe una persona
desde la Bandeja.

```json
{"sessionId": "cliente-42", "messages": [{"from": "human", "text": "Hola Ana, soy Marta", "at": "...", "by": "marta"}],
 "next": 9, "handoff": true, "ended": false}
```

### `DELETE /api/v1/bots/{bot}/sessions/{sessionId}`

```json
{"sessionId": "cliente-42", "deleted": true}
```

### `GET /api/v1/bots/{bot}/report`

Cuántas conversaciones tuvieron cada clasificación. Filtros `from`, `to`, `channel`.

```json
{"bot": {"id": "654a0008", "name": "Pizzería"}, "from": "2026-11-01", "to": null, "channel": null,
 "sessions": 120, "unclassified": 14,
 "classifications": [{"name": "Venta", "count": 80, "configured": true}],
 "by_day": [{"date": "2026-11-01", "sessions": 9, "unclassified": 1, "counts": {"Venta": 6}}]}
```

`configured: false` = una clasificación que ya no existe en el bot.

### Webhooks de WhatsApp y Telegram

Los llaman Meta y Telegram, no vos: no usan login ni claves de API y aceptan cualquier `Host`. Responden 403 sin
detalles si el canal está apagado en el bot (`channels.whatsapp.enabled` / `channels.telegram.enabled`), falta una
clave o la firma no coincide. Cuerpo hasta 1 MB. Configuración en [channels_es.md](channels_es.md).

| Ruta | Se autentica con | Respuesta |
|---|---|---|
| `GET /api/v1/bots/{bot}/whatsapp?hub.mode=subscribe&hub.verify_token=…&hub.challenge=…` | `hub.verify_token` = `WHATSAPP_VERIFY_TOKEN` | `200` con el desafío en `text/plain`. |
| `POST /api/v1/bots/{bot}/whatsapp` | `X-Hub-Signature-256: sha256=<HMAC-SHA256 del cuerpo con WHATSAPP_APP_SECRET>` | `200 ok` enseguida; los mensajes se atienden en segundo plano. Los estados (entregado, leído) se ignoran y un id repetido se atiende una vez. |
| `POST /api/v1/bots/{bot}/telegram` | `X-Telegram-Bot-Api-Secret-Token` = `TELEGRAM_WEBHOOK_SECRET` | `200 {}` enseguida; `message` y `callback_query` se atienden en segundo plano. |

Cada mensaje se atiende como un `POST …/events` con `environment: production`, `channel: whatsapp` o `telegram` y
`sessionId` `wa-<teléfono>` o `tg-<chat_id>`; las `replies` vuelven por el canal.

### Llamadas desde un navegador (CORS) y nombres permitidos

Parla rechaza con 403 los pedidos a `/api/` que traen un encabezado `Origin` cuyo host no es
`127.0.0.1:<puerto>`, `localhost:<puerto>` ni uno de `PARLA_HOSTS`, para que cualquier página no pueda usar tu
Parla. Las únicas excepciones son `events`, `audio` y `sessions/{id}/messages` de un bot con el widget prendido,
desde los sitios cargados en **Widget web** (`widget.origins`, o `*` para cualquiera). Para esas rutas también
responde el preflight `OPTIONS` (204, métodos `POST, GET, OPTIONS`). Desde tu backend (sin `Origin`) no hay
restricción de origen.

Además, contra el DNS rebinding, un pedido a `/api/` cuyo `Host` no es `127.0.0.1`, `localhost`, `[::1]` (cualquier
puerto) ni uno de `PARLA_HOSTS` se rechaza con 403, salvo que traiga una clave de API válida o sea el chat público
del widget. Detrás de un proxy, sumá tu dominio a `PARLA_HOSTS` (ver [deployment.md](deployment_es.md)).

## Archivos: `GET /files/{agente}/{fileId}`

Los archivos que manda un paso `file`. Fuera de `/api/` y sin login: el `fileId` es aleatorio (22 caracteres) y hace
de llave. Se sirven con el tipo según la extensión y `X-Content-Type-Options: nosniff`; PDF, imágenes y TXT se
abren en el navegador, el resto se descarga.

## API interna

La usan la interfaz y el servidor MCP. No es estable. Todas las rutas siguen las reglas de
[autenticación y roles](#autenticación-y-roles). `{id}` es siempre el id de 8 caracteres del agente (acá no vale el
nombre ni el slug).

### Sesión y usuarios (`parla/auth.py`)

| Ruta | Quién | Cuerpo | Respuesta |
|---|---|---|---|
| `GET /api/auth/me` | Cualquiera | — | `{"enabled": hay usuarios, "user": {"name", "role", "bots"} \| null}` |
| `POST /api/auth/login` | Cualquiera | `{"name", "password"}` | Lo mismo que `me`, más la cookie. 401 si no coincide; 429 tras 5 intentos fallidos en un minuto (por usuario e IP). |
| `POST /api/auth/logout` | Cualquiera | — | `{"enabled", "user": null}` y borra la cookie. |
| `GET /api/users` | Dueño (sin usuarios, cualquiera: devuelve la lista vacía) | — | `{"users": [{"name", "role", "bots", "keys": [{"id", "label", "created"}]}]}` |
| `POST /api/users` | Dueño. Sin usuarios, cualquiera: el primero queda como dueño y con la sesión iniciada. | `{"name", "password"` (5 o más caracteres), `"role", "bots"?}` | El usuario. |
| `PUT /api/users/{nombre}` | Dueño | `{"role"?, "bots"?, "password"?}` | El usuario. Cambiar la contraseña cierra sus sesiones. Tiene que quedar al menos un dueño. |
| `DELETE /api/users/{nombre}` | Dueño | — | `{"deleted": nombre}`. No se puede borrar al único dueño. |
| `POST /api/users/{nombre}/keys` | Dueño | `{"label"}` | `{"id", "label", "created", "key"}`. La clave se muestra solo esta vez. |
| `DELETE /api/users/{nombre}/keys/{keyId}` | Dueño | — | El usuario. |

`bots`: `null` (ve todos) o una lista de ids de agentes. El dueño siempre ve todos.

### Agentes

| Ruta | Cuerpo | Respuesta |
|---|---|---|
| `GET /api/agents` | — | `[{"id", "name", "intents" (cantidad), "flows" (cantidad)}]` |
| `POST /api/agents` | `{"name", "demo"?: true}` (en blanco o el ejemplo de pedidos) o `{"import": agente}` (acepta el sobre `{"parla": 1, "agent": ...}`) | El agente creado. Quien ve solo algunos bots pasa a ver también este. |
| `POST /api/agents/import/rasa` | `{"zip": el .zip del proyecto en base64, "name"?}` o `{"files": {"domain.yml": "...", "data/nlu.yml": "..."}, "name"?}` | `{"agent", "warnings"}`: un agente nuevo convertido de un proyecto de Rasa 3.x y ya entrenado; `warnings` dice todo lo que no se pudo pasar tal cual. Mismo rol que crear un agente (dueño o editor). Solo lee `.yml`/`.yaml`; límites del zip: 500 archivos, 20 MB descomprimido, sin rutas absolutas ni `..`. Ver [migrate-from-rasa_es.md](migrate-from-rasa_es.md). |
| `GET /api/agents/{id}` | — | El JSON completo del agente (borrador), con `system` completo. |
| `PUT /api/agents/{id}` | El agente entero | El agente guardado. Reemplaza todo (lo que falta vuelve a los valores en blanco); `environments` y `deployments` no se pueden pisar. |
| `DELETE /api/agents/{id}` | — | `{}`. Borra el agente, su modelo, versiones, conversaciones y archivos. |
| `POST /api/agents/{id}/train` | `{"fingerprint"?}` | `{"at", "fingerprint", "phrases", "marked", "log"}`; `log` trae los pasos, la autoevaluación (`self_check`), el CRF y los consejos (`warnings`). |
| `POST /api/agents/{id}/chat` | `{"session", "text", "environment"?}` (`draft` por defecto) | Un turno del chat de prueba (canal `prueba`): `messages`, `buttons`, `replies`, `nlu` (`intent`, `confidence`, `ranking`, `entities`), `slots`, `trace`, `answer_to`, `rejected`, `fallback`, `handoff`, `language`, `via`, `sources`. |
| `POST /api/agents/{id}/reset` | `{"session"}` | `{}`. Termina esa conversación. |
| `POST /api/agents/{id}/http` | `{"step": paso http, "vars": {slot: valor}}` | `{"status", "body"}`: «Probar consulta» del editor (con las claves del agente). |
| `POST /api/agents/{id}/functions/test` | `{"function": definición, "inputs": {}}`, con `Content-Type: application/json` (si no, 415) | `{"ok", "result" \| "error", "traceback"?, "logs", "ms"}` |

### Versiones

| Ruta | Cuerpo | Respuesta |
|---|---|---|
| `GET /api/agents/{id}/versions` | — | `{"versions": [{"version", "created", "note", "stats", "environments"}], "environments": {"production", "staging"}, "deployments": [{"environment", "version", "previous", "at"}]}`, lo más nuevo primero (hasta 50 despliegues). |
| `POST /api/agents/{id}/versions` | `{"note", "environment"?}` | Publica el borrador como versión nueva (con su propio modelo) y, si se pide, la pone en ese entorno. Devuelve el resumen de la versión. |
| `GET /api/agents/{id}/versions/{n}` | — | El resumen más `agent` (la definición congelada). |
| `POST /api/agents/{id}/versions/{n}/restore` | — | Vuelve el borrador a esa versión (no toca entornos ni reentrena). Devuelve el agente. |
| `POST /api/agents/{id}/deploy` | `{"environment": "production" \| "staging", "version": n \| null}` | `{"environment", "version", "previous"}`. `null` deja el entorno vacío. |
| `GET /api/agents/{id}/diff?from=&to=` | — | Qué cambia entre `production`, `staging`, `draft` o un número de versión (por defecto de `production` a `draft`): `{"changes", "settings", "intents", "entities", "slots", "flows", "classifications", "functions", "from", "to"}`. |

### Conocimiento, voz, archivos y claves

| Ruta | Cuerpo | Respuesta |
|---|---|---|
| `POST /api/agents/{id}/knowledge/extract` | `{"kind": "text" \| "html" \| "pdf", "data"}` (`data` en base64 para `pdf`) o `{"kind": "url", "url"}` | `{"title", "text"}`. No guarda nada: la interfaz suma el documento con `PUT`. |
| `POST /api/agents/{id}/knowledge/search` | `{"query", "k"?: 3}` | `{"results": [{"text", "title", "doc", "score"}]}` |
| `POST /api/agents/{id}/voice/transcribe` | `{"audio": base64, "mime", "language"}` | `{"text", "language", "ms"}` |
| `GET /api/agents/{id}/files` | — | `{"files": [{"id", "name", "mime", "size", "url"}]}` |
| `POST /api/agents/{id}/files` | `{"name", "data": base64}` | El archivo subido más `files`. Hasta 10 MB; extensiones: pdf, png, jpg, jpeg, gif, webp, txt, csv, doc, docx, xls, xlsx, ppt, pptx, zip. |
| `DELETE /api/agents/{id}/files/{fileId}` | — | `{"files"}` |
| `GET /api/agents/{id}/secrets` | — | `{"secrets": [nombres]}`. Los valores nunca vuelven. |
| `PUT /api/agents/{id}/secrets` | `{"name", "value"}`, con `Content-Type: application/json` | `{"secrets"}`. El nombre se normaliza (`api key` → `API_KEY`). |
| `DELETE /api/agents/{id}/secrets` | `{"name"}` | `{"secrets"}` |

### Operación

| Ruta | Cuerpo | Respuesta |
|---|---|---|
| `GET /api/agents/{id}/inbox` | — | `{"sessions": [resumen + "handoff"]}`: las conversaciones que atiende (o espera) una persona. |
| `POST /api/agents/{id}/sessions/{sid}/take` | — | Una persona toma la conversación. Devuelve el estado más `history`. |
| `POST /api/agents/{id}/sessions/{sid}/reply` | `{"text"}` | Le escribe a la persona (si no estaba tomada, la toma). En una conversación `whatsapp` o `telegram` también se manda por ese canal. |
| `POST /api/agents/{id}/sessions/{sid}/release` | — | La devuelve al bot (corta el flujo que estaba a medias). |
| `GET /api/agents/{id}/channels` | — | «Canales»: `{"public_url", "env_public_url", "whatsapp"/"telegram": {"enabled", "webhook", "secrets": {nombre: ¿cargada?}, "status": {"last_in", "last_out", "error", "error_at"}}}`. El estado vive en memoria. |
| `POST /api/agents/{id}/channels/telegram` | `{"connect": true \| false}` | Llama a `setWebhook` de Telegram (crea `TELEGRAM_WEBHOOK_SECRET` si falta) o a `deleteWebhook`: `{"connected"}`. Dueño o editor. |
| `GET /api/agents/{id}/insights/unrecognized` | Filtros `from`, `to`, `channel`, `classification` | `{"groups": [{"label", "count", "texts", "examples", "suggested_intent"}]}`: «Para enseñar». |
| `GET /api/agents/{id}/insights/analytics` | Los mismos filtros | `{"sessions", "contained", "handoff", "contained_rate", "handoff_rate", "user_messages", "fallbacks", "fallback_rate", "csat", "abandoned", "drop_off", "flows", "by_day"}` |

### IA, voz y «Conectar con IA»

| Ruta | Cuerpo | Respuesta |
|---|---|---|
| `POST /api/ai/status` | `{"ai": config}` y/o `{"agent": id}` (con `agent`, la API key que nombra `ai.api_key_secret` sale de las Claves de ese agente); con `ai.prompt`, además prueba el modelo. Dueño o editor. | `{"ok", "models", "recommended", "provider", "model", "model_ready", "local", "models_unknown"?, "error", "hint", "reply"?, "ms"?}`. Nunca devuelve la key. |

La config `ai` (`agent.ai`): `enabled`, `provider` (`"ollama"` por defecto, u `"openai"` para cualquier servidor
compatible con OpenAI), `url`, `model`, `api_key_secret` (el **nombre** de una clave de Claves; la key nunca va en
el JSON del agente), `azure` / `api_version` (Azure OpenAI), `temperature`, `rescue_intents`, `use_knowledge`,
`generative_fallback`, `persona`. Ver [ai-and-voice_es.md](ai-and-voice_es.md#endpoints-compatibles-con-openai).
| `POST /api/ai/pull` | `{"ai": config, "model"}` | `{"ok", "started", "model"}`. Descarga un modelo de Ollama en segundo plano. |
| `GET /api/ai/progress` | — | `{modelo: {"status", "completed", "total", "done", "error"}}` |
| `GET /api/voice/status` | — | `{"stt", "tts", "hint", "errors", "models"}` |
| `POST /api/voice/speak` | `{"text"` (hasta 2000 caracteres), `"language"}` | El audio (`audio/wav`), no JSON. Las frases ya generadas salen de la caché. |
| `GET /api/connect` | — | `[{"id", "name", "installed", "connected", "manual"}]`, uno por asistente. |
| `POST /api/connect` | `{"client": "claude-code" \| "codex" \| "claude-desktop" \| "cursor"}` | `{"ok", "message", ...}`. Con usuarios, crea una clave de API para quien lo pide. |
| `POST /api/connect/remove` | `{"client"}` | `{"ok", "message"}` |

`/api/connect*` solo responde si el `Host` del pedido es `127.0.0.1:<puerto>` o `localhost:<puerto>` (si no, 403)
y los `POST` piden `Content-Type: application/json` (si no, 415).

### Lo demás

- `GET /`: la interfaz (`web/index.html`).
- `GET /static/{nombre}.js`: los scripts de la interfaz y `widget.js`.
