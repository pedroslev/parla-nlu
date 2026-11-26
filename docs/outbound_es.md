# Mensajes salientes, campañas y recordatorios

[English](outbound.md) · **Español**

Lo normal es que la persona escriba primero y el bot conteste. Con los mensajes salientes **el bot escribe
primero**: el recordatorio del turno de mañana, una encuesta de satisfacción después de una compra, el aviso de que
el pedido salió, o una llamada para confirmar una visita. Hay tres formas:

- **La API de salida** (`POST /api/v1/bots/{bot}/outbound`): tu sistema le pide a Parla que le escriba (o que
  llame) a una persona ahora. Sirve para avisos que dispara algo que pasa en tu CRM o tu backend.
- **Campañas** (**Operar → Campañas**): subís un CSV con una lista de personas, elegís qué mandar, cuándo y a qué
  ritmo, y mirás los resultados. Sirve para muchas personas a la vez.
- **Recordatorios** (el paso `remind` de un flujo): el bot programa un mensaje para más tarde a la misma persona,
  por ejemplo «24 horas antes del turno».

Las tres funcionan por **WhatsApp**, **Telegram** y **teléfono** (una llamada saliente); la API y los recordatorios
también por el **widget web**. En todos los casos es una conversación de producción normal: los datos que mandás se
precargan en los slots, corre un flujo, y cuando la persona contesta la charla sigue como si hubiera escrito ella
primero. Las bajas («STOP», «BAJA») se respetan en todos lados.

