# Changelog

All notable changes to Parla are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres to
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## Unreleased

### Added

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

## 0.9.0

First public version: no-code bot builder with embeddings kNN + CRF NLU, flows, optional local AI (Ollama), local
voice (faster-whisper + piper), versions and environments, inbox, analytics, HTTP API, web widget and MCP server.
Not tagged yet; compare links will be added from the first tagged release.
