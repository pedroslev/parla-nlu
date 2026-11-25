# HTTP API

**English** · [Español](api_es.md)

Parla exposes two APIs on the same port:

- **The public API `/api/v1`**: the one your website, your system, an IVR or a CRM uses to talk to a bot. It is
  stable. The same reference, with examples for each bot, is in the UI under **Publicar → API** (Publish → API).
- **The internal API** (`/api/agents`, `/api/auth`, `/api/users`, `/api/ai`, `/api/voice`, `/api/connect`): the one
  the web UI and the MCP server use. It is documented [below](#internal-api), but it may change between versions.

General notes:

- Base: `http://127.0.0.1:8000` (or the port you passed to `app.py`).
- Request bodies and responses are JSON. The body must be a JSON object (otherwise 400). Maximum size (otherwise
  413): 25 MB for uploading files, knowledge documents and audio; 2 MB for audio from the public widget; 1 MB for
  everything else.
- Errors: `{"error": "mensaje en castellano"}` (a message in Spanish) with 400, 401, 403, 404, 405, 413, 415 or
  429. An exception inside a route (for example, requesting a version that doesn't exist) comes back as 400 with the
  message.
- `{bot}` can be the id (`654a0008`), the exact name (case-insensitive) or the slug (`pizzeria`). If the name is
  ambiguous, use the id.
- `sessionId`: up to 100 characters, unaccented letters, digits and `. @ + - _`, no spaces and not starting with a
  dot. If you don't send it in `start` or `message`, Parla generates one and returns it.

## Authentication and roles

As long as no user exists, everything is open (no login or key required).

With users, every request to `/api/` (except `/api/auth/*`) needs one of these two:

- **API key** (for your system, the MCP or `curl`): `Authorization: Bearer parla_xxxxxxxx`. Created in
  **Usuarios → tu usuario → Claves de API** (Users → your user → API keys).
- **Session cookie** `parla_session` (used by the UI): lasts 12 hours and lives in the server's memory (it is lost
  when the server restarts).

Without either: 401. What you can do depends on the user's role:

| Role | Can |
|---|---|
| `owner` | Everything, including managing users (`/api/users*`). Sees all bots. |
| `editor` | Everything except managing users. |
| `analyst` | Only `GET` requests (read-only). Any other method: 403. |
| `agent` (support) | Only the Bandeja (Inbox): `GET /api/agents`, `GET /api/agents/{id}`, `GET /api/agents/{id}/inbox`, `POST /api/agents/{id}/sessions/{sid}/take\|reply\|release` and `GET /api/v1/bots/{bot}/sessions/{sid}[/messages]`. |

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
- Runs the flow with trigger `__start__`, if there is one.
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

Requires the voice extras. Transcribes locally, handles it like a `message` and, with `speak`, returns the reply as
audio.

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
started). Most recent activity first.

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
(the start data) or `classification`. The last 500 messages are kept.

### `GET /api/v1/bots/{bot}/sessions/{sessionId}/messages?after=N`

What's new since index `N` (the `next` of the previous response). Use it to receive what a person writes from the
Bandeja (Inbox).

```json
{"sessionId": "cliente-42", "messages": [{"from": "human", "text": "Hola Ana, soy Marta", "at": "...", "by": "marta"}],
 "next": 9, "handoff": true, "ended": false}
```

### `DELETE /api/v1/bots/{bot}/sessions/{sessionId}`

```json
{"sessionId": "cliente-42", "deleted": true}
```

### `GET /api/v1/bots/{bot}/report`

How many conversations had each classification. Filters `from`, `to`, `channel`.

```json
{"bot": {"id": "654a0008", "name": "Pizzería"}, "from": "2026-11-01", "to": null, "channel": null,
 "sessions": 120, "unclassified": 14,
 "classifications": [{"name": "Venta", "count": 80, "configured": true}],
 "by_day": [{"date": "2026-11-01", "sessions": 9, "unclassified": 1, "counts": {"Venta": 6}}]}
```

`configured: false` = a classification that no longer exists in the bot.

### WhatsApp and Telegram webhooks

