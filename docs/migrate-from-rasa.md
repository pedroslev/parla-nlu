# Migrating from Rasa

**English** · [Español](migrate-from-rasa_es.md)

Parla can import a Rasa 3.x project (classic NLU + stories/rules, or CALM flows) and turn it into a Parla agent.
The goal is to have your bot running in Parla in an afternoon: the import does the bulk of the work and gives you a
**list of warnings** with everything it couldn't translate as is. Nothing is dropped silently.

Only `.yml`/`.yaml` files are read. Your custom action code (`actions/*.py`) is never executed or imported.

## How to run it

**From the UI.** On the home screen («Tus agentes»), click **Importar de Rasa** and choose a `.zip` of your project
folder (the one with `domain.yml`, `config.yml` and `data/`). The agent is created and trained, and a dialog lists
the warnings. Zip it without `models/` and `.venv/` (only the `.yml` matter; maximum 18 MB).

**From the API.** `POST /api/agents/import/rasa` (same role as creating an agent: owner or editor):

```sh
curl -s http://127.0.0.1:8000/api/agents/import/rasa -H 'Content-Type: application/json' \
  -d "{\"name\": \"Moodbot\", \"zip\": \"$(base64 < moodbot.zip | tr -d '\n')\"}"
# or {"files": {"domain.yml": "...", "data/nlu.yml": "..."}}
```

Returns `{"agent": {...}, "warnings": ["..."]}`. Zip limits: 500 `.yml` files, 20 MB uncompressed; paths that are
absolute or contain `..` are skipped (with a warning).

