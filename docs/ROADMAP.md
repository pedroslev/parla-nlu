# Roadmap

**English** · [Español](ROADMAP_es.md)

Where Parla is heading, grouped by how soon. It is a plan, not a promise of dates: priorities move with what users
need. Everything listed here will land in the open-source project under Apache-2.0; there is no paid edition that
holds features back.

Want to help or need something sooner? Open an issue or comment on an existing one; see
[CONTRIBUTING.md](../CONTRIBUTING.md). For how Parla compares with other platforms today, see
[comparison.md](comparison.md).

## Shipped recently

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

## Now (in progress)

- **English UI** (interface internationalization).

## Next

- **Telephony**: SIP / phone calls through Jambonz and Twilio, with DTMF input, on top of the existing local voice.
- **OIDC single sign-on** (Keycloak, Entra ID, Google, Okta and others).

## Later

- **Horizontal scaling and Postgres**: several replicas on shared storage, with Postgres as an alternative to
  SQLite.
- **Tools in the AI agent step**: let the `agent` step call external tools as an **MCP client**.
- **Observability**: OpenTelemetry traces and metrics export.
- **A/B experiments** between flow or bot versions.
- **Outbound campaigns**: start conversations proactively (reminders, notifications).

## Already there

For reference, what Parla does today: no-code builder, embeddings + CRF NLU, flows with many step types, optional
local LLM, local voice, versions with `staging`/`production`, users and roles, secret vault, inbox, analytics,
HTTP API, web widget, MCP server, Docker and Kubernetes. See the [README](../README.md#features).
