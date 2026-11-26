# Kubernetes y Helm

[English](kubernetes.md) · **Español**

Dos formas de correr Parla en Kubernetes:

- **Chart de Helm** (`deploy/helm/parla`): el camino completo. Ingress solo con las rutas públicas, SSO, métricas,
  trazas, copias nocturnas, NetworkPolicy y un Ollama opcional, todo como values.
- **Manifiestos de Kustomize** (`deploy/k8s`, `deploy/k3s`): un Deployment, PVC y Service simples, más ejemplos
  para editar a mano (Ingress, NetworkPolicy, CronJob de copias, ServiceMonitor).

Los dos usan la misma imagen y la misma seguridad. Con SQLite (lo de siempre) la regla es **una réplica**; con
Postgres podés correr varias ([Alta disponibilidad](#alta-disponibilidad)). Leé
[deployment_es.md](deployment_es.md) para las variables, la guarda de Origin y dónde quedan los datos, y
[security_es.md](security_es.md#antes-de-exponerlo-a-internet) antes de exponer nada.

## Una réplica con SQLite

Con SQLite, las conversaciones, las sesiones de login y la auditoría están en `parla.db` en el volumen de datos, y
dos pods sobre el mismo archivo se pisarían, así que:

- `replicaCount` es `1` (`0` apaga Parla, por ejemplo para restaurar una copia). El chart no acepta más de 1 sin
  Postgres.
- La estrategia es `Recreate`: el pod viejo se apaga antes de que arranque el nuevo. Un upgrade o un cambio de
  configuración tiene unos segundos de corte, y se pierde el pedido que estaba en curso. Las sesiones de login
  sobreviven.
- El volumen de datos es `ReadWriteOnce`. Lo que también lo monte (el job de copias) tiene que correr en el mismo
  nodo.

Para upgrades sin corte y que se banque la caída de un nodo, pasá a Postgres y varias réplicas (sección siguiente).

## Alta disponibilidad

Varios pods de Parla detrás del mismo Service, con una base Postgres y un volumen de datos ReadWriteMany
compartidos. Cómo se coordinan las réplicas (locks por conversación, el bus por `LISTEN/NOTIFY`, las colas, la
líder) está en [deployment_es.md](deployment_es.md#postgres-y-alta-disponibilidad).

Requisitos:

- **Postgres 13+** que manejes vos: un servicio gestionado (RDS, Cloud SQL, Azure Database, Neon…) o un operador
  como CloudNativePG. Cada pod abre hasta `PARLA_DB_POOL` (20) + `PARLA_DB_LOCKS` (32) + 3 conexiones; con 3 pods
  dejá `max_connections` ≥ 200 o bajá los pools (`database.pool`). Un PgBouncer en modo **session** sirve; en modo
  transaction no (los advisory locks y `LISTEN` necesitan una sesión).
- **Un volumen ReadWriteMany** para `/data` (agentes, versiones, modelos entrenados, usuarios, claves, archivos
  subidos): EFS, Filestore, Azure Files, NFS, CephFS, Longhorn RWX. El chart monta `/data/models` (embeddings, voz)
  como un `emptyDir` por pod: horneá el modelo de embeddings en la imagen (`BAKE_EMBED_DIR`) o cada pod nuevo baja
  1,2 GB.
- **`secretKey`**: el mismo `PARLA_SECRET_KEY` en todos los pods (firma las direcciones de audio del teléfono).

```yaml
# values-ha.yaml
replicaCount: 3
database:
  existingSecret: parla-db          # clave PARLA_DATABASE_URL: postgresql://parla:…@pg.interna:5432/parla?sslmode=require
secretKey:
  existingSecret: parla-secret-key  # clave PARLA_SECRET_KEY: openssl rand -hex 32
persistence:
  accessModes: [ReadWriteMany]
  storageClass: efs-sc              # tu clase RWX (o existingClaim)
# autoscaling: {enabled: true, minReplicas: 2, maxReplicas: 6, targetCPUUtilizationPercentage: 70}
```

Con CloudNativePG:

```yaml
apiVersion: postgresql.cnpg.io/v1
kind: Cluster
metadata: {name: parla-pg, namespace: parla}
spec:
  instances: 2                      # una primaria y una réplica en caliente: el operador hace el failover
  storage: {size: 10Gi}
  bootstrap: {initdb: {database: parla, owner: parla}}
```

y `database.existingSecret: parla-pg-app`, `database.secretKey: uri` (el secret de la app del operador apunta al
servicio de lectura-escritura).

Qué hace el chart con `replicaCount > 1` o `autoscaling.enabled`: no renderiza sin `database.url`/`existingSecret`,
`secretKey` y un volumen ReadWriteMany; usa `RollingUpdate` (`maxUnavailable: 0`); crea un PodDisruptionBudget
(`podDisruptionBudget.maxUnavailable: 1`) y, con `autoscaling.enabled`, un HPA por CPU. La readiness probe es
`/readyz`, que falla si el pod no llega a la base.

Tamaño: cada pod necesita el modelo de embeddings en memoria (~1 GB; requests 1,5 Gi y límite 3 Gi, como con una
réplica); el rendimiento lo limita la CPU de los embeddings, así que crece con CPU por pod y con pods, y Postgres
queda liviano (unas pocas consultas chicas por turno). Medido en una VM de una notebook con 8 CPU (k3d, Postgres en
la misma VM, `PARLA_EMBED_WORKERS=1`, `tests/perf/load.py` por el Service con 50 conversaciones a la vez): 57
turnos/s con 1 pod, 97 con 3, 0 errores.

Failover, medido borrando a la fuerza el pod líder en medio de una carga de 60 s con 30 conversaciones a la vez: 14
pedidos fallidos de ~5.500 (los que estaban en curso en ese pod o le llegaron antes de que el Service lo sacara; los
clientes reintentan), una líder nueva en 5 s, el pod de reemplazo atendiendo 5 s después, ningún turno perdido ni
duplicado.

Queda en cada pod: modelos cargados y cachés, métricas (scrapeá todos los pods; `parla_cluster_leader` suma 1), el
estado de los canales en la página del agente y el WebSocket de audio de una llamada (si ese pod se muere, la
llamada se corta).

Pasar una instalación existente: escalá a 0, corré una vez `python -m parla.migrate sqlite-to-postgres
/data/parla.db` en un pod que monte el volumen viejo con `PARLA_DATABASE_URL`, copiá el resto de `/data` (sin
`models/` ni `parla.db*`) al volumen RWX e instalá con los values de HA. Copias: `pg_dump` (o los backups del
operador) para la base más el volumen de datos; el CronJob `backup` del chart sigue archivando `/data` pero solo
saca la foto de `parla.db` con SQLite.

Kustomize: `deploy/k8s-ha` es lo mismo que `deploy/k8s` con 3 réplicas, RollingUpdate, un PDB, `/readyz`, un volumen
`models` por pod y un Secret `parla-ha` con las dos variables (ver su `kustomization.yaml`).

## Helm

```sh
helm install parla ./deploy/helm/parla -n parla --create-namespace -f values.yaml
kubectl -n parla rollout status deploy/parla
```

El chart todavía no está en un repositorio: se instala desde una copia de este repo. Todos los values están en
[deploy/helm/parla/README.md](../deploy/helm/parla/README.md).

### Imagen

`image.tag` usa por defecto el `appVersion` del chart (la versión de Parla con la que se armó el chart). Hasta que se
publique la primera versión etiquetada en ghcr.io, usá `image.tag: edge` (sigue a `main`). `image.variant: voice`
elige la imagen con ffmpeg, faster-whisper y piper (`0.9.0-voice`, `edge-voice`); dale
`resources.limits.memory: 4Gi`.

Las imágenes con el SDK de Anthropic (`--build-arg INSTALL_PROVIDERS=1`) o con el modelo de vectores adentro
(`--build-arg BAKE_EMBED_DIR=/opt/embeddings`) no se publican: armalas (ver
[deployment_es.md](deployment_es.md#armarla-vos)), subilas a tu registro y definí `image.repository` e `image.tag`.
Otra opción: `embeddings.preload: true` baja el modelo de vectores (~1,2 GB) al volumen con un init container antes de
que arranque Parla, así el primer entrenamiento no lo espera.

### Primeros pasos

```sh
kubectl -n parla port-forward deploy/parla 8000:8000      # y abrís http://127.0.0.1:8000
```

Usá **8000 a los dos lados**: el `Origin` del navegador se compara con el puerto de Parla
([Origin](deployment_es.md#la-guarda-de-origin)). Después creá el primer usuario (**Usuarios → Nuevo usuario**).
Queda como dueño y desde ahí se pide login. Mientras no haya usuarios, quien llegue a la interfaz es dueño: hacelo
antes de publicar la interfaz. Desde la terminal:

```sh
curl -s http://127.0.0.1:8000/api/users -H 'Content-Type: application/json' \
  -d '{"name":"admin","password":"<una contraseña larga>","role":"owner"}'
```

`port-forward` llega al loopback del propio pod, que es también desde donde se puede crear el dueño con SSO prendido
y donde `PARLA_OIDC_ONLY` todavía acepta la contraseña del dueño (break-glass).

### Ingress: solo las rutas públicas, o el sitio entero

Con `ingress.enabled` y el valor por defecto `ingress.exposeAdmin: false`, el Ingress publica **solo**:

| Ruta | Tipo | Qué es |
|---|---|---|
| `/api/v1/` | Prefix | API de los bots, el chat del widget y los webhooks de WhatsApp, Telegram y teléfono (Twilio, jambonz) |
| `/files/` | Prefix | Los archivos que manda el paso **Enviar un archivo** |
| `/static/widget.js` | Exact | El script del widget. No carga nada más de `/static/`. |

Todo lo demás (`/`, `/api/agents`, `/metrics`…) recibe el 404 del controlador de ingress. Se administra con
`port-forward`.

Con `ingress.exposeAdmin: true` se publica el sitio entero y el chart suma `ingress.hosts` a `PARLA_HOSTS` (sin eso
la interfaz abre pero todo `/api/` responde 403). Con `ingress.tls` además define `PARLA_SECURE_COOKIE=1`. Creá el
dueño antes. `/metrics` también queda accesible por el dominio, pero sin el token responde 401.

Poné en `config.publicUrl` la dirección pública `https://`: Parla la usa para las URLs de webhook que muestra y
registra, para verificar la firma de Twilio y para la redirect URI del SSO.

Con ingress-nginx, subí el límite de cuerpo y el timeout de lectura (audio y PDFs viajan en base64; la IA local y la
voz tardan segundos; Twilio espera ~15 s):

```yaml
ingress:
  annotations:
    nginx.ingress.kubernetes.io/proxy-body-size: 25m
    nginx.ingress.kubernetes.io/proxy-read-timeout: "3600"
    nginx.ingress.kubernetes.io/proxy-send-timeout: "3600"
    nginx.ingress.kubernetes.io/proxy-buffering: "off"
```

### Values de ejemplo para producción

```yaml
# values.yaml
image:
  tag: "0.9.0"
config:
  lang: es
  publicUrl: https://bots.example.com
  retentionDays: 180
ingress:
  enabled: true
  className: nginx
  exposeAdmin: true                         # SSO necesita la interfaz en el dominio
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
  existingSecret: parla-oidc                # clave: client-secret
  roleClaim: groups
  roleMap: parla-owners:owner,parla-editors:editor,parla-support:agent
  label: Acme
metrics:
  enabled: true
  existingSecret: parla-metrics             # clave: PARLA_METRICS_TOKEN
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
    extra:                                  # el colector de OTel es interno: hay que permitirlo
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
kubectl -n parla create secret generic parla-oidc --from-literal=client-secret='<el secreto del cliente>'
kubectl -n parla create secret generic parla-metrics --from-literal=PARLA_METRICS_TOKEN="$(openssl rand -hex 24)"
helm install parla ./deploy/helm/parla -n parla -f values.yaml
```

Los secretos también se pueden pasar directo (`metrics.token`, `otel.headers`, `oidc.clientSecret`): el chart crea
el Secret, pero los valores quedan en el historial de releases de Helm. Mejor `existingSecret`. El secreto de OIDC se
monta como archivo (`PARLA_OIDC_CLIENT_SECRET_FILE`), nunca como variable de entorno.

### IA local con Ollama

`ollama.enabled: true` suma un Deployment de Ollama (`ollama/ollama`, versión fija), un PVC para los modelos
(`ollama.persistence`) y un Service. Un init container baja `ollama.models` al volumen antes de que arranque Ollama
(la primera vez necesita internet; después ya los encuentra). En cada agente poné **IA → dirección**
`http://<release>-ollama:11434` (con `helm install parla …`: `http://parla-ollama:11434`). El botón de descarga de la
interfaz baja más modelos por esa misma dirección.

Con `networkPolicy.enabled`, Parla puede llegar a Ollama en el 11434 y Ollama solo acepta conexiones de Parla.

### Métricas y trazas

`metrics.enabled` define `PARLA_METRICS=1`. Prometheus siempre lee desde otro pod, así que necesita el token
(`metrics.existingSecret` o `metrics.token`): sin token `/metrics` solo responde al loopback del pod.
`metrics.serviceMonitor.enabled` crea un `ServiceMonitor` (Prometheus Operator) que manda el token desde ese mismo
Secret, así que el Secret tiene que estar en el namespace de Parla. Detalles en
[observability_es.md](observability_es.md).

`otel.endpoint` prende las trazas; `otel.headers` / `otel.existingSecret` llevan la API key del colector
(`OTEL_EXPORTER_OTLP_HEADERS`). Cualquier otra variable va en `extraEnv`.

### NetworkPolicy: la salida es la mitigación de SSRF

Los pasos `http`, las herramientas HTTP y MCP del paso de agente, la importación de URLs a la base de conocimiento y
los proveedores de IA y voz son pedidos que hace **el pod de Parla** a una dirección que eligió un editor. Sin reglas
de salida, un editor llega a los servicios de tu clúster, a la red de los nodos y al servicio de metadatos de la nube
(`169.254.169.254`, que en muchos proveedores entrega credenciales). `networkPolicy.enabled: true` crea una política
sobre el pod de Parla:

- **Entrada:** puerto 8000 solo desde los namespaces de `networkPolicy.ingress.namespaces` (por defecto
  `ingress-nginx`, `kube-system` para el Traefik de k3s y `monitoring`). `kubectl port-forward` y las probes del
  kubelet no se ven afectados.
- **Salida:** DNS (puerto 53 a cualquier namespace) y TCP 443 a `0.0.0.0/0` **salvo** `10.0.0.0/8`,
  `172.16.0.0/12`, `192.168.0.0/16`, `169.254.0.0/16` (metadatos), `100.64.0.0/10` y `127.0.0.0/8`. Más Ollama si
  está prendido.
- Lo interno que Parla tenga que llamar (un colector de OTel, una API interna de tus pasos `http`, un Ollama fuera
  del chart, algo por HTTP sin TLS) va en `networkPolicy.egress.extra` como `NetworkPolicyEgressRule` estándar. Otros
  puertos a internet: `networkPolicy.egress.internet.ports`.

La política solo funciona si el CNI del clúster aplica NetworkPolicy (Calico, Cilium, Antrea, el kube-router que
trae k3s…). El CNI por defecto de kind y algunos administrados no: el objeto se acepta y se ignora. Probalo:

```sh
kubectl -n parla exec deploy/parla -- python -c \
  "import socket; socket.create_connection(('169.254.169.254', 80), timeout=4)"   # tiene que fallar
```

Las cachés de DNS por nodo (NodeLocal DNSCache en `169.254.20.10`) caen dentro del rango link-local bloqueado:
permití esa dirección en el puerto 53 en `egress.extra`. La lista `except` es IPv4: en clústeres dual-stack sumá tu
propia regla IPv6.

### Copias de seguridad

`backup.enabled: true` crea un CronJob (`backup.schedule`, por defecto todos los días a las 03:17) que corre la imagen
de Parla con el mismo contexto de seguridad y escribe `/backup/parla-<fecha UTC>-<hora>.tar.gz` en su propio PVC
(`backup.persistence`), guardando las `backup.keep` (7) más nuevas. Cada archivo tiene:

- `parla.db`, copiado con la API de backup en línea de SQLite (consistente mientras Parla sigue escribiendo),
- `agents/` (borradores, modelos entrenados, versiones, archivos y `*.secrets.json`), `users.json` y todo lo demás de
  `/data`, salvo `models/` (se baja de nuevo) y los archivos vivos de la base.

Los archivos tienen conversaciones, usuarios y claves: se crean con permisos 600. Como el volumen de datos es
`ReadWriteOnce`, el job tiene afinidad obligatoria con el pod de Parla (mismo nodo). Por eso no corre mientras
Parla está apagado; con un volumen de datos `ReadWriteMany` poné `backup.sameNode: false`.

Correr una ahora y revisarla:

```sh
kubectl -n parla create job --from=cronjob/parla-backup backup-now
kubectl -n parla logs -f job/backup-now       # wrote /backup/parla-20261126-155150.tar.gz (12979 bytes); removed 0 old
```

Para mandar cada archivo fuera del clúster, sumá un paso de subida. Corre después de la copia como un segundo
contenedor con el volumen de copias montado de solo lectura en `/backup`, como uid 10001:

```yaml
backup:
  enabled: true
  upload:
    image: amazon/aws-cli:2.22.0
    command: [sh, -c, 'f=$(ls /backup/parla-*.tar.gz | tail -1); aws s3 cp "$f" s3://mi-bucket/parla/']
    envFrom: [{secretRef: {name: parla-backup-s3}}]   # AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY, AWS_DEFAULT_REGION
    env: [{name: HOME, value: /tmp}]
```

Con `backup.persistence.enabled: false` el archivo va a un `emptyDir` y solo lo conserva la subida.

#### Restaurar

Apagá Parla, descomprimí el archivo en el volumen de datos con el mismo script y arrancá Parla:

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
      image: ghcr.io/pedroslev/parla-nlu:0.9.0          # la misma imagen que el Deployment
      # la más nueva; o una en particular: python /scripts/backup.py restore /backup/parla-20261126-031700.tar.gz
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

La restauración primero borra un `parla.db-wal` / `-shm` viejo (un journal viejo se aplicaría encima de la base
restaurada) y pisa los archivos que vienen en la copia; los que no vienen quedan. Para partir de un volumen limpio,
vaciá antes el PVC. También se restauran las sesiones de login de la copia. Para restaurar un archivo que bajaste,
copialo con `kubectl cp` a un pod que monte el PVC de copias, o montá donde lo tengas.

### Upgrade y rollback

```sh
helm upgrade parla ./deploy/helm/parla -n parla -f values.yaml        # chart nuevo y/o image.tag
helm history parla -n parla
helm rollback parla <revisión> -n parla
```

Hacé una copia antes de actualizar (`kubectl create job --from=cronjob/parla-backup pre-upgrade`). Parla migra solo
los archivos de datos viejos al arrancar; volver a una imagen anterior después de una migración no garantiza que lea
el formato nuevo, así que si hacés rollback entre versiones restaurá la copia de antes del upgrade. Los PVCs tienen
`helm.sh/resource-policy: keep`: `helm uninstall` deja los datos, las copias y los modelos de Ollama (borrá los PVCs
a mano para sacarlos).

## Arranque rápido en k3s (un nodo)

k3s trae Traefik, la clase de almacenamiento `local-path` y un controlador de NetworkPolicy, así que el chart
funciona tal cual:

```sh
curl -sfL https://get.k3s.io | sh -
export KUBECONFIG=/etc/rancher/k3s/k3s.yaml        # (sudo, o copialo a ~/.kube/config)
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
kubectl -n parla port-forward deploy/parla 8000:8000      # creá el dueño en http://127.0.0.1:8000
```

- Traefik usa por defecto un certificado propio autofirmado: para uno real, cert-manager (`ingress.tls` +
  `cert-manager.io/cluster-issuer`) o el resolver ACME de Traefik.
- `local-path` guarda los datos en el disco del nodo (`/var/lib/rancher/k3s/storage/`). Con un nodo está bien; con
  varios, el pod queda atado a ese nodo.
- Traefik corre en `kube-system`, que está en `networkPolicy.ingress.namespaces` por defecto.
- Una imagen armada por vos, sin registro: `docker save parla:local | sudo k3s ctr images import -` e
  `image: {repository: docker.io/library/parla, tag: local, pullPolicy: Never}`.

## Manifiestos de Kustomize

`deploy/k8s` es una base mínima: ConfigMap (las variables, las opcionales comentadas), PVC, Deployment y Service.
`deploy/k3s` le suma un Ingress de Traefik.

```sh
kubectl create namespace parla
kubectl apply -n parla -k deploy/k8s           # o -k deploy/k3s
kubectl -n parla rollout status deploy/parla
```

La imagen es `ghcr.io/pedroslev/parla-nlu:edge`; fijá una versión o tu registro con `images:` en
`kustomization.yaml`. Ejemplos para editar y aplicar con `kubectl apply -n parla -f`:

| Archivo | Qué es |
|---|---|
| `deploy/k8s/ingress.yaml` | ingress-nginx + TLS, solo `/api/v1/`, `/files/`, `/static/widget.js` (el sitio entero, comentado) |
| `deploy/k3s/ingress.yaml` | lo mismo para Traefik |
| `deploy/k8s/networkpolicy.yaml` | la política por defecto del chart: entrada desde el controlador y monitoreo, salida DNS + 443 pública |
| `deploy/k8s/backup.yaml` | PVC de copias + CronJob nocturno, mismo formato que el chart (restaurar con `files/backup.py` del chart, o a mano: apagar Parla, borrar `parla.db-wal` y `-shm` y `tar xzf` en `/data`) |
| `deploy/k8s/servicemonitor.yaml` | `ServiceMonitor` del Prometheus Operator con el token bearer |

Secretos: `PARLA_METRICS_TOKEN` y `OTEL_EXPORTER_OTLP_HEADERS` entran por los `secretRef` comentados, el secreto del
cliente de OIDC por el volumen `oidc` comentado (un archivo, `PARLA_OIDC_CLIENT_SECRET_FILE`). Los comandos para
crearlos están en los comentarios de `deploy/k8s/parla.yaml`.

## Lista para producción

1. **El dueño primero.** Crealo por `port-forward` antes de que el DNS apunte al Ingress o de prender
   `exposeAdmin`.
2. **Imagen fija** (`image.tag: "0.9.0"`, no `edge`), y el values con las versiones del chart y la imagen bajo
   control de versiones.
3. **Solo las rutas públicas** salvo que necesites la interfaz en el dominio (SSO la necesita). Con `exposeAdmin`,
   usá TLS y revisá `PARLA_HOSTS` / `PARLA_SECURE_COOKIE` en `kubectl -n parla get deploy parla -o yaml`.
4. **`config.publicUrl`** con la dirección `https://` exacta que usan los webhooks.
5. **NetworkPolicy prendida**, en un CNI que la aplique, y verificada con la prueba de metadatos de arriba. Permití
   los destinos internos de a uno en `egress.extra`.
6. **`config.functions: false`** (el valor por defecto) salvo que confíes en todos los editores: las funciones
   corren código dentro del pod.
7. **Secretos en `existingSecret`**, no en los values. Token de métricas largo y aleatorio.
8. **Copias prendidas** y fuera del nodo (`backup.upload` o un snapshot del volumen de copias); probá una
   restauración una vez.
9. **Retención:** `config.retentionDays` (o por agente) para que las conversaciones no crezcan sin fin;
   `config.auditDays`.
10. **Recursos:** 1,5–2 Gi pedidos, límite 3 Gi (4 Gi con voz), sin límite de CPU. `embeddings.preload: true` o una
    imagen con el modelo adentro si el clúster no tiene internet al arrancar.
11. **Almacenamiento:** una clase con snapshots o replicación si el disco del nodo es la única copia.
12. **Límites de pedidos** en el ingress (Parla solo limita el login), y las anotaciones de tamaño de cuerpo y
    timeout.
13. **Monitoreo:** `metrics.enabled` + ServiceMonitor, el tablero de Grafana de `deploy/observability/`; dejá
    `otel.content` apagado salvo que el backend de trazas sea tan privado como los datos.
14. Revisá [security_es.md](security_es.md#antes-de-exponerlo-a-internet).
