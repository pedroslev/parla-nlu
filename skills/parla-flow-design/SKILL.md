---
name: parla-flow-design
description: Conversation design for Parla flows - steps (message, ask, set, if, goto, call, end, classify, handoff, file, agent, remind), good questions and re-asks, buttons and their per-channel limits (WhatsApp, Telegram, web), CEL conditions and templates, start flow and preloaded data, corrections, interruptions (interrupts false/always), system flows (cancel, repeat, clarify, resume, handoff, csat, anything_else), fallbacks, voice-friendly wording and multilingual bots, and reminders / flows for outbound messages (consent, WhatsApp templates, opt-out). Use it when designing or reviewing the flows of a Parla agent, writing the bot's messages and questions, or fixing a flow that skips questions, loops, ends early or handles digressions badly.
---

# Flow design for Parla

## How a flow runs (the behaviour you design around)

- A flow starts when its `trigger` intent is detected, at conversation start (`"__start__"`, only one per agent),
  or via `goto`/`call` (`"trigger": ""`). If two flows share a trigger, the first one wins.
- Steps run in order until an `ask` waits for an answer, a `handoff` happens, the flow ends or a step fails.
- **An `ask` whose slot already has a value is skipped.** Slots fill from entities in the triggering message
  («turno de limpieza el 15/12 a las 10» skips two questions), from start data and from earlier flows.
  Clear re-askable slots with `set` `mode: "clear"` when the flow is done.
- `goto` jumps to another flow and never comes back; `call` runs a subflow and returns to the next step;
  `end` finishes the flow (inside a subflow, returns to the caller). Max 5 stacked flows, max 200 steps per turn.
- A failing step (bad CEL, missing slot in a template, a function that raised with no `ok`/`error` save, a deleted
  file) shows «⚠ Hay un problema…» and **stops the conversation**. Treat every "⚠" in a test as a bug.

## Checklist

1. **One goal per flow.** «Reservar turno», «Cancelar turno», «Urgencias». Shared pieces («Validar identidad»,
   «Pedir contacto») are trigger-less subflows reached with `call`.
2. **A `__start__` greeting** that says who the bot is and offers 2–4 buttons whose `value` is a phrase that
   triggers each main intent («quiero sacar un turno»). WhatsApp does **not** run `__start__` (the first message
   goes straight to the NLU), so the main intents must work without the menu; Telegram runs it on `/start`.
3. **One question per `ask`**, short, saying the expected format when there is one: «¿Qué día y a qué hora? Por
   ejemplo: el jueves a las 10». Use entities with a format/list so a bad answer is re-asked automatically
   («No reconocí ese dato, probemos de nuevo.» + the question again).
4. **Confirm before acting** when the action is costly (bookings, payments): an `ask` on a yes/no list slot with
   buttons, then an `if` on the answer. Read the collected data back in the confirmation.
5. **Branch on results, never assume success**: `if` on the http `status` or the function's `ok` with a clear
   message and a way out (handoff or a re-ask) on the else branch.
6. **Re-ask loop**: when a value is valid for the entity but not for the business (a Sunday, a 0 quantity):
   message why → `set` the slot `clear` → `goto` the same flow. Filled slots are skipped, so only that question is
   asked again.
7. **Count outcomes**: a `classify` step where the goal is met (after the confirmation, not before) and on each
   escalation path.
8. **Escalate to people**: `handoff` with a `reason` for complaints, anger, emergencies or failures the bot can't
   solve. The bot goes silent until someone releases the conversation in the Inbox («Bandeja»).
9. **Mark small talk** flows (greeting, thanks) `"interrupts": false` and true emergencies `"interrupts": "always"`.
10. **Keep the system flows on** (cancel, repeat, clarify, correction, resume, handoff); customise their `text` and
    add domain `examples` instead of building your own. Turn on `csat` if the business measures satisfaction.
11. Test every branch (see `parla-testing-and-release`).

## Buttons

`"buttons": [{"label": "Sí, confirmar", "value": "si"}]` on a `message` or `ask` (`value` defaults to the label).

