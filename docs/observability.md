# Observability

**English** · [Español](observability_es.md)

Parla can export **Prometheus metrics**, **OpenTelemetry traces** and **JSON request logs**. Everything is off by
default and uses only the standard library (`parla/telemetry.py`): there's no SDK to install. Metrics and traces
carry ids, intent and flow names, confidence, durations and statuses. They never carry what people write, slot
values or secrets, unless you turn on [content in traces](#privacy).

| Variable | Default | What for |
|---|---|---|
| `PARLA_METRICS` | off | `1` serves `GET /metrics` in the Prometheus text format (0.0.4). Off: `/metrics` answers 404. |
| `PARLA_METRICS_TOKEN` | empty | Bearer token for `/metrics`. Without a token, `/metrics` only answers on this machine (see [Access to /metrics](#access-to-metrics)). |
| `PARLA_OTEL_ENDPOINT` | empty | OTLP/HTTP base URL. Spans go to `{PARLA_OTEL_ENDPOINT}/v1/traces` as JSON. Empty: no traces. |
| `OTEL_EXPORTER_OTLP_ENDPOINT`, `OTEL_EXPORTER_OTLP_TRACES_ENDPOINT` | empty | Standard OpenTelemetry variables, used when `PARLA_OTEL_ENDPOINT` is empty (the `TRACES` one is a full URL). |
| `OTEL_EXPORTER_OTLP_HEADERS` (or `..._TRACES_HEADERS`) | empty | Headers for the collector, `key=value,key2=value2` (values URL-encoded), for example an API key. |
| `OTEL_SERVICE_NAME` | `parla` | `service.name` of the spans. `OTEL_RESOURCE_ATTRIBUTES` (`deployment.environment=prod,...`) adds more. |
| `OTEL_EXPORTER_OTLP_TIMEOUT` | `5000` | Milliseconds per export request. |
| `OTEL_SDK_DISABLED` | empty | `true` turns traces off even if an endpoint is set. |
| `PARLA_OTEL_INTERVAL` | `2` | Seconds between batches. |
| `PARLA_OTEL_CONTENT` | off | `1` adds the turn's text to the `parla.turn` span, masked (see [Privacy](#privacy)). |
| `PARLA_LOG_FORMAT` | empty | `json`: one JSON line per HTTP request on stderr, with `trace_id` and `span_id`. Empty: nothing changes. |

## Metrics

Durations are histograms in seconds (buckets 5 ms to 30 s). Every histogram also gives `_count` (calls) and `_sum`,
so "calls by outcome" is `rate(<name>_count{outcome="error"}[5m])`. `outcome` is `ok`, `error` or, for HTTP steps,
`http_error` (4xx/5xx) and `unreachable` (no connection, DNS, timeout).

| Metric | Type | Labels | Meaning |
|---|---|---|---|
| `parla_http_requests_total` | counter | `route`, `method`, `status` | HTTP requests. `route` is the template (`/api/v1/bots/{bot}/events`), never the raw path. |
| `parla_http_request_duration_seconds` | histogram | `route`, `method`, `outcome` | Request latency; `outcome="error"` for 5xx. |
| `parla_turns_total` | counter | `agent`, `channel`, `environment` | Conversation turns (test chat, API, widget, WhatsApp, Telegram, phone). |
| `parla_conversations_started_total` | counter | `agent`, `channel` | Conversations started with a `start` event. |
| `parla_intent_outcomes_total` | counter | `agent`, `outcome` | How each turn was understood: `matched` (an intent), `answer` (the answer to a question), `system` (cancel, repeat, handoff), `fallback`, `none` (a person is handling it). |
| `parla_nlu_duration_seconds` | histogram | `stage`, `outcome` | NLU latency: `classify` (intent) and `extract` (entities). |
| `parla_llm_request_duration_seconds` | histogram | `provider`, `outcome` | LLM calls (`ollama`, `openai`, `openai_compatible`, `anthropic`, `gemini`). |
| `parla_llm_tokens_total` | counter | `provider`, `type` | Tokens (`input`, `output`) when the provider reports them. |
| `parla_usage_total` | counter | `agent`, `kind`, `provider`, `unit` | Billable usage: `kind` is `llm_input`, `llm_output`, `llm_cached`, `llm_compute`, `asr`, `tts`, `phone`, `phone_call`, `whatsapp`, `telegram`, `turn` ([costs.md](costs.md)). `agent="none"` outside a conversation. |
| `parla_cost_total` | counter | `agent`, `kind`, `provider`, `currency` | The same usage priced with the price table at the moment it happened (unpriced usage and the spread server cost aren't counted; the Costs report recalculates with today's prices). |
| `parla_asr_duration_seconds` | histogram | `provider`, `outcome` | Speech to text (`local`, `openai`, `deepgram`, `elevenlabs`, `google`). |
| `parla_tts_duration_seconds` | histogram | `provider`, `outcome` | Text to speech. Cached fixed phrases aren't counted. |
| `parla_voice_e2e_latency_seconds` | histogram | `channel`, `asr`, `tts` | Real-time voice: end of the person's speech (including the end-of-turn silence) to the first audio byte sent back. Target < 1 s with streaming providers. |
| `parla_voice_tts_first_byte_seconds` | histogram | `provider` | Real-time voice: a sentence handed to TTS to its first audio byte. |
| `parla_voice_barge_ins_total` | counter | `channel` | Real-time voice: the person talked over the bot and it stopped. |
| `parla_http_step_duration_seconds` | histogram | `outcome` | `http` steps and HTTP tools of the agent step. |
| `parla_function_duration_seconds` | histogram | `language`, `outcome` | Function runs (steps and agent-step tools). |
| `parla_knowledge_search_duration_seconds` | histogram | `outcome` | Knowledge base searches. |
| `parla_experiment_conversations_total` | counter | `agent`, `experiment`, `variant` | Conversations assigned to an A/B experiment variant (counted only while the experiment runs; results come from the database). |
| `parla_handoffs_total` | counter | `agent`, `channel` | Conversations the bot handed to a person. |
| `parla_webhook_deliveries_total` | counter | `outcome` | Handoff webhook attempts: `delivered`, `retry` (will be retried), `dead` (no more retries). |
| `parla_webhook_delivery_duration_seconds` | histogram | | Webhook HTTP round trip (each attempt that got an answer or timed out). |
| `parla_csat_score` | histogram | `agent` | CSAT answers, buckets 1 to 5 (average: `_sum / _count`). |
| `parla_connections` | gauge | `kind` | Open connections: `http` (keep-alive), `ws`, `sse`, `voice` (real-time voice WebSockets). |
| `parla_queue_depth` | gauge | `queue` | `executor` (requests waiting for a thread), `inflight`, `sessions` (conversations with a turn running or queued), `bus_subscribers`, `db_write`, `embed`, `webhooks` (handoff webhook deliveries queued or sending). |
| `parla_embed_batches_total`, `parla_embed_items_total` | counter | | ONNX embedding calls and texts: items / batches = mean batch size. |
| `parla_db_commits_total`, `parla_db_statements_total` | counter | | SQLite group commits and the writes in them: statements / commits = mean group size. With Postgres: transactions and background (`later`) writes. |
| `parla_db_pool_connections` | gauge | `pool`, `state` | Postgres only: connections per pool (`queries`, `locks`) that are `open` and `idle`; `open - idle` are in use. Near `PARLA_DB_POOL` / `PARLA_DB_LOCKS` = raise them (and Postgres' `max_connections`). |
| `parla_cluster_leader` | gauge | | `1` on the replica that runs campaigns, retention and timeouts (always `1` with SQLite). The sum over pods should be 1. |
| `parla_cluster_events_total` | counter | `direction` | Bus events `sent` to and `received` from other replicas (`LISTEN/NOTIFY`). |
| `parla_active_sessions` | gauge | `agent` | Conversations not ended with activity in the last 30 minutes (computed on each scrape). |
| `parla_test_runs_total` | counter | `agent`, `outcome` | Test suite runs (`passed`, `failed`): UI, API, MCP and the publish gate. |
| `parla_outbound_messages_total` | counter | `channel`, `outcome` | Outbound messages and calls (API, campaigns, reminders): `sent`, `retry` (failed, will be retried), `failed`, `opted_out` (refused because the person opted out, or a new opt-out). |
| `parla_campaign_recipients` | gauge | `status` | Campaign recipients by status (`queued`, `sending`, `sent`, `delivered`, `read`, `replied`, `failed`, `opted_out`, `canceled`), computed on each scrape. See [outbound.md](outbound.md). |
| `parla_telemetry_dropped_total` | counter | `reason` | Spans dropped (`queue_full`, `export_failed`) or metric series refused (`too_many_series`). |
| `parla_info` | gauge | `version` | Always 1. |
| `process_start_time_seconds` | gauge | | Process start, Unix time. |

Label cardinality is bounded: `agent` is the agent id (8 hex characters), `channel` is one of `web`, `api`,
`whatsapp`, `telegram`, `phone`, `prueba` (the test chat) or `other`, routes are templates (ids become `{id}`,
`{bot}`, `{session}`, `{campaign}`…: `/api/agents/{id}/campaigns/{campaign}/start`), and Parla stops creating
new series after 5,000 (counted in `parla_telemetry_dropped_total{reason="too_many_series"}`).

Useful queries:

```promql
# fallback rate per agent, last 15 minutes
sum by (agent) (rate(parla_intent_outcomes_total{outcome="fallback"}[15m]))
  / sum by (agent) (rate(parla_intent_outcomes_total[15m]))
# p95 latency of the conversation API
histogram_quantile(0.95, sum by (le) (rate(parla_http_request_duration_seconds_bucket{route="/api/v1/bots/{bot}/events"}[5m])))
# LLM errors per provider
sum by (provider) (rate(parla_llm_request_duration_seconds_count{outcome!="ok"}[5m]))
# estimated spend per agent, last 24 h
sum by (agent, currency) (increase(parla_cost_total[1d]))
# average CSAT today
sum(increase(parla_csat_score_sum[1d])) / sum(increase(parla_csat_score_count[1d]))
```

### Readiness and the leader

`GET /readyz` (no token) answers `{"ok": true, "database": "sqlite"|"postgres", "leader": true|false}` with 200, or
503 when the database doesn't answer: the Helm chart uses it as the readiness probe, so a pod that loses Postgres
leaves the Service until it reconnects. With several replicas, `leader` (and `parla_cluster_leader`) tells which
pod runs the singleton jobs; after the leader dies another one reports `true` within `PARLA_LEADER_CHECK` seconds.

### Access to /metrics

- `PARLA_METRICS` unset: `/metrics` is 404.
- `PARLA_METRICS=1` and `PARLA_METRICS_TOKEN` set: it needs `Authorization: Bearer <token>`, from anywhere. Use this
  for Docker, Kubernetes or any Prometheus on another host.
- `PARLA_METRICS=1` without a token: only from this machine, meaning the connection comes from loopback **and** the
  `Host` is `127.0.0.1`, `localhost` or `[::1]`. A domain in `PARLA_HOSTS` is not enough on purpose: a proxy on the
  same machine would forward anybody's request from loopback.

`/metrics` isn't under `/api/`, so it doesn't need a user session or an API key, and it's not in the audit log. If
your proxy publishes everything, block `/metrics` there or set the token.

### Prometheus

```yaml
scrape_configs:
  - job_name: parla
    metrics_path: /metrics
    authorization:
      type: Bearer
      credentials_file: /etc/prometheus/parla-token     # the same value as PARLA_METRICS_TOKEN
    static_configs:
      - targets: ["parla.example.internal:8000"]
```

On Kubernetes with the Prometheus Operator, [`deploy/k8s/servicemonitor.yaml`](../deploy/k8s/servicemonitor.yaml) is
a commented `ServiceMonitor` that reads the token from a Secret; [`deploy/k8s/parla.yaml`](../deploy/k8s/parla.yaml)
has the variables and the `prometheus.io/*` annotations commented. See [deployment.md](deployment.md#observability).

### Grafana

[`deploy/observability/grafana-dashboard.json`](../deploy/observability/grafana-dashboard.json) is a dashboard to
import (**Dashboards → New → Import**, pick your Prometheus): turns, fallback rate, active sessions, average CSAT,
requests and p95 latency per route, how turns were understood, LLM p95 latency and errors, NLU latency, handoffs,
CSAT answers and p95 of HTTP steps and functions. It has an `agent` filter.

## Traces

With `PARLA_OTEL_ENDPOINT` (or the standard `OTEL_EXPORTER_OTLP_ENDPOINT`), each request is a trace sent with
**OTLP/HTTP in JSON** (`POST /v1/traces`, `Content-Type: application/json`), which any OpenTelemetry Collector and
most backends accept directly. The exporter is a background thread with a bounded queue (2,048 spans): requests only
add to the queue and never wait for the collector. Batches go out every `PARLA_OTEL_INTERVAL` seconds (sooner when
512 spans pile up), with a `OTEL_EXPORTER_OTLP_TIMEOUT` timeout. If the queue is full or the collector is down,
spans are dropped and counted in `parla_telemetry_dropped_total`, and Parla prints at most one warning a minute.

The span tree of a message to `/api/v1/bots/{bot}/events` (or the test chat):

```text
POST /api/v1/bots/{bot}/events          server · http.route, http.response.status_code
└─ parla.turn                           parla.agent.id, parla.channel, parla.environment, parla.version,
   │                                    parla.intent, parla.confidence, parla.outcome, parla.flow, parla.via, parla.handoff
   ├─ nlu.classify                      parla.intent, parla.confidence
   ├─ nlu.extract                       parla.entities (the entity names, never the values)
   ├─ chat {model}                      client · AI rescue, understanding by meaning, generative fallback
   │  └─ (gen_ai.* attributes)
   ├─ knowledge.search                  parla.knowledge.docs, parla.knowledge.hits, parla.knowledge.top_score
   └─ flow.run                          parla.flow, parla.flow.status (done, wait, handoff, error)
      ├─ http.step                      client · http.request.method, server.address, http.response.status_code
      ├─ function.run                   parla.function
      └─ agent.step                     parla.tools, parla.agent.turn, parla.agent.done
         ├─ chat {model}
         └─ http.step / function.run    (the tools the AI called)
```

Other entry points add a span on top of `parla.turn`: `channel.message` for WhatsApp and Telegram (the turn runs
after the webhook answers, in the same trace), `phone.turn` for Twilio and jambonz, and `asr` / `tts` for
`/api/v1/bots/{bot}/audio` and the voice routes.

LLM spans follow the OpenTelemetry GenAI conventions: `gen_ai.operation.name` (`chat`), `gen_ai.system` and
`gen_ai.provider.name` (`ollama`, `openai`, `anthropic`, `gcp.gemini`), `gen_ai.request.model`,
`gen_ai.request.max_tokens`, `gen_ai.request.temperature` and, when the provider returns them,
`gen_ai.usage.input_tokens` and `gen_ai.usage.output_tokens`. Prompts and answers are never attributes.

**Propagation.** An incoming W3C `traceparent` header continues that trace (and if it says "not sampled", Parla
doesn't export it). Every `http` step and HTTP tool sends `traceparent` to the service it calls, unless the step
already sets that header, so your API's spans hang under `http.step`.

A failed span has status `ERROR` and `error.type` (the exception class; the message isn't sent, since it can carry
the person's data).

### Where to send them

Everything speaks OTLP/HTTP, so it's the endpoint plus, for hosted backends, a header.

| Backend | Variables |
|---|---|
| **Jaeger** (all-in-one, OTLP on 4318) | `PARLA_OTEL_ENDPOINT=http://jaeger:4318` |
| **OpenTelemetry Collector** | `PARLA_OTEL_ENDPOINT=http://otel-collector:4318` (an `otlp` receiver with `protocols: http`) |
| **Grafana Tempo** | `PARLA_OTEL_ENDPOINT=http://tempo:4318` (Tempo's `otlp` receiver, `http`). Grafana Cloud: `PARLA_OTEL_ENDPOINT=https://otlp-gateway-<zone>.grafana.net/otlp` (for example `prod-eu-west-0`) and `OTEL_EXPORTER_OTLP_HEADERS=Authorization=Basic%20<base64 of instance:token>` |
| **Datadog** | Through the Datadog Agent with OTLP ingestion on (`DD_OTLP_CONFIG_RECEIVER_PROTOCOLS_HTTP_ENDPOINT=0.0.0.0:4318`): `PARLA_OTEL_ENDPOINT=http://datadog-agent:4318` |
| **Honeycomb** | `PARLA_OTEL_ENDPOINT=https://api.honeycomb.io` and `OTEL_EXPORTER_OTLP_HEADERS=x-honeycomb-team=<API key>` (EU: `https://api.eu1.honeycomb.io`) |

Only HTTP with JSON: no gRPC and no protobuf. A collector in between covers anything else (sampling, other formats,
several destinations).

## JSON logs

`PARLA_LOG_FORMAT=json` writes one line per request to stderr:

```json
{"ts": "2026-11-26T10:15:02-0300", "level": "info", "msg": "request", "method": "POST", "route": "/api/v1/bots/{bot}/events", "status": 200, "duration_ms": 14.8, "trace_id": "4bf92f3577b34da6a3ce929d0e0e4736", "span_id": "00f067aa0ba902b7"}
```

`level` is `error` for 5xx. The route is the template, as in the metrics. Without the variable, Parla logs as before
(it doesn't log requests). With traces off, `trace_id` still comes from the caller's `traceparent` when there is
one, so the line matches the caller's trace; otherwise it's a fresh id.

## Docker Compose: Jaeger and Prometheus

The optional `observability` profile adds Jaeger all-in-one (traces, UI at `http://127.0.0.1:16686`) and Prometheus
(`http://127.0.0.1:9090`, config in [`deploy/observability/prometheus.yml`](../deploy/observability/prometheus.yml)):

```sh
export PARLA_METRICS=1 PARLA_METRICS_TOKEN="$(openssl rand -hex 24)" PARLA_OTEL_ENDPOINT=http://jaeger:4318
docker compose --profile observability up -d
```

Prometheus reads the token as a compose secret from `PARLA_METRICS_TOKEN`. To use Grafana, add your own or point an
existing one at that Prometheus and import the dashboard.

## Privacy

By default nothing in metrics, spans or JSON logs comes from the conversation itself: no messages, bot replies, slot
values, entity values, URLs or paths of HTTP steps (only the host), keys or session ids (which can be phone numbers;
routes are templates). What does go: agent ids, intent, flow, entity and function names, confidence, statuses,
durations, the provider and model, token counts and the host each `http` step calls.

`PARLA_OTEL_CONTENT=1` adds `parla.message` (what the person wrote) and `parla.reply` (what the bot said) to the
`parla.turn` span, with the agent's vault secrets replaced by `••••` and personal data masked with every
[PII redaction](concepts.md#retention-and-personal-data) category (emails, phones, cards, ID numbers, bank
accounts), whatever the agent's own setting. Masking is a heuristic: leave this off unless your trace backend is as
private as `parla.db`, and see [security.md](security.md#metrics-and-traces).

## Overhead

With everything off, each instrumented call does one `if` and gets a shared no-op object. Measured on a laptop with
200 chat turns against the pizzeria example (`examples/pizzeria.json`), metrics and traces on to a local collector:

| Turns | Off | Metrics + traces |
|---|---|---|
| Repeated messages (embeddings cached, the cheapest possible turn) | 0.83 ms mean | 0.95 ms mean (+0.12 ms) |
| Different messages (embedding each one) | 14.7 ms mean | 14.7–15.3 ms mean (within noise) |

## Limits

- Only Parla's own process: no Ollama, provider or database metrics (use their exporters).
- No OTLP metrics or logs export: metrics are pull (Prometheus), and logs go to stderr.
- No gRPC or protobuf, no sampler setting (everything is sampled, unless the caller's `traceparent` says not to).
- MCP tool calls from the agent step don't have their own span yet; they are part of `agent.step`.
- The `start` event (the first message a flow sends on its own) is in the HTTP span but not in a `parla.turn`.
- Counters live in memory: they start at zero on every restart (Prometheus handles that with `rate`/`increase`).
