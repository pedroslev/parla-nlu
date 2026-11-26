# External contact centers

**English** · [Español](contact-centers_es.md)

For companies that already have their own contact center (Genesys, Twilio Flex, Five9, Zendesk, Salesforce…) and
won't answer from Parla's Inbox. Parla keeps the bot; when the conversation goes to a person, it notifies the
contact center with a signed webhook, stays silent, and the contact center replies, returns or closes the
conversation through the API. Phone calls are transferred with the context in SIP headers (or as a Flex task).

> The platform recipes below are based on each vendor's public docs. They are not certified connectors: menu
> names and APIs change, so check them against your account and edition. Links are at the end of each recipe.

## Setup (Channels → Handoff)

| Field | What it does |
| --- | --- |
| **Who handles it** (`handoff.mode`) | `inbox` (Parla's Inbox, the default), `external` (the external contact center: the Inbox only shows it, read-only, with the badge «In the external contact center»), `both`. |
| **If nobody accepts it within** (`timeout_minutes`) | Minutes until an `external`/`both` handoff that nobody accepted goes back to the bot (`on_timeout: "bot"`) or closes (`"close"`). `0` = wait forever. |
| **Queue or destination** (`target`) | Free text that goes in the webhook (`handoff.target`), for routing on the CC side. |
| **Messages included in the context** (`last_messages`) | How many recent messages go in the webhook and lookup (default 10, max 50). |
| **Webhooks** (`webhooks`) | `[{url, events, secret_name}]`. `secret_name` is a key in **Secrets** used to sign. |
| **Context in phone transfers** (`handoff.phone`) | SIP headers, slots as headers, User-to-User and the Twilio Flex Workflow SID (see [Phone](#phone-transfer-with-context)). |

Owner or editor configures it (every change is audited as `handoff.update`). It applies immediately, without
publishing (like data retention).

```json
"handoff": {"mode": "external", "timeout_minutes": 15, "on_timeout": "bot", "target": "support",
            "phone": {"headers": ["session", "intent", "language", "summary", "context_url"], "slots": ["dni"], "uui": true}},
"webhooks": [{"url": "https://cc.example.com/parla", "events": ["handoff.requested", "handoff.released", "conversation.ended"],
              "secret_name": "CC_WEBHOOK_SECRET"}]
```

## The pattern

1. The bot hands off (a `handoff` step or «I want to talk to a person»). The conversation is marked `handoff`
   with `mode`, `reason`, `target` and a one or two line `summary` (made by the agent's AI if AI is on; otherwise
   intent + slots). The bot stops answering that conversation.
2. Parla sends `handoff.requested` to your webhook with the context (below).
3. The contact center creates a task/ticket/interaction with that context.
4. An agent accepts it: `POST …/handoff {"action": "accept", "agent_name": "Ana"}`.
5. They reply: `POST …/messages {"text": "…"}` (Parla delivers it through the conversation's channel). On the
   phone, the call arrives with SIP headers (`X-Parla-Session`…) and the agent opens the context with the lookup.
6. They return it to the bot (`release`, optionally with `data` for the slots and a `flow` to run) or close it
   (`close` with `resolution`). Parla sends `handoff.released` / `conversation.ended`.

If nobody accepts it within `timeout_minutes`, Parla does the `release`/`close` itself.

## Webhook events

`handoff.requested`, `handoff.released`, `conversation.started`, `conversation.ended`, `message.user` and
`message.bot` (opt-in: one per message), `csat.received`, `campaign.finished`. «Send test event» sends `test`.

```json
{"id": "evt_3f2a…", "type": "handoff.requested", "created": "2026-11-26T14:03:11Z",
 "agent": {"id": "a1b2c3d4", "name": "Support"}, "sessionId": "wa-5491112345678", "channel": "whatsapp",
 "customer": {"channel": "whatsapp", "address": "5491112345678"}, "language": "es", "intent": "complaint",
 "flow": null, "slots": {"dni": "30123456", "product": "router"},
 "handoff": {"active": true, "mode": "external", "reason": "complaint", "since": "2026-11-26T11:03:11",
             "by": null, "summary": "Wants to file a complaint about the router; already gave their ID.", "target": "support"},
 "ended": false, "messages": [{"from": "user", "text": "…", "at": "…"}, {"from": "bot", "text": "…", "at": "…"}],
 "links": {"session": "https://bots.example.com/api/v1/bots/a1b2c3d4/sessions/wa-5491112345678",
           "messages": "…/messages", "handoff": "…/handoff", "lookup": "…/lookup?sid=wa-5491112345678"}}
```

Extra fields: `text` (`message.*`), `score` (`csat.received`), `released_by` (`handoff.released`), `resolution`
(`conversation.ended`), `campaign` (`campaign.finished`, without session fields). With **personal data
redaction** on, `customer.address` is masked and `slots`, `messages` and `text` are redacted. The `sessionId` of
WhatsApp/Telegram (`wa-<phone>`, `tg-<chat>`) is how the API finds the conversation and is not masked.
`links` use the public address (Channels → Public address or `PARLA_PUBLIC_URL`).

### Delivery

- Headers: `Parla-Signature: t=<unix>,v1=<hex HMAC-SHA256 of "t.body">`, `Parla-Event`, `Parla-Delivery`.
- One SQLite queue (`webhook_deliveries`), survives restarts. Any non-2xx (or no answer in 10 s, or a redirect)
  is retried: 30 s, 1, 2, 4… minutes up to 4 h between attempts, 14 attempts (~24 h), then **dead**. Channels →
  Handoff → **Latest deliveries** shows status and response code, with **Retry**.
- Order: events of the same conversation to the same webhook go one at a time, in order (a failing one holds the
  next ones of that conversation, not others).
- At least once: a restart in the middle sends it again. **Deduplicate by `id`.**
- Delivered and dead rows are deleted after 30 days.

### Verifying the signature

Use the raw body (before parsing JSON), reject old timestamps (replay) and compare in constant time.

```python
import hashlib, hmac, time

def verify(secret: str, header: str, raw: bytes, tolerance=300) -> bool:
    parts = dict(p.split("=", 1) for p in header.split(","))
    expected = hmac.new(secret.encode(), parts["t"].encode() + b"." + raw, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, parts["v1"]) and abs(time.time() - int(parts["t"])) < tolerance
```

```js
const crypto = require('crypto');
function verify(secret, header, raw /* Buffer */, tolerance = 300) {
  const parts = Object.fromEntries(header.split(',').map((p) => p.split('=', 2)));
  const expected = crypto.createHmac('sha256', secret).update(parts.t + '.').update(raw).digest('hex');
  return expected.length === parts.v1.length && crypto.timingSafeEqual(Buffer.from(expected), Buffer.from(parts.v1))
    && Math.abs(Date.now() / 1000 - Number(parts.t)) < tolerance;
}
```

## API for the contact center

Bearer API key of an owner/editor, or better an **integration key**: `POST /api/users/{name}/keys
{"label": "genesys", "scope": "integration"}`. It only works for these routes (and reading the conversation);
everything else is 403. It keeps the user's bot list. An analyst's key stays read-only.

| Route | Body | What it does |
| --- | --- | --- |
| `POST /api/v1/bots/{bot}/sessions/{sid}/handoff` | `{"action": "accept", "agent_name"?}` | Taken by an external agent (`handoff.by`). Starts the handoff if it wasn't active. |
| | `{"action": "release", "data"?: {slot: value}, "flow"?: "name"}` | Back to the bot. `data` fills slots, `flow` runs (its replies reach the customer). |
| | `{"action": "close", "resolution"?}` | Ends the conversation (`conversation.ended` with `resolution`). |
| `POST /api/v1/bots/{bot}/sessions/{sid}/messages` | `{"text", "from_name"?}` | Delivers to the customer through the conversation's channel and records it as `human`. |
| `GET /api/v1/bots/{bot}/lookup?phone=…` \| `?chat=…` \| `?sid=…` | | The latest open conversation of that customer (handed-off first), with the same context as the webhook. 404 if none. |
| `GET /api/v1/bots/{bot}/sessions/{sid}[/messages?after=N]` | | The conversation (already existing). |

`messages` delivery: web widget (immediately via WebSocket/SSE), WhatsApp and Telegram (synchronous: `502` if the
provider rejects it). WhatsApp outside the 24 h window → `409` (only an approved template, `POST /outbound`). A
phone call → `409`. Channel `api` → only recorded (your client polls `…/messages`). An ended conversation → `409`.
Audit: `handoff.accept`, `handoff.release`, `handoff.close`, `handoff.message`.

## Phone: transfer with context

On handoff, Parla transfers to `channels.phone.handoff_to`:

- **SIP URI + Twilio**: `<Dial><Sip>sip:queue@pbx?X-Parla-Session=…&amp;X-Parla-Intent=…</Sip></Dial>`. Twilio
  accepts `X-` headers and `User-to-User` in the URI ([Twilio `<Sip>`](https://www.twilio.com/docs/voice/twiml/sip)).
- **Number + Twilio**: `<Dial><Number>+54…</Number></Dial>` (no headers on the PSTN).
- **Twilio Flex**: with a Workflow SID, `<Enqueue workflowSid="WW…"><Task>{…}</Task></Enqueue>`; the task attributes
  carry `parla_session`, `intent`, `language`, `summary`, `slots`, `context_url`, `customer`
  ([TaskRouter TwiML](https://www.twilio.com/docs/taskrouter/twiml-queue-calls)).
- **jambonz**: `dial` with `"headers": {"X-Parla-Session": …, "User-to-User": …}` ([jambonz dial](https://docs.jambonz.org/verbs/verbs/dial)).

Headers you can choose: `X-Parla-Session`, `X-Parla-Intent`, `X-Parla-Language`, `X-Parla-Summary`,
`X-Parla-Context` (the lookup URL; the CC still needs its key to call it), `X-Parla-Slot-<name>` for the slots you
list, and `User-to-User` (the sessionId in hex, `;encoding=hex`). ASCII only, each value at most 128 characters
encoded and all of them under 1000 (Twilio's limit is 1024); what doesn't fit is dropped. Nothing from the vault is
ever sent. Default: no headers.

## Recipes

### Genesys Cloud

1. In Architect, an inbound message/call flow, or a Data Action that receives Parla's webhook through a small relay
   (Genesys can't verify `Parla-Signature` itself: put an AWS Lambda / function in between that verifies and calls
   the Genesys Platform API to create the interaction, e.g. an open messaging inbound message or a callback).
2. For calls: transfer to a SIP trunk / BYOC of Genesys; read `X-Parla-Session` or the UUI in Architect
   (`Call.UUIData` / SIP header variables) and a **Data Action** (web services) that calls
   `GET …/lookup?sid=…` with the integration key, to show the context in a script.
3. When the agent finishes: a Data Action that calls `POST …/handoff {"action": "release"|"close"}`.

Docs: [Data Actions](https://help.mypurecloud.com/articles/about-the-data-actions-integrations/),
[Open Messaging](https://developer.genesys.cloud/commdigital/digital/openmessaging/).

### Twilio Flex

1. Phone: set the Workflow SID in Handoff; the call enters Flex with the task attributes.
2. Chat (WhatsApp/web via Parla): a Twilio Function receives `handoff.requested`, verifies the signature and
   creates a task with the TaskRouter API (`attributes` = the payload).
3. A Flex plugin shows the context: with `task.attributes.parla_session`, call `GET …/lookup?sid=…` (via your
   backend: never put the API key in the browser) and send the agent's replies to `POST …/messages`. On wrap-up,
   `release` or `close`.

Docs: [TaskRouter tasks](https://www.twilio.com/docs/taskrouter/api/task), [Flex plugins](https://www.twilio.com/docs/flex/developer/plugins).

### Five9

1. Calls: transfer to Five9 by SIP with `X-Parla-Session` (or the UUI); in the IVR script, map the SIP header to a
   call variable and use a **Query** module (web service) against `…/lookup?sid=…`.
2. Chats: Five9 Digital Engagement can create interactions through its APIs from a relay that receives the webhook.
3. Return/close through a connector or web service on disposition.

Docs: [Five9 IVR / Query module](https://documentation.five9.com/), [Five9 APIs](https://developer.five9.com/).

### Zendesk

1. `handoff.requested` → a relay (verifies the signature) that creates a ticket (`POST /api/v2/tickets`) with the
   summary, slots and last messages, and saves `sessionId` in a custom field.
2. A Zendesk **webhook + trigger** on public agent comments calls your relay, which sends `POST …/messages`.
3. Ticket solved → trigger → `POST …/handoff {"action": "close", "resolution": "solved"}`.

Docs: [Tickets API](https://developer.zendesk.com/api-reference/ticketing/tickets/tickets/),
[Webhooks](https://developer.zendesk.com/documentation/webhooks/).

### Salesforce Service Cloud

1. `handoff.requested` → relay → create a Case (REST API) with the context and `sessionId`; an **Omni-Channel**
   flow routes it to a queue.
2. Agent replies: a Flow (record-triggered on a Case comment / Messaging) with an **HTTP Callout** (or Apex) to
   `POST …/messages` using a Named Credential with the integration key.
3. Case closed → Flow → `POST …/handoff {"action": "close"}`.

Docs: [Omni-Channel developer guide](https://developer.salesforce.com/docs/atlas.en-us.omni_channel_dev.meta/omni_channel_dev/),
[Salesforce Help: Flow HTTP Callout](https://help.salesforce.com/) (search «HTTP Callout»).

## Limits

- One delivery thread: a slow webhook (up to 10 s) delays the others.
- Order is per conversation and webhook; a dead event doesn't block the next ones.
- The AI summary doesn't delay the turn: the conversation and the phone transfer (SIP headers, Flex task) get the
  deterministic summary (intent + slots) at once; `handoff.requested` waits up to 10 s for the AI summary and is
  sent with the deterministic one if it doesn't arrive.
- Outbound egress follows the same rules as `http` steps (see [security.md](security.md#outbound-webhooks)).
