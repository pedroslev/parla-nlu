---
name: parla-migrate-from-rasa
description: Migrating a Rasa 3.x project (classic NLU/domain/stories/rules/forms or CALM flows) to Parla with the import_rasa_project MCP tool, reading its warnings and validation output, and finishing the job - replacing custom-action placeholder http steps, adding example phrases to intents created from CALM flow descriptions, fixing conditions and slot mappings that couldn't be translated, translating system texts, then testing and publishing. Use it when the user has a Rasa bot (domain.yml, data/*.yml, config.yml) and wants it running in Parla.
---

# Migrating a Rasa bot to Parla

The importer does the bulk of the work and **lists everything it couldn't translate**; nothing is dropped
silently. It reads only `.yml`/`.yaml` files and never runs the Rasa action code. Your job is the checklist after
the import.

## Checklist

1. **Locate the project**: the folder with `domain.yml`, `config.yml` and `data/` (ask the user for the path; the
   tool reads the local disk). Large `models/` and `.venv/` folders are ignored anyway.
2. **Import**: `import_rasa_project(path, name="…")` → `{id, name, slug, warnings, validation}`. The agent is
   created as a new draft and trained. (Without MCP: `python -m parla.rasa_import <folder> -o bot.parla.json`, or
   «Importar de Rasa» in the UI with a zip.)
3. **Show the user the warnings, grouped**, and agree on what to fix. Then work through them with
   `get_agent` → edit → `validate_agent` → `update_agent`:

