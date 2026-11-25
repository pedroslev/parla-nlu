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
- Las sesiones viven **en memoria**: al reiniciar el servidor hay que volver a entrar. El rol y los bots de cada
  usuario se leen de `users.json` en cada pedido, así que un cambio de rol vale al instante.
- Cambiar la contraseña o borrar un usuario cierra sus sesiones. Salir (`/api/auth/logout`) borra la sesión.
- **Bloqueo de login:** después de 5 intentos fallidos en un minuto para el mismo nombre de usuario y la misma IP,
  el login responde 429 hasta que pase el minuto. Detrás de un proxy la IP es la del proxy (Parla no lee
  `X-Forwarded-For`): el bloqueo pasa a ser por usuario, y alguien puede trabar el login de otro un minuto por
  vez. Un usuario que no existe tarda lo mismo en contestar que uno que sí.

## Claves de API

- Para la API y el MCP: `Authorization: Bearer parla_...`. Se crean en **Usuarios → un usuario → Claves de API**
  (solo el dueño maneja usuarios y claves, de cualquier usuario).
- Actúan con el rol y los bots **del usuario al que pertenecen**: una clave de un analista solo puede hacer `GET`.
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

Los webhooks `GET`/`POST /api/v1/bots/{bot}/whatsapp` y `POST /api/v1/bots/{bot}/telegram` son las únicas rutas de
`/api/` que se saltean el login y el chequeo de `Host`: los llaman los servidores de Meta y Telegram. En cambio,
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

## Bóveda de claves (secretos)

En **Publicar → Claves** cargás tokens y contraseñas de servicios externos por agente.

- Se guardan aparte, en `agents/<id>.secrets.json` (permisos 600), **sin cifrar**: protegé la carpeta de datos
  como protegerías un `.env`. Se borran al borrar el agente.
- Nunca están en el JSON del agente: no viajan al exportar ni quedan en las versiones publicadas.
- La interfaz, la API y el MCP solo ven los **nombres**; los valores nunca vuelven por la API y el MCP no puede
  leerlos ni cargarlos.
- Solo se resuelven en la URL, los encabezados y el cuerpo de un paso `http` (`{{ secret.NOMBRE }}`) y como
  entrada `secret.NOMBRE` de una función. En mensajes no se resuelven.
- Cualquier valor de 4 o más caracteres que aparezca en una traza o en un mensaje de error del flujo se tapa con
  `••••`. **No** se tapa lo que devuelve el servicio o la función: si una respuesta trae la clave y la guardás en
  un slot, queda en la conversación.

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
8. **Copias:** la carpeta de datos tiene conversaciones, usuarios y claves. Guardá las copias en un lugar privado
   y mantené `users.json` y `*.secrets.json` con permisos 600 al restaurar.
9. Revisá los pasos `http`, los orígenes del widget y las claves de API viejas (sobre todo las de «Conectar con
   IA»).
10. Si usás el MCP con `--http`, protegelo en el proxy.
11. Agregá en el proxy un límite de pedidos: Parla solo lo tiene en el login.

## Lo que todavía no hay

- Una sola réplica por carpeta de datos. Sesiones y contadores de login en memoria: se pierden al reiniciar.
- Sin límite de pedidos, salvo el bloqueo de login.
- Sin registro de auditoría ni de accesos: Parla no guarda quién cambió qué (el registro de despliegues no dice
  quién) ni loguea los pedidos. La Bandeja sí anota quién tomó y respondió cada conversación.
- Sin segundo factor, sin política de contraseñas y sin lista de sesiones abiertas para cerrarlas a mano.
- Las claves no se cifran en disco. Los agentes y las conversaciones se guardan con los permisos normales del
  sistema (solo `users.json` y las claves son 600).
- No se tapan datos personales en las conversaciones guardadas y no se borran solas.

## Reportar una vulnerabilidad

No abras un issue público. Abrí un aviso de seguridad privado en
<https://github.com/pedroslev/parla-nlu/security/advisories/new> (**Security → Report a vulnerability** en el
repositorio), con los pasos para reproducirlo. La política completa está en [SECURITY.md](../SECURITY.md).
