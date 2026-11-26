# How Parla compares

**English** · [Español](comparison_es.md)

This page compares Parla with other conversational AI and chatbot platforms: Rasa Pro / Rasa Studio, NiCE
Cognigy, Kore.ai, Google Dialogflow CX, Microsoft Copilot Studio, Botpress and Voiceflow. It is meant to help
you pick the right tool. It is not a benchmark, and every product listed here has many more features than fit
on one page.

The research is **as of November 2026**. Vendors change pricing and features often, so check the linked sources
before you decide. Where a vendor does not publish something, this page says so rather than guessing.

## Parla in one paragraph

Parla is an Apache-2.0 open-source chatbot builder that runs locally on a CPU: one Python process (stdlib HTTP
server), JSON files and a SQLite file on disk and a no-code web interface in vanilla JavaScript. Its NLU uses embeddings and
nearest neighbour (`google/embeddinggemma-300m` via fastembed), a CRF for entities, and lists, regex and date
rules. Flows have many step types (questions, HTTP requests, conditions, subflows, file sending, functions,
handoff, AI steps). An LLM is optional (local Ollama by default, or any OpenAI-compatible endpoint, self-hosted or hosted), and so is local voice
(faster-whisper for speech-to-text, piper for text-to-speech), including an interruptible voice call in the test
chat. It ships an MCP server with 27 tools, versions with `staging` / `production` and rollback, users, roles and
API keys, a per-agent secret vault, an inbox for human handoff, analytics, a "to teach" queue for unrecognized
phrases and conversation replay against another version. Channels today are the HTTP API (`/api/v1`) and an
embeddable web widget. It can be deployed with Docker, docker-compose, Kubernetes or k3s. The interface is in
English, Spanish and Portuguese. Parla has a **no-open-core pledge**: every feature stays open source.

## Summary table

| | Parla | Rasa Pro / Studio | NiCE Cognigy | Kore.ai | Dialogflow CX | Copilot Studio | Botpress | Voiceflow |
|---|---|---|---|---|---|---|---|---|
| License | Apache-2.0, no open core | Commercial license; free Developer Edition [1][2] | Proprietary [3] | Proprietary [5] | Proprietary (Google Cloud service) [7] | Proprietary (Microsoft service) [9] | Proprietary cloud; v12 (AGPLv3 / proprietary) sunset [11] | Proprietary SaaS [13] |
| Self-hosting | Yes (single process, Docker, K8s, k3s) | Yes (Helm / Kubernetes) [2] | Offered per vendor materials; quote-based [3] | Private cloud / on-premise on enterprise tier, per third-party guides [5] | No (Google Cloud) | No (Microsoft cloud) | Not for new deployments (v12 sunset) [11] | Not mentioned on pricing page; hosted on Voiceflow [13] |
| Pricing | Free | Not published [2] | Quote-based; a third-party guide cites a $43,080 list price [3] | Quote-based / not published [5] | Per request, published (e.g. $0.007 text, $0.012 with playbooks) [7] | Credit packs ($200 / 25,000 credits / month) or pay-as-you-go ($0.01 / credit) [9] | Free tier + published paid plans [12] | Usage-based for agencies; businesses on request [13] |
| Local / offline models | Yes: embeddings, CRF and optional LLM all run locally | Configurable LLM providers; self-hosted models possible [2] | Not publicly documented as fully offline | Not publicly documented as fully offline | No (Google models) | No (Microsoft / Azure models) | No | No |
| Voice | Local STT/TTS, interruptible voice call in test chat; phone calls via Twilio or jambonz (DTMF, transfer) | Yes, via AudioCodes, Jambonz, browser [1] | Yes, Voice Gateway [3] | Yes | Yes (audio billed per second) [7] | Yes, real-time voice [10] | Voice channel on enterprise plan, per third-party guide [12] | Yes (voice and chat) [13] |
| Channels | HTTP API, web widget, WhatsApp, Telegram, phone (Twilio, jambonz) | Many connectors | Many | Many | Many integrations | Teams, web and Microsoft channels | Many | Many |
| MCP | MCP server (27 tools) to build/test/publish bots | MCP tools server for IDEs (beta, 3.16) [1] | MCP tools in agents; MCP server endpoint (experimental) [4] | Not verified in official docs | Not verified in official docs | MCP tools in agents (GA) [10] | MCP in the ADK CLI, per third-party sources [12] | MCP tools in agents + hosted MCP server [14] |
| Analytics | Containment, handoffs, fallbacks, CSAT, drop-off | Built-in dashboard in Studio 1.16 [1] | Yes | Yes | Yes (Google Cloud) | Yes | Yes | Yes (observability) [13] |
| Testing | Self-evaluation, confusion matrix, test chat, replay against another version | Yes (E2E tests) | Simulator [3] | Yes | Yes | Yes | Yes | Yes |

