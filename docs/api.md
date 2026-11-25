# API HTTP pública (`/api/v1`)

La API que usan tu web, tu sistema, un IVR o un CRM para hablar con un bot. La misma referencia, con ejemplos
para cada bot, está en la interfaz en **Publicar → API**.

- Base: `http://127.0.0.1:8000/api/v1`
- Cuerpo y respuestas en JSON (`Content-Type: application/json`).
- Errores: `{"error": "mensaje en castellano"}` con 400, 401, 403, 404 o 405.
- `{bot}` puede ser el id (`654a0008`), el nombre exacto (sin importar mayúsculas) o el slug (`pizzeria`). Si
  el nombre es ambiguo, usá el id.
- `sessionId`: hasta 100 caracteres, letras sin tildes, números y `. @ + - _`, sin espacios. Si no lo mandás en
  `start` o `message`, Parla genera uno y lo devuelve.

## Autenticación

Sin usuarios creados, la API está abierta. Con usuarios, mandá una clave de API (se crea en **Usuarios → tu
usuario → Claves de API**):

```sh
-H "Authorization: Bearer parla_xxxxxxxx"
```

Lo que puede hacer la clave depende del rol de su usuario y de qué bots ve (ver [security.md](security.md)).
Excepción: con el widget prendido, los eventos y audios del bot son públicos (es el chat de tu web).

## Bots

### `GET /bots`

```sh
curl -s http://127.0.0.1:8000/api/v1/bots
```
```json
{"bots": [{"id": "654a0008", "name": "Pizzería", "slug": "pizzeria", "online": true,
           "trained_at": "2026-11-24 22:10", "intents": ["Saludar", "Pedir pizza"],
           "environments": {"production": 3, "staging": 4}}]}
```

Solo lista los bots que ve quien llama.

### `GET /bots/{bot}`

El mismo objeto, para un bot.

## Eventos: `POST /bots/{bot}/events`

Una conversación es una serie de eventos con el mismo `sessionId`.

Campos comunes:

| Campo | Qué es |
|---|---|
| `type` | `start` (o `online`), `message` o `end`. Si falta y hay `text`, es `message`. |
| `sessionId` | La conversación. |
| `channel` | Texto libre para filtrar después (`web`, `ivr`, `whatsapp`…). Por defecto `api`. |
| `environment` | `production` (por defecto), `staging` o `draft`. |

### `start`: empezar (con datos precargados)

```sh
curl -s http://127.0.0.1:8000/api/v1/bots/pizzeria/events \
  -H 'Content-Type: application/json' \
  -d '{"type": "start", "sessionId": "cliente-42", "channel": "ivr",
       "data": {"nombre": "Ana", "dni": "30123456", "idioma": "es"}}'
```

- `data`: los campos que se llaman como un slot se guardan en ese slot; el resto vuelve en `ignored_data`.
  `idioma`, `language` o `lang` eligen el idioma de la charla si el bot lo tiene.
- Corre el flujo con trigger `__start__`, si hay.
- Si ese `sessionId` ya existía, empieza de cero pero conserva el historial.

### `message`: un mensaje de la persona

```sh
curl -s http://127.0.0.1:8000/api/v1/bots/pizzeria/events \
  -H 'Content-Type: application/json' \
  -d '{"type": "message", "sessionId": "cliente-42", "text": "quiero dos de muzza"}'
```

`text` es obligatorio (hasta 4000 caracteres). Para tocar un botón, mandá su `value`.

Respuesta (de `start` y `message`):

```json
{
  "bot": {"id": "654a0008", "name": "Pizzería"},
  "sessionId": "cliente-42", "channel": "ivr",
  "started": "2026-11-25T10:00:00", "updated": "2026-11-25T10:00:05", "ended": false,
  "messages": ["Listo: 2 de muzzarella. ¡Ya sale!"],
  "buttons": [],
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
| `messages` | Lo que dice el bot, en orden. |
| `buttons` | Botones del último mensaje: `[{"label", "value"}]`. |
| `understood` | (solo `message`) intención, confianza, entidades y `answer_to`: el slot al que respondió, si el mensaje se tomó como respuesta a una pregunta. En `start` es `null`. |
| `slots` | La memoria de la conversación. |
| `waiting_for` | El slot que está preguntando, o `null`. |
| `flow` | El flujo en curso, o `null`. |
| `classifications` | Las clasificaciones de la conversación. |
| `environment`, `version` | Contra qué responde (`version: null` = borrador). |
| `handoff` | `true` si la atiende una persona: el bot no va a contestar; leé las respuestas con `/messages`. |
| `language` | Idioma de la charla. |
| `via` | `null` (motor), `ia` o `knowledge`: quién resolvió el turno. |
| `sources` | Si respondió la base de conocimiento: `[{"title", "doc", "score"}]`. |
| `next` | Índice para pedir mensajes nuevos con `/messages?after=`. |
| `ignored_data`, `trace` | (solo `start`) datos que no eran slots y traza del flujo de inicio. |

### `end`: terminar

```sh
curl -s http://127.0.0.1:8000/api/v1/bots/pizzeria/events \
  -H 'Content-Type: application/json' -d '{"type": "end", "sessionId": "cliente-42"}'
