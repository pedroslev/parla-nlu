# Observabilidad

[English](observability.md) · **Español**

Parla puede exportar **métricas de Prometheus**, **trazas de OpenTelemetry** y **logs de pedidos en JSON**. Todo
viene apagado y usa solo la biblioteca estándar (`parla/telemetry.py`): no hay SDK que instalar. Las métricas y las
trazas llevan ids, nombres de intenciones y flujos, confianza, duraciones y estados. Nunca llevan lo que escribe la
gente, los valores de los slots ni claves, salvo que prendas el [contenido en las trazas](#privacidad).

| Variable | Por defecto | Para qué |
|---|---|---|
| `PARLA_METRICS` | apagado | `1` sirve `GET /metrics` en el formato de texto de Prometheus (0.0.4). Apagado: `/metrics` contesta 404. |
| `PARLA_METRICS_TOKEN` | vacío | Token bearer para `/metrics`. Sin token, `/metrics` solo contesta en esta misma máquina (ver [Acceso a /metrics](#acceso-a-metrics)). |
| `PARLA_OTEL_ENDPOINT` | vacío | URL base OTLP/HTTP. Los spans van a `{PARLA_OTEL_ENDPOINT}/v1/traces` en JSON. Vacío: sin trazas. |
| `OTEL_EXPORTER_OTLP_ENDPOINT`, `OTEL_EXPORTER_OTLP_TRACES_ENDPOINT` | vacío | Las variables estándar de OpenTelemetry, si `PARLA_OTEL_ENDPOINT` está vacío (la de `TRACES` es la URL completa). |
| `OTEL_EXPORTER_OTLP_HEADERS` (o `..._TRACES_HEADERS`) | vacío | Encabezados para el colector, `clave=valor,clave2=valor2` (valores url-encoded), por ejemplo una API key. |
| `OTEL_SERVICE_NAME` | `parla` | `service.name` de los spans. `OTEL_RESOURCE_ATTRIBUTES` (`deployment.environment=prod,...`) suma otros. |
| `OTEL_EXPORTER_OTLP_TIMEOUT` | `5000` | Milisegundos por envío. |
| `OTEL_SDK_DISABLED` | vacío | `true` apaga las trazas aunque haya un endpoint. |
| `PARLA_OTEL_INTERVAL` | `2` | Segundos entre lotes. |
| `PARLA_OTEL_CONTENT` | apagado | `1` suma el texto del turno al span `parla.turn`, tapado (ver [Privacidad](#privacidad)). |
| `PARLA_LOG_FORMAT` | vacío | `json`: una línea JSON por pedido HTTP en stderr, con `trace_id` y `span_id`. Vacío: no cambia nada. |

## Métricas

Las duraciones son histogramas en segundos (buckets de 5 ms a 30 s). Cada histograma también da `_count` (llamadas)
y `_sum`, así que «llamadas por resultado» es `rate(<nombre>_count{outcome="error"}[5m])`. `outcome` es `ok`,
`error` o, en los pasos HTTP, `http_error` (4xx/5xx) y `unreachable` (sin conexión, DNS, timeout).

| Métrica | Tipo | Etiquetas | Qué mide |
|---|---|---|---|
| `parla_http_requests_total` | counter | `route`, `method`, `status` | Pedidos HTTP. `route` es la plantilla (`/api/v1/bots/{bot}/events`), nunca la ruta cruda. |
| `parla_http_request_duration_seconds` | histogram | `route`, `method`, `outcome` | Latencia de los pedidos; `outcome="error"` en los 5xx. |
| `parla_turns_total` | counter | `agent`, `channel`, `environment` | Turnos de conversación (chat de prueba, API, widget, WhatsApp, Telegram, teléfono). |
| `parla_conversations_started_total` | counter | `agent`, `channel` | Conversaciones empezadas con un evento `start`. |
| `parla_intent_outcomes_total` | counter | `agent`, `outcome` | Cómo se entendió cada turno: `matched` (una intención), `answer` (la respuesta a una pregunta), `system` (cancelar, repetir, pasar a una persona), `fallback`, `none` (la atiende una persona). |
| `parla_nlu_duration_seconds` | histogram | `stage`, `outcome` | Latencia del NLU: `classify` (intención) y `extract` (entidades). |
| `parla_llm_request_duration_seconds` | histogram | `provider`, `outcome` | Llamadas al modelo (`ollama`, `openai`, `openai_compatible`, `anthropic`, `gemini`). |
| `parla_llm_tokens_total` | counter | `provider`, `type` | Tokens (`input`, `output`) cuando el proveedor los informa. |
| `parla_usage_total` | counter | `agent`, `kind`, `provider`, `unit` | Uso facturable: `kind` es `llm_input`, `llm_output`, `llm_cached`, `llm_compute`, `asr`, `tts`, `phone`, `phone_call`, `whatsapp`, `telegram`, `turn` ([costs_es.md](costs_es.md)). `agent="none"` fuera de una conversación. |
| `parla_cost_total` | counter | `agent`, `kind`, `provider`, `currency` | El mismo uso con el precio de la tabla en ese momento (sin el uso sin precio ni el costo fijo repartido; el reporte de Costos recalcula con los precios de hoy). |
| `parla_asr_duration_seconds` | histogram | `provider`, `outcome` | Voz a texto (`local`, `openai`, `deepgram`, `elevenlabs`, `google`). |
| `parla_tts_duration_seconds` | histogram | `provider`, `outcome` | Texto a voz. Las frases fijas ya pregeneradas no cuentan. |
| `parla_voice_e2e_latency_seconds` | histogram | `channel`, `asr`, `tts` | Voz en tiempo real: fin de lo que dice la persona (con el silencio de fin de turno) hasta el primer byte de audio que sale. Objetivo < 1 s con proveedores en streaming. |
| `parla_voice_tts_first_byte_seconds` | histogram | `provider` | Voz en tiempo real: de una oración que va al TTS a su primer byte de audio. |
| `parla_voice_barge_ins_total` | counter | `channel` | Voz en tiempo real: la persona habló encima del bot y el bot se calló. |
| `parla_http_step_duration_seconds` | histogram | `outcome` | Pasos `http` y herramientas HTTP del paso agente. |
| `parla_function_duration_seconds` | histogram | `language`, `outcome` | Ejecuciones de funciones (pasos y herramientas del paso agente). |
| `parla_knowledge_search_duration_seconds` | histogram | `outcome` | Búsquedas en la base de conocimiento. |
| `parla_handoffs_total` | counter | `agent`, `channel` | Conversaciones que el bot pasó a una persona. |
| `parla_webhook_deliveries_total` | counter | `outcome` | Intentos de los webhooks de la derivación: `delivered`, `retry` (se va a reintentar), `dead` (sin más reintentos). |
| `parla_webhook_delivery_duration_seconds` | histogram | | Ida y vuelta HTTP del webhook (cada intento que tuvo respuesta o venció). |
| `parla_csat_score` | histogram | `agent` | Respuestas a la encuesta CSAT, buckets de 1 a 5 (promedio: `_sum / _count`). |
| `parla_connections` | gauge | `kind` | Conexiones abiertas: `http` (keep-alive), `ws`, `sse`, `voice` (WebSockets de voz en tiempo real). |
| `parla_queue_depth` | gauge | `queue` | `executor` (pedidos esperando un hilo), `inflight`, `sessions` (charlas con un turno en curso o en fila), `bus_subscribers`, `db_write`, `embed`, `webhooks` (entregas de webhooks de la derivación en cola o saliendo). |
| `parla_embed_batches_total`, `parla_embed_items_total` | counter | | Llamadas de embeddings a ONNX y textos: textos / llamadas = tamaño medio del lote. |
| `parla_db_commits_total`, `parla_db_statements_total` | counter | | Group commits de SQLite y sus escrituras: sentencias / commits = tamaño medio del grupo. |
| `parla_active_sessions` | gauge | `agent` | Conversaciones sin terminar con movimiento en los últimos 30 minutos (se calcula en cada scrape). |
| `parla_test_runs_total` | counter | `agent`, `outcome` | Corridas de las pruebas (`passed`, `failed`): interfaz, API, MCP y el control antes de publicar. |
| `parla_outbound_messages_total` | counter | `channel`, `outcome` | Mensajes y llamadas salientes (API, campañas, recordatorios): `sent`, `retry` (falló y se va a reintentar), `failed`, `opted_out` (rechazado porque la persona se dio de baja, o una baja nueva). |
| `parla_campaign_recipients` | gauge | `status` | Destinatarios de campañas por estado (`queued`, `sending`, `sent`, `delivered`, `read`, `replied`, `failed`, `opted_out`, `canceled`), calculado en cada lectura. Ver [outbound_es.md](outbound_es.md). |
| `parla_telemetry_dropped_total` | counter | `reason` | Spans descartados (`queue_full`, `export_failed`) o series rechazadas (`too_many_series`). |
| `parla_info` | gauge | `version` | Siempre 1. |
| `process_start_time_seconds` | gauge | | Arranque del proceso, hora Unix. |

La cardinalidad de las etiquetas está acotada: `agent` es el id del agente (8 caracteres hex), `channel` es `web`,
`api`, `whatsapp`, `telegram`, `phone`, `prueba` (el chat de prueba) u `other`, las rutas son plantillas (los ids
quedan como `{id}`, `{bot}`, `{session}`, `{campaign}`…: `/api/agents/{id}/campaigns/{campaign}/start`), y Parla
deja de crear series nuevas después de 5.000 (cuenta en `parla_telemetry_dropped_total{reason="too_many_series"}`).

Consultas útiles:

```promql
# tasa de fallback por agente, últimos 15 minutos
sum by (agent) (rate(parla_intent_outcomes_total{outcome="fallback"}[15m]))
  / sum by (agent) (rate(parla_intent_outcomes_total[15m]))
# latencia p95 de la API de conversación
histogram_quantile(0.95, sum by (le) (rate(parla_http_request_duration_seconds_bucket{route="/api/v1/bots/{bot}/events"}[5m])))
# errores del modelo por proveedor
sum by (provider) (rate(parla_llm_request_duration_seconds_count{outcome!="ok"}[5m]))
# gasto estimado por agente, últimas 24 h
sum by (agent, currency) (increase(parla_cost_total[1d]))
# CSAT promedio de hoy
sum(increase(parla_csat_score_sum[1d])) / sum(increase(parla_csat_score_count[1d]))
```

### Acceso a /metrics

- Sin `PARLA_METRICS`: `/metrics` da 404.
- `PARLA_METRICS=1` con `PARLA_METRICS_TOKEN`: pide `Authorization: Bearer <token>`, desde cualquier lado. Es lo que
  va en Docker, Kubernetes o cualquier Prometheus en otra máquina.
- `PARLA_METRICS=1` sin token: solo desde esta misma máquina, o sea, la conexión viene de loopback **y** el `Host` es
  `127.0.0.1`, `localhost` o `[::1]`. Un dominio de `PARLA_HOSTS` no alcanza, a propósito: un proxy en la misma
  máquina reenviaría desde loopback el pedido de cualquiera.

`/metrics` no está bajo `/api/`: no pide sesión ni API key, y no queda en la auditoría. Si tu proxy publica todo,
bloqueá `/metrics` ahí o poné el token.

### Prometheus

```yaml
scrape_configs:
  - job_name: parla
    metrics_path: /metrics
    authorization:
      type: Bearer
      credentials_file: /etc/prometheus/parla-token     # el mismo valor que PARLA_METRICS_TOKEN
    static_configs:
      - targets: ["parla.example.internal:8000"]
```

En Kubernetes con el Prometheus Operator, [`deploy/k8s/servicemonitor.yaml`](../deploy/k8s/servicemonitor.yaml) es
un `ServiceMonitor` comentado que lee el token de un Secret; [`deploy/k8s/parla.yaml`](../deploy/k8s/parla.yaml)
tiene las variables y las anotaciones `prometheus.io/*` comentadas. Ver [deployment.md](deployment_es.md#observabilidad).

### Grafana

[`deploy/observability/grafana-dashboard.json`](../deploy/observability/grafana-dashboard.json) es un tablero para
importar (**Dashboards → New → Import**, elegí tu Prometheus): turnos, tasa de fallback, sesiones activas, CSAT
promedio, pedidos y latencia p95 por ruta, cómo se entendieron los turnos, latencia p95 y errores del modelo,
latencia del NLU, pases a una persona, respuestas CSAT y p95 de pasos HTTP y funciones. Tiene un filtro por `agent`.

## Trazas

Con `PARLA_OTEL_ENDPOINT` (o la estándar `OTEL_EXPORTER_OTLP_ENDPOINT`), cada pedido es una traza que se manda por
**OTLP/HTTP en JSON** (`POST /v1/traces`, `Content-Type: application/json`), que aceptan directo cualquier
OpenTelemetry Collector y la mayoría de los backends. El exportador es un hilo aparte con una cola acotada (2.048
spans): los pedidos solo suman a la cola y nunca esperan al colector. Los lotes salen cada `PARLA_OTEL_INTERVAL`
segundos (antes si se juntan 512 spans), con un timeout de `OTEL_EXPORTER_OTLP_TIMEOUT`. Si la cola se llena o el
colector está caído, los spans se descartan y se cuentan en `parla_telemetry_dropped_total`, y Parla avisa como
mucho una vez por minuto.

El árbol de spans de un mensaje a `/api/v1/bots/{bot}/events` (o al chat de prueba):

```text
POST /api/v1/bots/{bot}/events          server · http.route, http.response.status_code
└─ parla.turn                           parla.agent.id, parla.channel, parla.environment, parla.version,
   │                                    parla.intent, parla.confidence, parla.outcome, parla.flow, parla.via, parla.handoff
   ├─ nlu.classify                      parla.intent, parla.confidence
   ├─ nlu.extract                       parla.entities (los nombres de las entidades, nunca los valores)
   ├─ chat {modelo}                     client · rescate de intención, entender por significado, fallback generativo
   │  └─ (atributos gen_ai.*)
   ├─ knowledge.search                  parla.knowledge.docs, parla.knowledge.hits, parla.knowledge.top_score
   └─ flow.run                          parla.flow, parla.flow.status (done, wait, handoff, error)
      ├─ http.step                      client · http.request.method, server.address, http.response.status_code
      ├─ function.run                   parla.function
      └─ agent.step                     parla.tools, parla.agent.turn, parla.agent.done
         ├─ chat {modelo}
         └─ http.step / function.run    (las herramientas que llamó la IA)
```

Las otras entradas suman un span arriba de `parla.turn`: `channel.message` para WhatsApp y Telegram (el turno corre
después de que el webhook contesta, en la misma traza), `phone.turn` para Twilio y jambonz, y `asr` / `tts` para
`/api/v1/bots/{bot}/audio` y las rutas de voz.

Los spans del modelo siguen las convenciones GenAI de OpenTelemetry: `gen_ai.operation.name` (`chat`),
`gen_ai.system` y `gen_ai.provider.name` (`ollama`, `openai`, `anthropic`, `gcp.gemini`), `gen_ai.request.model`,
`gen_ai.request.max_tokens`, `gen_ai.request.temperature` y, cuando el proveedor los devuelve,
`gen_ai.usage.input_tokens` y `gen_ai.usage.output_tokens`. Los prompts y las respuestas nunca son atributos.

**Propagación.** Un encabezado W3C `traceparent` entrante continúa esa traza (y si dice «no muestrear», Parla no la
exporta). Cada paso `http` y herramienta HTTP le manda `traceparent` al servicio que llama, salvo que el paso ya
ponga ese encabezado, así los spans de tu API quedan colgados de `http.step`.

Un span que falló tiene estado `ERROR` y `error.type` (la clase de la excepción; el mensaje no se manda, porque
puede traer datos de la persona).

### A dónde mandarlas

Todos hablan OTLP/HTTP: es el endpoint y, en los backends en la nube, un encabezado.

| Backend | Variables |
|---|---|
| **Jaeger** (all-in-one, OTLP en 4318) | `PARLA_OTEL_ENDPOINT=http://jaeger:4318` |
| **OpenTelemetry Collector** | `PARLA_OTEL_ENDPOINT=http://otel-collector:4318` (un receiver `otlp` con `protocols: http`) |
| **Grafana Tempo** | `PARLA_OTEL_ENDPOINT=http://tempo:4318` (el receiver `otlp` de Tempo, `http`). Grafana Cloud: `PARLA_OTEL_ENDPOINT=https://otlp-gateway-<zona>.grafana.net/otlp` (por ejemplo `prod-eu-west-0`) y `OTEL_EXPORTER_OTLP_HEADERS=Authorization=Basic%20<base64 de instancia:token>` |
| **Datadog** | Por el Datadog Agent con la ingesta OTLP prendida (`DD_OTLP_CONFIG_RECEIVER_PROTOCOLS_HTTP_ENDPOINT=0.0.0.0:4318`): `PARLA_OTEL_ENDPOINT=http://datadog-agent:4318` |
| **Honeycomb** | `PARLA_OTEL_ENDPOINT=https://api.honeycomb.io` y `OTEL_EXPORTER_OTLP_HEADERS=x-honeycomb-team=<API key>` (UE: `https://api.eu1.honeycomb.io`) |

Solo HTTP con JSON: ni gRPC ni protobuf. Un colector en el medio cubre todo lo demás (muestreo, otros formatos,
varios destinos).

## Logs JSON

`PARLA_LOG_FORMAT=json` escribe una línea por pedido en stderr:

```json
{"ts": "2026-11-26T10:15:02-0300", "level": "info", "msg": "request", "method": "POST", "route": "/api/v1/bots/{bot}/events", "status": 200, "duration_ms": 14.8, "trace_id": "4bf92f3577b34da6a3ce929d0e0e4736", "span_id": "00f067aa0ba902b7"}
```

`level` es `error` en los 5xx. La ruta es la plantilla, como en las métricas. Sin la variable, Parla loguea como
siempre (no loguea los pedidos). Con las trazas apagadas, `trace_id` igual sale del `traceparent` del que llama si
vino uno, así la línea coincide con su traza; si no, es un id nuevo.

## Docker Compose: Jaeger y Prometheus

El perfil opcional `observability` suma Jaeger all-in-one (trazas, interfaz en `http://127.0.0.1:16686`) y
Prometheus (`http://127.0.0.1:9090`, configurado en [`deploy/observability/prometheus.yml`](../deploy/observability/prometheus.yml)):

```sh
export PARLA_METRICS=1 PARLA_METRICS_TOKEN="$(openssl rand -hex 24)" PARLA_OTEL_ENDPOINT=http://jaeger:4318
docker compose --profile observability up -d
```

Prometheus lee el token como un secret de compose desde `PARLA_METRICS_TOKEN`. Para Grafana, sumá el tuyo o apuntá
uno que ya tengas a ese Prometheus e importá el tablero.

## Privacidad

Por defecto nada de las métricas, los spans ni los logs JSON sale de la conversación en sí: ni mensajes, ni
respuestas del bot, ni valores de slots o entidades, ni URLs o rutas de los pasos HTTP (solo el host), ni claves, ni
ids de conversación (que pueden ser teléfonos; las rutas son plantillas). Lo que sí va: ids de agentes, nombres de
intenciones, flujos, entidades y funciones, confianza, estados, duraciones, el proveedor y el modelo, la cantidad de
tokens y el host al que llama cada paso `http`.

`PARLA_OTEL_CONTENT=1` suma `parla.message` (lo que escribió la persona) y `parla.reply` (lo que dijo el bot) al span
`parla.turn`, con las claves de la bóveda del agente reemplazadas por `••••` y los datos personales tapados con todas
las categorías de [enmascarado](concepts_es.md#retención-y-datos-personales) (emails, teléfonos, tarjetas,
documentos, cuentas bancarias), tenga el agente el ajuste que tenga. El enmascarado es heurístico: dejalo apagado
salvo que tu backend de trazas sea tan privado como `parla.db`, y mirá [security.md](security_es.md#métricas-y-trazas).

## Costo

Con todo apagado, cada llamada instrumentada hace un `if` y recibe un objeto vacío compartido. Medido en una laptop
con 200 turnos de chat contra el ejemplo de la pizzería (`examples/pizzeria.json`), con métricas y trazas a un
colector local:

| Turnos | Apagado | Métricas + trazas |
|---|---|---|
| Mensajes repetidos (vectores en caché, el turno más barato posible) | 0,83 ms promedio | 0,95 ms promedio (+0,12 ms) |
| Mensajes distintos (calcula el vector de cada uno) | 14,7 ms promedio | 14,7–15,3 ms promedio (dentro del ruido) |

## Límites

- Solo el proceso de Parla: nada de métricas de Ollama, de los proveedores ni de la base (usá sus exporters).
- No exporta métricas ni logs por OTLP: las métricas se leen (Prometheus) y los logs van a stderr.
- Ni gRPC ni protobuf, ni ajuste de muestreo (se muestrea todo, salvo que el `traceparent` del que llama diga que no).
- Las llamadas a herramientas MCP del paso agente todavía no tienen su propio span; son parte de `agent.step`.
- El evento `start` (lo primero que dice un flujo por su cuenta) está en el span HTTP pero no en un `parla.turn`.
- Los contadores viven en memoria: arrancan en cero con cada reinicio (Prometheus lo maneja con `rate`/`increase`).