"Yes" without a source means the feature is widely documented by the vendor but was not re-checked for this page.

## Per-platform notes

### Rasa Pro and Rasa Studio

Rasa Pro uses the CALM approach (LLM-driven understanding with deterministic business logic) and Rasa Studio adds
a no-code editor. Rasa 3.16 (March 2026) added a local MCP tools server so IDE copilots can read, validate and
train a Rasa project, and Studio 1.16 (April 2026) added a built-in analytics dashboard with containment and CSAT
[1]. Voice runs through AudioCodes and Jambonz. It is deployed on Kubernetes with Helm. Rasa Pro requires a
commercial license; the free Developer Edition is limited (about 1,000 conversations per month according to one
guide), and production pricing is not published [2].

**Choose Rasa if** you need a mature, large-scale platform with CALM, telephony partners and enterprise support,
and a commercial license fits your budget. **Choose Parla if** you are looking for an open-source Rasa
alternative that is lighter (one process, no database server), fully Apache-2.0 and runs on a laptop.

### NiCE Cognigy

Cognigy, now part of NiCE, is an enterprise contact-center AI platform with a Voice Gateway, many channels and a
simulator for testing [3]. It supports MCP tools inside agents and, since 2026.5, an experimental MCP server
endpoint [4]. Pricing is custom; one third-party guide cites a list price of $43,080 [3].

**Choose Cognigy if** you run a large contact center and need native telephony, CCaaS integration and vendor
support. **Choose Parla if** you want an on-premise bot with no license cost and full control of the code.

### Kore.ai

Kore.ai is an enterprise platform for conversational and agentic AI. In May 2026 it announced Artemis, an
AI-native platform for enterprise multi-agent systems [6]. Pricing is quote-based and not published; third-party
estimates vary widely [5]. Third-party sources describe private cloud / on-premise options on its top tier [5].
We could not confirm MCP support in Kore.ai's own documentation.

**Choose Kore.ai if** you need a broad enterprise suite (multi-agent orchestration, many channels, governance)
with vendor support. **Choose Parla if** your scope is a focused bot you want to run yourself.

### Google Dialogflow CX

Dialogflow CX (part of Google Cloud Conversational Agents) offers visual flows and generative playbooks [8]. Its
pricing is published and per request: for example $0.007 per text request without generative AI, $0.012 per
request with playbooks, and audio billed per second [7]. It runs only on Google Cloud.

**Choose Dialogflow CX if** you are already on Google Cloud and want a managed service with Google models and
telephony. **Choose Parla if** you need a self-hosted Dialogflow alternative where conversations never leave
your servers.

### Microsoft Copilot Studio

Copilot Studio builds agents for Microsoft 365, Teams and the web, with multi-agent orchestration (including
A2A) and real-time voice [10]. MCP servers can be added to agents as tools (generally available) [10]. Licensing
is based on Copilot Credits: packs of 25,000 credits at $200 per month, or pay-as-you-go at $0.01 per credit [9].

**Choose Copilot Studio if** your organization lives in Microsoft 365 and wants agents inside Teams and Power
Platform. **Choose Parla if** you need something independent of a cloud tenant, running offline.

### Botpress

Botpress is a cloud platform with a visual editor and a large integration ecosystem. The older open-source
Botpress v12 (dual-licensed AGPLv3 / proprietary) has been officially sunset and is no longer available for new
deployments [11]. Third-party sources report a free tier plus paid plans, a pricing change in May 2026, and MCP
support in its ADK CLI [12].

**Choose Botpress if** you want a hosted, LLM-centric builder with many ready-made integrations. **Choose Parla
if** you want a self-hosted, open-source Botpress alternative.

### Voiceflow

Voiceflow is a hosted platform for designing voice and chat agents, with team roles and observability. Its
pricing page offers usage-based billing for agencies and on-request pricing for businesses, and production runs
are hosted on Voiceflow [13]. Agents can use MCP tools from internet-reachable MCP servers, and Voiceflow also
runs a hosted MCP server for managing agents [14].

