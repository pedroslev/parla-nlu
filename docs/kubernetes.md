# Kubernetes and Helm

**English** · [Español](kubernetes_es.md)

Two ways to run Parla on Kubernetes:

- **Helm chart** (`deploy/helm/parla`): the full-featured path. Ingress with only the public routes, SSO, metrics,
  traces, nightly backups, NetworkPolicy and an optional Ollama, all as values.
- **Kustomize manifests** (`deploy/k8s`, `deploy/k3s`): a plain Deployment, PVC and Service plus examples to edit
  by hand (Ingress, NetworkPolicy, backup CronJob, ServiceMonitor).

Both use the same image and the same security settings. With SQLite (the default) the rule is **one replica**;
with Postgres you can run several ([High availability](#high-availability)). Read
[deployment.md](deployment.md) for the variables, the Origin guard and the data layout, and
[security.md](security.md#before-exposing-it-to-the-internet) before exposing anything.

## One replica with SQLite

With SQLite, conversations, login sessions and the audit log are in `parla.db` on the data volume, and two pods on
the same file would overwrite each other, so:

- `replicaCount` is `1` (`0` stops Parla, for example to restore a backup). The chart refuses more than 1 without
  Postgres.
- The strategy is `Recreate`: the old pod stops before the new one starts. An upgrade or a config change has a
  few seconds of downtime, and a request in flight is dropped. Login sessions survive.
- The data volume is `ReadWriteOnce`. Anything else that mounts it (the backup job) has to run on the same node.
- The agents' secrets are encrypted at rest (`secrets.encrypt: true`, the default): without `secretKey.value` or
  `secretKey.existingSecret`, the chart creates `<release>-secret-key` with a random `PARLA_SECRET_KEY`, reuses it on
  every `helm upgrade` (`lookup`) and keeps it on uninstall. **Back it up** (losing it loses the secrets). With
  `helm template` / Argo CD / Flux, `lookup` sees nothing and would make a new key on every render: use
  `secretKey.existingSecret` there. See [security.md](security.md#secrets-encryption-at-rest).

For no downtime on upgrades and node failures, move to Postgres and several replicas (next section).

## High availability

Several Parla pods behind the same Service, sharing a Postgres database and a ReadWriteMany data volume. How the
replicas cooperate (per-conversation locks, the bus over `LISTEN/NOTIFY`, queues, the leader) is in
[deployment.md](deployment.md#postgres-and-high-availability).

Requirements:

- **Postgres 13+** you run: a managed service (RDS, Cloud SQL, Azure Database, Neon…) or an operator such as
  CloudNativePG. Each pod opens up to `PARLA_DB_POOL` (20) + `PARLA_DB_LOCKS` (32) + 3 connections; with 3 pods
  keep `max_connections` ≥ 200 or lower the pools (`database.pool`). A PgBouncer in **session** mode works;
  transaction mode doesn't (advisory locks and `LISTEN` need a session).
- **A ReadWriteMany volume** for `/data` (agents, versions, trained models, users, secrets, uploaded files): EFS,
  Filestore, Azure Files, NFS, CephFS, Longhorn RWX. The chart mounts `/data/models` (embeddings, voice) as a per-pod
  `emptyDir`, so bake the embedding model into the image (`BAKE_EMBED_DIR`) or each new pod downloads 1.2 GB.
- **`secretKey`**: the same `PARLA_SECRET_KEY` in every pod (signs phone audio URLs, encrypts the secrets vault);
  the generated one (`secrets.encrypt`) is shared too, but prefer `existingSecret` in HA.

```yaml
# values-ha.yaml
replicaCount: 3
database:
  existingSecret: parla-db          # key PARLA_DATABASE_URL: postgresql://parla:…@pg.internal:5432/parla?sslmode=require
secretKey:
  existingSecret: parla-secret-key  # key PARLA_SECRET_KEY: openssl rand -hex 32
persistence:
  accessModes: [ReadWriteMany]
  storageClass: efs-sc              # your RWX class (or existingClaim)
# autoscaling: {enabled: true, minReplicas: 2, maxReplicas: 6, targetCPUUtilizationPercentage: 70}
```

With CloudNativePG:

```yaml
apiVersion: postgresql.cnpg.io/v1
kind: Cluster
metadata: {name: parla-pg, namespace: parla}
spec:
  instances: 2                      # a primary and a hot standby: the operator fails over
  storage: {size: 10Gi}
  bootstrap: {initdb: {database: parla, owner: parla}}
```

and `database.existingSecret: parla-pg-app`, `database.secretKey: uri` (the operator's app secret points at the
read-write service).

What the chart does when `replicaCount > 1` or `autoscaling.enabled`: it refuses to render without
`database.url`/`existingSecret`, `secretKey` and a ReadWriteMany volume; uses `RollingUpdate` (`maxUnavailable: 0`);
creates a PodDisruptionBudget (`podDisruptionBudget.maxUnavailable: 1`) and, with `autoscaling.enabled`, an HPA on
CPU. The readiness probe is `/readyz`, which fails when the pod can't reach the database.

Sizing: each pod needs the embedding model in memory (~1 GB; requests 1.5 Gi, limit 3 Gi as with one replica);
throughput is CPU-bound by the embeddings, so it grows with CPU per pod and with pods, while Postgres stays light (a
few small queries per turn). Measured on one 8-CPU laptop VM (k3d, Postgres in the same VM, `PARLA_EMBED_WORKERS=1`,
`tests/perf/load.py` through the Service at 50 concurrent conversations): 57 turns/s with 1 pod, 97 with 3, 0 errors.

Failover, measured with the leader pod force-deleted in the middle of a 60 s load test at 30 concurrent
conversations: 14 failed requests of ~5,500 (the ones in flight on that pod or sent to it before the Service dropped
it; clients retry), a new leader within 5 s, the replacement pod serving 5 s later, no lost or duplicated turns.

Stays per pod: loaded models and caches, metrics (scrape every pod; `parla_cluster_leader` sums to 1), the channel
status shown on the Agent page, and a phone call's media WebSocket (if that pod dies, the call drops).

Moving an existing install: scale to 0, run `python -m parla.migrate sqlite-to-postgres /data/parla.db` once in a
pod that mounts the old volume with `PARLA_DATABASE_URL` set, copy the rest of `/data` (without `models/` and
`parla.db*`) to the RWX volume, then install with the HA values. Backups: `pg_dump` (or the operator's backups) for
the database plus the data volume; the chart's `backup` CronJob still archives `/data` but only snapshots `parla.db`
with SQLite.

Kustomize: `deploy/k8s-ha` is the same as `deploy/k8s` with 3 replicas, RollingUpdate, a PDB, `/readyz`, a per-pod
`models` volume and a `parla-ha` Secret with the two variables (see its `kustomization.yaml`).

## Helm

```sh
helm install parla ./deploy/helm/parla -n parla --create-namespace -f values.yaml
kubectl -n parla rollout status deploy/parla
```

The chart has no repository yet: install it from a checkout of this repo. All values are listed in
[deploy/helm/parla/README.md](../deploy/helm/parla/README.md).

### Image

`image.tag` defaults to the chart's `appVersion` (the Parla release the chart was cut with). Until the first tagged
release is published on ghcr.io, use `image.tag: edge` (follows `main`). `image.variant: voice` picks the image with
ffmpeg, faster-whisper and piper (`0.9.0-voice`, `edge-voice`); give it `resources.limits.memory: 4Gi`.

Images with the Anthropic SDK (`--build-arg INSTALL_PROVIDERS=1`) or the embedding model baked in
(`--build-arg BAKE_EMBED_DIR=/opt/embeddings`) aren't published: build them (see
[deployment.md](deployment.md#building-it-yourself)), push them to your registry and set `image.repository` and
`image.tag`. Alternatively `embeddings.preload: true` downloads the embedding model (~1.2 GB) into the volume with an
init container before Parla starts, so the first training doesn't wait for it.

### First steps

```sh
kubectl -n parla port-forward deploy/parla 8000:8000      # then open http://127.0.0.1:8000
```

Use **8000 on both sides**: the browser's `Origin` is checked against Parla's own port
([Origin](deployment.md#the-origin-guard)). Then create the first user (**Users → New user**). It becomes the owner,
and from then on login is required. Until a user exists, anyone who reaches the UI is the owner, so do this
before publishing the admin UI. From the command line:

```sh
curl -s http://127.0.0.1:8000/api/users -H 'Content-Type: application/json' \
  -d '{"name":"admin","password":"<a long password>","role":"owner"}'
```

`port-forward` connects to the pod's own loopback, which is also where the owner can be created when SSO is on and
where `PARLA_OIDC_ONLY` still accepts the owner's password (break-glass).

### Ingress: public routes only, or the whole site

With `ingress.enabled` and the default `ingress.exposeAdmin: false`, the Ingress publishes **only**:

| Path | Type | What it is |
|---|---|---|
| `/api/v1/` | Prefix | Bots API, the widget chat, and the WhatsApp, Telegram and phone (Twilio, jambonz) webhooks |
| `/files/` | Prefix | Files sent by the **Send a file** step |
| `/static/widget.js` | Exact | The widget script. It loads nothing else from `/static/`. |

Everything else (`/`, `/api/agents`, `/metrics`…) gets the ingress controller's 404. Administer with
`port-forward`.

With `ingress.exposeAdmin: true` the whole site is published and the chart adds `ingress.hosts` to `PARLA_HOSTS`
(without it, the UI opens but every `/api/` call answers 403). With `ingress.tls` it also sets
`PARLA_SECURE_COOKIE=1`. Create the owner first. `/metrics` is then reachable through the domain too, but answers
401 without the token.

Set `config.publicUrl` to the public `https://` address: Parla uses it for the webhook URLs it shows and registers,
for the Twilio signature check and for the SSO redirect URI.

For ingress-nginx, raise the body limit and the read timeout (audio and PDFs travel as base64; local AI and voice take
seconds; Twilio waits ~15 s):

```yaml
ingress:
  annotations:
    nginx.ingress.kubernetes.io/proxy-body-size: 25m
    nginx.ingress.kubernetes.io/proxy-read-timeout: "3600"
    nginx.ingress.kubernetes.io/proxy-send-timeout: "3600"
    nginx.ingress.kubernetes.io/proxy-buffering: "off"
```

### Example production values

```yaml
# values.yaml
image:
  tag: "0.9.0"
config:
  lang: en
  publicUrl: https://bots.example.com
  retentionDays: 180
ingress:
  enabled: true
  className: nginx
  exposeAdmin: true                         # SSO needs the UI on the domain
  hosts: [bots.example.com]
  tls: [{secretName: parla-tls, hosts: [bots.example.com]}]
  annotations:
    cert-manager.io/cluster-issuer: letsencrypt
    nginx.ingress.kubernetes.io/proxy-body-size: 25m
    nginx.ingress.kubernetes.io/proxy-read-timeout: "3600"
    nginx.ingress.kubernetes.io/proxy-send-timeout: "3600"
    nginx.ingress.kubernetes.io/proxy-buffering: "off"
oidc:
  issuer: https://kc.example.com/realms/acme
  clientId: parla
  existingSecret: parla-oidc                # key: client-secret
  roleClaim: groups
  roleMap: parla-owners:owner,parla-editors:editor,parla-support:agent
  label: Acme
metrics:
  enabled: true
  existingSecret: parla-metrics             # key: PARLA_METRICS_TOKEN
  serviceMonitor: {enabled: true, labels: {release: kube-prometheus-stack}}
otel:
  endpoint: http://otel-collector.observability:4318
  resourceAttributes: deployment.environment=prod
backup:
  enabled: true
  keep: 14
networkPolicy:
  enabled: true
  ingress:
    namespaces: [ingress-nginx, monitoring]
  egress:
    extra:                                  # the OTel collector is cluster-internal: allow it explicitly
      - to: [{namespaceSelector: {matchLabels: {kubernetes.io/metadata.name: observability}}}]
        ports: [{port: 4318, protocol: TCP}]
ollama:
  enabled: true
  models: [qwen2.5:1.5b]
resources:
  requests: {cpu: 500m, memory: 2Gi}
  limits: {memory: 4Gi}
```

```sh
kubectl create namespace parla
kubectl -n parla create secret generic parla-oidc --from-literal=client-secret='<the client secret>'
kubectl -n parla create secret generic parla-metrics --from-literal=PARLA_METRICS_TOKEN="$(openssl rand -hex 24)"
helm install parla ./deploy/helm/parla -n parla -f values.yaml
```

Secrets can also be given inline (`metrics.token`, `otel.headers`, `oidc.clientSecret`): the chart then creates them,
but the values end up in Helm's release history. Prefer `existingSecret`. The OIDC secret is mounted as a file
(`PARLA_OIDC_CLIENT_SECRET_FILE`), never as an environment variable.

### Local AI with Ollama

`ollama.enabled: true` adds an Ollama Deployment (`ollama/ollama`, pinned), a PVC for the models (`ollama.persistence`)
and a Service. An init container pulls `ollama.models` into the volume before Ollama starts (the first time it needs
internet; later starts find them there). In each agent set **AI → address** to
`http://<release>-ollama:11434` (with `helm install parla …`: `http://parla-ollama:11434`). The interface's
download button pulls more models through that same address.

With `networkPolicy.enabled`, Parla may reach Ollama on 11434, and Ollama only accepts connections from Parla.

### Metrics and traces

`metrics.enabled` sets `PARLA_METRICS=1`. Prometheus always scrapes from another pod, so it needs the token
(`metrics.existingSecret` or `metrics.token`): without one `/metrics` only answers the pod's own loopback.
`metrics.serviceMonitor.enabled` creates a `ServiceMonitor` (Prometheus Operator) that sends the token from the same
Secret, so the Secret has to be in Parla's namespace. Details in [observability.md](observability.md).

`otel.endpoint` turns on traces; `otel.headers` / `otel.existingSecret` carry the collector's API key
(`OTEL_EXPORTER_OTLP_HEADERS`). Any other variable goes in `extraEnv`.

### NetworkPolicy: egress is the SSRF mitigation

`http` steps, HTTP and MCP tools of the agent step, knowledge URL imports and the AI and voice providers are all
requests made **by the Parla pod** to an address an editor chose. Without egress rules an editor can reach your
cluster's services, the node network and the cloud metadata service (`169.254.169.254`, which hands out cloud
credentials on many providers). `networkPolicy.enabled: true` creates a policy on the Parla pod:

- **Ingress:** port 8000 only from the namespaces in `networkPolicy.ingress.namespaces` (default `ingress-nginx`,
  `kube-system` for k3s' Traefik, `monitoring`). `kubectl port-forward` and the kubelet's probes aren't affected.
- **Egress:** DNS (port 53 to any namespace), and TCP 443 to `0.0.0.0/0` **except** `10.0.0.0/8`, `172.16.0.0/12`,
  `192.168.0.0/16`, `169.254.0.0/16` (metadata), `100.64.0.0/10` and `127.0.0.0/8`. Plus Ollama when enabled.
- Anything internal Parla must call (an OTel collector, an internal API used by `http` steps, an Ollama outside the
  chart, a plain-HTTP endpoint) goes in `networkPolicy.egress.extra` as standard `NetworkPolicyEgressRule`s. Other
  ports to the internet: `networkPolicy.egress.internet.ports`.

The policy only works if the cluster's CNI enforces NetworkPolicy (Calico, Cilium, Antrea, k3s' built-in
kube-router…). kind's default CNI and some managed defaults don't: the object is accepted and ignored. Check it:

```sh
kubectl -n parla exec deploy/parla -- python -c \
  "import socket; socket.create_connection(('169.254.169.254', 80), timeout=4)"   # must fail
```

Node-local DNS caches (NodeLocal DNSCache on `169.254.20.10`) fall inside the blocked link-local range: allow that
address on port 53 in `egress.extra`. IPv6 egress isn't covered by the IPv4 `except` list: on dual-stack clusters
add an IPv6 rule of your own.

### Backups

`backup.enabled: true` creates a CronJob (`backup.schedule`, default 03:17 every day) that runs the Parla image
with the same security context and writes `/backup/parla-<UTC date>-<time>.tar.gz` to its own PVC
(`backup.persistence`), keeping the newest `backup.keep` (7). Each archive has:

- `parla.db`, copied with SQLite's online backup API (consistent while Parla keeps writing),
- `agents/` (drafts, trained models, versions, files and `*.secrets.json`), `users.json` and everything else in
  `/data`, except `models/` (downloaded again) and the live database files.

Archives contain conversations, users and keys: they are created with permissions 600. Because the data volume is
`ReadWriteOnce`, the job has a required pod affinity to the Parla pod (same node). That means it can't run while
Parla is stopped; with a `ReadWriteMany` data volume set `backup.sameNode: false`.

Run one now and check it:

```sh
kubectl -n parla create job --from=cronjob/parla-backup backup-now
kubectl -n parla logs -f job/backup-now       # wrote /backup/parla-20261126-155150.tar.gz (12979 bytes); removed 0 old
```

To ship each archive off the cluster, add an upload step. It runs after the snapshot as a second container with
the backup volume mounted read-only at `/backup`, as uid 10001:

```yaml
backup:
  enabled: true
  upload:
    image: amazon/aws-cli:2.22.0
    command: [sh, -c, 'f=$(ls /backup/parla-*.tar.gz | tail -1); aws s3 cp "$f" s3://my-bucket/parla/']
    envFrom: [{secretRef: {name: parla-backup-s3}}]   # AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY, AWS_DEFAULT_REGION
    env: [{name: HOME, value: /tmp}]
```

With `backup.persistence.enabled: false` the archive goes to an `emptyDir` and only the upload keeps it.

#### Restoring

Stop Parla, extract the archive into the data volume with the same script, start Parla:

```sh
helm upgrade parla ./deploy/helm/parla -n parla --reuse-values --set replicaCount=0
kubectl -n parla apply -f - <<'EOF'
apiVersion: v1
kind: Pod
metadata: {name: parla-restore}
spec:
  restartPolicy: Never
  securityContext: {runAsNonRoot: true, runAsUser: 10001, runAsGroup: 10001, fsGroup: 10001, seccompProfile: {type: RuntimeDefault}}
  containers:
    - name: restore
      image: ghcr.io/pedroslev/parla-nlu:0.9.0          # the same image as the Deployment
      # the newest archive; or name one: python /scripts/backup.py restore /backup/parla-20261126-031700.tar.gz
      command: [sh, -c, 'python /scripts/backup.py restore "$(ls /backup/parla-*.tar.gz | tail -1)"']
      securityContext: {allowPrivilegeEscalation: false, readOnlyRootFilesystem: true, capabilities: {drop: [ALL]}}
      volumeMounts:
        - {name: data, mountPath: /data}
        - {name: backup, mountPath: /backup, readOnly: true}
        - {name: scripts, mountPath: /scripts}
  volumes:
    - {name: data, persistentVolumeClaim: {claimName: parla-data}}
    - {name: backup, persistentVolumeClaim: {claimName: parla-backup}}
    - {name: scripts, configMap: {name: parla-backup}}
EOF
kubectl -n parla logs -f parla-restore && kubectl -n parla delete pod parla-restore
helm upgrade parla ./deploy/helm/parla -n parla --reuse-values --set replicaCount=1
```

The restore removes a stale `parla.db-wal` / `-shm` first (an old journal would be replayed over the restored
database) and overwrites the files in the archive; files that aren't in it are kept. To start from a clean volume,
delete the PVC's contents first. Login sessions in the archive are restored too. To restore an archive you
downloaded, `kubectl cp` it into a pod that mounts the backup PVC, or mount wherever you keep it.

### Upgrade and rollback

```sh
helm upgrade parla ./deploy/helm/parla -n parla -f values.yaml        # new chart and/or image.tag
helm history parla -n parla
helm rollback parla <revision> -n parla
```

Take a backup before upgrading (`kubectl create job --from=cronjob/parla-backup pre-upgrade`). Parla migrates old
data files by itself on startup; a rollback to an older image after a migration isn't guaranteed to read the new
format, so restore the pre-upgrade archive if you roll back across versions. The PVCs have
`helm.sh/resource-policy: keep`: `helm uninstall` leaves the data, backups and Ollama models in place (delete the
PVCs by hand to get rid of them).

## k3s quickstart (single node)

k3s ships Traefik, the `local-path` storage class and a NetworkPolicy controller, so the chart works as is:

```sh
curl -sfL https://get.k3s.io | sh -
export KUBECONFIG=/etc/rancher/k3s/k3s.yaml        # (sudo, or copy it to ~/.kube/config)
# Helm: https://helm.sh/docs/intro/install/
git clone https://github.com/pedroslev/parla-nlu && cd parla-nlu
cat > values.yaml <<'EOF'
image: {tag: edge}
config: {publicUrl: https://bots.example.com}
embeddings: {preload: true}
ingress:
  enabled: true
  className: traefik
  hosts: [bots.example.com]
  annotations:
    traefik.ingress.kubernetes.io/router.entrypoints: websecure
    traefik.ingress.kubernetes.io/router.tls: "true"
networkPolicy: {enabled: true}
backup: {enabled: true}
EOF
helm install parla ./deploy/helm/parla -n parla --create-namespace -f values.yaml
kubectl -n parla port-forward deploy/parla 8000:8000      # create the owner at http://127.0.0.1:8000
```

- Traefik serves its own self-signed certificate by default: for a real one use cert-manager (`ingress.tls` +
  `cert-manager.io/cluster-issuer`) or Traefik's ACME resolver.
- `local-path` keeps the data on the node's disk (`/var/lib/rancher/k3s/storage/`). On a single node that's fine; on
  several, the pod is tied to that node.
- Traefik runs in `kube-system`, which is in the default `networkPolicy.ingress.namespaces`.
- An image you built yourself, without a registry: `docker save parla:local | sudo k3s ctr images import -` and
  `image: {repository: docker.io/library/parla, tag: local, pullPolicy: Never}`.

## Kustomize manifests

`deploy/k8s` is a minimal base: ConfigMap (the variables, the optional ones commented), PVC, Deployment and Service.
`deploy/k3s` adds a Traefik Ingress.

```sh
kubectl create namespace parla
kubectl apply -n parla -k deploy/k8s           # or -k deploy/k3s
kubectl -n parla rollout status deploy/parla
```

The image is `ghcr.io/pedroslev/parla-nlu:edge`; pin a release or your registry with `images:` in
`kustomization.yaml`. Examples to edit and apply with `kubectl apply -n parla -f`:

| File | What it is |
|---|---|
| `deploy/k8s/ingress.yaml` | ingress-nginx + TLS, only `/api/v1/`, `/files/`, `/static/widget.js` (the whole site commented) |
| `deploy/k3s/ingress.yaml` | the same for Traefik |
| `deploy/k8s/networkpolicy.yaml` | the chart's default policy: ingress from the controller and monitoring, egress DNS + 443 public |
| `deploy/k8s/backup.yaml` | backup PVC + nightly CronJob, same archive format as the chart (restore with the chart's `files/backup.py`, or by hand: stop Parla, `tar xzf` into `/data` after deleting `parla.db-wal` and `-shm`) |
| `deploy/k8s/servicemonitor.yaml` | Prometheus Operator `ServiceMonitor` with the bearer token |

Secrets: `PARLA_METRICS_TOKEN` and `OTEL_EXPORTER_OTLP_HEADERS` come in through the commented `secretRef`s, the OIDC
client secret through the commented `oidc` volume (a file, `PARLA_OIDC_CLIENT_SECRET_FILE`). The commands to create
them are in the comments of `deploy/k8s/parla.yaml`.

## Production checklist

1. **Owner first.** Create it over `port-forward` before the DNS points at the Ingress or `exposeAdmin` is on.
2. **Pin the image** (`image.tag: "0.9.0"`, not `edge`) and keep the chart and image versions in your values file
   under version control.
3. **Public routes only** unless you need the UI on the domain (SSO does). With `exposeAdmin`, use TLS and check
   `PARLA_HOSTS` / `PARLA_SECURE_COOKIE` in `kubectl -n parla get deploy parla -o yaml`.
4. **`config.publicUrl`** set to the exact `https://` address the webhooks use.
5. **NetworkPolicy on**, on a CNI that enforces it, and verified with the metadata check above. Allow internal
   targets one by one in `egress.extra`.
6. **`config.functions: false`** (the default) unless you trust every editor: functions run code inside the pod.
7. **Secrets in `existingSecret`**, not inline values. Long random metrics token.
8. **Backups on** and shipped off the node (`backup.upload` or a snapshot of the backup volume); test a restore once.
9. **Retention:** `config.retentionDays` (or per agent) so conversations don't grow forever; `config.auditDays`.
10. **Resources:** 1.5–2 Gi requested, 3 Gi limit (4 Gi with voice), no CPU limit. `embeddings.preload: true` or a
    baked image if the cluster has no internet at startup.
11. **Storage:** a storage class with snapshots or replication if the node's disk is the only copy.
12. **Rate limits** at the ingress (Parla only limits login), and the body limit / read timeout annotations.
13. **Monitoring:** `metrics.enabled` + ServiceMonitor, the Grafana dashboard in `deploy/observability/`; keep
    `otel.content` off unless the trace backend is as private as the data.
14. Review [security.md](security.md#before-exposing-it-to-the-internet).
