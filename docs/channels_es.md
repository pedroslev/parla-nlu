# WhatsApp, Telegram y teléfono

[English](channels.md) · **Español**

Un bot puede atender por **WhatsApp** (la Cloud API de WhatsApp Business, de Meta) y por **Telegram**, además del
widget web y la API. Es el mismo bot y el mismo motor: contesta con lo publicado en **Producción** (o el borrador si
todavía no publicaste nada), con sus botones y archivos. Las conversaciones aparecen en **Conversaciones** con el
canal `whatsapp` o `telegram`, y cuando la charla pasa a una persona, lo que esa persona escribe en la **Bandeja**
también le llega al WhatsApp o Telegram del cliente. También puede atender **llamadas telefónicas** por Twilio o
jambonz: ver [Llamadas telefónicas](#llamadas-telefónicas-twilio-y-jambonz). Y puede **escribir primero** (la API de
salida, campañas y recordatorios, también llamadas salientes): ver [outbound_es.md](outbound_es.md).

Todo se configura en **Publicar → Canales**.

## Qué hace falta

- **Una dirección pública con HTTPS.** Meta y Telegram le hablan a Parla por internet, así que Parla tiene que
  estar publicado con un certificado válido: un servidor detrás de un proxy, un Ingress de Kubernetes o un túnel
  (Cloudflare Tunnel, ngrok, Tailscale Funnel) para probar. Ver [deployment_es.md](deployment_es.md).
- **Que el proxy publique las rutas de los webhooks.** Están bajo `/api/v1/`, que los proxies e Ingress de ejemplo
  de `deploy/` ya publican:
  - `GET` y `POST /api/v1/bots/{bot}/whatsapp`
  - `POST /api/v1/bots/{bot}/telegram`
  - `POST /api/v1/bots/{bot}/phone/twilio[/gather|/status]` o `…/phone/jambonz[/gather|/status]`, y
    `GET /api/v1/bots/{bot}/phone/audio/<token>.wav` (la voz de Parla en las llamadas)
- **Decirle a Parla su dirección pública**, de una de dos formas:
  - La variable de entorno `PARLA_PUBLIC_URL` (`https://bots.midominio.com`), para todo el servidor.
  - **Dirección pública** en **Canales**, por bot (`channels.public_url` en el JSON del agente). Gana sobre la variable.

  Sirve para mostrar la URL del webhook y para conectar Telegram. **No** hace falta sumar ese dominio a
  `PARLA_HOSTS`: los webhooks se aceptan desde cualquier `Host` (se autentican con firma, ver abajo).

## WhatsApp (Cloud API)

Necesitás una cuenta de Meta Business y un número que no esté registrado en la app de WhatsApp (Meta también te da
un número de prueba).

