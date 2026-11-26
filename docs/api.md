# HTTP API

**English** · [Español](api_es.md)

Parla exposes two APIs on the same port:

- **The public API `/api/v1`**: the one your website, your system, an IVR or a CRM uses to talk to a bot. It is
  stable. The same reference, with examples for each bot, is in the UI under **Publish → API**.
- **The internal API** (`/api/agents`, `/api/auth`, `/api/users`, `/api/ai`, `/api/voice`, `/api/connect`): the one
  the web UI and the MCP server use. It is documented [below](#internal-api), but it may change between versions.

General notes:

- Base: `http://127.0.0.1:8000` (or the port you passed to `app.py`).
- Request bodies and responses are JSON. The body must be a JSON object (otherwise 400). Maximum size (otherwise
  413): 25 MB for uploading files, knowledge documents, audio and Rasa projects; 2 MB for audio from the public widget; 1 MB for
  everything else.
- Errors: `{"error": "mensaje en castellano"}` (in Spanish by default; send `Accept-Language: en` or `pt` for
  English or Portuguese) with 400, 401, 403, 404, 405, 409, 413, 415
  or 429 (409: publishing to production with failing tests, or an outbound send that isn't allowed), and 502 when
  an outbound send is rejected by the channel. An exception inside a route (for example, requesting a version that doesn't exist) comes back as 400 with the
  message.
- `{bot}` can be the id (`654a0008`), the exact name (case-insensitive) or the slug (`pizzeria`). If the name is
  ambiguous, use the id.
- `sessionId`: up to 100 characters, unaccented letters, digits and `. @ + - _`, no spaces and not starting with a
  dot. If you don't send it in `start` or `message`, Parla generates one and returns it.

## Authentication and roles

As long as no user exists, everything is open (no login or key required).

With users, every request to `/api/` (except `/api/auth/*`) needs one of these two:

- **API key** (for your system, the MCP or `curl`): `Authorization: Bearer parla_xxxxxxxx`. Created in
  **Users → your user → API keys**.
- **Session cookie** `parla_session` (used by the UI): lasts 12 hours and is stored in `parla.db` (it survives a
  server restart).

Without either: 401. What you can do depends on the user's role:

| Role | Can |
|---|---|
| `owner` | Everything, including managing users (`/api/users*`). Sees all bots. |
| `editor` | Everything except managing users. |
| `analyst` | Only `GET` requests (read-only), plus `POST /api/agents/{id}/tests/run` (running tests changes nothing). Any other method: 403. |
| `agent` (support) | Only the Inbox: `GET /api/agents`, `GET /api/agents/{id}`, `GET /api/agents/{id}/inbox`, `POST /api/agents/{id}/sessions/{sid}/take\|reply\|release` and `GET /api/v1/bots/{bot}/sessions/{sid}[/messages]`. |

Users who aren't owners can have a list of visible bots (`bots`). A request to a bot they can't see returns 404, as
if it didn't exist. `GET /api/v1/bots` and `GET /api/agents` list only the ones they see.

**Exception: the widget.** If the bot has the widget enabled, `POST /api/v1/bots/{bot}/events` and
`POST /api/v1/bots/{bot}/audio` are public (it's the chat on your website), and so is
`GET /api/v1/bots/{bot}/sessions/{sid}/messages` for conversations on the `web` channel. A public request (without a
session, or from someone who can't see that bot) is restricted: always `web` channel and `production` environment,
no start `data`, no `trace` in the response, and it can't continue a conversation from another channel (403). See
[security.md](security.md).

## Public API `/api/v1`

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

The same object, for one bot.

### `POST /api/v1/bots/{bot}/events`

A conversation is a series of events with the same `sessionId`.

Common fields:

| Field | What it is |
|---|---|
| `type` | `start` (or `online`), `message` or `end`. If missing and there is `text`, it is `message`. |
| `sessionId` | The conversation. |
| `channel` | Free text to filter by later (`web`, `ivr`, `whatsapp`…), up to 30 characters. Default `api`. |
| `environment` | `production` (default), `staging` or `draft`. Requesting `staging` with nothing published there gives 400. |

#### `start`: start (with preloaded data)

```sh
curl -s http://127.0.0.1:8000/api/v1/bots/pizzeria/events \
  -H 'Content-Type: application/json' \
  -d '{"type": "start", "sessionId": "cliente-42", "channel": "ivr",
       "data": {"nombre": "Ana", "dni": "30123456", "idioma": "es"}}'
```

- `data` (object): fields named like a slot are stored in that slot; the rest come back in `ignored_data`.
  `idioma`, `language` or `lang` choose the conversation language if the bot has it in `languages`.
- Runs the flow with trigger `__start__`, if there is one. `flow` (the name of a flow) runs that one instead; it
  isn't accepted from the public widget.
- If that `sessionId` already existed, it starts from scratch (blank memory, with the version the environment has
  now) but keeps the history.

#### `message`: a message from the person

```sh
curl -s http://127.0.0.1:8000/api/v1/bots/pizzeria/events \
  -H 'Content-Type: application/json' \
  -d '{"type": "message", "sessionId": "cliente-42", "text": "quiero dos de muzza"}'
```

`text` is required (truncated to 4000 characters). To tap a button, send its `value` (or its `label`). If the
conversation didn't exist, it is created at that point (without running the start flow).

Response to `start` and `message`:

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

| Field | What it is |
|---|---|
| `messages` | What the bot says, in order (text only). |
| `buttons` | Buttons of the last message: `[{"label", "value"}]`. |
| `replies` | Same as `messages` with detail: `[{"text", "buttons", "file"?}]`. `file` appears when a step sends a file: `{"id", "name", "mime", "size", "url"}` (see [concepts.md](concepts.md#file-send-a-file)). |
| `understood` | (`message` only) intent, confidence, entities and `answer_to`: the slot it answered, if the message was taken as the answer to a question. In `start` it is `null`. |
| `slots` | The conversation's memory. |
| `waiting_for` | The slot it is asking for, or `null`. |
| `flow` | The current flow, or `null`. |
| `classifications` | The conversation's classifications. |
| `environment`, `version` | What it is answering against (`version: null` = draft). |
| `handoff` | `true` if a person is handling it: the bot won't answer; read the replies with `/messages`. |
| `language` | Conversation language. |
| `via` | What resolved the turn: `null` (the engine), `ia` (AI), `knowledge` (knowledge base) or `significado` (an answer understood by meaning, see [ai-and-voice.md](ai-and-voice.md#understanding-answers-by-meaning)). |
| `sources` | If the knowledge base answered: `[{"title", "doc", "score"}]`. |
| `next` | Index to request new messages with `/messages?after=`. |
| `ignored_data`, `trace` | (`start` only) data that weren't slots and the trace of the start flow. |

#### `end`: finish

```sh
curl -s http://127.0.0.1:8000/api/v1/bots/pizzeria/events \
  -H 'Content-Type: application/json' -d '{"type": "end", "sessionId": "cliente-42"}'
```
```json
{"sessionId": "cliente-42", "ended": true}
```

404 if it doesn't exist. A `message` to a finished conversation starts with blank memory.

### `POST /api/v1/bots/{bot}/audio`

Requires the voice extras (or a BYOK voice provider). Transcribes with the agent's `voice.asr`, handles it like a
`message` and, with `speak`, returns the reply as audio from the agent's `voice.tts`.

```sh
curl -s http://127.0.0.1:8000/api/v1/bots/pizzeria/audio \
  -H 'Content-Type: application/json' \
  -d "{\"sessionId\": \"cliente-42\", \"mime\": \"audio/webm\", \"speak\": true, \"audio\": \"$(base64 < nota.webm)\"}"
```

- `audio`: base64 (also accepts `data:audio/webm;base64,...`). Between 0.3 and 60 seconds.
- `mime`: default `audio/webm`.
- `speak`: `true` to receive the reply as audio.
- `sessionId`, `channel`, `environment` as in `message`.

Response: the same as `message` plus `heard` (the transcription) and, with `speak: true`, `audio` (WAV in base64).
Without voice installed, with audio that can't be read, or with no words: 400 with the reason.

### `GET /api/v1/bots/{bot}/sessions`

Filters: `channel`, `classification` (`__none__` = unclassified), `from` and `to` (`YYYY-MM-DD`, by the day it
started) and `campaign` (the id of the campaign that started it, see [outbound.md](outbound.md#campaigns)). Most
recent activity first.

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

The state (`bot`, `sessionId`, `channel`, dates, `ended`, `slots`, `waiting_for`, `flow`, `classifications`,
`environment`, `version`, `language`, `next`) plus `history`. Here `handoff` is the full object
(`{"active", "since", "reason", "by", "until"?}`) or `null`.

Each `history` entry has `from` (`user`, `bot`, `event` or `human`), `text` and `at`. `user` entries carry `intent`,
`confidence`, `entities`, `answer_to`, `fallback`, `via` and `flow`/`waiting` (where the conversation was); `bot`
entries carry `buttons` and `file` if they had them; `human` entries carry `by`; `event` entries may carry `data`
(the start data) or `classification`. The last 500 messages are kept. With `pii_redaction` on, texts, entity
values and `data` come with personal data masked («[email]», «[teléfono]», …).

`usage` is the conversation's measured usage and estimated cost (`{"currency", "estimated": true, "total", "items":
[{"kind", "group", "provider", "model", "qty", "unit", "cost", "priced"}]}`); `user` history entries carry the turn's
`usage` (`{"kind|provider|model": qty}`). See [costs.md](costs.md).

### `GET /api/v1/bots/{bot}/sessions/{sessionId}/messages?after=N`

What's new since index `N` (the `next` of the previous response). Use it to receive what a person writes from the
Inbox.

```json
{"sessionId": "cliente-42", "messages": [{"from": "human", "text": "Hola Ana, soy Marta", "at": "...", "by": "marta"}],
 "next": 9, "handoff": true, "ended": false}
```

### Push: WebSocket and SSE

Same port, same authentication as the polling routes (cookie, `Authorization: Bearer`, or the public widget rules
when anonymous: widget on, site in **Allowed sites**, channel `web`). Polling keeps working.

**WebSocket** `GET /api/v1/bots/{bot}/ws` (RFC 6455, text frames with JSON, up to 1 MB per message, ping every 30 s).
Send the same bodies as `POST /events`, plus an optional `id` that comes back in the reply:

```text
→ {"id": 1, "type": "start", "sessionId": "cliente-42"}
← {"type": "reply", "id": 1, "status": 200, "body": {...same as POST /events...}}
→ {"id": 2, "type": "message", "sessionId": "cliente-42", "text": "¿abren el domingo?"}
← {"type": "delta", "stream": 7, "text": "Sí, abrimos"}           (AI replies while they are written)
← {"type": "delta", "stream": 7, "text": " de 12 a 23."}
← {"type": "reply", "id": 2, "status": 200, "body": {...}}
← {"type": "messages", "sessionId": "cliente-42", "messages": [{"from": "human", ...}], "next": 12, "handoff": true, "ended": false}
→ {"type": "follow", "sessionId": "cliente-42", "after": 12}       (listen without sending, e.g. after a reload)
```

`messages` carries what the socket didn't cause itself (Inbox replies, take/release events), same shape as
`GET .../messages`. `overflow` means events were dropped for a slow client: send `follow` again. A cross-site
`Origin` that isn't an allowed widget site gets `403` on the handshake.

**SSE** (`text/event-stream`, a comment every 15 s keeps proxies open):

| Route | Events |
|---|---|
| `GET /api/v1/bots/{bot}/sessions/{sessionId}/stream?after=N` | `messages` (same body as `GET .../messages`), `delta`, `replace` |
| `GET /api/agents/{id}/inbox/stream` | `inbox` (same body as `GET /api/agents/{id}/inbox`, sent when it changes) |
| `GET /api/agents/{id}/campaigns/stream` | `campaigns` (the campaign list, sent on each send or status change) |

```text
event: messages
data: {"sessionId": "cliente-42", "messages": [...], "next": 9, "handoff": false, "ended": false}
```

**AI streaming and guardrails.** Knowledge answers, the generative fallback and the `agent` step stream tokens as
`delta` events (for JSON outputs, only the user-facing text field). Guardrails that need the whole text (the leak
regex, "the fallback must ask back", the knowledge support check) run at the end: if the final text differs from what
was streamed, a `replace` event with the same `stream` id carries the final text (`""` = remove it). The `reply` /
`messages` event always has the final text, so clients without streaming see exactly what they saw before.

### Real-time voice WebSocket

`GET /api/v1/bots/{bot}/voice/ws` (same authentication and `Origin` rules as `/ws`, public widget included). Binary
frames are audio, PCM16 little-endian mono 16 kHz, both ways (send ~20–100 ms per frame). Text frames are JSON.
Engine and latency: [ai-and-voice.md](ai-and-voice.md#real-time-voice).

```text
← {"type": "ready", "rate": 16000}
→ {"type": "start", "sessionId": "cliente-42", "language": "es", "channel": "web", "replay": true}
   (the conversation must exist: start it with POST /events; replay: say aloud the bot's last messages)
→ <binary PCM16>  …                                    ← <binary PCM16> (the bot's voice, queue it)
← {"type": "partial", "text": "quiero una"}             (Deepgram only)
← {"type": "transcript", "text": "quiero una muzza"}    (end of the person's turn; runs as a POST /events message)
← {"type": "speaking", "latency_ms": 412}               (first audio byte of the reply)
← {"type": "reply", "status": 200, "body": {...same as POST /events...}}
← {"type": "clear"}                                     (barge-in: stop playback now, drop what's queued)
→ {"type": "stop"}
```

The phone streams (`/phone/twilio/stream`, `/phone/jambonz/stream`) are the providers' protocols, not this one: see
[channels.md](channels.md#real-time-stream-mode).

### `DELETE /api/v1/bots/{bot}/sessions/{sessionId}`

```json
{"sessionId": "cliente-42", "deleted": true}
```

### `GET /api/v1/bots/{bot}/report`

How many conversations had each classification. Filters `from`, `to`, `channel`, `campaign`.

```json
{"bot": {"id": "654a0008", "name": "Pizzería"}, "from": "2026-11-01", "to": null, "channel": null,
 "sessions": 120, "unclassified": 14,
 "classifications": [{"name": "Venta", "count": 80, "configured": true}],
 "by_day": [{"date": "2026-11-01", "sessions": 9, "unclassified": 1, "counts": {"Venta": 6}}]}
```

`configured: false` = a classification that no longer exists in the bot.

### `GET /api/v1/bots/{bot}/costs`

What the conversations cost: measured usage × the current price table ([costs.md](costs.md)). Analyst or above.
Filters `from`, `to` (usage days), `channel`, `campaign`; `group=day|channel|provider` also returns `groups`.

```json
{"currency": "USD", "estimated": true, "from": "2026-11-01", "to": null, "total": 12.41,
 "by_day": [{"date": "2026-11-01", "cost": 0.52}], "by_channel": [{"channel": "whatsapp", "cost": 8.1}],
 "by_kind": [{"group": "llm", "cost": 6.2}],
 "by_provider": [{"kind": "llm_input", "group": "llm", "provider": "anthropic", "model": "claude-sonnet-5-5",
                  "qty": 1830000, "unit": "tokens", "cost": 3.66, "priced": true}],
 "conversations": {"count": 310, "avg": 0.04, "median": 0.021, "p95": 0.13},
 "resolved": {"count": 251, "cost_per": 0.049}, "top": [{"sessionId": "wa-5491112345678", "channel": "whatsapp", "cost": 0.91}],
 "missing_prices": [{"kind": "whatsapp", "provider": "meta", "model": "service"}]}
```

### `POST /api/v1/bots/{bot}/outbound`

The bot writes first: a message on WhatsApp or Telegram, a call, or a message into an open widget conversation.
Owner or editor (API key or session); never public. Details, the WhatsApp window and templates in
[outbound.md](outbound.md).

```sh
curl -s http://127.0.0.1:8000/api/v1/bots/clinica/outbound \
  -H 'Authorization: Bearer parla_xxxxxxxx' -H 'Content-Type: application/json' \
  -d '{"channel": "whatsapp", "to": "+5491112345678", "template": "recordatorio_turno",
       "flow": "Confirmar turno", "data": {"nombre": "Ana", "fecha": "1/12 a las 10"}}'
```
```json
{"sessionId": "wa-5491112345678", "via": "template", "messages": [], "message_id": "wamid.HBgN…",
 "id": 17, "channel": "whatsapp", "to": "5491112345678", "status": "sent"}
```

- Body: `channel` (`whatsapp` by default, `telegram`, `phone`, `web`), `to` (number with country code, Telegram
  chat id or widget `sessionId`), `data` (slots), `flow` and, on WhatsApp, `template` (a name from
  `channels.whatsapp.templates` or `{"name", "language", "params", "components"}`).
- `via`: `message`, `template` (outside WhatsApp's 24-hour window; `flow` runs when the person replies) or `call`.
- 409: outside the window without a template, the person opted out, or a person is handling the conversation.
  429: more than `agent.outbound.api_per_minute` (default 30) per minute. 502: the channel rejected it.

### Contact center (external handoff)

For a contact center outside Parla ([contact-centers.md](contact-centers.md)). Owner/editor key or an
`integration`-scoped key.

| Route | Body → response |
|---|---|
| `POST /api/v1/bots/{bot}/sessions/{sid}/handoff` | `{"action": "accept", "agent_name"?}` · `{"action": "release", "data"?, "flow"?}` · `{"action": "close", "resolution"?}` → the conversation (like `GET …/sessions/{sid}` without `history`). 400 unknown action/flow, 404, 409 already ended. |
| `POST /api/v1/bots/{bot}/sessions/{sid}/messages` | `{"text", "from_name"?}` → the conversation plus `delivered`. Delivered through the channel (widget, WhatsApp, Telegram). 409: phone call, ended, or WhatsApp outside 24 h. 502: the provider rejected it. |
| `GET /api/v1/bots/{bot}/lookup?phone=\|chat=\|sid=` | The latest open conversation of that customer (handed-off first), same body as the webhook (without `id`/`type`). 404 if none. |

**Outbound webhooks** (`agent.webhooks`): events `handoff.requested`, `handoff.released`, `conversation.started`,
`conversation.ended`, `message.user`, `message.bot`, `csat.received`, `campaign.finished`, signed with
`Parla-Signature: t=…,v1=…`. Payload, retries and verification in
[contact-centers.md](contact-centers.md#webhook-events).

### WhatsApp and Telegram webhooks

Called by Meta and Telegram, not by you: they don't use login or API keys and accept any `Host`. They answer 403
with no details if the channel is off in the bot (`channels.whatsapp.enabled` / `channels.telegram.enabled`), a key
is missing or the signature doesn't match. Body up to 1 MB. Setup in [channels.md](channels.md).

| Route | Authenticated by | Response |
|---|---|---|
| `GET /api/v1/bots/{bot}/whatsapp?hub.mode=subscribe&hub.verify_token=…&hub.challenge=…` | `hub.verify_token` = `WHATSAPP_VERIFY_TOKEN` | `200` with the challenge as `text/plain`. |
| `POST /api/v1/bots/{bot}/whatsapp` | `X-Hub-Signature-256: sha256=<HMAC-SHA256 of the body with WHATSAPP_APP_SECRET>` | `200 ok` right away; messages are processed in the background, repeated ids once. Statuses (`sent`, `delivered`, `read`, `failed`) update the outbound sends ([outbound.md](outbound.md#delivery-statuses)). |
| `POST /api/v1/bots/{bot}/telegram` | `X-Telegram-Bot-Api-Secret-Token` = `TELEGRAM_WEBHOOK_SECRET` | `200 {}` right away; `message` and `callback_query` are processed in the background. |

Each message is processed like `POST …/events` with `environment: production`, `channel: whatsapp` or `telegram`
and `sessionId` `wa-<phone>` or `tg-<chat_id>`; the `replies` are sent back through the channel.

### Phone webhooks (Twilio and jambonz)

Called by Twilio or jambonz during a call. Like the ones above, they skip login and the `Host` check and answer
403 with no details if `channels.phone.enabled` is off, the route's provider isn't `channels.phone.provider`, a
key is missing or the signature doesn't match. Body up to 1 MB. Setup in
[channels.md](channels.md#phone-calls-twilio-and-jambonz).

| Route | Authenticated by | Response |
|---|---|---|
| `POST /api/v1/bots/{bot}/phone/twilio` (call starts), `…/twilio/gather` (each answer: `SpeechResult` / `Digits`) | `X-Twilio-Signature`: base64 of HMAC-SHA1 with `TWILIO_AUTH_TOKEN` of the public URL + each POST key and value sorted by key | TwiML (`text/xml`): `<Gather input="speech dtmf">` with `<Say>` or `<Play>`, `<Dial>` or `<Hangup>`. |
| `POST /api/v1/bots/{bot}/phone/twilio/status` | Same | `200`; `CallStatus` `completed`, `busy`, `failed`, `no-answer` or `canceled` ends the conversation. |
| `POST /api/v1/bots/{bot}/phone/jambonz`, `…/jambonz/gather` (`speech.alternatives[0].transcript` / `digits`) | `Jambonz-Signature: t=<unix>,v1=<HMAC-SHA256 of "<t>.<body>" with JAMBONZ_WEBHOOK_SECRET>` (5 minutes of tolerance) and/or `Authorization: Basic` with `JAMBONZ_BASIC_USER` / `JAMBONZ_BASIC_PASSWORD`: every one that is loaded must match | jambonz verbs (JSON array): `gather` (`input: ["speech", "digits"]`, `bargein`, nested `say` or `play`), `say`/`play`, `dial`, `hangup`. |
| `POST /api/v1/bots/{bot}/phone/jambonz/status` | Same | `200 {}`; `call_status` as above ends the conversation. |
| `GET /api/v1/bots/{bot}/phone/audio/<token>.wav` | The token: HMAC-SHA256 signed by the server, names the bot, expires in 10 minutes | Parla's voice (piper) for `tts: "parla"`, `audio/wav`. 403 if invalid or expired. |

Each turn is processed like `POST …/events` with `environment: production`, `channel: phone` and
`sessionId` `call-<CallSid>`. On the first one, `data` carries `caller` (the caller's number) and `language`.
On a call Parla placed, the webhook URLs carry `?o=<token>` (covered by the signature): `data` adds the send's
data, `caller` is the number that was called, and the send's `flow` runs instead of `__start__`.

### Calls from a browser (CORS) and allowed host names

Parla rejects with 403 requests to `/api/` that carry an `Origin` header whose host isn't `127.0.0.1:<port>`,
`localhost:<port>` or one of `PARLA_HOSTS`, so that arbitrary pages can't use your Parla. The only exceptions are
`events`, `audio` and `sessions/{id}/messages` of a bot with the widget enabled, from the sites listed in
**Web widget** (`widget.origins`, or `*` for any). For those routes it also answers the `OPTIONS`
preflight (204, methods `POST, GET, OPTIONS`). From your backend (without `Origin`) there is no origin restriction.

In addition, against DNS rebinding, a request to `/api/` whose `Host` isn't `127.0.0.1`, `localhost`, `[::1]` (any
port) or one of `PARLA_HOSTS` is rejected with 403, unless it carries a valid API key or is the widget's public
chat. Behind a proxy, add your domain to `PARLA_HOSTS` (see [deployment.md](deployment.md)).

## Files: `GET /files/{agente}/{fileId}`

The files sent by a `file` step (`{agente}` is the agent). Outside `/api/` and without login: the `fileId` is random
(22 characters) and acts as the key. They are served with the type based on the extension and
`X-Content-Type-Options: nosniff`; PDFs, images and TXT open in the browser, everything else is downloaded.

## Internal API

Used by the UI and the MCP server. It is not stable. All routes follow the rules in
[authentication and roles](#authentication-and-roles). `{id}` is always the agent's 8-character id (the name or slug
don't work here).

### Session and users (`parla/auth.py`)

| Route | Who | Body | Response |
|---|---|---|---|
| `GET /api/auth/me` | Anyone | — | `{"enabled": there are users, "user": {"name", "role", "bots"} \| null}` |
| `POST /api/auth/login` | Anyone | `{"name", "password"}` | Same as `me`, plus the cookie. 401 if it doesn't match; 429 after 5 failed attempts in one minute (per user and IP). |
| `POST /api/auth/logout` | Anyone | — | `{"enabled", "user": null}` and clears the cookie. |
| `GET /api/users` | Owner (with no users, anyone: returns the empty list) | — | `{"users": [{"name", "role", "bots", "keys": [{"id", "label", "created"}]}]}` |
| `POST /api/users` | Owner. With no users, anyone: the first one becomes owner and is logged in. | `{"name", "password"` (5 or more characters), `"role", "bots"?}` | The user. |
| `PUT /api/users/{nombre}` | Owner | `{"role"?, "bots"?, "password"?}` | The user. Changing the password closes their sessions. At least one owner must remain. |
| `DELETE /api/users/{nombre}` | Owner | — | `{"deleted": name}`. The only owner can't be deleted. |
| `POST /api/users/{nombre}/keys` | Owner | `{"label"}` | `{"id", "label", "created", "key"}`. The key is shown only this once. |
| `DELETE /api/users/{nombre}/keys/{keyId}` | Owner | — | The user. |

`{nombre}` is the user name. `bots`: `null` (sees all) or a list of agent ids. The owner always sees all.

### Audit

| Route | Who | Response |
|---|---|---|
| `GET /api/audit?agent=&user=&since=&limit=` | Owner (403 for other roles; with no users, anyone) | `{"entries": [{"at", "user", "role", "agent_id", "action", "detail"}]}`, newest first. Filters: `agent` (id), `user` (name), `since` (`YYYY-MM-DD` or `YYYY-MM-DDTHH:MM:SS`), `limit` (1 to 1000, 200 by default). |

The actions recorded are listed in [security.md](security.md#audit-log).

### Agents

| Route | Body | Response |
|---|---|---|
| `GET /api/agents` | — | `[{"id", "name", "intents" (count), "flows" (count)}]` |
| `POST /api/agents` | `{"name", "demo"?: true}` (blank, or the ordering example) or `{"import": agent}` (accepts the `{"parla": 1, "agent": ...}` envelope) | The created agent. A user who sees only some bots also gets to see this one. |
| `POST /api/agents/import/rasa` | `{"zip": base64 of the project .zip, "name"?}` or `{"files": {"domain.yml": "...", "data/nlu.yml": "..."}, "name"?}` | `{"agent", "warnings"}`: a new agent converted from a Rasa 3.x project and already trained; `warnings` lists everything that couldn't be migrated as is. Same role as creating an agent (owner or editor). Only `.yml`/`.yaml` files are read; zip limits: 500 files, 20 MB uncompressed, no absolute paths or `..`. See [migrate-from-rasa.md](migrate-from-rasa.md). |
| `GET /api/agents/{id}` | — | The agent's full JSON (draft), with the full `system`. |
| `PUT /api/agents/{id}` | The whole agent | The saved agent. Replaces everything (anything missing goes back to blank values); `environments` and `deployments` can't be overwritten. Includes the operational settings `retention_days` (days, `0` = forever, `null` = `PARLA_RETENTION_DAYS`) and `pii_redaction` (`false`, `true` or a list of `email`, `phone`, `card`, `id`, `bank`); they aren't versioned or exported. See [concepts.md](concepts.md#retention-and-personal-data). The conversation tests are the `tests` field (see [testing-bots.md](testing-bots.md#format)). |
| `DELETE /api/agents/{id}` | — | `{}`. Deletes the agent, its model, versions, conversations and files. |
| `POST /api/agents/{id}/train` | `{"fingerprint"?}` | `{"at", "fingerprint", "phrases", "marked", "log"}`; `log` has the steps, the self-evaluation (`self_check`), the CRF and the tips (`warnings`). |
| `POST /api/agents/{id}/chat` | `{"session", "text", "environment"?}` (`draft` by default) | One turn of the test chat (channel `prueba`): `messages`, `buttons`, `replies`, `nlu` (`intent`, `confidence`, `ranking`, `entities`), `slots`, `trace`, `answer_to`, `rejected`, `fallback`, `handoff`, `language`, `via`, `sources`, `tools` (the agent step's tool calls this turn: `[{"tool", "type", "args", "ok", "result" (up to 300 characters), "ms"}]`, secrets masked). |
| `POST /api/agents/{id}/reset` | `{"session"}` | `{}`. Ends that conversation. |
| `POST /api/agents/{id}/http` | `{"step": http step, "vars": {slot: value}}` | `{"status", "body"}`: the editor's **Test the call** (with the agent's secrets). |
| `POST /api/agents/{id}/functions/test` | `{"function": definition, "inputs": {}}`, with `Content-Type: application/json` (otherwise 415) | `{"ok", "result" \| "error", "traceback"?, "logs", "ms"}` |
| `POST /api/agents/{id}/mcp/tools` | `{"server": "<name>"}` (a server of the saved agent) or `{"server": {"name", "url", "headers_secret"?}}` (config not saved yet) | `{"tools": [{"name", "description", "inputSchema"}]}`: the editor's **View tools**. 400 if the server doesn't exist, 502 if it can't be reached or answers badly. Owner or editor. |

The agent step's tools live in the agent JSON: `mcp_servers` (`[{"name", "url", "headers_secret"?}]`, at the agent
level) and, in each `agent` step, `tools`, `max_tool_calls` and `time_budget`. See
[concepts.md](concepts.md#agent-let-the-ai-converse).

### Versions

| Route | Body | Response |
|---|---|---|
| `GET /api/agents/{id}/versions` | — | `{"versions": [{"version", "created", "note", "stats", "environments"}], "environments": {"production", "staging"}, "deployments": [{"environment", "version", "previous", "at"}]}`, newest first (up to 50 deployments). |
| `POST /api/agents/{id}/versions` | `{"note", "environment"?, "force"?}` | Publishes the draft as a new version (with its own model) and, if requested, puts it in that environment. Returns the version summary. With `"environment": "production"` and tests in the agent, it runs the whole suite against the draft first: if any fails, 409 `{"error", "tests": results}` and nothing is published; `"force": true` publishes anyway. Staging and no environment are never gated. |
| `POST /api/agents/{id}/tests/run` | `{"environment"?: "draft" \| "staging" \| "production", "names"?: [...]}` | Runs the conversation tests (all, or those in `names`; `environment` overrides each test's own) in memory, without saving sessions: `{"passed", "total", "failed", "tests": [{"name", "environment", "version", "passed", "error"?, "turns": [{"user", "passed", "failures": [{"check", "expected", "got"}], "got": {"intent", "says", "buttons", "slots", "flow", "handoff"}}]}]}`. Owner, editor or analyst. See [testing-bots.md](testing-bots.md#api). |
| `GET /api/agents/{id}/versions/{n}` | — | The summary plus `agent` (the frozen definition). |
| `POST /api/agents/{id}/versions/{n}/restore` | — | Brings the draft back to that version (doesn't touch environments or retrain). Returns the agent. |
| `POST /api/agents/{id}/deploy` | `{"environment": "production" \| "staging", "version": n \| null}` | `{"environment", "version", "previous"}`. `null` leaves the environment empty. Doesn't run the tests. |
| `GET /api/agents/{id}/diff?from=&to=` | — | What changes between `production`, `staging`, `draft` or a version number (by default from `production` to `draft`): `{"changes", "settings", "intents", "entities", "slots", "flows", "classifications", "functions", "tests", "from", "to"}`. |

### Knowledge, voice, files and secrets

| Route | Body | Response |
|---|---|---|
| `POST /api/agents/{id}/knowledge/extract` | `{"kind": "text" \| "html" \| "pdf", "data"}` (`data` in base64 for `pdf`) or `{"kind": "url", "url"}` | `{"title", "text"}`. Saves nothing: the UI adds the document with `PUT`. |
| `POST /api/agents/{id}/knowledge/search` | `{"query", "k"?: 3}` | `{"results": [{"text", "title", "doc", "score"}]}` |
| `POST /api/agents/{id}/voice/transcribe` | `{"audio": base64, "mime", "language", "voice"?}` | `{"text", "language", "ms"}`. Uses the agent's `voice.asr`, or the unsaved `voice` config to test it. |
| `GET /api/agents/{id}/files` | — | `{"files": [{"id", "name", "mime", "size", "url"}]}` |
| `POST /api/agents/{id}/files` | `{"name", "data": base64}` | The uploaded file plus `files`. Up to 10 MB; extensions: pdf, png, jpg, jpeg, gif, webp, txt, csv, doc, docx, xls, xlsx, ppt, pptx, zip. |
| `DELETE /api/agents/{id}/files/{fileId}` | — | `{"files"}` |
| `GET /api/agents/{id}/secrets` | — | `{"secrets": [names]}`. Values are never returned. |
| `PUT /api/agents/{id}/secrets` | `{"name", "value"}`, with `Content-Type: application/json` | `{"secrets"}`. The name is normalized (`api key` → `API_KEY`). |
| `DELETE /api/agents/{id}/secrets` | `{"name"}` | `{"secrets"}` |

### Operations

| Route | Body | Response |
|---|---|---|
| `GET /api/agents/{id}/inbox` | — | `{"sessions": [summary + "handoff"]}`: the conversations a person is handling (or that are waiting for one). |
| `POST /api/agents/{id}/sessions/{sid}/take` | — | A person takes over the conversation. Returns the state plus `history`. |
| `POST /api/agents/{id}/sessions/{sid}/reply` | `{"text"}` | Writes to the person (if it wasn't taken, takes it). On a `whatsapp` or `telegram` conversation it is also sent through that channel. |
| `POST /api/agents/{id}/sessions/{sid}/release` | — | Hands it back to the bot (stops the flow that was halfway through). |
| `GET /api/agents/{id}/channels` | — | **Channels**: `{"public_url", "env_public_url", "whatsapp"/"telegram": {"enabled", "webhook", "secrets": {name: loaded?}, "status": {"last_in", "last_out", "error", "error_at"}}, "phone": {"enabled", "provider", "webhook", "status_webhook", "secrets", "status"}}`. Status is in memory. |
| `POST /api/agents/{id}/channels/telegram` | `{"connect": true \| false}` | Calls Telegram's `setWebhook` (creating `TELEGRAM_WEBHOOK_SECRET` if missing) or `deleteWebhook`: `{"connected"}`. Owner or editor. |
| `GET /api/agents/{id}/insights/unrecognized` | Filters `from`, `to`, `channel`, `classification` | `{"groups": [{"label", "count", "texts", "examples", "suggested_intent"}]}`: **Improve**. |
| `GET /api/agents/{id}/insights/analytics` | The same filters | `{"sessions", "contained", "handoff", "contained_rate", "handoff_rate", "user_messages", "fallbacks", "fallback_rate", "csat", "abandoned", "drop_off", "flows", "by_day"}` |
| `GET /api/agents/{id}/costs` | The same filters, `campaign`; `?sid=` one conversation; `?format=csv` | Like `GET /api/v1/bots/{bot}/costs`; the CSV has one row per day, conversation, channel, provider, model and kind. |
| `GET /api/prices` · `PUT /api/prices` | `{"currency", "prices": [{"kind", "provider", "model", "price", "source"?, "checked"?, "note"?}]}` | The price table ([costs.md](costs.md#prices)). `PUT` owner only (403 otherwise), audited as `prices.update`. |

### Campaigns and opt-outs

Owner or editor; analyst only the `GET`s. `{c}` is the campaign's 12-character id. Bodies, statuses and examples in
[outbound.md](outbound.md#admin-routes).

| Route | Response |
|---|---|
| `GET`, `POST /api/agents/{id}/campaigns` | The list (`{"campaigns"}`) / a new campaign in `draft`, with `imported: {"added", "duplicates", "invalid", "opted_out"}`. |
| `POST /api/agents/{id}/campaigns/preview` | `{"columns", "rows", "count", "mapping"}` of a CSV, without saving. |
| `GET`, `PUT`, `DELETE /api/agents/{id}/campaigns/{c}` | The campaign / edit it (`draft` or `paused`) / delete it (not while `running`). |
| `GET`, `POST /api/agents/{id}/campaigns/{c}/recipients` | `{"total", "recipients"}` with `status`, `limit`, `offset` filters / add people (CSV or list). |
| `POST /api/agents/{id}/campaigns/{c}/start\|pause\|resume\|cancel` | The campaign; 409 if its status doesn't allow it. |
| `GET /api/agents/{id}/campaigns/{c}/export` | The results as CSV. |
| `GET`, `POST`, `DELETE /api/agents/{id}/optouts` | `{"optouts": [{"address", "channel", "keyword", "at"}]}`; `POST`/`DELETE` with `{"address"}` add or remove one by hand. |

### Handoff webhooks

| Route | Response |
|---|---|
| `GET /api/agents/{id}/webhooks/deliveries?limit=50` | `{"deliveries": [{"id", "url", "event", "event_id", "sessionId", "status", "attempts", "code", "error", "latency_ms", "next_at", "created", "updated"}], "pending"}` (analyst too). |
| `POST /api/agents/{id}/webhooks/test` | `{"url"}` of a saved webhook → the `test` delivery, already attempted. |
| `POST /api/agents/{id}/webhooks/deliveries/{n}/retry` | Back to the queue with attempts at zero. 404 if it was delivered. |

`POST /api/users/{name}/keys` accepts `"scope": "integration"`: the key only works for the contact center routes.

### AI, voice and “Connect to AI”

| Route | Body | Response |
|---|---|---|
| `POST /api/ai/status` | `{"ai": config}` and/or `{"agent": id}` (with `agent`, the API key named by `ai.api_key_secret` comes from that agent's vault); with `ai.prompt`, it also tests the model. Owner or editor. | `{"ok", "models", "recommended", "suggested", "provider", "model", "model_ready", "local", "models_unknown"?, "error", "hint", "reply"?, "ms"?}`. `suggested`: model ids for that provider; `local` is `false` for `anthropic` and `gemini`. Never returns the key. |
| `POST /api/ai/pull` | `{"ai": config, "model"}` | `{"ok", "started", "model"}`. Downloads an Ollama model in the background. |
| `GET /api/ai/progress` | — | `{model: {"status", "completed", "total", "done", "error"}}` |
| `GET /api/voice/status` | — | `{"stt", "tts", "hint", "errors", "models"}` |
| `POST /api/voice/speak` | `{"text"` (up to 2000 characters), `"language", "agent"?, "voice"?}` | The audio (`audio/wav`), not JSON. With `agent`, uses that agent's `voice.tts`; `voice` is an unsaved config to test. Phrases already generated come from the cache. |
| `POST /api/voice/voices` | `{"language", "agent"?, "voice"?}` | `{"voices": [{"id", "name"}]}`: ElevenLabs and Google from their APIs, OpenAI and Deepgram fixed lists, `local` the piper voices. |
| `GET /api/connect` | — | `[{"id", "name", "installed", "connected", "manual"}]`, one per assistant. |
| `POST /api/connect` | `{"client": "claude-code" \| "codex" \| "claude-desktop" \| "cursor"}` | `{"ok", "message", ...}`. With users, creates an API key for the requester. |
| `POST /api/connect/remove` | `{"client"}` | `{"ok", "message"}` |

`/api/connect*` only responds if the request's `Host` is `127.0.0.1:<port>` or `localhost:<port>` (otherwise 403)
and the `POST`s require `Content-Type: application/json` (otherwise 415).

The `ai` config (`agent.ai`): `enabled`, `provider` (`"ollama"` default, `"openai"`, `"openai_compatible"`,
`"anthropic"` or `"gemini"`), `url`, `model`, `api_key_secret` (the **name** of a vault key; the key itself is never
accepted in the agent JSON), `azure` / `api_version` (Azure OpenAI), `temperature`, `rescue_intents`, `use_knowledge`,
`generative_fallback`, `persona`. The `voice` config (`agent.voice`): `{"asr": {"provider", "model"?, "api_key_secret"?},
"tts": {"provider", "voice"?, "model"?, "api_key_secret"?}}`. See [concepts.md](concepts.md#agent) and
[ai-and-voice.md](ai-and-voice.md#openai-compatible-endpoints).

### Everything else

- `GET /`: the UI (`web/index.html`).
- `GET /static/{nombre}.js`: the UI scripts and `widget.js`.
