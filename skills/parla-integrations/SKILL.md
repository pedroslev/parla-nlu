---
name: parla-integrations
description: Connecting a Parla bot to the outside world safely - http steps (secrets with {{ secret.NAME }}, URL encoding, timeouts, saving the response into slots, error branches), custom Python/JavaScript functions, file steps, the knowledge base (writing FAQ documents, chunking, knowledge_threshold), the optional AI features (rescue_intents, fill ai, generative_fallback, use_knowledge, the agent step and its tools - functions, http tools and MCP servers with allow-lists; local Ollama vs OpenAI-compatible providers and privacy), web widget, WhatsApp and Telegram channel setup, and personal-data settings (pii_redaction, retention). Use it when a Parla bot must call an API, run code, answer FAQs from documents, use an LLM, or be published on a channel.
---

# Integrations for Parla bots

## Hard rules (security)

- **You never handle secret values.** Not in the agent JSON, not in chat, not in a test. Use the *name*:
  `{{ secret.CRM_TOKEN }}` in an http step's url/headers/body, `"secret.CRM_TOKEN"` as a function input,
  `ai.api_key_secret: "OPENAI_KEY"` for the AI provider. Then tell the user: «Cargá el valor de `CRM_TOKEN` en
  Parla → Publicar → Claves». `create_agent`/`update_agent` warn about missing names; `list_secret_names` shows
  `{secrets, used, missing}`. The MCP server cannot read or write values, by design.
- `{{ secret.X }}` anywhere else (messages, set, if) is a validation error. Values of 4+ characters are masked
  (`••••`) in traces and errors, but **whatever an API returns is not**: don't save a token from a response
  into a slot that a message shows.
- Channel tokens (`WHATSAPP_TOKEN`, `WHATSAPP_APP_SECRET`, `WHATSAPP_VERIFY_TOKEN`, `TELEGRAM_TOKEN`) are also
  vault keys the user loads; the JSON only holds `channels.whatsapp.phone_number_id` and on/off switches.
- An http step can reach anything the Parla server can (internal network, `localhost`, cloud metadata). Only call
  URLs the user gave you, and say so in your report.

## http step

```json
{"type": "http", "method": "POST", "url": "https://api.example.com/reservas",
 "headers": [{"key": "Authorization", "value": "Bearer {{ secret.BOOKING_TOKEN }}"}],
 "body": "{\"fecha\": \"{{ fecha }}\", \"telefono\": \"{{ telefono }}\"}",
 "saves": [{"expr": "status", "slot": "reserva_status"}, {"expr": "has(body.code) ? body.code : ''", "slot": "codigo"}]}
```

- Methods `GET POST PUT PATCH DELETE`. With a `body`, `Content-Type: application/json` is added. Timeout **10 s**,
  up to 1 MB read, redirects followed.
