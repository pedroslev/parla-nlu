# Security

**English** · [Español](security_es.md)

Parla is meant to run on your computer or on a server you control, with a single person or a small team managing
it. This page covers what it protects, what it doesn't, and what to do before exposing it.

## Threat model

- **Local first.** With no configuration it listens only on `127.0.0.1` (`PARLA_HOST` changes that; the Docker
  image uses `0.0.0.0`). The admin interface is meant to be used from that same machine or through a tunnel.
- **With no users, it's open.** As long as no user exists, there's no login and no password: **anyone who reaches
  the port is the owner** and can read, change and delete every bot, its conversations and its keys. The `Host`
  check (see below) stops browsers, but a program like `curl` can send `Host: localhost` and get through anyway.
- **Create the owner before exposing it.** While there are no users, whoever makes the first `POST /api/users`
  creates the owner, whoever they are. There is no default username or password (there's no `admin/admin`): you
  create the first user yourself in **Users** and it becomes the owner (`owner`). From then on all of
  `/api/` requires a session or a key, except the widget's public chat.
- Anyone who can edit a bot is trusted: they can make the server call any URL (`http` steps) and, if functions are
  on and they're the owner, run code on the machine.
- Anyone chatting with the bot (the widget or your integration) is not trusted: what they type can never change
  the address of an `http` step, but it does reach headers and bodies as text (see [HTTP steps](#http-steps)).

## Users and sessions

- Users are stored in `users.json` (permissions 600) in the data folder, or wherever `PARLA_USERS` says.
- Passwords use scrypt (`n=2^14, r=8, p=1`) with a random salt per user. Minimum 5 characters, no other rules: if
  you expose it, use long passwords.
- Logging in sets the `parla_session` cookie: `HttpOnly`, `SameSite=Strict`, `Path=/`, valid for 12 hours. It
  carries `Secure` if `PARLA_SECURE_COOKIE=1`, or if the request has `X-Forwarded-Proto: https` and its `Host` is
  one of `PARLA_HOSTS` (an HTTPS proxy in front). Otherwise the cookie is also sent over HTTP. If the proxy
  rewrites the `Host` (nginx with `proxy_pass` does by default), the second condition isn't met: use
  `PARLA_SECURE_COOKIE=1`.
- Sessions are stored in `parla.db` in the data folder, only as the SHA-256 of the cookie value: they survive a
  restart. Each user's role and bots are read from `users.json` on every request, so a role change takes effect
  immediately.
- Changing the password or deleting a user ends their sessions. Logging out (`/api/auth/logout`) deletes the
  session.
- **Login lockout:** after 5 failed attempts within a minute for the same username and the same IP, login responds
  429 until the minute is up. Behind a proxy the IP is the proxy's (Parla doesn't read `X-Forwarded-For`): the
  lockout becomes per-user, and someone can lock another person out for a minute at a time. A user that doesn't
  exist takes as long to answer as one that does.

## Single sign-on (OIDC)

Optional: with `PARLA_OIDC_ISSUER` and `PARLA_OIDC_CLIENT_ID` set, the login screen shows **Sign in with
{label}** next to the password form. Setup per provider in [sso.md](sso.md). How it's protected:

- **Flow:** authorization code with PKCE (`S256`). `GET /api/auth/oidc/start` stores the state (as its SHA-256),
  the nonce and the PKCE verifier in the `oidc` table of `parla.db`, and sets the `parla_oidc` cookie
  (`HttpOnly`, `SameSite=Lax`, `Path=/api/auth/oidc`, 10 minutes) with the state. The callback requires the
  `state` in the URL to match that cookie, which binds the login to the browser that started it (against login
  CSRF), and the stored state is deleted on first use.
- **ID token validation:** the signature is checked against the provider's JWKS, only RS256, RS384 or RS512 (`none`,
  `HS*` and `ES*` are rejected) and only RSA keys of at least 2048 bits. Then `iss` must be exactly the discovery
  document's issuer, which in turn must equal `PARLA_OIDC_ISSUER`; `aud` must contain the client id; `azp` is
  checked when present or when there are several audiences; `exp` and `iat` with a 60 s leeway; and the `nonce`.
- **No crypto dependency.** RSA PKCS#1 v1.5 verification is pure Python (stdlib only): it builds the full expected
  encoded block (`00 01 FF…FF 00` + DigestInfo + hash) and compares it whole, it doesn't parse the decoded
  signature. OIDC Core §3.1.3.7 allows skipping signature checks for a token received directly from the token
  endpoint over TLS; Parla checks it anyway, as defense in depth.
- The discovery document and the JWKS are cached for 1 hour; an unknown `kid` re-fetches the JWKS (key rotation).
  Provider URLs must be `https://` (except `localhost` / `127.0.0.1`, for testing).
- **Redirect URI:** `PARLA_PUBLIC_URL` + `/api/auth/oidc/callback`. Without `PARLA_PUBLIC_URL`, the request's
  `Host` is used only if it's local or in `PARLA_HOSTS`; any other `Host` is refused.
- The callback is a cross-site navigation, so it's exempt from the Origin check (state, nonce and PKCE protect
  it). The Host check still applies: put your public host in `PARLA_HOSTS`.
