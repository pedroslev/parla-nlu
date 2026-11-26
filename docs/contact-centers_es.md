# Contact centers externos

[English](contact-centers.md) · **Español**

Para empresas que ya tienen su contact center (Genesys, Twilio Flex, Five9, Zendesk, Salesforce…) y no van a
atender desde la Bandeja de Parla. Parla sigue siendo el bot; cuando la charla pasa a una persona, le avisa al
contact center con un webhook firmado, se calla, y el contact center contesta, devuelve o cierra la conversación
por la API. Las llamadas se transfieren con el contexto en encabezados SIP (o como tarea de Flex).

> Las recetas de cada plataforma se basan en su documentación pública. No son conectores certificados: los menús y
> las APIs cambian, así que probalas en tu cuenta y edición. Los links están al final de cada receta.

## Configuración (Canales → Derivación)

| Campo | Qué hace |
| --- | --- |
| **Quién atiende** (`handoff.mode`) | `inbox` (la Bandeja de Parla, lo de siempre), `external` (el contact center externo: la Bandeja solo la muestra, de lectura, con «En el contact center externo»), `both` (ambos). |
| **Si nadie la acepta en** (`timeout_minutes`) | Minutos hasta que un handoff `external`/`both` que nadie aceptó vuelve al bot (`on_timeout: "bot"`) o se cierra (`"close"`). `0` = esperar siempre. |
| **Cola o destino** (`target`) | Texto libre que va en el webhook (`handoff.target`), para rutear del lado del CC. |
| **Mensajes que van en el contexto** (`last_messages`) | Cuántos mensajes recientes van en el webhook y el lookup (10 por defecto, hasta 50). |
| **Webhooks** (`webhooks`) | `[{url, events, secret_name}]`. `secret_name` es una clave de **Claves** con la que se firma. |
| **Contexto en la transferencia telefónica** (`handoff.phone`) | Encabezados SIP, slots como encabezado, User-to-User y el Workflow SID de Twilio Flex (ver [Teléfono](#teléfono-transferir-con-contexto)). |

Lo configura el dueño o un editor (cada cambio queda en la auditoría como `handoff.update`). Aplica enseguida, sin
publicar (como la retención).

```json
"handoff": {"mode": "external", "timeout_minutes": 15, "on_timeout": "bot", "target": "soporte",
            "phone": {"headers": ["session", "intent", "language", "summary", "context_url"], "slots": ["dni"], "uui": true}},
"webhooks": [{"url": "https://cc.midominio.com/parla", "events": ["handoff.requested", "handoff.released", "conversation.ended"],
              "secret_name": "CC_WEBHOOK_SECRET"}]
```

## El patrón

1. El bot deriva (paso `handoff` o «quiero hablar con una persona»). La charla queda en `handoff` con `mode`,
   `reason`, `target` y un `summary` de una o dos líneas (lo hace la IA del agente si está prendida; si no,
   intención + slots). El bot deja de contestar esa conversación.
2. Parla manda `handoff.requested` a tu webhook con el contexto (abajo).
3. El contact center crea la tarea / ticket / interacción con ese contexto.
4. Un agente la acepta: `POST …/handoff {"action": "accept", "agent_name": "Ana"}`.
5. Contesta: `POST …/messages {"text": "…"}` (Parla lo entrega por el canal de la conversación). Por teléfono, la
   llamada llega con encabezados SIP (`X-Parla-Session`…) y el agente abre el contexto con el lookup.
6. La devuelve al bot (`release`, opcionalmente con `data` para los slots y un `flow` para seguir) o la cierra
   (`close` con `resolution`). Parla manda `handoff.released` / `conversation.ended`.

Si nadie la acepta en `timeout_minutes`, Parla hace el `release`/`close` solo.

## Eventos del webhook

`handoff.requested`, `handoff.released`, `conversation.started`, `conversation.ended`, `message.user` y
`message.bot` (opcionales: uno por mensaje), `csat.received`, `campaign.finished`. «Enviar evento de prueba» manda
`test`. El cuerpo es el mismo que en la [versión en inglés](contact-centers.md#webhook-events):
`id`, `type`, `created`, `agent`, `sessionId`, `channel`, `customer` `{channel, address}`, `language`, `intent`,
`flow`, `slots`, `handoff` `{active, mode, reason, since, by, summary, target}`, `ended`, `messages` (los últimos
N) y `links` (`session`, `messages`, `handoff`, `lookup`).

Campos extra: `text` (`message.*`), `score` (`csat.received`), `released_by` (`handoff.released`), `resolution`
(`conversation.ended`), `campaign` (`campaign.finished`, sin los campos de la conversación). Con **datos
personales tapados** prendido, `customer.address` va enmascarado y `slots`, `messages` y `text` van tapados. El
`sessionId` de WhatsApp/Telegram (`wa-<teléfono>`, `tg-<chat>`) es como la API encuentra la conversación y no se
tapa. Los `links` usan la dirección pública (Canales → Dirección pública o `PARLA_PUBLIC_URL`).

### Entrega

- Encabezados: `Parla-Signature: t=<unix>,v1=<hex del HMAC-SHA256 de "t.cuerpo">`, `Parla-Event`, `Parla-Delivery`.
- Una cola en SQLite (`webhook_deliveries`) que sigue después de un reinicio. Cualquier respuesta que no sea 2xx
  (o sin respuesta en 10 s, o una redirección) se reintenta: 30 s, 1, 2, 4… minutos hasta 4 h entre intentos, 14
  intentos (~24 h) y después queda **dead**. Canales → Derivación → **Últimas entregas** muestra el estado y el
  código, con **Reintentar**.
- Orden: los eventos de una misma conversación a un mismo webhook salen de a uno y en orden (uno que falla frena los
  siguientes de esa conversación, no los de otras).
- Al menos una vez: un reinicio a mitad de camino lo manda de nuevo. **Deduplicá por `id`.**
- Las entregas hechas o dead se borran a los 30 días.

### Verificar la firma

Con el cuerpo crudo (antes de parsear el JSON), rechazando marcas de tiempo viejas y comparando en tiempo
constante. Ejemplos en Python y Node en la [versión en inglés](contact-centers.md#verifying-the-signature):

```python
expected = hmac.new(secret.encode(), t.encode() + b"." + raw_body, hashlib.sha256).hexdigest()
ok = hmac.compare_digest(expected, v1) and abs(time.time() - int(t)) < 300
```

## API para el contact center

Clave de API Bearer de un dueño o editor, o mejor una **clave de integración**: `POST /api/users/{nombre}/keys
{"label": "genesys", "scope": "integration"}`. Solo sirve para estas rutas (y leer la conversación); lo demás da
403. Respeta la lista de bots del usuario. La clave de un analista sigue siendo de solo lectura.

| Ruta | Cuerpo | Qué hace |
| --- | --- | --- |
| `POST /api/v1/bots/{bot}/sessions/{sid}/handoff` | `{"action": "accept", "agent_name"?}` | La toma un agente externo (`handoff.by`). Si no estaba en handoff, la pasa. |
| | `{"action": "release", "data"?: {slot: valor}, "flow"?: "nombre"}` | Vuelve al bot. `data` llena slots, `flow` corre (sus respuestas le llegan a la persona). |
| | `{"action": "close", "resolution"?}` | Termina la conversación (`conversation.ended` con `resolution`). |
| `POST /api/v1/bots/{bot}/sessions/{sid}/messages` | `{"text", "from_name"?}` | Se lo entrega a la persona por el canal de la conversación y queda como `human`. |
| `GET /api/v1/bots/{bot}/lookup?phone=…` \| `?chat=…` \| `?sid=…` | | La última conversación abierta de esa persona (primero las derivadas), con el mismo contexto que el webhook. 404 si no hay. |
| `GET /api/v1/bots/{bot}/sessions/{sid}[/messages?after=N]` | | La conversación (ya existía). |

Entrega de `messages`: widget web (enseguida por WebSocket/SSE), WhatsApp y Telegram (en el momento: `502` si el
proveedor lo rechaza). WhatsApp fuera de la ventana de 24 h → `409` (solo una plantilla aprobada, `POST /outbound`).
Una llamada → `409`. Canal `api` → solo queda guardado (tu cliente consulta `…/messages`). Conversación terminada →
`409`. Auditoría: `handoff.accept`, `handoff.release`, `handoff.close`, `handoff.message`.

## Teléfono: transferir con contexto

Al derivar, Parla transfiere a `channels.phone.handoff_to`:

- **URI SIP + Twilio**: `<Dial><Sip>sip:cola@pbx?X-Parla-Session=…&amp;X-Parla-Intent=…</Sip></Dial>`. Twilio
  acepta encabezados `X-` y `User-to-User` en el URI ([Twilio `<Sip>`](https://www.twilio.com/docs/voice/twiml/sip)).
- **Número + Twilio**: `<Dial><Number>+54…</Number></Dial>` (a la red telefónica no le llegan encabezados).
- **Twilio Flex**: con un Workflow SID, `<Enqueue workflowSid="WW…"><Task>{…}</Task></Enqueue>`; los atributos de la
  tarea llevan `parla_session`, `intent`, `language`, `summary`, `slots`, `context_url`, `customer`
  ([TaskRouter TwiML](https://www.twilio.com/docs/taskrouter/twiml-queue-calls)).
- **jambonz**: `dial` con `"headers": {"X-Parla-Session": …, "User-to-User": …}` ([jambonz dial](https://docs.jambonz.org/verbs/verbs/dial)).

Encabezados para elegir: `X-Parla-Session`, `X-Parla-Intent`, `X-Parla-Language`, `X-Parla-Summary`,
`X-Parla-Context` (la URL del lookup; el CC igual necesita su clave para llamarla), `X-Parla-Slot-<nombre>` para los
slots que pongas y `User-to-User` (el sessionId en hex, `;encoding=hex`). Solo ASCII, cada valor hasta 128
caracteres ya codificado y todos juntos menos de 1000 (el límite de Twilio es 1024); lo que no entra se descarta.
Nunca se manda nada de la bóveda. Por defecto: ningún encabezado.

## Recetas

### Genesys Cloud

1. Un relay chico (AWS Lambda / una función) recibe el webhook, verifica `Parla-Signature` y llama a la Platform API
   de Genesys para crear la interacción (Open Messaging o un callback).
2. Llamadas: transferí a un trunk SIP / BYOC de Genesys; en Architect leé `X-Parla-Session` o la UUI y usá una
   **Data Action** (servicios web) que llame a `GET …/lookup?sid=…` con la clave de integración, para mostrar el
   contexto en un script.
3. Al terminar: otra Data Action con `POST …/handoff {"action": "release"|"close"}`.

Docs: [Data Actions](https://help.mypurecloud.com/articles/about-the-data-actions-integrations/),
[Open Messaging](https://developer.genesys.cloud/commdigital/digital/openmessaging/).

### Twilio Flex

1. Teléfono: poné el Workflow SID en Derivación; la llamada entra a Flex con los atributos de la tarea.
2. Chat (WhatsApp/web por Parla): una Twilio Function recibe `handoff.requested`, verifica la firma y crea la tarea
   con la API de TaskRouter (`attributes` = el payload).
3. Un plugin de Flex muestra el contexto: con `task.attributes.parla_session` llama a `GET …/lookup?sid=…` (por tu
   backend: nunca pongas la clave en el navegador) y manda las respuestas del agente a `POST …/messages`. Al
   cerrar la tarea, `release` o `close`.

Docs: [TaskRouter tasks](https://www.twilio.com/docs/taskrouter/api/task), [Flex plugins](https://www.twilio.com/docs/flex/developer/plugins).

### Five9

1. Llamadas: transferí a Five9 por SIP con `X-Parla-Session` (o la UUI); en el script del IVR pasá el encabezado a
   una variable de la llamada y usá un módulo **Query** (servicio web) contra `…/lookup?sid=…`.
2. Chats: Five9 Digital Engagement puede crear interacciones por sus APIs desde un relay que recibe el webhook.
3. Devolver/cerrar con un conector o servicio web al disposicionar.

Docs: [Five9 documentation](https://documentation.five9.com/), [Five9 APIs](https://developer.five9.com/).

### Zendesk

1. `handoff.requested` → un relay (verifica la firma) que crea un ticket (`POST /api/v2/tickets`) con el resumen, los
   slots y los últimos mensajes, y guarda el `sessionId` en un campo personalizado.
2. Un **webhook + trigger** de Zendesk ante comentarios públicos del agente llama a tu relay, que manda
   `POST …/messages`.
3. Ticket resuelto → trigger → `POST …/handoff {"action": "close", "resolution": "solved"}`.

Docs: [Tickets API](https://developer.zendesk.com/api-reference/ticketing/tickets/tickets/),
[Webhooks](https://developer.zendesk.com/documentation/webhooks/).

### Salesforce Service Cloud

1. `handoff.requested` → relay → crear un Case (REST API) con el contexto y el `sessionId`; un flujo de
   **Omni-Channel** lo rutea a una cola.
2. Respuestas del agente: un Flow (disparado por el comentario del Case / Messaging) con un **HTTP Callout** (o Apex)
   a `POST …/messages` usando una Named Credential con la clave de integración.
3. Case cerrado → Flow → `POST …/handoff {"action": "close"}`.

Docs: [Omni-Channel developer guide](https://developer.salesforce.com/docs/atlas.en-us.omni_channel_dev.meta/omni_channel_dev/),
[Salesforce Help: Flow HTTP Callout](https://help.salesforce.com/) (buscá «HTTP Callout»).

## Límites

- Un solo hilo de entrega: un webhook lento (hasta 10 s) demora a los demás.
- El orden es por conversación y webhook; un evento dead no frena los siguientes.
- El resumen con IA suma hasta ~8 s al turno del handoff (si falla: intención + slots).
- La salida a internet sigue las mismas reglas que los pasos `http` (ver [security_es.md](security_es.md#webhooks-salientes)).
