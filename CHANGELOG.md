# Changelog

All notable changes to Parla are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres to
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## Unreleased

### Added

- Per-agent conversation retention (`retention_days`, or `PARLA_RETENTION_DAYS` for all agents), applied at startup
  and every hour; uploaded files are never deleted by it.
- Audit log of write operations (logins, users, keys, agents, versions, secrets, files, channels, Inbox), with an
  owner-only «Auditoría» page and `GET /api/audit`; entries older than `PARLA_AUDIT_DAYS` (365) are deleted.
- Optional masking of personal data in stored conversations (`pii_redaction`: emails, phones, Luhn-valid cards,
  DNI/CUIT and other long numbers, CBU/CVU and IBAN). The live turn still sees the real values.
- «Privacidad y datos» panel in the agent's «Ajustes» for retention and masking.
- Rasa 3.x project importer (classic and CALM) from the UI, API, CLI and MCP, with a warnings report
  ([docs/migrate-from-rasa.md](docs/migrate-from-rasa.md)).
- WhatsApp (Cloud API) and Telegram channels: signed webhooks, native buttons, file uploads, Inbox replies
  delivered to the channel, and a «Canales» screen ([docs/channels.md](docs/channels.md)).
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

- The agent step counted each turn twice.
- The TTS cache key.

## 0.9.0

First public version: no-code bot builder with embeddings kNN + CRF NLU, flows, optional local AI (Ollama), local
voice (faster-whisper + piper), versions and environments, inbox, analytics, HTTP API, web widget and MCP server.
Not tagged yet; compare links will be added from the first tagged release.
