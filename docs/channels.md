# WhatsApp, Telegram and phone

**English** · [Español](channels_es.md)

A bot can answer on **WhatsApp** (Meta's WhatsApp Business Cloud API) and **Telegram**, besides the web widget and
the API. It is the same bot and the same conversation engine: it answers with what is published in **Production**,
or the draft if nothing has been published yet, with its buttons and files. Conversations show up in
**Conversations** with channel `whatsapp` or `telegram`. When the conversation is handed to a person, what that
person writes in the **Inbox** reaches the customer's WhatsApp or Telegram too. It can also answer **phone
calls** through Twilio or jambonz: see [Phone calls](#phone-calls-twilio-and-jambonz). And it can **write first**
(the outbound API, campaigns and reminders, also outbound calls): see [outbound.md](outbound.md).

Everything is configured in **Publish → Channels**.

## Requirements

- **A public HTTPS address.** Meta and Telegram call Parla over the internet, so Parla has to be reachable
  with a valid certificate: a server behind a reverse proxy, a Kubernetes Ingress, or a tunnel (Cloudflare Tunnel,
  ngrok, Tailscale Funnel) for testing. See [deployment.md](deployment.md).
- **The proxy has to publish the webhook paths.** They live under `/api/v1/`, which the example proxies and
  Ingresses in `deploy/` already publish:
  - `GET` and `POST /api/v1/bots/{bot}/whatsapp`
  - `POST /api/v1/bots/{bot}/telegram`
  - `POST /api/v1/bots/{bot}/phone/twilio[/gather|/status]` or `…/phone/jambonz[/gather|/status]`, and
    `GET /api/v1/bots/{bot}/phone/audio/<token>.wav` (Parla's voice on calls)
- **Tell Parla its public address**, in one of two ways:
  - The `PARLA_PUBLIC_URL` environment variable (`https://bots.mydomain.com`), for the whole server.
  - **Public address** in **Channels**, per bot (`channels.public_url` in the agent JSON). It wins over the variable.

  It is used to show the webhook URL and to connect Telegram. You **don't** need to add that domain to
  `PARLA_HOSTS`: webhooks are allowed from any `Host` (they authenticate with a signature, see below).

## WhatsApp (Cloud API)

You need a Meta Business account and a phone number that isn't registered in the WhatsApp app (Meta also gives
you a test number).

1. **Create the app.** At [developers.facebook.com](https://developers.facebook.com/apps) → *Create app* → type
   *Business*. Add the **WhatsApp** product.
2. **Phone number ID.** In *WhatsApp → API Setup*, choose the number (or the test one) and copy the **Phone number
   ID** (a long number; not the phone number itself). In Parla, **Channels → WhatsApp → Phone number ID**.
3. **Permanent token.** The token shown in *API Setup* lasts 24 hours: good for a first test only. For real use:
   *Business Settings → Users → System users* → add one (admin) → *Assign assets*: your app, with full control →
   *Generate token* with the permissions `whatsapp_business_messaging` and `whatsapp_business_management`. In
   Parla, load it in the `WHATSAPP_TOKEN` key (button **Cargar**, Load).
4. **App secret.** *App settings → Basic → App secret* → *Show*. Load it in `WHATSAPP_APP_SECRET`. Parla uses it
   to check that each message really comes from Meta (`X-Hub-Signature-256` header).
5. **Verify token.** Make up a long random word (for example the output of `openssl rand -hex 24`) and load it in
   `WHATSAPP_VERIFY_TOKEN`.
6. Turn on **Answer on WhatsApp** in Parla. Until then the webhook answers 403, and Meta can't verify it.
7. **Webhook.** In Meta, *WhatsApp → Configuration → Webhook → Edit*:
   - *Callback URL*: the one shown by **Channels** (`https://bots.mydomain.com/api/v1/bots/<id>/whatsapp`).
   - *Verify token*: the same word as `WHATSAPP_VERIFY_TOKEN`.
   - *Verify and save*. Meta makes a `GET` with that token, and Parla answers with the challenge.
   - In *Webhook fields*, **subscribe to `messages`**. That field also brings the delivery statuses (`sent`,
     `delivered`, `read`, `failed`) that campaigns use ([outbound.md](outbound.md#delivery-statuses)).
8. **Test.** With the test number, add your phone to the allowed recipients list in *API Setup*. Write to the
   number: the bot answers. To serve everyone, the app has to be in *Live* mode and the number verified.

**Channels** shows the last message received, the last answer sent and the last error (for example a token
that expired), since Parla started.

## Telegram

1. Talk to [@BotFather](https://t.me/BotFather), send `/newbot`, pick a name and a user, and copy the **token**
   (`123456789:AA…`).
2. In Parla, **Channels → Telegram**: turn on **Answer on Telegram**, load the token in `TELEGRAM_TOKEN` and check that
   the **Public address** starts with `https://`.
3. Press **Connect webhook**. Parla generates a random secret (`TELEGRAM_WEBHOOK_SECRET`, in the vault) and calls
   Telegram's `setWebhook` with the URL `…/api/v1/bots/<id>/telegram` and that secret. Telegram sends it in every
   request (`X-Telegram-Bot-Api-Secret-Token` header), and Parla rejects requests that don't have it.
4. Write to your bot. **Disconnect** calls `deleteWebhook`.

Telegram only calls webhooks on ports 443, 80, 88 or 8443. To check what Telegram sees:
`curl https://api.telegram.org/bot<token>/getWebhookInfo` (it shows the last error, if any).

## How each thing is sent

| From the bot | WhatsApp | Telegram |
|---|---|---|
| Text | Text message (up to 4096 characters). | Text message (up to 4096), no formatting. |
| 1 to 3 buttons | Reply buttons (title cut to 20 characters). | One button per row (`inline_keyboard`). |
| 4 to 10 buttons | A list with an “Options” button, in the bot's language (titles cut to 24 characters). | Same as above. |
| More than 10 buttons | Only the first 10 are shown. | All of them. |
| File (`file` step) | It is uploaded to Meta (`/media`) and sent as an image (JPG/PNG up to 5 MB) or a document, with the text as caption. | It is uploaded as a photo (JPG/PNG up to 5 MB) or a document. |

Tapping a button is like writing its value. If the value doesn't fit what the channel allows (200 bytes on
WhatsApp, 64 on Telegram), it travels as `#n` and Parla translates it back to the value of that button.

What comes from the person:

- Text, buttons and list choices go to the bot as a message.
- **Media** (images, audio, documents, videos, stickers) is downloaded (WhatsApp: `GET /{media-id}` → `url` →
  `GET` with the token; Telegram: `getFile` → `file_path`), 16 MB max, 30 s timeout, only images, audio, video, PDF,
  Office, text, CSV and zip (never HTML/SVG). It's stored with the agent's files but tied to the conversation: it isn't
  listed among the bot's files, `/files/…` serves it only to someone who can see that agent's conversations (session
  or API key), and it's deleted with the conversation (API delete or retention). Too big or a disallowed type: not
  stored, the bot gets the placeholder (`[imagen]`, `[documento]`…) and `media.error` says why.
- **Voice notes and audio** are transcribed with the agent's ASR (**AI & voice → Speech recognition**; local Whisper
  or a provider, cost recorded in the turn) and the transcript goes to the bot as the person's message. The history
  keeps the text plus `media.url` and `media.transcript` (masked like the rest with PII redaction). If ASR fails, the
  bot gets `[audio sin transcribir]` and answers its fallback.
- The turn receives `media`: `{type, url, mime, name, size, caption, transcript}`, usable in steps as
  `{{ media.url }}`, `{{ media.type }}`, `{{ media.caption }}` (only on the turn that brought it; `{{ }}` on a missing
  `media` is an error, so guard it with a condition). A **location** arrives as slot-friendly text
  (`Name, address (-34.6037,-58.3816)` or `-34.6037,-58.3816`) with `media.lat`/`lng`/`name`/`address`; a **contact** as
  `Name +phone` with `media.name`/`phone`.
- **Vision (optional, off):** with `"ai": {"vision": true}` and an OpenAI, Claude or Gemini provider, each image is
  described in a sentence (`media.description`, AI cost recorded) and the AI steps see it next to the message as
  `[imagen: …]`. Intents and slots still get only the caption.
- Inbox and Conversations show photos as thumbnails, audio with a player (plus the transcript as the message), files
  as links and locations with a map link.
- On Telegram, `/start` starts the conversation from scratch (the `start` event: it runs the `__start__` flow).
  WhatsApp has no such event: the first message goes straight to the bot and the `__start__` flow doesn't run.

Conversation ids are `wa-<phone>` and `tg-<chat_id>`: the same person keeps the same conversation.

## Handoff to a person

It works the same as on the web: when a flow or the person asks for a human, the conversation shows up in the
**Inbox** and the bot stays quiet. The person's messages keep arriving there (without a bot answer); what the human
writes from the Inbox is sent through the channel. **Hand back to the bot** gives it back.

## Limits

- **WhatsApp's 24-hour window.** WhatsApp only allows free-form messages within 24 hours of the person's last
  message. After that, a message has to be an approved **template**. Writing first (the outbound API, campaigns
  and reminders) chooses the template on its own, from **Channels → WhatsApp → Approved templates**
  (`channels.whatsapp.templates`): see [outbound.md](outbound.md). From the **Inbox** (or the contact-center API)
  after 24 hours, Parla asks for one of those templates instead of sending free text: see
  [outbound.md](outbound.md#templates-from-the-inbox-and-the-contact-center).
- The duplicate filter, the per-conversation order and the status in **Channels** live in memory: they are lost on
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

- Phone: Twilio requests must carry `X-Twilio-Signature` (HMAC-SHA1 with `TWILIO_AUTH_TOKEN` of the full URL plus
  the sorted POST parameters); jambonz requests `Jambonz-Signature` (`JAMBONZ_WEBHOOK_SECRET`) and/or HTTP basic
  (`JAMBONZ_BASIC_USER` / `JAMBONZ_BASIC_PASSWORD`). Parla's audio for calls is served only with an HMAC-signed token
  that expires in 10 minutes and names the bot; the conversation id `call-<CallSid>` and the caller number
  (`caller`, if the bot has a slot with that name) are personal data.

More in [security.md](security.md#messaging-channels-whatsapp-and-telegram).

## Phone calls (Twilio and jambonz)

A bot can also answer **phone calls**, through **Twilio Programmable Voice** (hosted, the most common) or
**jambonz** (open source, self-hostable on your own SIP infrastructure). It is the same bot: each call is a
conversation `call-<CallSid>` with channel `phone`, it runs the `__start__` flow when the call is answered, and it
shows up in **Conversations** and the **Inbox** like any other.

How a call works: the provider calls Parla's webhook when the call comes in, Parla answers what to say and to
listen (`<Gather>` / `gather`), the provider transcribes what the caller says (or collects the keys pressed) and
posts it back, Parla runs a turn and answers the next step: listen again, transfer (`<Dial>` / `dial`) or hang
up (`<Hangup>` / `hangup`).

### Settings

**Channels → Phone** (`channels.phone` in the agent JSON; nothing secret goes there):

| Field | Meaning |
|---|---|
| `enabled` | Answer calls. Off, the webhooks answer 403. |
| `provider` | `twilio` (default) or `jambonz`. Only the chosen provider's webhooks are accepted. |
| `language` | Recognition and voice language variant, for example `es-AR`, `en-US`, `pt-BR`. If the conversation switches to another of the bot's languages, Parla uses `es-US`, `en-US` or `pt-BR`. |
| `tts` | `provider` (default): the provider's voice (`<Say>` / `say`). `parla`: the agent's own voice (`voice.tts`: local piper or a provider with your key, such as Deepgram Aura-2, ElevenLabs, OpenAI or Google), played from signed URLs (`<Play>` / `play`), for the same voice as the test call and no provider TTS. |
| `voice` | Provider voice name (optional): `Polly.Mia-Neural` on Twilio, the voice of the synthesizer configured in jambonz. |
| `handoff_to` | Where to transfer when the conversation goes to a person: a number (`+5491112345678`) or a SIP URI (`sip:desk@pbx.mydomain.com`). |
| `finish_on_key` | Key that ends a number typed on the keypad. Default `#`. |
| `greeting` | What to say when the call starts if the bot has no `__start__` flow. Default «Hola, ¿en qué te puedo ayudar?» in the bot's language. |
| `mode` | `turns` (default, as described here) or `stream`: live audio over WebSocket with the agent's voice, sub-second replies and barge-in. See [Real-time (stream mode)](#real-time-stream-mode). |
| `from` | **Number calls are made from**: your number at the provider, or a SIP URI. Only for outbound calls. |
| `api_url` | **jambonz API address** for outbound calls. Default `https://api.jambonz.cloud`. |
| `application_sid` | **Application SID**: the jambonz application that handles outbound calls (recommended). |

The public address is the same as for the other channels (`PARLA_PUBLIC_URL` or **Public address**).

To **place calls** (outbound API, campaigns, reminders) Parla also needs `TWILIO_ACCOUNT_SID` (with
`TWILIO_AUTH_TOKEN`) on Twilio, or `JAMBONZ_API_KEY` and `JAMBONZ_ACCOUNT_SID` on jambonz, in **Secrets**. Answering
calls doesn't need them. See [outbound.md](outbound.md#phone-outbound-calls).

### Twilio step by step

1. Create an account at [twilio.com](https://www.twilio.com) and buy a number with voice (a trial account works,
   with a notice before each call and only to verified numbers).
2. In Parla, **Channels → Phone**: turn on **Answer phone calls**, provider **Twilio**, set the language.
3. Load the account's **Auth Token** (*Console → Account Info*) in `TWILIO_AUTH_TOKEN`. Parla uses it to check the
   `X-Twilio-Signature` of every request. If you rotate it in Twilio, load the new one.
4. In Twilio, *Phone Numbers → Manage → Active numbers → your number → Voice configuration*:
   - *A call comes in*: **Webhook**, `https://bots.mydomain.com/api/v1/bots/<id>/phone/twilio`, **HTTP POST**.
   - *Call status changes*: `https://bots.mydomain.com/api/v1/bots/<id>/phone/twilio/status`.
   Copy them exactly as **Channels** shows them: the signature covers the full URL.
5. Call the number.

**Costs and privacy with Twilio:** Twilio charges per minute for the call, and for speech recognition (`<Gather
input="speech">`) and its voices; check its current pricing. **The caller's speech is transcribed by Twilio**
(and by the speech providers it uses), not by Parla: the audio and the transcript leave your server. Only the text
reaches Parla. With `tts: "parla"` the bot's answers are synthesized by the agent's voice (locally with piper, or at
the provider it uses), but recognition still happens at Twilio. If audio must not leave your infrastructure, use jambonz with a self-hosted recognizer.

### jambonz step by step

1. Have a jambonz: self-hosted ([docs.jambonz.org](https://docs.jambonz.org/)) or the hosted service, with a SIP
   trunk / carrier and a number, and a speech recognizer and synthesizer configured (*Speech services*). That's
   where you choose who transcribes and speaks: a cloud vendor, or a self-hosted one.
2. In Parla, **Channels → Phone**: turn on **Answer phone calls**, provider **jambonz**, set the language.
3. Authentication (at least one; if you load both, both have to match):
   - **Webhook signature**: copy your account's *webhook secret* (in the jambonz portal, *Account*) into
     `JAMBONZ_WEBHOOK_SECRET`. jambonz sends `Jambonz-Signature: t=<unix>,v1=<hex>`, the HMAC-SHA256 of
     `<t>.<body>`; Parla checks it in constant time and rejects signatures older than 5 minutes.
   - **HTTP basic auth**: make up a user and a long password, put them in the jambonz application and load them in
     `JAMBONZ_BASIC_USER` and `JAMBONZ_BASIC_PASSWORD`. Useful on self-hosted installs.
4. In jambonz, *Applications → Add application*:
   - *Calling webhook*: `https://bots.mydomain.com/api/v1/bots/<id>/phone/jambonz`, **POST**.
   - *Call status webhook*: `https://bots.mydomain.com/api/v1/bots/<id>/phone/jambonz/status`, **POST**.
   - Choose the speech vendors and language (Parla sends `vendor: "default"`, so the application's ones are used).
5. Point your number (*Phone numbers*) to that application and call.

### Keypad (DTMF), buttons and numbers

- When the bot's last message has **buttons**, Parla announces them in the bot's language: «Marcá 1 para
  Muzzarella, 2 para Fugazza.» / «Press 1 for …» / «Digite 1 para …» (the first 9). Pressing a key chooses that
  button, and the call waits for a single key. Saying the option out loud also works.
- When the bot **asks for a value** (a DNI, an order number), the caller can type it and end with `#`
  (`finish_on_key`): the digits go to the bot as the answer.
- **Speech hints:** the bot's entity values and synonyms, and the button labels, are sent as hints to the
  recognizer (`hints`), like the local transcription does.

### What is said on the phone

- **Voice-friendly text:** emojis, Markdown (`**bold**`, `[text](url)`, bullets, headings) and URLs are removed
  before speaking. Long answers are split by sentence into several `<Say>` / audio pieces. Keep phone texts short:
  a URL or a list of ten options doesn't work by voice.
- **Files** (`file` step): they can't be sent on a call. Parla says the step's text, if any, plus a short notice
  («Tengo un archivo para vos, pero por teléfono no lo puedo mandar.»).
- **Barge-in:** everything is said inside the `Gather` / `gather`, so the caller can interrupt by speaking or
  pressing a key (on jambonz with `bargein` and `dtmfBargein`).
- **Silence:** if nothing is heard (`actionOnEmptyResult` on Twilio, a `timeout` on jambonz), Parla repeats the
  last question; after 3 silences in a row it says goodbye and hangs up.
- **Hanging up:** an `end` step hangs up after saying what came before. When the caller hangs up, the status
  webhook ends the conversation.
- **Voices:** with `tts: "provider"`, the provider voice (`voice`) speaks; with `tts: "parla"`, the agent's voice
  (`voice.tts`) speaks the same pre-generated phrases as the test call (fixed phrases are prewarmed and play right
  away; phrases with `{{ }}` are generated when the provider downloads them, which adds a little latency).
- **Lowest latency:** `tts: "parla"` with Deepgram Aura-2 or ElevenLabs Flash as the agent's voice. Setup, keys and
  what leaves the machine in [ai-and-voice.md](ai-and-voice.md).

### Handoff on a call

When a flow or the caller asks for a person, Parla says the handoff text and transfers the call to `handoff_to`
(`<Dial>` / `dial`); the conversation stays in the **Inbox** with a «Transferida a …» event. Without `handoff_to`
Parla apologizes and hangs up (and shows the error in **Channels**). There's nothing to type on a call: in the
Inbox, **Take conversation** makes Parla transfer the call to `handoff_to` as soon as the caller stops talking.

**Transfer with context** (Channels → Handoff → Context in phone transfers): to a SIP URI, Parla can add
`X-Parla-Session`, `X-Parla-Intent`, `X-Parla-Language`, `X-Parla-Summary`, `X-Parla-Context` (lookup URL),
`X-Parla-Slot-<name>` and `User-to-User` (Twilio: in the `<Sip>` URI; jambonz: `dial.headers`). ASCII only, each
value up to 128 characters and all under 1000; nothing from the vault. To a number Twilio uses `<Dial><Number>`
(no headers). With a Twilio Flex Workflow SID, the call goes to `<Enqueue workflowSid><Task>{…}</Task></Enqueue>`
with the context as task attributes. Details in [contact-centers.md](contact-centers.md#phone-transfer-with-context).

### Phone limits

- Outbound calls (the API, campaigns and reminders) need `from`, the provider's keys and, on jambonz, `api_url` and
  `application_sid`: see [outbound.md](outbound.md#phone-outbound-calls). There is no answering machine detection.
- In turn mode speech recognition is done by the provider (Twilio, or what jambonz is configured with), not by Parla
  (neither local faster-whisper nor the agent's `voice.asr`). Turns are request/response, so each answer waits for
  the end of the caller's sentence. Stream mode lifts both (below).
- The provider waits about 15 seconds for each answer: slow AI steps or HTTP calls can make it fail. Keep them fast.
- Mid-call handoffs from the Inbox happen on the caller's next turn (or silence), not instantly.
- The silence counter and the key that signs audio URLs live in memory: a restart invalidates audio URLs being
  played (they last 10 minutes anyway), and several replicas need one shared instance (run one).
- `tts: "parla"` needs the voice extras on the server (with piper) or the voice provider's key in **Secrets**, and
  the provider has to reach the audio URLs (they are under `/api/v1/`, like the webhooks).

### Real-time (stream mode)

`"mode": "stream"` in `channels.phone`. The start webhook is the same; instead of a `<Gather>` Parla answers:

- **Twilio:** `<Connect><Stream url="wss://<public address>/api/v1/bots/{bot}/phone/twilio/stream">` (bidirectional
  Media Streams: μ-law 8 kHz) followed by `<Redirect>` to `/phone/twilio/after`. Parla validates the
  `X-Twilio-Signature` of the WebSocket upgrade (HMAC-SHA1 of the `wss://` URL with `TWILIO_AUTH_TOKEN`).
- **jambonz:** a `listen` verb to `wss://…/phone/jambonz/stream?t=<signed token>` with `sampleRate` 8000,
  `bidirectionalAudio: {enabled, streaming: true, sampleRate: 8000}` (L16 both ways), `passDtmf: true` and
  `actionHook` `/phone/jambonz/after`. The token comes from the (signed) webhook and lasts 10 minutes; with
  `JAMBONZ_BASIC_USER`/`PASSWORD` the verb also carries `wsAuth` and Parla checks it.

From then on the audio is Parla's: the agent's `voice.asr` (Deepgram live recommended) and `voice.tts`, reply from
the first sentence, barge-in (`clear` / `killAudio`), keys pressed (`dtmf` events: a menu key answers at once, a
number ends with `finish_on_key` or 2 s without keys), re-prompt after `voice.stream.idle_seconds` of silence. To
transfer or hang up Parla lets the last sentence play, closes the stream (jambonz: `disconnect`) and the provider
requests `/after`, which answers `<Dial>`/`dial` (same SIP headers and Flex as turn mode) or `<Hangup>`. Details and
latency in [ai-and-voice.md](ai-and-voice.md#real-time-voice).

- Behind a proxy, allow WebSocket upgrades on `/api/v1/` with long read timeouts (see [deployment.md](deployment.md)).
- `tts`, `voice` and `language` of the provider don't apply in stream mode (Parla speaks).
- The greeting and what follows the stream live in memory per call: the call has to stay on the same replica.

## Testing without real accounts

`tests/test_channels.py` runs everything against fake Graph and Telegram APIs on a local port. The base URLs of those
APIs can be changed with `PARLA_WHATSAPP_API` (default `https://graph.facebook.com/v21.0`) and
`PARLA_TELEGRAM_API` (default `https://api.telegram.org`). Only change them for tests. `tests/test_outbound.py`
also fakes Twilio (`PARLA_TWILIO_API`) and jambonz (`channels.phone.api_url`) for outbound calls.

`tests/test_phone.py` sends fake signed Twilio and jambonz requests (first turn, speech, keys, handoff, hang-up,
silence, signatures, signed audio URLs) without contacting either provider. To try a real call from your computer,
expose Parla with a tunnel (`cloudflared tunnel --url http://127.0.0.1:8000`), set that address as the public
address and paste the webhooks into Twilio or jambonz.