- In an `ask`, pressing stores the `value` in the slot — use the list entity's canonical values as `value`.
- In a `message`, pressing is the same as typing the `value`: make it a phrase that triggers the intent.
- Typing the label or the value by hand also counts as pressing.
- 2–6 options; validate warns above 10. Labels must be unique within a step.
- Channels: **WhatsApp** shows 1–3 as reply buttons (titles cut to 20 characters) and 4–10 as a list (24
  characters); more than 10 are dropped. **Telegram** shows one button per row, all of them. Values longer than
  200 bytes (WhatsApp) or 64 (Telegram) travel as `#n` and are mapped back. Keep labels ≤ 20 characters.
- Voice calls don't show buttons: write the options in the question text too.

## Conditions, templates and `set`

- `{{ slot }}` or `{{ CEL }}` in any text, url, header or body. Variables: every slot, `intent`, `confidence`,
  `text` (current message), `entities` (`{entity: value}` of the current message); in http `saves` also
  `status`/`body`; in function `saves` also `result`/`ok`/`error`. An empty slot renders as "".
- `if` with `cond` `{var, op, value}` (`eq ne contains` compare as case-insensitive text, `gt lt` as numbers,
  `empty filled`). `cond.var` must be a slot. JSON booleans/numbers compare as their JSON text: `"true"`,
  `"201"`.
- `if` with `expr` (CEL) for anything else: `"int(cantidad) > 3 && tratamiento == 'limpieza'"`,
  `"has(entities.fecha)"`. The `then` branch runs only when it evaluates to exactly `true`.
- Slots are text: convert with `int()`/`double()`. `int("")` fails → check `filled` first.
- `set` modes: `text` (template), `clear`, `cel` (`"expr": "int(cantidad) * 9500"`).

## Digressions, corrections, interruptions