| Warning about | What to do |
|---|---|
| **custom action** `action_x` → placeholder http step to `http://localhost:5055/webhook` with a `note` «TODO» | Ask what the action did. Replace the step with the real `http` call (secrets via `{{ secret.NAME }}`, `saves`, an `if` on the status) or a `function` (see `parla-integrations`). If the Rasa action server will stay running, at least add `saves` and a status branch. Remove the `note`. |
| **CALM flows** «need example phrases»: an intent named after the flow whose only example is the flow `description` | Write 6–12 real user phrases per intent (see `parla-nlu-design`) and delete the description phrase. Rename the intent if users will see it in «¿Quisiste decir…?». |
| intents with **no examples** (often listed in `domain.intents` only) | Add phrases or delete the intent. |
| a condition that **couldn't be translated** (`expr: "false"` with the original in `note`) | Rewrite it as a `cond` or CEL `expr` over slots (`int()`/`double()` for numbers). Until then that branch never runs. |
| slots `from_llm` / no mappings → «store the whole answer» | Give the slot an entity (list, preset, custom regex) if it has a format; or `fill: "ai"` + `description` with AI on. |
| `from_intent`, `custom` mappings, `initial_value`, mapping conditions | Rebuild with `set` steps at the start of the flow, or an `if`. |
| `validate_<form>` / `rejections` | Validate with format/list entities (they re-ask automatically) or a function + re-ask loop. |
| stories that depend on context (`slot_was_set`, checkpoints, same intent answered differently) | Only the first answer was kept: add `if` steps on the slots, or split into flows. |
| response variations / channel / condition variants | Only the first was kept; rewrite if it matters. Parla's `fallback` can be a list of variants. |
| entity `role` → separate entities (`city_from`), `group` ignored | Check the slots that use them. |
| synonyms on a learned entity | Prefer a `list` entity with those values if the set is closed. |
| `pattern_*` flows, `action_restart`, `session_config` | Covered by Parla's system flows (`cancel`, `repeat`, `clarify`, `handoff`…) and `set clear` steps. |
| a non-Spanish `language` | The fallback and system flow texts may need translating (English gets defaults). **Date entities only parse Spanish** («tomorrow» isn't understood): ask for `dd/mm`, or use a custom regex. |
| `endpoints.yml`, `credentials.yml`, Rasa `tests/` | Channels are set up in Parla (`parla-integrations`); port important e2e tests to `tests` (step 6). |

4. **Read `validation`** (the same output as `validate_agent`): typically intents with < 3 phrases and intents that
   trigger no flow (Rasa responses unused by any rule/story). Fix or delete.
5. **Retrain and check** `trained.log.self_check` after adding phrases: Rasa projects often have overlapping
   intents that a classifier tolerated; fix the mistakes it lists.
6. **Write tests** for the main paths (port the Rasa e2e stories you care about) and `run_tests`. Placeholder
   http steps answer status 0 when the action server isn't running: the flow continues, so a test can pass while
   the action does nothing — assert on what the action should have produced.
7. **Try it** with `test_conversation` (paraphrases, invalid answers, cancel), then release with
   `parla-testing-and-release` (staging first, production only with the user's OK).

## What maps cleanly (no work needed)

NLU intents and examples; `[value](entity)` marks (+ synonyms); `lookup` → list entities; `regex` named like an
entity → `custom`; never-annotated `email/number/phone/date/time` → presets; `from_entity` slots; `utter_*` →
`message`/`ask` text with `{slot}` → `{{ slot }}`; buttons → `{label, value}`; forms → one `ask` per required slot;
CALM `collect` → `ask`, `set_slots` → `set`, `link` → `goto`, `call` → `call`, `next` with `if/then/else` →
nested `if` (bare slots mean «has a value»). Full table: `docs/migrate-from-rasa.md`.

## Anti-patterns

- Telling the user «migrated!» right after the import, with placeholder steps and one-phrase intents left.
- Keeping the flow `description` as the only training phrase.
- Porting Rasa's custom NLU pipeline settings: Parla's NLU is fixed (embeddings + CRF); tune phrases instead.
- Re-creating Rasa's `utter_ask_*` for cancel/repeat/human: use the system flows.

## Worked example

A CALM flow `book` («The user wants to book an appointment») with `collect: date`, `collect: phone`,
`action: action_book` imports as an intent `book` with one phrase and a flow with two `ask`s and a placeholder
http step. After the checklist it looks like this:

```json parla-agent
{
  "name": "Rasa demo (migrated)",
  "languages": ["en"],
  "fallback": ["Sorry, I didn't get that. I can book an appointment for you."],
  "intents": [{"name": "book", "examples": [
    "I want to book an appointment", "can I get an appointment?", "book me in for next week",
    "I need to see the dentist", "do you have any slots on friday?", "schedule a visit", "appointment please"]}],
  "entities": [{"name": "date", "kind": "custom", "regex": "\\b(\\d{1,2}/\\d{1,2})\\b"}, {"name": "phone", "kind": "phone"}],
  "slots": [{"name": "date", "entity": "date"}, {"name": "phone", "entity": "phone"}, {"name": "booking_status", "entity": ""}],
  "flows": [{"name": "book", "trigger": "book", "steps": [
    {"type": "ask", "slot": "date", "text": "Which day? Please write it as dd/mm."},
    {"type": "ask", "slot": "phone", "text": "What's your phone number?"},
    {"type": "http", "method": "POST", "url": "https://booking.example.com/appointments",
     "headers": [{"key": "Authorization", "value": "Bearer {{ secret.BOOKING_TOKEN }}"}],
     "body": "{\"date\": \"{{ date }}\", \"phone\": \"{{ phone }}\"}",
     "saves": [{"expr": "status", "slot": "booking_status"}]},
    {"type": "if", "cond": {"var": "booking_status", "op": "eq", "value": "201"},
     "then": [{"type": "message", "text": "Booked for {{ date }}."}],
     "else": [{"type": "handoff", "reason": "booking API failed", "text": "I couldn't book it. A person will help you."}]},
    {"type": "set", "slot": "date", "mode": "clear"}]}],
  "system": {"cancel": {"text": "OK, let's stop here. Anything else?", "examples": ["cancel", "forget it", "stop"]},
             "repeat": {"examples": ["what?", "repeat that", "sorry?"]},
             "handoff": {"text": "I'll get a person to help you.", "examples": ["talk to a human", "I want an agent"]}},
  "tests": [{"name": "Book", "turns": [
    {"user": "could I book a visit?", "intent": "book", "says": "Which day?"},
    {"user": "tomorrow", "says": "write it as dd/mm"}]}]
}
```