**From the command line** (doesn't need Parla running; writes a file you can load with «Importar agente»):

```sh
.venv/bin/python -m parla.rasa_import path/to/rasa-project -o moodbot.parla.json
```

The warnings are printed to stderr.

**From an AI assistant (MCP).** The `import_rasa_project(path, name=None)` tool reads the project folder on your
machine and calls the API. Ask it «import my Rasa bot in ~/bots/moodbot and fix the warnings».

## What maps to what

| Rasa | Parla |
|---|---|
| `config.yml` `language: en` | `languages: ["en"]`. For English, the fallback and the system flows (cancel, repeat, handoff…) get English texts. Other languages: warning, translate the system flows by hand. |
| `pipeline`, `policies` | Ignored (warning): Parla has its own NLU (embeddings + CRF) and flows. |
| `nlu` intent with examples | Intent with the same name and examples. |
| `[value](entity)`, `[text](entity:value)`, `[text]{"entity": "x", "value": "y"}` | `[text](x)`; when the value differs it becomes a synonym of the entity. |
| Entity `role` | A separate entity per role: `city` + role `from` → `city_from`. Slots that map `entity: city, role: from` use `city_from`. |
| Entity `group` | Ignored (warning). |
| `synonym:` | `synonyms` of the entity that uses that value. On a learned (CRF) entity Parla keeps the text as typed; there's a warning suggesting a list entity. |
| `lookup:` named after an entity | `list` entity with those values. |
| `regex:` named after an entity | `custom` entity with that regex. A regex that isn't an entity is only a classifier hint in Rasa: skipped with a warning. |
| Entity never annotated named `email`, `number`, `phone`, `date`, `time` | The matching preset kind (it probably came from Duckling/spaCy). |
| Other entities | `examples` kind (learned by the CRF from the annotations). |
| Slot `from_entity` | Slot with that `entity`. |
| Slot `from_text`, `from_llm`, no mappings | Slot without entity: takes the whole answer when asked. For `from_llm` there's a warning: turn on AI and use «Lo completa la IA» to extract. |
| `categorical` slot with `values` and no entity | A `list` entity with those values. |
| `bool` slot with no entity | A `list` entity `true`/`false` with yes/no synonyms (en, es, pt). |
| `from_intent`, `from_trigger_intent`, `custom` mappings, `initial_value`, mapping conditions | Not imported (warning). |
| `responses` `utter_*` | Text of a `message` step (or the question of an `ask`). `{slot}` → `{{ slot }}`. |
| Response variations, `channel` or `condition` variants | The first one without condition/channel (warning listing them). |
| Buttons `{title, payload}` | `{label, value}`. A `/intent` payload becomes the first example of that intent (tapping a button in Parla is typing its value); entities in the payload: warning. |
| `image`, `attachment`, `custom`, … in a response | Not imported (warning). |
| `utter_default` | The agent's `fallback`. A rule `nlu_fallback → utter_x` also sets the fallback. |
| Rules and stories | Split at each user intent: each intent → a flow triggered by it, with the actions that follow it. The first one found wins (rules before stories); if another story answers the same intent differently there's a warning (context dependent). |
| `or:` of intents | Same flow for each intent. |
| `bot:` text in a story | `message` step. |
| `forms` + `action: my_form` | One `ask` step per `required_slots`, with `utter_ask_<form>_<slot>` or `utter_ask_<slot>` as the question. The actions after the form (the «submit» rule with `condition: active_loop`) are appended. |
| `validate_<form>`, `action_ask_<slot>` | Not imported (warning). Validate with format or list entities: they reject what doesn't match. |
| Custom action `action_x` | Placeholder `http` step: `POST http://localhost:5055/webhook` with `{"next_action": "action_x"}` and a `note`. Replace it with the real request or a function (warning). |
| `action_listen`, `action_deactivate_loop`, `active_loop`, `slot_was_set: requested_slot` | Nothing (they're Rasa internals). |
| `slot_was_set` on other slots, `checkpoint`, `user:` e2e steps, `action_restart` | Not imported (warning). |
| Retrieval intents `faq/ask_x` + `utter_faq/ask_x` | One intent and one flow per question. |
| CALM `flows` | One Parla flow per flow, with the same name. |
| Flow `description` | CALM picks flows with an LLM; Parla needs example phrases. A new intent named after the flow, with the description as its only example (warning: add 5–10 real phrases). |
| Flow `nlu_trigger` intents | Their examples move to the flow's intent. |
| `collect: slot` | `ask` step with `utter` or `utter_ask_<slot>`. `ask_before_filling: true` → clear the slot first. |
| `reset_after_flow_ends` (default true), `persisted_slots` | Collected slots are cleared where the flow ends, except persisted ones. |
| `rejections` | Not imported (warning). |
| `action: utter_x` / custom action | `message` / placeholder `http` step (as above). |
| `set_slots` | `set` steps (`null` → clear). |
| `link: flow` | `goto` (doesn't come back). |
| `call: flow` | `call` (comes back). |
| `next: step_id` | `goto` to an extra flow «`<flow> · <step_id>`» that holds the steps from there. Loops work. |
| `next: END` | End of flow. |
| `next` with `if/then/else` | Nested `if` steps. |
| Conditions `slots.x = v`, `is`, `==`, `!=`, `is not`, `>`, `<`, `slots.x`, `not slots.x`, `is null` | A `cond` (`eq`, `ne`, `gt`, `lt`, `filled`, `empty`). |
| Other conditions (`and`, `or`, `>=`, …) | Translated to a CEL `expr` (floats are compared with `double(x)`). If it can't be translated: `expr: "false"` with the original in `note` (warning). |
| Flow `if`, `always_include_in_prompt`, `pattern_*` flows | Not imported (warning). Parla's system flows cover cancel, repeat, clarify, handoff, etc. |
| `endpoints.yml`, `credentials.yml`, `tests/` | Not imported (warning). |

## After importing

1. Read the warnings. The usual work: add example phrases to the intents that came from CALM flows, and replace
   the placeholder `http` steps of custom actions with the real request or a function.
2. Try it in the test chat (or with `test_conversation` from the MCP).
3. Publish when it behaves.

## Known limitations

- Stories are flattened into «intent → actions»: dialogue that depends on what happened before (story context,
  `slot_was_set` branches, checkpoints) is not reproduced; there's a warning for each case.
- Custom actions aren't migrated (Parla never runs your Rasa Python code). If you keep the Rasa action server
  running, the placeholder step already points at it, but you'll have to save the response in slots yourself.
- CALM's LLM-based understanding (command generator, slot filling from free text, rephrasing) isn't reproduced
  without examples; turn on Parla's local AI to get closer.
- Slots are text in Parla; a `float` compared in a `cond` with `gt`/`lt` works, other numeric logic may need CEL.