- **Users are matched by `sub`, never by name.** A provider user whose name matches a local user gets a suffixed
  name (`ana-1a2b3c`); it never takes over the local account. SSO users are stored in `users.json` with
  `sso: true`, `sub` and `email`, and no password.
- **Roles:** with a role mapping (`PARLA_OIDC_ROLE_CLAIM` + `PARLA_OIDC_ROLE_MAP`) the role is recomputed on every
  login; the user's `bots` scoping is kept. No mapped role and no `PARLA_OIDC_DEFAULT_ROLE`: access denied.
  Without a role mapping, new users get `PARLA_OIDC_DEFAULT_ROLE` (none set: denied) and existing ones keep the
  role set in Parla, which the owner can edit.
- **`PARLA_OIDC_ONLY=1`** turns password login off, except a break-glass login for an **owner** when the TCP peer
  is loopback, the `Host` is `127.0.0.1`, `localhost` or `[::1]` and the request has no `X-Forwarded-For`,
  `X-Forwarded-Host`, `X-Real-IP` or `Forwarded` header. A reverse proxy on the same machine also connects from
  loopback: it **must** send one of those headers (e.g. `X-Forwarded-For`), or its requests would look local.
- With OIDC configured and no users, login is required anyway, and the first local owner can only be created
  break-glass (from the machine itself, as above).
- API keys keep working as before, also with `PARLA_OIDC_ONLY`.
- **Audit:** each attempt is logged as `login.sso` with `ok` or `falló: <reason>` and the IP. Tokens are never
  stored or logged.
- **Logout** ends the Parla session. If the provider has an `end_session_endpoint`, the browser is then sent there
  with `client_id` (and `post_logout_redirect_uri` when `PARLA_PUBLIC_URL` is set). There's no `id_token_hint`
  because tokens aren't kept; providers that require it (Okta) need `PARLA_OIDC_LOGOUT=0`, which turns this off.

Limitations to keep in mind:

- A Parla session lasts 12 hours whatever the provider says. There's no back-channel logout: disabling someone in
  the provider takes effect at their next login or when the session expires. To cut them off now, delete the user
  in **Users** (that ends their sessions), but they can sign in again via SSO while the provider allows it.
- A user removed from every mapped group loses access at their next login, not before.
- The provider can demote the last owner (role mapping wins). Keep a local owner for break-glass.
- No ES256 or EdDSA ID tokens; one issuer per installation; Entra ID's multi-tenant `common` issuer isn't
  supported (use the tenant's issuer); with Entra ID group overage (more than 200 groups the claim is replaced
  by a link) use app roles (the `roles` claim) instead.

## Audit log

Parla records successful write operations in the `audit` table of `parla.db`: who (user and role), when, on which
agent, what, and a short detail. The owner sees it in **Audit log** (`#/auditoria`, from the avatar menu,
next to **Manage users**) or with `GET /api/audit` ([api.md](api.md)); other roles get 403.

- Actions: `login` (successful **and failed**, with the IP; never the password), `login.sso` (`ok` or
  `falló: <reason>`, with the IP; never tokens), `logout`, `user.create`,
  `user.update`, `user.role`, `user.delete`, `key.create` (also “Connect to AI”), `key.revoke`, `agent.create`,
  `agent.import`, `agent.save`, `agent.delete`, `agent.train`, `agent.publish`, `agent.deploy`, `agent.restore`,
  `secret.set` / `secret.delete` (the name only, never the value), `file.upload` / `file.delete`,
  `channel.update` (a save that changed `channels`), `channel.telegram`, `inbox.take` / `inbox.release` /
  `inbox.reply`, `session.delete`, and for outbound messaging `outbound.send`, `campaign.create`, `campaign.update`,
  `campaign.delete`, `campaign.recipients`, `campaign.start` / `campaign.pause` / `campaign.resume` /
  `campaign.cancel`, `optout.add` and `optout.remove` (phone numbers masked: `549••••••5678`).
