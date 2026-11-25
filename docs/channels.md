# WhatsApp and Telegram

**English** · [Español](channels_es.md)

A bot can answer on **WhatsApp** (Meta's WhatsApp Business Cloud API) and **Telegram**, besides the web widget and
the API. It is the same bot and the same conversation engine: it answers with what is published in **Producción**
(Production), or the draft if nothing has been published yet, with its buttons and files. Conversations show up in
**Conversaciones** (Conversations) with channel `whatsapp` or `telegram`. When the conversation is handed to a person, what
that person writes in the **Bandeja** (Inbox) reaches the customer's WhatsApp or Telegram too.

Everything is configured in **Publicar → Canales** (Publish → Channels).

## Requirements

- **A public HTTPS address.** Meta and Telegram call Parla over the internet, so Parla has to be reachable
  with a valid certificate: a server behind a reverse proxy, a Kubernetes Ingress, or a tunnel (Cloudflare Tunnel,
  ngrok, Tailscale Funnel) for testing. See [deployment.md](deployment.md).
- **The proxy has to publish the webhook paths.** They live under `/api/v1/`, which the example proxies and
  Ingresses in `deploy/` already publish:
  - `GET` and `POST /api/v1/bots/{bot}/whatsapp`
  - `POST /api/v1/bots/{bot}/telegram`
- **Tell Parla its public address**, in one of two ways:
  - The `PARLA_PUBLIC_URL` environment variable (`https://bots.mydomain.com`), for the whole server.
  - **Dirección pública** (Public address) in **Canales**, per bot (`channels.public_url` in the agent JSON). It wins over the variable.

  It is used to show the webhook URL and to connect Telegram. You **don't** need to add that domain to
  `PARLA_HOSTS`: webhooks are allowed from any `Host` (they authenticate with a signature, see below).

## WhatsApp (Cloud API)

You need a Meta Business account and a phone number that isn't registered in the WhatsApp app (Meta also gives
you a test number).