Called by Meta and Telegram, not by you: they don't use login or API keys and accept any `Host`. They answer 403
with no details if the channel is off in the bot (`channels.whatsapp.enabled` / `channels.telegram.enabled`), a key
is missing or the signature doesn't match. Body up to 1 MB. Setup in [channels.md](channels.md).

| Route | Authenticated by | Response |
|---|---|---|
| `GET /api/v1/bots/{bot}/whatsapp?hub.mode=subscribe&hub.verify_token=…&hub.challenge=…` | `hub.verify_token` = `WHATSAPP_VERIFY_TOKEN` | `200` with the challenge as `text/plain`. |
| `POST /api/v1/bots/{bot}/whatsapp` | `X-Hub-Signature-256: sha256=<HMAC-SHA256 of the body with WHATSAPP_APP_SECRET>` | `200 ok` right away; messages are processed in the background. Statuses are ignored, repeated ids are processed once. |
| `POST /api/v1/bots/{bot}/telegram` | `X-Telegram-Bot-Api-Secret-Token` = `TELEGRAM_WEBHOOK_SECRET` | `200 {}` right away; `message` and `callback_query` are processed in the background. |

Each message is processed like `POST …/events` with `environment: production`, `channel: whatsapp` or `telegram`
and `sessionId` `wa-<phone>` or `tg-<chat_id>`; the `replies` are sent back through the channel.

### Calls from a browser (CORS) and allowed host names

Parla rejects with 403 requests to `/api/` that carry an `Origin` header whose host isn't `127.0.0.1:<port>`,
`localhost:<port>` or one of `PARLA_HOSTS`, so that arbitrary pages can't use your Parla. The only exceptions are
`events`, `audio` and `sessions/{id}/messages` of a bot with the widget enabled, from the sites listed in
**Widget web** (Web widget) (`widget.origins`, or `*` for any). For those routes it also answers the `OPTIONS`
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

### Agents

| Route | Body | Response |
|---|---|---|
| `GET /api/agents` | — | `[{"id", "name", "intents" (count), "flows" (count)}]` |
| `POST /api/agents` | `{"name", "demo"?: true}` (blank, or the ordering example) or `{"import": agent}` (accepts the `{"parla": 1, "agent": ...}` envelope) | The created agent. A user who sees only some bots also gets to see this one. |
| `GET /api/agents/{id}` | — | The agent's full JSON (draft), with the full `system`. |
| `PUT /api/agents/{id}` | The whole agent | The saved agent. Replaces everything (anything missing goes back to blank values); `environments` and `deployments` can't be overwritten. |
| `DELETE /api/agents/{id}` | — | `{}`. Deletes the agent, its model, versions, conversations and files. |
| `POST /api/agents/{id}/train` | `{"fingerprint"?}` | `{"at", "fingerprint", "phrases", "marked", "log"}`; `log` has the steps, the self-evaluation (`self_check`), the CRF and the tips (`warnings`). |
| `POST /api/agents/{id}/chat` | `{"session", "text", "environment"?}` (`draft` by default) | One turn of the test chat (channel `prueba`): `messages`, `buttons`, `replies`, `nlu` (`intent`, `confidence`, `ranking`, `entities`), `slots`, `trace`, `answer_to`, `rejected`, `fallback`, `handoff`, `language`, `via`, `sources`. |
| `POST /api/agents/{id}/reset` | `{"session"}` | `{}`. Ends that conversation. |
| `POST /api/agents/{id}/http` | `{"step": http step, "vars": {slot: value}}` | `{"status", "body"}`: the editor's «Probar consulta» (Test request) (with the agent's secrets). |
| `POST /api/agents/{id}/functions/test` | `{"function": definition, "inputs": {}}`, with `Content-Type: application/json` (otherwise 415) | `{"ok", "result" \| "error", "traceback"?, "logs", "ms"}` |

### Versions