**Choose Voiceflow if** you want a polished collaborative design tool and a hosted runtime. **Choose Parla if**
you need everything on your own machine, including local voice.

## What Parla does not have yet

Being honest about gaps matters more than a long feature list. These are on the roadmap (see
[ROADMAP.md](ROADMAP.md)):

- **Channels:** HTTP API, web widget, WhatsApp (Cloud API), Telegram and phone. No Messenger, Teams or Slack yet.
- **Telephony:** inbound calls through Twilio or jambonz (speech recognized by the provider, request/response turns,
  no outbound campaigns or audio streaming); no AudioCodes or contact-center (CCaaS) connectors.
- **Horizontal scaling:** Parla is a single process with files on disk; it is designed for a small server.
- **SSO** (SAML / OIDC).
- **End-to-end conversation test suites** (replay against another version exists; full test suites do not).
- **Observability exports** (OpenTelemetry, Prometheus or similar).

If any of these is a hard requirement today, one of the platforms above is probably a better fit.

## When Parla is a good fit

- You want an **on-premise voice bot** or chatbot that works without a GPU and without sending data to a cloud.
- You want a **free, open-source conversational AI platform** with no paid tier and no open-core features.
- You build bots for Spanish-speaking users and want Rioplatense date parsing and an interface in Spanish.
- You want an AI assistant (Claude Code, Codex, Cursor) to build and test the bot for you through MCP.

## Sources

1. Rasa, "Behind the release notes: product updates, spring 2026" — https://rasa.com/blog/behind-the-release-notes-product-updates-spring-2026
2. Macha, "Rasa AI: complete guide" (third-party) — https://www.getmacha.com/blog/rasa-ai-complete-guide
3. Macha, "Cognigy: complete guide" (third-party) — https://www.getmacha.com/blog/cognigy-complete-guide
4. Cognigy, "Automated Knowledge Synchronization and More with Cognigy.AI 2026.5" — https://www.cognigy.com/product-updates/2026.5 ; MCP in agents — https://www.cognigy.com/product-updates/model-context-protocol-mcp
5. eesel AI, "Kore.ai pricing 2026" (third-party) — https://www.eesel.ai/blog/kore-ai-pricing
6. Help Net Security, "Kore.ai unveils AI-native platform for enterprise multi-agent systems" (May 2026) — https://www.helpnetsecurity.com/2026/05/22/kore-ai-unveils-ai-native-platform-for-enterprise-multiagent-systems/
7. Google Cloud, Conversational Agents (Dialogflow CX) pricing — https://cloud.google.com/products/conversational-agents/pricing
8. Google Cloud, Dialogflow CX playbooks — https://docs.cloud.google.com/dialogflow/cx/docs/concept/playbook
9. Microsoft, Copilot Studio licensing guidance — https://www.microsoft.com/licensing/guidance/microsoft-copilot-studio ; Copilot Credits overview — https://learn.microsoft.com/microsoft-copilot-studio/copilot-credits-overview
10. Microsoft, "New and improved: multi-agent orchestration, connected experiences" — https://www.microsoft.com/en-us/microsoft-copilot/blog/copilot-studio/new-and-improved-multi-agent-orchestration-connected-experiences ; "MCP is now generally available in Microsoft Copilot Studio" — https://www.microsoft.com/en-us/microsoft-copilot/blog/copilot-studio/model-context-protocol-mcp-is-now-generally-available-in-microsoft-copilot-studio
11. Botpress, "Botpress v12 (and self-hosted versions)" — https://botpress.com/docs/learn/guides/advanced/v12 ; repository — https://github.com/botpress/v12
12. eesel AI, "Botpress pricing 2026" (third-party) — https://www.eesel.ai/blog/botpress-pricing ; Agents Index, Botpress (third-party) — https://agentsindex.ai/botpress.md
13. Voiceflow, pricing — https://www.voiceflow.com/pricing
14. Voiceflow docs, MCP tool — https://docs.voiceflow.com/documentation/build/tools/mcp-tool ; MCP overview — https://www.voiceflow.com/docs/mcp/overview

## Trademarks and corrections

All product and company names are trademarks or registered trademarks of their respective owners. They are used
here only to identify the products being compared. Parla is not affiliated with, endorsed by or sponsored by any
of these companies.

Found something outdated or wrong? Corrections are welcome: please open an issue or a pull request with a link to
the source.
