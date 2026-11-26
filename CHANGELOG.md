# Changelog

All notable changes to Parla are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres to
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## Unreleased

### Fixed

- Reports no longer fails to render on an agent without classifications (the costs panel was used before it existed).
- The handoff AI summary no longer runs inside the turn (it could add up to 8 s): the reply goes out with the
  deterministic summary, the AI summary is computed in the background and the `handoff.requested` webhook waits up
  to 10 s for it (otherwise it is sent with the deterministic one). SIP headers and Flex tasks use the deterministic
  summary.
- «Repetir» no longer takes longer questions: «¿cómo puedo pagar?» matched the «¿cómo?» example and answered with an
  empty reply. The message has to be almost the closest example (one extra word at most, politeness aside), and
  with nothing to repeat it's handled as usual ([docs/concepts.md](docs/concepts.md#system-flows)).
- «Corregir un dato»: an address with a number («Corrientes 1234») to a free-text question was taken as a new
  quantity, looping «Listo, lo cambié» + the same question. On free-text questions it corrects only with a cue
  («mejor», «no, …», «en realidad»…).
- The CSAT survey only follows a flow that did something (asked, called a service or function, sent a file,
  classified, ended the conversation…), not a greeting.
- «Para enseñar» pre-selects an intent only when it's close (similarity ≥ 0.7); otherwise «Elegí una intención…».
- `examples/pizzeria.json`: threshold 0.55 -> 0.7, new «Reclamo» (hands off) and «Estado del pedido» intents and three
  more tests. Training warns when the threshold is below 0.65.
- UI: "phrase" everywhere in English for training phrases; site chat and channel toggles are switches; copy buttons
  show the check mark only after copying; the Inbox stacks the list above the conversation when the center is narrow
  (it used to squeeze it next to the list); the Try-it header fits at 360 px; JSON `null` in the API docs is code; changing only `#/agent/section` switches
  section without reloading; the audit page doesn't open for non-owners, even from its hidden link.

### Added

- **A/B experiments.** `/api/agents/{id}/experiments` (owner/editor write, analyst read; audited): 2 to 4 published
  versions with weights on an environment, optional channel filter and goal (flow, intent or classification). New
  conversations get a variant from `sha256(experiment id + sessionId)` (the same on every replica) and keep that
  version; sessions, `events` responses and webhook payloads carry `experiment` and `variant`. Results per variant
  (conversations, resolved, handoff, fallback, goal, CSAT, cost, turns, latency) with two-proportion z-tests and
  Welch's t-tests, Bonferroni, CIs and a minimum-sample warning, no SciPy; never picks a winner on its own — stopping
  with `winner` deploys it. `GET /api/v1/bots/{bot}/experiments/{eid}/results`; Reports, sessions and costs filter by
  `experiment`/`variant`; `parla_experiment_conversations_total`. UI in **Versions** and **Reports**
  ([docs/experiments.md](docs/experiments.md)).
