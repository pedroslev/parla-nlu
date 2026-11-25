# Deployment

**English** · [Español](deployment_es.md)

Parla is **a single** Python **process** (`ThreadingHTTPServer`, one thread per request) with no database:
everything is stored as files in the data folder. That shapes how it's deployed:

- **One replica per data folder.** Login sessions and loaded models live in memory, and agents are saved to files
  with no cross-process locking. Two instances on the same data overwrite each other; after a restart, users have
  to log in again.
- **The admin interface is used from `127.0.0.1` / `localhost`**, or through a domain you add to `PARLA_HOSTS`.
  See [Origin](#the-origin-guard).
- Read [security.md](security.md#before-exposing-it-to-the-internet) before exposing it.

| Variable | In the container | What for |
|---|---|---|
| `PARLA_HOST` | `0.0.0.0` | Where it listens. Unset: `127.0.0.1`. |
| `PARLA_DATA` | `/data` | Agents, versions, conversations, `users.json`, voice models. |
| `PARLA_EMBED_CACHE` | `/data/models/embeddings` | Embedding model cache (fastembed, ~1.2 GB). |
| `HF_HOME` | `/data/models/hf` | Hugging Face cache (fastembed downloads). |
| `PARLA_FUNCTIONS` | `0` | «función» (function) steps (the bots' code). Off in the image; `1` to turn them on. |
| `PARLA_WHISPER` | `base` | Dictation model (`tiny` if the machine is slow). |
| `PARLA_HOSTS` | | Domains (`host` or `host:port`, comma-separated) that can also be used to reach the interface and `/api/`. |
| `PARLA_SECURE_COOKIE` | | `1`: the session cookie always has `Secure` (behind HTTPS). |
| `PARLA_USERS` | | A different path for `users.json`. |

The port is the argument to `app.py` (the image uses `8000`). The Ollama address isn't a variable: it's configured
per agent in the interface (**IA → dirección**, AI → address).

## On your computer

```sh
make run                          # or: .venv/bin/python app.py
.venv/bin/python app.py 8080      # another port
```

It listens on `127.0.0.1` unless you set `PARLA_HOST`.

## Docker

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
docker compose logs -f parla
```

With the `ai` profile, pull a model and point the agent at Ollama:

```sh
docker compose exec ollama ollama pull qwen2.5:0.5b
```

In the agent: **IA → dirección** (AI → address) `http://ollama:11434` (or the interface's download button, which
uses that address). Ollama doesn't publish ports: only Parla talks to it.

Data is kept in the `parla-data` and `ollama-models` volumes. `docker compose down` doesn't delete them;
`down -v` does.

## Kubernetes

Manifests in `deploy/k8s/` with no fixed namespace: ConfigMap, PVC (5 Gi), Deployment and Service.

```sh
docker build -t registry.example.com/parla:1.0.0 . && docker push registry.example.com/parla:1.0.0
# in deploy/k8s/kustomization.yaml uncomment "images:" with that name and version
kubectl create namespace parla
kubectl apply -n parla -k deploy/k8s
kubectl -n parla rollout status deploy/parla
```

What the Deployment includes:

- `replicas: 1` and `strategy: Recreate`: the old pod shuts down before the new one starts (the PVC is
  `ReadWriteOnce` and there can't be two Parlas on the same data). An upgrade has a few seconds of downtime.
- Non-root (uid/gid `10001`, `fsGroup` for the volume), `readOnlyRootFilesystem`, no capabilities, no service
  account token. `/tmp` is an `emptyDir`.
- Probes on `GET /` (returns the static page, doesn't touch models or disk).
- Configuration goes in the `parla` ConfigMap. There's no Secret: Parla doesn't read secrets from variables; bot
  keys and users live in the volume.

### Administering

```sh
kubectl -n parla port-forward deploy/parla 8000:8000     # then open http://127.0.0.1:8000
```

Use **8000 on both sides** (because of the Origin guard).

### Ingress

`deploy/k8s/ingress.yaml` is an example (ingress-nginx + TLS) that publishes **only** `/api/v1/`, `/files/` and
`/static/widget.js`, which is what the widget and your integrations need. Edit the host, the class and the
certificate and apply it separately:

```sh
kubectl apply -n parla -f deploy/k8s/ingress.yaml
```

Don't publish `/` or all of `/api/`: with no users created Parla doesn't ask for a login, and the interface over a
domain needs `PARLA_HOSTS` (see below). If your bots send files (the «Enviar un archivo», Send a file, step), also
publish `/files/`.

The WhatsApp and Telegram webhooks (`/api/v1/bots/{bot}/whatsapp` and `/telegram`) are under `/api/v1/`, so these
examples already publish them. Set `PARLA_PUBLIC_URL` to the public address (`https://bots.example.com`) so Parla
can show the webhook URL and connect Telegram. See [channels.md](channels.md).

## k3s

k3s already ships with Traefik and the `local-path` storage class (the default), so the base works as-is.
`deploy/k3s/` adds a Traefik Ingress with the same public routes:

```sh
# image without a registry: import it into k3s's containerd
docker build -t parla:latest . && docker save parla:latest | sudo k3s ctr images import -
# edit the host in deploy/k3s/ingress.yaml
kubectl create namespace parla
kubectl apply -n parla -k deploy/k3s
```

- `local-path` stores data on the node's disk (`/var/lib/rancher/k3s/storage/`): if the pod moves to another node,
  it won't see it. On a single-node cluster it doesn't matter; on several, pin the node or use other storage.
- The certificate: Traefik uses its own by default; for a real one, use cert-manager or Traefik's ACME resolver.

## The Origin guard

Every request to `/api/` with an `Origin` that isn't `127.0.0.1:<port>` or `localhost:<port>` (the port Parla
listens on) or one of `PARLA_HOSTS` is rejected with 403, except the widget's public routes. Also, a request whose
`Host` isn't local or in `PARLA_HOSTS` is rejected with 403 unless it carries an API key or is the widget chat
(against DNS rebinding). This protects your Parla from pages you open in your browser. Consequences:

- **The full interface behind a domain (`https://bots.midominio.com`) needs
  `PARLA_HOSTS=bots.midominio.com`.** Without it, the page opens but all of `/api/` (login included) responds 403.
  With HTTPS, add `PARLA_SECURE_COOKIE=1` or have the proxy send `X-Forwarded-Proto: https`. «Conectar con IA»
  (Connect to AI) still only works from `127.0.0.1` / `localhost`.
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
    proxy_read_timeout 120s;           # local AI and voice take seconds

    location /api/v1/ { proxy_pass http://127.0.0.1:8000; }
    location = /static/widget.js { proxy_pass http://127.0.0.1:8000; }
    location /files/ { proxy_pass http://127.0.0.1:8000; }
    location / { return 404; }
}
```

- The widget is loaded from `https://bots.midominio.com/static/widget.js` and talks to that same server. Add the
  site where you embed it in **Widget web → sitios autorizados** (Web widget → authorized sites).
- WhatsApp and Telegram call `/api/v1/bots/{bot}/whatsapp` and `/telegram`, already covered by `/api/v1/` (see
  [channels.md](channels.md)). Don't rate-limit them too tightly: Meta and Telegram retry when they get errors.
- Parla has no rate limiting of its own (except on login): add it at the proxy.

## First login and users

**With no users created, Parla doesn't ask for a login**: anyone who reaches the interface is the owner. There's
no default password. So, before publishing anything:

1. Go in through `127.0.0.1` (or the tunnel / port-forward).
2. In **Usuarios** (Users), create the first user: it becomes the owner and from then on login is required.
3. Create the others with the minimum role and, for integrations, API keys.

Changing a password: **Usuarios → editar** (Users → edit). Only an owner can do it, for their own or someone
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

## Resources

| | CPU | Memory | Disk |
|---|---|---|---|
| Base (text, no AI) | 0.25 core idle; spikes while training | ~1 GB with the model loaded | 2 GB |
| With voice | +1 core while transcribing | +0.5–1 GB | +0.5 GB |
| Ollama `qwen2.5:0.5b` | 1–2 cores per reply | +1 GB | +0.5 GB |

Measured: with the embedding model loaded the process uses ~970 MB. The Deployment requests 1.5 Gi and limits to
3 Gi; raise it to 4 Gi with voice. It has no CPU limit on purpose (training is a short spike). Conversations grow
without limit: they aren't deleted automatically.

## Where the data lives

```
/data   (or data/ on your computer)
  agents/
    <id>.json               the agent's draft
    <id>.model.json         the latest trained model
    <id>.crfsuite           entity model
    <id>.secrets.json       keys (permissions 600)
    <id>.versions/<n>.json  published versions (+ <n>.crfsuite)
    <id>.sessions/<sid>.json  one conversation per file
  users.json                users (permissions 600)
  models/                   embeddings, voice and audio cache (can be downloaded again)
```

## Backups

Copy the whole data folder, with Parla stopped or at a quiet moment. `models/` can be excluded (it's downloaded
again). Backups contain conversations, users and keys: keep them somewhere private.

```sh
# on your computer / systemd
tar czf parla-$(date +%F).tar.gz --exclude=models data/

# Docker / Compose (the volume is called parla-data; with compose: parla_parla-data)
docker run --rm -v parla-data:/data:ro -v "$PWD":/backup python:3.12-slim \
  tar czf /backup/parla-$(date +%F).tar.gz --exclude=models -C /data .

# Kubernetes (the image has no tar: copy with Python)
kubectl -n parla exec deploy/parla -- python -c \
  "import tarfile,sys; t=tarfile.open(fileobj=sys.stdout.buffer,mode='w|gz'); t.add('/data','.',filter=lambda i: None if i.name.startswith('./models') else i); t.close()" \
  > parla-$(date +%F).tar.gz
```

Restoring: with Parla stopped, extract into the empty folder / volume and start it. In Docker:

```sh
docker run --rm -v parla-data:/data -v "$PWD":/backup python:3.12-slim \
  sh -c 'tar xzf /backup/parla-AAAA-MM-DD.tar.gz -C /data && chown -R 10001:10001 /data'
```

(`AAAA-MM-DD` is the backup's date, YYYY-MM-DD.) To move a single bot to another installation use «Exportar
agente» / «Importar agente» (Export agent / Import agent); it doesn't carry versions, conversations or keys.

## Upgrades

Data lives outside the image; on startup, Parla migrates old files by itself. Make a backup first.

```sh
docker compose build && docker compose up -d                       # Compose
docker build -t registry.example.com/parla:1.1.0 . && docker push registry.example.com/parla:1.1.0
kubectl -n parla set image deploy/parla parla=registry.example.com/parla:1.1.0   # Kubernetes
```

A restart drops login sessions (users have to log in again) and conversations in the middle of a request.

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
