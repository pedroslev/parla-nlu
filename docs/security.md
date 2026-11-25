# Seguridad

Parla está pensado para correr en tu compu o en un servidor tuyo. Esta página cuenta qué protege, qué no, y qué
hacer antes de exponerlo.

## Sin usuarios, está abierto

Mientras no exista ningún usuario, **cualquiera que llegue a Parla puede leer, cambiar y borrar todos los bots y
sus conversaciones**. Es cómodo en tu compu, pero creá un usuario antes de compartirlo. El primer usuario se crea
en **Usuarios** y queda como dueño (`owner`); desde ese momento todo pide iniciar sesión.

## Usuarios y sesiones

- Contraseñas con scrypt y sal por usuario. Mínimo 5 caracteres (subilo con una política propia si lo exponés).
- La interfaz usa la cookie `parla_session` (`HttpOnly`, `SameSite=Strict`), válida 12 horas. Las sesiones viven
  en memoria: al reiniciar el servidor hay que volver a entrar.
- Después de 5 intentos fallidos en un minuto (por usuario e IP), el login responde 429.
- Cambiar la contraseña o borrar un usuario cierra sus sesiones.
- Los usuarios se guardan en `users.json` (permisos 600) en la carpeta de datos, o donde diga `PARLA_USERS`.

## Roles

| Rol | En la interfaz | Puede |
|---|---|---|
| `owner` | Dueño | Todo, incluido manejar usuarios y claves. Siempre ve todos los bots. Tiene que quedar al menos uno. |
| `editor` | Editor | Todo sobre los bots que ve, menos manejar usuarios. |
| `analyst` | Analista | Solo leer (`GET`): conversaciones, reportes, bandeja, «para enseñar». |
| `agent` | Atención | Solo la Bandeja: leer, tomar, responder y devolver conversaciones. |

## Bots por usuario

Cada usuario que no es dueño tiene `bots`: `null` (ve todos) o una lista de ids. Un bot que no ve responde 404,
como si no existiera, en la interfaz y en la API. Si alguien con lista crea o importa un bot, se le suma.

## Claves de API

Para la API y el MCP: **Usuarios → un usuario → Claves de API**. Se mandan como `Authorization: Bearer
parla_...`, actúan con el rol y los bots de ese usuario, se muestran una sola vez y se guardan solo como hash
SHA-256. Se borran desde el mismo lugar.

## Bóveda de claves (secretos)

En **Publicar → Claves** cargás tokens y contraseñas de servicios externos por agente.

- Se guardan aparte, en `<agente>.secrets.json` (permisos 600), nunca en el JSON del agente: no viajan al
  exportar ni quedan en las versiones.
- La interfaz y el MCP solo ven los **nombres**; los valores nunca vuelven por la API.
- Se usan con `{{ secret.NOMBRE }}` en URL, headers y body de un paso `http`, o como entrada `secret.NOMBRE` de una
  función. En mensajes no se pueden usar.
- Cualquier valor de 4 o más caracteres que aparezca en una traza o log se tapa con `••••`.
- No están cifrados en disco: protegé la carpeta de datos como protegerías un `.env`.

## Funciones: no son un sandbox

Las funciones corren código Python o JavaScript en un proceso aparte, con tiempo máximo (5 s), límite de CPU, de
memoria (donde el sistema lo permite; macOS no), una carpeta temporal vacía y variables de entorno limpias. Eso
evita que una función colgada tire el bot, **pero no es un aislamiento de seguridad**: el código corre con los
permisos del usuario que corre Parla, puede leer archivos y usar la red.

Quien puede editar un bot (o una IA conectada por MCP) puede correr código en tu máquina. En un Parla compartido
o expuesto, apagalas:

```sh
PARLA_FUNCTIONS=0 .venv/bin/python app.py
```

Los pasos `function` y la prueba de funciones fallan con ese aviso.

## Pasos HTTP

Un paso `http` puede llamar a cualquier URL desde el servidor de Parla, incluida tu red interna. Revisá los bots
que arme una IA o alguien más antes de usarlos con datos reales.

## Pedidos de otros sitios (Origin) y el widget

- Parla escucha **solo en `127.0.0.1`**: desde otra máquina no se llega sin un proxy.
- Todo pedido a `/api/` que trae un `Origin` distinto de `127.0.0.1:<puerto>` o `localhost:<puerto>` se rechaza
  con 403. Así una página cualquiera que abras en el navegador no puede usar tu Parla local.
- «Conectar con IA» (`/api/connect`) además exige que el `Host` sea local (contra DNS rebinding).
- **Excepción del widget**: si un bot tiene el widget prendido, `POST .../events` y `POST .../audio` de ese bot
  son públicos (es el chat de tu web), y `GET .../sessions/{id}/messages` también, pero solo para conversaciones
  del canal `web`. Las respuestas llevan CORS solo para los sitios de `widget.origins` (o `*`). Quien conozca el
  bot puede chatear con él: no pongas en esos flujos datos que no darías en tu web.

## Antes de exponerlo a internet

1. Creá un usuario dueño con una contraseña fuerte y usuarios con el rol mínimo para cada persona.
2. Arrancá con `PARLA_FUNCTIONS=0` salvo que confíes en todos los que editan bots.
3. No abras el puerto: dejalo en `127.0.0.1` y poné delante un proxy con HTTPS (ver
   [deployment.md](deployment.md)).
4. Publicá solo lo necesario: para un widget o una integración alcanza con `/api/v1/` y `/static/widget.js`.
   Para administrar desde afuera, preferí un túnel SSH a la interfaz.
5. Si usás el MCP con `--http`, protegelo en el proxy (no tiene autenticación propia) y configurá
   `PARLA_MCP_ALLOWED_HOSTS`.
6. Revisá los pasos `http` y los orígenes del widget.
7. Hacé copias de la carpeta de datos (contiene conversaciones y claves).
8. Tené en cuenta lo que todavía no hay: no se tapan datos personales en las conversaciones guardadas y no se
   borran solas.