- **Secrets encrypted at rest.** With `PARLA_SECRET_KEY`, `agents/<id>.secrets.json` is AES-256-GCM (`cryptography`
  pinned in `requirements.txt`) with an HKDF-SHA256 subkey and the agent id as associated data; tampering is detected;
  plaintext files are read and encrypted on the next write; `PARLA_SECRET_KEY_OLD` + `python -m parla.vault rotate`
  for rotation. Without a key, plaintext as before and a warning in **Secrets**. Helm `secrets.encrypt: true` (default)
  generates and keeps the key when none is given ([docs/security.md](docs/security.md#secrets-encryption-at-rest)).
- **Postgres and several replicas (high availability).** `PARLA_DATABASE_URL=postgresql://…` (psycopg 3,
  `requirements-postgres.txt`, `scripts/setup.sh --postgres`, included in the Docker image) moves conversations,
  logins, audit, usage, campaigns, queues and SSO state to Postgres, with a connection pool and versioned migrations
  run at startup under an advisory lock; SQLite stays the default and unchanged. With several replicas: turns of a
  conversation are serialized with advisory locks, live events cross replicas over `LISTEN/NOTIFY`, API sends,
  reminders and webhooks are claimed with `FOR UPDATE SKIP LOCKED`, a leader (advisory lock, automatic failover)
  runs campaigns, retention and timeouts, and login lockout, API rate limits, WhatsApp/Telegram dedupe, phone
  silence counters and `/after` plans are shared. `PARLA_SECRET_KEY` signs audio URLs for every replica. Training and
  publishing lock per agent; other replicas reload the new model. `python -m parla.migrate sqlite-to-postgres`
  copies an existing `parla.db`. `GET /readyz` (database check, leader). Metrics `parla_db_pool_connections`,
  `parla_cluster_leader`, `parla_cluster_events_total`. Helm: `replicaCount > 1`/HPA with `database`, `secretKey` and
  a ReadWriteMany volume (enforced), RollingUpdate, PodDisruptionBudget, per-pod models volume; Kustomize overlay
  `deploy/k8s-ha`; Compose `postgres` profile; CI runs the whole suite on Postgres plus a two-replica test
  ([docs/deployment.md](docs/deployment.md#postgres-and-high-availability), [docs/kubernetes.md](docs/kubernetes.md#high-availability)).

- Inbound media on WhatsApp and Telegram: files are downloaded (16 MB, allowed types only), stored per conversation
  (served only to users who can see the agent's conversations, deleted with the conversation), voice notes are
  transcribed with the agent's ASR and answered, locations/contacts arrive as slot-friendly text, `media` is available
  in steps (`{{ media.url }}`), optional image description with `ai.vision`. Inbox and Conversations show thumbnails,
  an audio player and file links ([docs/channels.md](docs/channels.md#how-each-thing-is-sent)).
- WhatsApp templates from the Inbox and `POST …/sessions/{sid}/messages` outside the 24-hour window (`template`
  field, `409 template_required` with the catalog otherwise) and `GET /api/v1/bots/{bot}/outbound[/{id}]` send status
  ([docs/outbound.md](docs/outbound.md#send-status-api)). In-app API docs: real-time voice WebSocket, send status, media.

- Real-time voice over WebSocket ([docs/ai-and-voice.md](docs/ai-and-voice.md#real-time-voice)): streaming ASR
  (Deepgram live with partials and endpointing; otherwise a VAD that sends each utterance to the usual ASR), TTS from
  the first sentence of the reply (streaming HTTP for OpenAI, Deepgram Aura and ElevenLabs) and true barge-in (audio
  cleared, the AI stream of that turn cut, the interruption recorded in the history). Phone `channels.phone.mode:
  "stream"`: Twilio Media Streams (signed upgrade, `clear`, DTMF) and jambonz `listen` (L16, `killAudio`, DTMF), with
  transfer/hang-up after the stream ([docs/channels.md](docs/channels.md#real-time-stream-mode)). The test chat's
  **Call (voice)** and the widget microphone use `/api/v1/bots/{bot}/voice/ws` when available
  ([docs/api.md](docs/api.md#real-time-voice-websocket)). Metrics `parla_voice_e2e_latency_seconds`,
  `parla_voice_tts_first_byte_seconds`, `parla_voice_barge_ins_total`. Turn mode stays the default.
- Costs per conversation ([docs/costs.md](docs/costs.md)): usage measured per turn and per conversation (LLM input,
  output and cached tokens by provider and model, Ollama compute time, ASR minutes, TTS characters, phone minutes from
  Twilio/jambonz status callbacks, outbound calls, WhatsApp service and template messages, Telegram, engine turns),
  stored raw in a SQLite `usage` table (written through the DB writer queue, never waited on) and in the
  conversation record; an owner-editable price table in `DATA/prices.json` with verified defaults (source and
  `checked` date) and empty prices where unverified; a **Costs** panel in Reports (total, per day, per conversation
  avg/median/p95, per resolved conversation, by channel, kind and provider, most expensive conversations, CSV), the
  cost in the conversation viewer and the campaign detail; `GET /api/v1/bots/{bot}/costs`, `usage` in
  `GET …/sessions/{sid}`, `GET|PUT /api/prices`; metrics `parla_usage_total` and `parla_cost_total`. Costs are
  recalculated with the current prices.
- In-app API docs: the contact-center routes (`…/handoff`, `…/messages`, `…/lookup`), webhook events and signature,
  WebSocket/SSE and the costs route.
- External contact centers ([docs/contact-centers.md](docs/contact-centers.md)): per-agent `handoff.mode`
  (`inbox`, `external`, `both`) with a timeout that returns the conversation to the bot or closes it; outbound
  webhooks (`handoff.*`, `conversation.*`, `message.*`, `csat.received`, `campaign.finished`) signed with
  `Parla-Signature`, delivered from a SQLite queue in order per conversation, retried for ~24 h and dead-lettered,
  with a delivery log, test and retry in Channels → Handoff; contact center API `POST …/sessions/{sid}/handoff`
  (accept, release with `data`/`flow`, close), `POST …/sessions/{sid}/messages` (widget, WhatsApp with the 24 h rule,
  Telegram) and `GET …/lookup`; `integration`-scoped API keys; phone transfer with `X-Parla-*` / `User-to-User` SIP
  headers (Twilio `<Sip>`, jambonz `dial.headers`), Twilio `<Number>` and Twilio Flex `<Enqueue><Task>`; a handoff
  summary (AI if enabled, otherwise intent + slots). The Inbox shows external handoffs read-only. Metrics
  `parla_webhook_deliveries_total`, `parla_webhook_delivery_duration_seconds`, `parla_queue_depth{queue="webhooks"}`.
- UI sweep in CI (`make ui-test`, `tests/ui/run.py`): every role × language × agent × section in headless Chrome
  ([docs/development.md](docs/development.md#ui-sweep)).

## 0.9.0 — 2026-11-26

First tagged release (`v0.9.0`): images `ghcr.io/pedroslev/parla-nlu:0.9.0` / `:latest`.

### Added

- Event-driven core ([docs/development.md](docs/development.md#server-architecture)): an asyncio HTTP/1.1 server
  (keep-alive, same limits and guards, `uvloop` if installed) replaces the thread-per-connection server; turns of one
  conversation run in order and different conversations in parallel; embeddings are micro-batched across
  conversations (`PARLA_EMBED_WORKERS`, `PARLA_EMBED_THREADS`, `PARLA_EMBED_BATCH`, `PARLA_EMBED_WAIT_MS`); SQLite
  reads use a connection per thread and writes go through one writer thread with group commit. On a 10-core M4:
  10 concurrent conversations 50 -> ~270 turns/s, 50 concurrent 27 -> ~360, 1,000 concurrent with 0 errors.
- WebSocket `GET /api/v1/bots/{bot}/ws` and SSE `.../sessions/{sid}/stream`, `/api/agents/{id}/inbox/stream` and
  `/api/agents/{id}/campaigns/stream` ([docs/api.md](docs/api.md#push-websocket-and-sse)), fed by an in-process
  event bus. The widget, the Inbox and Campaigns use them and fall back to polling.
- AI streaming: knowledge answers, the generative fallback and the `agent` step send `delta` events from Ollama,
  OpenAI-compatible servers, Anthropic (`messages.stream`) and Gemini (`streamGenerateContent`); guardrails run on
  the full text and send `replace` when they change it.
- Metrics `parla_connections`, `parla_queue_depth`, `parla_embed_*_total`, `parla_db_*_total`; `tests/perf/load.py`
  and a perf smoke in CI.

- Helm chart (`deploy/helm/parla`): single replica with Recreate, hardened pod, every `PARLA_*` setting as values with
  secrets via `existingSecret` (OIDC secret as a file), Ingress publishing only `/api/v1/`, `/files/` and
  `/static/widget.js` unless `exposeAdmin`, optional ServiceMonitor, NetworkPolicy (egress limited to DNS + HTTPS to
  public addresses), nightly backup CronJob with a consistent SQLite snapshot and a restore script, optional Ollama
  with model pre-pull, embedding model preload, values schema ([docs/kubernetes.md](docs/kubernetes.md)).
- Outbound messaging: the bot writes first ([docs/outbound.md](docs/outbound.md)). `POST /api/v1/bots/{bot}/outbound`
  (owner/editor; `channel` `whatsapp`, `telegram`, `phone` or `web`, `to`, `data`, `flow`, `template`) starts a
  production conversation with the same session id an inbound message would use, the data preloaded in the slots and
  the flow; replies continue it. WhatsApp tracks the 24-hour window per conversation and picks free-form or an
  approved template on its own (catalog in `channels.whatsapp.templates`, slots mapped to `{{1}}`, `{{2}}`…; the
  flow runs when the person replies), translates Meta error codes and retries rate limits, and uses the `statuses`
  webhook (`sent`, `delivered`, `read`, `failed`). Outbound calls through Twilio (`Calls.json`, `TWILIO_ACCOUNT_SID`)
  or jambonz (`/v1/Accounts/{sid}/Calls`, `JAMBONZ_API_KEY`, `JAMBONZ_ACCOUNT_SID`, `channels.phone.api_url`,
  `application_sid`) from `channels.phone.from`, matched with a `?o=` token. **Campaigns** (**Operate → Campaigns**):
  CSV import with column mapping, dedupe and opt-out filtering (up to 10,000 recipients, `PARLA_CAMPAIGN_MAX`),
  schedule and time zone, rate (default 20/minute, up to 50/second), quiet hours, draft/running/paused/done/canceled,
  up to 3 attempts with backoff, a queue in `parla.db` that survives restarts, per-recipient statuses, conversions
  (classification, intent, flow or CSAT), CSV export and a `?campaign=` filter on sessions and reports. A `remind`
  step schedules a reminder (`after` or `at`, `flow` or `text`, `template`). Opt-out keywords («STOP», «BAJA»,
  `agent.outbound.optout_keywords`) with a confirmation, plus manual opt-outs. Audit actions `outbound.send`,
  `campaign.*`, `optout.add` / `optout.remove` with masked numbers; metrics `parla_outbound_messages_total` and
  `parla_campaign_recipients`; retention and `pii_redaction` cover recipients.
- Observability, standard library only and off by default ([docs/observability.md](docs/observability.md)).
  **Prometheus metrics** at `GET /metrics` with `PARLA_METRICS=1` (bearer `PARLA_METRICS_TOKEN`, or loopback only
  without one): HTTP requests and latency by route template, turns by agent/channel/environment, intent outcomes
  (matched, answer, system, fallback), NLU, LLM (by provider, with token counts), ASR/TTS, HTTP step, function and
  knowledge search latency by outcome, handoffs, CSAT histogram, active sessions, test suite runs and `parla_info`.
  **OpenTelemetry traces** over OTLP/HTTP JSON (`PARLA_OTEL_ENDPOINT` or the standard `OTEL_EXPORTER_OTLP_*`,
  `OTEL_SERVICE_NAME`, `OTEL_RESOURCE_ATTRIBUTES`) from a bounded background exporter that drops instead of
  blocking: HTTP server span → `parla.turn` → `nlu.classify` / `nlu.extract`, `flow.run`, `http.step`,
  `function.run`, `agent.step`, `chat {model}` (gen_ai.* attributes and token usage), `knowledge.search`, `asr`,
  `tts`, `channel.message`, `phone.turn`. Incoming W3C `traceparent` continues the trace and `http` steps send it on.
  No message text, slot values or secrets in metrics or spans; `PARLA_OTEL_CONTENT=1` adds the turn's text with vault
  secrets and personal data masked. `PARLA_LOG_FORMAT=json` logs one line per request with `trace_id`/`span_id`.
  Optional `observability` compose profile (Jaeger all-in-one + Prometheus), commented `ServiceMonitor` and scrape
  annotations for Kubernetes, and a Grafana dashboard in `deploy/observability/`.
- Bring-your-own-key providers, chosen per agent (local stays the default). **AI** (`ai.provider`): `openai`
  (api.openai.com, or any compatible server with `url` as before), `openai_compatible`, `anthropic` (Claude through
  the official `anthropic` SDK, optional `requirements-providers.txt`: structured outputs, effort `low`, server-side
  refusal fallback, refusal and `max_tokens` handled as errors) and `gemini` (`generateContent` REST with
  `responseJsonSchema`). **Speech** (`voice.asr` / `voice.tts`): OpenAI, Deepgram (nova-3 with `keyterm`, Aura-2),
  ElevenLabs (Scribe with `keyterms`, Flash TTS) and Google Cloud (Speech-to-Text with `speechContexts`,
  Text-to-Speech). Keys come from the agent's vault by name (defaults `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`,
  `GEMINI_API_KEY`, `DEEPGRAM_API_KEY`, `ELEVENLABS_API_KEY`, `GOOGLE_API_KEY`) and are masked in every error. TTS is
  always WAV, so the browser call mode, the widget and phone `tts: "parla"` (now the agent's voice) keep working; the
  prewarm cache is keyed by provider and voice. Provider picker and a **Voz** panel (voice list, sample playback,
  3-second transcription test, privacy notice) in the **IA** screen; `POST /api/voice/voices`; `agent`/`voice` on
  `POST /api/voice/speak`; `scripts/setup.sh --providers`, `make setup-providers`, Docker `INSTALL_PROVIDERS=1`
  ([docs/ai-and-voice.md](docs/ai-and-voice.md)).
- Tools in the AI `agent` step: `tools` with `function`, `http` (like an http step, typed `params`, fixed host) and
  `mcp` entries (mandatory allow-list), agent-level `mcp_servers` (Streamable HTTP only, `headers_secret` from the
  vault, `tools/list` cached 5 minutes), and `max_tool_calls` / `time_budget` limits. Parla's own JSON protocol
  (`{"tool", "args"}`), so it works with Ollama and OpenAI-compatible endpoints; args are validated, results are
  masked, truncated and framed as data, broken output is retried once. Calls show in the trace, in the chat result
  (`tools`) and as history events. **Herramientas** section in the agent step editor, **Servidores MCP** in the
  **IA** screen, and `POST /api/agents/{id}/mcp/tools` ([docs/ai-and-voice.md](docs/ai-and-voice.md#tools-in-the-agent-step)).
- Single sign-on with OIDC (Keycloak, Entra ID, Google Workspace, Okta, Authentik, Auth0): authorization code +
  PKCE, ID token signature (RS256/384/512) checked against the provider's JWKS with no new dependency, roles mapped
  from a groups/roles claim (`PARLA_OIDC_ROLE_CLAIM`, `PARLA_OIDC_ROLE_MAP`, `PARLA_OIDC_DEFAULT_ROLE`), an
  SSO-only mode with a local break-glass owner (`PARLA_OIDC_ONLY`), provider logout, an **SSO** badge in
  **Users** and `login.sso` audit entries. Configured with `PARLA_OIDC_*` variables; the client secret can come from
  a file (`PARLA_OIDC_CLIENT_SECRET_FILE`) ([docs/sso.md](docs/sso.md)).
- Telephony: inbound phone calls through Twilio Programmable Voice (TwiML, `X-Twilio-Signature`) or jambonz (verbs
  JSON, `Jambonz-Signature` and/or HTTP basic). One conversation per call (`call-<CallSid>`, channel `phone`), speech
  or DTMF each turn, buttons announced as a keypad menu («Marcá 1 para…», es/en/pt), digits as answers for
  numeric questions, barge-in, voice-friendly text (no emojis, Markdown or URLs), a notice instead of files,
  silence reprompts, an `end` step hangs up, handoff transfers to `handoff_to` (number or SIP URI), and optional
  Parla (piper) voice from HMAC-signed URLs that expire in 10 minutes. **Phone** card in **Channels**; calls in the
  Inbox are transferred instead of typed to ([docs/channels.md](docs/channels.md#phone-calls-twilio-and-jambonz)).
- English and Portuguese (pt-BR) UI: every screen of the web interface in English, Spanish or Portuguese
  (`web/static/i18n.js`, `t()` with the Spanish text as key), chosen next to the theme picker (the ⋯ menu, the home
  screen or the sign-in screen; `?lang=en` also works) and remembered per browser. `PARLA_LANG` sets the install
  default for users who haven't picked one (`scripts/setup.sh --lang en|es|pt` writes it to `.env`). Server errors
  and warnings shown in the UI follow the UI language (`Accept-Language`, `parla/i18n.py`); logs stay in Spanish.
  The web widget takes its labels from the bot's main language (`data-lang`). Bots whose main language is English
  get English defaults for the system flows. `tests/test_i18n.py` fails on any UI string without an English
  translation.
- Bot-building best practices as Agent Skills in `skills/` (`parla-build-bot`, `parla-nlu-design`,
  `parla-flow-design`, `parla-integrations`, `parla-testing-and-release`, `parla-migrate-from-rasa`) with a verified
  example bot, served by the MCP server as `parla://skills` resources and referenced by the `build_bot` prompt;
  `make skills-install` links them into Claude Code ([docs/skills.md](docs/skills.md),
  [docs/best-practices.md](docs/best-practices.md)).
- OpenAI-compatible model endpoints for the AI features (`ai.provider: "openai"`): vLLM, llama.cpp, LM Studio,
  LocalAI, OpenAI, Azure OpenAI, Groq, OpenRouter. API key from the agent's vault (`ai.api_key_secret`), JSON mode
  with a prompt-only fallback, error messages with the key masked, **Test connection** and a privacy warning
  for non-local URLs ([docs/ai-and-voice.md](docs/ai-and-voice.md#openai-compatible-endpoints)).
- Conversation test suites (**Tests**): expected conversations stored in the agent (`tests`), run from the UI, the
  API (`POST /api/agents/{id}/tests/run`), the MCP (`run_tests`) and the command line
  (`python -m parla.bottests`, with GitHub Actions annotations); **Save as test** from a conversation or the
  test chat; publishing to production runs the suite first and stops on failures unless forced
  ([docs/testing-bots.md](docs/testing-bots.md)).
- Per-agent conversation retention (`retention_days`, or `PARLA_RETENTION_DAYS` for all agents), applied at startup
  and every hour; uploaded files are never deleted by it.
- Audit log of write operations (logins, users, keys, agents, versions, secrets, files, channels, Inbox), with an
  owner-only **Audit log** page and `GET /api/audit`; entries older than `PARLA_AUDIT_DAYS` (365) are deleted.
- Optional masking of personal data in stored conversations (`pii_redaction`: emails, phones, Luhn-valid cards,
  DNI/CUIT and other long numbers, CBU/CVU and IBAN). The live turn still sees the real values.
- **Privacy and data** panel in the agent's **Settings** for retention and masking.
- Rasa 3.x project importer (classic and CALM) from the UI, API, CLI and MCP, with a warnings report
  ([docs/migrate-from-rasa.md](docs/migrate-from-rasa.md)).
- WhatsApp (Cloud API) and Telegram channels: signed webhooks, native buttons, file uploads, Inbox replies
  delivered to the channel, and a **Channels** screen ([docs/channels.md](docs/channels.md)).
- Apache-2.0 license, `NOTICE` file and a "no open core" pledge: every feature stays in the open-source project.
- `CONTRIBUTING.md` (setup, tests, style, DCO sign-off), `CODE_OF_CONDUCT.md` (Contributor Covenant 2.1) and
  `SECURITY.md` (private vulnerability reporting through GitHub).
- GitHub issue and pull request templates, and Dependabot for pip, GitHub Actions and Docker.
- CI on Python 3.11 and 3.12 (lint plus the full test suite, with the embedding model cached).
- Multi-arch (amd64/arm64) container images on `ghcr.io/pedroslev/parla-nlu`, with `-voice` variants.
- Docker image, Docker Compose (with optional Ollama) and Kubernetes/k3s manifests in `deploy/`, with a rewritten
  deployment guide.
- English documentation, with the Spanish versions kept as `*_es.md`; a comparison with other conversational AI
  platforms and a public roadmap.

### Security

- Vault secrets are masked in flow error messages shown to chat users.
- Public widget calls are limited to the web channel and production, cannot preload slots and get no trace.
- Only owners can add or change function code while functions are enabled.
- Host allowlist (`PARLA_HOSTS`) against DNS rebinding, which also lets the admin UI run behind a domain.
- Request body size caps, rejection of negative `Content-Length`, 30 s socket timeout.
- Slot values are URL-encoded in HTTP steps and CR/LF is rejected in headers.
- Agent ids are validated in paths; the support role gets a trimmed agent view.
- Generic 500 errors, `Secure` cookie behind HTTPS, bounded login lockout.
- Deleting an agent also removes its secrets file; safe knowledge links; random UUID widget session ids.
- Login sessions are stored as SHA-256 hashes; `parla.db` is created with permissions 600.

### Changed

- Local voice: a pool of `PARLA_VOICE_WORKERS` model sets instead of one global lock; training locks per agent;
  `users.json` is read without a lock (cached by mtime); the outbound queue wakes on new work instead of every second.

- Conversations, login sessions and the audit log are stored in a SQLite database (`DATA/parla.db`, WAL) instead
  of `agents/<id>.sessions/*.json`. Existing folders are imported on startup and renamed to
  `<id>.sessions.migrated` (never deleted). Backups must now include `parla.db`; see
  [docs/deployment.md](docs/deployment.md#backups).
- Login sessions survive a server restart.
- Performance: cached agent index, session records and published versions; per-snapshot NLU index and query
  embedding cache; single-flight TTS prewarm; atomic JSON writes; model and training locks.

### Fixed

- Marking a date entity in a phrase (`[mañana](fecha)`) made the answer «mañana» look ambiguous, so the bot kept
  re-asking; training no longer warns that a date entity is «marked 0 times».
- Rasa import: CALM conditions with bare slots (`slots.a and slots.b`) became CEL that failed at runtime; a bare
  slot now means «has a value».
- The agent step counted each turn twice.
- The TTS cache key.

## Before 0.9.0 (untagged)

First public version: no-code bot builder with embeddings kNN + CRF NLU, flows, optional local AI (Ollama), local
voice (faster-whisper + piper), versions and environments, inbox, analytics, HTTP API, web widget and MCP server.
Not tagged yet; compare links will be added from the first tagged release.
