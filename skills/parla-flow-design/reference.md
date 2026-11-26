# Flow steps and patterns (reference)

The authoritative field list is `agent_format_guide`. This is the cheat sheet plus the patterns that work.

## Steps

| `type` | Fields | Behaviour |
|---|---|---|
| `message` | `text`, `translations?`, `buttons?` | Sends text (templates allowed). Button `value` = what the person "types". |
| `ask` | `slot`, `text`, `translations?`, `buttons?`, `also?` | Skipped if the slot has a value. Waits; re-asks on invalid format/list answers. |
| `set` | `slot`, `mode` (`text` + `text` / `clear` / `cel` + `expr`) | Stores a value. |
| `if` | `cond {var, op, value}` **or** `expr` (CEL); `then`, `else` (nested steps) | `cond.var` must be a slot. `expr` must give exactly `true`. |
| `goto` | `flow` | Continues in another flow from its first step. Never returns. Can target the current flow (re-ask loop). |
| `call` | `flow` | Runs a subflow and returns to the next step. Not the flow itself. Max depth 5. |
| `end` | — | Ends the flow; inside a subflow returns to the caller. |
| `classify` | `classification` | Tags the conversation (must exist in `classifications`). Silent. Counted once. |
| `handoff` | `reason`, `text?`, `translations?` | Hands over to the Inbox; bot silent until released. Without `text`, uses `system.handoff.text`. |
| `http` | `method`, `url`, `headers [{key, value}]`, `body`, `saves [{expr, slot}]` | See `parla-integrations`. |
| `function` | `function`, `auto_save?` (default true), `saves [{expr, slot}]` | See `parla-integrations`. |
| `file` | `file` (id or name from `list_files`), `text?`, `translations?` | Sends an uploaded file. |
| `agent` | `instructions`, `goal`, `functions?`, `tools?`, `slots?`, `knowledge?`, `max_turns?`, `max_tool_calls?`, `time_budget?` | AI island; needs `ai.enabled`. Tools (function / http / mcp): see `parla-integrations`. |

## Flow fields

`{"name", "trigger", "steps", "interrupts"?}` — `trigger`: an intent name, `"__start__"` or `""`.
`interrupts`: `true` (default), `false` (small talk: never cuts a pending question, the AI never offers it as
another action), `"always"` (emergencies: cuts the question even if the message carries the asked data, and
doesn't come back).

## System flows (`system`)

| Key | Default | Fields | Notes |
|---|---|---|---|
| `cancel` | on | `examples`, `text`, `translations` | Stops the current flow (slots are kept). |
| `repeat` | on | `examples` | Repeats the bot's last messages; the pending question stays pending. |
| `clarify` | on | `margin` (0.04), `text` («¿Quisiste decir…?») | Buttons with the two intent names: name intents so they read well to users. |
| `correction` | on | `text` («Listo, lo cambié.») | Only slots asked earlier in the current flow. |
| `resume` | on | `text` («Sigamos con lo de antes.») | After an interruption. |
| `handoff` | on | `examples`, `text` | «quiero hablar con una persona». |
| `anything_else` | off | `text` | After a flow finishes. |
| `csat` | off | `text` | After the conversation's first finished flow: 1–5 buttons; accepts «4» or «4/5». Shows in `get_analytics`. |

`examples` of cancel/repeat/handoff are trained as the intents `__cancel__`, `__repeat__`, `__handoff__`
(usable in tests as `"intent": "__handoff__"`). validate warns if you turn off cancel or handoff.

## Templates and CEL cheat sheet

```text
{{ nombre }}                                   slot (empty slot → "")
{{ nombre != null ? nombre : "che" }}          default value
{{ int(cantidad) * 9500 }}                     maths: slot values are text
{{ promo ? ' (con 10% off)' : '' }}            booleans saved from a function
size(x) > 3   x.contains("a")   x.startsWith("a")   x.matches("^\\d+$")
has(body.code)   has(entities.fecha)           optional fields
```

A template or CEL that names something that doesn't exist fails the step with "⚠" — `validate_agent` catches
unknown slot names, not runtime type errors (`int("")`, a missing `body` field without `has()`).

## Patterns

**Greeting menu** — `__start__` flow with a `message` whose buttons' `value`s are training phrases of the
intents. Add a `Saludar` intent with the same menu for channels without a start event (WhatsApp).

**Confirm, then act**

```text
ask confirma (list si/no, buttons Sí/No, text reads back the data)
if confirma eq "no" → message "no hice nada" + clear + end
http/function … → if status/ok … else handoff
```

**Re-ask for a business rule** — `function`/`if` detects the problem → `message` why → `set` slot `clear` →
`goto` the same flow (asks with values are skipped, only the cleared one is asked again).

**Shared subflow** — `{"name": "Validar identidad", "trigger": ""}` with the `ask`s and the lookup; every flow
that needs it starts with `{"type": "call", "flow": "Validar identidad"}`.

**Preloaded data** — slots named like the start data keys (`dni`, `telefono`) are filled before `__start__` runs;
mark them `"start": true` so the UI's «Empezar con datos» shows them. `if cond empty` → `ask`, else greet by name.

**Counter-offer** — the bot proposes a slot it set itself and asks a yes/no with `also: ["fecha"]`; on «mejor el
jueves» the yes/no slot stays empty and `if expr has(entities.fecha)` handles the new date.

**Escalation** — `classify` (to count) then `handoff` with a `reason` the human will read.

**Clear at the end** — `set clear` for every slot that must be asked again next time (the order details), keep
identity slots (name, phone) unless the business says otherwise.

## Voice checklist

- ≤ 2 sentences per message, the question last; options spelled out («limpieza, control u ortodoncia»).
- No emojis, URLs, markdown, «tocá el botón», ISO dates or codes read digit by digit without need.
- Confirm numbers and dates back before acting.
- Fixed texts are pre-rendered to audio when a voice is installed; texts with `{{ }}` are synthesised live.
