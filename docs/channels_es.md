# WhatsApp y Telegram

[English](channels.md) · **Español**

Un bot puede atender por **WhatsApp** (la Cloud API de WhatsApp Business, de Meta) y por **Telegram**, además del
widget web y la API. Es el mismo bot y el mismo motor: contesta con lo publicado en **Producción** (o el borrador si
todavía no publicaste nada), con sus botones y archivos. Las conversaciones aparecen en **Conversaciones** con el
canal `whatsapp` o `telegram`, y cuando la charla pasa a una persona, lo que esa persona escribe en la **Bandeja**
también le llega al WhatsApp o Telegram del cliente.

Todo se configura en **Publicar → Canales**.

## Qué hace falta

- **Una dirección pública con HTTPS.** Meta y Telegram le hablan a Parla por internet, así que Parla tiene que
  estar publicado con un certificado válido: un servidor detrás de un proxy, un Ingress de Kubernetes o un túnel
  (Cloudflare Tunnel, ngrok, Tailscale Funnel) para probar. Ver [deployment_es.md](deployment_es.md).
- **Que el proxy publique las rutas de los webhooks.** Están bajo `/api/v1/`, que los proxies e Ingress de ejemplo
  de `deploy/` ya publican:
  - `GET` y `POST /api/v1/bots/{bot}/whatsapp`
  - `POST /api/v1/bots/{bot}/telegram`
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
   - En *Campos del webhook*, **suscribite a `messages`**.
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
  último mensaje de la persona. Pasado eso, hay que usar una **plantilla** aprobada. Parla **todavía no maneja
  plantillas ni empieza conversaciones**: una respuesta de la Bandeja después de 24 horas falla (Meta responde el
  error 131047) y lo ves en **Canales → Último error**.
- No hay envíos salientes ni masivos: el bot solo contesta.
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

Más en [security_es.md](security_es.md#canales-de-mensajería-whatsapp-y-telegram).

## Probar sin cuentas reales

`tests/test_channels.py` corre todo contra APIs falsas de Graph y Telegram en un puerto local. Las direcciones de
esas APIs se cambian con `PARLA_WHATSAPP_API` (por defecto `https://graph.facebook.com/v21.0`) y
`PARLA_TELEGRAM_API` (por defecto `https://api.telegram.org`). Cambialas solo para pruebas.