| Route | Body | Response |
|---|---|---|
| `GET /api/agents/{id}/versions` | — | `{"versions": [{"version", "created", "note", "stats", "environments"}], "environments": {"production", "staging"}, "deployments": [{"environment", "version", "previous", "at"}]}`, newest first (up to 50 deployments). |
| `POST /api/agents/{id}/versions` | `{"note", "environment"?}` | Publishes the draft as a new version (with its own model) and, if requested, puts it in that environment. Returns the version summary. |
| `GET /api/agents/{id}/versions/{n}` | — | The summary plus `agent` (the frozen definition). |
| `POST /api/agents/{id}/versions/{n}/restore` | — | Brings the draft back to that version (doesn't touch environments or retrain). Returns the agent. |
| `POST /api/agents/{id}/deploy` | `{"environment": "production" \| "staging", "version": n \| null}` | `{"environment", "version", "previous"}`. `null` leaves the environment empty. |
| `GET /api/agents/{id}/diff?from=&to=` | — | What changes between `production`, `staging`, `draft` or a version number (by default from `production` to `draft`): `{"changes", "settings", "intents", "entities", "slots", "flows", "classifications", "functions", "from", "to"}`. |

### Knowledge, voice, files and secrets

| Route | Body | Response |
|---|---|---|
| `POST /api/agents/{id}/knowledge/extract` | `{"kind": "text" \| "html" \| "pdf", "data"}` (`data` in base64 for `pdf`) or `{"kind": "url", "url"}` | `{"title", "text"}`. Saves nothing: the UI adds the document with `PUT`. |
| `POST /api/agents/{id}/knowledge/search` | `{"query", "k"?: 3}` | `{"results": [{"text", "title", "doc", "score"}]}` |
| `POST /api/agents/{id}/voice/transcribe` | `{"audio": base64, "mime", "language"}` | `{"text", "language", "ms"}` |
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
| `GET /api/agents/{id}/channels` | — | «Canales» (Channels): `{"public_url", "env_public_url", "whatsapp"/"telegram": {"enabled", "webhook", "secrets": {name: loaded?}, "status": {"last_in", "last_out", "error", "error_at"}}}`. Status is in memory. |
| `POST /api/agents/{id}/channels/telegram` | `{"connect": true \| false}` | Calls Telegram's `setWebhook` (creating `TELEGRAM_WEBHOOK_SECRET` if missing) or `deleteWebhook`: `{"connected"}`. Owner or editor. |
| `GET /api/agents/{id}/insights/unrecognized` | Filters `from`, `to`, `channel`, `classification` | `{"groups": [{"label", "count", "texts", "examples", "suggested_intent"}]}`: «Para enseñar» (To teach). |
| `GET /api/agents/{id}/insights/analytics` | The same filters | `{"sessions", "contained", "handoff", "contained_rate", "handoff_rate", "user_messages", "fallbacks", "fallback_rate", "csat", "abandoned", "drop_off", "flows", "by_day"}` |

### AI, voice and «Conectar con IA» (Connect with AI)

| Route | Body | Response |
|---|---|---|
| `POST /api/ai/status` | `{"ai": config}` or `{"agent": id}`; with `ai.prompt`, it also tests the model | `{"ok", "models", "recommended", "provider", "model", "model_ready", "error", "hint", "reply"?, "ms"?}` |
| `POST /api/ai/pull` | `{"ai": config, "model"}` | `{"ok", "started", "model"}`. Downloads an Ollama model in the background. |
| `GET /api/ai/progress` | — | `{model: {"status", "completed", "total", "done", "error"}}` |
| `GET /api/voice/status` | — | `{"stt", "tts", "hint", "errors", "models"}` |
| `POST /api/voice/speak` | `{"text"` (up to 2000 characters), `"language"}` | The audio (`audio/wav`), not JSON. Phrases already generated come from the cache. |
| `GET /api/connect` | — | `[{"id", "name", "installed", "connected", "manual"}]`, one per assistant. |
| `POST /api/connect` | `{"client": "claude-code" \| "codex" \| "claude-desktop" \| "cursor"}` | `{"ok", "message", ...}`. With users, creates an API key for the requester. |
| `POST /api/connect/remove` | `{"client"}` | `{"ok", "message"}` |

`/api/connect*` only responds if the request's `Host` is `127.0.0.1:<port>` or `localhost:<port>` (otherwise 403)
and the `POST`s require `Content-Type: application/json` (otherwise 415).

### Everything else

- `GET /`: the UI (`web/index.html`).
- `GET /static/{nombre}.js`: the UI scripts and `widget.js`.
