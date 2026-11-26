# Parla MCP tools: reference for bot builders

All tools take `agent` as id (8 hex chars), exact name or slug. Tools that change something only touch the
**draft**. Errors come back as tool errors with Parla's message (often in Spanish); read them, they say what to fix.

## Build

| Tool | Use it to | Notes |
|---|---|---|
| `list_agents()` | see what exists | `environments` tells you what is live (`production`/`staging` version or `null`). |
| `get_agent(agent)` | start any edit | Returns the full draft JSON, plus `trained` (with `trained.log`). |
| `agent_format_guide()` | learn the exact format | Same text as the `parla://format-guide` resource. Read before writing JSON. |
| `validate_agent(agent_json)` | check without saving | `{ok, errors, warnings}`. Does not know which files are uploaded (only warns about `file` steps). |
| `create_agent(agent_json)` | create a new bot | Validates, imports, trains. Fills the regex of `number/email/phone/dni` if omitted. Returns `{id, name, slug, trained, warnings}`; `warnings` includes missing secrets. |
| `update_agent(agent, agent_json)` | replace the whole draft | Anything omitted is reset (tests, knowledge, functions included). Also checks `file` steps against uploaded files. Retrains. |
| `train_agent(agent)` | retrain the draft | Only needed after `teach_phrases` (create/update already train). |
| `import_rasa_project(path, name)` | migrate a Rasa project | See the `parla-migrate-from-rasa` skill. |
| `delete_agent(agent, confirm)` | delete a bot and its conversations | Irreversible; only when the user asked. |

## Test

| Tool | Use it to | Notes |
|---|---|---|
| `test_conversation(agent, messages, start_data=None, keep=False, environment="draft")` | try a conversation | Runs the `__start__` flow, then each message. `start_data` keys named like slots preload them; `{"idioma": "pt"}` picks the language. To press a button send its `value` (or label). The session is deleted unless `keep=True`. |
| `run_tests(agent, environment=None, names=None)` | run the saved `tests` | Nothing is stored. `environment` overrides each test's own (`draft` default). |
| `test_function(agent, function, inputs)` | run one function alone | Pass the full definition to try it before saving it. Inputs not declared in the function are dropped (`ignored_inputs`). |

`test_conversation` turn fields: `user`, `intent`, `confidence`, `entities` (`[{entity, value, start, end}]`),
`answer_to`, `bot` (list of texts), `flow`, `waiting_for`, `classifications`, `language`, `handoff`, and when
present `buttons` (`[{label, value}]`), `via`, `sources`, `files`. Top level: `final_slots`, `waiting_for`,
`handoff`, `version` (`null` = draft) and `problems`.

## Versions

| Tool | Use it to | Notes |
|---|---|---|
| `diff_agent(agent, from_ref="production", to_ref="draft")` | review before publishing | Refs: `production`, `staging`, `draft` or a version number. |
| `publish_agent(agent, note, environment=None, confirm=False, force=False)` | freeze the draft as v1, v2… | `environment="staging"` for the user to try; `"production"` needs `confirm=True` and runs the tests first (fails with the list unless `force=True`). |
| `deploy_version(agent, environment, version, confirm=False)` | point an environment to a version | Rollback = deploy the previous version. Production needs `confirm=True`. Not gated by tests. |
| `list_versions(agent)` | versions, environments, deployment log | `deployments[].previous` = what to deploy to roll back. |
| `restore_version(agent, version, confirm=False)` | throw away draft edits | Overwrites the draft with that version. |

## Real conversations

| Tool | Use it to |
|---|---|
| `list_sessions(agent, channel, classification, date_from, date_to)` | find conversations (`classification="__none__"` = unclassified) |
| `get_session(agent, session_id)` | read one, with intent/confidence per message |
| `get_report(agent, …)` | count conversations per classification and day |
| `get_analytics(agent, …)` | containment, handoff rate, fallback rate, CSAT, drop-off per question |
| `list_unrecognized(agent, …)` | what users wrote that fell to the fallback, grouped, with a suggested intent |
| `teach_phrases(agent, intent, phrases)` | add phrases to an existing intent (then `train_agent`) |

## Knowledge, files, secrets

| Tool | Use it to |
|---|---|
| `add_knowledge(agent, title, text=None, url=None)` | add/replace (same title) a knowledge document; no retraining |
| `search_knowledge(agent, query, k=3)` | see the scores the bot would get; `answers` = reaches `knowledge_threshold` |
| `list_files(agent)` | files the user uploaded, for `file` steps (the MCP cannot upload) |
| `list_secret_names(agent)` | `{secrets, used, missing}` — names only, never values |

## Prompt and resources

- Prompt `build_bot(description)`: the step-by-step brief this skill expands.
- Resource `parla://format-guide`: the format guide.
- Resources `parla://skills` and `parla://skills/<skill>/<file>`: these skills, served by the MCP server itself.

## The training report (`trained.log`)

```text
duration_ms, steps[]            what training did (phrases → vectors, CRF, self-check)
crf {trained, entities, reason} whether a CRF was needed (only for entities with no regex, values or date)
self_check {accuracy, checked, right, summary, intents[], mistakes[], confusion{}}
entities [{name, kind, marked}] how many times each entity is marked in phrases
warnings []                     concrete advice
```

`self_check` is leave-one-out: each phrase is classified against all the others. `mistakes` (up to 20, worst first)
has `phrase`, `expected`, `got`, `score` and `closest` (the phrase it matched). `confusion[expected][got]` counts
phrases. Intents with a single phrase are not checked.

## Limits worth knowing

| Limit | Value |
|---|---|
| Steps run in one turn | 200 (stops `goto` loops with a "⚠") |
| Stacked flows (`call` + interruptions) | 5 |
| http step | 10 s timeout, 1 MB of response read |
| function | 5 s, standard library only, separate process |
| file step | up to 10 MB; pdf, images, Office, csv, txt, zip |
| `agent` step | `max_turns` 1–50 (default 8), up to 4 function calls per turn |
| message history kept per conversation | 500 |
