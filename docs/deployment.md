# Despliegue

## En tu compu

```sh
make run                          # o: .venv/bin/python app.py
.venv/bin/python app.py 8080      # otro puerto
```

Siempre escucha en `127.0.0.1`. Es un solo proceso (`ThreadingHTTPServer`, un hilo por pedido), sin base de
datos: todo queda en archivos en la carpeta de datos.

## Dónde quedan los datos

En `data/` (o lo que diga `PARLA_DATA`):

```
data/
  agents/
    <id>.json               el borrador del agente
    <id>.model.json         lo último entrenado
    <id>.crfsuite           modelo de entidades
    <id>.secrets.json       claves (permisos 600)
    <id>.versions/<n>.json  versiones publicadas (+ <n>.crfsuite)
    <id>.sessions/<sid>.json  una conversación por archivo
  users.json                usuarios (permisos 600)
  models/                   modelos de voz
```

Las conversaciones no se borran solas: si se acumulan miles, limpiá las viejas a mano. El modelo de vectores lo
guarda fastembed en su propia caché.

## Copias de seguridad

Con Parla apagado (o en un momento tranquilo), copiá la carpeta entera:

```sh
tar czf parla-$(date +%F).tar.gz data/
```

Restaurar es descomprimirla en el mismo lugar. Guardá las copias en un lugar privado: tienen conversaciones,
usuarios y claves. Para mover un solo bot a otra instalación usá «Exportar agente» / «Importar agente» (no lleva
versiones, conversaciones ni claves).

## Como servicio

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

## Detrás de un proxy con HTTPS

Leé antes [security.md](security.md#antes-de-exponerlo-a-internet). Lo más seguro es publicar solo lo que
necesitan el widget y tus integraciones, y administrar por un túnel SSH:

```sh
ssh -L 8000:127.0.0.1:8000 usuario@tu-servidor     # y abrís http://127.0.0.1:8000 en tu compu
```

Caddy (`Caddyfile`), solo API pública y widget:

```
bots.midominio.com {
    @public path /api/v1/* /static/widget.js
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

    location /api/v1/ { proxy_pass http://127.0.0.1:8000; }
    location = /static/widget.js { proxy_pass http://127.0.0.1:8000; }
    location / { return 404; }
}
```

Notas:

- El widget se carga desde `https://bots.midominio.com/static/widget.js` y le habla a ese mismo servidor. Agregá
  el sitio donde lo pegás en **Widget web → sitios autorizados**.
- Tu backend puede llamar a `https://bots.midominio.com/api/v1/...` con una clave de API.
- **La interfaz completa detrás de un dominio propio no funciona tal cual hoy**: el navegador manda
  `Origin: https://bots.midominio.com` en los pedidos que cambian algo y Parla solo acepta `127.0.0.1`/`localhost`
  como propios, así que responde 403. Para administrar de forma remota usá el túnel SSH.
- Parla no tiene límite de pedidos propio (salvo en el login): si lo exponés, agregalo en el proxy.

## Varias instancias

Parla guarda el estado en archivos y en memoria (sesiones de login, modelos cargados): corré **una sola
instancia** por carpeta de datos. Para más bots, alcanza con una instancia; para aislarlos, usá carpetas
(`PARLA_DATA`) y puertos distintos.