Antes de empezar, leé [Consentimiento y leyes](#consentimiento-y-leyes): escribirle a quien no lo pidió hace que te
bloqueen el número y puede ser ilegal.

## Cómo funciona

- **La misma conversación que un mensaje entrante.** El id de la conversación es el que tendría la persona si
  escribiera: `wa-<teléfono>` en WhatsApp, `tg-<chat_id>` en Telegram, `call-<CallSid>` en una llamada, y el
  `sessionId` del widget en la web. Cuando la persona contesta, cae en esa misma conversación, con los slots ya
  cargados.
- **Empieza de nuevo.** Mandar reinicia la conversación, como un evento `start`: la memoria (slots, flujo actual)
  arranca de cero, el historial se conserva y los `data` que mandás van a los slots que se llaman igual (las demás
  claves se ignoran). `idioma`, `language` o `lang` eligen el idioma, como en `start`.
- **Solo producción.** Siempre usa la versión publicada en **Producción** (o el borrador, si no publicaste nada).
  El `flow` tiene que existir ahí.
- **Qué flujo.** `flow` es el nombre del flujo que corre. Sin él, corre el flujo `__start__` (en WhatsApp hace falta
  una plantilla, ver abajo). En WhatsApp fuera de la ventana de 24 horas, el flujo corre **cuando la persona
  contesta** la plantilla.
- **Se rechaza** si la persona se dio de baja (409), si alguien del equipo está atendiendo esa conversación en la
  **Bandeja** (409), o si el canal está apagado en **Canales** (400).
- **La cola.** Las campañas y los recordatorios pasan por una cola que se guarda en `parla.db` (tabla
  `campaign_recipients`). Un hilo en segundo plano la revisa cada segundo, respetando el ritmo y el horario de
  silencio de cada campaña. Lo que queda en la cola sigue después de reiniciar.

## La API de salida

`POST /api/v1/bots/{bot}/outbound`

**Autenticación:** una clave de API (`Authorization: Bearer parla_…`) o la cookie de sesión de un usuario con rol
`owner` o `editor`. Sin ninguna de las dos: 401; `analyst` y `agent` (atención) reciben 403. Nunca es pública,
aunque el widget esté prendido. Mientras no haya usuarios, está abierta como el resto de la API (ver
[api_es.md](api_es.md#autenticación-y-roles)).

**Cuerpo:**

| Campo | Qué es |
|---|---|
| `channel` | `whatsapp` (por defecto), `telegram`, `phone` o `web`. |
| `to` | WhatsApp y teléfono: el número con código de país (`+5491112345678`; se sacan espacios, guiones, puntos, paréntesis y `+`; de 6 a 15 dígitos). Telegram: el chat id (un número). Web: el `sessionId` de una conversación del widget que ya existe. |
| `data` | Objeto opcional: valores para los slots (`{"nombre": "Ana", "fecha": "2026-12-01"}`). También son los valores de los huecos de la plantilla. |
| `flow` | Opcional: el nombre del flujo que corre (tiene que existir en Producción). |
| `template` | Solo WhatsApp, opcional: el nombre de una plantilla del catálogo (`"recordatorio_turno"`) o un objeto `{"name", "language"?, "params"?, "components"?}`. Ver [WhatsApp](#whatsapp-la-ventana-de-24-horas-y-las-plantillas). |

```sh
curl -s http://127.0.0.1:8000/api/v1/bots/clinica/outbound \
  -H 'Authorization: Bearer parla_xxxxxxxx' \
  -H 'Content-Type: application/json' \
  -d '{"channel": "whatsapp", "to": "+54 9 11 1234-5678",
       "template": "recordatorio_turno", "flow": "Confirmar turno",
       "data": {"nombre": "Ana", "fecha": "2026-12-01 10:00"}}'
```
```json
{"sessionId": "wa-5491112345678", "via": "template", "messages": [], "message_id": "wamid.HBgN…",
 "id": 17, "channel": "whatsapp", "to": "5491112345678", "status": "sent"}
```

| Campo | Qué es |
|---|---|
| `id` | La fila del envío en la cola. |
| `sessionId` | La conversación (`wa-…`, `tg-…`, `call-…` o la del widget). Se lee con `GET /api/v1/bots/{bot}/sessions/{sessionId}`. |
| `via` | `message` (los mensajes del flujo salieron como mensajes normales), `template` (se mandó una plantilla de WhatsApp; el flujo corre cuando la persona contesta) o `call` (se hizo una llamada). |
| `messages` | Lo que dijo el bot (texto), con `via: "message"`. Vacío en plantillas y llamadas. |
| `message_id` | El id del canal: el `wamid` de WhatsApp (del último mensaje), el `message_id` de Telegram o el SID de la llamada. `null` en la web. |
| `channel`, `to` | El canal y el destinatario normalizado. |
| `status` | `sent`: el canal lo aceptó. La entrega viene después (ver [estados de entrega](#estados-de-entrega)). |

**Errores** (`{"error": "…"}`, en el idioma de `Accept-Language`):

| Estado | Cuándo |
|---|---|
| 400 | `to` mal escrito, `data` que no es un objeto, un `flow` que no existe, el canal apagado, un chat de Telegram que nunca escribió, ninguna conversación web con ese id, una plantilla sin los datos para sus huecos, una clave o configuración que falta (`WHATSAPP_TOKEN`, `phone_number_id`, `channels.phone.from`, las claves de Twilio o jambonz, una dirección pública `https://`), o nada para mandar. |
| 401, 403 | Sin clave ni sesión; el rol no puede mandar (analista, atención). |
| 409 | WhatsApp fuera de la ventana de 24 horas (o alguien que nunca escribió) sin `template`; la persona se dio de baja; alguien del equipo está atendiendo la conversación. |
| 429 | Más de `api_per_minute` envíos en el último minuto para este agente (30 por defecto, `agent.outbound.api_per_minute`). Para muchas personas, usá una campaña. |
| 502 | El canal lo rechazó o no contestó (Meta, Telegram, Twilio, jambonz). El mensaje lo explica cuando el código de error es conocido (ver [Errores de Meta](#errores-de-meta)). |

Los envíos por la API no se reintentan: si falla, tu sistema decide si vuelve a probar.

## WhatsApp: la ventana de 24 horas y las plantillas

WhatsApp solo deja mandar mensajes libres dentro de las **24 horas desde el último mensaje de la persona** (la
*ventana de atención*). Fuera de esa ventana, o a alguien que nunca escribió, lo único que se puede mandar es una
**plantilla** aprobada por Meta.

Parla anota la hora del último mensaje de la persona en cada conversación y **elige solo**:

- **Dentro de la ventana** y con un `flow` (o el texto de un recordatorio): los mensajes del flujo salen como
  mensajes normales (`via: "message"`). La plantilla, si hay, no se usa.
- **Fuera de la ventana**, o sin `flow`: se manda la `template` (`via: "template"`). Si hay `flow`, corre **cuando
  la persona contesta** la plantilla (cualquier respuesta, también tocar un botón de respuesta rápida). Sin
  plantilla: 409.

### El catálogo de plantillas

Las plantillas se crean y se aprueban en Meta (*WhatsApp Manager → Plantillas de mensajes*), no en Parla. En Parla
solo se nombran, en **Canales → WhatsApp → Plantillas aprobadas** (`channels.whatsapp.templates` en el JSON del
agente):

```json
"channels": {"whatsapp": {"enabled": true, "phone_number_id": "1234567890",
  "templates": [{"name": "recordatorio_turno", "language": "es_AR", "params": ["nombre", "fecha"]}]}}
```

| Campo | Qué es |
|---|---|
| `name` | El nombre exacto en Meta: minúsculas, números y `_`. |
| `language` | El código de idioma de la plantilla en Meta (`es`, `es_AR`, `en_US`, `pt_BR`…). Sin él: `es`, `en_US` o `pt_BR` según el primer idioma del bot. |
| `params` | Los slots que completan los huecos del cuerpo, en orden: el primero va a `{{1}}`, el segundo a `{{2}}`… |

Si el cuerpo de `recordatorio_turno` es «Hola {{1}}, te recordamos tu turno del {{2}}. ¿Confirmás?», mandar con
`data: {"nombre": "Ana", "fecha": "1/12 a las 10"}` lo completa. Un dato que falta es un 400 antes de mandar nada.
Los valores se cortan en 1024 caracteres.

En la API, `template` puede pisar el catálogo: `{"name": "recordatorio_turno", "language": "es", "params":
["nombre"]}`, o traer los `components` crudos de la Cloud API (para variables del encabezado, botones con
parámetros o archivos), que se mandan tal cual en lugar de `params`.

### Errores de Meta

Cuando Meta contesta con un error, Parla traduce los códigos conocidos y decide si reintenta:

| Código | Qué significa | Se reintenta |
|---|---|---|
| 131047 | Pasaron más de 24 horas desde el último mensaje de la persona: solo se puede mandar una plantilla. | No |
| 131026 | No se pudo entregar el mensaje (¿ese número tiene WhatsApp?). | No |
| 131050 | La persona pidió no recibir mensajes de marketing de esta empresa en WhatsApp. | No |
| 132000 | La cantidad de datos no coincide con los huecos de la plantilla: revisá `params`. | No |
| 132001 | La plantilla no existe en ese idioma o todavía no está aprobada. | No |
| 132005 | El texto de la plantilla con los datos quedó demasiado largo. | No |
| 132007 | La plantilla no cumple las políticas de WhatsApp. | No |
| 132012 | Un dato no tiene el formato que pide la plantilla. | No |
| 132015 | La plantilla está pausada por baja calidad. | No |
| 132016 | La plantilla está desactivada. | No |
| otro 132xxx | WhatsApp rechazó la plantilla. | No |
| 4, 80007, 130429, 131048, 131056 | Límites de envío: hay que ir más despacio. | Sí |
| sin respuesta, 429, 5xx | Problemas de red o de Meta. | Sí |

Los reintentos son para campañas y recordatorios (ver [reintentos](#reintentos-y-reinicios)). El error se ve en la
fila del destinatario, en **Canales → Último error** y en la consola (con los números tapados).

### Estados de entrega

Meta avisa qué pasó con cada mensaje (`sent`, `delivered`, `read`, `failed`) por el mismo webhook. Parla usa esos
estados para actualizar a cada destinatario: un `delivered` que llega tarde nunca pisa un `read`, y `failed` trae
el motivo (los códigos de arriba). **En Meta, el webhook tiene que estar suscripto al campo `messages`** (el mismo
que se usa para recibir mensajes; los estados vienen con él). Si no, los destinatarios quedan en `sent` hasta que
contestan.

Cuando un envío son varios mensajes (un flujo que dice tres cosas), solo se sigue el estado del último.

### API de estado de los envíos

`POST /outbound` devuelve `id`. `GET /api/v1/bots/{bot}/outbound/{id}` da
`{id, kind, channel, to, status, error, attempts, sessionId, message_id, campaign, created, sent_at, updated}`
(`status`: `sent`, `delivered`, `read`, `replied`, `failed`…, `error` con el motivo). `GET …/outbound` lista los envíos
(API, campañas y recordatorios), el más nuevo primero, con `?to=&status=&from=&to_date=` (`AAAA-MM-DD`) y `kind`,
`channel`, `limit` (≤ 500). Analista o más, o una clave `integration`; atención (agent) no. `updated` es la hora del
último cambio de estado (no hay fechas separadas de entregado/leído).

### Plantillas desde la Bandeja y el contact center

Fuera de las 24 horas, una respuesta de la Bandeja o `POST …/sessions/{sid}/messages` no manda texto libre (Meta lo
rechazaría con 131047). Contesta `409` con `"code": "template_required"` y `templates` (el catálogo). La Bandeja
muestra entonces un selector de plantilla con sus `params` completados con los slots de la conversación; la API
recibe `"template": {"name", "language"?, "params"?}`, donde `params` es la lista de valores para `{{1}}`, `{{2}}`…
(si no viene, salen de los slots que nombra el catálogo). Una plantilla que no existe → `400` `template_invalid`.
Queda como mensaje `human` `[nombre: valores]` con `template`. Cuando el cliente contesta, la ventana se abre y se
vuelve a escribir texto libre. `GET …/sessions/{sid}` trae `whatsapp_window: {open, templates?}`.

## Telegram

Telegram solo deja que un bot le escriba a quien **empezó un chat con él** (y no lo bloqueó). `to` es el chat id, el
número de `tg-<chat_id>`: lo encontrás en **Conversaciones**, o en tu sistema si lo guardaste. Escribirle a un chat
que nunca le habló al bot se rechaza antes de llamar a Telegram (400); alguien que bloqueó al bot da un error que no
se reintenta.

No hay ventana ni plantillas: el flujo corre y sus mensajes salen enseguida. Telegram no avisa entregas ni
lecturas, así que un destinatario de Telegram pasa de `sent` a `replied` (o queda en `sent`).

## Teléfono: llamadas salientes

Con `channel: "phone"`, Parla le pide a tu proveedor que **haga una llamada**. Cuando la persona atiende, la llamada
funciona como una entrante: el proveedor llama al webhook de siempre de Parla, y el bot corre el `flow` (o
`__start__`) con los datos precargados. Si el bot tiene un slot que se llama `caller`, recibe el número al que se
llamó (la persona), como el número de quien llama en una llamada entrante.

Configuración, en **Canales → Teléfono**, además de lo que piden las llamadas entrantes
([channels_es.md](channels_es.md#llamadas-telefónicas-twilio-y-jambonz)):

| Dato | Dónde | Qué es |
|---|---|---|
| **Número desde el que se llama** | `channels.phone.from` | Tu número en el proveedor (`+5491112345678`) o una URI SIP. |
| Dirección pública | `PARLA_PUBLIC_URL` o **Dirección pública** | Tiene que empezar con `https://`: el proveedor la necesita para volver a llamar a Parla. |
| Claves de Twilio | **Claves** | `TWILIO_ACCOUNT_SID` (`AC…`) y `TWILIO_AUTH_TOKEN`. |
| Claves de jambonz | **Claves** | `JAMBONZ_API_KEY` (una clave de API de la cuenta) y `JAMBONZ_ACCOUNT_SID`. |
| **Dirección de la API de jambonz** | `channels.phone.api_url` | Por defecto `https://api.jambonz.cloud`; la de tu servidor si es propio. |
| **Application SID** | `channels.phone.application_sid` | La aplicación de jambonz que atiende la llamada. Recomendado: sin ella, jambonz pide en el pedido los datos del proveedor de voz, que Parla no manda. |

Qué manda Parla:

- **Twilio:** `POST https://api.twilio.com/2010-04-01/Accounts/{TWILIO_ACCOUNT_SID}/Calls.json` con Basic auth
  (`TWILIO_ACCOUNT_SID:TWILIO_AUTH_TOKEN`), `To`, `From`, `Url` (el webhook `…/phone/twilio`) y `StatusCallback`
  (el webhook `…/phone/twilio/status`, eventos `initiated`, `ringing`, `answered`, `completed`).
- **jambonz:** `POST {api_url}/v1/Accounts/{JAMBONZ_ACCOUNT_SID}/Calls` con `Authorization: Bearer
  {JAMBONZ_API_KEY}`, `from`, `to`, `call_hook` y `call_status_hook` (los webhooks `…/phone/jambonz`, con
  `JAMBONZ_BASIC_USER` / `JAMBONZ_BASIC_PASSWORD` si están cargadas) y `application_sid` si está puesto.

Las dos URLs de webhook llevan `?o=<token>`: un token al azar que le dice a Parla de qué envío se trata (datos,
flujo, campaña). La firma del proveedor cubre la URL entera, token incluido. Cuando la persona atiende, el
destinatario pasa a `delivered`; `busy`, `no-answer`, `failed` o `canceled` lo dejan en `failed` («no atendió»).
Una llamada que no se atendió no se reintenta.

Parla no detecta contestadores: si atiende el buzón de voz, el bot le habla a él. Que el primer mensaje sea corto y
diga quién llama.

## Widget web

Con `channel: "web"`, `to` es el `sessionId` de una conversación que ya existe en el widget (canal `web`). Los
mensajes del flujo se suman a esa conversación; el widget los muestra en su próxima consulta
(`GET …/sessions/{sessionId}/messages?after=`), como una respuesta de la Bandeja. No hay push: si la página está
cerrada, los mensajes esperan en la conversación. Sirve para «tu pedido está listo» mientras la persona todavía
tiene la página abierta.

## Campañas

Una **campaña** manda lo mismo a una lista de personas, a un ritmo controlado. En la interfaz: **Operar →
Campañas**, pestañas **Campañas** y **Bajas**. **Nueva campaña** te lleva por:

1. **Nombre y canal**: WhatsApp, Telegram o teléfono (las campañas no usan el widget web).
2. **Qué se manda**: en WhatsApp una **Plantilla aprobada** y, si querés, un **Flujo cuando responde (opcional)**;
   en Telegram y teléfono, el flujo que corre con cada persona.
3. **A quién**: una **Planilla CSV**. La primera fila es el encabezado.
4. **Cuándo y a qué ritmo**: ya o en una fecha y hora, la zona horaria, el ritmo y el horario de silencio.
5. **Qué cuenta como éxito (opcional)**: lo que convierte una conversación en una conversión.

En WhatsApp la plantilla es obligatoria (la API rechaza una campaña de WhatsApp sin plantilla), y el flujo tiene
que existir en lo publicado en Producción, que es lo que corre.

Se crea en **borrador**: ves cuántas personas quedaron cargadas, repetidas, inválidas o dadas de baja, y después
tocás **Iniciar**.

### El CSV

```csv
telefono;nombre;fecha
+5491112345678;Ana;1/12 a las 10
+5491187654321;Tomás;1/12 a las 11:30
```

- Coma o punto y coma (el que más aparezca en el encabezado), UTF-8 (con o sin BOM).
- Cada columna se usa como **destinatario** (`to`), como un **slot** del bot (su valor se precarga y completa la
  plantilla), o se ignora. Parla adivina: una columna que se llama `to`, `phone`, `telefono`, `teléfono`, `numero`,
  `número`, `celular`, `whatsapp`, `chat_id`, `chat` o `destinatario` es el destinatario, y una columna que se
  llama como un slot (sin importar mayúsculas) va a ese slot. Lo podés cambiar; tiene que haber exactamente una
  columna de destinatario.
- Números con código de país (`+5491112345678`); en Telegram, chat ids.
- Los destinatarios repetidos se cargan una vez (`duplicates`), las filas con un destinatario que no sirve se
  saltean (`invalid`), y las personas dadas de baja también (`opted_out`).
- Como máximo **10.000 destinatarios** por campaña. Se cambia por agente con `agent.outbound.max_recipients` o para
  el servidor con `PARLA_CAMPAIGN_MAX`. Una carga que se pasa del límite se rechaza entera.
- Podés sumar más personas a una campaña que no terminó (`POST …/recipients`).

### Inicio, ritmo y horario de silencio

- **Inicio:** ya, o `schedule.at` (`2026-12-01T10:00`) en `schedule.timezone` (una zona IANA como
  `America/Argentina/Buenos_Aires`; por defecto `UTC`, la interfaz propone la del navegador). Hasta entonces la
  campaña está en marcha pero **esperando** (`waiting: "schedule"`).
- **Ritmo:** `rate: {"count": 20, "per": "minute"}` por defecto; de 1 por minuto a 50 por segundo (3.000 por
  minuto). Ir despacio cuida la reputación del número: WhatsApp baja la calificación de calidad (y los límites) de
  los números que la gente bloquea o denuncia, y las operadoras marcan los números que llaman demasiado rápido.
- **Horario de silencio:** `quiet_hours: {"start": "21:00", "end": "09:00"}`, en la zona horaria de la campaña.
  Un rango que cruza la medianoche funciona. En horario de silencio no sale nada (`waiting: "quiet_hours"`) y sigue
  cuando termina. La interfaz lo prende de 21:00 a 09:00 por defecto; la API no pone ninguno si no se lo pedís.

### Estados

| Campaña | Qué significa |
|---|---|
| `draft` | Creada, sin iniciar. Se puede cambiar, sumar personas y borrar. |
| `running` | Enviando. `waiting` dice si espera la hora de inicio (`schedule`) o que termine el horario de silencio (`quiet_hours`). |
| `paused` | Frenada; no sale nada hasta **Seguir**. Se puede cambiar. |
| `done` | No queda nada en la cola. |
| `canceled` | Cancelada: a quien todavía no se le mandó no se le manda. No se puede retomar. |

Acciones: **Iniciar** (`draft` → `running`; necesita destinatarios y el canal prendido), **Pausar** (`running` →
`paused`), **Seguir** (`paused` → `running`), **Cancelar campaña** (desde `draft`, `running` o `paused`). Cambiarla
(`PUT`) solo se puede en `draft` o `paused`, y el canal no cambia. Para borrarla no tiene que estar en `running`;
se borran también los destinatarios y sus resultados.

| Destinatario | Qué significa |
|---|---|
| `queued` | Esperando su turno (o un reintento). |
| `sending` | Saliendo en este momento. |
| `sent` | El canal lo aceptó. |
| `delivered` | Llegó al teléfono (WhatsApp), o se atendió la llamada. |
| `read` | La persona lo leyó (WhatsApp, si tiene las confirmaciones de lectura prendidas). |
| `replied` | La persona contestó. |
| `failed` | No se pudo mandar; `error` dice por qué. |
| `opted_out` | La persona estaba dada de baja, o se dio de baja mientras esperaba en la cola. |
| `canceled` | La campaña se canceló antes de mandarle. |

### Reintentos y reinicios

- Un envío que falla por algo que puede pasar (sin conexión, 429, 5xx, los límites de envío de WhatsApp) se
  reintenta hasta **3 intentos** en total, esperando 30 segundos y después 60. Los errores que no van a cambiar (una
  plantilla mal, un número sin WhatsApp, una baja) fallan enseguida.
- Todo se guarda en `parla.db`, así que un reinicio sigue donde quedó: las filas en cola, los horarios y los
  recordatorios continúan.
- Una fila que estaba **saliendo** cuando se cortó el proceso queda en `failed` («se cortó por un reinicio») en vez
  de mandarse de nuevo: Parla no puede saber si salió, y un mensaje repetido es peor que uno que no llegó. Exportá
  los resultados para reintentar esos a mano.

### Resultados y conversiones

La campaña muestra cuántos se enviaron, entregaron, leyeron, respondieron, fallaron y se dieron de baja, con
refresco cada 3 segundos mientras está en marcha, y la lista de destinatarios con filtro por estado y **Ver
conversación**. **Exportar CSV** baja `to, status, error, attempts, sent_at, updated, sessionId` más los datos de
cada persona.

Las **Conversiones** cuentan las conversaciones de la campaña que llegaron a una meta (`conversion`, opcional; con
varios campos, cuenta cualquiera):

| Campo | Cuenta cuando |
|---|---|
| `classification` | La conversación tiene esa clasificación (un paso `classify`). |
| `intent` | La persona dijo algo con esa intención. |
| `flow` | La persona escribió mientras corría ese flujo. |
| `csat` | La nota de satisfacción fue al menos esa (1 a 5). |

Cada conversación que empieza una campaña queda marcada con el id de la campaña (`campaign` en la conversación, y
en cada recordatorio que programe). **Reportes** tiene un filtro por campaña, y la API acepta `?campaign=<id>` en
`GET /api/v1/bots/{bot}/sessions` y `/report`, y en las rutas de analítica.

### Rutas de administración

La interfaz usa estas rutas internas (`{id}` es el id del agente, `{c}` el id de 12 caracteres de la campaña).
Dueño y editor pueden usarlas todas; el analista solo los `GET`; atención ninguna. Más en
[api_es.md](api_es.md#campañas-y-bajas).

| Ruta | Cuerpo | Respuesta |
|---|---|---|
| `GET /api/agents/{id}/campaigns` | — | `{"campaigns": [campaña]}`, la más nueva primero. |
| `POST /api/agents/{id}/campaigns` | `{"name", "channel", "flow"?, "template"?, "schedule"?: {"at", "timezone"}, "rate"?: {"count", "per"}, "quiet_hours"?: {"start", "end"}, "conversion"?, "csv"?, "mapping"?, "recipients"?}` | La campaña (en `draft`) más `imported: {"added", "duplicates", "invalid", "opted_out"}`. |
| `POST /api/agents/{id}/campaigns/preview` | `{"csv"}` | `{"columns", "rows"` (las primeras 5), `"count", "mapping"` (lo que adivinó)`}`. No guarda nada. |
| `GET /api/agents/{id}/campaigns/{c}` | — | La campaña. |
| `PUT /api/agents/{id}/campaigns/{c}` | Los mismos campos que al crear (lo que no mandás queda como estaba) | La campaña. Solo en `draft` o `paused` (si no, 409). |
| `DELETE /api/agents/{id}/campaigns/{c}` | — | `{"deleted"}`. No mientras está en `running` (409). |
| `GET /api/agents/{id}/campaigns/{c}/recipients?status=&limit=&offset=` | — | `{"total", "recipients": [{"id", "to", "data", "status", "error", "attempts", "updated", "sent_at", "sessionId"}]}`. `limit` de 1 a 500, 50 por defecto. |
| `POST /api/agents/{id}/campaigns/{c}/recipients` | `{"csv", "mapping"?}` o `{"recipients": ["+549…", {"to", slot: valor}]}` | La campaña más `imported`. No en `done` ni `canceled` (409). |
| `POST /api/agents/{id}/campaigns/{c}/start\|pause\|resume\|cancel` | — | La campaña. 409 si su estado no lo permite. |
| `GET /api/agents/{id}/campaigns/{c}/export` | — | El CSV (`text/csv`, como archivo adjunto). |
| `GET /api/agents/{id}/optouts` | — | `{"optouts": [{"address", "channel", "keyword", "at"}]}` |
| `POST /api/agents/{id}/optouts` | `{"address", "channel"?}` | Agrega una baja a mano; devuelve la lista. |
| `DELETE /api/agents/{id}/optouts` | `{"address"}` | La saca; devuelve la lista. |

Una campaña (`campaña` arriba) es `{"id", "name", "channel", "status", "waiting", "created", "updated",
"created_by", "flow", "template", "schedule", "rate", "quiet_hours", "conversion", "stats"}`; `stats` tiene la
cantidad por estado de destinatario más `total` y `conversions`.

```sh
curl -s http://127.0.0.1:8000/api/agents/654a0008/campaigns \
  -H 'Authorization: Bearer parla_xxxxxxxx' -H 'Content-Type: application/json' \
  -d '{"name": "Turnos de diciembre", "channel": "whatsapp", "template": "recordatorio_turno",
       "flow": "Confirmar turno", "schedule": {"at": "2026-12-01T10:00", "timezone": "America/Argentina/Buenos_Aires"},
       "rate": {"count": 30, "per": "minute"}, "quiet_hours": {"start": "21:00", "end": "09:00"},
       "conversion": {"classification": "Turno confirmado"},
       "csv": "telefono,nombre,fecha\n+5491112345678,Ana,1/12 a las 10\n"}'
curl -s -X POST http://127.0.0.1:8000/api/agents/654a0008/campaigns/3f2a9c0d1e4b/start \
  -H 'Authorization: Bearer parla_xxxxxxxx'
```

## Recordatorios: el paso `remind`

Un flujo puede programar un mensaje para más tarde a la misma persona. En el editor de flujos es **Programar un
recordatorio**.

```json
{"type": "remind", "after": "24h", "flow": "Recordatorio", "template": "recordatorio_turno"}
{"type": "remind", "at": "{{ fecha }} 09:00", "text": "Hola {{ nombre }}, te esperamos hoy a las {{ hora }}."}
```

| Campo | Qué es |
|---|---|
| `after` | Cuánto después de ahora: un número y `m`, `h` o `d` (`30m`, `24h`, `2d`). |
| `at` | Una fecha y hora, con plantillas, que quede como `AAAA-MM-DD HH:MM` (`"{{ fecha }} 09:00"`). En `agent.outbound.timezone` (por ejemplo `America/Argentina/Buenos_Aires`), o en la zona horaria del servidor si no está. Va uno de los dos: `after` o `at`. |
| `flow` | El flujo que corre el recordatorio. |
| `text` | Un mensaje en vez de un flujo (con plantillas y `translations`). Hace falta `flow` o `text`. |
| `template` | WhatsApp: la plantilla del catálogo que se usa si el recordatorio sale más de 24 horas después del último mensaje de la persona. |

- Va a la **misma persona por el mismo canal**: WhatsApp, Telegram o el widget web. En una llamada, vuelve a llamar
  al número del slot `caller` (así que el bot necesita un slot que se llame `caller`).
- Cuando sale, la conversación empieza de nuevo con los **slots que tenía cuando se programó** precargados, y corre
  `flow` (o manda `text`). Vale la regla de la ventana de WhatsApp: dentro de las 24 horas sale como mensaje
  normal; después necesita `template`, o falla. `validate_agent` avisa de un recordatorio sin plantilla cuando
  WhatsApp está prendido.
- Si la hora ya pasó, no se programa nada (la traza lo dice). No se manda desde el **chat de prueba** ni desde
  conversaciones de la API (`channel: "api"`): el historial muestra «no se envía desde este canal».
- El historial muestra «Recordatorio programado para …». Los recordatorios esperan en la cola de `parla.db`,
  siguen después de reiniciar, tienen los reintentos de arriba, respetan las bajas y conservan la marca de la
  campaña si la conversación vino de una.
- Programá un recordatorio por cosa (uno por turno, no uno en cada mensaje).

## Bajas

Cuando alguien contesta con una palabra de baja, Parla la anota, contesta con una confirmación y el bot no corre
con ese mensaje. Desde ahí, ningún envío de la API, campaña ni recordatorio le llega a esa persona en ese bot; sus
filas en la cola pasan a `opted_out`.

- **Palabras de fábrica:** en castellano `stop`, `baja`, `no me escriban`, `no me escribas`, `desuscribir`; en
  inglés `stop`, `unsubscribe`, `opt out`; en portugués `parar`, `sair`, `descadastrar`. Se revisan todos los
  idiomas, sea cual sea el de la conversación.
- **Cómo se reconocen:** no importan mayúsculas, tildes ni signos. Una **palabra sola** tiene que ser todo el
  mensaje («STOP», «baja.»), así que «no quiero darme de baja del plan» no da de baja. Una **frase** cuenta en
  cualquier parte del mensaje («por favor no me escriban más»).
- **Tus propias palabras:** `agent.outbound.optout_keywords`, por ejemplo `{"es": ["baja", "no molestar"]}`; cada
  idioma que pongas reemplaza las de fábrica de ese idioma (una lista vacía apaga ese idioma). En la interfaz:
  **Campañas → Bajas → Palabras de baja** (vacío usa las de siempre).
- **Confirmación:** «Listo, no te vamos a escribir más. Si cambiás de idea, escribinos cuando quieras.» (o la
  versión en inglés o portugués, según el idioma de la conversación). La persona puede seguir escribiéndole al bot;
  lo único que se corta es lo saliente.
- **A mano:** **Bajas → Agregar a mano** (un número o chat id), y el tachito saca una. Sacá una baja solo si la
  persona lo pidió.
- Las palabras funcionan en WhatsApp, Telegram y el widget web. En las llamadas no hay palabra: agregá el número a
  mano cuando alguien pide que no lo llamen.
- Las personas dadas de baja se saltean al cargar una campaña, y la API contesta 409.

## Límites de envío

| Qué | Límite |
|---|---|
| API de salida | `agent.outbound.api_per_minute` envíos por minuto por agente (30 por defecto); 429 si se pasa. |
| Ritmo de una campaña | `rate`, de 1 por minuto a 50 por segundo; 20 por minuto por defecto. Hasta un segundo de ráfaga. |
| Destinatarios por campaña | 10.000 (`agent.outbound.max_recipients` o `PARLA_CAMPAIGN_MAX`). |
| Reintentos | 3 intentos, con 30 s y 60 s de espera (campañas y recordatorios). |

Meta y los proveedores de telefonía tienen sus propios límites (niveles de mensajería, llamadas por segundo):
quedate por debajo.

## Seguridad y privacidad

- **Roles:** `owner` y `editor` mandan (API, campañas, bajas); `analyst` ve campañas, resultados, bajas y la
  exportación, solo lectura; `agent` (atención) no ve nada de esto. Los usuarios limitados a algunos bots solo ven
  las campañas de esos bots.
- **Auditoría:** `outbound.send` (canal y número tapado), `campaign.create` (con cuántos se cargaron),
  `campaign.update`, `campaign.delete`, `campaign.recipients`, `campaign.start`, `campaign.pause`,
  `campaign.resume`, `campaign.cancel`, `optout.add` y `optout.remove` (número tapado). Ver
  [security_es.md](security_es.md#registro-de-auditoría).
- **Números tapados:** en la auditoría y en la consola los números van tapados (`549••••••5678`). La interfaz y la
  API de administración los muestran enteros a quien puede ver el bot.
- **Retención:** con `retention_days` (o `PARLA_RETENTION_DAYS`), los destinatarios (números y datos) de las
  campañas que terminaron o se cancelaron hace más de esos días se borran, y la campaña conserva sus totales.
  También se borran las filas viejas de envíos por la API y de recordatorios. Las conversaciones siguen su propia
  retención.
- **`pii_redaction`:** después de mandar una fila (de campaña, recordatorio o envío por la API), sus datos se tapan con las
  categorías del agente. El historial de la conversación se tapa como cualquier otro.
- Borrar el agente borra sus campañas, su cola y sus bajas.
- Las llamadas salientes se reconocen por un token al azar en la URL del webhook, que cubre la firma del proveedor.

## Consentimiento y leyes

Esto es informativo, no asesoramiento legal. Las reglas dependen del país y del canal; consultá con alguien que
conozca las tuyas.

- **Consentimiento (opt-in).** Escribile solo a quien aceptó recibir mensajes tuyos por ese canal, y guardá
  constancia de cuándo y cómo. La [Política de mensajería de WhatsApp Business](https://business.whatsapp.com/policy)
  lo exige, y también las leyes de privacidad como el GDPR (Europa), la LGPD (Brasil) y la Ley 25.326 de Protección
  de Datos Personales de Argentina.
- **Plantillas de WhatsApp.** Meta clasifica las plantillas como *marketing*, *utilidad* o *autenticación*, con
  precios y reglas distintas; la persona puede limitar o bloquear los mensajes de marketing (error 131050). Usá
  plantillas de utilidad para recordatorios y avisos, y dejá el marketing para quien aceptó recibirlo.
- **Llamadas.** Las llamadas automáticas y grabadas están reguladas en muchos lugares (por ejemplo la TCPA en
  Estados Unidos) y muchos países tienen registros de *no llamar* (en Argentina, el Registro Nacional «No Llame»).
  Cruzá tu lista con ellos antes de una campaña telefónica.
- **Horario de silencio.** No escribas ni llames de noche ni en los horarios que prohíbe la ley. Usá
  `quiet_hours` y la zona horaria correcta.
- **Decí quién sos** en el primer mensaje o en la primera frase de la llamada, y por qué escribís.
- **Que sea fácil irse.** Mencioná la palabra de baja («Respondé BAJA si no querés recibir más mensajes») y
  respetala. La segunda parte la hace Parla solo.

## Probarlo

**Sin cuentas reales:** `tests/test_outbound.py` corre todo contra servidores falsos en un puerto local: WhatsApp
(`PARLA_WHATSAPP_API`), Telegram (`PARLA_TELEGRAM_API`), Twilio (`PARLA_TWILIO_API`, por defecto
`https://api.twilio.com`) y jambonz (`channels.phone.api_url`). Cambiá esas variables solo para pruebas.

**Con cuentas reales:**

- **WhatsApp:** el canal andando ([channels_es.md](channels_es.md#whatsapp-cloud-api)), el webhook suscripto a
  `messages`, y al menos una plantilla aprobada en Meta y cargada en **Plantillas aprobadas**. Con el número de
  prueba de Meta solo le podés escribir a los destinatarios que agregaste en *API Setup*; la plantilla
  `hello_world` ya viene aprobada (`"language": "en_US"`, sin params).
- **Telegram:** el canal conectado, y el chat id de alguien que ya le escribió al bot.
- **Teléfono:** el canal andando, una dirección pública `https://`, **Número desde el que se llama**, y las claves
  de Twilio (`TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`) o de jambonz (`JAMBONZ_API_KEY`, `JAMBONZ_ACCOUNT_SID`,
  **Application SID**). Una cuenta de prueba de Twilio solo llama a números verificados y pasa un aviso antes.
- Empezá con una campaña de una persona: tu propio número.

## Límites

- **Un solo proceso.** La cola usa un lock global y el estado del ritmo (el de cada campaña, el contador por minuto
  de la API) vive en memoria: corré una sola réplica (ver [deployment_es.md](deployment_es.md)). Un reinicio pone
  en cero el contador por minuto.
- **No detecta contestadores** en las llamadas salientes.
- **Plantillas:** solo los huecos del cuerpo, con `params`; encabezados, botones con variables o archivos necesitan
  `components` crudos en la API (la interfaz y el catálogo no los editan).
- **Telegram** no avisa entregas ni lecturas.
- **El estado de entrega** sigue solo el último mensaje de un envío de varios mensajes.
- **Una zona horaria por campaña** (no por destinatario), y una por agente para los recordatorios.
- El estado de entrega de los envíos sueltos por la API se guarda, pero todavía ninguna ruta lo muestra: usá una
  campaña para seguir a cada destinatario.
- Una respuesta desde la **Bandeja** después de 24 horas en WhatsApp sigue fallando (error 131047): la Bandeja manda
  texto libre, no plantillas. Usá la API de salida con una plantilla.