- The interface autosaves every ~400 ms: consecutive `agent.save` entries by the same user on the same agent
  within 5 minutes are merged into one.
- Without users configured, entries have an empty user.
- Entries older than `PARLA_AUDIT_DAYS` (default 365) are deleted by the hourly cleanup.
- It doesn't log reads or every request: for that, use the proxy's access log.

## Personal data in conversations

- **Retention:** `retention_days` on the agent (or `PARLA_RETENTION_DAYS` for all of them) deletes conversations
  with no activity for that many days. Without either, they're kept forever. See
  [concepts.md](concepts.md#retention-and-personal-data).
- **Masking (`pii_redaction`):** replaces emails, phones, cards, ID numbers and bank accounts with «[email]»,
  «[teléfono]», etc. in what's **stored** (history, Inbox, insights, analytics, the API's history). The live turn
  (flow, `http` steps, functions and that turn's reply) still sees the real value, and the conversation's working
  state keeps it until the conversation ends; with masking on, conversations idle for 24 h are closed so it's
  wiped.
- Masking is a heuristic (regular expressions): it can miss a format or mask a number that isn't personal data.
  It doesn't rewrite what was already stored when you turn it on, and it doesn't apply to the server's console
  output.

## API keys

- For the API and MCP: `Authorization: Bearer parla_...`. They're created in **Users → a user → API keys**. Only the owner manages users and keys, for any user.
- They act with the role and bots **of the user they belong to**: an analyst's key can only make `GET` requests.
  A key created with `"scope": "integration"` only reaches the contact center routes (see [Outbound webhooks](#outbound-webhooks)).
- They're shown only once. They're stored as a SHA-256 hash in `users.json`; deleting the key (or the user) cuts
  it off immediately.
- With a valid key you can call `/api/` even if the `Host` isn't a known one (your backend behind a proxy). With a
  cookie you can't: the `Host` has to be local or in `PARLA_HOSTS`.

### “Connect to AI” (`/api/connect`)

Once users exist, every time someone clicks **Connect** Parla **creates a new key** for that user
(named «Conectar con Claude Code», etc.) and puts it in the assistant's configuration:

- In Claude Code it's registered with `claude mcp add ... -e PARLA_TOKEN=parla_...`: the key goes **on the command
  line**, so while that command runs, anyone who can list processes (`ps`) on the machine can see it.
- In every assistant it ends up in plain text in its configuration file (`~/.claude.json`,
  `~/.codex/config.toml`, the Claude Desktop configuration or `~/.cursor/mcp.json`), with that file's normal
  permissions.
- Disconnecting doesn't delete the key, and reconnecting creates another one. **Delete the old ones** in
  **Users → API keys**.
- It only responds if the `Host` is exactly `127.0.0.1:<port>` or `localhost:<port>`: it doesn't work through a
  proxy. It requires `POST` with `Content-Type: application/json`, so an analyst or support user can't use it.

## Roles

| Role | In the interface | Can |
|---|---|---|
| `owner` | Owner | Everything, including managing users and keys. Always sees every bot. The only one who can create or change function code while functions are on. There must be at least one. |
| `editor` | Editor | Everything on the bots they see, except managing users and keys. With functions on, **they can't add or change function code**: not when saving the bot, importing one that includes functions, restoring a version with different functions, or with **Try it** (403). They can delete or reorder them. |
| `analyst` | Analyst | Only `GET` requests, on everything they see: bot definitions, conversations, reports, inbox, key names. Any other method: 403. |
| `agent` | Support | A minimal view: the list of bots and each bot without its definition (no intents, flows, functions or knowledge), the Inbox (`inbox`), taking, replying to and handing back conversations, and reading a conversation via `/api/v1/bots/{bot}/sessions/{id}`. Everything else: 403. |

With functions off (`PARLA_FUNCTIONS=0`) the code rule doesn't apply: an editor can save functions, but they don't
run.

## Bots per user

Every user who isn't an owner has `bots`: `null` (sees all of them) or a list of ids. A bot they can't see responds
**404**, as if it didn't exist, on `/api/agents/{id}/...` and `/api/v1/bots/{bot}/...`; lists show only theirs. If
someone with a list creates or imports a bot, it's added to their list. The bot check runs before the role check.

## Requests from other sites: Host, Origin and `PARLA_HOSTS`

Two checks protect a local Parla from the pages you open in your browser:

- **Origin:** a request to `/api/` with an `Origin` header is rejected with 403 unless its host is
  `127.0.0.1:<port>` or `localhost:<port>` (the port Parla listens on), one of `PARLA_HOSTS`, or an authorized
  widget site for the chat routes. Together with `SameSite=Strict` it prevents another page from using your
  session.
- **Host (against DNS rebinding):** a request to `/api/` whose `Host` isn't `127.0.0.1`, `localhost` or `[::1]`
  (any port) or one of `PARLA_HOSTS` is rejected with 403, unless it carries a valid API key or is the widget's
  public chat. That way a domain pointing at `127.0.0.1` can't talk to your Parla.

`PARLA_HOSTS` is a comma-separated list of `host` or `host:port` values that can also be used to reach Parla, for
example `PARLA_HOSTS=bots.midominio.com`. With that, the full interface works behind a proxy on that domain (login
included). Also add `localhost:9000` there if you publish the port under a different number (`-p 9000:8000`).

`/`, `/static/*.js` and `/files/...` skip these checks (they're not `/api/`).

## The widget: what someone without a session can do

If a bot has the widget turned on, these routes of **that bot** respond without a session or key:

- `POST /api/v1/bots/{bot}/events` and `POST /api/v1/bots/{bot}/audio`
- `GET /api/v1/bots/{bot}/sessions/{id}/messages`, only for conversations on the `web` channel

A public request is restricted:

- Always the `web` channel and the `production` environment: `channel` and `environment` in the body are ignored.
- It can't preload data (`data` in `start`) and the response has no `trace`.
- It can't continue, read or end a conversation from another channel (403).
- Public audio is capped at 2 MB.
- It can't read the bot definition, the list of conversations, the detail with slots or reports.

Things to keep in mind:

- **CORS is not access control.** `widget.origins` (or `*`) only decides which sites can call from a browser. Any
  program that isn't a browser (no `Origin`) can use these public routes of any bot with the widget turned on:
  chat, send audio (which the server transcribes) and read `web` conversations whose id it knows.
- **The conversation id is the only key.** The widget generates it in the browser with `crypto.randomUUID()`
  (`web-` + 32 hex characters) and stores it in `localStorage`; if the browser doesn't have `randomUUID` (a page
  without HTTPS on old browsers) it uses the time and `Math.random()`, which is guessable. Whoever has that id can
  read the conversation and continue it. If you send `web` events from your backend, use random ids, not a national
  ID number or a phone number.
- Anyone who knows the bot's name or id can chat with it: don't put data in those flows that you wouldn't put on
  your website.
- A logged-in user who can see the bot uses those same routes without the public limits.

## Messaging channels (WhatsApp and Telegram)

The webhooks `GET`/`POST /api/v1/bots/{bot}/whatsapp` and `POST /api/v1/bots/{bot}/telegram`, and the phone routes
below, are the only `/api/` routes that skip the login and the `Host` check: Meta's, Telegram's and the phone
provider's servers call them. Each request
authenticates on its own instead:

- WhatsApp `POST`: `X-Hub-Signature-256` has to be `sha256=` + the HMAC-SHA256 of the raw body with the app secret
  (`WHATSAPP_APP_SECRET`). The verification `GET` has to bring `hub.verify_token` equal to `WHATSAPP_VERIFY_TOKEN`.
- Telegram `POST`: `X-Telegram-Bot-Api-Secret-Token` has to be equal to `TELEGRAM_WEBHOOK_SECRET` (Parla generates it
  when you press **Connect webhook**).
- Comparisons are constant-time. Channel off, missing key or bad signature: **403 with no details**. Body up to 1 MB.
- Only messages for the configured `phone_number_id` are processed; repeated message ids are processed once.
- The tokens (`WHATSAPP_TOKEN`, `TELEGRAM_TOKEN`) and secrets live in the vault, never in the agent's JSON; outbound
  errors go to the console with values masked.
- Conversation ids (`wa-<phone>`, `tg-<chat>`) contain the person's phone number or chat id.
- The bot answers with the `production` environment. Webhooks can't preload data, read conversations or reach any
  other route.

Setup and limits in [channels.md](channels.md).

### Phone calls (Twilio and jambonz)

- `POST /api/v1/bots/{bot}/phone/twilio[/gather|/status]`: `X-Twilio-Signature` has to be the base64 HMAC-SHA1, with
  `TWILIO_AUTH_TOKEN`, of the public URL (`public_url` / `PARLA_PUBLIC_URL` + the requested path and query) followed
  by each POST key and value sorted by key, as Twilio computes it.
- `POST /api/v1/bots/{bot}/phone/jambonz[/gather|/status]`: with `JAMBONZ_WEBHOOK_SECRET` loaded, `Jambonz-Signature`
  (`t=<unix>,v1=<hex>`) has to be the HMAC-SHA256 of `<t>.<raw body>` and `t` within 5 minutes (replays of old
  requests fail); with `JAMBONZ_BASIC_USER` and `JAMBONZ_BASIC_PASSWORD` loaded, `Authorization: Basic` has to match.
  Every method that is loaded must pass; with none loaded, nothing does.
- Only the provider chosen in `channels.phone.provider` is accepted, and only with `channels.phone.enabled`.
  Comparisons are constant-time; failures are **403 with no details**; body up to 1 MB.
- **Signed audio URLs** (`tts: "parla"`): `GET /api/v1/bots/{bot}/phone/audio/<token>.wav` serves only the text inside
  the token, which carries the bot id, an expiry (10 minutes) and the language, signed with HMAC-SHA256 by a random
  key that lives in the server's memory. It can't be forged, reused for another bot, or used after it expires, and it
  opens nothing else. Whoever holds a URL can hear that phrase until it expires (providers fetch them without auth).
- With Twilio, the caller's audio is transcribed at Twilio (the audio and text leave your server). With jambonz, it
  goes wherever its speech services point, which can be self-hosted.
- The conversation id `call-<CallSid>` and the caller's number (saved in a `caller` slot if the bot has one, and kept
  by the provider) are personal data; `pii_redaction` masks phone numbers in what is saved.

## Outbound messages and campaigns

The bot can write first: the outbound API, campaigns and reminders ([outbound.md](outbound.md)).

- **Who:** `POST /api/v1/bots/{bot}/outbound`, creating, changing, starting or canceling campaigns and managing
  opt-outs need `owner` or `editor`. `analyst` sees campaigns, results, the CSV export and opt-outs, read-only.
  `agent` (support) sees none of it. The outbound route is never public, even with the widget on.
- **Audit:** every send through the API, every campaign change and action, and every manual opt-out is in the
  [audit log](#audit-log), with the phone number masked.
- **Masking:** numbers are masked in the audit log and in the console errors. The UI and the admin API show them to
  whoever can see the bot, and conversation ids (`wa-<phone>`) still contain them.
- **Rate limits:** `agent.outbound.api_per_minute` API sends per minute per agent (default 30, 429 above it); each
  campaign's rate (1 per minute to 50 per second); 10,000 recipients per campaign (`agent.outbound.max_recipients`,
  `PARLA_CAMPAIGN_MAX`). The counters live in memory.
- **Retention and personal data:** with `retention_days` (or `PARLA_RETENTION_DAYS`), the recipients of campaigns
  that finished more than that many days ago are deleted (numbers and data), keeping only the totals; old API and
  reminder rows too. With `pii_redaction`, a campaign or reminder row's data is masked once it's sent. Deleting the
  agent deletes its campaigns, queue and opt-outs.
- **Outbound calls:** the provider calls back the usual signed webhook with a random `?o=<token>` that names the
  send; the signature covers it. Placing calls needs `TWILIO_ACCOUNT_SID` or `JAMBONZ_API_KEY` /
  `JAMBONZ_ACCOUNT_SID` in the vault.
- **Consent:** opt-out keywords («STOP», «BAJA») are honored on their own, and an opted-out person can't be sent to
  (409). Getting consent before writing, respecting quiet hours and do-not-call lists is on you: see
  [Consent and the law](outbound.md#consent-and-the-law).

## Key vault (secrets)

In **Publish → Secrets** you store tokens and passwords for external services, per agent.

- They're stored separately, in `agents/<id>.secrets.json` (permissions 600), **unencrypted**: protect the data
  folder as you would a `.env`. They're deleted when the agent is deleted.
- They're never in the agent's JSON: they don't travel on export and don't end up in published versions.
- The interface, the API and MCP only see the **names**; values never come back through the API, and MCP can't
  read or set them.
- They're only resolved in the URL, headers and body of an `http` step (`{{ secret.NOMBRE }}`), as the
  `secret.NOMBRE` input of a function and as the AI and voice providers' API keys (`ai.api_key_secret`, and
  `api_key_secret` in `voice.asr` / `voice.tts`). They aren't resolved in messages. The AI key is never returned by `/api/ai/status` and is masked in its errors.
- Any value of 4 or more characters that shows up in a trace or in a flow error message is masked with `••••`.
  What the service or function returns is **not** masked: if a response contains the key and you save it in a
  slot, it stays in the conversation.

## Hosted AI and voice providers: data leaves the machine

By default everything runs on your machine: the AI on Ollama, speech recognition on faster-whisper and the bot's
voice on piper. If an agent uses a hosted provider (its own key, see [ai-and-voice.md](ai-and-voice.md)), this is
what goes to it, handled under its terms (retention, training, region) and billed to the key owner:

| Provider | What leaves the machine |
|---|---|
| AI `ollama` | Nothing. |
| AI `openai`, `openai_compatible` (when the URL is not yours), `anthropic`, `gemini` | The conversation text and recent turns, the persona, the knowledge-base snippets used for an answer and the tool results in the agent step. |
| Speech recognition (`voice.asr`: OpenAI, Deepgram, ElevenLabs, Google) | The user's audio and the vocabulary hints (the bot's entity values and synonyms). |
| Bot voice (`voice.tts`: OpenAI, Deepgram, ElevenLabs, Google) | The text of the bot's replies. |

- Embeddings, intents and knowledge search stay local. The AI and voice screens warn when data leaves the machine.
- **Keys** come only from the agent's vault (**Secrets**) by name (`api_key_secret`), never from the agent's JSON
  (MCP `validate` rejects an `api_key`). They're masked (`••••`) in every error, log and trace, also when a provider
  echoes the key in its error body.
- **Fixed hosts:** each provider's address is fixed in the code (only `openai_compatible` and `openai` with a `url`
  use the URL you set), so there's no SSRF surface from these calls. The `PARLA_*_BASE_URL` overrides (tests,
  proxies) are environment variables: only whoever runs the server can set them.