While an `ask` waits, Parla tries, in order: system intents (cancel/repeat/handoff, with a stricter threshold) →
flows with `"interrupts": "always"` (cut everything, don't come back) → a side question the knowledge base can
answer (answers it and asks again) → a correction of an earlier answer of this flow («mejor un control» →
«Listo, lo cambié.» and continues from there) → the answer → if the answer is invalid and the message is another
clear intent (≥ 0.75), that flow runs as an interruption and then `resume` says «Sigamos con lo de antes.» and
repeats the question. Design consequences:

- Put FAQ content in `knowledge` so mid-question questions get answered without losing the flow.
- Free-text questions (slot without entity) accept anything, so they can't be interrupted by intents — prefer
  entities where a format exists.
- Corrections only touch slots **this flow already asked** before the current question. For a value the bot
  *proposed* (a slot it set itself), use `ask.also: ["fecha"]`: «¿Te sirve el lunes a las 9?» → «mejor el
  jueves» leaves the slot empty, the flow continues and the next steps read `entities.fecha`
  (`{"type": "if", "expr": "has(entities.fecha)", …}`).
- **Cancel stops the flow but keeps the slots.** If the person starts again, already-answered questions are
  skipped. Usually fine (name, phone); clear sensitive or per-attempt slots at the start of a retry path if not.

## Fallback and clarify

- `fallback`: a list of 3–4 variants (one is picked at random, never the same twice in a row) that say what the
  bot can do: «Perdón, no lo entendí. Puedo darte un turno, cancelarlo o contarte horarios.»
- Before the fallback Parla tries the knowledge base and, with AI, a rescue and a generative re-prompt (see
  `parla-integrations`). `clarify` handles near ties between two intents with buttons.

## Writing for chat and voice

- Short sentences, one idea each, one question per turn, the question last.
- Use the person's words and register (voseo for Argentina). No jargon, no internal codes.
- Voice (calls, IVR, `Llamada (voz)`): no emojis, URLs, tables or «tocá el botón»; spell options out; read back
  numbers and dates in words-friendly form (format ISO dates with a function: «martes 15/12 a las 10:00»), and
  confirm critical data before acting.
- Never promise what the flow doesn't do («te mandamos un mail» only if a step does it).

## Multilingual bots

`"languages": ["es", "pt"]` (first = default) + `translations` on every `message`/`ask`/`handoff`/`file`, on button
labels and on system flow texts, + `fallback_translations`. The language comes from start data
(`{"idioma": "pt"}`) or the first message. Validate warns about missing `fallback_translations`.

## Reminders and flows that write first

The `remind` step schedules a message to the same person and channel for later; campaigns and the outbound API
start a conversation with a flow (see `docs/outbound.md`).

```json
{"type": "remind", "after": "24h", "flow": "Recordatorio turno", "template": "recordatorio_turno"}
{"type": "remind", "at": "{{ fecha }} 09:00", "text": "Hola {{ nombre }}, te esperamos hoy a las {{ hora }}."}
```

- `after` (`30m`, `24h`, `2d`) **or** `at` (a template that renders as `YYYY-MM-DD HH:MM`, in
  `agent.outbound.timezone`); `flow` **or** `text`. The flow runs later with the slots the conversation has now,
  so collect what the reminder needs (name, date, time) before the `remind` step.
- **Consent first.** Only remind people who asked for it or expect it (they just booked). Ask «¿Querés que te
  recuerde el turno el día anterior?» when in doubt, and `if` on the answer before `remind`.
- **One reminder per thing**: one per appointment, placed after the confirmation, never in a step that runs on
  every turn. Don't stack several reminders for the same event.
- **Mind the clock.** `at` with a fixed hour in business time (`"{{ fecha }} 09:00"`), not «after 8h» that can land
  at 3 a.m.; set `agent.outbound.timezone`. Campaigns take `quiet_hours`.
- **WhatsApp after 24 hours needs a template.** If the reminder can go out more than 24 hours after the person's
  last message, set `template` to an approved one from `channels.whatsapp.templates` (its `params` are slots, in
  `{{1}}`, `{{2}}` order). The flow then runs when the person replies to the template, so write the flow as the
  answer to it: no greeting again, go straight to «¿Confirmás?» with buttons.
- **Say who you are and why** in the first line, and **offer the way out**: «Respondé BAJA si no querés recibir
  más avisos.» Opt-outs (STOP, BAJA…) are handled by Parla; don't build an intent for them.
- **Keep it short and actionable**: one message with 2–3 buttons (Confirmar / Cambiar / Cancelar) that map to
  flows. On calls (phone reminders and outbound calls, which call the `caller` slot) the first sentence is who is
  calling; there is no answering machine detection.
- Low frequency: campaigns default to 20 per minute; don't use reminders as a drip-marketing engine.

## Anti-patterns

- A flow that asks everything again because slots weren't cleared — or never asks because they weren't.
- `goto` to come back to a caller (use `call`), or `call` of the flow itself (loop error).
- Assuming an http call or function worked; leaving the else branch empty.
- Buttons with 11 options, labels over 20 characters, or `value`s that don't match the list entity.
- Own «cancelar»/«hablar con una persona» intents; turning `system.cancel`/`system.handoff` off.
- Long paragraphs, several questions in one message, emojis and links in voice bots.
- `classify` before the goal is actually met.
- A `remind` step without consent, in a loop, at night, or without a `template` when it can go out after 24 h on
  WhatsApp.

## Worked example

Greeting menu, a subflow with `call`, a confirmation with buttons (answering «mejor el jueves a las 11» there is
a correction: the date changes and the confirmation is asked again), an urgent interruption, a non-interrupting
thanks flow, CSAT and Portuguese translations:

```json parla-agent
{
  "name": "Veterinaria Patitas",
  "languages": ["es", "pt"],
  "fallback": ["No te entendí. Puedo darte un turno o pasarte con la guardia."],
  "fallback_translations": {"pt": ["Não entendi. Posso marcar uma consulta ou te passar para o plantão."]},
  "intents": [
    {"name": "Pedir turno", "examples": ["quiero un turno para mi perro", "necesito turno con el veterinario",
      "¿me das un turno para [mañana](fecha)?", "quería vacunar al gato", "sacame un turno", "turno",
      "quero marcar uma consulta"]},
    {"name": "Urgencia", "examples": ["mi perro se envenenó", "mi gato no respira bien", "es una emergencia",
      "lo atropelló un auto", "está convulsionando", "urgente, sangra mucho", "é uma emergência",
      "mi perro comió veneno para ratas", "a mi gato le cuesta respirar", "mi perro está muy mal, no se levanta"]},
    {"name": "Agradecer", "examples": ["gracias", "muchas gracias", "genial, gracias", "dale, gracias", "obrigado"]}],
  "entities": [
    {"name": "fecha", "kind": "date"},
    {"name": "telefono", "kind": "phone"},
    {"name": "confirma", "kind": "list", "values": ["si", "no"],
     "synonyms": {"si": ["sí", "dale", "ok", "sim"], "no": ["nop", "não"]},
     "phrasings": {"si": ["está perfecto", "me sirve"], "no": ["no me sirve", "mejor otro día"]}}],
  "slots": [{"name": "fecha", "entity": "fecha"}, {"name": "telefono", "entity": "telefono"},
            {"name": "mascota", "entity": ""}, {"name": "confirma", "entity": "confirma"}],
  "classifications": [{"name": "Turno dado", "color": 1}, {"name": "Urgencia", "color": 5}],
  "flows": [
    {"name": "Bienvenida", "trigger": "__start__", "steps": [
      {"type": "message", "text": "¡Hola! Soy el asistente de Patitas. ¿Qué necesitás?",
       "translations": {"pt": "Olá! Sou o assistente da Patitas. Do que você precisa?"},
       "buttons": [{"label": "Turno", "value": "quiero un turno para mi perro", "translations": {"pt": "Consulta"}},
                   {"label": "Urgencia", "value": "es una emergencia", "translations": {"pt": "Emergência"}}]}]},
    {"name": "Contacto", "trigger": "", "steps": [
      {"type": "ask", "slot": "telefono", "text": "¿A qué teléfono te llamamos?",
       "translations": {"pt": "Para qual telefone ligamos?"}}]},
    {"name": "Turno", "trigger": "Pedir turno", "steps": [
      {"type": "ask", "slot": "mascota", "text": "¿Cómo se llama tu mascota y qué es? Por ejemplo: Toby, perro.",
       "translations": {"pt": "Qual o nome do seu pet e o que ele é? Por exemplo: Toby, cachorro."}},
      {"type": "ask", "slot": "fecha", "text": "¿Qué día y a qué hora te queda bien?",
       "translations": {"pt": "Que dia e horário fica bom?"}},
      {"type": "call", "flow": "Contacto"},
      {"type": "ask", "slot": "confirma",
       "text": "Turno para {{ mascota }} el {{ fecha }}. ¿Lo confirmo?",
       "translations": {"pt": "Consulta para {{ mascota }} em {{ fecha }}. Confirmo?"},
       "buttons": [{"label": "Sí", "value": "si", "translations": {"pt": "Sim"}},
                   {"label": "No", "value": "no", "translations": {"pt": "Não"}}]},
      {"type": "if", "cond": {"var": "confirma", "op": "eq", "value": "si"},
       "then": [{"type": "message", "text": "¡Listo! Te esperamos.", "translations": {"pt": "Pronto! Te esperamos."}},
                {"type": "classify", "classification": "Turno dado"}],
       "else": [{"type": "message", "text": "Dale, no lo agendé.", "translations": {"pt": "Tudo bem, não marquei."}}]},
      {"type": "set", "slot": "fecha", "mode": "clear"}, {"type": "set", "slot": "confirma", "mode": "clear"}]},
    {"name": "Guardia", "trigger": "Urgencia", "interrupts": "always", "steps": [
      {"type": "classify", "classification": "Urgencia"},
      {"type": "handoff", "reason": "urgencia veterinaria", "text": "Te paso ya con la guardia.",
       "translations": {"pt": "Vou te passar agora para o plantão."}}]},
    {"name": "De nada", "trigger": "Agradecer", "interrupts": false, "steps": [
      {"type": "message", "text": "¡De nada!", "translations": {"pt": "De nada!"}}]}],
  "system": {"handoff": {"enabled": true, "text": "Te paso con alguien del equipo.",
                         "translations": {"pt": "Vou te passar para alguém da equipe."},
                         "examples": ["quiero hablar con el veterinario", "pasame con alguien"]},
             "csat": {"enabled": true, "text": "¿Cómo te atendí? Del 1 al 5.",
                      "translations": {"pt": "Como foi o atendimento? De 1 a 5."}}}
}
```

Step-by-step field reference and more patterns: [reference.md](reference.md).