1. **Create the app.** At [developers.facebook.com](https://developers.facebook.com/apps) → *Create app* → type
   *Business*. Add the **WhatsApp** product.
2. **Phone number ID.** In *WhatsApp → API Setup*, choose the number (or the test one) and copy the **Phone number
   ID** (a long number; not the phone number itself). In Parla, **Canales → WhatsApp → Identificador del número**
   (Phone number ID).
3. **Permanent token.** The token shown in *API Setup* lasts 24 hours: good for a first test only. For real use:
   *Business Settings → Users → System users* → add one (admin) → *Assign assets*: your app, with full control →
   *Generate token* with the permissions `whatsapp_business_messaging` and `whatsapp_business_management`. In
   Parla, load it in the `WHATSAPP_TOKEN` key (button **Cargar**, Load).
4. **App secret.** *App settings → Basic → App secret* → *Show*. Load it in `WHATSAPP_APP_SECRET`. Parla uses it
   to check that each message really comes from Meta (`X-Hub-Signature-256` header).
5. **Verify token.** Make up a long random word (for example the output of `openssl rand -hex 24`) and load it in
   `WHATSAPP_VERIFY_TOKEN`.
6. **Turn on** «Atender por WhatsApp» (Answer on WhatsApp) in Parla. Until then the webhook answers 403, and Meta can't verify it.
7. **Webhook.** In Meta, *WhatsApp → Configuration → Webhook → Edit*:
   - *Callback URL*: the one shown by **Canales** (`https://bots.mydomain.com/api/v1/bots/<id>/whatsapp`).
   - *Verify token*: the same word as `WHATSAPP_VERIFY_TOKEN`.
   - *Verify and save*. Meta makes a `GET` with that token, and Parla answers with the challenge.
   - In *Webhook fields*, **subscribe to `messages`**.
8. **Test.** With the test number, add your phone to the allowed recipients list in *API Setup*. Write to the
   number: the bot answers. To serve everyone, the app has to be in *Live* mode and the number verified.

**Canales** shows the last message received, the last answer sent and the last error (for example a token
that expired), since Parla started.

## Telegram

1. Talk to [@BotFather](https://t.me/BotFather), send `/newbot`, pick a name and a user, and copy the **token**
   (`123456789:AA…`).
2. In Parla, **Canales → Telegram**: turn on «Atender por Telegram» (Answer on Telegram), load the token in `TELEGRAM_TOKEN` and check that
   the **Dirección pública** (Public address) starts with `https://`.
3. Press **Conectar webhook** (Connect webhook). Parla generates a random secret (`TELEGRAM_WEBHOOK_SECRET`, in the vault) and calls
   Telegram's `setWebhook` with the URL `…/api/v1/bots/<id>/telegram` and that secret. Telegram sends it in every
   request (`X-Telegram-Bot-Api-Secret-Token` header), and Parla rejects requests that don't have it.
4. Write to your bot. **Desconectar** (Disconnect) calls `deleteWebhook`.

Telegram only calls webhooks on ports 443, 80, 88 or 8443. To check what Telegram sees:
`curl https://api.telegram.org/bot<token>/getWebhookInfo` (it shows the last error, if any).

## How each thing is sent

| From the bot | WhatsApp | Telegram |
|---|---|---|
| Text | Text message (up to 4096 characters). | Text message (up to 4096), no formatting. |
| 1 to 3 buttons | Reply buttons (title cut to 20 characters). | One button per row (`inline_keyboard`). |
| 4 to 10 buttons | A list with a «Opciones» (Options) button (titles cut to 24 characters). | Same as above. |
| More than 10 buttons | Only the first 10 are shown. | All of them. |
| File (`file` step) | It is uploaded to Meta (`/media`) and sent as an image (JPG/PNG up to 5 MB) or a document, with the text as caption. | It is uploaded as a photo (JPG/PNG up to 5 MB) or a document. |

Tapping a button is like writing its value. If the value doesn't fit what the channel allows (200 bytes on
WhatsApp, 64 on Telegram), it travels as `#n` and Parla translates it back to the value of that button.

What comes from the person:

- Text, buttons and list choices go to the bot as a message.
- Images, audio, documents, videos, stickers and locations aren't downloaded: the bot receives the caption or a
  placeholder (`[imagen]`, `[audio]`…), and the conversation keeps `media` (`type`, `id`, `mime`) so whoever reads the
  Bandeja knows something arrived. Voice notes aren't transcribed.
- On Telegram, `/start` starts the conversation from scratch (the `start` event: it runs the `__start__` flow).
  WhatsApp has no such event: the first message goes straight to the bot and the `__start__` flow doesn't run.

Conversation ids are `wa-<phone>` and `tg-<chat_id>`: the same person keeps the same conversation.

## Handoff to a person

It works the same as on the web: when a flow or the person asks for a human, the conversation shows up in the
**Bandeja** and the bot stays quiet. The person's messages keep arriving there (without a bot answer); what the human
writes from the Bandeja is sent through the channel. **Devolver al bot** (Return to the bot) gives it back.

## Limits

- **WhatsApp's 24-hour window.** WhatsApp only allows free-form messages within 24 hours of the person's last
  message. After that, a message has to be an approved **template**. Parla **doesn't support templates or
  starting conversations** yet: a Bandeja reply after 24 hours fails (Meta answers error 131047), and you see that
  in **Canales → Último error** (Last error).
- No outbound or bulk sending: the bot only answers.
- The duplicate filter, the per-conversation order and the status in **Canales** live in memory: they are lost on
  restart and don't work across several replicas (run one; see [deployment.md](deployment.md)).
- If Meta or Telegram retry a message right after a restart, it could be answered twice.
- Telegram groups: by default a bot only sees commands and replies to it (BotFather's *privacy mode*).
- Telegram and WhatsApp formatting (bold, links in buttons, Markdown) isn't used: plain text is sent.

## Security

- The webhook routes are the only ones that skip the login and the `Host` check, because they come from Meta's and
  Telegram's servers. Instead:
  - WhatsApp: each `POST` has to carry `X-Hub-Signature-256`, the HMAC-SHA256 of the raw body with the app secret.
  - Telegram: each `POST` has to carry the `X-Telegram-Bot-Api-Secret-Token` header with the webhook secret.
  - Both are compared in constant time. The WhatsApp `GET` (verification) has to bring the verify token.
- If the channel is turned off, a key is missing, or the signature doesn't match, the answer is **403 with no
  details**. The body is capped at 1 MB.
- Tokens and secrets live only in the agent's vault (`<agent>.secrets.json`, mode 600): they aren't in the agent's
  JSON, aren't exported, aren't returned by the API, and the MCP can't see them. Errors are logged to the console
  with values masked (`••••`).
- The conversation id contains the phone number (WhatsApp) or chat id (Telegram): it's personal data. Whoever can
  see the bot's conversations sees it.
- Messages are only accepted for the configured `phone_number_id`. Repeated message ids are answered once.

More in [security.md](security.md#messaging-channels-whatsapp-and-telegram).

## Testing without real accounts

`tests/test_channels.py` runs everything against fake Graph and Telegram APIs on a local port. The base URLs of those
APIs can be changed with `PARLA_WHATSAPP_API` (default `https://graph.facebook.com/v21.0`) and
`PARLA_TELEGRAM_API` (default `https://api.telegram.org`). Only change them for tests.
