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
  create the first user yourself in **Usuarios** (Users) and it becomes the owner (`owner`). From then on all of
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
- Sessions live **in memory**: after a server restart you have to log in again. Each user's role and bots are read
  from `users.json` on every request, so a role change takes effect immediately.
- Changing the password or deleting a user ends their sessions. Logging out (`/api/auth/logout`) deletes the
  session.
- **Login lockout:** after 5 failed attempts within a minute for the same username and the same IP, login responds
  429 until the minute is up. Behind a proxy the IP is the proxy's (Parla doesn't read `X-Forwarded-For`): the
  lockout becomes per-user, and someone can lock another person out for a minute at a time. A user that doesn't
  exist takes as long to answer as one that does.

## API keys

- For the API and MCP: `Authorization: Bearer parla_...`. They're created in **Usuarios → a user → Claves de API**
  (Users → a user → API keys). Only the owner manages users and keys, for any user.
- They act with the role and bots **of the user they belong to**: an analyst's key can only make `GET` requests.
- They're shown only once. They're stored as a SHA-256 hash in `users.json`; deleting the key (or the user) cuts
  it off immediately.
- With a valid key you can call `/api/` even if the `Host` isn't a known one (your backend behind a proxy). With a
  cookie you can't: the `Host` has to be local or in `PARLA_HOSTS`.

### «Conectar con IA» (Connect to AI) (`/api/connect`)

Once users exist, every time someone clicks **Conectar** (Connect) Parla **creates a new key** for that user
(«Conectar con Claude Code», etc.) and puts it in the assistant's configuration:

- In Claude Code it's registered with `claude mcp add ... -e PARLA_TOKEN=parla_...`: the key goes **on the command
  line**, so while that command runs, anyone who can list processes (`ps`) on the machine can see it.
- In every assistant it ends up in plain text in its configuration file (`~/.claude.json`,
  `~/.codex/config.toml`, the Claude Desktop configuration or `~/.cursor/mcp.json`), with that file's normal
  permissions.
- Disconnecting doesn't delete the key, and reconnecting creates another one. **Delete the old ones** in
  **Usuarios → Claves de API**.
- It only responds if the `Host` is exactly `127.0.0.1:<port>` or `localhost:<port>`: it doesn't work through a
  proxy. It requires `POST` with `Content-Type: application/json`, so an analyst or support user can't use it.

## Roles

| Role | In the interface | Can |
|---|---|---|
| `owner` | Dueño (Owner) | Everything, including managing users and keys. Always sees every bot. The only one who can create or change function code while functions are on. There must be at least one. |
| `editor` | Editor | Everything on the bots they see, except managing users and keys. With functions on, **they can't add or change function code**: not when saving the bot, importing one that includes functions, restoring a version with different functions, or with «Probar» (Test) (403). They can delete or reorder them. |
| `analyst` | Analista (Analyst) | Only `GET` requests, on everything they see: bot definitions, conversations, reports, inbox, key names. Any other method: 403. |
| `agent` | Atención (Support) | A minimal view: the list of bots and each bot without its definition (no intents, flows, functions or knowledge), the Bandeja (Inbox, `inbox`), taking, replying to and handing back conversations, and reading a conversation via `/api/v1/bots/{bot}/sessions/{id}`. Everything else: 403. |

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

The webhooks `GET`/`POST /api/v1/bots/{bot}/whatsapp` and `POST /api/v1/bots/{bot}/telegram` are the only `/api/`
routes that skip the login and the `Host` check: Meta's and Telegram's servers call them. Each request
authenticates on its own instead:

- WhatsApp `POST`: `X-Hub-Signature-256` has to be `sha256=` + the HMAC-SHA256 of the raw body with the app secret
  (`WHATSAPP_APP_SECRET`). The verification `GET` has to bring `hub.verify_token` equal to `WHATSAPP_VERIFY_TOKEN`.
- Telegram `POST`: `X-Telegram-Bot-Api-Secret-Token` has to be equal to `TELEGRAM_WEBHOOK_SECRET` (Parla generates it
  when you press **Conectar webhook**, Connect webhook).
