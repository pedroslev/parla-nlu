# Despliegue

[English](deployment.md) · **Español**

Parla es **un solo proceso** Python (`ThreadingHTTPServer`, un hilo por pedido) sin servidor de base
de datos: los agentes son archivos en la carpeta de datos, y las conversaciones, las sesiones de login y la
auditoría van en un archivo SQLite ahí mismo (`parla.db`). Eso define cómo se despliega:

- **Una sola réplica por carpeta de datos.** Los modelos cargados viven en memoria y los agentes se guardan en
  archivos sin bloqueo entre procesos. Dos instancias sobre los mismos datos se pisan. Las sesiones de login
  sobreviven a un reinicio.
- **La interfaz de administración se usa desde `127.0.0.1` / `localhost`**, o por un dominio que sumes a
  `PARLA_HOSTS`. Ver [Origin](#la-guarda-de-origin).
- Leé [security.md](security_es.md#antes-de-exponerlo-a-internet) antes de exponerlo.
- En Kubernetes, ver [kubernetes_es.md](kubernetes_es.md) (chart de Helm, k3s, copias, NetworkPolicy).

## Variables de entorno

| Variable | En el contenedor | Para qué |
|---|---|---|
| `PARLA_HOST` | `0.0.0.0` | Dónde escucha. Sin definir: `127.0.0.1`. |
| `PARLA_DATA` | `/data` | Agentes, versiones, conversaciones, `users.json`, modelos de voz. |
| `PARLA_EMBED_CACHE` | `/data/models/embeddings` | Caché del modelo de vectores (fastembed, ~1,2 GB). |
| `HF_HOME` | `/data/models/hf` | Caché de Hugging Face (descargas de fastembed). |
| `PARLA_FUNCTIONS` | `0` | Pasos «función» (código de los bots). Apagados en la imagen; `1` para prenderlos. |
| `PARLA_WHISPER` | `base` | Modelo de dictado (`tiny` si la máquina es lenta). |
| `PARLA_LANG` | el del navegador | Idioma de la interfaz por defecto (`en`, `es` o `pt`) para quien no eligió uno. |
| `PARLA_HOSTS` | | Dominios (`host` o `host:puerto`, separados por coma) por los que también se entra a la interfaz y a `/api/`. |
| `PARLA_SECURE_COOKIE` | | `1`: la cookie de sesión siempre con `Secure` (detrás de HTTPS). |
| `PARLA_USERS` | | Otra ruta para `users.json`. |
| `PARLA_RETENTION_DAYS` | | Días que se guardan las conversaciones sin movimiento, para los agentes sin `retention_days` propio. Sin definir o `0`: para siempre. |
| `PARLA_AUDIT_DAYS` | | Días que se guarda la auditoría. Sin definir: `365`. |
| `PARLA_CAMPAIGN_MAX` | | Máximo de destinatarios por campaña ([outbound_es.md](outbound_es.md)). Sin definir: `10000`. |
| `PARLA_PUBLIC_URL` | | Dirección pública (`https://bots.example.com`): webhooks y la redirect URI del SSO. |
| `PARLA_METRICS`, `PARLA_METRICS_TOKEN` | | `1`: métricas de Prometheus en `GET /metrics`, con el token como `Authorization: Bearer` (obligatorio desde otra máquina o contenedor). Ver [Observabilidad](#observabilidad). |
| `PARLA_OTEL_ENDPOINT` | | URL base OTLP/HTTP para las trazas de OpenTelemetry (`http://jaeger:4318`). |
| `OTEL_EXPORTER_OTLP_ENDPOINT`, `OTEL_EXPORTER_OTLP_TRACES_ENDPOINT` | | Las variables estándar de OpenTelemetry, si `PARLA_OTEL_ENDPOINT` está vacío. |
| `OTEL_EXPORTER_OTLP_HEADERS` (o `..._TRACES_HEADERS`) | | Encabezados para el colector (`clave=valor,…`), por ejemplo su API key. Guardalo en un secreto. |
| `OTEL_SERVICE_NAME`, `OTEL_RESOURCE_ATTRIBUTES` | | `service.name` (por defecto `parla`) y atributos de recurso extra de los spans. |
| `OTEL_EXPORTER_OTLP_TIMEOUT`, `OTEL_SDK_DISABLED` | | Timeout de cada envío en ms (por defecto `5000`); `true` apaga las trazas. |
| `PARLA_OTEL_INTERVAL`, `PARLA_OTEL_CONTENT` | | Segundos entre tandas de spans (por defecto `2`); `1` suma a los spans el texto del turno, enmascarado. Ver [observability_es.md](observability_es.md). |
| `PARLA_LOG_FORMAT` | | `json`: una línea JSON por pedido en stderr, con `trace_id` y `span_id`. |
| `PARLA_OIDC_ISSUER`, `PARLA_OIDC_CLIENT_ID` | | Inicio de sesión único con tu proveedor de identidad: con los dos se prende. Ver [sso_es.md](sso_es.md). |
| `PARLA_OIDC_CLIENT_SECRET`, `PARLA_OIDC_CLIENT_SECRET_FILE` | | El secreto del cliente o, mejor, un archivo que lo tenga (secretos de Docker / Kubernetes; gana el archivo). |
| `PARLA_OIDC_SCOPES`, `PARLA_OIDC_ROLE_CLAIM`, `PARLA_OIDC_ROLE_MAP`, `PARLA_OIDC_DEFAULT_ROLE` | | Scopes (por defecto `openid email profile`), el claim con los grupos, pares `grupo:rol` y el rol de quien no tiene grupo mapeado (vacío: no entra). |
| `PARLA_OIDC_ONLY`, `PARLA_OIDC_LABEL`, `PARLA_OIDC_LOGOUT` | | `1`: sin login con contraseña salvo el dueño desde el loopback; el texto del botón; `0`: no mandar al logout del proveedor (Okta). |
| `PARLA_ANTHROPIC_BASE_URL`, `PARLA_GEMINI_BASE_URL` | | Otra dirección para esos proveedores de IA (un proxy propio, pruebas). Los demás proveedores de IA toman la dirección por agente. |
| `PARLA_OPENAI_BASE_URL`, `PARLA_DEEPGRAM_BASE_URL`, `PARLA_ELEVENLABS_BASE_URL`, `PARLA_GOOGLE_SPEECH_BASE_URL`, `PARLA_GOOGLE_TTS_BASE_URL` | | Otra dirección para los proveedores de voz en la nube. |
| `PARLA_WHATSAPP_API`, `PARLA_TELEGRAM_API` | | Otra URL base para la API de WhatsApp Cloud (por defecto `https://graph.facebook.com/v21.0`) y la Bot API de Telegram. |
| `PARLA_URL`, `PARLA_TOKEN`, `PARLA_MCP_ALLOWED_HOSTS` | | Solo para `mcp_server.py`: dónde está Parla, su API key y hosts extra para `--http`. |
| `PARLA_THREADS` | | Hilos que corren los pedidos (turnos, API de administración). Sin poner: `64`. Ver [Rendimiento y ajustes](#rendimiento-y-ajustes). |
| `PARLA_EMBED_WORKERS`, `PARLA_EMBED_THREADS` | | Llamadas de embeddings en paralelo (por defecto: núcleos / 2) e hilos de ONNX por llamada (por defecto `2`). |
| `PARLA_EMBED_BATCH`, `PARLA_EMBED_WAIT_MS` | | Textos por llamada (por defecto `16`) y cuánto esperar para llenar un lote (por defecto `0`: solo lo que ya está en la cola). |
| `PARLA_VOICE_WORKERS` | | Juegos de modelos locales Whisper/Piper que trabajan a la vez (por defecto `min(2, núcleos / 4)`; cada uno usa su RAM). |
| `PARLA_VOICE_MAX_SECONDS` | | El stream de voz en tiempo real más largo (llamada, navegador o widget) antes de que Parla lo cierre (por defecto `3600`). |
| `PARLA_IDLE_TIMEOUT`, `PARLA_WS_MAX_MESSAGE` | | Segundos sin datos antes de cerrar una conexión (por defecto `30`) y el mensaje de WebSocket más grande (por defecto `1000000` bytes). |

El puerto es el argumento de `app.py` (la imagen usa `8000`). La dirección de Ollama no es una variable: se
configura por agente en la interfaz (**IA → dirección**).

## En tu compu

```sh
make run                          # o: .venv/bin/python app.py
.venv/bin/python app.py 8080      # otro puerto
```

Escucha en `127.0.0.1` salvo que definas `PARLA_HOST`.

## Docker

### Imagen publicada

Hay imágenes para `linux/amd64` y `linux/arm64` en el GitHub Container Registry. `latest` y las etiquetas de
versión (`0.9.0`, `0.9`) aparecen desde la primera versión etiquetada; `edge` sigue a `main`. Cada una tiene su
variante `-voice` (`latest-voice`, `edge-voice`) con ffmpeg, faster-whisper y piper.

```sh
docker run -d --name parla --restart unless-stopped \
  --read-only --tmpfs /tmp \
  -p 127.0.0.1:8000:8000 -v parla-data:/data ghcr.io/pedroslev/parla-nlu:latest
```

El modelo de vectores (~1,2 GB) se baja al volumen `parla-data` la primera vez que entrenás.

### Armarla vos

```sh
make docker-build                 # imagen parla:local   (VOICE=1 make docker-build: con voz)
make docker-run                   # http://127.0.0.1:8000, datos en el volumen «parla-data»
```

A mano:

```sh
docker build -t parla:local .
docker build -t parla:local --build-arg INSTALL_VOICE=1 .                # + ffmpeg, faster-whisper, piper
docker build -t parla:local --build-arg BAKE_EMBED_DIR=/opt/embeddings . # modelo de vectores dentro de la imagen

docker run -d --name parla --restart unless-stopped \
  --read-only --tmpfs /tmp \
  -p 127.0.0.1:8000:8000 -v parla-data:/data parla:local
```

- Usuario sin privilegios (uid `10001`), sistema de archivos de solo lectura salvo `/data` y `/tmp`.
- Publicá en `127.0.0.1` y con **el mismo número de puerto** afuera y adentro (`-p 127.0.0.1:8000:8000`). Con
  `-p 9000:8000` la interfaz abre pero no deja guardar nada (403, ver [Origin](#la-guarda-de-origin)), salvo que
  sumes `PARLA_HOSTS=localhost:9000`.
- `data/` del repo no entra en la imagen (`.dockerignore`): tiene usuarios, claves y conversaciones.

## Docker Compose

```sh
docker compose up -d                       # Parla en http://127.0.0.1:8000
docker compose --profile ai up -d          # + Ollama (IA local)
PARLA_VOICE=1 docker compose up -d --build # con voz
docker compose --profile observability up -d   # + Jaeger y Prometheus (ver Observabilidad más abajo)
docker compose logs -f parla
```

Con el perfil `ai`, bajá un modelo y apuntá el agente a Ollama:

```sh
docker compose exec ollama ollama pull qwen2.5:0.5b
```

En el agente: **IA → dirección** `http://ollama:11434` (o el botón de descarga de la interfaz, que usa esa
dirección). Ollama no publica puertos: solo Parla le habla.

Los datos quedan en los volúmenes `parla-data` y `ollama-models`. `docker compose down` no los borra; `down -v`
sí.

## Kubernetes y k3s

[kubernetes_es.md](kubernetes_es.md) tiene la guía completa: el chart de Helm (`deploy/helm/parla`) con un values de
ejemplo para producción (dominio, TLS, SSO, métricas, copias, NetworkPolicy, Ollama), un arranque rápido en k3s,
upgrades y rollbacks, copias y restauración desde los archivos del CronJob, los manifiestos de Kustomize
(`deploy/k8s`, `deploy/k3s`) y una lista para producción. En corto:

```sh
helm install parla ./deploy/helm/parla -n parla --create-namespace -f values.yaml
kubectl -n parla port-forward deploy/parla 8000:8000     # y abrís http://127.0.0.1:8000 para crear el dueño
```

- **Una réplica, estrategia `Recreate`**: SQLite, los archivos de agentes y el estado en memoria no se comparten
  entre pods; un upgrade tiene unos segundos de corte.
- No root (uid/gid `10001`, `fsGroup` para el volumen), `readOnlyRootFilesystem`, sin capabilities, seccomp
  `RuntimeDefault`, sin token de service account. Probes en `GET /` (página estática, no toca modelos ni disco).
- **El Ingress publica solo `/api/v1/`, `/files/` y `/static/widget.js`** por defecto (la API, el widget y los
  webhooks de WhatsApp, Telegram y teléfono). La interfaz completa por un dominio (hace falta para SSO) necesita
  `PARLA_HOSTS`; `ingress.exposeAdmin: true` del chart lo define.
- Usá **8000 a los dos lados** del `port-forward` (por la [guarda de Origin](#la-guarda-de-origin)).

## La guarda de Origin

Todo pedido a `/api/` con un `Origin` que no sea `127.0.0.1:<puerto>` o `localhost:<puerto>` (el puerto en el que
escucha Parla) ni uno de `PARLA_HOSTS` se rechaza con 403, salvo las rutas públicas del widget. Además, un
pedido cuyo `Host` no es local ni de `PARLA_HOSTS` se rechaza con 403 salvo que traiga una clave de API o sea el
chat del widget (contra DNS rebinding). Protege tu Parla de páginas que abras en el navegador. Consecuencias:

- **La interfaz completa detrás de un dominio (`https://bots.midominio.com`) necesita
  `PARLA_HOSTS=bots.midominio.com`.** Sin eso, la página abre pero todo `/api/` (login incluido) responde 403. Con HTTPS, sumá
  `PARLA_SECURE_COOKIE=1` o que el proxy mande `X-Forwarded-Proto: https`. «Conectar con IA» igual solo anda
  desde `127.0.0.1` / `localhost`.
- Para administrar de forma remota sin exponer la interfaz: túnel al puerto, con el mismo número a los dos lados.

```sh
ssh -L 8000:127.0.0.1:8000 usuario@tu-servidor            # servidor con Docker o systemd
kubectl -n parla port-forward deploy/parla 8000:8000        # Kubernetes / k3s
```

- La API pública (`/api/v1/` con `Authorization: Bearer <clave>` desde tu backend) no manda `Origin` y no se ve
  afectada. El widget usa la excepción de **sitios autorizados**.

## Detrás de un proxy con HTTPS

Fuera de Kubernetes, publicá solo lo que necesitan el widget y tus integraciones. Caddy:

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
    client_max_body_size 25m;          # audios y PDFs van en base64
    proxy_read_timeout 3600s;          # la IA y la voz tardan segundos; WebSocket/SSE quedan abiertos (Parla manda ping cada 15-30 s)
    proxy_buffering off;               # SSE y las respuestas de la IA en vivo, token a token
    proxy_http_version 1.1;            # keep-alive y WebSocket
    proxy_set_header Upgrade $http_upgrade;
    proxy_set_header Connection $connection_upgrade;   # map $http_upgrade $connection_upgrade { default upgrade; "" ""; }

    location /api/v1/ { proxy_pass http://127.0.0.1:8000; }
    location = /static/widget.js { proxy_pass http://127.0.0.1:8000; }
    location /files/ { proxy_pass http://127.0.0.1:8000; }
    location / { return 404; }
}
```

- El widget se carga desde `https://bots.midominio.com/static/widget.js` y le habla a ese mismo servidor. Agregá
  el sitio donde lo pegás en **Widget web → sitios autorizados**.
- WhatsApp y Telegram llaman a `/api/v1/bots/{bot}/whatsapp` y `/telegram`, que ya entran en `/api/v1/` (ver
  [channels_es.md](channels_es.md)). No les pongas un límite muy bajo: Meta y Telegram reintentan cuando reciben errores.
- Los proveedores de telefonía llaman a `/api/v1/bots/{bot}/phone/…` (y bajan `/phone/audio/<token>.wav` con
  `tts: "parla"`), también bajo `/api/v1/`. El proxy tiene que pasar la ruta y la query originales sin tocarlas, y
  `PARLA_PUBLIC_URL` tiene que ser exactamente la dirección a la que llama Twilio: la firma de Twilio cubre la URL
  completa. Twilio espera ~15 s cada respuesta, así que `proxy_read_timeout` tiene que ser mayor.
- Parla no tiene límite de pedidos propio (salvo en el login): agregalo en el proxy.

## Primer ingreso y usuarios

**Sin usuarios creados, Parla no pide login**: cualquiera que llegue a la interfaz es dueño. No hay contraseña
por defecto. Por eso, antes de publicar nada:

1. Entrá por `127.0.0.1` (o el túnel / port-forward).
2. En **Usuarios**, creá el primer usuario: queda como dueño y desde ahí se pide iniciar sesión.
3. Creá los demás con el rol mínimo y, para integraciones, claves de API.

Con [SSO](sso_es.md) configurado, el login se pide aunque no haya usuarios, y ese primer dueño local solo se puede
crear desde la misma máquina (`127.0.0.1`, el túnel o el `port-forward`).

Cambiar una contraseña: **Usuarios → editar** (solo un dueño puede, la propia o la de otro). Cambiarla o
borrar el usuario cierra sus sesiones. Si perdiste la del único dueño, con Parla apagado borrá `users.json` de la
carpeta de datos (vuelve a quedar abierto, sin usuarios) y creá uno nuevo:

```sh
docker run --rm -v parla-data:/data --entrypoint rm parla:local /data/users.json
kubectl -n parla exec deploy/parla -- rm /data/users.json && kubectl -n parla rollout restart deploy/parla
```

## Modelos: descarga y caché

| Modelo | Tamaño | Cuándo se baja | Dónde |
|---|---|---|---|
| Vectores (`google/embeddinggemma-300m`, fastembed) | ~1,2 GB | al entrenar por primera vez | `PARLA_EMBED_CACHE` |
| Dictado (faster-whisper `base`) | ~150 MB | al usar la voz | `/data/models/whisper` |
| Voces (piper) | ~60 MB por idioma | al usar la voz | `/data/models/piper` |
| IA local (Ollama) | 0,4–1,3 GB | al bajarlo vos | volumen de Ollama |

Todo cae en el volumen de datos y sobrevive reinicios y upgrades. El primer entrenamiento tarda lo que tarde la
descarga. Para no depender de internet al arrancar (o en clústeres sin salida), metelo en la imagen:

```sh
docker build -t parla:baked --build-arg BAKE_EMBED_DIR=/opt/embeddings .
```

La imagen pasa de ~400 MB a ~1,6 GB. Si cambia `MODEL` en `parla/server.py`, actualizá el nombre en el
`Dockerfile`. Whisper y piper no se pre-bajan en la imagen.

## Rendimiento y ajustes

Un solo proceso atiende todo en un loop de eventos (asyncio; usa `uvloop` si está instalado): HTTP/1.1 keep-alive,
WebSocket y SSE comparten el puerto 8000, así que las probes y las rutas del ingress no cambian. Medido en una M4 de
10 núcleos con `tests/perf/load.py` (charlas de 5 turnos, textos únicos): ~280 turnos/s con 10 charlas a la vez,
~360-420 de 50 a 1.000 a la vez sin errores, y 5.000 conexiones WebSocket/SSE quietas en ~150 MB además del modelo.

- **El techo es el modelo de embeddings**: cada turno que el bot tiene que clasificar corre `embeddinggemma-300m` en la
  CPU (~500 textos/s en esa máquina con todos los núcleos). Más allá, más concurrencia solo suma espera. Lo sube más
  CPU (o más réplicas, cada una con sus datos); más workers en el mismo proceso no (medido).
- `PARLA_EMBED_WORKERS` × `PARLA_EMBED_THREADS` ≈ los núcleos del pod. Con un límite de 4 CPU: `2` × `2`.
- `PARLA_THREADS` limita los pedidos en curso; un proveedor de IA lento ocupa un hilo por respuesta: subilo si muchas
  charlas esperan a la IA a la vez.
- Detrás de un proxy, WebSocket necesita que pase `Upgrade`/`Connection`, y SSE el buffering apagado y un timeout de
  lectura largo (el bloque de nginx de arriba; para ingress-nginx, las anotaciones de [kubernetes_es.md](kubernetes_es.md)).
  Si el proxy no puede, el widget y la interfaz vuelven solos al polling.
- La voz en tiempo real ([ai-and-voice.md](ai-and-voice_es.md#voz-en-tiempo-real)) usa la misma configuración de
  WebSocket (los timeouts de 3600 s de arriba ya cubren una llamada larga); los streams del teléfono vienen de
  Twilio/jambonz, así que `/api/v1/` tiene que llegar desde internet con TLS (`wss://`). Con varias réplicas, una
  llamada tiene que quedar en una sola.
- Las escrituras a SQLite pasan por un solo hilo que hace commit en grupo; lo que la API confirmó ya está en el WAL
  (`synchronous=NORMAL`: sobrevive a que se caiga el proceso; un corte de luz puede perder las últimas transacciones).

## Recursos

| | CPU | Memoria | Disco |
|---|---|---|---|
| Base (texto, sin IA) | 0,25 núcleo en reposo; picos al entrenar | ~1 GB con el modelo cargado | 2 GB |
| Con voz | +1 núcleo mientras transcribe | +0,5–1 GB | +0,5 GB |
| Ollama `qwen2.5:0.5b` | 1–2 núcleos por respuesta | +1 GB | +0,5 GB |

Medido: con el modelo de vectores cargado el proceso usa ~970 MB. El Deployment pide 1,5 Gi y limita a 3 Gi;
subilo a 4 Gi con voz. No tiene límite de CPU a propósito (entrenar es un pico corto). Las conversaciones crecen
sin límite salvo que pongas una retención (`retention_days` o `PARLA_RETENTION_DAYS`, ver
[concepts_es.md](concepts_es.md#retención-y-datos-personales)).

## Observabilidad

Las métricas, las trazas y los logs JSON vienen apagados; [observability.md](observability_es.md) tiene la lista
completa de métricas, el árbol de spans, todas las variables y ejemplos para Grafana Tempo, Datadog y Honeycomb.
En corto:

- **Prometheus:** `PARLA_METRICS=1` y un `PARLA_METRICS_TOKEN` largo y al azar; después leé `/metrics` con
  `Authorization: Bearer <token>`. Sin token, `/metrics` solo le contesta al propio `127.0.0.1`, que para Prometheus
  nunca es un contenedor ni un pod.
- **Trazas:** `PARLA_OTEL_ENDPOINT=http://<colector>:4318` (OTLP/HTTP JSON). El exportador nunca frena los pedidos:
  si el colector está caído, los spans se descartan.
- **Logs:** `PARLA_LOG_FORMAT=json` para una línea por pedido con `trace_id`.

**Docker Compose.** El perfil opcional `observability` suma Jaeger all-in-one y Prometheus, solo en `127.0.0.1`:

```sh
export PARLA_METRICS=1 PARLA_METRICS_TOKEN="$(openssl rand -hex 24)" PARLA_OTEL_ENDPOINT=http://jaeger:4318
docker compose --profile observability up -d
# trazas: http://127.0.0.1:16686   métricas: http://127.0.0.1:9090
```

**Kubernetes.** Con el chart de Helm: `metrics.enabled: true`, `metrics.existingSecret` y, con el Prometheus
Operator, `metrics.serviceMonitor.enabled: true` ([kubernetes_es.md](kubernetes_es.md#métricas-y-trazas)). Con los
manifiestos de Kustomize, poné el token en un Secret y descomentá las variables, el `secretRef` y (para descubrir por
anotaciones) las anotaciones `prometheus.io/*` en `deploy/k8s/parla.yaml`:

```sh
kubectl -n parla create secret generic parla-metrics --from-literal=PARLA_METRICS_TOKEN="$(openssl rand -hex 24)"
```

Con el Prometheus Operator, `deploy/k8s/servicemonitor.yaml` es un `ServiceMonitor` comentado que manda ese mismo
Secret como token bearer. Una configuración de Prometheus común:

```yaml
scrape_configs:
  - job_name: parla
    metrics_path: /metrics
    authorization: {type: Bearer, credentials_file: /etc/prometheus/parla-token}
    kubernetes_sd_configs: [{role: pod, namespaces: {names: [parla]}}]
    relabel_configs:
      - {source_labels: [__meta_kubernetes_pod_label_app], regex: parla, action: keep}
      # pods del chart de Helm: __meta_kubernetes_pod_label_app_kubernetes_io_name
```

El tablero de Grafana está en `deploy/observability/grafana-dashboard.json`. No publiques `/metrics` por el Ingress:
solo `/api/v1/`, `/static/widget.js` y `/files/` necesitan ser públicos.

## Dónde quedan los datos

```
/data   (o data/ en tu compu)
  agents/
    <id>.json               el borrador del agente
    <id>.model.json         lo último entrenado
    <id>.crfsuite           modelo de entidades
    <id>.secrets.json       claves (permisos 600)
    <id>.versions/<n>.json  versiones publicadas (+ <n>.crfsuite)
    <id>.files/             archivos subidos para el paso `file`
    <id>.sessions.migrated/ archivos viejos de conversaciones, ya importados a parla.db (se pueden borrar)
  parla.db                  conversaciones, sesiones de login y auditoría (SQLite, permisos 600)
  parla.db-wal, -shm        el diario de parla.db mientras corre (son parte de la base)
  users.json                usuarios (permisos 600)
  models/                   vectores, voz y caché de audios (se pueden volver a bajar)
```

## Copias de seguridad

Copiá la carpeta de datos entera; `models/` se puede excluir (se vuelve a bajar). Con Parla apagado alcanza con
copiar la carpeta tal cual. Mientras corre, `parla.db` se está escribiendo y una copia común puede salir
inconsistente: primero sacá una copia con `.backup` de SQLite (segura con Parla andando) y dejá la base en uso
fuera del archivo. Las copias tienen conversaciones, usuarios y claves: guardalas en un lugar privado.

```sh
# en tu compu / systemd
sqlite3 data/parla.db ".backup 'data/parla.db.backup'"
tar czf parla-$(date +%F).tar.gz --exclude=models --exclude=parla.db --exclude='parla.db-*' data/

# Docker / Compose (contenedor parla, volumen parla-data; con compose: docker compose exec parla …, volumen parla_parla-data)
docker exec parla python -c "import sqlite3; sqlite3.connect('/data/parla.db').backup(sqlite3.connect('/data/parla.db.backup'))"
docker run --rm -v parla-data:/data:ro -v "$PWD":/backup python:3.12-slim \
  tar czf /backup/parla-$(date +%F).tar.gz --exclude=models --exclude=parla.db --exclude='parla.db-*' -C /data .

# Kubernetes: el CronJob de copias del chart de Helm (backup.enabled) o deploy/k8s/backup.yaml lo hacen cada noche
kubectl -n parla create job --from=cronjob/parla-backup backup-now
```

En Kubernetes, la restauración está en [kubernetes_es.md](kubernetes_es.md#restaurar).

Restaurar: con Parla apagado, descomprimir en la carpeta / volumen vacío, renombrar `parla.db.backup` a
`parla.db` y arrancar. En Docker:

```sh
docker run --rm -v parla-data:/data -v "$PWD":/backup python:3.12-slim \
  sh -c 'tar xzf /backup/parla-AAAA-MM-DD.tar.gz -C /data && mv /data/parla.db.backup /data/parla.db && chown -R 10001:10001 /data'
```

Para mover un solo bot a otra instalación usá «Exportar agente» / «Importar agente» (no lleva versiones,
conversaciones ni claves).

## Upgrades

Los datos viven fuera de la imagen; al arrancar, Parla migra los archivos viejos solo. Hacé una copia antes. Si
venís de una versión que guardaba las conversaciones en `agents/<id>.sessions/`: al arrancar se importan a
`parla.db` (sin pisar lo que ya esté) y la carpeta pasa a llamarse `<id>.sessions.migrated`; nunca se borra, y los
archivos que no se pueden leer se avisan y quedan ahí.

```sh
docker compose build && docker compose up -d                       # Compose
helm upgrade parla ./deploy/helm/parla -n parla -f values.yaml --set image.tag=1.1.0   # Helm (rollback: helm rollback)
kubectl -n parla set image deploy/parla parla=ghcr.io/pedroslev/parla-nlu:1.1.0       # manifiestos de Kustomize
```

Al reiniciar se pierden las conversaciones a mitad de un pedido; las sesiones de login se mantienen.

## Como servicio (sin contenedores)

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