```
```json
{"sessionId": "cliente-42", "ended": true}
```

Un `message` a una conversación terminada empieza con la memoria en blanco.

## Audio: `POST /bots/{bot}/audio`

Necesita los extras de voz. Transcribe localmente, lo atiende como un `message` y, con `speak`, devuelve la
respuesta en audio.

```sh
curl -s http://127.0.0.1:8000/api/v1/bots/pizzeria/audio \
  -H 'Content-Type: application/json' \
  -d "{\"sessionId\": \"cliente-42\", \"mime\": \"audio/webm\", \"speak\": true, \"audio\": \"$(base64 < nota.webm)\"}"
```

- `audio`: base64 (acepta también `data:audio/webm;base64,...`). Hasta 60 segundos.
- `mime`: por defecto `audio/webm`.
- `sessionId`, `channel`, `environment` como en `message`.

Respuesta: la misma de `message` más `heard` (lo transcripto) y, con `speak: true`, `audio` (WAV en base64).

## Conversaciones

### `GET /bots/{bot}/sessions`

Filtros: `channel`, `classification` (`__none__` = sin clasificar), `from` y `to` (`YYYY-MM-DD`, por el día en
que empezó).

```sh
curl -s 'http://127.0.0.1:8000/api/v1/bots/pizzeria/sessions?channel=ivr&from=2026-11-01'
```
```json
{"sessions": [{"sessionId": "cliente-42", "channel": "ivr", "started": "...", "updated": "...", "ended": false,
               "messages": 6, "first_message": "quiero dos de muzza", "last_message": "Listo: ...",
               "data": {"nombre": "Ana", "dni": "30123456"}, "classifications": ["Venta"],
               "environment": "production", "version": 3}]}
```

### `GET /bots/{bot}/sessions/{sessionId}`

El estado (los mismos campos que la respuesta de un evento, sin `messages`) más `history`: cada entrada tiene
`from` (`user`, `bot`, `event` o `human`), `text` y `at`. Las de `user` traen `intent`, `confidence`, `entities`,
`answer_to`, `fallback` y `via`; las de `bot`, `buttons` si tenía; las de `human`, `by`.

### `GET /bots/{bot}/sessions/{sessionId}/messages?after=N`

Lo nuevo desde el índice `N` (el `next` de la respuesta anterior). Sirve para recibir lo que escribe una persona
desde la Bandeja.

```json
{"sessionId": "cliente-42", "messages": [{"from": "human", "text": "Hola Ana, soy Marta", "at": "...", "by": "marta"}],
 "next": 9, "handoff": true, "ended": false}
```

### `DELETE /bots/{bot}/sessions/{sessionId}`

```json
{"sessionId": "cliente-42", "deleted": true}
```

## Reporte: `GET /bots/{bot}/report`

Cuántas conversaciones terminaron con cada clasificación. Filtros `from`, `to`, `channel`.

```json
{"bot": {"id": "654a0008", "name": "Pizzería"}, "from": "2026-11-01", "to": null, "channel": null,
 "sessions": 120, "unclassified": 14,
 "classifications": [{"name": "Venta", "count": 80, "configured": true}],
 "by_day": [{"date": "2026-11-01", "sessions": 9, "unclassified": 1, "counts": {"Venta": 6}}]}
```

`configured: false` = una clasificación que ya no existe en el bot.

## Llamadas desde un navegador (CORS)

Parla rechaza con 403 los pedidos a `/api/` que vienen de otro sitio web (el encabezado `Origin`), para que
cualquier página no pueda usar tu Parla local. Las únicas excepciones son `events`, `audio` y
`sessions/{id}/messages` de un bot con el widget prendido, desde los sitios cargados en **Widget web**
(`widget.origins`, o `*` para cualquiera). Desde tu backend (sin `Origin`) no hay restricción de origen.

## API interna

La interfaz usa además `/api/agents/...`, `/api/auth/...`, `/api/users...`, `/api/ai/...`, `/api/voice/...` y
`/api/connect`. No son una API estable: pueden cambiar entre versiones. El servidor MCP las usa y es un buen
ejemplo de cómo llamarlas.
