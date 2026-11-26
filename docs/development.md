# Development

**English** · [Español](development_es.md)

## Requirements and dependencies

Python 3.11 or newer (`scripts/setup.sh` looks for `python3.13`, `3.12`, `3.11` or `python3`, or the one you pass in
`PYTHON=`). Few dependencies, on purpose: the HTTP server is the standard library one (`http.server`), with no
framework. Agents, versions and users are JSON files; conversations, login sessions and the audit log go in a
SQLite file (`parla.db`, with the standard library's `sqlite3`).

| Package (`requirements.txt`) | What for |
|---|---|
| `fastembed` (+ `onnxruntime`), `numpy` | Phrase vectors with `google/embeddinggemma-300m` (~1.2 GB, stored in `data/models/embeddings` or in `PARLA_EMBED_CACHE`). |
| `python-crfsuite` | Learned entities (CRF). |
| `cel-python` | CEL expressions in `{{ }}`, `set`, `if` and `saves`. |
| `pypdf` | Knowledge base PDFs. |
| `mcp` | The MCP server. |
| `faster-whisper`, `piper-tts` (`requirements-voice.txt`) | Voice, optional. Requires `ffmpeg` on the system. |

The AI talks to Ollama over HTTP with `urllib` (`llm.py`), no SDK. Node.js is only needed for JavaScript functions.

## Commands

| Command | What it does |
|---|---|
| `scripts/setup.sh [--voice] [--ollama]` | Creates `.venv` and installs the dependencies; `--voice` adds voice, `--ollama` pulls `qwen2.5:0.5b` if Ollama is installed. |
| `make setup` / `make setup-voice` | Same as `scripts/setup.sh` / `scripts/setup.sh --voice`. |
| `make run` (or `.venv/bin/python app.py [port]`) | Opens Parla at `http://127.0.0.1:8000` (`PORT=8080 make run` for another port). |
| `make test` (or `.venv/bin/python tests/run_all.py [name ...]`) | The tests. |
| `make ui-test` (or `.venv/bin/python tests/ui/run.py`) | The UI sweep in headless Chrome (see below). |
| `make mcp` | The MCP server over HTTP at `:8001/mcp`. For stdio: `.venv/bin/python mcp_server.py`. |
| `make docker-build` / `make docker-run` | Builds the `parla:local` image (`VOICE=1` adds voice) and runs it on `127.0.0.1:8000`. See [deployment.md](deployment.md). |
| `make clean-pyc` | Deletes the `__pycache__` folders. |

## Environment variables

All are optional. Nothing loads `.env` automatically: export them in your shell.

| Variable | Default | What for |
|---|---|---|
| `PARLA_DATA` | `<repo>/data` | Agents, versions, conversations, files, secrets, `users.json` and voice models. |
| `PARLA_USERS` | `$PARLA_DATA/users.json` | Users file. |
| `PARLA_HOST` | `127.0.0.1` | Address the server listens on (the Docker image uses `0.0.0.0`). |
| `PARLA_HOSTS` | empty | Extra names (`host[:port]`) used to reach Parla behind a proxy. See [deployment.md](deployment.md). |
| `PARLA_RETENTION_DAYS` | empty | Days to keep conversations with no activity, for agents without `retention_days`. Empty or `0`: forever. |
| `PARLA_AUDIT_DAYS` | `365` | Days to keep the audit log. |
| `PARLA_SECURE_COOKIE` | empty | `1` adds `Secure` to the session cookie (it is also added automatically if a `PARLA_HOSTS` proxy signals HTTPS with `X-Forwarded-Proto`). |
| `PARLA_EMBED_CACHE` | `<repo>/data/models/embeddings` | Where the vector model is stored. It doesn't follow `PARLA_DATA`, so the tests don't download it every time. |
| `PARLA_FUNCTIONS` | `1` | `0`, `false`, `no` or `off` disable agent functions. |
| `PARLA_PUBLIC_URL` | empty | Public HTTPS address for the WhatsApp/Telegram webhooks (an agent's `channels.public_url` wins). See [channels.md](channels.md). |
| `PARLA_WHATSAPP_API`, `PARLA_TELEGRAM_API` | `https://graph.facebook.com/v21.0`, `https://api.telegram.org` | Base URL of those APIs. Only for tests (`tests/test_channels.py` points them to a fake server). |
| `PARLA_TWILIO_API` | `https://api.twilio.com` | Base URL of Twilio's REST API for outbound calls. Only for tests (`tests/test_outbound.py`). |
| `PARLA_CAMPAIGN_MAX` | `10000` | Maximum recipients per campaign, for agents without `outbound.max_recipients`. |
| `PARLA_WHISPER` | `base` | faster-whisper model (`tiny` if the machine is slow). |
| `PARLA_LANG` | browser's language | Default interface language (`en`, `es` or `pt`); `scripts/setup.sh --lang` writes it to `.env`. |
| `PARLA_URL` | `http://127.0.0.1:8000` | (MCP) where Parla is. |
| `PARLA_TOKEN` | empty | (MCP) API key sent as `Authorization: Bearer`. |
| `PARLA_MCP_ALLOWED_HOSTS` | empty | (MCP with `--http`) public domains accepted behind a proxy. |

## Code

| File | What it contains |
|---|---|
| `app.py` | Entry point: starts `parla/server.py` (`main`). |
| `parla/__init__.py` | `ROOT`, `DATA` (`PARLA_DATA`) and `__version__`. |
| `parla/server.py` | NLU (`classify`, `extract`, `parse`, `read_answer`), training (`train`, `self_check`), versions (`publish`, `deploy`, `target`, `diff`), templates (`cel`, `render`), the engine (`handle`, `run`, `begin`), conversations on disk (`converse`), `api_v1`, `audio_event`, the Bandeja (Inbox) (`human`) and the HTTP `Handler`. |
| `parla/auth.py` | Users, roles, cookies, keys; `handle` (routes `/api/auth`, `/api/users`) and `guard` (before every `/api/`). |
| `parla/aserver.py` | The asyncio HTTP/1.1 server: keep-alive, per-conversation queues, WebSocket (`/ws`) and SSE (`/stream`). Runs each request through `server.Handler` in a thread pool. |
| `parla/bus.py` | In-process pub/sub (`publish` from any thread, `subscribe` from the loop): topics `session:`, `inbox:`, `campaign:`. |
| `parla/db.py` | The SQLite database `parla.db` (WAL): per-thread read connections and one writer thread with group commit; tables `sessions`, `logins`, `audit`, campaigns; `q`, `connect`, `audit`, `audit_list`. |
| `parla/pii.py` | Masking personal data in what is stored (`pii_redaction`): `categories`, the rules and the Luhn / mod-97 checks. |
| `parla/brain.py` | AI on top of the engine: `rescue_intent`, `fill_slot`, `understand`, `side_question`, `answer`, `fallback`, `agent_turn`. No function raises. |
| `parla/llm.py` | Ollama / OpenAI-compatible / Anthropic / Gemini client: `chat` (with `stream=` for live tokens), `settle`, `status`, `pull`. |
| `parla/knowledge.py` | `extract` (text, HTML, URL, PDF), `chunks`, `search`. |
| `parla/dates.py` | `extract`: rule-based natural language dates. |
| `parla/files.py` | Files for the `file` step: `save`, `listing`, `find`, `read`, `delete`. |
| `parla/insights.py` | `unrecognized` and `analytics`, computed on the fly over the conversations. |
| `parla/runner.py` | `run_function`: functions in a separate process. |
| `parla/telemetry.py` | Observability: `count`, `observe`, `gauge` and `render` (Prometheus), `span` (OpenTelemetry, OTLP/HTTP JSON exporter thread), `log_request` (JSON logs). See [observability.md](observability.md). |
| `parla/vault.py` | Per-agent secrets: `put`, `delete`, `names`, `values`, `mask`. |
| `parla/voice.py` | `transcribe`, `speak` and `prewarm` (cache of fixed phrases). |
| `parla/connect.py` | “Connect to AI”. |
| `parla/mcp_server.py` | MCP server: format validator (`validate`), format guide and tools. |
| `web/index.html` | The UI (JS with no build step): editor, test chat and voice call. Each large section lives in `web/static/*.js`. |
| `web/static/voice.js` | Dictation, read aloud and the call (local WebRTC + voice activity detector). |
| `web/static/files.js`, `sessions.js`, `functions.js`, … | Files for the `file` step; conversations (re-run as a test, continue as that customer); functions (editor with syntax highlighting, examples and testing); and the rest of the sections. |
| `web/static/audit.js` | The **Audit log** page, owner only (`#/auditoria`). |
| `web/static/widget.js` | The widget, with no dependencies, in a Shadow DOM. |

On disk (`PARLA_DATA`): `agents/<id>.json` (the draft), `<id>.model.json` and `<id>.crfsuite` (the trained model),
`<id>.versions/`, `<id>.files/`, `<id>.secrets.json`, `users.json`, `parla.db` (conversations, login sessions and
audit log) and `models/` (voice and audio cache). On startup, `migrate_sessions` imports any old
`agents/<id>.sessions/` folder into `parla.db` and renames it to `<id>.sessions.migrated`; `cleanup` (at startup
and every hour) applies the retention.

## Server architecture

```
socket ─► aserver (event loop) ─► per-conversation queue ─► thread pool: server.Handler (auth, limits, route)
                                                                     ├─► embeddings: micro-batch queue ─► N ONNX callers
                                                                     ├─► SQLite: reads on a per-thread connection,
                                                                     │   writes ─► writer thread (group commit)
                                                                     └─► bus.publish ─► WebSocket / SSE subscribers
```

- **Loop**: one asyncio loop owns every connection. Hot paths stay in the loop (`/static/*.js` from memory, WS/SSE
  framing); everything else runs the existing `Handler` code unchanged in `PARLA_THREADS` threads.
- **Queues**: turns of the same bot + `sessionId` wait in a FIFO `asyncio.Lock` that is deleted when empty, so one
  conversation is serial and different ones are parallel. Embedding requests from all conversations are batched
  (`_jobs` in `server.py`); SQLite writes go to one writer that commits whatever is queued in one transaction.
  `q()` returns after the COMMIT; a crash before it loses only unacknowledged writes (`tests/test_aserver.py`).
- **Bus**: `save_session` publishes the stored record; WS/SSE send what's after the client's cursor. During a turn
  `converse` sets `llm.STREAM.sink` only if someone listens, so streaming costs nothing otherwise.
- **Measuring**: `tests/perf/load.py` (not in `run_all`; CI runs a 10 s smoke). The embedding model is the
  ceiling; see [deployment.md](deployment.md#performance-and-tuning).

## How the engine works

A conversation's state (`st`) is a dictionary: `slots`, `flow` (current flow), `pc` (step), `stack` (subflows and
interruptions), `waiting` (slot being asked), `lang`, `buttons`, `clarify`, `hint` (option just explained),
`csat_waiting`, `handoff`, `agent` (state of the AI step), `last_bot` (for «repetí») and `recent` (context for the
AI). It is stored inside the conversation's record (`record` column of the `sessions` table in `parla.db`, through
`load_session` / `save_session`).

`begin(agent, st, data)` starts it: copies `data` to the slots with the same name, picks the language and runs the
flow with trigger `__start__`.

`handle(agent, st, text)` is one turn, in this order:

1. If a person is handling it (`handoff.active`), the bot doesn't speak.
2. Tapped button, answer to the CSAT survey, answer to «¿quisiste decir…?» (did you mean…?).
3. `parse`: intent + entities. Entities fill their slots (while waiting for an answer, only the slot being asked).
   Two different values for the slot being asked = ambiguous answer.
4. System intents (`__cancel__`, `__repeat__`, `__handoff__`): with the agent's threshold, or with
   `max(threshold, 0.75)` if it is waiting for a value (0.92 if the question is free text), never below 0.65 and
   never if the message already answered or a button was tapped.
5. A flow with `interrupts: "always"` cuts off whatever is waiting.
6. If there is an active `agent` step, it's the AI's turn. If it is waiting for a value: side question
   (`side_question`), corrections, `fill: "ai"`, `also`, option just explained, `read_answer` (by meaning),
   `brain.understand` (with AI), interruption by another intent (it is stacked and then comes back) or «No reconocí
   ese dato» (I didn't recognize that).
7. If it wasn't in a flow: AI rescue, clarification on a tie, flow by intent or fallback (knowledge → AI follow-up
   question → `fallback`).
8. `run`, and when it finishes, CSAT or «¿algo más?» (anything else?).
9. `turn` builds the result (`messages`, `buttons`, `replies`, `nlu`, `slots`, `trace`, `via`, `sources`, …).

`run(agent, st, nlu, text, out, trace)` executes steps until `done`, `wait`, `handoff` or `error`. Before that,
`flatten` turns nested `if`s into a flat list with labels and jumps. Limits: 200 consecutive steps (`MAX_STEPS`) and
5 stacked flows (`MAX_DEPTH`). A failing step doesn't bring down the server: the chat shows «⚠ Hay un problema en el
flujo…» (There is a problem in the flow…) and the conversation stops.

Pluggable modules (AI, dates, secrets, reading by meaning) are called through `hook()`: if they blow up, the bot
keeps going as if they weren't there.

`converse` is the bridge between the API/chat and `handle`: it loads the version the conversation started with,
uses its trained model, and stores the history (up to 500 messages) and the classifications.

`store` saves the agent and, if piper voices have been downloaded, launches `voice.prewarm` in a thread with the
phrases from `spoken_texts`.

## Adding a step type

Example: a `wait` step that says «un momento» (one moment).

1. **Engine** (`parla/server.py`): add the name to `STEP_NAMES` and a branch in `run()`:
   ```python
   elif kind == "wait":
       out.append(render(localized(step, st), ctx) or "Un momento…")
   ```
   If the step has to wait for the person, return `"wait"`; if it ends the conversation, `"done"`. If it says a
   fixed text, add it to `spoken_texts` so the voice call has it pre-generated.
2. **MCP validator** (`parla/mcp_server.py`): add it to `STEP_TYPES`, validate its fields in `validate()` and
   document it in the format guide (`GUIDE`).
3. **UI** (`web/index.html`): add it to `STEP_MENU` and build its editor.
4. **Test** (`tests/test_app.py`): a conversation that uses it and an `assert` on what it says.
5. **Docs**: [concepts.md](concepts.md#step-types).

## Tests

```sh
make test                                # all of them: tests/run_all.py
.venv/bin/python tests/run_all.py app mcp   # some, by name
.venv/bin/python tests/test_app.py       # a single one, by hand
```

They are scripts with `assert`, no framework: if something doesn't hold, the script fails at that `assert`.
`run_all.py` runs each one in its own process, shows the time and marks voice or AI tests as «saltado» (skipped)
when what they need is missing (that doesn't count as a failure). `tests/support.py` sets up a temporary data folder
and, for the tests that need it, starts its own copy of the server on a free port: they never touch your `data/`.

| File | Needs |
|---|---|
| `test_app.py` | Nothing: the engine with a fake NLU and toy vectors, no model or network. |
| `test_insights.py` | Nothing. |
| `test_connect.py` | Nothing (uses a temporary HOME and an empty `PATH`). |
| `test_knowledge.py` | The vector model. |
| `test_auth.py` | Nothing external: starts its own server with a temporary `users.json`. |
| `test_storage.py` | Nothing external: `parla.db`, the migration, retention, audit and masking; starts its own server twice on the same temporary data (logins survive the restart). |
| `test_ai.py` | Ollama for the part with a model; if it isn't there, skips it with a warning. Dates are always tested. |
| `test_voice.py` | The voice extras and `ffmpeg`; if missing, it is skipped. |
| `test_mcp.py` | The `mcp` package and the vector model: starts its own temporary Parla and tests the validator and the tools end to end. |

### UI sweep

`tests/ui/run.py` (not in `run_all`; CI runs it as its own job) starts a temporary Parla, creates an owner, an editor,
an analyst and a support user, imports both examples, trains, and leaves a few conversations (one handed off to a
person, a couple the bot didn't understand). Then `tests/ui/sweep.mjs` drives headless Chrome over CDP, one process
per role in parallel, through every language (es, en, pt) × agent × section in that role's menu, and fails on: JS
exceptions, console errors, HTTP ≥ 400, visible `[role=alert]` banners, «null»/«undefined»/«NaN»/«[object …]» on screen
(outside `<pre>`/`<code>`), Spanish UI words in en/pt, and a non-owner reaching the audit page. Agent content (phrases,
chat bubbles, bot texts) is excluded by marking its container with `data-content`: add it when a new view shows
what the bot or the user wrote. Needs Node 22+ and Chrome: `CHROME=/path/to/chrome` if it isn't in the usual place
(`google-chrome` on Linux); `LANGS=en` sweeps a single language.

## Style

- **Small functions** that do one thing and read top to bottom.
- **Comments in Spanish**, to explain the why, not the what. User-facing messages too, in Rioplatense Spanish
  (they're the keys that `web/static/i18n.js` and `parla/i18n.py` translate to English and Portuguese) and saying
  what to do («Revisá que los slots que usa existan» — check that the slots it uses exist).
- **The simplest thing that works**: standard library before a new dependency, JSON files before a database
  (conversations are the exception: they live in SQLite, still standard library), no abstractions nobody asked
  for.
- **`ponytail:` comments** when taking a shortcut with a known limit, naming the limit and how to improve it. Real
  examples from the code (kept in Spanish, as in the source):
  ```python
  # ponytail: un hilo por pedido (la IA y la voz tardan segundos); dos mensajes a la vez en la MISMA conversación
  # pueden pisarse: agregar un lock por sessionId si algún canal los manda en paralelo
  # ponytail: una conexión y un lock para todo el proceso (ThreadingHTTPServer); alcanza para un servidor.
  # Con mucho tráfico: una conexión por hilo (WAL ya deja leer mientras otro escribe)
  ```
  (One thread per request — AI and voice take seconds; two simultaneous messages in the SAME conversation can
  overwrite each other: add a lock per sessionId if some channel sends them in parallel. / One connection and one
  lock for the whole process — enough for one server; with heavy traffic, one connection per thread, since WAL
  already lets you read while another writes.)
  Find them with `grep -rn "ponytail:" parla web` to see the technical debt taken on.
- An error in an optional module (AI, voice, dates) never stops a conversation.
- All non-trivial logic leaves a test in `tests/`.