- In the **URL** every `{{ }}` value is URL-encoded (a slot can't change host or path); `{{ secret.X }}` goes in
  raw. Headers with line breaks fail the step.
- The **body is not escaped**: `"{{ nombre }}"` with a quote in it breaks the JSON. Only interpolate validated
  slots (format/list entities) or build the body in a function.
- `saves` evaluate CEL over `status` (number; **0 = could not connect/timeout**) and `body` (parsed JSON or text).
  A missing field stores `null` (use `has()` for a default). A 4xx/5xx does **not** stop the flow.
- **Always branch on the status** right after: `{"type": "if", "cond": {"var": "reserva_status", "op": "eq",
  "value": "201"}, "then": [...], "else": [handoff or apology]}`.
- Test it for real with `test_conversation`; the trace shows `METHOD url → status` with secrets masked.

## function step

Use a function for real logic (price tables, check digits, date maths, reshaping an http response); a single
formula fits in `set mode cel`, and a plain API call is an http step.

```json
{"name": "formatear_fecha", "language": "python", "inputs": ["fecha"],
 "code": "from datetime import datetime\n\ndef run(inputs):\n    when = datetime.fromisoformat(inputs.get(\"fecha\") or \"\")\n    return {\"fecha_texto\": when.strftime(\"%d/%m %H:%M\")}"}
```

- Contract: `run(inputs)` gets only the declared slots (as text or `null`) and returns a JSON object; keys named
  like slots are saved automatically (`auto_save`, default true). Secrets arrive as `inputs["secret"]["NAME"]`.
  `print`/`console.log` go to the trace, never to the chat. Raise to fail.
- Limits: separate process, **5 s**, CPU/memory limits, empty temp dir, no env vars, standard library only
  (Python) / built-in modules (Node). JavaScript needs Node.js on the server. It is **not a sandbox**.
- `PARLA_FUNCTIONS=0` (default in the Docker image) disables them: every run fails. With users enabled only the
  **owner** can create or change function code (an editor's MCP key gets a 403).
- Error handling: if a save looks at `ok` or `error`, a failure doesn't stop the flow:
  `"saves": [{"expr": "ok", "slot": "f_ok"}, {"expr": "ok ? '' : error", "slot": "f_error"}]` then
  `if f_ok eq "false"`. Otherwise a failure stops the conversation with "⚠".
- Prove it first: `test_function(agent, {full definition}, inputs)` for the happy path **and** an edge case
  (empty, wrong type), then wire it.

## file step

`{"type": "file", "file": "Lista de precios.pdf", "text": "Acá tenés la lista"}`. The **user** uploads the file in
Parla (flow editor, «Enviar un archivo»); you reference it by name or id from `list_files`. Up to 10 MB; pdf,
images, Office, csv, txt, zip. The download link works without a session — nothing private. Files belong to the
agent, not to a version, and aren't exported.

## Knowledge base

Questions that need an answer but no data collection (hours, address, prices, policies, requirements) go to
`knowledge`, not to intents.

- How it's used: when no intent reaches `threshold`, the best chunk is used if its score ≥ `knowledge_threshold`
  (default 0.75). It also answers questions asked in the middle of a question (then re-asks). Without AI the
  reply is the chunk itself (≤ 600 chars, question line removed); with `ai.use_knowledge` a short answer is
  written from the top 2 chunks and discarded if it adds numbers, negations or many words that aren't there.
- Chunks are ~500 characters (max 700); `P: …\nR: …` pairs separated by a blank line stay together. Write
  **one question per pair**, the answer self-contained and short, and **several phrasings on the `P:` line**:
  `P: ¿Qué horarios tienen? ¿A qué hora abren? ¿Atienden los sábados?` (measured: 0.73 → 0.89).
- Cover the near misses: if a frequent question has no pair, the nearest chunk can still score high and give the
  wrong answer («precio del blanqueamiento» matched the cleaning price at 0.77 until it had its own pair).
- Tune with `search_knowledge` on real wordings (case and «¿» shift scores a few points). Measured on a dental
  FAQ: good paraphrases 0.72–0.90, off-topic ~0.44, so 0.70 is a reasonable `knowledge_threshold` for an FAQ
  written this way; keep 0.75 if wrong answers are costly.
- `add_knowledge(agent, title, text=...)` or `url=...` (downloads the page; HTML/PDF up to 3 MB). Same title
  replaces. No retraining needed.

## AI features (optional; `ai.enabled`)

The engine works without a language model. With AI: **the AI proposes, the engine decides**; failures fall back
to normal behaviour.

| Flag | What it does | Guardrails |
|---|---|---|
| `rescue_intents` (default on) | picks an intent when confidence < threshold or two tie | only among the top 5 above `max(0.25, threshold − 0.3)`, asked twice in reverse order |
| `use_knowledge` | writes the knowledge answer | only from the top 2 chunks; checked for invented numbers/negations |
| `generative_fallback` | rephrased «no entendí» + «Puedo ayudarte con: …» | must be a question without numbers/links; capabilities = first 8 intent names (name intents for users) |
| slot `fill: "ai"` + `description` | extracts a free value | the value must appear literally in the message |
| `agent` step | a free conversation island with tools | only listed tools (`max_tool_calls`, default 3/turn; `time_budget` 15 s), only listed slots, ends at `goal` or `max_turns` (default 8) |

- Provider: `"ollama"` (default, `http://127.0.0.1:11434`, `qwen2.5:0.5b`) keeps everything on the machine.
  `"openai"` = any OpenAI-compatible server (`url` ending in `/v1`, `model`, `api_key_secret`, `azure: true` for
  Azure). **With a hosted provider the conversation text, recent turns, persona and knowledge snippets leave the
  machine** — say so to the user and get their OK. Embeddings, intents and knowledge search always stay local.
- Use the `agent` step sparingly (advice, comparisons); collect data with `ask`. Tests through AI are flaky:
  assert loosely.

## Tools in the agent step

`tools` on an `agent` step lets the model look things up: `{"type": "function", "name"}` (same as `functions`),
`{"type": "http", "name", "description", "params", "method", "url", "headers", "body"}` (like an http step) and
`{"type": "mcp", "server", "tools": [allow-list]}` with the server in the agent's `mcp_servers` (Streamable HTTP
only; `headers_secret` = the *name* of a Claves secret sent as `Authorization`).

- **Prefer a plain flow.** If the lookup always happens (ask the order number → http → message), an `ask` + `http`
  step is faster, testable and works without AI. Tools are for when the model decides *whether* and *which*.
- **1–3 tools, short descriptions**, param names that say what they are (`pedido`, not `id`). Small local models
  (`qwen2.5:0.5b`) often skip tools or pass wrong args; `qwen2.5:1.5b`+ or a hosted model is far more reliable.
- **Read-only tools.** Never expose deletes, payments or writes to the model; do those in a flow with a confirm
  step. MCP responses (and API bodies) are untrusted data and may contain prompt injection: allow-list only the
  MCP tools you need from servers you trust.
- **The host is fixed** in `url` (`https://api.x.com/pedidos/{{ pedido }}`, never `https://{{ host }}/…`):
  args are URL-encoded; secrets only via `{{ secret.NAME }}` and masked in what the model, trace and history see.
- **Phone:** keep `max_tool_calls` 1–2 and `time_budget` ≤ 12 s.

```json parla-agent
{
  "name": "Pedidos con IA",
  "intents": [{"name": "Consultar pedido", "examples": ["¿dónde está mi pedido?", "quiero saber de mi compra", "estado del pedido"]}],
  "slots": [],
  "mcp_servers": [{"name": "crm", "url": "https://mcp.example.com/mcp", "headers_secret": "CRM_TOKEN"}],
  "ai": {"enabled": true},
  "flows": [{"name": "Pedido", "trigger": "Consultar pedido", "steps": [
    {"type": "agent", "instructions": "Ayudá a la persona con su pedido. Pedile el número y usá buscar_pedido; no inventes estados.",
     "goal": "cuando le dijiste el estado del pedido", "max_turns": 4, "max_tool_calls": 2, "time_budget": 12,
     "tools": [{"type": "http", "name": "buscar_pedido", "description": "Estado de un pedido por número",
                "params": {"pedido": "número de pedido"}, "method": "GET",
                "url": "https://tracking.example.com/pedidos/{{ pedido }}",
                "headers": [{"key": "Authorization", "value": "Bearer {{ secret.TRACKING_TOKEN }}"}], "body": ""},
               {"type": "mcp", "server": "crm", "tools": ["get_customer"]}]}]}]
}
```

## Channels

| Channel | In the JSON | The user does |
|---|---|---|
| Web widget | `widget: {enabled, origins: ["https://site.com"], title, color, greeting, position, voice}` | pastes the snippet; `origins` without trailing `/` |
| WhatsApp Cloud API | `channels: {public_url, whatsapp: {enabled, phone_number_id}}` | Meta app, permanent token → `WHATSAPP_TOKEN`, app secret → `WHATSAPP_APP_SECRET`, verify token → `WHATSAPP_VERIFY_TOKEN`, webhook in Meta |
| Telegram | `channels: {public_url, telegram: {enabled}}` | @BotFather token → `TELEGRAM_TOKEN`, then «Conectar webhook» in Canales |

Both need a public **https** address. Channels answer with what is deployed to **production** (or the draft if
nothing is published). Design notes: WhatsApp runs no `__start__` flow and only allows free-form replies within
24 h of the user's last message; buttons are capped (see `parla-flow-design`); media from users arrives as a
placeholder (`[imagen]`), voice notes aren't transcribed. Walk the user through `docs/channels.md`; never ask
them for the tokens.

## Personal data

- `pii_redaction` (`true` or a list of `email phone card id bank`) masks what is **stored** (history, entities,
  start data); the live turn, http and functions still get real values. `retention_days` deletes idle
  conversations. Both are operational settings set in «Ajustes → Privacidad y datos», not versioned; `get_agent`
  returns them, so keep them when you `update_agent`.
- Collect only what the flow needs; never echo full card or ID numbers back.

## Anti-patterns

- A token in `headers`, `body`, a function's code or a message (validate warns on hand-written credentials).
- An http step with no `if` on the status after it; trusting `body.x` without `has()`.
- Free text interpolated into a JSON body.
- A function for something `set mode cel` does; a function used without `test_function`.
- FAQ as intents; one giant knowledge document with no `P:`/`R:` structure.
- Turning on a hosted AI provider without telling the user data leaves the machine.
- Agent-step tools that write or delete; an MCP tool without an allow-list; a tool URL whose host is a `{{ }}`.

## Worked example

```json parla-agent
{
  "name": "Soporte Envíos",
  "knowledge_threshold": 0.7,
  "knowledge": [{"title": "Envíos", "text": "P: ¿Cuánto tarda el envío? ¿Cuándo llega mi compra?\nR: De 2 a 5 días hábiles en todo el país.\n\nP: ¿El envío es gratis? ¿Cuánto cuesta el envío?\nR: Es gratis desde $ 50.000; si no, cuesta $ 4.500."}],
  "intents": [{"name": "Rastrear pedido", "examples": [
    "¿dónde está mi pedido?", "quiero rastrear mi compra", "estado del pedido [48213](pedido)",
    "mi pedido [10293](pedido) no llegó", "seguimiento del envío", "¿cómo viene mi pedido?"]}],
  "entities": [{"name": "pedido", "kind": "number"}],
  "slots": [{"name": "pedido", "entity": "pedido"}, {"name": "estado", "entity": ""},
            {"name": "codigo_http", "entity": ""}, {"name": "firma", "entity": ""}],
  "functions": [{"name": "firmar", "language": "python", "inputs": ["pedido", "secret.SIGNING_KEY"],
                 "code": "import hashlib, hmac\n\ndef run(inputs):\n    key = inputs['secret']['SIGNING_KEY']\n    if not key:\n        raise ValueError('falta cargar SIGNING_KEY en Claves')\n    return {'firma': hmac.new(key.encode(), (inputs['pedido'] or '').encode(), hashlib.sha256).hexdigest()}"}],
  "flows": [{"name": "Rastreo", "trigger": "Rastrear pedido", "steps": [
    {"type": "ask", "slot": "pedido", "text": "¿Cuál es el número de pedido?"},
    {"type": "function", "function": "firmar"},
    {"type": "http", "method": "GET", "url": "https://tracking.example.com/pedidos/{{ pedido }}",
     "headers": [{"key": "Authorization", "value": "Bearer {{ secret.TRACKING_TOKEN }}"},
                 {"key": "X-Signature", "value": "{{ firma }}"}], "body": "",
     "saves": [{"expr": "status", "slot": "codigo_http"}, {"expr": "has(body.estado) ? body.estado : ''", "slot": "estado"}]},
    {"type": "if", "cond": {"var": "codigo_http", "op": "eq", "value": "200"},
     "then": [{"type": "message", "text": "Tu pedido {{ pedido }} está: {{ estado }}."}],
     "else": [{"type": "if", "cond": {"var": "codigo_http", "op": "eq", "value": "404"},
               "then": [{"type": "message", "text": "No encontré el pedido {{ pedido }}. ¿Lo revisás?"},
                        {"type": "set", "slot": "pedido", "mode": "clear"}, {"type": "goto", "flow": "Rastreo"}],
               "else": [{"type": "handoff", "reason": "el servicio de seguimiento no respondió",
                         "text": "No pude consultar el seguimiento ahora. Te paso con una persona."}]}]},
    {"type": "set", "slot": "pedido", "mode": "clear"}]}],
  "ai": {"enabled": false, "provider": "openai", "url": "https://api.openai.com/v1", "model": "gpt-4o-mini",
         "api_key_secret": "OPENAI_KEY"},
  "widget": {"enabled": true, "origins": ["https://tienda.example.com"], "title": "¿Te ayudamos?", "position": "right"},
  "channels": {"public_url": "https://bots.example.com", "whatsapp": {"enabled": false, "phone_number_id": ""},
               "telegram": {"enabled": false}}
}
```

`firmar` shows the secret-input pattern (an HMAC header for the API); it has no `ok`/`error` save on purpose: a
missing key is a setup error and should stop with a visible "⚠", not sign with an empty key. Note the slot is `codigo_http`, not
`status`: `status`, `body`, `intent`, `text`, `entities`, `confidence` are reserved names. `reason` is shown
as-is in the Inbox (no `{{ }}`). The user then loads `TRACKING_TOKEN`, `SIGNING_KEY` and, if AI is turned on,
`OPENAI_KEY` in «Claves».
