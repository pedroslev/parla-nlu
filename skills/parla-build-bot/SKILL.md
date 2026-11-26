---
name: parla-build-bot
description: End-to-end workflow for building, changing or fixing a Parla chatbot through Parla's MCP tools (agent_format_guide, validate_agent, create_agent, update_agent, test_conversation, run_tests, publish_agent, deploy_version). Use it whenever the user asks to create a bot, assistant or IVR in Parla, add a feature to an existing Parla agent, or debug why a Parla bot misunderstands, skips a question or shows a "⚠" error. Covers the tool order, small validated increments, reading validate errors and training self-check output, testing and publishing safely.
---

# Build a Parla bot

Parla bots are JSON agents (intents, entities, slots, flows, tests…) edited through the `parla` MCP server.
The engine is deterministic: an embeddings nearest-neighbour classifier picks the intent, regex/lists/CRF pick the
entities, and flows run step by step. Your job is to design that JSON well, prove it with tests and publish it
without breaking what real users get.

Related skills: `parla-nlu-design` (phrases, entities, thresholds), `parla-flow-design` (steps, questions,
buttons, handoff), `parla-integrations` (http, functions, knowledge, channels, AI), `parla-testing-and-release`
(tests, versions), `parla-migrate-from-rasa`. Read the one that matches the part you are working on.

## Ground rules

- **Never guess a field shape.** Call `agent_format_guide` (or read the `parla://format-guide` resource) once per
  session before writing JSON. It lists every step type and its exact fields. Unknown keys are ignored silently,
  so a typo like `"button"` instead of `"buttons"` does nothing and `validate_agent` will not tell you.
- **Edit the whole agent.** `update_agent` replaces the full definition: start from `get_agent`, change what you
  need, send everything back (including `tests`, or they are deleted).
- **Everything you edit is the draft.** Real users only see what is deployed to `production`. Never call
  `deploy_version` / `publish_agent(environment="production")` without the user's explicit OK.
- **Never ask for, read or write secret values** (API tokens, WhatsApp/Telegram tokens, AI keys). Reference them as
  `{{ secret.NAME }}` and tell the user to load the value in Parla's «Claves» section. `list_secret_names` shows
  which names exist and which are missing.
- **Small increments.** Add one intent + flow (or one integration) at a time, then validate → update → test.
  A 40-step change that fails is much harder to debug than four 10-step ones.

## Workflow checklist

Copy this list into your plan and tick it off:

1. **Discover.** `list_agents` (does it exist already? then `get_agent`). Ask the user only what you cannot
   decide: the business, the 3–6 things people come for, which data must be collected, which external systems
   exist (URLs, auth), languages and channels (web widget, WhatsApp, Telegram, voice).
2. **Read the format.** `agent_format_guide`. Skim the worked examples at its end.
3. **Design on paper first** (write it in your reply, short):
   - intents (user goals) → one flow each; FAQs go to `knowledge`, not intents;
   - the data each flow needs → slots, each with the right entity kind;
   - integrations (http / function), outcomes to count (`classifications`), where a human takes over (`handoff`);
   - 4+ tests: happy path, data in the first message, invalid answer, a "no"/cancel, the escalation.
4. **Create a minimal agent**: greeting `__start__` flow + the main intent/flow + its tests.
   `validate_agent` → fix every error → `create_agent` (it validates, imports and trains).
5. **Read the training report** returned in `trained.log`:
   - `self_check.summary` / `self_check.mistakes`: each mistake is a training phrase that, left out, lands on
     another intent. Rewrite or move it, or add phrases that mark the difference. Aim for 0 mistakes.
   - `self_check.confusion`: which intents bleed into each other.
   - `warnings`: few phrases, intents with no flow, learned entities marked fewer than 3 times.
6. **Try it**: `test_conversation(agent, messages=[...])` with realistic messages *not* copied from the training
   phrases. Check per turn: `intent`/`confidence`, `entities`, `answer_to` (which slot the message answered),
   `waiting_for`, `buttons`, `via`, `handoff`, `final_slots` and `problems` (any "⚠" step error).
7. **Save what matters as tests** in `"tests"` and `run_tests`. Every bug you fix becomes a test.
8. **Grow** one feature at a time: `get_agent` → edit → `validate_agent` → `update_agent` → `run_tests` →
   `test_conversation` for the new path.
9. **Secrets and files**: after `create_agent`/`update_agent`, read `warnings` for missing secrets; tell the user
   exactly which names to load in «Claves». For `file` steps, `list_files`; the user uploads files in Parla.
10. **Release**: `diff_agent` → `publish_agent(note=..., environment="staging")` →
    `run_tests(environment="staging")` → show the user the result → only with their OK:
    `publish_agent(..., environment="production", confirm=True)` or `deploy_version(..., confirm=True)`.
    See `parla-testing-and-release`.
11. **Report**: what the bot does, its intents/flows, test results, version numbers, the slug for the API
    (`/api/v1/bots/<slug>/events`) and anything the user still has to do (secrets, files, channel setup).

## Reading `validate_agent`

`{ok, errors, warnings}`. **Errors** mean the bot breaks or behaves differently from what the JSON suggests: fix
all of them (`create_agent`/`update_agent` refuse to save otherwise). **Warnings** are quality problems: fix them
unless you can say why they don't apply. The common ones and what to do:

