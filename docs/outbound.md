# Outbound messages, campaigns and reminders

**English** · [Español](outbound_es.md)

Usually the person writes first and the bot answers. With outbound messaging **the bot writes first**: a reminder of
tomorrow's appointment, a satisfaction survey after a purchase, a notice that an order shipped, or a call to
confirm a visit. There are three ways to do it:

- **The outbound API** (`POST /api/v1/bots/{bot}/outbound`): your system asks Parla to message (or call) one person
  now. Good for notifications triggered by an event in your CRM or backend.
- **Campaigns** (**Operate → Campaigns**): upload a CSV with a list of people, choose what to send, when and how
  fast, and watch the results. Good for many people at once.
- **Reminders** (the `remind` step in a flow): the bot schedules a message to the same person for later, for
  example «24 hours before the appointment».

All three work on **WhatsApp**, **Telegram** and the **phone** (an outbound call); the API and reminders also work
on the **web widget**. In every case it is a normal production conversation: the data you send is preloaded into the
slots, a flow runs, and when the person answers, the conversation continues as if they had written first. Opt-outs
(«STOP», «BAJA») are respected everywhere.

Before you start, read [Consent and the law](#consent-and-the-law): writing to people who didn't ask for it gets
numbers blocked and can be illegal.

## How it works

- **Same conversation as an inbound message.** The conversation id is the one the person would get by writing:
  `wa-<phone>` on WhatsApp, `tg-<chat_id>` on Telegram, `call-<CallSid>` for a call, and the widget's own
  `sessionId` on the web. When the person replies, it lands in that same conversation, with the slots already
  filled.
- **A fresh start.** Sending starts the conversation again, like a `start` event: the memory (slots, current flow)
  is reset, the history is kept, and the `data` you send goes into the slots with the same name (other keys are
  ignored). `idioma`, `language` or `lang` choose the language, as in `start`.
- **Production only.** It always uses the version published in **Production** (or the draft, if nothing is
  published). A `flow` must exist there.
- **Which flow.** `flow` names the flow to run. Without it, the `__start__` flow runs (on WhatsApp you need a
  template instead, see below). On WhatsApp outside the 24-hour window, the flow runs **when the person replies**
  to the template.
- **Refused** if the person opted out (409), if a person from the team is handling that conversation in the
  **Inbox** (409), or if the channel is off in **Channels** (400).
- **The queue.** Campaigns and reminders go through a queue stored in `parla.db` (table `campaign_recipients`). A
  background thread checks it every second, respecting each campaign's rate and quiet hours. What is queued
  survives a restart.

## The outbound API

`POST /api/v1/bots/{bot}/outbound`

**Authentication:** an API key (`Authorization: Bearer parla_…`) or the session cookie of a user with the `owner`
or `editor` role. Without either: 401; `analyst` and `agent` (support) get 403. It is never public, even with the
widget on. As long as no user exists, it is open like the rest of the API (see
[api.md](api.md#authentication-and-roles)).

**Body:**

| Field | What it is |
|---|---|
| `channel` | `whatsapp` (default), `telegram`, `phone` or `web`. |
| `to` | WhatsApp and phone: the number with country code (`+5491112345678`; spaces, dashes, dots, parentheses and `+` are removed; 6 to 15 digits). Telegram: the chat id (a number). Web: the `sessionId` of an existing widget conversation. |
| `data` | Optional object: values for the slots (`{"nombre": "Ana", "fecha": "2026-12-01"}`). They are also the values for the template placeholders. |
| `flow` | Optional: the name of the flow to run (it must exist in Production). |
| `template` | WhatsApp only, optional: the name of a template from the catalog (`"recordatorio_turno"`) or an object `{"name", "language"?, "params"?, "components"?}`. See [WhatsApp](#whatsapp-the-24-hour-window-and-templates). |

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

| Field | What it is |
|---|---|
| `id` | The send's row in the queue. |
| `sessionId` | The conversation (`wa-…`, `tg-…`, `call-…` or the widget's). Read it with `GET /api/v1/bots/{bot}/sessions/{sessionId}`. |
| `via` | `message` (the flow's messages were sent as normal messages), `template` (a WhatsApp template was sent; the flow runs when the person replies) or `call` (a call was placed). |
| `messages` | What the bot said (text), for `via: "message"`. Empty for templates and calls. |
| `message_id` | The channel's id: the WhatsApp `wamid` (of the last message), the Telegram `message_id`, or the call's SID. `null` on the web. |
| `channel`, `to` | The channel and the normalized recipient. |
| `status` | `sent`: the channel accepted it. Delivery comes later (see [delivery statuses](#delivery-statuses)). |

**Errors** (`{"error": "…"}`, in the language of `Accept-Language`):

| Status | When |
|---|---|
| 400 | Bad `to`, `data` that isn't an object, a `flow` that doesn't exist, the channel is off, a Telegram chat that never wrote, no web conversation with that id, a template without the data for its placeholders, a missing key or setting (`WHATSAPP_TOKEN`, `phone_number_id`, `channels.phone.from`, Twilio or jambonz keys, a public `https://` address), or nothing to send. |
| 401, 403 | No key or session; the role can't send (analyst, support). |
| 409 | WhatsApp outside the 24-hour window (or a person who never wrote) without a `template`; the person opted out; a person from the team is handling the conversation. |
| 429 | More than `api_per_minute` sends in the last minute for this agent (default 30, `agent.outbound.api_per_minute`). For many people, use a campaign. |
| 502 | The channel rejected it or didn't answer (Meta, Telegram, Twilio, jambonz). The message explains it when the error code is known (see [Meta errors](#meta-errors)). |

API sends are not retried: if it fails, your system decides whether to try again.

## WhatsApp: the 24-hour window and templates

WhatsApp only allows free-form messages within **24 hours of the person's last message** (the *customer service
window*). Outside it, or to someone who never wrote, the only thing you can send is a **template** approved by Meta.

Parla records the time of the person's last message in each conversation and **chooses on its own**:

- **Inside the window** and with a `flow` (or a reminder text): the flow's messages are sent as normal messages
  (`via: "message"`). The template, if any, isn't used.
- **Outside the window**, or with no `flow`: the `template` is sent (`via: "template"`). If there is a `flow`, it
  runs **when the person replies** to the template (any reply, including tapping a quick-reply button). Without a
  template: 409.

### The template catalog

Templates are created and approved in Meta (*WhatsApp Manager → Message templates*), not in Parla. In Parla you
only name them, in **Channels → WhatsApp → Approved templates** (`channels.whatsapp.templates` in the agent JSON):

```json
"channels": {"whatsapp": {"enabled": true, "phone_number_id": "1234567890",
  "templates": [{"name": "recordatorio_turno", "language": "es_AR", "params": ["nombre", "fecha"]}]}}
```

| Field | What it is |
|---|---|
| `name` | The exact name in Meta: lowercase letters, digits and `_`. |
| `language` | The template's language code in Meta (`es`, `es_AR`, `en_US`, `pt_BR`…). Without it: `es`, `en_US` or `pt_BR` from the bot's first language. |
| `params` | The slots that fill the body placeholders, in order: the first one goes to `{{1}}`, the second to `{{2}}`… |

If the body of `recordatorio_turno` is «Hola {{1}}, te recordamos tu turno del {{2}}. ¿Confirmás?», sending with
`data: {"nombre": "Ana", "fecha": "1/12 a las 10"}` fills it in. A missing value is a 400 before anything is sent.
Values are cut at 1024 characters.

In the API, `template` can override the catalog: `{"name": "recordatorio_turno", "language": "es", "params":
["nombre"]}`, or bring raw Cloud API `components` (for header variables, buttons with parameters or media), which
are sent as they are instead of `params`.

### Meta errors

When Meta answers with an error, Parla translates the known codes and decides whether to retry:

| Code | Meaning | Retried |
|---|---|---|
| 131047 | More than 24 hours since the person's last message: only a template is allowed. | No |
| 131026 | The message couldn't be delivered (does that number have WhatsApp?). | No |
| 131050 | The person stopped marketing messages from this business on WhatsApp. | No |
| 132000 | The number of values doesn't match the template's placeholders: check `params`. | No |
| 132001 | The template doesn't exist in that language or isn't approved yet. | No |
| 132005 | The template text with the values is too long. | No |
| 132007 | The template breaks WhatsApp's policies. | No |
| 132012 | A value doesn't have the format the template expects. | No |
| 132015 | The template is paused for low quality. | No |
| 132016 | The template is disabled. | No |
| other 132xxx | WhatsApp rejected the template. | No |
| 4, 80007, 130429, 131048, 131056 | Rate limits: go slower. | Yes |
| no answer, 429, 5xx | Network or Meta trouble. | Yes |

Retries apply to campaigns and reminders (see [retries](#retries-and-restarts)). The error shows in the
recipient's row, in **Channels → Last error** and in the console (with numbers masked).

### Delivery statuses

Meta reports what happened to each message (`sent`, `delivered`, `read`, `failed`) on the same webhook. Parla
uses those statuses to update each recipient: a late `delivered` never overwrites a `read`, and `failed` brings
the reason (the codes above). **In Meta, the webhook must be subscribed to the `messages` field** (the same one
used to receive messages; statuses come with it). Without it, recipients stay as `sent` until they reply.

When a send is several messages (a flow that says three things), only the last message's status is followed.

## Telegram

Telegram only lets a bot write to people who **started a chat with it** (or didn't block it). `to` is the chat id,
the number in `tg-<chat_id>`: you find it in **Conversations**, or in your own system if you stored it. Writing
to a chat that never talked to the bot is refused before calling Telegram (400); a person who blocked the bot
gives an error that isn't retried.

There is no window and no templates: the flow runs and its messages go out right away. Telegram doesn't report
deliveries or reads, so a Telegram recipient goes from `sent` to `replied` (or stays `sent`).

## Phone: outbound calls

With `channel: "phone"`, Parla asks your provider to **place a call**. When the person answers, the call works
like an inbound one: the provider calls Parla's usual webhook, and the bot runs the `flow` (or `__start__`) with the
preloaded data. If the bot has a slot named `caller`, it gets the number that was called (the person), like the
caller's number on an inbound call.

Setup, in **Channels → Phone**, besides what inbound calls need ([channels.md](channels.md#phone-calls-twilio-and-jambonz)):

| Setting | Where | What it is |
|---|---|---|
| **Number calls are made from** | `channels.phone.from` | Your number at the provider (`+5491112345678`) or a SIP URI. |
| Public address | `PARLA_PUBLIC_URL` or **Public address** | Must start with `https://`: the provider needs it to call back. |
| Twilio keys | **Secrets** | `TWILIO_ACCOUNT_SID` (`AC…`) and `TWILIO_AUTH_TOKEN`. |
| jambonz keys | **Secrets** | `JAMBONZ_API_KEY` (an API key of the account) and `JAMBONZ_ACCOUNT_SID`. |
| **jambonz API address** | `channels.phone.api_url` | Default `https://api.jambonz.cloud`; your server's address if it's self-hosted. |
| **Application SID** | `channels.phone.application_sid` | The jambonz application that handles the call. Recommended: without it, jambonz asks for the speech vendor fields in the request, which Parla doesn't send. |

What Parla sends:

- **Twilio:** `POST https://api.twilio.com/2010-04-01/Accounts/{TWILIO_ACCOUNT_SID}/Calls.json` with Basic auth
  (`TWILIO_ACCOUNT_SID:TWILIO_AUTH_TOKEN`), `To`, `From`, `Url` (the `…/phone/twilio` webhook) and `StatusCallback`
  (the `…/phone/twilio/status` webhook, events `initiated`, `ringing`, `answered`, `completed`).
- **jambonz:** `POST {api_url}/v1/Accounts/{JAMBONZ_ACCOUNT_SID}/Calls` with `Authorization: Bearer
  {JAMBONZ_API_KEY}`, `from`, `to`, `call_hook` and `call_status_hook` (the `…/phone/jambonz` webhooks, with
  `JAMBONZ_BASIC_USER` / `JAMBONZ_BASIC_PASSWORD` if loaded) and `application_sid` if set.

Both webhook URLs carry `?o=<token>`: a random token that tells Parla which send it is (data, flow, campaign). The
provider's signature covers the full URL, token included. When the person answers, the recipient goes to
`delivered`; `busy`, `no-answer`, `failed` or `canceled` mark it as `failed` («no atendió»). An unanswered call isn't
retried.

Parla doesn't detect answering machines: if voicemail picks up, the bot talks to it. Keep the first message short
and say who is calling.

## Web widget

With `channel: "web"`, `to` is the `sessionId` of a conversation that already exists on the widget (channel `web`).
The flow's messages are added to that conversation; the widget shows them on its next poll
(`GET …/sessions/{sessionId}/messages?after=`), like an Inbox reply. There is no push: if the page is closed, the
messages wait in the conversation. Use it for «your order is ready» while the person still has the page open.

## Campaigns

A **campaign** sends the same thing to a list of people, at a controlled rate. In the UI: **Operate → Campaigns**,
tabs **Campaigns** and **Opt-outs**. **New campaign** walks you through:

1. **Name and channel**: WhatsApp, Telegram or phone (campaigns don't use the web widget).
2. **What is sent**: on WhatsApp an **Approved template** and, optionally, a **Flow when they reply**; on Telegram
   and phone the flow that runs with each person.
3. **Who**: a **CSV spreadsheet**. The first row is the header.
4. **When and how fast**: right away or at a date and time, the time zone, the rate, and quiet hours.
5. **What counts as success (optional)**: what turns a conversation into a conversion.

The template is required on WhatsApp (the API refuses a WhatsApp campaign without one), and the flow has to exist
in what's published in Production, since that is what runs.

It is created as a **draft**: you see how many people were loaded, duplicated, invalid or opted out, and then press
**Start**.

### The CSV

```csv
telefono;nombre;fecha
+5491112345678;Ana;1/12 a las 10
+5491187654321;Tomás;1/12 a las 11:30
```

- Comma or semicolon (whichever appears more in the header), UTF-8 (with or without BOM).
- Each column is used as the **recipient** (`to`), as a **slot** of the bot (its value is preloaded and fills the
  template), or ignored. Parla guesses: a column named `to`, `phone`, `telefono`, `teléfono`, `numero`, `número`,
  `celular`, `whatsapp`, `chat_id`, `chat` or `destinatario` is the recipient, and a column named like a slot
  (case-insensitive) goes to that slot. You can change it; exactly one column must be the recipient.
- Numbers with country code (`+5491112345678`); on Telegram, chat ids.
- Repeated recipients are loaded once (`duplicates`), rows with an unusable recipient are skipped (`invalid`),
  and people who opted out are skipped (`opted_out`).
- At most **10,000 recipients** per campaign. Change it per agent with `agent.outbound.max_recipients` or for the
  server with `PARLA_CAMPAIGN_MAX`. A load that goes over the limit is refused as a whole.
- You can add more people to a campaign that isn't finished (`POST …/recipients`).

### Schedule, rate and quiet hours

- **Start:** right away, or `schedule.at` (`2026-12-01T10:00`) in `schedule.timezone` (an IANA zone such as
  `America/Argentina/Buenos_Aires`; default `UTC`, the UI proposes the browser's). Until then the campaign is
  running but **waiting** (`waiting: "schedule"`).
- **Rate:** `rate: {"count": 20, "per": "minute"}` by default; from 1 per minute to 50 per second (3,000 per
  minute). Going slowly protects the number's reputation: WhatsApp lowers the quality rating (and the limits) of
  numbers that people block or report, and carriers flag numbers that call too fast.
- **Quiet hours:** `quiet_hours: {"start": "21:00", "end": "09:00"}`, in the campaign's time zone. A range that
  crosses midnight works. During quiet hours nothing is sent (`waiting: "quiet_hours"`) and it continues when
  they end. The UI turns 21:00–09:00 on by default; the API has none unless you set it.

### Statuses

| Campaign | Meaning |
|---|---|
| `draft` | Created, not started. It can be edited, filled and deleted. |
| `running` | Sending. `waiting` says if it is waiting for the start time (`schedule`) or for quiet hours to end (`quiet_hours`). |
| `paused` | Stopped; nothing is sent until **Resume**. It can be edited. |
| `done` | Nothing left in the queue. |
| `canceled` | Canceled: whoever wasn't sent to yet won't be. It can't be resumed. |

Actions: **Start** (`draft` → `running`; needs recipients and the channel on), **Pause** (`running` →
`paused`), **Resume** (`paused` → `running`), **Cancel** (from `draft`, `running` or `paused`). Editing
(`PUT`) is only for `draft` or `paused`, and the channel can't change. Deleting needs it not to be `running`; it
deletes the recipients and their results too.

| Recipient | Meaning |
|---|---|
| `queued` | Waiting for its turn (or for a retry). |
| `sending` | Being sent right now. |
| `sent` | The channel accepted it. |
| `delivered` | It reached the phone (WhatsApp), or the call was answered. |
| `read` | The person read it (WhatsApp, if they have read receipts on). |
| `replied` | The person answered. |
| `failed` | It couldn't be sent; `error` says why. |
| `opted_out` | The person had opted out, or did it while it was queued. |
| `canceled` | The campaign was canceled before it was sent. |

### Retries and restarts

- A send that fails for a reason that can pass (no connection, 429, 5xx, WhatsApp's rate limits) is retried up to
  **3 attempts** in total, waiting 30 seconds and then 60. Errors that won't change (a wrong template, a number
  without WhatsApp, an opt-out) fail right away.
- Everything is stored in `parla.db`, so a restart picks up where it left off: queued rows, schedules and
  reminders continue.
- A row that was **being sent** when the process stopped is marked `failed` («se cortó por un reinicio») instead
  of sent again: Parla can't know whether it went out, and a duplicate is worse than a miss. Export the results to
  retry those by hand.

### Results and conversions

The campaign shows how many were sent, delivered, read, replied, failed and opted out, refreshed every 3 seconds
while it runs, and the list of recipients with a filter by status and **View conversation**. **Export CSV** downloads
`to, status, error, attempts, sent_at, updated, sessionId` plus each person's data.

**Conversions** count the campaign's conversations that reached a goal (`conversion`, optional; with several
fields, any of them counts):

| Field | Counts when |
|---|---|
| `classification` | The conversation got that classification (a `classify` step). |
| `intent` | The person said something with that intent. |
| `flow` | The person wrote while that flow was running. |
| `csat` | The satisfaction score was at least that (1–5). |

Every conversation a campaign starts is tagged with the campaign id (`campaign` in the conversation, and in each
reminder it schedules). **Reports** has a campaign filter, and the API accepts `?campaign=<id>` on
`GET /api/v1/bots/{bot}/sessions` and `/report`, and on the analytics routes.

### Admin routes

The UI uses these internal routes (`{id}` is the agent's id, `{c}` the campaign's 12-character id). Owner and editor
can use all of them; analyst only the `GET`s; support none. More in [api.md](api.md#campaigns-and-opt-outs).

| Route | Body | Response |
|---|---|---|
| `GET /api/agents/{id}/campaigns` | — | `{"campaigns": [campaign]}`, newest first. |
| `POST /api/agents/{id}/campaigns` | `{"name", "channel", "flow"?, "template"?, "schedule"?: {"at", "timezone"}, "rate"?: {"count", "per"}, "quiet_hours"?: {"start", "end"}, "conversion"?, "csv"?, "mapping"?, "recipients"?}` | The campaign (in `draft`) plus `imported: {"added", "duplicates", "invalid", "opted_out"}`. |
| `POST /api/agents/{id}/campaigns/preview` | `{"csv"}` | `{"columns", "rows"` (first 5), `"count", "mapping"` (the guess)`}`. Saves nothing. |
| `GET /api/agents/{id}/campaigns/{c}` | — | The campaign. |
| `PUT /api/agents/{id}/campaigns/{c}` | Same fields as creating (what you don't send stays) | The campaign. Only `draft` or `paused` (otherwise 409). |
| `DELETE /api/agents/{id}/campaigns/{c}` | — | `{"deleted"}`. Not while `running` (409). |
| `GET /api/agents/{id}/campaigns/{c}/recipients?status=&limit=&offset=` | — | `{"total", "recipients": [{"id", "to", "data", "status", "error", "attempts", "updated", "sent_at", "sessionId"}]}`. `limit` 1 to 500, default 50. |
| `POST /api/agents/{id}/campaigns/{c}/recipients` | `{"csv", "mapping"?}` or `{"recipients": ["+549…", {"to", slot: value}]}` | The campaign plus `imported`. Not for `done` or `canceled` (409). |
| `POST /api/agents/{id}/campaigns/{c}/start\|pause\|resume\|cancel` | — | The campaign. 409 if its status doesn't allow it. |
| `GET /api/agents/{id}/campaigns/{c}/export` | — | The CSV (`text/csv`, as an attachment). |
| `GET /api/agents/{id}/optouts` | — | `{"optouts": [{"address", "channel", "keyword", "at"}]}` |
| `POST /api/agents/{id}/optouts` | `{"address", "channel"?}` | Adds an opt-out by hand; returns the list. |
| `DELETE /api/agents/{id}/optouts` | `{"address"}` | Removes it; returns the list. |

A campaign (`campaign` above) is `{"id", "name", "channel", "status", "waiting", "created", "updated",
"created_by", "flow", "template", "schedule", "rate", "quiet_hours", "conversion", "stats"}`; `stats` has a count
per recipient status plus `total` and `conversions`.

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

## Reminders: the `remind` step

A flow can schedule a message to the same person for later. In the flow editor it is **Schedule a reminder**.

```json
{"type": "remind", "after": "24h", "flow": "Recordatorio", "template": "recordatorio_turno"}
{"type": "remind", "at": "{{ fecha }} 09:00", "text": "Hola {{ nombre }}, te esperamos hoy a las {{ hora }}."}
```

| Field | What it is |
|---|---|
| `after` | How long from now: a number and `m`, `h` or `d` (`30m`, `24h`, `2d`). |
| `at` | A date and time, with templates, that ends up as `YYYY-MM-DD HH:MM` (`"{{ fecha }} 09:00"`). In `agent.outbound.timezone` (for example `America/Argentina/Buenos_Aires`), or the server's time zone without it. Use one of `after` or `at`. |
| `flow` | The flow the reminder runs. |
| `text` | A message instead of a flow (templates allowed, with `translations`). One of `flow` or `text` is required. |
| `template` | WhatsApp: the template from the catalog to use if the reminder goes out more than 24 hours after the person's last message. |

- It goes to the **same person on the same channel**: WhatsApp, Telegram or the web widget. On a phone call it
  calls back the number in the `caller` slot (so the bot needs a slot named `caller`).
- When it goes out, the conversation starts again with the **slots it had when the reminder was scheduled**
  preloaded, and runs `flow` (or sends `text`). The WhatsApp window rule applies: within 24 hours it goes as a
  normal message; after that it needs `template`, or it fails. `validate_agent` warns about a reminder without a
  template when WhatsApp is on.
- If the time already passed, nothing is scheduled (the trace says so). It isn't sent from the **test chat** or
  from API conversations (`channel: "api"`): the history shows «no se envía desde este canal».
- The history shows «Recordatorio programado para …». Reminders are queued in `parla.db`, survive restarts, follow
  the retries above, respect opt-outs, and keep the campaign tag if the conversation came from a campaign.
- Schedule one reminder per thing (one per appointment, not one on every message).

## Opt-out

When someone answers with an opt-out keyword, Parla records it, answers with a confirmation and the bot doesn't run
for that message. From then on no API send, campaign or reminder reaches that person on that bot; queued rows for
them become `opted_out`.

- **Default keywords:** Spanish `stop`, `baja`, `no me escriban`, `no me escribas`, `desuscribir`; English
  `stop`, `unsubscribe`, `opt out`; Portuguese `parar`, `sair`, `descadastrar`. All languages are checked, whatever
  the conversation's language.
- **How they match:** case, accents and punctuation don't matter. A **single word** must be the whole message
  («STOP», «baja.»), so «no quiero darme de baja del plan» doesn't opt out. A **phrase** counts anywhere in the
  message («por favor no me escriban más»).
- **Your own keywords:** `agent.outbound.optout_keywords`, for example `{"es": ["baja", "no molestar"]}`; each
  language you set replaces that language's defaults (an empty list turns that language off). In the UI:
  **Campaigns → Opt-outs → Opt-out keywords** (empty uses the defaults).
- **Confirmation:** «Listo, no te vamos a escribir más. Si cambiás de idea, escribinos cuando quieras.» (or the
  English or Portuguese version, by conversation language). The person can keep writing to the bot; only outbound
  stops.
- **By hand:** **Opt-outs → Add manually** (a number or chat id), and the trash icon removes one. Only remove an
  opt-out when the person asked for it.
- Keywords work on WhatsApp, Telegram and the web widget. On phone calls there is no keyword: add the number by
  hand when someone asks not to be called.
- Opted-out people are skipped when loading a campaign, and the API answers 409.

## Rate limits

| What | Limit |
|---|---|
| Outbound API | `agent.outbound.api_per_minute` sends per minute per agent (default 30); 429 above it. |
| Campaign rate | `rate`, from 1 per minute to 50 per second; default 20 per minute. Up to one second of burst. |
| Recipients per campaign | 10,000 (`agent.outbound.max_recipients` or `PARLA_CAMPAIGN_MAX`). |
| Retries | 3 attempts, 30 s and 60 s apart (campaigns and reminders). |

Meta and the phone providers have their own limits (messaging tiers, calls per second): stay below them.

## Security and privacy

- **Roles:** `owner` and `editor` send (API, campaigns, opt-outs); `analyst` sees campaigns, results, opt-outs and
  the export, read-only; `agent` (support) sees none of it. Users limited to some bots only see those bots'
  campaigns.
- **Audit log:** `outbound.send` (channel and masked number), `campaign.create` (with how many were loaded),
  `campaign.update`, `campaign.delete`, `campaign.recipients`, `campaign.start`, `campaign.pause`,
  `campaign.resume`, `campaign.cancel`, `optout.add` and `optout.remove` (masked number). See
  [security.md](security.md#audit-log).
- **Masking:** numbers are masked in the audit log and in the console (`549••••••5678`). The UI and the admin API
  show them whole to whoever can see the bot.
- **Retention:** with `retention_days` (or `PARLA_RETENTION_DAYS`), the recipients (numbers and data) of campaigns
  that finished or were canceled more than that many days ago are deleted, keeping the campaign's totals. Rows of
  old API sends and reminders are deleted too. Conversations follow their own retention.
- **`pii_redaction`:** after a row is sent (campaign, reminder or API send), its data is masked with the agent's categories.
  The conversation's history is masked like any other.
- Deleting the agent deletes its campaigns, queue and opt-outs.
- Outbound calls are matched by a random token in the webhook URL, covered by the provider's signature.

## Consent and the law

This is informational, not legal advice. Rules depend on the country and the channel; check with someone who knows
yours.

- **Consent (opt-in).** Message only people who agreed to receive messages from you on that channel, and keep a
  record of when and how. WhatsApp's [Business Messaging Policy](https://business.whatsapp.com/policy) requires it,
  and so do privacy laws such as the GDPR (Europe), the LGPD (Brazil) and Argentina's Ley 25.326 de Protección de
  Datos Personales.
- **WhatsApp templates.** Meta classifies templates as *marketing*, *utility* or *authentication*, with different
  prices and rules; marketing messages can be limited or blocked by the person (error 131050). Use utility templates
  for reminders and notices, and keep marketing to people who opted in to it.
- **Calls.** Automated and prerecorded calls are regulated in many places (for example the TCPA in the United
  States) and many countries have *do-not-call* registries (in Argentina, the Registro Nacional «No Llame»).
  Check your list against them before a phone campaign.
- **Quiet hours.** Don't message or call at night or at times the law forbids. Use `quiet_hours` and the right time
  zone.
- **Say who you are** in the first message or the first sentence of the call, and why you are writing.
- **Make it easy to leave.** Mention the opt-out keyword («Respondé BAJA si no querés recibir más mensajes») and
  honor it. Parla does the second part on its own.

## Trying it

**Without real accounts:** `tests/test_outbound.py` runs everything against fake servers on a local port: WhatsApp
(`PARLA_WHATSAPP_API`), Telegram (`PARLA_TELEGRAM_API`), Twilio (`PARLA_TWILIO_API`, default
`https://api.twilio.com`) and jambonz (`channels.phone.api_url`). Only change those variables for tests.

**With real accounts:**

- **WhatsApp:** the channel working ([channels.md](channels.md#whatsapp-cloud-api)), the webhook subscribed to
  `messages`, and at least one template approved in Meta and loaded in **Approved templates**. With Meta's test
  number you can only write to the recipients you added in *API Setup*; the `hello_world` template is approved
  there from the start (`"language": "en_US"`, no params).
- **Telegram:** the channel connected, and the chat id of someone who already wrote to the bot.
- **Phone:** the channel working, a public `https://` address, **Number calls are made from**, and the Twilio
  (`TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`) or jambonz (`JAMBONZ_API_KEY`, `JAMBONZ_ACCOUNT_SID`, **Application
  SID**) keys. A Twilio trial account only calls verified numbers and plays a notice first.
- Start with a campaign of one: your own number.

## Limits

- **One process.** The queue uses a global lock and the rate state (campaign rate, API per-minute counter) lives in
  memory: run a single replica (see [deployment.md](deployment.md)). A restart resets the per-minute counter.
- **No answering machine detection** on outbound calls.
- **Templates:** only body placeholders from `params`; headers, buttons with variables or media need raw
  `components` in the API (the UI and the catalog don't edit them).
- **Telegram** doesn't report deliveries or reads.
- **Delivery status** follows only the last message of a send with several messages.
- **One time zone per campaign** (no per-recipient time zone), and one per agent for reminders.
- The delivery status of single API sends is stored but not exposed by any route yet: use a campaign to follow
  each recipient.
- An **Inbox** reply after 24 hours on WhatsApp still fails (error 131047): the Inbox sends free text, not
  templates. Use the outbound API with a template.