1. **Creá la app.** En [developers.facebook.com](https://developers.facebook.com/apps) → *Crear app* → tipo
   *Negocios*. Sumale el producto **WhatsApp**.
2. **Identificador del número.** En *WhatsApp → Configuración de la API*, elegí el número (o el de prueba) y copiá
   el **Identificador del número de teléfono** (*Phone number ID*, un número largo; no es el teléfono). En Parla:
   **Canales → WhatsApp → Identificador del número**.
3. **Token permanente.** El token que aparece en *Configuración de la API* dura 24 horas: sirve solo para una
   primera prueba. Para usarlo de verdad: *Configuración del negocio → Usuarios → Usuarios del sistema* → agregá uno
   (administrador) → *Asignar activos*: tu app, con control total → *Generar token* con los permisos
   `whatsapp_business_messaging` y `whatsapp_business_management`. En Parla, cargalo en la clave `WHATSAPP_TOKEN`
   (botón **Cargar**).
4. **Clave secreta de la app.** *Configuración de la app → Básica → Clave secreta de la app* → *Mostrar*. Cargala
   en `WHATSAPP_APP_SECRET`. Con ella Parla comprueba que cada mensaje viene de verdad de Meta (encabezado
   `X-Hub-Signature-256`).
5. **Token de verificación.** Inventá una palabra larga y al azar (por ejemplo la salida de `openssl rand -hex 24`)
   y cargala en `WHATSAPP_VERIFY_TOKEN`.
6. **Prendé** «Atender por WhatsApp» en Parla. Mientras esté apagado el webhook responde 403 y Meta no lo puede
   verificar.
7. **Webhook.** En Meta, *WhatsApp → Configuración → Webhook → Editar*:
   - *URL de devolución de llamada*: la que muestra **Canales** (`https://bots.midominio.com/api/v1/bots/<id>/whatsapp`).
   - *Token de verificación*: la misma palabra que `WHATSAPP_VERIFY_TOKEN`.
   - *Verificar y guardar*. Meta hace un `GET` con ese token y Parla le devuelve el desafío.
   - En *Campos del webhook*, **suscribite a `messages`**. Ese campo también trae los estados de entrega (`sent`,
     `delivered`, `read`, `failed`) que usan las campañas ([outbound_es.md](outbound_es.md#estados-de-entrega)).
8. **Probá.** Con el número de prueba, sumá tu teléfono a la lista de destinatarios en *Configuración de la API*.
   Escribile al número: el bot contesta. Para atender a cualquiera, la app tiene que estar en modo *Activo (Live)* y
   el número verificado.

**Canales** muestra el último mensaje recibido, la última respuesta enviada y el último error (por ejemplo un token
vencido), desde que arrancó Parla.

## Telegram

1. Hablale a [@BotFather](https://t.me/BotFather), mandá `/newbot`, elegí nombre y usuario, y copiá el **token**
   (`123456789:AA…`).
2. En Parla, **Canales → Telegram**: prendé «Atender por Telegram», cargá el token en `TELEGRAM_TOKEN` y revisá que
   la **Dirección pública** empiece con `https://`.
3. Tocá **Conectar webhook**. Parla genera un secreto al azar (`TELEGRAM_WEBHOOK_SECRET`, en la bóveda) y llama a
   `setWebhook` de Telegram con la URL `…/api/v1/bots/<id>/telegram` y ese secreto. Telegram lo manda en cada pedido
   (encabezado `X-Telegram-Bot-Api-Secret-Token`) y Parla rechaza los que no lo traen.
4. Escribile a tu bot. **Desconectar** llama a `deleteWebhook`.

Telegram solo llama a webhooks en los puertos 443, 80, 88 u 8443. Para ver qué ve Telegram:
`curl https://api.telegram.org/bot<token>/getWebhookInfo` (muestra el último error, si hubo).

## Cómo se manda cada cosa

| Del bot | WhatsApp | Telegram |
|---|---|---|
| Texto | Mensaje de texto (hasta 4096 caracteres). | Mensaje de texto (hasta 4096), sin formato. |
| 1 a 3 botones | Botones de respuesta (título cortado a 20 letras). | Un botón por fila (`inline_keyboard`). |
| 4 a 10 botones | Una lista con el botón «Opciones» (títulos cortados a 24 letras). | Igual que arriba. |
| Más de 10 botones | Solo se ven los primeros 10. | Todos. |
| Archivo (paso `file`) | Se sube a Meta (`/media`) y va como imagen (JPG/PNG hasta 5 MB) o documento, con el texto como epígrafe. | Se sube como foto (JPG/PNG hasta 5 MB) o documento. |

Tocar un botón es como escribir su valor. Si el valor no entra en lo que permite el canal (200 bytes en WhatsApp, 64
en Telegram), viaja como `#n` y Parla lo traduce al valor de ese botón.

Lo que llega de la persona:

- Texto, botones y elecciones de la lista van al bot como un mensaje.
- Imágenes, audios, documentos, videos, stickers y ubicaciones no se descargan: el bot recibe el epígrafe o un
  marcador (`[imagen]`, `[audio]`…), y la conversación guarda `media` (`type`, `id`, `mime`) para que quien lee la
  Bandeja sepa que llegó algo. Los audios no se transcriben.
- En Telegram, `/start` empieza la conversación de cero (el evento `start`: corre el flujo `__start__`). WhatsApp no
  tiene ese evento: el primer mensaje va directo al bot y el flujo `__start__` no corre.

Las conversaciones se llaman `wa-<teléfono>` y `tg-<chat_id>`: la misma persona sigue en la misma conversación.

## Pasar con una persona

Funciona igual que en la web: cuando un flujo o la persona piden hablar con alguien, la conversación aparece en la
**Bandeja** y el bot se calla. Los mensajes de la persona siguen llegando ahí (sin respuesta del bot); lo que escribe
la persona del equipo desde la Bandeja se manda por el canal. **Devolver al bot** la devuelve.

## Límites

- **La ventana de 24 horas de WhatsApp.** WhatsApp solo deja mandar mensajes libres hasta 24 horas después del
  último mensaje de la persona. Pasado eso, hay que usar una **plantilla** aprobada. Cuando el bot escribe primero
  (la API de salida, campañas y recordatorios), la plantilla se elige sola de **Canales → WhatsApp → Plantillas
  aprobadas** (`channels.whatsapp.templates`): ver [outbound_es.md](outbound_es.md). Una respuesta de la **Bandeja**
  después de 24 horas sigue fallando (Meta responde el error 131047 y lo ves en **Canales → Último error**), porque la
  Bandeja manda texto libre.
- El filtro de repetidos, el orden por conversación y el estado de **Canales** viven en memoria: se pierden al
  reiniciar y no funcionan con varias réplicas (corré una; ver [deployment_es.md](deployment_es.md)).
- Si Meta o Telegram reintentan un mensaje justo después de reiniciar, podría contestarse dos veces.
- Grupos de Telegram: por defecto un bot solo ve comandos y respuestas a él (*privacy mode* de BotFather).
- No se usa el formato de Telegram ni de WhatsApp (negritas, links en botones, Markdown): va texto plano.

## Seguridad

- Las rutas de los webhooks son las únicas que se saltean el login y el chequeo de `Host`, porque vienen de los
  servidores de Meta y Telegram. En cambio:
  - WhatsApp: cada `POST` tiene que traer `X-Hub-Signature-256`, el HMAC-SHA256 del cuerpo tal cual con la clave
    secreta de la app.
  - Telegram: cada `POST` tiene que traer el encabezado `X-Telegram-Bot-Api-Secret-Token` con el secreto del webhook.
  - Las dos se comparan en tiempo constante. El `GET` de WhatsApp (verificación) tiene que traer el token de
    verificación.
- Si el canal está apagado, falta una clave o la firma no coincide, la respuesta es **403 sin detalles**. El cuerpo
  tiene un máximo de 1 MB.
- Los tokens y secretos viven solo en la bóveda del agente (`<agente>.secrets.json`, permisos 600): no están en el
  JSON del agente, no se exportan, la API no los devuelve y el MCP no los ve. Los errores van a la consola con los
  valores tapados (`••••`).
- El id de la conversación tiene el teléfono (WhatsApp) o el chat (Telegram): es un dato personal. Lo ve quien puede
  ver las conversaciones del bot.
- Solo se aceptan mensajes del `phone_number_id` configurado. Un id de mensaje repetido se atiende una sola vez.

- Teléfono: los pedidos de Twilio tienen que traer `X-Twilio-Signature` (HMAC-SHA1 con `TWILIO_AUTH_TOKEN` de la URL
  completa más los parámetros del POST ordenados); los de jambonz, `Jambonz-Signature` (`JAMBONZ_WEBHOOK_SECRET`)
  y/o HTTP basic (`JAMBONZ_BASIC_USER` / `JAMBONZ_BASIC_PASSWORD`). El audio de Parla para las llamadas solo se
  sirve con un token firmado con HMAC que vence a los 10 minutos y nombra al bot; el id `call-<CallSid>` y el número
  de quien llama (`caller`, si el bot tiene un slot con ese nombre) son datos personales.

Más en [security_es.md](security_es.md#canales-de-mensajería-whatsapp-y-telegram).

## Llamadas telefónicas (Twilio y jambonz)

Un bot también puede atender **llamadas telefónicas**, por **Twilio Programmable Voice** (en la nube, el más
común) o por **jambonz** (código abierto, se instala en tu propia infraestructura SIP). Es el mismo bot: cada
llamada es una conversación `call-<CallSid>` con canal `phone`, corre el flujo `__start__` al atender y aparece en
**Conversaciones** y en la **Bandeja** como cualquier otra.

Cómo funciona una llamada: el proveedor llama al webhook de Parla cuando entra la llamada, Parla contesta qué decir
y que escuche (`<Gather>` / `gather`), el proveedor transcribe lo que dice la persona (o junta las teclas) y se lo
manda, Parla corre un turno y contesta el paso siguiente: volver a escuchar, transferir (`<Dial>` / `dial`) o
cortar (`<Hangup>` / `hangup`).

### Configuración

**Canales → Teléfono** (`channels.phone` en el JSON del agente; ahí no va nada secreto):

| Campo | Qué es |
|---|---|
| `enabled` | Atender llamadas. Apagado, los webhooks responden 403. |
| `provider` | `twilio` (por defecto) o `jambonz`. Solo se aceptan los webhooks del proveedor elegido. |
| `language` | Variante de idioma para reconocer y hablar, por ejemplo `es-AR`, `en-US`, `pt-BR`. Si la charla pasa a otro idioma del bot, Parla usa `es-US`, `en-US` o `pt-BR`. |
| `tts` | `provider` (por defecto): la voz del proveedor (`<Say>` / `say`). `parla`: la voz del agente (`voice.tts`: piper local o un proveedor con tu key, como Deepgram Aura-2, ElevenLabs, OpenAI o Google), que se reproduce desde direcciones firmadas (`<Play>` / `play`): la misma voz que la llamada de prueba y sin TTS del proveedor. |
| `voice` | Nombre de la voz del proveedor (opcional): `Polly.Mia-Neural` en Twilio, la voz del sintetizador configurado en jambonz. |
| `handoff_to` | A dónde transferir cuando la charla pasa a una persona: un número (`+5491112345678`) o una dirección SIP (`sip:mesa@pbx.midominio.com`). |
| `finish_on_key` | Tecla que termina un número escrito con el teclado. Por defecto `#`. |
| `greeting` | Qué decir al atender si el bot no tiene flujo `__start__`. Por defecto «Hola, ¿en qué te puedo ayudar?» en el idioma del bot. |
| `from` | **Número desde el que se llama**: tu número en el proveedor, o una URI SIP. Solo para llamadas salientes. |
| `api_url` | **Dirección de la API de jambonz** para llamadas salientes. Por defecto `https://api.jambonz.cloud`. |
| `application_sid` | **Application SID**: la aplicación de jambonz que atiende las llamadas salientes (recomendado). |

La dirección pública es la misma que la de los otros canales (`PARLA_PUBLIC_URL` o **Dirección pública**).

Para **hacer llamadas** (API de salida, campañas, recordatorios) Parla además necesita, en **Claves**,
`TWILIO_ACCOUNT_SID` (junto con `TWILIO_AUTH_TOKEN`) en Twilio, o `JAMBONZ_API_KEY` y `JAMBONZ_ACCOUNT_SID` en jambonz.
Para atender llamadas no hacen falta. Ver [outbound_es.md](outbound_es.md#teléfono-llamadas-salientes).

### Twilio paso a paso

1. Creá una cuenta en [twilio.com](https://www.twilio.com) y comprá un número con voz (sirve una cuenta de prueba,
   con un aviso antes de cada llamada y solo a números verificados).
2. En Parla, **Canales → Teléfono**: prendé **Atender llamadas**, proveedor **Twilio**, elegí el idioma.
3. Cargá el **Auth Token** de la cuenta (*Console → Account Info*) en `TWILIO_AUTH_TOKEN`. Parla lo usa para
   verificar el `X-Twilio-Signature` de cada pedido. Si lo rotás en Twilio, cargá el nuevo.
4. En Twilio, *Phone Numbers → Manage → Active numbers → tu número → Voice configuration*:
   - *A call comes in*: **Webhook**, `https://bots.midominio.com/api/v1/bots/<id>/phone/twilio`, **HTTP POST**.
   - *Call status changes*: `https://bots.midominio.com/api/v1/bots/<id>/phone/twilio/status`.
   Copialas tal cual las muestra **Canales**: la firma cubre la URL completa.
5. Llamá al número.

**Costos y privacidad con Twilio:** Twilio cobra por minuto de llamada, y aparte el reconocimiento de voz
(`<Gather input="speech">`) y sus voces; mirá sus precios actuales. **La voz de quien llama la transcribe Twilio**
(y los proveedores de voz que usa), no Parla: el audio y la transcripción salen de tu servidor. A Parla solo llega
el texto. Con `tts: "parla"` las respuestas del bot las genera la voz del agente (acá con piper, o en el proveedor que
use), pero el reconocimiento sigue en Twilio. Si el
audio no puede salir de tu infraestructura, usá jambonz con un reconocedor propio.

### jambonz paso a paso

1. Tené un jambonz: propio ([docs.jambonz.org](https://docs.jambonz.org/)) o el servicio en la nube, con un
   troncal SIP / operador y un número, y un reconocedor y un sintetizador de voz configurados (*Speech services*).
   Ahí elegís quién transcribe y quién habla: un proveedor en la nube o uno propio.
2. En Parla, **Canales → Teléfono**: prendé **Atender llamadas**, proveedor **jambonz**, elegí el idioma.
3. Autenticación (al menos una; si cargás las dos, tienen que dar bien las dos):
   - **Firma del webhook**: copiá el *webhook secret* de tu cuenta (en el portal de jambonz, *Account*) en
     `JAMBONZ_WEBHOOK_SECRET`. jambonz manda `Jambonz-Signature: t=<unix>,v1=<hex>`, el HMAC-SHA256 de
     `<t>.<cuerpo>`; Parla lo compara en tiempo constante y rechaza firmas de hace más de 5 minutos.
   - **HTTP basic**: inventá un usuario y una contraseña larga, ponelos en la aplicación de jambonz y cargalos en
     `JAMBONZ_BASIC_USER` y `JAMBONZ_BASIC_PASSWORD`. Útil en instalaciones propias.
4. En jambonz, *Applications → Add application*:
   - *Calling webhook*: `https://bots.midominio.com/api/v1/bots/<id>/phone/jambonz`, **POST**.
   - *Call status webhook*: `https://bots.midominio.com/api/v1/bots/<id>/phone/jambonz/status`, **POST**.
   - Elegí los proveedores de voz y el idioma (Parla manda `vendor: "default"`: se usan los de la aplicación).
5. Apuntá tu número (*Phone numbers*) a esa aplicación y llamá.

### Teclado (DTMF), botones y números

- Cuando el último mensaje del bot tiene **botones**, Parla los anuncia en el idioma del bot: «Marcá 1 para
  Muzzarella, 2 para Fugazza.» / «Press 1 for …» / «Digite 1 para …» (los primeros 9). Una tecla elige ese botón,
  y la llamada espera una sola tecla. Decir la opción en voz alta también sirve.
- Cuando el bot **pregunta un dato** (un DNI, un número de pedido), la persona lo puede marcar y terminar con `#`
  (`finish_on_key`): los dígitos le llegan al bot como respuesta.
- **Pistas para el reconocedor:** los valores y sinónimos de las entidades del bot y las etiquetas de los botones
  van como pistas (`hints`), igual que en la transcripción local.

### Qué se dice por teléfono

- **Texto para la voz:** se sacan emojis, Markdown (`**negrita**`, `[texto](url)`, viñetas, títulos) y direcciones
  web antes de hablar. Las respuestas largas se parten por oraciones en varios `<Say>` / audios. Escribí textos
  cortos para el teléfono: un link o una lista de diez opciones no funcionan por voz.
- **Archivos** (paso `file`): no se pueden mandar en una llamada. Parla dice el texto del paso, si tiene, y un aviso
  corto («Tengo un archivo para vos, pero por teléfono no lo puedo mandar.»).
- **Interrumpir (barge-in):** todo se dice dentro del `Gather` / `gather`, así la persona puede interrumpir
  hablando o con una tecla (en jambonz con `bargein` y `dtmfBargein`).
- **Silencio:** si no se escucha nada (`actionOnEmptyResult` en Twilio, un `timeout` en jambonz), Parla repite la
  última pregunta; después de 3 silencios seguidos se despide y corta.
- **Cortar:** un paso `end` corta después de decir lo anterior. Cuando la persona corta, el webhook de estado
  termina la conversación.
- **Voces:** con `tts: "provider"` habla la voz del proveedor (`voice`); con `tts: "parla"` habla la voz del
  agente (`voice.tts`) con las mismas frases pregeneradas que la llamada de prueba (las fijas se preparan antes y
  suenan al instante; las que tienen `{{ }}` se generan cuando el proveedor las baja, con algo de demora).
- **Menor demora:** `tts: "parla"` con Deepgram Aura-2 o ElevenLabs Flash como voz del agente. Configuración, keys y
  qué sale de la máquina en [ai-and-voice_es.md](ai-and-voice_es.md).

### Pasar con una persona en una llamada

Cuando un flujo o la persona piden hablar con alguien, Parla dice el texto del paso y transfiere la llamada a
`handoff_to` (`<Dial>` / `dial`); la conversación queda en la **Bandeja** con un evento «Transferida a …». Sin
`handoff_to`, Parla pide disculpas y corta (y muestra el error en **Canales**). En una llamada no hay nada para
escribir: en la Bandeja, **Tomar conversación** hace que Parla transfiera la llamada a `handoff_to` apenas la persona
deje de hablar.

### Límites del teléfono

- Las llamadas salientes (la API, campañas y recordatorios) necesitan `from`, las claves del proveedor y, en jambonz,
  `api_url` y `application_sid`: ver [outbound_es.md](outbound_es.md#teléfono-llamadas-salientes). No se detectan
  contestadores automáticos.
- El reconocimiento de voz lo hace el proveedor (Twilio, o lo que tenga configurado jambonz), no Parla (ni el
  faster-whisper local ni el `voice.asr` del agente). Los turnos son pedido/respuesta (sin audio en streaming): cada
  respuesta espera a que la persona termine la frase.
- El proveedor espera unos 15 segundos cada respuesta: pasos de IA o consultas HTTP lentas pueden hacerla fallar.
  Que sean rápidos.
- Tomar una llamada desde la Bandeja transfiere en el próximo turno (o silencio) de la persona, no al instante.
- El contador de silencios y la clave que firma los audios viven en memoria: un reinicio invalida los audios que se
  están reproduciendo (igual duran 10 minutos), y varias réplicas necesitan una sola instancia (corré una).
- `tts: "parla"` necesita los extras de voz en el servidor (con piper) o la key del proveedor de voz en **Claves**,
  y el proveedor tiene que llegar a las direcciones de los audios (están bajo `/api/v1/`, como los webhooks).

## Probar sin cuentas reales

`tests/test_channels.py` corre todo contra APIs falsas de Graph y Telegram en un puerto local. Las direcciones de
esas APIs se cambian con `PARLA_WHATSAPP_API` (por defecto `https://graph.facebook.com/v21.0`) y
`PARLA_TELEGRAM_API` (por defecto `https://api.telegram.org`). Cambialas solo para pruebas. `tests/test_outbound.py`
también simula Twilio (`PARLA_TWILIO_API`) y jambonz (`channels.phone.api_url`) para las llamadas salientes.

`tests/test_phone.py` manda pedidos falsos y firmados de Twilio y jambonz (primer turno, voz, teclas, pasar con una
persona, cortar, silencio, firmas, audios firmados) sin hablar con ningún proveedor. Para probar una llamada real
desde tu compu, publicá Parla con un túnel (`cloudflared tunnel --url http://127.0.0.1:8000`), poné esa dirección
como dirección pública y pegá los webhooks en Twilio o jambonz.
