---
name: parla-testing-and-release
description: Writing conversation tests for Parla bots (the agent "tests" list - turns with user, intent, says substring or /regex/, buttons, slots, flow, handoff, start data), covering negative paths, running them with run_tests or python -m parla.bottests in CI, and releasing safely with versions and environments (draft, staging, production; publish gate with 409 and force; deploy_version, rollback, restore_version, diff_agent). Also the improvement loop on real traffic (list_unrecognized, teach_phrases, get_analytics, list_sessions, ignored_phrases). Use it before publishing a Parla bot, when a test fails, when the user asks to go live or roll back, or to improve a bot from real conversations.
---

# Testing and releasing Parla bots

## Test format

Tests live in the agent JSON (`"tests": [...]`), travel with exports and versions, and are validated by
`validate_agent`.

```json
{"name": "Reserva completa", "start": {"telefono": "11 5555 1234"}, "environment": "draft", "turns": [
  {"says": "¿En qué te ayudo?", "buttons": ["Sacar turno"]},
  {"user": "quiero sacar un turno", "intent": "Pedir turno", "flow": "Reservar turno", "says": "¿Para qué tratamiento?"},
  {"user": "Limpieza", "slots": {"tratamiento": "limpieza"}},
  {"user": "si", "says": "/reservado .*Código: DC-\\d{4}/", "handoff": false}]}
```

| Field | Meaning |
|---|---|
| `name` | required, unique |
| `start` | start data: keys named like slots preload them before `__start__` runs |
| `environment` | `draft` (default), `staging`, `production` |
| `turns[].user` | what the person writes; a button is pressed by its `value` or `label`. Only the **first** turn may omit it: it checks the greeting |
| `intent` | the intent understood. An answer to a question and a fallback count as **no intent**, so don't assert `intent` on answers. `null` is not checked (you can't assert "no intent": assert the fallback text instead) |
| `says` | substring of everything the bot said that turn (case-insensitive), or `/regex/` (Python, case-**sensitive** unless `(?i)`; use `(?s)` to span lines — messages are joined with newlines) |
| `buttons` | each item must be among the offered labels or values |
| `slots` | only the listed slots, compared as text, case-insensitive, **exact** (no regex) |
| `flow` | the flow running at the end of the turn, or the last one that started in it |
| `handoff` | whether a person took over |

A turn where a step failed ("⚠") fails unless it has a `says` (then you are asserting the error on purpose).

## What to cover (checklist)

For every flow, at least:

1. **Happy path** with buttons pressed the way users press them.
2. **Everything in the first message** («turno de limpieza para el 15/12 a las 10» skips those questions).
3. **Invalid answer** → «No reconocí ese dato» and the question again, then a valid one.
4. **Business-rule rejection** (closed day, quantity 0) → the re-ask path.
5. **Saying no** at the confirmation → nothing is done.
6. **Integration failure** (http status ≠ success, function error) → the escalation path (`handoff: true`).
7. **Interruptions**: an urgent intent mid-question (`flow`, `handoff`), a FAQ mid-question (`says` the answer
   and the question again), a correction («mejor un control» → `slots`).
8. **Knowledge** questions answered (`says` a distinctive word of the answer).
9. **Off-topic** → fallback (`says: "/entend|no lo sé/"` matching all your fallback variants).
10. **Greeting** (first turn without `user`) and, for multilingual bots, one test with `start: {"idioma": "pt"}`.

Test with **paraphrases**, not with training phrases. Make expectations robust: a distinctive substring instead
of the whole message, regex for codes, no `says` on today's date or on AI-written text.

## Running tests

- `run_tests(agent)` after every `update_agent`; `run_tests(agent, environment="staging")` after publishing to
  staging. Read `tests[].turns[].failures[] {check, expected, got}`; `got` shows what really happened.
- Against `draft`, tests use the current draft even if untrained (a throwaway model is trained for them).
- Nothing is stored: tests never appear in conversations, Inbox, reports or analytics.
- **http steps, functions and AI run for real.** Tests that hit an API need it up and its secrets loaded; tests
  through the AI can be flaky — keep them loose or out of the suite.
- CI: export the bot (`.parla.json`) and run `python -m parla.bottests bots/mybot.parla.json` (exit 1 on failure,
  GitHub annotations with `GITHUB_ACTIONS=true`; needs the embedding model cached). Secrets don't travel in exports,
  so tests that need them fail there — point them at a test service or keep them out of CI.

## Releasing

```text
draft ──publish_agent(environment="staging")──▶ v3 in staging ──user OK──▶ production
   ▲                                                             │
   └──────────── restore_version (discard draft edits) ◀────────┘  rollback = deploy_version(previous)
```

1. `run_tests` green on the draft. `diff_agent(agent)` (production → draft) to see exactly what changes; tell the
   user in plain words.
2. `publish_agent(agent, note="what changed", environment="staging")` — never gated. `run_tests(environment=
   "staging")` and `test_conversation(environment="staging")`; share the result.
