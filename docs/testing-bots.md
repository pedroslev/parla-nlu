# Testing bots (conversation test suites)

**English** · [Español](testing-bots_es.md)

A **test** is a conversation you write once (what the person says, what the bot should understand and answer) and
run again after every change. It is a regression test for the bot: if you retouch an intent, a flow or a prompt and
something that used to work breaks, the test fails before your users notice. It's the same idea as Rasa's
end-to-end tests or Cognigy's simulator, but it runs locally, in the UI, from the API and in your CI.

In the UI the section is called **Tests**.

## Format

Tests are stored inside the agent JSON, in `"tests": [...]`. That means they travel with the agent: they are
exported and imported (the `.parla.json` file), they are part of each published version (restoring a version also
restores its tests) and they show up in the version diff (`tests`, **Tests**).

```json
{"name": "Pedido completo", "start": {"nombre": "Ana"}, "environment": "draft",
 "turns": [
   {"user": "hola", "intent": "Saludar", "flow": "Tomar pedido", "says": "¿Cuál es tu nombre?"},
   {"user": "Juan", "slots": {"nombre": "Juan"}, "says": "/(?i)apellido/"},
   {"user": "Sí", "buttons": ["Confirmar"], "handoff": false}
 ]}
```

### Test fields

| Field | What it is |
|---|---|
| `name` | Required and unique within the agent. |
| `start` | Optional. Start data: fields named like a slot preload it, exactly like `data` in the API's `start` event (see [api.md](api.md#start-start-with-preloaded-data)). The `__start__` flow runs before the first turn. |
| `environment` | Optional: `draft` (default), `staging` or `production`. |
| `turns` | The list of turns, in order. |

### Turn fields

`user` is what the person writes. To press a button, write its value or its label. Only the **first** turn may
omit `user`: then it checks what the bot says when the conversation starts (the greeting of the `__start__` flow).

Everything else is an expectation, and all of them are optional: only what you write is checked.

| Expectation | Passes when |
|---|---|
| `intent` | The intent it understood is this one. An answer to a question (a slot) and a low-confidence fallback count as no intent. |
| `says` | Everything the bot said in that turn (joined with newlines) contains this text, ignoring case. Or, written between slashes (`/.../`), it matches that Python regular expression: case-sensitive unless you add `(?i)`. |
| `buttons` | Each item is among the labels or values of the buttons offered. |
| `slots` | Only the slots listed are compared, as text and ignoring case. The others can have anything. |
| `flow` | The flow running at the end of the turn or, if it already finished, the last flow that started in that turn. |
| `handoff` | `true` or `false`: whether a person took over the conversation. |

A turn where a step failed (a bot message starting with «⚠») fails on its own, unless it has a `says`.

[`examples/pizzeria.json`](../examples/pizzeria.json) has two tests: «Pedido completo» and «Pedido directo con el
nombre precargado».

## How tests run

- In memory, with the engine: no session is saved. Tests never appear in Conversations, Inbox, Improve,
  Reports or the analytics.