| Message is about | Fix |
|---|---|
| a slot used in `{{ }}`, a `cond` or CEL that "is not a slot" | create the slot, or fix the name (lowercase, `_`, no leading digit; not `intent`, `text`, `status`, `body`…) |
| `{{ secret.X }}` outside an http step | secrets only go in http url/headers/body or as a function input `secret.X` |
| trigger is not an intent | the flow's `trigger` must equal an intent name exactly, or be `__start__` / `""` |
| a mark `[x](ent)` with an unknown entity | create the entity or fix the mark |
| entity kind inconsistent (`examples` with values, `list` without values, `custom` without regex) | pick the right kind (see `parla-nlu-design`) |
| intent with < 3 phrases / repeated phrases | write 6–12 varied phrases |
| intent that triggers no flow | add the flow, or delete the intent |
| flow with no trigger that nothing `goto`/`call`s | it never runs: wire it or delete it |
| function never used / input read but not declared | wire it with a `function` step / add the input |
| test turn with unknown keys, bad regex, unknown intent/slot/flow | fix the test (keys: `user intent says buttons slots flow handoff`) |

## Reading `test_conversation`

- `confidence` is the cosine similarity with the closest training phrase. A message that only matches at
  0.75–0.80 is fragile: add phrases like it. See `parla-nlu-design` for the numbers.
- `answer_to: "slot"` means the message was taken as the answer to that question, not as a new intent.
- A turn whose bot reply is «No reconocí ese dato…» means the slot's entity didn't find a value: check the
  entity (regex, list values, synonyms) or the question wording.
- `via`: `"knowledge"` (answered from the knowledge base), `"significado"` (an option understood by meaning),
  `"ia"` (the AI decided). `null` = the plain engine.
- `problems` lists "⚠" messages: a step failed (bad CEL, a function that raised with no `ok`/`error` save, a
  missing file). The conversation stopped there.
- Slots persist for the whole conversation. A question whose slot is already filled is **skipped**: clear
  re-askable slots with `{"type": "set", "slot": "x", "mode": "clear"}` at the end of the flow.

## Anti-patterns

- Writing the whole bot in one `create_agent` call and testing at the end.
- Testing only with the exact training phrases (they always score 1.0) — test paraphrases.
- One intent per FAQ ("horarios", "dirección", "precios"): use `knowledge` (see `parla-integrations`).
- Own intents for "cancel", "repeat" or "talk to a human": the system flows already do it (`system`).
- Fixing a misunderstanding by lowering `threshold` before looking at `self_check` and the phrases.
- `update_agent` with a JSON that is missing `tests`, `knowledge` or `functions` you didn't mean to delete.
- Publishing to production to "see if it works", or with `force=True` without the user accepting the failures.
- Asking the user to paste a token into the chat.

## Worked example

[`examples/dental-clinic.json`](examples/dental-clinic.json) is a complete bot built and verified with this
workflow (0 validation errors or warnings, 100 % self-check, 10/10 tests, published to staging and production):
appointment booking for a dental clinic in Rioplatense Spanish with a `date` entity, a phone preset, a list
entity with synonyms and `phrasings`, buttons, a Python function with error handling and a re-ask loop, an http
step that uses `{{ secret.BOOKING_TOKEN }}` and branches on the status, an urgent flow with
`"interrupts": "always"` that hands over to a person, a `"interrupts": false` greeting, classifications, an FAQ
knowledge base and tests for every path, including negative ones.

Its http step points at a fake local service (`http://127.0.0.1:8766/reservas`, `Authorization: Bearer
<BOOKING_TOKEN>`, answers 201 `{"code": …}` or an error status), so the tests that book need that service and the
key. Replace the URL with the real booking API.

The smallest agent that is worth creating looks like this (greeting + one intent + one flow + one test):

```json parla-agent
{
  "name": "Peluquería Rulos",
  "threshold": 0.75,
  "fallback": ["No te entendí, ¿me lo decís de otra forma?", "Perdón, no lo entendí. Puedo darte un turno."],
  "intents": [{"name": "Pedir turno", "examples": [
    "quiero sacar un turno", "necesito un turno para cortarme el pelo", "me das un turno para [mañana](fecha)",
    "¿tenés lugar el sábado?", "quería pedir hora", "sacame un turno", "un turno"]}],
  "entities": [{"name": "fecha", "kind": "date"}],
  "slots": [{"name": "fecha", "entity": "fecha"}],
  "flows": [
    {"name": "Bienvenida", "trigger": "__start__", "steps": [
      {"type": "message", "text": "¡Hola! Soy el asistente de Rulos. ¿Querés un turno?",
       "buttons": [{"label": "Sacar turno", "value": "quiero sacar un turno"}]}]},
    {"name": "Turno", "trigger": "Pedir turno", "steps": [
      {"type": "ask", "slot": "fecha", "text": "¿Para qué día y hora?"},
      {"type": "message", "text": "Listo, te anoté para el {{ fecha }}."},
      {"type": "set", "slot": "fecha", "mode": "clear"}]}],
  "tests": [{"name": "Turno con fecha", "turns": [
    {"says": "¿Querés un turno?"},
    {"user": "che, ¿me das un turno?", "intent": "Pedir turno", "says": "¿Para qué día"},
    {"user": "el 15/12 a las 10", "says": "te anoté"}]}]
}
```

More detail on every tool and its output: [reference.md](reference.md).
