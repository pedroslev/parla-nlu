# Parla Helm chart

Runs [Parla](https://github.com/pedroslev/parla-nlu) on Kubernetes: one replica on a persistent volume (or several on Postgres), hardened pod,
an Ingress with only the public routes, and optional SSO, metrics, traces, nightly backups, NetworkPolicy and Ollama.
The full guide (production values, k3s, backup/restore, upgrades, checklist) is in
[docs/kubernetes.md](../../../docs/kubernetes.md) ([español](../../../docs/kubernetes_es.md)).

```sh
helm install parla ./deploy/helm/parla -n parla --create-namespace -f values.yaml
kubectl -n parla port-forward deploy/parla 8000:8000      # http://127.0.0.1:8000, create the owner first
```

Until the first tagged release is on ghcr.io, set `image.tag: edge`.

## Values

| Key | Default | Description |
|---|---|---|
| `image.repository` | `ghcr.io/pedroslev/parla-nlu` | Image. |
| `image.tag` | `""` (= `appVersion`) | `edge` follows `main`. |
| `image.variant` | `""` | `voice`: appends `-voice` to the tag (ffmpeg, faster-whisper, piper). |
| `image.pullPolicy` | `IfNotPresent` | |
| `imagePullSecrets` | `[]` | |
| `nameOverride`, `fullnameOverride` | `""` | |
| `replicaCount` | `1` | With SQLite `0` or `1` (`Recreate`; `0` stops Parla, restores). More than 1 needs `database`, `secretKey` (or `secrets.encrypt`, the default) and a ReadWriteMany volume: `RollingUpdate` + PDB ([high availability](../../../docs/kubernetes.md#high-availability)). |
| `database.url` / `database.existingSecret` / `database.secretKey` | `""` / `""` / `PARLA_DATABASE_URL` | Postgres (`postgresql://…`) instead of SQLite. `url` creates a Secret; better an existing one (CloudNativePG: `<cluster>-app`, key `uri`). |
| `database.pool` | `null` | `PARLA_DB_POOL`: query connections per pod (default 20). |
| `secretKey.value` / `secretKey.existingSecret` / `secretKey.secretKey` | `""` / `""` / `PARLA_SECRET_KEY` | Same random value in every replica: signs phone audio URLs and encrypts the agents' secrets at rest. |
| `secrets.encrypt` | `true` | Encrypt per-agent secrets (AES-256-GCM). Without `secretKey.value`/`existingSecret` the chart generates `PARLA_SECRET_KEY` in `<release>-secret-key`, reuses it on upgrades (`lookup`) and keeps it on uninstall (`helm.sh/resource-policy: keep`). Back it up. |
| `autoscaling.enabled`, `minReplicas`, `maxReplicas`, `targetCPUUtilizationPercentage` | `false`, `2`, `6`, `70` | HPA on CPU (needs Postgres, like `replicaCount > 1`). |
| `podDisruptionBudget.maxUnavailable` | `1` | PDB created with more than one replica. |
| `config.lang` | `""` | `PARLA_LANG`: `en`, `es` or `pt`. |
| `config.publicUrl` | `""` | `PARLA_PUBLIC_URL`: public `https://` address (webhooks, SSO). |
| `config.hosts` | `[]` | `PARLA_HOSTS`. `ingress.hosts` are added when `ingress.exposeAdmin`. |
| `config.functions` | `false` | `PARLA_FUNCTIONS`: code steps run inside the pod. |
| `config.whisper` | `base` | `PARLA_WHISPER`: dictation model (voice image). |
| `config.retentionDays` | `null` | `PARLA_RETENTION_DAYS`. |
| `config.auditDays` | `null` | `PARLA_AUDIT_DAYS` (Parla's default: 365). |
| `config.secureCookie` | `null` | `PARLA_SECURE_COOKIE`. `null`: on when `exposeAdmin` with `ingress.tls`. |
| `config.logFormat` | `""` | `PARLA_LOG_FORMAT`: `json`. |
| `metrics.enabled` | `false` | `PARLA_METRICS=1`. |
| `metrics.token` | `""` | Token; the chart creates a Secret. Prefer `existingSecret`. |
| `metrics.existingSecret` | `""` | Secret with the token under `metrics.secretKey`. |
| `metrics.secretKey` | `PARLA_METRICS_TOKEN` | |
| `metrics.serviceMonitor.enabled` | `false` | Prometheus Operator `ServiceMonitor` with the bearer token. Needs a token. |
| `metrics.serviceMonitor.interval` | `30s` | |
| `metrics.serviceMonitor.labels` | `{}` | e.g. `{release: kube-prometheus-stack}`. |
| `otel.endpoint` | `""` | `PARLA_OTEL_ENDPOINT`: OTLP/HTTP base URL. |
| `otel.serviceName` | `""` | `OTEL_SERVICE_NAME`. |
| `otel.resourceAttributes` | `""` | `OTEL_RESOURCE_ATTRIBUTES`. |
| `otel.content` | `false` | `PARLA_OTEL_CONTENT=1`. |
| `otel.headers` / `otel.existingSecret` / `otel.secretKey` | `""` / `""` / `OTEL_EXPORTER_OTLP_HEADERS` | Collector headers (API keys), from a Secret. |
| `oidc.issuer`, `oidc.clientId` | `""` | `PARLA_OIDC_ISSUER`, `PARLA_OIDC_CLIENT_ID`: both turn SSO on. |
| `oidc.clientSecret` / `oidc.existingSecret` / `oidc.secretKey` | `""` / `""` / `client-secret` | Mounted as a file at `/run/secrets/parla-oidc/<key>` + `PARLA_OIDC_CLIENT_SECRET_FILE`. |
| `oidc.scopes`, `oidc.roleClaim`, `oidc.roleMap`, `oidc.defaultRole`, `oidc.label` | `""` | `PARLA_OIDC_SCOPES`, `_ROLE_CLAIM`, `_ROLE_MAP` (`group:role,…`), `_DEFAULT_ROLE`, `_LABEL`. |
| `oidc.only` | `false` | `PARLA_OIDC_ONLY=1`. |
| `oidc.logout` | `true` | `false`: `PARLA_OIDC_LOGOUT=0` (Okta). |
| `extraEnv` | `[]` | More env entries (`PARLA_<PROVIDER>_BASE_URL`, `OTEL_*`…). |
| `extraEnvFrom` | `[]` | `envFrom` sources. |
| `embeddings.preload` | `false` | Init container that downloads the embedding model (~1.2 GB) into the volume. |
| `embeddings.model` | `google/embeddinggemma-300m` | Must match `MODEL` in `parla/server.py`. |
| `persistence.enabled` | `true` | `false`: `emptyDir` (tests only). |
| `persistence.existingClaim` | `""` | |
| `persistence.storageClass` | `""` | Cluster default. |
| `persistence.accessModes` | `[ReadWriteOnce]` | |
| `persistence.size` | `5Gi` | |
| `persistence.annotations` | `{}` | The PVC always has `helm.sh/resource-policy: keep`. |
| `resources` | requests `250m` / `1536Mi`, limit `3Gi` | 4Gi with voice. No CPU limit on purpose. |
| `podSecurityContext` | uid/gid/fsGroup `10001`, non-root, seccomp `RuntimeDefault` | |
| `securityContext` | read-only root, no privilege escalation, drop `ALL` | |
| `podAnnotations`, `podLabels`, `nodeSelector`, `tolerations`, `affinity` | `{}` / `[]` | |
| `readinessProbe`, `livenessProbe` | `GET /readyz`, `GET /` | `/readyz` fails (503) when the database doesn't answer. |
| `service.type`, `service.port`, `service.annotations` | `ClusterIP`, `8000`, `{}` | |
| `ingress.enabled` | `false` | |
| `ingress.className` | `""` | |
| `ingress.annotations` | `{}` | |
| `ingress.hosts` | `[bots.example.com]` | |
| `ingress.tls` | `[]` | |
| `ingress.exposeAdmin` | `false` | `false`: only `/api/v1/`, `/files/`, `/static/widget.js`. `true`: the whole site, hosts added to `PARLA_HOSTS`. |
| `networkPolicy.enabled` | `false` | Policy on the Parla pod (needs an enforcing CNI). |
| `networkPolicy.ingress.namespaces` | `[ingress-nginx, kube-system, monitoring]` | Namespaces allowed to reach port 8000. |
| `networkPolicy.ingress.extra` | `[]` | More ingress rules. |
| `networkPolicy.egress.dns` | `true` | Port 53 to any namespace. |
| `networkPolicy.egress.internet.enabled` | `true` | Egress to `0.0.0.0/0` minus `except`. |
| `networkPolicy.egress.internet.ports` | `[443]` | |
| `networkPolicy.egress.internet.except` | private, link-local (metadata), CGNAT, loopback | |
| `networkPolicy.egress.extra` | `[]` | More egress rules (collector, internal APIs). |
| `backup.enabled` | `false` | Nightly CronJob: consistent `parla.db` snapshot + `/data` without `models/`. |
| `backup.schedule` | `17 3 * * *` | |
| `backup.keep` | `7` | Archives kept. |
| `backup.sameNode` | `true` | Pod affinity to Parla (RWO data volume). |
| `backup.persistence.*` | `enabled: true`, `size: 5Gi` | Backup PVC (`existingClaim`, `storageClass`). `enabled: false`: `emptyDir`. |
| `backup.upload.image`, `.command`, `.env`, `.envFrom` | `""`, `[]` | Optional second container that ships `/backup/parla-*.tar.gz`. |
| `backup.resources` | requests `50m` / `128Mi`, limit `512Mi` | |
| `ollama.enabled` | `false` | Ollama Deployment + Service `<fullname>-ollama:11434`. |
| `ollama.image.repository`, `.tag`, `.pullPolicy` | `ollama/ollama`, `0.12.3`, `IfNotPresent` | |
| `ollama.models` | `[qwen2.5:0.5b]` | Pulled by an init container. |
| `ollama.persistence.*` | `enabled: true`, `size: 10Gi` | Models PVC. |
| `ollama.resources` | requests `500m` / `1Gi`, limit `4Gi` | |
| `ollama.nodeSelector`, `.tolerations`, `.affinity` | | |
