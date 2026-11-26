# Seguridad

[English](security.md) · **Español**

Parla está pensado para correr en tu compu o en un servidor tuyo, con una sola persona o un equipo chico que lo
administra. Esta página cuenta qué protege, qué no, y qué hacer antes de exponerlo.

## Modelo de amenazas

- **Local primero.** Sin configurar nada escucha solo en `127.0.0.1` (`PARLA_HOST` lo cambia; la imagen de
  Docker usa `0.0.0.0`). La interfaz de administración está pensada para usarse desde esa misma máquina o por un
  túnel.
- **Sin usuarios, está abierto.** Mientras no exista ningún usuario no se pide login ni clave: **cualquiera que
  llegue al puerto es dueño** y puede leer, cambiar y borrar todos los bots, sus conversaciones y sus claves. La
  revisión de `Host` (ver más abajo) frena a los navegadores, pero un programa como `curl` puede mandar
  `Host: localhost` y pasa igual.
- **Creá el dueño antes de exponerlo.** Mientras no haya usuarios, el primero que haga `POST /api/users` crea el
  dueño, sea quien sea. No hay usuario ni contraseña por defecto (no existe un `admin/admin`): el primer usuario lo
  creás vos en **Usuarios** y queda como dueño (`owner`). Desde ese momento todo `/api/` pide sesión o clave,
  salvo el chat público del widget.
- Quien puede editar un bot es de confianza: puede hacer que el servidor llame a cualquier URL (pasos `http`) y,
  si las funciones están prendidas y es dueño, correr código en la máquina.
