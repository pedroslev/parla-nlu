# Despliegue

[English](deployment.md) · **Español**

Parla es **un solo proceso** Python (`ThreadingHTTPServer`, un hilo por pedido) sin base de datos: todo queda en
archivos en la carpeta de datos. Eso define cómo se despliega:

- **Una sola réplica por carpeta de datos.** Las sesiones de login y los modelos cargados viven en memoria y los
  agentes se guardan en archivos sin bloqueo entre procesos. Dos instancias sobre los mismos datos se pisan; al
  reiniciar, los usuarios tienen que volver a entrar.
- **La interfaz de administración se usa desde `127.0.0.1` / `localhost`**, o por un dominio que sumes a
  `PARLA_HOSTS`. Ver [Origin](#la-guarda-de-origin).
- Leé [security.md](security_es.md#antes-de-exponerlo-a-internet) antes de exponerlo.

| Variable | En el contenedor | Para qué |
|---|---|---|
| `PARLA_HOST` | `0.0.0.0` | Dónde escucha. Sin definir: `127.0.0.1`. |
| `PARLA_DATA` | `/data` | Agentes, versiones, conversaciones, `users.json`, modelos de voz. |
| `PARLA_EMBED_CACHE` | `/data/models/embeddings` | Caché del modelo de vectores (fastembed, ~1,2 GB). |
| `HF_HOME` | `/data/models/hf` | Caché de Hugging Face (descargas de fastembed). |
| `PARLA_FUNCTIONS` | `0` | Pasos «función» (código de los bots). Apagados en la imagen; `1` para prenderlos. |
| `PARLA_WHISPER` | `base` | Modelo de dictado (`tiny` si la máquina es lenta). |
| `PARLA_HOSTS` | | Dominios (`host` o `host:puerto`, separados por coma) por los que también se entra a la interfaz y a `/api/`. |
| `PARLA_SECURE_COOKIE` | | `1`: la cookie de sesión siempre con `Secure` (detrás de HTTPS). |
| `PARLA_USERS` | | Otra ruta para `users.json`. |

El puerto es el argumento de `app.py` (la imagen usa `8000`). La dirección de Ollama no es una variable: se
configura por agente en la interfaz (**IA → dirección**).

## En tu compu

```sh
make run                          # o: .venv/bin/python app.py
.venv/bin/python app.py 8080      # otro puerto
```

Escucha en `127.0.0.1` salvo que definas `PARLA_HOST`.

## Docker

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

## Kubernetes

Manifiestos en `deploy/k8s/` sin namespace fijo: ConfigMap, PVC (5 Gi), Deployment y Service.

```sh
docker build -t registry.example.com/parla:1.0.0 . && docker push registry.example.com/parla:1.0.0
# en deploy/k8s/kustomization.yaml descomentá «images:» con ese nombre y versión
kubectl create namespace parla
kubectl apply -n parla -k deploy/k8s
kubectl -n parla rollout status deploy/parla
```

Qué trae el Deployment:

- `replicas: 1` y `strategy: Recreate`: el pod viejo se apaga antes de que arranque el nuevo (el PVC es
  `ReadWriteOnce` y no puede haber dos Parla sobre los mismos datos). Un upgrade tiene unos segundos de corte.
- No root (uid/gid `10001`, `fsGroup` para el volumen), `readOnlyRootFilesystem`, sin capabilities, sin token de
  service account. `/tmp` es un `emptyDir`.
- Probes en `GET /` (devuelve la página estática, no toca modelos ni disco).
- La configuración va en el ConfigMap `parla`. No hay Secret: Parla no lee secretos por variable; las claves de
  los bots y los usuarios viven en el volumen.

### Administrar

```sh
kubectl -n parla port-forward deploy/parla 8000:8000     # y abrís http://127.0.0.1:8000
```

Usá **8000 a los dos lados** (por la guarda de Origin).

### Ingress

`deploy/k8s/ingress.yaml` es un ejemplo (ingress-nginx + TLS) que publica **solo** `/api/v1/`, `/files/` y
`/static/widget.js`, lo que necesitan el widget y tus integraciones. Editá el host, la clase y el certificado y
aplicalo aparte:

```sh
kubectl apply -n parla -f deploy/k8s/ingress.yaml
```

No publiques `/` ni `/api/` completo: sin usuarios creados Parla no pide login, y la interfaz por un dominio
necesita `PARLA_HOSTS` (ver abajo). Si tus bots mandan archivos (paso «Enviar un archivo»), publicá también
`/files/`.

Los webhooks de WhatsApp y Telegram (`/api/v1/bots/{bot}/whatsapp` y `/telegram`) están bajo `/api/v1/`, así que
estos ejemplos ya los publican. Poné en `PARLA_PUBLIC_URL` la dirección pública (`https://bots.example.com`) para que
Parla muestre la URL del webhook y pueda conectar Telegram. Ver [channels_es.md](channels_es.md).

## k3s

k3s ya trae Traefik y la clase de almacenamiento `local-path` (por defecto), así que la base sirve tal cual.
`deploy/k3s/` le suma un Ingress de Traefik con las mismas dos rutas públicas:

```sh
# imagen sin registro: importarla en el containerd de k3s
docker build -t parla:latest . && docker save parla:latest | sudo k3s ctr images import -
# editá el host en deploy/k3s/ingress.yaml
kubectl create namespace parla
kubectl apply -n parla -k deploy/k3s
```

- `local-path` guarda los datos en el disco del nodo (`/var/lib/rancher/k3s/storage/`): si el pod cambia de
  nodo, no los ve. En un clúster de un nodo no importa; en varios, fijá el nodo o usá otro almacenamiento.
- El certificado: Traefik usa uno propio por defecto; para uno real, cert-manager o el resolver ACME de Traefik.

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
    proxy_read_timeout 120s;           # la IA local y la voz tardan segundos

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
- Parla no tiene límite de pedidos propio (salvo en el login): agregalo en el proxy.

## Primer ingreso y usuarios

**Sin usuarios creados, Parla no pide login**: cualquiera que llegue a la interfaz es dueño. No hay contraseña
por defecto. Por eso, antes de publicar nada:

1. Entrá por `127.0.0.1` (o el túnel / port-forward).
2. En **Usuarios**, creá el primer usuario: queda como dueño y desde ahí se pide iniciar sesión.
3. Creá los demás con el rol mínimo y, para integraciones, claves de API.

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

## Recursos

| | CPU | Memoria | Disco |
|---|---|---|---|
| Base (texto, sin IA) | 0,25 núcleo en reposo; picos al entrenar | ~1 GB con el modelo cargado | 2 GB |
| Con voz | +1 núcleo mientras transcribe | +0,5–1 GB | +0,5 GB |
| Ollama `qwen2.5:0.5b` | 1–2 núcleos por respuesta | +1 GB | +0,5 GB |

Medido: con el modelo de vectores cargado el proceso usa ~970 MB. El Deployment pide 1,5 Gi y limita a 3 Gi;
subilo a 4 Gi con voz. No tiene límite de CPU a propósito (entrenar es un pico corto). Las conversaciones crecen
sin límite: no se borran solas.

## Dónde quedan los datos

```
/data   (o data/ en tu compu)
  agents/
    <id>.json               el borrador del agente
    <id>.model.json         lo último entrenado
    <id>.crfsuite           modelo de entidades
    <id>.secrets.json       claves (permisos 600)
    <id>.versions/<n>.json  versiones publicadas (+ <n>.crfsuite)
    <id>.sessions/<sid>.json  una conversación por archivo
  users.json                usuarios (permisos 600)
  models/                   vectores, voz y caché de audios (se pueden volver a bajar)
```

## Copias de seguridad

Copiá la carpeta de datos entera, con Parla apagado o en un momento tranquilo. `models/` se puede excluir (se
vuelve a bajar). Las copias tienen conversaciones, usuarios y claves: guardalas en un lugar privado.

```sh
# en tu compu / systemd
tar czf parla-$(date +%F).tar.gz --exclude=models data/

# Docker / Compose (el volumen se llama parla-data; con compose: parla_parla-data)
docker run --rm -v parla-data:/data:ro -v "$PWD":/backup python:3.12-slim \
  tar czf /backup/parla-$(date +%F).tar.gz --exclude=models -C /data .

# Kubernetes (la imagen no tiene tar: se copia con Python)
kubectl -n parla exec deploy/parla -- python -c \
  "import tarfile,sys; t=tarfile.open(fileobj=sys.stdout.buffer,mode='w|gz'); t.add('/data','.',filter=lambda i: None if i.name.startswith('./models') else i); t.close()" \
  > parla-$(date +%F).tar.gz
```

Restaurar: con Parla apagado, descomprimir en la carpeta / volumen vacío y arrancar. En Docker:

```sh
docker run --rm -v parla-data:/data -v "$PWD":/backup python:3.12-slim \
  sh -c 'tar xzf /backup/parla-AAAA-MM-DD.tar.gz -C /data && chown -R 10001:10001 /data'
```

Para mover un solo bot a otra instalación usá «Exportar agente» / «Importar agente» (no lleva versiones,
conversaciones ni claves).

## Upgrades

Los datos viven fuera de la imagen; al arrancar, Parla migra los archivos viejos solo. Hacé una copia antes.

```sh
docker compose build && docker compose up -d                       # Compose
docker build -t registry.example.com/parla:1.1.0 . && docker push registry.example.com/parla:1.1.0
kubectl -n parla set image deploy/parla parla=registry.example.com/parla:1.1.0   # Kubernetes
```

Al reiniciar se pierden las sesiones de login (hay que volver a entrar) y las conversaciones a mitad de un pedido.

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
