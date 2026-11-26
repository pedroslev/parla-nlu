# Parla documentation

**English** · [Español](README_es.md)

| Document | Audience | Contents |
|---|---|---|
| [User manual](manual/README.md) | Non-technical users | The web interface step by step, organized by role. |
| [Getting started](getting-started.md) | Everyone | Your first bot, from zero to published. |
| [Concepts](concepts.md) | Everyone | Agent, intent, entity, slot, flow, step types, templates, system flows, what happens while it waits for an answer. |
| [Testing bots](testing-bots.md) | Everyone | Conversation test suites: format, **Save as test**, the publish gate, API, command line and GitHub Actions. |
| [HTTP API](api.md) | Developers | The public `/api/v1` API with `curl` examples, authentication and roles, and the internal API. |
| [WhatsApp and Telegram](channels.md) | Whoever publishes the bot | Connect a bot to WhatsApp (Cloud API) and Telegram, step by step, limits and security. |
| [External contact centers](contact-centers.md) | Whoever integrates the bot | Hand off to your own contact center: signed webhooks, the contact center API, SIP headers and Flex tasks, recipes for Genesys, Flex, Five9, Zendesk and Salesforce. |
| [A/B experiments](experiments.md) | Whoever runs the bot | Compare published versions with real traffic: setup, metrics, significance, how to run a good test, pitfalls. |
| [Costs per conversation](costs.md) | Whoever runs the bot | What each conversation costs: what is measured, the price table, reports and API, comparing with vendors, caveats. |
| [Outbound and campaigns](outbound.md) | Whoever publishes the bot | The bot writes first: outbound API, WhatsApp templates and the 24-hour window, outbound calls, CSV campaigns, reminders, opt-outs, consent. |
| [MCP and “Connect to AI”](mcp.md) | Everyone | Let Claude, Codex or Cursor build the bot for you. |
| [Skills for AI assistants](skills.md) | Everyone | Bot-building best practices as Agent Skills: what they are and how to install them in Claude Code, Claude Desktop, Codex or Cursor. |
| [Best practices](best-practices.md) | Everyone | A short guide to designing intents, entities, flows, integrations and tests that work. |
| [Local AI and voice](ai-and-voice.md) | Everyone | Embedding model, Ollama, what each AI feature does and its guardrails, voice and calls. |
| [Security](security.md) | Whoever installs it | Users, roles, keys, functions, what to do before exposing it. |
| [Single sign-on (OIDC)](sso.md) | Whoever installs it | Sign in with Keycloak, Entra ID, Google Workspace, Okta, Authentik or Auth0: variables, role mapping, per-provider steps, troubleshooting. |
| [Deployment](deployment.md) | Whoever installs it | Local, Docker, behind a proxy, every environment variable, backups. |
| [Kubernetes and Helm](kubernetes.md) | Whoever installs it | Helm chart, k3s quickstart, backups and restore, NetworkPolicy, production checklist. |
| [Observability](observability.md) | Whoever installs it | Prometheus metrics, OpenTelemetry traces, JSON logs: every metric, the span tree, Grafana, Jaeger, Tempo, Datadog, Honeycomb, privacy. |
| [Development](development.md) | Developers | Commands, environment variables, code, engine internals, how to add a step type, tests, style. |
| [FAQ](faq.md) | Everyone | Common questions. |
| [Migrating from Rasa](migrate-from-rasa.md) | Rasa users | Import a Rasa 3.x project (classic or CALM): what maps to what, what's not supported, UI, API, CLI and MCP. |
| [Comparison](comparison.md) | Everyone | Parla vs Rasa, Cognigy, Kore.ai, Dialogflow CX, Copilot Studio, Botpress and Voiceflow, with sources. |
| [Roadmap](ROADMAP.md) | Everyone | What's being built now, next and later. |