- Quien chatea con el bot (el widget o tu integración) no es de confianza: lo que escribe nunca puede cambiar la
  dirección de un paso `http`, pero sí llega como texto a encabezados y cuerpos (ver [Pasos HTTP](#pasos-http)).

## Usuarios y sesiones

- Los usuarios se guardan en `users.json` (permisos 600) en la carpeta de datos, o donde diga `PARLA_USERS`.
- Contraseñas con scrypt (`n=2^14, r=8, p=1`) y sal aleatoria por usuario. Mínimo 5 caracteres, sin otras reglas:
  si lo exponés, usá contraseñas largas.
- El login da la cookie `parla_session`: `HttpOnly`, `SameSite=Strict`, `Path=/`, válida 12 horas. Lleva
  `Secure` si `PARLA_SECURE_COOKIE=1`, o si el pedido trae `X-Forwarded-Proto: https` y su `Host` es uno de
  `PARLA_HOSTS` (un proxy con HTTPS delante). Sin eso, la cookie viaja también por HTTP. Si el proxy reescribe el
  `Host` (nginx con `proxy_pass` lo hace por defecto), la segunda condición no se cumple: usá
  `PARLA_SECURE_COOKIE=1`.
- Las sesiones se guardan en `parla.db`, en la carpeta de datos, solo como el SHA-256 del valor de la cookie:
  sobreviven a un reinicio. El rol y los bots de cada usuario se leen de `users.json` en cada pedido, así que un
  cambio de rol vale al instante.
- Cambiar la contraseña o borrar un usuario cierra sus sesiones. Salir (`/api/auth/logout`) borra la sesión.
- **Bloqueo de login:** después de 5 intentos fallidos en un minuto para el mismo nombre de usuario y la misma IP,
  el login responde 429 hasta que pase el minuto. Detrás de un proxy la IP es la del proxy (Parla no lee
  `X-Forwarded-For`): el bloqueo pasa a ser por usuario, y alguien puede trabar el login de otro un minuto por
  vez. Un usuario que no existe tarda lo mismo en contestar que uno que sí.

## Inicio de sesión único (OIDC)

Es opcional: con `PARLA_OIDC_ISSUER` y `PARLA_OIDC_CLIENT_ID` definidas, la pantalla de entrada muestra
**Entrar con {label}** al lado del formulario de contraseña. La configuración por proveedor está en
[sso_es.md](sso_es.md). Cómo se protege:

- **Flujo:** authorization code con PKCE (`S256`). `GET /api/auth/oidc/start` guarda el state (como su SHA-256),
  el nonce y el verificador de PKCE en la tabla `oidc` de `parla.db`, y deja el state en la cookie `parla_oidc`
  (`HttpOnly`, `SameSite=Lax`, `Path=/api/auth/oidc`, 10 minutos). La vuelta exige que el `state` de la URL
  coincida con esa cookie, lo que ata el login al navegador que lo empezó (contra el CSRF de login), y el state
  guardado se borra al primer uso.
- **Validación del ID token:** la firma se verifica con la JWKS del proveedor, solo RS256, RS384 o RS512 (se
  rechazan `none`, `HS*` y `ES*`) y solo con claves RSA de 2048 bits o más. Después `iss` tiene que ser
  exactamente el issuer del discovery, que a su vez tiene que ser igual a `PARLA_OIDC_ISSUER`; `aud` tiene que
  incluir el client id; `azp` se revisa si viene o si hay varias audiencias; `exp` e `iat` con 60 s de margen; y el
  `nonce`.
- **Sin dependencias de criptografía.** La verificación RSA PKCS#1 v1.5 está en Python puro (solo biblioteca
  estándar): arma el bloque esperado completo (`00 01 FF…FF 00` + DigestInfo + hash) y lo compara entero, no
  parsea la firma descifrada. OIDC Core §3.1.3.7 permite no verificar la firma de un token que llega directo del
  token endpoint por TLS; Parla la verifica igual, como defensa en profundidad.
- El discovery y la JWKS se guardan 1 hora en caché; un `kid` desconocido vuelve a traer la JWKS (rotación de
  claves). Las URLs del proveedor tienen que ser `https://` (salvo `localhost` / `127.0.0.1`, para pruebas).
- **Redirect URI:** `PARLA_PUBLIC_URL` + `/api/auth/oidc/callback`. Sin `PARLA_PUBLIC_URL`, se usa el `Host` del
  pedido solo si es local o de `PARLA_HOSTS`; cualquier otro `Host` se rechaza.
- La vuelta es una navegación desde otro sitio, así que no pasa por el chequeo de Origin (la protegen state, nonce
  y PKCE). El chequeo de Host sí: poné tu host público en `PARLA_HOSTS`.
- **Los usuarios se buscan por `sub`, nunca por nombre.** Un usuario del proveedor que se llama igual que uno
  local recibe un nombre con sufijo (`ana-1a2b3c`); nunca se queda con la cuenta local. Los usuarios de SSO se
  guardan en `users.json` con `sso: true`, `sub` y `email`, sin contraseña.
- **Roles:** con mapa de roles (`PARLA_OIDC_ROLE_CLAIM` + `PARLA_OIDC_ROLE_MAP`) el rol se recalcula en cada
  login; los `bots` que ve el usuario se mantienen. Sin un rol mapeado y sin `PARLA_OIDC_DEFAULT_ROLE`: no entra.
  Sin mapa de roles, los usuarios nuevos reciben `PARLA_OIDC_DEFAULT_ROLE` (si no está: no entran) y los que ya
  existen se quedan con el rol que tienen en Parla, que el dueño puede cambiar.
- **`PARLA_OIDC_ONLY=1`** apaga el login con contraseña, salvo el de emergencia para un **dueño** cuando la
  conexión llega del loopback, el `Host` es `127.0.0.1`, `localhost` o `[::1]` y el pedido no trae
  `X-Forwarded-For`, `X-Forwarded-Host`, `X-Real-IP` ni `Forwarded`. Un proxy en la misma máquina también conecta
  desde el loopback: **tiene que** mandar alguno de esos encabezados (p. ej. `X-Forwarded-For`), o sus pedidos
  parecerían locales.
- Con OIDC configurado y sin usuarios, el login se pide igual, y el primer dueño local solo se puede crear con el
  acceso de emergencia (desde la misma máquina, como arriba).
- Las claves de API siguen andando como siempre, también con `PARLA_OIDC_ONLY`.
- **Auditoría:** cada intento queda como `login.sso` con `ok` o `falló: <motivo>` y la IP. Los tokens nunca se
  guardan ni se anotan.
- **Salir** cierra la sesión de Parla. Si el proveedor tiene `end_session_endpoint`, después manda el navegador
  ahí con `client_id` (y `post_logout_redirect_uri` si está `PARLA_PUBLIC_URL`). No va `id_token_hint` porque los
  tokens no se guardan; los proveedores que lo exigen (Okta) necesitan `PARLA_OIDC_LOGOUT=0`, que lo apaga.

Límites a tener en cuenta:

- Una sesión de Parla dura 12 horas, diga lo que diga el proveedor. No hay back-channel logout: desactivar a
  alguien en el proveedor vale en su próximo login o cuando vence la sesión. Para cortarlo ya, borrá el usuario en
  **Usuarios** (eso cierra sus sesiones), pero puede volver a entrar por SSO mientras el proveedor lo deje.
- Un usuario que sacás de todos los grupos mapeados pierde el acceso en su próximo login, no antes.
- El proveedor puede bajarle el rol al último dueño (manda el mapa de roles). Mantené un dueño local para
  emergencias.
- Sin ID tokens ES256 ni EdDSA; un solo issuer por instalación; no se soporta el issuer multi-tenant `common` de
  Entra ID (usá el del tenant); con el overage de grupos de Entra ID (con más de 200 grupos la claim se cambia por
  un enlace) usá app roles (la claim `roles`).

## Registro de auditoría

Parla anota las escrituras que salieron bien en la tabla `audit` de `parla.db`: quién (usuario y rol), cuándo, en
qué agente, qué y un detalle corto. El dueño lo ve en **Auditoría** (`#/auditoria`, desde el menú del avatar, al
lado de «Administrar usuarios») o con `GET /api/audit` ([api_es.md](api_es.md)); los otros roles reciben 403.

- Acciones: `login` (bien **y mal**, con la IP; nunca la contraseña), `login.sso` (`ok` o `falló: <motivo>`, con
  la IP; nunca los tokens), `logout`, `user.create`, `user.update`,
  `user.role`, `user.delete`, `key.create` (también «Conectar con IA»), `key.revoke`, `agent.create`,
  `agent.import`, `agent.save`, `agent.delete`, `agent.train`, `agent.publish`, `agent.deploy`, `agent.restore`,
  `secret.set` / `secret.delete` (solo el nombre, nunca el valor), `file.upload` / `file.delete`,
  `channel.update` (un guardado que cambió `channels`), `channel.telegram`, `inbox.take` / `inbox.release` /
  `inbox.reply`, `session.delete` y, para los mensajes salientes, `outbound.send`, `campaign.create`,
  `campaign.update`, `campaign.delete`, `campaign.recipients`, `campaign.start` / `campaign.pause` /
  `campaign.resume` / `campaign.cancel`, `optout.add` y `optout.remove` (con el teléfono tapado: `549••••••5678`).
- La interfaz guarda sola cada ~400 ms: los `agent.save` seguidos del mismo usuario en el mismo agente dentro de 5
  minutos se juntan en una sola entrada.
- Sin usuarios configurados, las entradas quedan con el usuario vacío.
- La limpieza de cada hora borra las entradas de más de `PARLA_AUDIT_DAYS` días (365 por defecto).
- No anota lecturas ni cada pedido: para eso, el log de accesos del proxy.

## Datos personales en las conversaciones

- **Retención:** `retention_days` en el agente (o `PARLA_RETENTION_DAYS` para todos) borra las conversaciones sin
  movimiento en esa cantidad de días. Sin ninguno de los dos, se guardan para siempre. Ver
  [concepts_es.md](concepts_es.md#retención-y-datos-personales).
- **Tapado (`pii_redaction`):** cambia emails, teléfonos, tarjetas, documentos y cuentas bancarias por «[email]»,
  «[teléfono]», etc. en lo que se **guarda** (historial, Bandeja, «lo que no entendió», analíticas, el historial de
  la API). El turno en vivo (el flujo, los pasos `http`, las funciones y la respuesta de ese turno) sigue viendo el
  valor real, y el estado de trabajo de la conversación lo guarda hasta que termina; con el tapado prendido, las
  conversaciones quietas por 24 h se cierran para que se borre.
- El tapado es una heurística (expresiones regulares): se le puede escapar un formato o tapar un número que no es
  un dato personal. No reescribe lo que ya estaba guardado cuando lo prendés y no se aplica a lo que el servidor
  escribe en la consola.

## Claves de API

- Para la API y el MCP: `Authorization: Bearer parla_...`. Se crean en **Usuarios → un usuario → Claves de API**
  (solo el dueño maneja usuarios y claves, de cualquier usuario).
- Actúan con el rol y los bots **del usuario al que pertenecen**: una clave de un analista solo puede hacer `GET`.
  Una clave creada con `"scope": "integration"` solo llega a las rutas del contact center (ver [Webhooks salientes](#webhooks-salientes)).
- Se muestran una sola vez. Se guardan como hash SHA-256 en `users.json`; borrar la clave (o el usuario) la corta
  al instante.
- Con una clave válida se puede llamar a `/api/` aunque el `Host` no sea uno conocido (tu backend detrás de un
  proxy). Con cookie, no: el `Host` tiene que ser local o de `PARLA_HOSTS`.

### «Conectar con IA» (`/api/connect`)

Con usuarios creados, cada vez que alguien aprieta **Conectar** Parla **crea una clave nueva** para ese usuario
(«Conectar con Claude Code», etc.) y la deja en la configuración del asistente:

- En Claude Code se registra con `claude mcp add ... -e PARLA_TOKEN=parla_...`: la clave va **en la línea de
  comandos**, así que mientras corre ese comando la ve cualquiera que pueda listar procesos (`ps`) en la máquina.
- En todos los asistentes queda escrita en texto plano en su archivo de configuración (`~/.claude.json`,
  `~/.codex/config.toml`, la configuración de Claude Desktop o `~/.cursor/mcp.json`), con los permisos normales
  de ese archivo.
- Desconectar no borra la clave, y reconectar crea otra. **Borrá las viejas** en **Usuarios → Claves de API**.
- Solo responde si el `Host` es exactamente `127.0.0.1:<puerto>` o `localhost:<puerto>`: no anda a través de un
  proxy. Pide `POST` con `Content-Type: application/json`, así que un analista o un usuario de atención no puede.

## Roles

| Rol | En la interfaz | Puede |
|---|---|---|
| `owner` | Dueño | Todo, incluido manejar usuarios y claves. Siempre ve todos los bots. Es el único que puede crear o cambiar código de funciones mientras están prendidas. Tiene que quedar al menos uno. |
| `editor` | Editor | Todo sobre los bots que ve, menos manejar usuarios y claves. Con las funciones prendidas **no puede agregar ni cambiar código de funciones**: ni al guardar el bot, ni al importar uno que las traiga, ni al restaurar una versión con funciones distintas, ni con «Probar» (403). Sí puede borrarlas o reordenarlas. |
| `analyst` | Analista | Solo pedidos `GET`, en todo lo que ve: la definición de los bots, conversaciones, reportes, bandeja, nombres de claves. Cualquier otro método: 403. |
| `agent` | Atención | Una vista mínima: la lista de bots y cada bot sin su definición (sin intenciones, flujos, funciones ni conocimiento), la Bandeja (`inbox`), tomar, responder y devolver conversaciones, y leer una conversación por `/api/v1/bots/{bot}/sessions/{id}`. Todo lo demás: 403. |

Con las funciones apagadas (`PARLA_FUNCTIONS=0`) la regla del código no aplica: el editor puede guardar funciones,
pero no corren.

## Bots por usuario

Cada usuario que no es dueño tiene `bots`: `null` (ve todos) o una lista de ids. Un bot que no ve responde **404**,
como si no existiera, en `/api/agents/{id}/...` y `/api/v1/bots/{bot}/...`; las listas muestran solo los suyos. Si
alguien con lista crea o importa un bot, se le suma. El chequeo de bot va antes que el de rol.

## Pedidos de otros sitios: Host, Origin y `PARLA_HOSTS`

Dos chequeos protegen un Parla local de las páginas que abrís en el navegador:

- **Origin:** un pedido a `/api/` con encabezado `Origin` se rechaza con 403 salvo que su host sea
  `127.0.0.1:<puerto>` o `localhost:<puerto>` (el puerto en el que escucha Parla), uno de `PARLA_HOSTS`, o un
  sitio autorizado del widget para las rutas del chat. Junto con `SameSite=Strict` evita que otra página use tu
  sesión.
- **Host (contra DNS rebinding):** un pedido a `/api/` cuyo `Host` no es `127.0.0.1`, `localhost` o `[::1]`
  (cualquier puerto) ni uno de `PARLA_HOSTS` se rechaza con 403, salvo que traiga una clave de API válida o sea el
  chat público del widget. Así un dominio que apunta a `127.0.0.1` no puede hablarle a tu Parla.

`PARLA_HOSTS` es una lista separada por comas de `host` o `host:puerto` por los que también se entra a Parla, por
ejemplo `PARLA_HOSTS=bots.midominio.com`. Con eso la interfaz completa anda detrás de un proxy en ese dominio
(login incluido). Sumá ahí también `localhost:9000` si publicás el puerto con otro número (`-p 9000:8000`).

`/`, `/static/*.js` y `/files/...` no pasan por estos chequeos (no son `/api/`).

## El widget: qué puede hacer alguien sin sesión

Si un bot tiene el widget prendido, estas rutas de **ese bot** responden sin sesión ni clave:

- `POST /api/v1/bots/{bot}/events` y `POST /api/v1/bots/{bot}/audio`
- `GET /api/v1/bots/{bot}/sessions/{id}/messages`, solo para conversaciones del canal `web`

Un pedido público queda limitado:

- Siempre canal `web` y entorno `production`: se ignoran `channel` y `environment` del cuerpo.
- No puede precargar datos (`data` en `start`) y la respuesta no trae `trace`.
- No puede seguir, leer ni terminar una conversación de otro canal (403).
- El audio público tiene un máximo de 2 MB.
- No puede leer la definición del bot, la lista de conversaciones, el detalle con slots ni reportes.

Lo que hay que tener en cuenta:

- **CORS no es control de acceso.** `widget.origins` (o `*`) solo decide qué sitios pueden llamar desde un
  navegador. Cualquier programa que no sea un navegador (sin `Origin`) puede usar estas rutas públicas de
  cualquier bot con el widget prendido: chatear, mandar audios (que el servidor transcribe) y leer conversaciones
  `web` de las que conozca el id.
- **El id de conversación es la única llave.** El widget lo genera en el navegador con `crypto.randomUUID()`
  (`web-` + 32 hexadecimales) y lo guarda en `localStorage`; si el navegador no tiene `randomUUID` (página sin
  HTTPS en navegadores viejos) usa la hora y `Math.random()`, que es adivinable. Quien tenga ese id puede leer la
  conversación y seguirla. Si mandás eventos `web` desde tu backend, usá ids aleatorios, no un DNI o un teléfono.
- Quien conozca el nombre o id del bot puede chatear con él: no pongas en esos flujos datos que no darías en tu
  web.
- Un usuario con sesión que ve el bot usa esas mismas rutas sin los límites públicos.

## Canales de mensajería (WhatsApp y Telegram)

Los webhooks `GET`/`POST /api/v1/bots/{bot}/whatsapp` y `POST /api/v1/bots/{bot}/telegram`, y las rutas del teléfono
de abajo, son las únicas rutas de `/api/` que se saltean el login y el chequeo de `Host`: los llaman los servidores de
Meta, Telegram y el proveedor de telefonía. En cambio,
cada pedido se autentica solo:

- `POST` de WhatsApp: `X-Hub-Signature-256` tiene que ser `sha256=` + el HMAC-SHA256 del cuerpo tal cual con la clave
  secreta de la app (`WHATSAPP_APP_SECRET`). El `GET` de verificación tiene que traer `hub.verify_token` igual a
  `WHATSAPP_VERIFY_TOKEN`.
- `POST` de Telegram: `X-Telegram-Bot-Api-Secret-Token` tiene que ser igual a `TELEGRAM_WEBHOOK_SECRET` (lo genera
  Parla al tocar **Conectar webhook**).
- Se compara en tiempo constante. Canal apagado, clave que falta o firma mala: **403 sin detalles**. Cuerpo hasta 1 MB.
- Solo se atienden mensajes del `phone_number_id` configurado; un id de mensaje repetido se atiende una vez.
- Los tokens (`WHATSAPP_TOKEN`, `TELEGRAM_TOKEN`) y secretos viven en la bóveda, nunca en el JSON del agente; los
  errores de envío van a la consola con los valores tapados.
- Los ids de conversación (`wa-<teléfono>`, `tg-<chat>`) tienen el teléfono o el chat de la persona.
- El bot contesta con el entorno `production`. Los webhooks no pueden precargar datos, leer conversaciones ni llegar
  a otra ruta.

Configuración y límites en [channels_es.md](channels_es.md).

### Llamadas telefónicas (Twilio y jambonz)

- `POST /api/v1/bots/{bot}/phone/twilio[/gather|/status]`: `X-Twilio-Signature` tiene que ser el HMAC-SHA1 en base64,
  con `TWILIO_AUTH_TOKEN`, de la URL pública (`public_url` / `PARLA_PUBLIC_URL` + la ruta y la query pedidas) seguida
  de cada clave y valor del POST ordenados por clave, como lo calcula Twilio.
- `POST /api/v1/bots/{bot}/phone/jambonz[/gather|/status]`: con `JAMBONZ_WEBHOOK_SECRET` cargada, `Jambonz-Signature`
  (`t=<unix>,v1=<hex>`) tiene que ser el HMAC-SHA256 de `<t>.<cuerpo tal cual>` y `t` de hace menos de 5 minutos
  (repetir pedidos viejos no sirve); con `JAMBONZ_BASIC_USER` y `JAMBONZ_BASIC_PASSWORD` cargadas, `Authorization:
  Basic` tiene que coincidir. Cada método cargado tiene que dar bien; sin ninguno cargado, no pasa nada.
- Solo se acepta el proveedor elegido en `channels.phone.provider`, y solo con `channels.phone.enabled`. Se compara
  en tiempo constante; si falla, **403 sin detalles**; cuerpo hasta 1 MB.
- **Audios con dirección firmada** (`tts: "parla"`): `GET /api/v1/bots/{bot}/phone/audio/<token>.wav` sirve solo el
  texto que va adentro del token, que lleva el id del bot, el vencimiento (10 minutos) y el idioma, firmado con
  HMAC-SHA256 con una clave al azar que vive en la memoria del servidor. No se puede falsificar, usar para otro bot ni
  después de vencido, y no abre nada más. Quien tenga una dirección puede escuchar esa frase hasta que venza (los
  proveedores las bajan sin autenticarse).
- Con Twilio, el audio de quien llama lo transcribe Twilio (el audio y el texto salen de tu servidor). Con jambonz,
  va a donde apunten sus servicios de voz, que pueden ser propios.
- El id `call-<CallSid>` y el número de quien llama (guardado en un slot `caller` si el bot lo tiene, y que también
  guarda el proveedor) son datos personales; `pii_redaction` tapa los teléfonos en lo que se guarda.

## Mensajes salientes y campañas

El bot puede escribir primero: la API de salida, campañas y recordatorios ([outbound_es.md](outbound_es.md)).

- **Quién:** `POST /api/v1/bots/{bot}/outbound`, crear, cambiar, iniciar o cancelar campañas y manejar las bajas
  necesitan `owner` o `editor`. `analyst` ve las campañas, los resultados, el CSV exportado y las bajas, solo
  lectura. `agent` (atención) no ve nada de esto. La ruta de salida nunca es pública, aunque el widget esté prendido.
- **Auditoría:** cada envío por la API, cada cambio y acción de una campaña y cada baja a mano quedan en el
  [registro de auditoría](#registro-de-auditoría), con el teléfono tapado.
- **Números tapados:** en la auditoría y en los errores de la consola. La interfaz y la API de administración los
  muestran a quien puede ver el bot, y los ids de conversación (`wa-<teléfono>`) los siguen teniendo.
- **Límites de envío:** `agent.outbound.api_per_minute` envíos por minuto con la API por agente (30 por defecto,
  429 si se pasa); el ritmo de cada campaña (de 1 por minuto a 50 por segundo); 10.000 destinatarios por campaña
  (`agent.outbound.max_recipients`, `PARLA_CAMPAIGN_MAX`). Los contadores viven en memoria.
- **Retención y datos personales:** con `retention_days` (o `PARLA_RETENTION_DAYS`), los destinatarios de las
  campañas que terminaron hace más de esos días se borran (números y datos) y quedan solo los totales; también las
  filas viejas de la API y de recordatorios. Con `pii_redaction`, los datos de una fila de campaña o recordatorio se
  tapan apenas sale. Borrar el agente borra sus campañas, la cola y las bajas.
- **Llamadas salientes:** el proveedor vuelve a llamar al webhook firmado de siempre con un `?o=<token>` aleatorio
  que identifica el envío; la firma lo cubre. Para llamar hacen falta `TWILIO_ACCOUNT_SID` o `JAMBONZ_API_KEY` /
  `JAMBONZ_ACCOUNT_SID` en la bóveda.
- **Consentimiento:** las palabras de baja («STOP», «BAJA») se respetan solas, y a quien se dio de baja no se le
  puede mandar (409). Pedir el consentimiento antes de escribir y respetar el horario de silencio y los registros de
  «no llame» corre por tu cuenta: ver [Consentimiento y leyes](outbound_es.md#consentimiento-y-leyes).

## Bóveda de claves (secretos)

En **Publicar → Claves** cargás tokens y contraseñas de servicios externos por agente.

- Se guardan aparte, en `agents/<id>.secrets.json` (permisos 600), **sin cifrar**: protegé la carpeta de datos
  como protegerías un `.env`. Se borran al borrar el agente.
- Nunca están en el JSON del agente: no viajan al exportar ni quedan en las versiones publicadas.
- La interfaz, la API y el MCP solo ven los **nombres**; los valores nunca vuelven por la API y el MCP no puede
  leerlos ni cargarlos.
- Solo se resuelven en la URL, los encabezados y el cuerpo de un paso `http` (`{{ secret.NOMBRE }}`), como
  entrada `secret.NOMBRE` de una función y como API key de los proveedores de IA y de voz (`ai.api_key_secret`, y
  `api_key_secret` en `voice.asr` / `voice.tts`). En mensajes no se resuelven. `/api/ai/status` nunca devuelve la key de la IA y la tapa en sus errores.
- Cualquier valor de 4 o más caracteres que aparezca en una traza o en un mensaje de error del flujo se tapa con
  `••••`. **No** se tapa lo que devuelve el servicio o la función: si una respuesta trae la clave y la guardás en
  un slot, queda en la conversación.

## Postgres y varias réplicas

- `PARLA_DATABASE_URL` lleva la contraseña de la base: va en un Secret (en Helm `database.existingSecret`), no en un
  values ni en un ConfigMap, y con `sslmode=require` (o `verify-full`) si Postgres no está en la misma máquina. El
  usuario necesita crear tablas en su schema; nada más (ni superusuario ni extensiones).
- Postgres tiene lo mismo que `parla.db` (conversaciones, hashes de las sesiones de login, auditoría): cifralo en
  reposo y limitá quién se conecta, como con la carpeta de datos. Los tokens de sesión se guardan hasheados
  (SHA-256), como antes.
- `PARLA_SECRET_KEY` firma las direcciones de audio que Parla le da al proveedor de telefonía; todas las réplicas
  necesitan el mismo valor, y quien lo tenga puede falsificar esas direcciones por 10 minutos. Generalo con
  `openssl rand -hex 32` y guardalo en un Secret.
- La bóveda de claves sigue en archivos en el volumen de datos compartido (permisos 600, sin cifrar, como en un
  servidor): un volumen ReadWriteMany tiene que ser tan privado como la base (storage class cifrada, sin otras cargas).

## Proveedores de IA y de voz en la nube: los datos salen de la máquina

Por defecto todo corre en tu máquina: la IA con Ollama, el reconocimiento de voz con faster-whisper y la voz del
bot con piper. Si un agente usa un proveedor en la nube (con tu propia key, ver
[ai-and-voice_es.md](ai-and-voice_es.md)), esto es lo que le llega, sujeto a sus condiciones (retención,
entrenamiento, región) y cobrado al dueño de la key:

| Proveedor | Qué sale de la máquina |
|---|---|
| IA `ollama` | Nada. |
| IA `openai`, `openai_compatible` (si la dirección no es tuya), `anthropic`, `gemini` | El texto de la conversación y los turnos recientes, la persona, los fragmentos de la base de conocimiento que se usan para responder y los resultados de las herramientas en el paso agente. |
| Transcripción (`voice.asr`: OpenAI, Deepgram, ElevenLabs, Google) | El audio del usuario y las pistas de vocabulario (los valores y sinónimos de las entidades del bot). |
| Voz del bot (`voice.tts`: OpenAI, Deepgram, ElevenLabs, Google) | El texto de las respuestas del bot. |

- Los embeddings, las intenciones y la búsqueda en la base siguen siendo locales. Las pantallas de IA y de voz
  avisan cuando los datos salen de la máquina.
- **Las keys** salen solo de la bóveda del agente (**Claves**) por nombre (`api_key_secret`), nunca del JSON del
  agente (el `validate` del MCP rechaza un `api_key`). Se tapan (`••••`) en todo error, log y traza, también cuando
  un proveedor devuelve la key en el cuerpo de su error.
- **Direcciones fijas:** la dirección de cada proveedor está fija en el código (solo `openai_compatible` y `openai`
  con `url` usan la dirección que cargás), así que estas llamadas no abren una superficie de SSRF. Los
  `PARLA_*_BASE_URL` (pruebas, proxies) son variables de entorno: solo las puede poner quien corre el servidor.
- Toda llamada a un proveedor tiene tiempo límite (30 s para la voz; la IA usa el presupuesto de tiempo de quien la
  llama).
- Cargar y borrar una clave ya queda en el [registro de auditoría](#registro-de-auditoría).
- Solo dueños y editores pueden cambiar el proveedor de IA o de voz de un agente o probarlo con su key; revisá los
  agentes que arme otra persona antes de prenderlos.

## Pasos HTTP

- En la URL, el valor de cada slot va codificado (`/`, `?`, `&`, `#` incluidos): lo que escribe la persona no
  puede cambiar el host ni la ruta. Los `{{ secret.X }}` van tal cual. La URL tiene que empezar con `http://` o
  `https://`.
- En encabezados, cualquier salto de línea (`\r` o `\n`) corta el paso con error.
- **El cuerpo no se escapa:** el valor del slot entra como texto. Si armás un JSON con `"{{ nombre }}"`, una
  comilla en lo que escribió la persona puede cambiar ese JSON. Validá esos slots (entidades, formato) o armá el
  cuerpo en una función.
- Tiempo máximo 10 s, se leen hasta 1 MB de respuesta y se siguen las redirecciones.
- **SSRF:** un paso `http` llama a cualquier URL a la que llegue el servidor de Parla: tu red interna, `localhost`
  (Ollama, otros servicios) o el servicio de metadatos de la nube (`169.254.169.254`). «Probar consulta» le
  devuelve la respuesta a quien la prueba. Lo mismo vale para importar conocimiento desde una URL y para la
  dirección de la IA de un agente. Cualquier editor puede usarlo: revisá los bots que arme una IA o alguien más,
  y en Kubernetes limitá la salida con una `NetworkPolicy` de egress (o el firewall del servidor).

## Webhooks salientes

Los webhooks de la derivación (`agent.webhooks`, [contact-centers_es.md](contact-centers_es.md)):

- **Firmados:** `Parla-Signature: t=<unix>,v1=<HMAC-SHA256 de "t.cuerpo">` con la clave `secret_name` de la bóveda.
  Sin esa clave no sale nada (se reintenta hasta que la cargues). El que recibe tiene que verificar con el cuerpo
  crudo, rechazar `t` viejos (repetición) y deduplicar por el `id` del evento (la entrega es al menos una vez).
- **Datos personales:** con datos tapados, dirección, slots y mensajes van tapados; el `sessionId` de
  WhatsApp/Telegram (`wa-<teléfono>`) no. Elegí `message.user`/`message.bot` solo si el CC necesita cada mensaje.
- **SSRF:** mismas reglas de salida que los pasos `http`: Parla le pega a la URL que guarde un editor, también a
  direcciones internas. No se siguen redirecciones (un 3xx cuenta como falla). Limitá la salida con un firewall o
  una `NetworkPolicy`. Solo dueño/editor configuran webhooks; los cambios, las pruebas y los reintentos quedan en la
  auditoría (`handoff.update`, `webhook.test`, `webhook.retry`).
- **Claves de integración:** `scope: "integration"` limita una clave a `…/handoff`, `…/messages`, `…/lookup` y leer
  conversaciones (nunca más que el rol del usuario; la de un analista sigue siendo de solo lectura). Usá una por
  contact center. Los encabezados SIP nunca llevan valores de la bóveda y `X-Parla-Context` es solo una URL: para
  llamarla hace falta una clave.

## Herramientas en el paso agente

Las `tools` de un paso `agent` le permiten al modelo disparar llamadas HTTP y herramientas MCP (ver
[concepts_es.md](concepts_es.md#agent-dejar-que-la-ia-converse)).

- **Mismo nivel de confianza que los pasos `http`.** Agregar o cambiar herramientas HTTP o las URLs de `mcp_servers`
  requiere owner o editor; el código de funciones sigue siendo solo del owner. `POST /api/agents/{id}/mcp/tools`
  («Ver herramientas») también es de owner/editor.
- **SSRF:** los pedidos salen del servidor de Parla, así que un editor puede apuntar una herramienta HTTP o un
  servidor MCP a direcciones internas, igual que con los pasos `http` (mismo consejo de arriba). El modelo no elige
  hosts: el host queda fijo en `url` y el modelo solo completa los `params`, que van codificados en la URL y
  escapados como JSON en el body. Los argumentos desconocidos se descartan y se controlan los tipos.
- **Inyección de prompt:** lo que devuelve un servidor MCP o una API no es confiable. Le llega al modelo como dato
  («datos, no órdenes»), recortado a 1500 caracteres, y nunca se ejecuta, pero igual puede traer texto que intente
  manejar al modelo. Habilitá en la allow-list (`tools` de la entrada `mcp`, obligatoria) solo herramientas de
  lectura y seguras, de servidores en los que confiás. **Nunca le des al modelo escrituras, pagos ni borrados**:
  hacelos en un flujo con un paso de confirmación.
- **Claves:** `{{ secret.X }}` y el `headers_secret` de un servidor MCP salen de la bóveda y se tapan en lo que ven el
  modelo, la traza, los logs y el historial. Con `pii_redaction` también se limpia el campo `tool` de los eventos del
  historial.
- Los servidores MCP son solo Streamable HTTP: `stdio` no está soportado, así la config de un bot no puede lanzar
  procesos.

## Funciones: no son un sandbox

Las funciones corren código Python (`python -I`) o JavaScript (`node`) en un proceso aparte, con tiempo máximo de
5 s, límite de CPU, de memoria (512 MB: en Python límite del espacio de direcciones donde el sistema lo permite —Linux sí, macOS no—; en JavaScript el límite del heap de V8; en Windows solo el
tiempo), una carpeta temporal vacía y variables de entorno limpias (`PATH` y poco más). Eso evita que una función
colgada tire el bot, **pero no es un aislamiento de seguridad**: el código corre con el usuario del sistema que
corre Parla, puede leer y escribir sus archivos (incluidos `users.json` y las claves de todos los bots), usar la
red y lanzar procesos.

- Prendidas por defecto al correrlo en tu compu; **apagadas en la imagen de Docker** (`PARLA_FUNCTIONS=0`), en el
  ConfigMap de Kubernetes y en el ejemplo de systemd. Se apagan con `0`, `false`, `no` u `off`.
- Con usuarios y funciones prendidas, solo el dueño puede escribir código nuevo (ver [Roles](#roles)). Una IA
  conectada por MCP con la clave del dueño sí puede.
- El código ya guardado corre cada vez que una conversación llega a ese paso, incluidas las del widget público.
- Apagadas, los pasos `function` y «Probar» fallan con un aviso.

```sh
PARLA_FUNCTIONS=0 .venv/bin/python app.py
```

## Archivos subidos

Los archivos del paso «Enviar un archivo»:

- Hasta 10 MB. Solo `pdf png jpg jpeg gif webp txt csv doc docx xls xlsx ppt pptx zip`. El tipo sale de la
  extensión, nunca del navegador: no se aceptan HTML ni SVG.
- Se sirven con `X-Content-Type-Options: nosniff`. PDF, imágenes y `.txt` se abren en el navegador; el resto se
  descarga. El nombre se limpia en `Content-Disposition`.
- Se sirven **sin sesión** en `/files/<agente>/<id>`: el id es aleatorio (128 bits) y hace de llave. Quien tenga
  el enlace lo puede bajar.

## Límites de pedidos y errores

- Cuerpo JSON (si no, 413): 1 MB en general; 25 MB para crear, importar o guardar un agente, subir archivos,
  extraer conocimiento, dictado y `POST /api/v1/bots/{bot}/audio`; 2 MB para un audio público del widget.
- Un mensaje se corta a 4000 caracteres; se guardan los últimos 500 mensajes por conversación.
- Una conexión sin datos durante 30 s se corta (contra conexiones lentas a propósito).
- Errores pensados para la persona: 400 con el mensaje. Cualquier otro error: 500 con un mensaje genérico, sin
  rutas ni detalles; el detalle va a la consola de Parla (sin tapar claves).

## MCP con `--http`

`mcp_server.py --http` **no tiene autenticación**: quien llegue a su puerto actúa con la clave de `PARLA_TOKEN`
(o con todo, si Parla no tiene usuarios). Escucha en `127.0.0.1` por defecto (`--host` lo cambia). Si lo publicás,
protegelo en el proxy y configurá `PARLA_MCP_ALLOWED_HOSTS` (los `Host` aceptados, además de `127.0.0.1` y
`localhost`). Con `stdio` (lo normal) no abre ningún puerto.

## Métricas y trazas

Todo apagado por defecto ([observability.md](observability_es.md)).

- **`/metrics`** existe solo con `PARLA_METRICS=1`. Con `PARLA_METRICS_TOKEN` pide `Authorization: Bearer <token>`
  (comparado en tiempo constante); sin token solo le contesta a una conexión desde loopback con `Host`
  `127.0.0.1`, `localhost` o `[::1]`. Un dominio de `PARLA_HOSTS` no cuenta, porque un proxy en la misma máquina
  dejaría pasar a cualquiera. Está fuera de `/api/`: sin sesión, sin rol, sin entrada en la auditoría. No lo
  publiques en el proxy; el Ingress de ejemplo no lo hace.
- **Lo que muestran las métricas:** ids de agentes, plantillas de rutas, cantidades y latencias, proveedores de IA y
  de voz, la distribución del CSAT. Nunca mensajes, valores de slots, ids de conversación ni claves. Los valores de
  las etiquetas salen de una lista fija o son ids, y las series nuevas se cortan en 5.000: un cliente no puede
  llenar la memoria con rutas raras.
- **Las trazas** llevan ids, nombres de intenciones, flujos, entidades y funciones, confianza, estado, duraciones,
  el nombre del modelo, la cantidad de tokens y el host de cada paso `http` (no su ruta ni su query, que pueden
  traer datos o claves). De las excepciones solo va la clase. El encabezado `traceparent` que sale en los pasos
  `http` le muestra a ese servicio el id de la traza, nada más.
- **`PARLA_OTEL_CONTENT=1`** manda el mensaje de la persona y la respuesta del bot en el span `parla.turn`, con las
  claves de la bóveda reemplazadas por `••••` y todas las categorías de datos personales tapadas. Tapar es una
  heurística (ver [Datos personales](#datos-personales-en-las-conversaciones)): tratá al backend de trazas como si
  guardara conversaciones, con el mismo control de acceso y retención que `parla.db`.
- **El colector** se llama desde el servidor como un paso `http`: los `OTEL_EXPORTER_OTLP_HEADERS` (API keys) son
  variables de entorno, no están en ningún agente y nunca se loguean.

## Antes de exponerlo a internet

1. **Creá el dueño** con una contraseña fuerte antes de abrir nada, y los demás usuarios con el rol mínimo y solo
   los bots que necesitan.
2. **Escuchá en local:** dejá `127.0.0.1` (o en Docker `-p 127.0.0.1:8000:8000`) y poné delante un proxy con
   HTTPS ([deployment.md](deployment_es.md)).
3. **`PARLA_HOSTS`** con tu dominio si vas a usar la interfaz por el proxy, y `PARLA_SECURE_COOKIE=1` (o que el
   proxy mande `X-Forwarded-Proto: https`).
4. **Publicá solo lo necesario:** para el widget y tus integraciones alcanza con `/api/v1/` y `/static/widget.js`
   (más `/files/` si tus bots mandan archivos). Para administrar, preferí un túnel SSH o `kubectl port-forward`.
5. **Funciones apagadas** (`PARLA_FUNCTIONS=0`) salvo que confíes en el dueño y en las IAs que conecta.
6. **Egress:** limitá a dónde puede llamar el servidor (`NetworkPolicy`, firewall), sobre todo el servicio de
   metadatos de la nube y la red interna.
7. **Contenedor:** usuario sin privilegios (la imagen usa el uid `10001`), sistema de archivos de solo lectura
   (`--read-only --tmpfs /tmp`, o `readOnlyRootFilesystem` en Kubernetes) y sin capabilities.
8. **Copias:** la carpeta de datos tiene conversaciones, usuarios y claves (`parla.db` incluida, ver
   [deployment_es.md](deployment_es.md#copias-de-seguridad)). Guardá las copias en un lugar privado
   y mantené `users.json` y `*.secrets.json` con permisos 600 al restaurar.
9. Revisá los pasos `http`, los orígenes del widget y las claves de API viejas (sobre todo las de «Conectar con
   IA»).
10. Si usás el MCP con `--http`, protegelo en el proxy.
11. Agregá en el proxy un límite de pedidos: Parla solo lo tiene en el login.
12. Si prendés las métricas, poné `PARLA_METRICS_TOKEN` y dejá `/metrics` fuera del proxy; dejá `PARLA_OTEL_CONTENT`
    apagado salvo que el backend de trazas sea tan privado como la carpeta de datos.

## Lo que todavía no hay

- Con SQLite, una sola réplica por carpeta de datos y los contadores del bloqueo de login en memoria (se reinician
  con el servidor). Con Postgres los comparten todas las réplicas.
- Sin un límite de pedidos general: solo el bloqueo de login y los límites de salida (envíos por minuto con la API,
  ritmo de las campañas).
- Sin registro de accesos con usuarios o IPs: la auditoría anota escrituras, y `PARLA_LOG_FORMAT=json` anota cada
  pedido con su plantilla de ruta, estado y duración, pero no quién lo hizo.
- Sin segundo factor para las contraseñas locales (con [SSO](sso_es.md), tu proveedor de identidad puede pedir
  MFA), sin política de contraseñas y sin lista de sesiones abiertas para cerrarlas a mano.
- Las claves no se cifran en disco. Los agentes se guardan con los permisos normales del sistema; `users.json`, las
  claves y `parla.db` (conversaciones, hashes de los logins y la auditoría) son 600.
- Tapar datos personales es una heurística, y viene apagado.

## Reportar una vulnerabilidad

No abras un issue público. Abrí un aviso de seguridad privado en
<https://github.com/pedroslev/parla-nlu/security/advisories/new> (**Security → Report a vulnerability** en el
repositorio), con los pasos para reproducirlo. La política completa está en [SECURITY.md](../SECURITY.md).