- Comparisons are constant-time. Channel off, missing key or bad signature: **403 with no details**. Body up to 1 MB.
- Only messages for the configured `phone_number_id` are processed; repeated message ids are processed once.
- The tokens (`WHATSAPP_TOKEN`, `TELEGRAM_TOKEN`) and secrets live in the vault, never in the agent's JSON; outbound
  errors go to the console with values masked.
- Conversation ids (`wa-<phone>`, `tg-<chat>`) contain the person's phone number or chat id.
- The bot answers with the `production` environment. Webhooks can't preload data, read conversations or reach any
  other route.

Setup and limits in [channels.md](channels.md).

## Key vault (secrets)

In **Publicar → Claves** (Publish → Keys) you store tokens and passwords for external services, per agent.

- They're stored separately, in `agents/<id>.secrets.json` (permissions 600), **unencrypted**: protect the data
  folder as you would a `.env`. They're deleted when the agent is deleted.
- They're never in the agent's JSON: they don't travel on export and don't end up in published versions.
- The interface, the API and MCP only see the **names**; values never come back through the API, and MCP can't
  read or set them.
- They're only resolved in the URL, headers and body of an `http` step (`{{ secret.NOMBRE }}`) and as the
  `secret.NOMBRE` input of a function. They aren't resolved in messages.
- Any value of 4 or more characters that shows up in a trace or in a flow error message is masked with `••••`.
  What the service or function returns is **not** masked: if a response contains the key and you save it in a
  slot, it stays in the conversation.

## HTTP steps

- In the URL, each slot value is encoded (including `/`, `?`, `&`, `#`): what the person types can't change the
  host or the path. `{{ secret.X }}` values go in as-is. The URL has to start with `http://` or `https://`.
- In headers, any line break (`\r` or `\n`) stops the step with an error.
- **The body is not escaped:** the slot value goes in as text. If you build JSON with `"{{ nombre }}"`, a quote in
  what the person typed can change that JSON. Validate those slots (entities, format) or build the body in a
  function.
- 10 s timeout, up to 1 MB of the response is read, and redirects are followed.
- **SSRF:** an `http` step calls any URL the Parla server can reach: your internal network, `localhost` (Ollama,
  other services) or the cloud metadata service (`169.254.169.254`). «Probar consulta» (Test request) returns the
  response to whoever runs the test. The same applies to importing knowledge from a URL and to an agent's AI
  address. Any editor can use this: review bots built by an AI or by someone else, and in Kubernetes restrict
  outbound traffic with an egress `NetworkPolicy` (or the server's firewall).

## Functions: not a sandbox

Functions run Python (`python -I`) or JavaScript (`node`) code in a separate process, with a 5 s timeout, a CPU
limit, a memory limit (512 MB where the system allows it: Linux yes, macOS no; on Windows only the timeout), an
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
- When they're off, `function` steps and «Probar» (Test) fail with a notice.

```sh
PARLA_FUNCTIONS=0 .venv/bin/python app.py
```

## Uploaded files

Files for the «Enviar un archivo» (Send a file) step:

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
8. **Backups:** the data folder holds conversations, users and keys. Keep backups somewhere private and keep
   `users.json` and `*.secrets.json` at permissions 600 when restoring.
9. Review `http` steps, widget origins and old API keys (especially the ones from «Conectar con IA»).
10. If you use MCP with `--http`, protect it at the proxy.
11. Add a rate limit at the proxy: Parla only has one on login.

## Not there yet

- One replica per data folder. Sessions and login counters are in memory: they're lost on restart.
- No rate limiting, except the login lockout.
- No audit or access log: Parla doesn't record who changed what (the deployment log doesn't say who) and doesn't
  log requests. The Bandeja (Inbox) does record who took and replied to each conversation.
- No second factor, no password policy and no list of open sessions to end by hand.
- Keys aren't encrypted on disk. Agents and conversations are saved with the system's normal permissions (only
  `users.json` and the keys are 600).
- Personal data in saved conversations isn't masked, and conversations aren't deleted automatically.

## Reporting a vulnerability

Don't open a public issue. Open a private security advisory at
<https://github.com/pedroslev/parla-nlu/security/advisories/new> (**Security → Report a vulnerability** on the
repository), with steps to reproduce it. The full policy is in [SECURITY.md](../SECURITY.md).