- Every provider call has a timeout (30 s for voice; the AI uses the caller's time budget).
- Setting and deleting a secret is already in the [audit log](#audit-log).
- Only owners and editors can change an agent's AI or voice provider or test it with the agent's key; review agents
  built by someone else before enabling them.

## HTTP steps

- In the URL, each slot value is encoded (including `/`, `?`, `&`, `#`): what the person types can't change the
  host or the path. `{{ secret.X }}` values go in as-is. The URL has to start with `http://` or `https://`.
- In headers, any line break (`\r` or `\n`) stops the step with an error.
- **The body is not escaped:** the slot value goes in as text. If you build JSON with `"{{ nombre }}"`, a quote in
  what the person typed can change that JSON. Validate those slots (entities, format) or build the body in a
  function.
- 10 s timeout, up to 1 MB of the response is read, and redirects are followed.
- **SSRF:** an `http` step calls any URL the Parla server can reach: your internal network, `localhost` (Ollama,
  other services) or the cloud metadata service (`169.254.169.254`). **Test the call** returns the
  response to whoever runs the test. The same applies to importing knowledge from a URL and to an agent's AI
  address. Any editor can use this: review bots built by an AI or by someone else, and in Kubernetes restrict
  outbound traffic with an egress `NetworkPolicy` (or the server's firewall).

## Outbound webhooks

Handoff webhooks (`agent.webhooks`, [contact-centers.md](contact-centers.md)):

- **Signed:** `Parla-Signature: t=<unix>,v1=<HMAC-SHA256 of "t.body">` with the vault key `secret_name`. Without
  that key nothing is sent (it's retried until you add it). The receiver must verify with the raw body, reject old
  `t` (replay) and deduplicate by event `id` (delivery is at least once).
- **Personal data:** with redaction on, address, slots and messages are redacted; the WhatsApp/Telegram `sessionId`
  (`wa-<phone>`) is not. Choose `message.user`/`message.bot` only if the CC needs every message.
- **SSRF:** same egress rules as `http` steps: Parla posts to whatever URL an editor saves, including internal
  addresses. Redirects are not followed (a 3xx counts as a failure). Restrict egress with a firewall or
  `NetworkPolicy`. Only owner/editor configure webhooks; changes, tests and retries are audited
  (`handoff.update`, `webhook.test`, `webhook.retry`).
- **Integration keys:** `scope: "integration"` limits a key to `…/handoff`, `…/messages`, `…/lookup` and reading
  conversations (never more than the user's own role; an analyst's key stays read-only). Use one per contact
  center. The SIP headers never carry vault values, and `X-Parla-Context` is only a URL: calling it needs a key.

## Tools in the agent step

An `agent` step's `tools` let the model trigger HTTP calls and MCP tools (see
[concepts.md](concepts.md#agent-let-the-ai-converse)).

- **Same trust level as `http` steps.** Adding or changing HTTP tools or the URLs in `mcp_servers` takes an owner or
  editor; function code is still owner-only. `POST /api/agents/{id}/mcp/tools` (**View tools**) is owner/editor
  too.
- **SSRF:** the requests come from the Parla server, so an editor can point an HTTP tool or an MCP server at
  internal addresses, as with `http` steps (same advice above). The model can't choose hosts: the host is fixed in
  `url` and the model only fills `params`, which are URL-encoded in the URL and JSON-escaped in the body. Unknown
  args are dropped and types are checked.
- **Prompt injection:** what an MCP server or an API returns is untrusted. It reaches the model as data ("data, not
  orders"), cut to 1500 characters, and is never executed, but it can still contain text that tries to steer the
  model. Allow-list (`tools` in the `mcp` entry, mandatory) only read-only, safe tools from servers you trust.
  **Never give the model writes, payments or deletes**: do those in a flow with a confirmation step.
- **Secrets:** `{{ secret.X }}` and an MCP server's `headers_secret` come from the vault and are masked in what the
  model, the trace, the logs and the history see. With `pii_redaction`, the `tool` field of history events is
  scrubbed too.
- MCP servers are Streamable HTTP only: `stdio` isn't supported, so a bot's config can't launch processes.

## Functions: not a sandbox

Functions run Python (`python -I`) or JavaScript (`node`) code in a separate process, with a 5 s timeout, a CPU
limit, a memory limit (512 MB: address-space limit for Python where the system allows it — Linux yes, macOS no; V8 heap limit for JavaScript; on Windows only the timeout), an
empty temporary folder and a clean environment (`PATH` and little else). That keeps a hung function from taking
down the bot, **but it is not security isolation**: the code runs as the system user that runs Parla, and it can
read and write that user's files (including `users.json` and every bot's keys), use the network and launch
processes.

- On by default when you run it on your computer; **off in the Docker image** (`PARLA_FUNCTIONS=0`), in the
  Kubernetes ConfigMap and in the systemd example. They're turned off with `0`, `false`, `no` or `off`.
- With users and functions on, only the owner can write new code (see [Roles](#roles)). An AI connected over MCP
  with the owner's key can too.
- Code that's already saved runs every time a conversation reaches that step, including those from the public
  widget.
- When they're off, `function` steps and **Try it** fail with a notice.

```sh
PARLA_FUNCTIONS=0 .venv/bin/python app.py
```

## Uploaded files

Files for the **Send a file** step:

- Up to 10 MB. Only `pdf png jpg jpeg gif webp txt csv doc docx xls xlsx ppt pptx zip`. The type comes from the
  extension, never from the browser: HTML and SVG aren't accepted.
- They're served with `X-Content-Type-Options: nosniff`. PDFs, images and `.txt` open in the browser; everything
  else downloads. The name is sanitized in `Content-Disposition`.
- They're served **without a session** at `/files/<agent>/<id>`: the id is random (128 bits) and acts as the key.
  Whoever has the link can download it.

## Request limits and errors

- JSON body (413 otherwise): 1 MB in general; 25 MB to create, import or save an agent, upload files, extract
  knowledge, dictation and `POST /api/v1/bots/{bot}/audio`; 2 MB for public widget audio.
- A message is cut at 4000 characters; the last 500 messages per conversation are kept.
- A connection with no data for 30 s is closed (against deliberately slow connections).
- Errors meant for the person: 400 with the message. Any other error: 500 with a generic message, no paths or
  details; the detail goes to the Parla console (keys not masked).

## MCP with `--http`

`mcp_server.py --http` **has no authentication**: anyone who reaches its port acts with the `PARLA_TOKEN` key (or
with full access, if Parla has no users). It listens on `127.0.0.1` by default (`--host` changes that). If you
publish it, protect it at the proxy and set `PARLA_MCP_ALLOWED_HOSTS` (the accepted `Host` values, in addition to
`127.0.0.1` and `localhost`). With `stdio` (the usual way) it doesn't open any port.

## Metrics and traces

All off by default ([observability.md](observability.md)).

- **`/metrics`** exists only with `PARLA_METRICS=1`. With `PARLA_METRICS_TOKEN` it requires
  `Authorization: Bearer <token>` (compared in constant time); without a token it only answers a connection from
  loopback with a `Host` of `127.0.0.1`, `localhost` or `[::1]`. A `PARLA_HOSTS` domain doesn't count, because a proxy
  on the same machine would let anyone through. It's outside `/api/`: no session, no role, no audit entry. Don't
  publish it at the proxy; the example Ingress doesn't.
- **What metrics reveal:** agent ids, route templates, counts and latencies, LLM and voice providers, CSAT
  distribution. Never messages, slot values, session ids or secrets. Label values come from a fixed set or are
  ids, and new series stop at 5,000, so a client can't blow up memory with odd paths.
- **Traces** carry ids, intent, flow, entity and function names, confidence, status, durations, the model name,
  token counts and the host of each `http` step (not its path or query, which can carry data or keys). Exceptions
  only send their class. The outgoing `traceparent` header on `http` steps reveals the trace id to that service,
  nothing else.
- **`PARLA_OTEL_CONTENT=1`** sends the person's message and the bot's reply in the `parla.turn` span, with vault
  secrets replaced by `••••` and every PII category masked. Masking is a heuristic (see
  [Personal data](#personal-data-in-conversations)): treat the trace backend as holding conversations, with the
  same access control and retention as `parla.db`.
- **The collector** is called from the server like an `http` step: the `OTEL_EXPORTER_OTLP_HEADERS` (API keys) are
  environment variables, not in any agent, and never logged.

## Before exposing it to the internet

1. **Create the owner** with a strong password before opening anything, and the other users with the minimum role
   and only the bots they need.
2. **Listen locally:** keep `127.0.0.1` (or in Docker `-p 127.0.0.1:8000:8000`) and put an HTTPS proxy in front
   ([deployment.md](deployment.md)).
3. **`PARLA_HOSTS`** with your domain if you'll use the interface through the proxy, and `PARLA_SECURE_COOKIE=1`
   (or have the proxy send `X-Forwarded-Proto: https`).
4. **Publish only what's needed:** for the widget and your integrations, `/api/v1/` and `/static/widget.js` are
   enough (plus `/files/` if your bots send files). To administer, prefer an SSH tunnel or `kubectl port-forward`.
5. **Functions off** (`PARLA_FUNCTIONS=0`) unless you trust the owner and the AIs they connect.
6. **Egress:** restrict where the server can call (`NetworkPolicy`, firewall), especially the cloud metadata
   service and the internal network.
7. **Container:** unprivileged user (the image uses uid `10001`), read-only file system
   (`--read-only --tmpfs /tmp`, or `readOnlyRootFilesystem` in Kubernetes) and no capabilities.
8. **Backups:** the data folder holds conversations, users and keys (`parla.db` included, see
   [deployment.md](deployment.md#backups)). Keep backups somewhere private and keep
   `users.json` and `*.secrets.json` at permissions 600 when restoring.
9. Review `http` steps, widget origins and old API keys (especially the ones from “Connect to AI”).
10. If you use MCP with `--http`, protect it at the proxy.
11. Add a rate limit at the proxy: Parla only has one on login.
12. If you turn on metrics, set `PARLA_METRICS_TOKEN` and keep `/metrics` off the proxy; keep `PARLA_OTEL_CONTENT`
    off unless the trace backend is as private as the data folder.

## Not there yet

- One replica per data folder. Login lockout counters are in memory: they reset on restart.
- No general rate limiting: only the login lockout and the outbound limits (API sends per minute, campaign rate).
- No access log with users or IPs: the audit log records writes, and `PARLA_LOG_FORMAT=json` logs every request
  with its route template, status and duration but not who made it.
- No second factor for local passwords (with [SSO](sso.md), your identity provider can require MFA), no password
  policy and no list of open sessions to end by hand.
- Keys aren't encrypted on disk. Agents are saved with the system's normal permissions; `users.json`, the keys and
  `parla.db` (conversations, login hashes and the audit log) are 600.
- Masking personal data is a heuristic, and it's off by default.

## Reporting a vulnerability

Don't open a public issue. Open a private security advisory at
<https://github.com/pedroslev/parla-nlu/security/advisories/new> (**Security → Report a vulnerability** on the
repository), with steps to reproduce it. The full policy is in [SECURITY.md](../SECURITY.md).