3. **Only with the user's explicit approval**: `deploy_version(agent, "production", N, confirm=True)` (moves the
   tested version, not gated) or `publish_agent(..., environment="production", confirm=True)` (publishes the
   draft and **runs the tests first**: if any fails nothing is published and the error lists them — HTTP 409).
   `force=True` publishes anyway: only if the user explicitly accepts those failures.
4. Rollback: `list_versions` → `deployments[0].previous` → `deploy_version(agent, "production", previous,
   confirm=True)`.
5. Conversations stay on the version they started with; new ones get the new version. Secrets, files,
   `retention_days` and `pii_redaction` belong to the agent, not to versions.

## Improving with real traffic

1. `get_analytics(agent)`: containment vs handoff, `fallback_rate`, CSAT, and `drop_off` (which question people
   abandon — reword it, add buttons, or accept more answers).
2. `list_unrecognized(agent)`: fallbacks grouped by meaning with a `suggested_intent`. For each group decide:
   - phrases of an existing intent → `teach_phrases(agent, intent, phrases)` then `train_agent`;
   - a frequent question → `add_knowledge` (check with `search_knowledge`);
   - a new need → new intent + flow with `update_agent`;
   - noise → add to the agent's `ignored_phrases` so it stops showing up.
3. `list_sessions(agent, classification="__none__")` + `get_session` to read conversations that reached no outcome.
4. Turn every real failure into a test, `run_tests`, publish to staging, get the OK, deploy.

## Anti-patterns

- Publishing to production without tests, or with `force=True` on your own.
- Tests that only use training phrases, or only the happy path.
- `says` with the full message (breaks on any copy edit), dates, or AI output.
- Asserting `intent` on a turn that answers a question (it is always no intent).
- `update_agent` without the `tests` list (deletes them).
- Teaching every unrecognised phrase to the closest intent without reading it.

## Worked example

A small bot with its full suite, including negative paths:

```json parla-agent
{
  "name": "Pedidos Pizzería",
  "fallback": ["No te entendí. Puedo tomarte un pedido.", "Perdón, no lo entendí. ¿Querés pedir una pizza?"],
  "intents": [{"name": "Pedir pizza", "examples": [
    "quiero una pizza", "mandame una de [muzza](gusto)", "quiero pedir [2](cantidad) pizzas",
    "haceme una [napolitana](gusto)", "¿me traés una pizza?", "pedido de pizza", "una pizza"]}],
  "entities": [
    {"name": "gusto", "kind": "list", "values": ["muzzarella", "napolitana", "fugazzeta"],
     "synonyms": {"muzzarella": ["muzza", "mozzarella"], "napolitana": ["napo"], "fugazzeta": ["fugazza"]}},
    {"name": "cantidad", "kind": "number"}],
  "slots": [{"name": "gusto", "entity": "gusto"}, {"name": "cantidad", "entity": "cantidad"}],
  "flows": [{"name": "Pedido", "trigger": "Pedir pizza", "steps": [
    {"type": "ask", "slot": "gusto", "text": "¿De qué gusto? Muzzarella, napolitana o fugazzeta.",
     "buttons": [{"label": "Muzzarella", "value": "muzzarella"}, {"label": "Napolitana", "value": "napolitana"},
                 {"label": "Fugazzeta", "value": "fugazzeta"}]},
    {"type": "ask", "slot": "cantidad", "text": "¿Cuántas? Decímelo en números."},
    {"type": "if", "expr": "int(cantidad) < 1",
     "then": [{"type": "message", "text": "Tiene que ser al menos una."}, {"type": "set", "slot": "cantidad", "mode": "clear"},
              {"type": "goto", "flow": "Pedido"}], "else": []},
    {"type": "message", "text": "Listo: {{ cantidad }} de {{ gusto }}."},
    {"type": "set", "slot": "gusto", "mode": "clear"}, {"type": "set", "slot": "cantidad", "mode": "clear"}]}],
  "tests": [
    {"name": "Pedido con botón", "turns": [
      {"user": "che, ¿me mandás una pizza?", "intent": "Pedir pizza", "says": "¿De qué gusto?", "buttons": ["Napolitana"]},
      {"user": "Napolitana", "slots": {"gusto": "napolitana"}, "says": "¿Cuántas?"},
      {"user": "2", "says": "Listo: 2 de napolitana"}]},
    {"name": "Todo junto y con sinónimo", "turns": [
      {"user": "mandame 3 de muzza", "says": "Listo: 3 de muzzarella"}]},
    {"name": "Cantidad inválida", "turns": [
      {"user": "quiero una de fugazza", "says": "¿Cuántas?"},
      {"user": "muchas", "says": "No reconocí ese dato"},
      {"user": "0", "says": "/(?s)al menos una.*¿Cuántas\\?/"},
      {"user": "1", "says": "Listo: 1 de fugazzeta"}]},
    {"name": "Fuera de tema", "turns": [{"user": "¿cuál es la capital de Francia?", "says": "/entend/"}]}]
}
```