- `http` steps, functions and AI (the `agent` step and the generative fallback) run **for real**. See
  [limitations](#limitations).
- Against `draft`, tests use the current draft definition. If intents or entities changed since the last training,
  a separate, throwaway model is trained just for the tests: the model the chat uses isn't touched.
- `staging` and `production` run against the version published there.

## In the UI

**Tests** is in the side menu, in the **Publish** group, above **Versions**.

- It lists the tests. **Run all** runs the whole suite and **Run** a single test, against the
  environment you pick.
- Each turn shows green or red; the failed checks read “expected … / got …”.
- Expectations are edited inline: intent (a list), says, buttons (comma-separated), slots (`slot=valor`,
  comma-separated), flow (a list) and handoff (a checkbox). You can also edit the start data and add or remove turns
  and tests.

### Save as test

The fastest way to write a test: have the conversation and save it. The button is in **Conversations** (on an open
conversation) and in the **Try it** chat panel. It turns the transcript into a test with the expectations
filled in from what happened: the intent, `says` with the bot's last message of each turn, the buttons offered and,
on the last turn, the final slots.

Then review it and loosen what changes from one run to another (dates, names, AI wording): shorten `says` to the part
that matters, or use a regex.

## Publish gate

Publishing to **Production** runs the whole suite against the draft first, if the agent has tests. If any test fails,
nothing is published.

- In the UI, the publish dialog shows the failures and a **Publish anyway** button.
- In the API, `POST /api/agents/{id}/versions` with `"environment": "production"` answers 409:

  ```json
  {"error": "No se publicó en Producción: fallaron 1 de 3 pruebas: «Pedido completo». …",
   "tests": {"passed": false, "total": 3, "failed": 1, "tests": [...]}}
  ```

  Send `"force": true` to publish anyway.

Not gated: publishing to `staging`, creating a version without an environment, and `POST /api/agents/{id}/deploy`
(moving an existing version, including a rollback).

## API

Tests are part of the agent: read them with `GET /api/agents/{id}` and change them with `PUT /api/agents/{id}`
(field `tests`). Only owners and editors can edit them. Owners, editors and analysts can run them (running changes
nothing).

```sh
curl -s http://127.0.0.1:8000/api/agents/654a0008/tests/run \
  -H 'Content-Type: application/json' -d '{"environment": "draft", "names": ["Pedido completo"]}'
```

Both fields are optional: `environment` overrides each test's own, and `names` runs only those tests.

```json
{"passed": false, "total": 1, "failed": 1,
 "tests": [{"name": "Pedido completo", "environment": "draft", "version": null, "passed": false,
            "turns": [{"user": "hola", "passed": false,
                       "failures": [{"check": "intent", "expected": "Saludar", "got": null}],
                       "got": {"intent": null, "says": "No te entendí.", "buttons": [], "slots": {},
                               "flow": null, "handoff": false}}]}]}
```

| Field | What it is |
|---|---|
| `passed`, `total`, `failed` | Summary of the run. |
| `tests[].error` | Only if the test couldn't run (for example, it is malformed). |
| `turns[].failures` | `[{"check", "expected", "got"}]`. `check` is `says`, `intent`, `buttons`, `slots.<name>`, `flow`, `handoff` or `error`. |
| `turns[].got` | What happened: `intent`, `says`, `buttons`, `slots` (the filled ones), `flow`, `handoff`. |

Full reference in [api.md](api.md#versions).

## Command line and CI

```sh
.venv/bin/python -m parla.bottests examples/pizzeria.json
```

It takes the agent JSON or an exported `.parla.json`, loads it into a throwaway data folder, trains it and runs its
tests. It prints `ok` or `FALLÓ` (failed) per test, the failure lines and a summary. Exit code 1 if any test fails (or
if the file has no tests), 0 otherwise. `--env` only accepts `draft` (the default): a file only has the draft. With
`GITHUB_ACTIONS=true` it also prints `::error` annotations, so failures show up on the pull request.

It doesn't need Parla running, but it does need Parla's requirements and the embedding model
(`google/embeddinggemma-300m`, ~1.2 GB), which is downloaded into `PARLA_EMBED_CACHE` (default
`data/models/embeddings`). In CI, cache that folder.

Parla's own CI runs `python -m parla.bottests examples/pizzeria.json` after the unit tests.

### GitHub Actions for your bot

Export your bot (**Export agent**, the `.parla.json` file), commit it to your repository and copy this workflow into
`.github/workflows/bot-tests.yml`. Change `bots/mybot.parla.json` to your file's path.

```yaml
name: Bot tests

on:
  push:
  pull_request:

permissions:
  contents: read

jobs:
  bot-tests:
    runs-on: ubuntu-latest
    timeout-minutes: 30
    env:
      PARLA_EMBED_CACHE: ${{ github.workspace }}/.cache/embeddings
      HF_HOME: ${{ github.workspace }}/.cache/hf
    steps:
      - uses: actions/checkout@v4                 # your repository, with the exported bot
      - uses: actions/checkout@v4                 # Parla, in ./parla
        with:
          repository: pedroslev/parla-nlu
          path: parla
          # ref: v0.9.0                           # pin a tag or commit for reproducible runs
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
          cache: pip
          cache-dependency-path: parla/requirements.txt
      - run: pip install -r parla/requirements.txt
      - name: Embedding model name
        id: model
        run: echo "name=$(grep -Po '^MODEL = "\K[^"]+' parla/parla/server.py)" >> "$GITHUB_OUTPUT"
      - uses: actions/cache@v4
        with:
          path: .cache/embeddings
          key: embed-${{ steps.model.outputs.name }}
      - name: Run the bot's tests
        run: python -m parla.bottests bots/mybot.parla.json
        env:
          PYTHONPATH: parla
```

The first run downloads the model (~1.2 GB); the following ones take it from the cache. If the bot uses secrets in
`http` steps, keep those tests out of CI or point them at a test service (see below): secrets don't travel in the
exported file.

## Limitations

- **AI and live APIs are real.** Tests that go through generative AI (the `agent` step, the generative fallback) or
  call live services through `http` steps or functions can be flaky. Keep them out of the suite that gates
  production, or assert loosely (a short `says`, a regex, only `intent` or `flow`).
- **Only publishing to production is gated.** `deploy` (moving an existing version, a rollback) and publishing to
  staging never run the tests.
- **Regexes use Python syntax** (`re`), case-sensitive unless they start with `(?i)`.
- **Dates and other changing values.** A `says` with today's date passes today and fails tomorrow. Assert on the
  stable part of the message, or use a regex such as `/\d{2}\/\d{2}/`.
- `--env` on the command line only accepts `draft`; to test `staging` or `production`, use the API, the UI or the MCP.
