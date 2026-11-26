# Roadmap

**English** · [Español](ROADMAP_es.md)

Where Parla is heading, grouped by how soon. It is a plan, not a promise of dates: priorities move with what users
need. Everything listed here will land in the open-source project under Apache-2.0; there is no paid edition that
holds features back.

Want to help or need something sooner? Open an issue or comment on an existing one; see
[CONTRIBUTING.md](../CONTRIBUTING.md). For how Parla compares with other platforms today, see
[comparison.md](comparison.md).

## Shipped recently

- **Observability**: Prometheus metrics at `/metrics` (requests, turns, fallback rate, NLU, LLM, voice, HTTP steps,
  functions, handoffs, CSAT, active sessions), OpenTelemetry traces over OTLP/HTTP with GenAI attributes and W3C
  trace context, and JSON request logs. Standard library only, off by default, no conversation content unless you
  opt in. See [observability.md](observability.md).
- **Bring-your-own-key providers**: the AI can use OpenAI, Claude (Anthropic), Google Gemini or any OpenAI-compatible
  endpoint, and voice can use OpenAI, Deepgram, ElevenLabs or Google Cloud for transcription and text-to-speech
  (also for the phone's Parla voice). Keys stay in the vault; local stays the default. See [ai-and-voice.md](ai-and-voice.md).
- **Tools in the AI agent step**: the `agent` step can call functions, HTTP APIs and allow-listed tools from MCP
  servers (Parla as an **MCP client**, Streamable HTTP), with a per-message call limit and time budget. See
  [ai-and-voice.md](ai-and-voice.md#tools-in-the-agent-step).
- **OIDC single sign-on**: sign in with Keycloak, Entra ID, Google Workspace, Okta, Authentik or Auth0, with roles
  mapped from the provider's groups and an optional SSO-only mode. See [sso.md](sso.md).
- **Telephony**: inbound phone calls through Twilio Programmable Voice or jambonz (open source, self-hostable),
  with speech and DTMF input, keypad menus for buttons, barge-in, transfer to a person and optional Parla (piper)
  voice. See [channels.md](channels.md#phone-calls-twilio-and-jambonz).
- **English and Portuguese UI**: the whole interface, server messages and the web widget in English, Spanish or
  Portuguese (pt-BR), chosen per user (next to the theme picker: home screen, ⋯ menu or sign-in screen), with an
  install default in `PARLA_LANG` (`scripts/setup.sh --lang en|es|pt`); bots whose main language is English get
  English system-flow defaults. See
  [CONTRIBUTING.md](../CONTRIBUTING.md#translations) to add a language.
- **WhatsApp channel** (WhatsApp Business Cloud API) and **Telegram channel**, with buttons, files and Inbox
  replies. See [channels.md](channels.md).
- **Rasa project importer**: classic and CALM Rasa 3.x projects become Parla agents, with a warning for anything
  not converted. See [migrate-from-rasa.md](migrate-from-rasa.md).
- **OpenAI-compatible model endpoints**: the AI features can use any OpenAI-compatible API (vLLM, llama.cpp,
  LM Studio, OpenAI, Azure OpenAI, Groq, OpenRouter), with the key in the vault. Ollama stays the default. See
  [ai-and-voice.md](ai-and-voice.md#openai-compatible-endpoints).
- **Conversation test suites**: expected conversations stored in the bot, run from the UI, the API, the MCP and the
  command line (GitHub Actions included), and before every publish to production. See
  [testing-bots.md](testing-bots.md).
- **SQLite storage** for conversations (`parla.db`), with automatic migration from the old JSON files, and
  **login sessions that survive a restart**. See [deployment.md](deployment.md#where-the-data-lives).
- **Conversation retention** per agent and an **audit log** of who changed what. See
  [security.md](security.md#audit-log).
- **PII redaction**: mask emails, phone numbers, IDs, cards and bank accounts in saved conversations. See
  [concepts.md](concepts.md#retention-and-personal-data).

## Next

- **Outbound campaigns**: start conversations proactively (reminders, notifications).

## Later

- **Horizontal scaling and Postgres**: several replicas on shared storage, with Postgres as an alternative to
  SQLite.
- **A/B experiments** between flow or bot versions.

## Already there

For reference, what Parla does today: no-code builder, embeddings + CRF NLU, flows with many step types, optional
LLM (local or your own key), voice (local or your own key), versions with `staging`/`production`, users and roles, OIDC single sign-on, secret vault, inbox, analytics,
HTTP API, web widget, MCP server, agent-step tools (MCP client), Prometheus metrics and OpenTelemetry traces, Docker and Kubernetes. See the [README](../README.md#features).
