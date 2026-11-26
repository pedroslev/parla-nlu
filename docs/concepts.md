# Concepts

**English** · [Español](concepts_es.md)

## Agent

An **agent** (or bot) is a JSON file with everything that defines it. The main fields:

| Field | What it is |
|---|---|
| `name` | Name. Its lowercase, accent-free version (*slug*) is used in URLs: «Pizzería Don Luis» → `pizzeria-don-luis`. |
| `threshold` | Minimum confidence (0 to 1) to accept an intent. `0.75` in a new agent. |
| `fallback` | What it says when it doesn't understand. Text or a list (it picks one at random without repeating the previous one). |
| `languages` | Languages; the first one is the default. E.g. `["es", "pt", "en"]`. Without this field, `["es"]`. |
| `fallback_translations` | `{"pt": "...", "en": "..."}` (text or list). |
| `intents`, `entities`, `slots`, `flows` | See below. |
| `classifications` | `[{"name", "color", "description"}]` to tag conversations and build reports. |
| `functions` | Python or JavaScript code run by a `function` step. |
| `knowledge`, `knowledge_threshold` | Knowledge base (`[{"id", "title", "source", "url", "text"}]`) and its minimum score (`0.75` by default). |
| `system` | System flows (see below). |
| `ai` | AI, local by default (see [ai-and-voice.md](ai-and-voice.md)). `provider`: `"ollama"` (default), `"openai"` (without `url`, `https://api.openai.com/v1`; with a `url`, any OpenAI-compatible server, as before), `"openai_compatible"` (same protocol, your own `url`: vLLM, llama.cpp, LM Studio, LocalAI, Azure OpenAI, Groq, OpenRouter), `"anthropic"` (Claude) or `"gemini"`. `api_key_secret` is the **name** of a vault key; if absent, `OPENAI_API_KEY`, `ANTHROPIC_API_KEY` or `GEMINI_API_KEY`. |
| `voice` | `{"asr": {"provider", "model"?, "api_key_secret"?}, "tts": {"provider", "voice"?, "model"?, "api_key_secret"?}}`: speech recognition and the bot's voice. `provider`: `"local"` (default: faster-whisper / piper, nothing leaves the machine), `"openai"`, `"deepgram"`, `"elevenlabs"` or `"google"`. Default key names: `OPENAI_API_KEY`, `DEEPGRAM_API_KEY`, `ELEVENLABS_API_KEY`, `GOOGLE_API_KEY`. |
| `mcp_servers` | `[{"name", "url", "headers_secret"}]`: MCP servers whose tools an `agent` step can use (see [`agent`](#agent-let-the-ai-converse)). |
| `widget` | `{"enabled", "origins", "title", "color", "greeting", "position", "voice"}`. |
| `channels` | `{"public_url", "whatsapp": {"enabled", "phone_number_id"}, "telegram": {"enabled"}}`. Tokens go in the vault, see [channels.md](channels.md). |
| `ignored_phrases` | Phrases that **Improve** no longer shows. |
| `tests` | Conversation tests: expected conversations that run before publishing to production (see [testing-bots.md](testing-bots.md)). |
| `retention_days` | Days to keep conversations with no activity. Absent or `null`: `PARLA_RETENTION_DAYS`; `0`: forever. See [Retention and personal data](#retention-and-personal-data). |
| `pii_redaction` | Mask personal data in stored conversations: `false` (default), `true` (everything) or a list of categories. Same section. |

Exporting an agent downloads that JSON; importing it creates a new agent. Versions, environments, training, secrets
and uploaded files are not included (it is trained when opened), and neither are `retention_days` and
`pii_redaction`.

## Intent

What the person wants to do: `{"name": "Pedir pizza", "examples": ["quiero una pizza", "una de [muzza](gusto)"]}`.

Parla turns each phrase into a vector (model `google/embeddinggemma-300m` via fastembed, with the prefix
`task: sentence similarity | query: `) and compares the message against all of them: the intent of the most similar
phrase wins (nearest neighbor). That is why adding a phrase doesn't require training a heavy model, and why it works
across languages. The confidence is the cosine similarity with that phrase.

Names starting with `__` are reserved: `__start__` and the intents of the system flows (`__cancel__`, `__repeat__`,
`__handoff__`).

## Entity

A piece of data inside the message. Types (the `kind` in the JSON):

| `kind` | In the UI | How it is recognized |
|---|---|---|
| `examples` | From the examples I mark in the phrases | A CRF (python-crfsuite) learns from the context of the marked values, like Rasa's `CRFEntityExtractor`. Stores the value as it was written. |
| `list` | From a list of options | `values` and `synonyms` (`{"muzzarella": ["muzza"]}`): stores the canonical value. |
| `number`, `email`, `phone`, `dni` | Número, email, teléfono, DNI (number, email, phone, national ID) | A regex set by the UI. |
| `date` | Date or time | Rules for Rioplatense Spanish (`dates.py`): «mañana», «el jueves que viene a la tarde», «15/12 a las 10». Stores `YYYY-MM-DD` or `YYYY-MM-DDTHH:MM`. |
| `custom` | A custom format (regex) | Your regex (case-insensitive). If it has a group, stores group 1. |

In practice the engine decides by the fields, not by `kind`: if there is a `regex`, it uses the regex; if there are
`values`, the list; if it is `date`, the date rules; if it has none of those, the CRF learns it. Marks in phrases are
written `[value](entity)` and also add that value as a known form. What is recognized with certainty (format, list)
takes priority over what the CRF guesses.

Optional, JSON only (the UI doesn't edit it yet): `phrasings`, other ways of saying each option of a list, used to
[understand answers by meaning](#understanding-an-answer-by-meaning):

```json
{"name": "modalidad", "kind": "list", "values": ["presencial", "virtual"],
 "phrasings": {"virtual": ["desde mi casa", "por videollamada"], "presencial": ["voy al consultorio"]}}
```

## Slot

The conversation's memory: `{"name": "gusto", "entity": "gusto"}`. When the entity appears, it is stored in the
slot. While the bot is waiting for an answer, only the slot it asked for is filled (so the number in an address
doesn't end up in `cantidad`).

- Without an entity (or with an `examples` entity), the whole answer to the question is stored.
- With AI: `{"name": "nombre", "fill": "ai", "description": "el nombre y apellido de la persona"}` lets the AI read
  the value from the message (only if it is written there).
- `"start": true` marks it as initial data: **Start with data** in the test chat shows only those.
  It doesn't change the engine: when a conversation is started through the API, any `data` field named like a slot
  is stored.

## Flow

A list of steps triggered by an intent:

```json
{"name": "Pedido", "trigger": "Pedir pizza", "steps": [ ... ]}
```

- `"trigger": "__start__"` runs the flow as soon as the conversation starts (`start` event).
- `"trigger": ""` = only reachable with `goto` or `call`.
- If two flows have the same trigger, the first one wins.
- `interrupts` (optional, JSON only): `false` for small-talk flows (greeting, thanking) that never cut off a pending
  question; `"always"` for urgent ones: it cuts off the question, even if the message carries the requested data, and
  doesn't come back. Default `true` (see [while waiting for an answer](#while-waiting-for-an-answer)).

## Step types

### `message`: send a message
```json
{"type": "message", "text": "Hola {{ nombre }}", "translations": {"pt": "Olá {{ nombre }}"},
 "buttons": [{"label": "Ver menú", "value": "quiero ver el menú"}]}
```
Tapping a button is the same as typing its `value` (or the `label` if it has none). Typing the label or the value by
hand also counts as tapping it. Buttons also accept `translations` for the label.

### `ask`: ask a question
```json
{"type": "ask", "slot": "gusto", "text": "¿De qué gusto?", "buttons": [{"label": "Muzzarella", "value": "muzzarella"}]}
```
If the slot already has a value, the step is skipped. Tapping a button stores its `value` in the slot. What happens
with the answer is described in [while waiting for an answer](#while-waiting-for-an-answer).

`also` (optional, JSON only): other entities that also count as an answer. If the answer doesn't carry the slot's
entity but does carry one of these («el jueves» to «¿te sirve el lunes?»), the slot stays empty and the flow
continues: the following steps read `entities` and decide.
```json
{"type": "ask", "slot": "confirma", "text": "¿Te sirve el lunes a las 9?", "also": ["fecha"]},
{"type": "if", "expr": "has(entities.fecha)", "then": [ ... ], "else": [ ... ]}
```

### `set`: store a value
```json
{"type": "set", "slot": "saludo", "mode": "text", "text": "Hola {{ nombre }}"}
{"type": "set", "slot": "total", "mode": "cel", "expr": "int(cantidad) * 5000"}
{"type": "set", "slot": "gusto", "mode": "clear"}
```

### `http`: call a service
```json
{"type": "http", "method": "GET", "url": "https://api.ejemplo.com/pedidos/{{ numero }}",
 "headers": [{"key": "Authorization", "value": "Bearer {{ secret.API_KEY }}"}], "body": "",
 "saves": [{"expr": "status", "slot": "codigo"}, {"expr": "body.estado", "slot": "estado"}]}
```
Timeout 10 s; up to 1 MB of the response is read. With a `body`, `Content-Type: application/json` is added. In the
URL, each `{{ }}` is encoded (what the person typed can't change the address), except `{{ secret.X }}`; a header
with line breaks is an error. In `saves`, expressions see `status` (0 if it couldn't connect) and `body` (JSON or
text). A value that didn't come back is `null`. A 4xx/5xx doesn't stop the flow: decide with an `if` on the code.

### `if`: take a branch
```json
{"type": "if", "cond": {"var": "codigo", "op": "eq", "value": "200"},
 "then": [{"type": "message", "text": "Encontrado"}], "else": [{"type": "message", "text": "No existe"}]}
```
Operators: `eq`, `ne`, `contains` (as text, case-insensitive), `gt`, `lt` (as numbers), `empty`, `filled`. Instead
of `cond` you can use `"expr"` with a CEL expression: the `then` branch runs only if it evaluates to `true`.

### `goto`: continue with another flow
```json
{"type": "goto", "flow": "Pedido"}
```
Jumps to the start of another flow and doesn't come back. (It also accepts the name in `"goto"`.)

### `call`: call another flow (and come back)
```json
{"type": "call", "flow": "Pedir dirección"}
```
When the subflow finishes, it continues with the next step. Up to 5 stacked flows (subflows and interruptions).

### `end`: finish
```json
{"type": "end"}
```
In a subflow, returns to the caller. On a phone call, it hangs up after saying what came before
([channels.md](channels.md#phone-calls-twilio-and-jambonz)).

### `classify`: classify the conversation
```json
{"type": "classify", "classification": "Venta"}
```
The conversation is tagged (each classification counts only once per conversation) and shows up in the reports.

### `file`: send a file
```json
{"type": "file", "file": "Lista de precios.pdf", "text": "Acá tenés la lista, {{ nombre }}"}
```
Sends a file you uploaded to the bot from the step itself (PDF, image, Word, Excel, PowerPoint, CSV, TXT or ZIP, up
to 10 MB). `file` is the id or the name (with repeated names, the last one uploaded); `text` is optional (without
text, the message is the file name). In the API the message arrives in `messages` as usual and `replies[i].file`
carries `{id, name, mime, size, url}`; `url` (`/files/<agent>/<id>`) opens without a session: the id is random and
acts as the key, so don't upload anything private. Files belong to the bot, not to a version: if you delete one, the
step also fails in what is published. Exporting the bot doesn't include the files.

### `function`: run a function
```json
{"type": "function", "function": "precio", "auto_save": true,
 "saves": [{"expr": "result.total", "slot": "total"}, {"expr": "ok", "slot": "salio_bien"}]}
```
The function is defined in `functions`:
```json
{"name": "precio", "language": "python", "inputs": ["gusto", "cantidad", "secret.API_KEY"],
 "code": "def run(inputs):\n    return {\"total\": int(inputs[\"cantidad\"]) * 5000}"}
```
It receives the slots it declares in `inputs` (and `inputs["secret"]["API_KEY"]`). Whatever it returns under a slot's
name is stored automatically (`auto_save`, on by default). If it fails and no `saves` looks at `ok` or `error`, the
flow stops with a warning. Timeout 5 s. JavaScript requires Node.js. The **Functions** section has
ready-to-use examples and a button to test them. See [security.md](security.md): it is not a sandbox.

### `handoff`: hand over to a person
```json
{"type": "handoff", "text": "Te paso con alguien del local.", "reason": "reclamo"}
```
The bot goes quiet and the conversation appears in the **Inbox** until a person hands it back. Without
`text`, it uses the one from `system.handoff`.

### `agent`: let the AI converse
```json
{"type": "agent", "instructions": "Ayudá a elegir un gusto y averiguá la dirección.",
 "functions": ["precio"], "knowledge": true, "slots": ["gusto", "direccion"],
 "goal": "cuando tengas el gusto y la dirección", "max_turns": 8}
```
An AI island inside the flow: it converses, can call only the listed functions, fills the listed slots and finishes
when it meets the goal or runs out of turns; then it continues with the next step. Requires AI to be enabled.

**Tools.** With `tools` the model can look things up on its own (`functions` still works and is the same as
`function` tools):
```json
"tools": [
  {"type": "function", "name": "precio"},
  {"type": "http", "name": "buscar_pedido", "description": "Estado de un pedido por número",
   "params": {"pedido": "número de pedido"}, "method": "GET",
   "url": "https://api.ejemplo.com/pedidos/{{ pedido }}",
   "headers": [{"key": "Authorization", "value": "Bearer {{ secret.API_KEY }}"}], "body": ""},
  {"type": "mcp", "server": "crm", "tools": ["get_customer"]}
],
"max_tool_calls": 2, "time_budget": 12
```
- `http` works like an `http` step: the model only fills the `params` (`{name: "description"}` or
  `{name: {"type": "string|integer|number|boolean", "description", "required"}}`), which are URL-encoded in the URL
  and JSON-escaped in the body. The host is fixed in `url`; the model never chooses it.
- `mcp` uses a server from the agent's `mcp_servers` (Streamable HTTP; `headers_secret` is the *name* of a vault
  secret sent as `Authorization`, `Bearer <value>` if it has no space). `tools` is a mandatory allow-list: the model
  only sees tools that are both listed and offered by the server. If the server is down, the step runs without them.
- `max_tool_calls` (1 to 10, default 3 per message) and `time_budget` (3 to 60 s, default 15) cap the lookups; on the
  phone keep 1–2 calls and ≤ 12 s.

Each call shows in the test chat trace (`IA usó buscar_pedido(...) -> bien: ...`) and in the history, with secrets
masked. In the flow editor it's the agent step's **Herramientas** section; MCP servers are set up in the **IA**
screen. If the lookup always happens, prefer a plain `ask` + `http`: faster and testable without AI. Details in
[ai-and-voice.md](ai-and-voice.md#tools-in-the-agent-step) and [security.md](security.md#tools-in-the-agent-step).

## `{{ }}` templates and CEL

Inside texts, URLs, headers and bodies, `{{ ... }}` is replaced by its value. Inside goes a slot name or a
[CEL](https://github.com/google/cel-spec) expression:

```
Tu pedido de {{ cantidad }} {{ gusto }} sale ${{ int(cantidad) * 5000 }}.
{{ nombre != null ? nombre : "che" }}
```

Available variables: all slots, plus `intent`, `confidence`, `text` (the last message) and `entities`
(`{entity: value}`). In the `saves` of `http`, also `status` and `body`; in the `saves` of `function`, `result`,
`ok` and `error`. `{{ secret.NAME }}` is only valid in the URL, headers and body of an `http` step (and as a
function input `secret.NAME`): in a message it is an error (the MCP validator flags it).

An empty slot renders as empty text. If an expression fails, the chat shows the flow, the step and the expression,
and the conversation stops.

## System flows

Conversation repairs that come enabled (or not) and are edited in `system`:

| Key | Default | What it does |
|---|---|---|
| `cancel` | on | «cancelar», «olvidalo» (cancel, forget it): stops what it was doing. |
| `repeat` | on | «¿cómo?», «repetí» (what?, repeat): repeats the last thing the bot said. |
| `clarify` | on, `margin: 0.04` | If the top two intents are above the threshold and less than `margin` apart, asks «¿Quisiste decir A o B?» (Did you mean A or B?) with buttons. |
| `anything_else` | off | When a flow finishes: «¿Te ayudo con algo más?» (Can I help you with anything else?). |
| `resume` | on | When returning from an interruption: «Sigamos con lo de antes.» (Let's continue where we left off.). |
| `correction` | on | «mejor de fugazza» (make it fugazza instead) while it asks something else: changes a value already given (only slots this flow has already asked for) and continues from that question. |
| `handoff` | on | «quiero hablar con una persona» (I want to talk to a person): hands over to the Inbox. |
| `csat` | off | When the conversation's first flow finishes: «¿Cómo te atendí? Del 1 al 5.» (How did I do? From 1 to 5.) with buttons. Accepts `4` or `4/5`. |

Each one has `enabled`, `text` (and `translations`) and, for those recognized by phrases (`cancel`, `repeat`,
`handoff`), `examples`. Those phrases are trained as system intents.

## While waiting for an answer

When an `ask` is waiting, the message is first taken as an answer. In order:

1. **System behaviors** (cancel, repeat, hand over to a person): they require more certainty than a normal intent
   (at least 0.75, or 0.92 if the question is free text) and don't count if the message already carries the
   requested data or a button was tapped. That way «Pedro» or «30.123.456» aren't mistaken for «repetí».
2. **Urgent**: a flow with `"interrupts": "always"` whose intent reaches the threshold cuts everything off and
   doesn't come back.
3. **A question instead of an answer** («¿qué es presencial?» to «¿presencial o virtual?»): if the knowledge base
   can answer it, it answers and asks again. With AI, if there is nothing in the base, it says it doesn't know
   instead of making something up. If the person then says «ah, entonces sí» (oh, then yes), it picks the option
   that was explained.
4. **Correction** of an earlier value (if `correction` is on).
5. **The answer**:
   - If the slot has an entity with a format, list or date and the answer doesn't carry it: first it checks `also`;
     then it tries to [understand it by meaning](#understanding-an-answer-by-meaning) and, with AI, asks the model
     what the person did (answered, asked, asked for something else or just said hi). If none of that works, it says
     «No reconocí ese dato, probemos de nuevo.» (I didn't recognize that, let's try again.) and asks again. It
     doesn't reply «No reconocí» to a «gracias».
   - If the answer carries two different values of the same entity («sí… no puedo»), it picks neither and asks
     again.
   - With `fill: "ai"`, the AI reads the value; if it can't find it, it asks again.
   - If the slot has no entity, it stores the whole text.
6. **Interruption**: if the answer didn't work and the message is another clear intent (at least 0.75) whose flow
   interrupts, it handles it and then returns to the question (with `resume`). If the message was read by meaning
   or with AI, it only interrupts for what that reading saw as a different action. Flows with
   `"interrupts": false` don't interrupt.

### Understanding an answer by meaning

For a list entity with `phrasings`, if the answer doesn't literally contain an option («la quiero desde mi casa»),
Parla compares it by meaning, with the same vector model, against the ways of saying each option (values, synonyms
and `phrasings`), against the phrases of the intents that could interrupt, and against small talk that answers
nothing («gracias», «un momento»). It only decides when it is clear (similarity of at least 0.60 and a 0.04 lead over
the runner-up; an intent has to beat the best option by 0.10). Otherwise it moves on to the AI or to «No reconocí».
It doesn't need generative AI. When it decides, the turn carries `via: "significado"`.

## What happens when it doesn't understand

Outside a question:

1. If AI is enabled and the confidence doesn't reach the threshold (or two intents tie), it tries to rescue the
   intent among the most similar ones.
2. If two intents are still tied, it asks «¿Quisiste decir…?» (Did you mean…?) (`clarify`).
3. If there is no intent (or the intent has no flow), it searches the knowledge base: if something reaches
   `knowledge_threshold`, it answers with that (without AI, with the chunk as is; with AI, a short controlled
   answer).
4. With AI and `generative_fallback`, it asks again and says what the bot can do.
5. Otherwise, the `fallback`.

## Language

The conversation language is the one received at start (`idioma`, `language` or `lang` in the start data) or,
otherwise, the one guessed from the words of the first message among those in `languages` (on a tie, the first one
wins). Messages use `translations[language]` if present; otherwise, the original text.

## Versions and environments

- **Draft**: what you edit.
- **Version**: a numbered, immutable copy of the draft, with its own trained model.
- **Environments**: `staging` (**Staging**) and `production` (**Production**) each point to a version.

The API talks to `production` by default (or to the draft if nothing has been published yet). Each conversation
stays tied to the version it started with: publishing doesn't change the steps in the middle of a conversation.
Rollback = pointing the environment to another version. **Use as draft** brings the draft back to what a
version had.

What belongs to the bot rather than to a version: secrets, files, conversations and the operational settings
`retention_days` and `pii_redaction` (they aren't versioned and **Use as draft** keeps them).

The conversation **tests** (section **Tests**) are part of the definition, so each version keeps its own. Publishing
to `production` runs them against the draft first and stops if any fails; publishing to `staging` and `deploy`
don't. See [testing-bots.md](testing-bots.md).

## Retention and personal data

Conversations are stored in `parla.db`, in the data folder. Both settings are in the agent's **Settings** →
**Privacy and data**.

**Retention (`retention_days`).** Conversations whose last activity is older than that many days are deleted. Without
the field (or `null`), `PARLA_RETENTION_DAYS` applies; `0`, or neither of the two, keeps them forever. The cleanup
runs at startup and every hour. Uploaded files (`file` step) belong to the agent, not to a conversation: retention
never deletes them.

**Masking (`pii_redaction`).** `true` masks every category; a list masks only those:

| Category | Becomes | What it catches |
|---|---|---|
| `email` | «[email]» | Email addresses. |
| `phone` | «[teléfono]» | Phone numbers. |
| `card` | «[tarjeta]» | 13 to 19 digits, only if they pass the Luhn check. |
| `id` | «[documento]» | CUIT/CUIL (11 digits), DNI (7 or 8 digits, with or without dots) and any other run of 9 or more digits. |
| `bank` | «[cuenta]» | CBU/CVU (22 digits) and IBAN (validated with mod 97). |

It applies to what is **stored**: the history text, entity values and the start data. So the Inbox, the
conversation viewer, **Improve**, analytics and the API's history see the masked text. It doesn't apply
to the live turn: the flow, `http` steps and functions get the real value, and that turn's reply carries the real
text. Slots and the AI context keep the real values while the conversation is open (later steps need them) and
are wiped when it ends; with masking on, conversations idle for 24 hours (not in handoff) are closed so that
happens.

Limits: it's a heuristic, so it can miss a format or mask a number that isn't personal data (an order number with 9
or more digits); the operator's replies in the Inbox are stored masked too (a widget reading the history sees
them masked); turning it on doesn't rewrite what was already stored (each conversation is masked from its next
save on); and it doesn't apply to the server's console output.
