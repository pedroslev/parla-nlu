# Costs per conversation

**English** · [Español](costs_es.md)

Parla measures what every conversation uses (model tokens, audio minutes, characters spoken, phone minutes,
messages sent) and multiplies it by a price table you control. That gives the cost of each conversation, of each
resolved conversation and of each day, so you can compare it with what a closed vendor charges per conversation.

**These are estimates.** Your providers' invoices are the source of truth: free tiers, volume discounts, taxes,
rounding (Twilio bills whole minutes) and per-country rates are not modeled.

## What is measured

| Kind | Unit | Where it comes from |
|---|---|---|
| `llm_input`, `llm_output` | tokens | What the provider reports on each call: Anthropic `usage` (cache writes counted as input), OpenAI-compatible `usage`, Gemini `usageMetadata` (thinking tokens count as output), Ollama `prompt_eval_count` / `eval_count`. |
| `llm_cached` | tokens | Cached input when the provider reports it (Anthropic `cache_read_input_tokens`, OpenAI `prompt_tokens_details.cached_tokens`, Gemini `cachedContentTokenCount`). |
| `llm_compute` | CPU hours | Ollama's `prompt_eval_duration + eval_duration`, to price your own hardware. |
| `asr` | minutes | Local Whisper: the decoded audio. Providers: the duration they report (Deepgram `metadata.duration`, Google `totalBilledTime`, OpenAI `whisper-1`), otherwise the audio's own length. |
| `tts` | characters | Each synthesized sentence; pre-generated fixed phrases served from the cache are free and not counted. |
| `phone` | minutes | Twilio `CallDuration` / jambonz `duration` on the status callback when the call ends, `inbound` or `outbound`. |
| `phone_call` | calls | Each outbound call placed. |
| `whatsapp` | messages | Bot replies (`service`) and templates (`template:<category>`, from the template's `category` in the catalog). |
| `telegram` | messages | Bot replies (the Bot API is free). |
| `turn` | turns | Each conversation turn, to spread a fixed server cost (embeddings and the CRF run locally and have no per-call price). |

Usage is stored raw, per agent, day, conversation, channel, provider, model and kind (SQLite table `usage`), and a
summary per turn goes into the conversation record (`usage` on the user message and on the conversation). The turn
never waits for this: writes go through the database writer queue without waiting for the commit.

The cost is computed **when you read it** with the current prices, so changing a price also changes the past
("estimated with the current prices").

## Prices

**Reports → Costs → Prices** shows the table; only the **owner** can change it (`PUT /api/prices`, audited). It is
stored in `DATA/prices.json`. Each row is a `kind`, a `provider`, a `model` (exact, or a pattern like `aura-2-*` or
`*`) and a `price` per unit: per 1M tokens, per minute, per 1M characters, per message, per call, per CPU hour. An
empty price means "unknown": that usage is listed under **Missing price** («completá el precio») and not added.

Built-in defaults only where the price was checked on the provider's official page (each row has its `source` and
`checked` date, 2026-11-26):

| Provider | Model | Price |
|---|---|---|
| Anthropic | `claude-opus-5-5` | $4 in / $0.20 cache read / $20 out per 1M tokens |
| Anthropic | `claude-sonnet-5-5` | $2 / $0.10 / $10 |
| Anthropic | `claude-haiku-5-5` | $0.10 / — / $0.50 (prompts ≤100K tokens) |
| OpenAI | `gpt-6-luna`, `gpt-6.1-terra`, `gpt-6.2-sol` | $0.10/$0.01/$0.50 · $1/$0.05/$5 · $2/$0.10/$10 |
| Gemini | `gemini-3.8-flash` | $0.75 / $0.075 / $3.75 until 2026-12-31 ($1.50 / $0.15 / $7.50 from 2027) |
| Gemini | `gemini-3.5-flash-lite`, `gemini-3.1-pro-preview` | $0.30/$0.03/$2.50 · $2/$0.20/$12 (≤200K) |
| OpenAI | `gpt-4o-mini-transcribe` | $0.003 per minute |
| Deepgram | `nova-3` / `aura-2-*` | $0.0043 per minute / $30 per 1M characters |
| ElevenLabs | `scribe_v3` / `eleven_flash_v2_5`, `eleven_turbo_v2_5` / `eleven_multilingual_v2` | $0.20 per hour / $40 / $80 per 1M characters |
| Twilio | inbound / outbound | $0.0085 / $0.014 per minute (US local) |
| Local | Ollama tokens, Whisper, Piper | $0 (price the hardware with `llm_compute`) |
| Telegram | | $0 |

Left empty on purpose: Google Cloud Speech-to-Text and Text-to-Speech, OpenAI TTS (priced per audio token, not per
character), jambonz (your carrier's rate), WhatsApp (Meta charges per delivered message, by country and category;
service messages have 1,000 free per number per month), Ollama CPU hours and the Parla server.

**Your own infrastructure.** `llm_compute` / `ollama` is your cost per CPU hour. `turn` / `parla` is your Parla
server's monthly cost: it is spread over all the turns of that month (all agents).

## Reports and API

**Reports → Costs** (same filters as the rest of Reports): total, per day, average / median / p95 per
conversation, cost per resolved conversation (the total divided by the conversations that were not handed to a
person), by channel, by kind (AI, speech to text, text to speech, phone, messaging, engine), by provider and model,
the most expensive conversations (click to open them) and **Export CSV**. A conversation in **Conversations** shows
its own breakdown; a campaign shows its cost; filtering Reports by an A/B experiment and variant shows that
variant's cost, and the experiment results compare the average cost per conversation ([experiments.md](experiments.md)).

```sh
curl -s 'http://127.0.0.1:8000/api/v1/bots/clinica/costs?from=2026-11-01&to=2026-11-30&group=channel' \
  -H 'Authorization: Bearer parla_xxxxxxxx'
```

Analyst or above. Details in [api.md](api.md#get-apiv1botsbotcosts). Prometheus: `parla_usage_total` and
`parla_cost_total` ([observability.md](observability.md)).

## Comparing with a vendor

1. Run a representative week (or replay real conversations as tests) and read **cost per resolved conversation**.
2. Compare it with the vendor's price per conversation or per session for the same channel; add the vendor's
   platform fee if it has one, and add your Parla server cost (`turn`) on this side.
3. Compare like with like: a "conversation" for Meta, for Dialogflow (per request) and for a contact-center vendor
   (per resolution or per minute) are different units.

## Caveats

- Estimates: provider invoices win. Prices change; check the `checked` date and update the table.
- Usage outside a conversation (test suite runs, voice previews in the editor) is counted in the metrics
  but not per conversation. Phone audio played by Parla (`tts: parla`) counts for the agent, not for the call.
- Deleting a conversation, or the retention period, removes its id from the usage table; the day's totals stay.
- Speech recognized by Twilio or jambonz themselves (`<Gather>`) is billed by them and not measured here.
