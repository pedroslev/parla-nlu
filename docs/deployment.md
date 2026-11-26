# Deployment

**English** · [Español](deployment_es.md)

Parla is **a single** Python **process** (`ThreadingHTTPServer`, one thread per request) with no database
server: agents are files in the data folder, and conversations, login sessions and the audit log are in a SQLite
file there (`parla.db`). That shapes how it's deployed:

- **One replica per data folder.** Loaded models live in memory, and agents are saved to files with no
  cross-process locking. Two instances on the same data overwrite each other. Login sessions survive a restart.
- **The admin interface is used from `127.0.0.1` / `localhost`**, or through a domain you add to `PARLA_HOSTS`.
  See [Origin](#the-origin-guard).
- Read [security.md](security.md#before-exposing-it-to-the-internet) before exposing it.
- On Kubernetes, see [kubernetes.md](kubernetes.md) (Helm chart, k3s, backups, NetworkPolicy).

## Environment variables

| Variable | In the container | What for |
|---|---|---|
| `PARLA_HOST` | `0.0.0.0` | Where it listens. Unset: `127.0.0.1`. |
| `PARLA_DATA` | `/data` | Agents, versions, conversations, `users.json`, voice models. |
| `PARLA_EMBED_CACHE` | `/data/models/embeddings` | Embedding model cache (fastembed, ~1.2 GB). |
| `HF_HOME` | `/data/models/hf` | Hugging Face cache (fastembed downloads). |
| `PARLA_FUNCTIONS` | `0` | `function` steps (the bots' code). Off in the image; `1` to turn them on. |
| `PARLA_WHISPER` | `base` | Dictation model (`tiny` if the machine is slow). |
| `PARLA_LANG` | browser's language | Default interface language (`en`, `es` or `pt`) for users who haven't picked one. |
| `PARLA_HOSTS` | | Domains (`host` or `host:port`, comma-separated) that can also be used to reach the interface and `/api/`. |
| `PARLA_SECURE_COOKIE` | | `1`: the session cookie always has `Secure` (behind HTTPS). |
| `PARLA_USERS` | | A different path for `users.json`. |
| `PARLA_RETENTION_DAYS` | | Days to keep conversations with no activity, for agents without their own `retention_days`. Unset or `0`: forever. |
| `PARLA_AUDIT_DAYS` | | Days to keep the audit log. Unset: `365`. |
| `PARLA_CAMPAIGN_MAX` | | Maximum recipients per campaign ([outbound.md](outbound.md)). Unset: `10000`. |
| `PARLA_PUBLIC_URL` | | Public address (`https://bots.example.com`): webhooks and the SSO redirect URI. |
| `PARLA_METRICS`, `PARLA_METRICS_TOKEN` | | `1`: Prometheus metrics at `GET /metrics`, with the token as `Authorization: Bearer` (required from another host or container). See [Observability](#observability). |
| `PARLA_OTEL_ENDPOINT` | | OTLP/HTTP base URL for OpenTelemetry traces (`http://jaeger:4318`). |
| `OTEL_EXPORTER_OTLP_ENDPOINT`, `OTEL_EXPORTER_OTLP_TRACES_ENDPOINT` | | Standard OpenTelemetry variables, used when `PARLA_OTEL_ENDPOINT` is empty. |
| `OTEL_EXPORTER_OTLP_HEADERS` (or `..._TRACES_HEADERS`) | | Headers for the collector (`key=value,…`), for example its API key. Keep it in a secret. |
| `OTEL_SERVICE_NAME`, `OTEL_RESOURCE_ATTRIBUTES` | | `service.name` (default `parla`) and extra resource attributes of the spans. |
| `OTEL_EXPORTER_OTLP_TIMEOUT`, `OTEL_SDK_DISABLED` | | Export timeout in ms (default `5000`); `true` turns traces off. |
| `PARLA_OTEL_INTERVAL`, `PARLA_OTEL_CONTENT` | | Seconds between span batches (default `2`); `1` adds the masked turn text to spans. See [observability.md](observability.md). |
| `PARLA_LOG_FORMAT` | | `json`: one JSON line per request on stderr, with `trace_id` and `span_id`. |
| `PARLA_OIDC_ISSUER`, `PARLA_OIDC_CLIENT_ID` | | Single sign-on with your identity provider: both set turn it on. See [sso.md](sso.md). |
| `PARLA_OIDC_CLIENT_SECRET`, `PARLA_OIDC_CLIENT_SECRET_FILE` | | The client secret, or better a file that holds it (Docker / Kubernetes secrets; the file wins). |
| `PARLA_OIDC_SCOPES`, `PARLA_OIDC_ROLE_CLAIM`, `PARLA_OIDC_ROLE_MAP`, `PARLA_OIDC_DEFAULT_ROLE` | | Scopes (default `openid email profile`), the claim with the groups, `group:role` pairs and the role for unmapped users (empty: denied). |
| `PARLA_OIDC_ONLY`, `PARLA_OIDC_LABEL`, `PARLA_OIDC_LOGOUT` | | `1`: no password login except the owner from loopback; the button's label; `0`: don't redirect to the provider's logout (Okta). |
| `PARLA_ANTHROPIC_BASE_URL`, `PARLA_GEMINI_BASE_URL` | | Another address for those AI providers (your own proxy, tests). The other AI providers take their address per agent. |
| `PARLA_OPENAI_BASE_URL`, `PARLA_DEEPGRAM_BASE_URL`, `PARLA_ELEVENLABS_BASE_URL`, `PARLA_GOOGLE_SPEECH_BASE_URL`, `PARLA_GOOGLE_TTS_BASE_URL` | | Another address for the hosted voice providers. |
| `PARLA_WHATSAPP_API`, `PARLA_TELEGRAM_API` | | Another base URL for the WhatsApp Cloud API (default `https://graph.facebook.com/v21.0`) and the Telegram Bot API. |
| `PARLA_URL`, `PARLA_TOKEN`, `PARLA_MCP_ALLOWED_HOSTS` | | Only for `mcp_server.py`: where Parla is, its API key and extra hosts for `--http`. |
| `PARLA_THREADS` | | Threads that run requests (turns, admin API). Unset: `64`. See [Performance and tuning](#performance-and-tuning). |
| `PARLA_EMBED_WORKERS`, `PARLA_EMBED_THREADS` | | Parallel embedding calls (default: cores / 2) and ONNX threads per call (default `2`). |
| `PARLA_EMBED_BATCH`, `PARLA_EMBED_WAIT_MS` | | Texts per embedding call (default `16`) and how long to wait to fill a batch (default `0`: only what is already queued). |
| `PARLA_VOICE_WORKERS` | | Local Whisper/Piper model sets that work at the same time (default `min(2, cores / 4)`; each one uses its own RAM). |
| `PARLA_VOICE_MAX_SECONDS` | | Longest real-time voice stream (call, browser or widget) before Parla closes it (default `3600`). |
| `PARLA_IDLE_TIMEOUT`, `PARLA_WS_MAX_MESSAGE` | | Seconds without data before a connection is closed (default `30`) and the largest WebSocket message (default `1000000` bytes). |
| `PARLA_DATABASE_URL` | | `postgresql://user:password@host:5432/db`: Postgres instead of SQLite, needed for several replicas. See [Postgres and high availability](#postgres-and-high-availability). |
| `PARLA_SECRET_KEY` | | A long random value, the same in every replica: signs the audio URLs of phone calls. Required with several replicas. |
| `PARLA_DB_POOL`, `PARLA_DB_LOCKS` | | Postgres connections per process for queries (default `20`) and for per-conversation locks (default `32`). |
| `PARLA_DATABASE_SCHEMA`, `PARLA_LOCK_TIMEOUT`, `PARLA_LEADER_CHECK` | | Postgres schema (default: the user's `search_path`), seconds to wait for a conversation lock (default `30`) and between leader checks (default `2`). |

The port is the argument to `app.py` (the image uses `8000`). The Ollama address isn't a variable: it's configured
per agent in the interface (**IA → dirección**, AI → address).

## On your computer

```sh
make run                          # or: .venv/bin/python app.py
.venv/bin/python app.py 8080      # another port
```

It listens on `127.0.0.1` unless you set `PARLA_HOST`.

## Docker

### Prebuilt image

Images for `linux/amd64` and `linux/arm64` are published to the GitHub Container Registry. `latest` and version
tags (`0.9.0`, `0.9`) appear after the first tagged release; `edge` follows `main`. Each has a `-voice` variant
(`latest-voice`, `edge-voice`) with ffmpeg, faster-whisper and piper.

```sh
docker run -d --name parla --restart unless-stopped \
  --read-only --tmpfs /tmp \
  -p 127.0.0.1:8000:8000 -v parla-data:/data ghcr.io/pedroslev/parla-nlu:latest
```

The embedding model (~1.2 GB) is downloaded to the `parla-data` volume the first time you train.

### Building it yourself

```sh
make docker-build                 # parla:local image   (VOICE=1 make docker-build: with voice)
make docker-run                   # http://127.0.0.1:8000, data in the "parla-data" volume
```

By hand:

```sh
docker build -t parla:local .
docker build -t parla:local --build-arg INSTALL_VOICE=1 .                # + ffmpeg, faster-whisper, piper
docker build -t parla:local --build-arg BAKE_EMBED_DIR=/opt/embeddings . # embedding model inside the image

docker run -d --name parla --restart unless-stopped \
  --read-only --tmpfs /tmp \
  -p 127.0.0.1:8000:8000 -v parla-data:/data parla:local
```

- Unprivileged user (uid `10001`), read-only file system except `/data` and `/tmp`.
- Publish on `127.0.0.1` and with **the same port number** outside and inside (`-p 127.0.0.1:8000:8000`). With
  `-p 9000:8000` the interface opens but won't let you save anything (403, see [Origin](#the-origin-guard)), unless
  you add `PARLA_HOSTS=localhost:9000`.
- The repo's `data/` isn't included in the image (`.dockerignore`): it holds users, keys and conversations.

## Docker Compose

```sh
docker compose up -d                       # Parla at http://127.0.0.1:8000
docker compose --profile ai up -d          # + Ollama (local AI)
PARLA_VOICE=1 docker compose up -d --build # with voice
docker compose --profile observability up -d   # + Jaeger and Prometheus (see Observability below)
docker compose logs -f parla
```

With the `ai` profile, pull a model and point the agent at Ollama:

```sh
docker compose exec ollama ollama pull qwen2.5:0.5b
```

In the agent: **AI → URL** `http://ollama:11434` (or the interface's download button, which
uses that address). Ollama doesn't publish ports: only Parla talks to it.

Data is kept in the `parla-data` and `ollama-models` volumes. `docker compose down` doesn't delete them;
`down -v` does.

## Kubernetes and k3s

[kubernetes.md](kubernetes.md) has the full guide: the Helm chart (`deploy/helm/parla`) with an example production
values file (domain, TLS, SSO, metrics, backups, NetworkPolicy, Ollama), a k3s quickstart, upgrades and
rollbacks, backup and restore from the CronJob's archives, the Kustomize manifests (`deploy/k8s`, `deploy/k3s`) and a
production checklist. In short:

```sh
helm install parla ./deploy/helm/parla -n parla --create-namespace -f values.yaml
kubectl -n parla port-forward deploy/parla 8000:8000     # then open http://127.0.0.1:8000 and create the owner
```

- **One replica, `Recreate` strategy** with SQLite (the default): an upgrade has a few seconds of downtime. Several
  replicas with `RollingUpdate` need Postgres: see [below](#postgres-and-high-availability).
- Non-root (uid/gid `10001`, `fsGroup` for the volume), `readOnlyRootFilesystem`, no capabilities, `RuntimeDefault`
  seccomp, no service account token. Liveness on `GET /` (static page), readiness on `GET /readyz` (checks the database).
- **Ingress publishes only `/api/v1/`, `/files/` and `/static/widget.js`** by default (the API, the widget and the
  WhatsApp, Telegram and phone webhooks). The whole UI on a domain (needed for SSO) needs `PARLA_HOSTS`; the chart's
  `ingress.exposeAdmin: true` sets it.
- Use **8000 on both sides** of `port-forward` (because of the [Origin guard](#the-origin-guard)).

## Postgres and high availability

By default everything is in SQLite and Parla is one process. With `PARLA_DATABASE_URL=postgresql://…` the same
tables go to Postgres (13 or newer) and **several Parla processes or pods can serve the same bots at once**:

```sh
.venv/bin/pip install -r requirements-postgres.txt       # or scripts/setup.sh --postgres (the Docker image has it)
export PARLA_DATABASE_URL=postgresql://parla:<password>@db.internal:5432/parla?sslmode=require
export PARLA_SECRET_KEY=$(openssl rand -hex 32)          # the same value in every replica
python -m parla.migrate sqlite-to-postgres              # once, to bring an existing data/parla.db (Parla stopped)
.venv/bin/python app.py 8000
```

The schema is created and migrated on startup (versioned, under an advisory lock, so replicas starting together
don't race). Compose: `docker compose --profile postgres up -d` with the two variables above (see
`docker-compose.yml`). Kubernetes: [kubernetes.md](kubernetes.md#high-availability).

| Where | What |
|---|---|
| Postgres | Conversations, login sessions, audit log, usage, campaigns and their queue, opt-outs, webhook queue, SSO login state; shared counters (login lockout, API sends per minute), WhatsApp/Telegram message ids already handled, phone silence counters and the plan for a call's `/after`. |
| Shared data folder (`PARLA_DATA`, ReadWriteMany) | Agents, versions, environments, trained models, `users.json` and API keys, secrets (`<id>.secrets.json`, mode 600), prices, uploaded files. Every replica re-reads a file when it changes (mtime), as it already did for hand edits. |
| Each replica | Embedding and voice models (`/data/models`: mount it per pod), loaded models and caches, metrics, channel status in the Agent page, the voice WebSocket of a call (it stays on the replica that holds it). |

How replicas cooperate:

- **Conversation order**: turns of the same conversation take a Postgres advisory lock
  (`pg_advisory_lock(hashtext(bot/session))`, waits up to `PARLA_LOCK_TIMEOUT`), so they run one at a time whatever
  replica each request reaches. WhatsApp, Telegram and phone webhooks use the same kind of lock.
- **Live events**: what one replica publishes (a saved conversation, an operator reply, campaign progress) reaches
  WebSocket and SSE clients on the others through `LISTEN/NOTIFY` (conversations travel as an id and are re-read).
  The AI's streamed tokens are only sent by the replica that runs the turn, which is the one the client talks to.
- **Queues**: API sends, reminders and webhook deliveries are claimed with `FOR UPDATE SKIP LOCKED` by any replica
  (webhooks keep their per-conversation order).
- **Leader**: one replica holds the `parla:leader` advisory lock and runs what must run once: campaign pacing,
  retention cleanup, external handoff timeouts and requeuing rows stuck in "sending" (5 min for webhooks, 10 for
  messages). If it dies, Postgres releases the lock with its connection and another replica takes over within
  `PARLA_LEADER_CHECK` seconds. `GET /readyz` says which one is the leader.
- **Training and publishing** take a per-agent advisory lock; the other replicas load the new model on their next
  turn (the trained file changed).

Backups: `pg_dump` for the database (`pg_dump -Fc "$PARLA_DATABASE_URL" > parla-$(date +%F).dump`, restore with
`pg_restore -d …`) plus the data folder without `models/`. Limits: an in-flight request is lost when its pod is killed
(the client retries); campaign pacing restarts with up to 1 s of burst after a failover; channel status and metrics
are per replica.

## The Origin guard

Every request to `/api/` with an `Origin` that isn't `127.0.0.1:<port>` or `localhost:<port>` (the port Parla
listens on) or one of `PARLA_HOSTS` is rejected with 403, except the widget's public routes. Also, a request whose
`Host` isn't local or in `PARLA_HOSTS` is rejected with 403 unless it carries an API key or is the widget chat
(against DNS rebinding). This protects your Parla from pages you open in your browser. Consequences:

- **The full interface behind a domain (`https://bots.midominio.com`) needs
  `PARLA_HOSTS=bots.midominio.com`.** Without it, the page opens but all of `/api/` (login included) responds 403.
  With HTTPS, add `PARLA_SECURE_COOKIE=1` or have the proxy send `X-Forwarded-Proto: https`. “Connect to AI”
  still only works from `127.0.0.1` / `localhost`.
- To administer remotely without exposing the interface: tunnel to the port, with the same number on both sides.

```sh
ssh -L 8000:127.0.0.1:8000 usuario@tu-servidor            # server with Docker or systemd
kubectl -n parla port-forward deploy/parla 8000:8000        # Kubernetes / k3s
```

- The public API (`/api/v1/` with `Authorization: Bearer <key>` from your backend) doesn't send `Origin` and isn't
  affected. The widget uses the **sitios autorizados** (authorized sites) exception.

## Behind an HTTPS proxy

Outside Kubernetes, publish only what the widget and your integrations need. Caddy:

```
bots.midominio.com {
    @public path /api/v1/* /static/widget.js /files/*
    handle @public {
        reverse_proxy 127.0.0.1:8000
    }
    respond 404
}
```

nginx:

```nginx
server {
    listen 443 ssl;
    server_name bots.midominio.com;
    # ssl_certificate / ssl_certificate_key ...
    client_max_body_size 25m;          # audio and PDFs are sent as base64
    proxy_read_timeout 3600s;          # AI and voice take seconds; WebSocket/SSE stay open (Parla pings every 15-30 s)
    proxy_buffering off;               # SSE and streamed AI replies, token by token
    proxy_http_version 1.1;            # keep-alive and WebSocket
    proxy_set_header Upgrade $http_upgrade;
    proxy_set_header Connection $connection_upgrade;   # map $http_upgrade $connection_upgrade { default upgrade; "" ""; }

    location /api/v1/ { proxy_pass http://127.0.0.1:8000; }
    location = /static/widget.js { proxy_pass http://127.0.0.1:8000; }
    location /files/ { proxy_pass http://127.0.0.1:8000; }
    location / { return 404; }
}
```

- The widget is loaded from `https://bots.midominio.com/static/widget.js` and talks to that same server. Add the
  site where you embed it in **Web widget → Allowed sites**.
- WhatsApp and Telegram call `/api/v1/bots/{bot}/whatsapp` and `/telegram`, already covered by `/api/v1/` (see
  [channels.md](channels.md)). Don't rate-limit them too tightly: Meta and Telegram retry when they get errors.
- Phone providers call `/api/v1/bots/{bot}/phone/…` (and fetch `/phone/audio/<token>.wav` with `tts: "parla"`), also
  under `/api/v1/`. The proxy must pass the original path and query untouched and `PARLA_PUBLIC_URL` must be the exact
  address Twilio calls: the Twilio signature covers the full URL. Twilio waits ~15 s per answer, so keep
  `proxy_read_timeout` above that.
- Parla has no rate limiting of its own (except on login): add it at the proxy.

## First login and users

**With no users created, Parla doesn't ask for a login**: anyone who reaches the interface is the owner. There's
no default password. So, before publishing anything:

1. Go in through `127.0.0.1` (or the tunnel / port-forward).
2. In **Users**, create the first user: it becomes the owner and from then on login is required.
3. Create the others with the minimum role and, for integrations, API keys.

With [SSO](sso.md) configured, login is required even with no users, and that first local owner can only be
created from the machine itself (`127.0.0.1`, the tunnel or `port-forward`).

Changing a password: **Users → Change password**. Only an owner can do it, for their own or someone
else's. Changing it or deleting the user ends their sessions. If you lost the password of the only owner, stop
Parla, delete `users.json` from the data folder (it goes back to open, with no users) and create a new one:

```sh
docker run --rm -v parla-data:/data --entrypoint rm parla:local /data/users.json
kubectl -n parla exec deploy/parla -- rm /data/users.json && kubectl -n parla rollout restart deploy/parla
```

## Models: download and cache

| Model | Size | When it's downloaded | Where |
|---|---|---|---|
| Embeddings (`google/embeddinggemma-300m`, fastembed) | ~1.2 GB | on first training | `PARLA_EMBED_CACHE` |
| Dictation (faster-whisper `base`) | ~150 MB | when voice is used | `/data/models/whisper` |
| Voices (piper) | ~60 MB per language | when voice is used | `/data/models/piper` |
| Local AI (Ollama) | 0.4–1.3 GB | when you pull it | Ollama volume |

Everything lands in the data volume and survives restarts and upgrades. The first training takes as long as the
download. To avoid depending on the internet at startup (or on clusters without outbound access), bake it into the
image:

```sh
docker build -t parla:baked --build-arg BAKE_EMBED_DIR=/opt/embeddings .
```

The image grows from ~400 MB to ~1.6 GB. If `MODEL` changes in `parla/server.py`, update the name in the
`Dockerfile`. Whisper and piper aren't pre-downloaded into the image.

## Performance and tuning

One process serves everything on one event loop (asyncio; `uvloop` is used if installed): HTTP/1.1 keep-alive,
WebSocket and SSE share port 8000, so probes and ingress paths don't change. Measured on a 10-core M4 with
`tests/perf/load.py` (5-turn conversations, unique texts): ~280 turns/s with 10 concurrent conversations, ~360-420
from 50 up to 1,000 concurrent with 0 errors, and 5,000 idle WebSocket/SSE connections in ~150 MB on top of the model.

- **The ceiling is the embedding model**: every turn the bot has to classify runs `embeddinggemma-300m` on the CPU
  (~500 texts/s on that machine with every core). Above that, more concurrency only adds waiting time. More CPU (or more
  replicas, each with its own data) is what raises it; more workers in the same process does not (measured).
- `PARLA_EMBED_WORKERS` × `PARLA_EMBED_THREADS` should be about the cores the pod has. With a CPU limit of 4: `2` × `2`.
- `PARLA_THREADS` bounds requests in flight; a slow AI provider holds one thread per reply, so raise it if many
  conversations wait on the AI at the same time.
- Behind a proxy, WebSocket needs `Upgrade`/`Connection` forwarded, and SSE needs buffering off and a long read timeout
  (see the nginx block above; for ingress-nginx, the annotations in [kubernetes.md](kubernetes.md)). If the proxy
  can't, the widget and the UI fall back to polling on their own.
- Real-time voice ([ai-and-voice.md](ai-and-voice.md#real-time-voice)) uses the same WebSocket setup (the 3600 s
  timeouts above already cover a long call); the phone streams come from Twilio/jambonz, so `/api/v1/` must be
  reachable from the internet with TLS (`wss://`). With several replicas a phone call must stay on one replica.
- Writes to SQLite go through one writer thread that commits in groups; a write the API acknowledged is in the WAL
  (`synchronous=NORMAL`: survives a process crash; a power cut can lose the last transactions).

## Resources

| | CPU | Memory | Disk |
|---|---|---|---|
| Base (text, no AI) | 0.25 core idle; spikes while training | ~1 GB with the model loaded | 2 GB |
| With voice | +1 core while transcribing | +0.5–1 GB | +0.5 GB |
| Ollama `qwen2.5:0.5b` | 1–2 cores per reply | +1 GB | +0.5 GB |

Measured: with the embedding model loaded the process uses ~970 MB. The Deployment requests 1.5 Gi and limits to
3 Gi; raise it to 4 Gi with voice. It has no CPU limit on purpose (training is a short spike). Conversations grow
without limit unless you set a retention (`retention_days` or `PARLA_RETENTION_DAYS`, see
[concepts.md](concepts.md#retention-and-personal-data)).

## Observability

Metrics, traces and JSON logs are off by default; [observability.md](observability.md) has the full list of metrics,
the span tree, every variable and examples for Grafana Tempo, Datadog and Honeycomb. In short:

- **Prometheus:** `PARLA_METRICS=1` and a long random `PARLA_METRICS_TOKEN`, then scrape `/metrics` with
  `Authorization: Bearer <token>`. Without a token `/metrics` only answers to `127.0.0.1` itself, which a container
  or a pod never is for Prometheus.
- **Traces:** `PARLA_OTEL_ENDPOINT=http://<collector>:4318` (OTLP/HTTP JSON). The exporter never blocks requests: if
  the collector is down, spans are dropped.
- **Logs:** `PARLA_LOG_FORMAT=json` for one line per request with `trace_id`.

**Docker Compose.** The optional `observability` profile adds Jaeger all-in-one and Prometheus, only on `127.0.0.1`:

```sh
export PARLA_METRICS=1 PARLA_METRICS_TOKEN="$(openssl rand -hex 24)" PARLA_OTEL_ENDPOINT=http://jaeger:4318
docker compose --profile observability up -d
# traces: http://127.0.0.1:16686   metrics: http://127.0.0.1:9090
```

**Kubernetes.** With the Helm chart: `metrics.enabled: true`, `metrics.existingSecret` and, with the Prometheus
Operator, `metrics.serviceMonitor.enabled: true` ([kubernetes.md](kubernetes.md#metrics-and-traces)). With the
Kustomize manifests, put the token in a Secret and uncomment the variables, the `secretRef` and (for annotation-based
discovery) the `prometheus.io/*` annotations in `deploy/k8s/parla.yaml`:

```sh
kubectl -n parla create secret generic parla-metrics --from-literal=PARLA_METRICS_TOKEN="$(openssl rand -hex 24)"
```

With the Prometheus Operator, `deploy/k8s/servicemonitor.yaml` is a commented `ServiceMonitor` that sends that same
Secret as the bearer token. A plain Prometheus scrape config:

```yaml
scrape_configs:
  - job_name: parla
    metrics_path: /metrics
    authorization: {type: Bearer, credentials_file: /etc/prometheus/parla-token}
    kubernetes_sd_configs: [{role: pod, namespaces: {names: [parla]}}]
    relabel_configs:
      - {source_labels: [__meta_kubernetes_pod_label_app], regex: parla, action: keep}
      # Helm chart pods: __meta_kubernetes_pod_label_app_kubernetes_io_name
```

The Grafana dashboard is in `deploy/observability/grafana-dashboard.json`. Don't publish `/metrics` through the
Ingress: only `/api/v1/`, `/static/widget.js` and `/files/` need to be public.

## Where the data lives

```
/data   (or data/ on your computer)
  agents/
    <id>.json               the agent's draft
    <id>.model.json         the latest trained model
    <id>.crfsuite           entity model
    <id>.secrets.json       keys (permissions 600)
    <id>.versions/<n>.json  published versions (+ <n>.crfsuite)
    <id>.files/             files uploaded for the `file` step
    <id>.sessions.migrated/ old conversation files, already imported into parla.db (can be deleted)
  parla.db                  conversations, login sessions and audit log (SQLite, permissions 600; not with Postgres)
  parla.db-wal, -shm        parla.db's journal while it runs (part of the database)
  users.json                users (permissions 600)
  models/                   embeddings, voice and audio cache (can be downloaded again)
```

## Backups

Back up the whole data folder; `models/` can be excluded (it's downloaded again). With Parla stopped, copying the
folder as is is enough. While it runs, `parla.db` is being written and a plain copy can come out inconsistent:
first take a copy with SQLite's `.backup` (safe while it runs) and leave the live database out of the archive.
Backups contain conversations, users and keys: keep them somewhere private.

```sh
# on your computer / systemd
sqlite3 data/parla.db ".backup 'data/parla.db.backup'"
tar czf parla-$(date +%F).tar.gz --exclude=models --exclude=parla.db --exclude='parla.db-*' data/

# Docker / Compose (container parla, volume parla-data; with compose: docker compose exec parla …, volume parla_parla-data)
docker exec parla python -c "import sqlite3; sqlite3.connect('/data/parla.db').backup(sqlite3.connect('/data/parla.db.backup'))"
docker run --rm -v parla-data:/data:ro -v "$PWD":/backup python:3.12-slim \
  tar czf /backup/parla-$(date +%F).tar.gz --exclude=models --exclude=parla.db --exclude='parla.db-*' -C /data .

# Kubernetes: the Helm chart's backup CronJob (backup.enabled) or deploy/k8s/backup.yaml do this every night
kubectl -n parla create job --from=cronjob/parla-backup backup-now
```

On Kubernetes, restoring is in [kubernetes.md](kubernetes.md#restoring).

Restoring: with Parla stopped, extract into the empty folder / volume, rename `parla.db.backup` to `parla.db` and
start it. In Docker:

```sh
docker run --rm -v parla-data:/data -v "$PWD":/backup python:3.12-slim \
  sh -c 'tar xzf /backup/parla-AAAA-MM-DD.tar.gz -C /data && mv /data/parla.db.backup /data/parla.db && chown -R 10001:10001 /data'
```

(`AAAA-MM-DD` is the backup's date, YYYY-MM-DD.) To move a single bot to another installation use **Export
agent** / **Import agent**; it doesn't carry versions, conversations or keys.

## Upgrades

Data lives outside the image; on startup, Parla migrates old files by itself. Make a backup first. Coming from a
version that kept conversations in `agents/<id>.sessions/`: on startup they're imported into `parla.db` (without
overwriting what's already there) and the folder is renamed to `<id>.sessions.migrated`; it's never deleted, and
files that can't be read are reported and left there.

```sh
docker compose build && docker compose up -d                       # Compose
helm upgrade parla ./deploy/helm/parla -n parla -f values.yaml --set image.tag=1.1.0   # Helm (rollback: helm rollback)
kubectl -n parla set image deploy/parla parla=ghcr.io/pedroslev/parla-nlu:1.1.0       # Kustomize manifests
```

A restart drops conversations in the middle of a request; login sessions are kept.

## As a service (without containers)

### Linux (systemd)

`/etc/systemd/system/parla.service`:

```ini
[Unit]
Description=Parla
After=network.target

[Service]
User=parla
WorkingDirectory=/opt/parla
Environment=PARLA_DATA=/var/lib/parla
Environment=PARLA_EMBED_CACHE=/var/lib/parla/models/embeddings
Environment=PARLA_FUNCTIONS=0
ExecStart=/opt/parla/.venv/bin/python app.py 8000
Restart=on-failure

[Install]
WantedBy=multi-user.target
```

```sh
sudo systemctl daemon-reload
sudo systemctl enable --now parla
journalctl -u parla -f
```

### macOS (launchd)

`~/Library/LaunchAgents/com.parla.plist`:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>com.parla</string>
  <key>WorkingDirectory</key><string>/Users/vos/parla</string>
  <key>ProgramArguments</key>
  <array>
    <string>/Users/vos/parla/.venv/bin/python</string>
    <string>app.py</string>
    <string>8000</string>
  </array>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>StandardOutPath</key><string>/tmp/parla.log</string>
  <key>StandardErrorPath</key><string>/tmp/parla.log</string>
</dict>
</plist>
```

```sh
launchctl load ~/Library/LaunchAgents/com.parla.plist
```
