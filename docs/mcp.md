# MCP and «Conectar con IA»

**English** · [Español](mcp_es.md)

Parla ships an [MCP](https://modelcontextprotocol.io) server that gives an assistant (Claude Code, Codex, Claude
Desktop, Cursor or claude.ai) tools to build bots: read the format guide, validate, create, train, test
conversations, publish and review real conversations. So you can ask it «armame un bot que tome turnos para la
peluquería» ("build me a bot that books appointments for the hair salon") and it designs it, creates it, tests it
and fixes it.

Parla has to be running while you use it.

## «Conectar con IA» (one click)

In the interface, **Conectar con IA** (Connect to AI) shows Claude Code, Codex, Claude Desktop and Cursor, whether
they're installed and whether they're already connected. When you connect:

- **Claude Code**: runs `claude mcp add --scope user parla ...` (if it was already there, it removes it and adds it
  again with the current path and port).
- **Codex**: adds the `[mcp_servers.parla]` table to `~/.codex/config.toml`.
- **Claude Desktop**: adds `parla` to `mcpServers` in `claude_desktop_config.json` (on macOS
  `~/Library/Application Support/Claude/`, on Windows `%APPDATA%\Claude\`, on Linux `~/.config/Claude/`).
- **Cursor**: adds `parla` to `~/.cursor/mcp.json`.

Before touching a file it saves a `*.parla-backup` copy; if the file can't be read, it leaves it alone and shows
you what to paste by hand («Hacerlo a mano», Do it by hand). If Parla has users, it creates an API key for your
user («Conectar con …») and puts it in `PARLA_TOKEN`. Then restart the assistant (Claude Desktop, Codex and Cursor)
and ask it «armame un bot que…» ("build me a bot that…").

This feature only answers requests made to `127.0.0.1`/`localhost`.

## Manual installation

The `mcp` package is already in `requirements.txt`. There are two ways to run it:

```sh
.venv/bin/python mcp_server.py                         # stdio: the assistant starts it (the usual way)
make mcp                                               # HTTP at http://127.0.0.1:8001/mcp (see «Hosted»)
```

It uses the official `mcp` 2.x SDK (`MCPServer`). It doesn't talk to the files directly: it calls Parla's HTTP API
(`PARLA_URL`), so it respects users and roles.

### Claude Code

```sh
claude mcp add --scope user parla -e PARLA_URL=http://127.0.0.1:8000 -- \
  /ruta/a/parla/.venv/bin/python /ruta/a/parla/mcp_server.py
```

Then: «armame un bot que …» ("build me a bot that …") or `/mcp__parla__build_bot`.

### Claude Desktop / Cursor

```json
{
  "mcpServers": {
    "parla": {
      "command": "/ruta/a/parla/.venv/bin/python",
      "args": ["/ruta/a/parla/mcp_server.py"],
      "env": {"PARLA_URL": "http://127.0.0.1:8000", "PARLA_TOKEN": "parla_..."}
    }
  }
}
```

### Codex (`~/.codex/config.toml`)

```toml
[mcp_servers.parla]
command = "/ruta/a/parla/.venv/bin/python"
args = ["/ruta/a/parla/mcp_server.py"]
env = { PARLA_URL = "http://127.0.0.1:8000" }
```

### Hosted (claude.ai, custom connector)

On the same server as Parla:

```sh
.venv/bin/python app.py 8000 &
PARLA_URL=http://127.0.0.1:8000 PARLA_TOKEN=parla_... PARLA_MCP_ALLOWED_HOSTS=bots.midominio.com \
  .venv/bin/python mcp_server.py --http --port 8001
```

It listens on `http://127.0.0.1:8001/mcp` (streamable HTTP; `--host` changes the interface). Publish it behind an
HTTPS proxy at `https://bots.midominio.com/mcp` and add that URL as a custom connector in claude.ai. **The MCP
server with `--http` has no authentication of its own**: whoever reaches it acts with the `PARLA_TOKEN` key.
Protect it at the proxy (see [security.md](security.md)).

## Environment variables

| Variable | Default | What it is |
|---|---|---|
| `PARLA_URL` | `http://127.0.0.1:8000` | Where Parla is. |
| `PARLA_TOKEN` | empty | Sent as `Authorization: Bearer <token>`. Required if Parla has users: `owner` or `editor` role to build and test bots; with `analyst` only the read tools work (`list_*`, `get_*`, `diff_agent`, `agent_format_guide`, `validate_agent`). The key only sees the bots its user sees. |
| `PARLA_MCP_ALLOWED_HOSTS` | empty | Only with `--http` behind a proxy: comma-separated public domains (the SDK rejects unknown Host headers to prevent DNS rebinding). |

## Tools

25 tools, one resource (`parla://format-guide`) and one prompt (`build_bot`). In all of them, `agent` can be the
id, the exact name or the slug. The ones that change something work on the **draft**.

**Build**

| Tool | What it does |
|---|---|
| `list_agents()` | Lists the bots: id, name, slug, when it was trained, intents and which version each environment has. |
| `get_agent(agent)` | The full definition of the draft. |
| `agent_format_guide()` | The agent format guide with complete examples (also as the `parla://format-guide` resource). |
| `validate_agent(agent_json)` | Validates without saving and returns `{ok, errors, warnings}`: step types, slots used in steps, `{{ }}` and conditions, triggers, `goto`/`call` flows, entities in markings, regex, `interrupts`, `also`, functions (language, `run()`, Python syntax, inputs), slots and functions of the `agent` step, buttons with label, `translations` languages, `{{ secret.X }}` outside an `http` step. |
| `create_agent(agent_json)` | Validates, creates and trains a new bot. Fills in the regex of `number`, `email`, `phone` and `dni` entities if missing. Returns `{id, name, slug, trained, warnings}` (`trained.log` includes the self-evaluation). |
| `update_agent(agent, agent_json)` | Replaces the whole draft (whatever you don't send goes back to empty) and retrains. Validates first, including that the files of `file` steps exist. Production and staging don't change. |
| `train_agent(agent)` | Retrains the draft. |
| `delete_agent(agent, confirm)` | Deletes the bot with its conversations; requires `confirm=True`. |

**Test**

| Tool | What it does |
|---|---|
| `test_conversation(agent, messages, start_data=None, keep=False, environment="draft")` | Starts a conversation through the API (`mcp` channel) with `start_data` and sends each message. Returns per turn: intent, confidence, entities, `answer_to`, replies, flow, awaited slot, classifications, `language`, `handoff` and, if present, `buttons`, `via`, `sources` and `files` (names of files sent); at the end, the slots, the version used and `problems` (the «⚠» messages). The conversation is deleted unless `keep=True`. To press a button, send its `value`; for another language, `start_data={"idioma": "pt"}`. |
| `test_function(agent, function, inputs=None)` | Runs a function (by name, or with the full definition before saving it) with only the inputs it declares: `ok`, `result`/`error`, `traceback`, `logs`, `ms`, `sent` and `ignored_inputs`. |

**Versions**

| Tool | What it does |
|---|---|
| `publish_agent(agent, note, environment=None, confirm=False)` | Freezes the draft as a new version; optionally puts it in `staging` or `production` (the latter with `confirm=True`). |
| `deploy_version(agent, environment, version, confirm=False)` | Points an environment to a version (`None` empties it). Production requires `confirm=True`. |
| `list_versions(agent)` | Versions, environments and deployment log (with `previous` for rolling back). |
| `diff_agent(agent, from_ref="production", to_ref="draft")` | What changes between `production`, `staging`, `draft` or a version number. |
| `restore_version(agent, version, confirm=False)` | Resets the draft to a version and retrains it; requires `confirm=True` (unpublished changes are lost). |

**Conversations and metrics**

| Tool | What it does |
|---|---|
| `list_sessions(agent, channel, classification, date_from, date_to)` | Saved conversations, most recent first. |
| `get_session(agent, session_id)` | One conversation with its history. |
| `get_report(agent, date_from, date_to, channel)` | Conversations by classification and by day. |
| `get_analytics(agent, date_from, date_to)` | Containment, handoffs, fallbacks, CSAT, drop-off by flow and question. |

**Knowledge and improvement**

| Tool | What it does |
|---|---|
| `add_knowledge(agent, title="", text=None, url=None)` | Adds a document with `text` or with `url` (one of the two; with `url` it downloads the page and extracts the text). Same title = replaces (`replaced: true`). No retraining needed. |
| `search_knowledge(agent, query, k=3)` | Searches the way the bot does; `answers` says whether it would answer (score ≥ `knowledge_threshold`). |
| `list_unrecognized(agent, date_from, date_to)` | What it didn't understand, grouped and with a suggested intent. |
| `teach_phrases(agent, intent, phrases)` | Adds phrases to an existing intent (skips duplicates; markings must use existing entities). Doesn't retrain: run `train_agent` afterwards. |
| `list_files(agent)` | The files the person uploaded to the agent (id, name, type, size), for use in a `file` step. The MCP doesn't upload files. |
| `list_secret_names(agent)` | The **names** of the secrets, which ones are used and which are missing. The MCP never reads or writes values. |

**Prompt**: `build_bot(description)` guides the AI step by step: varied and balanced phrases, the entity type
according to the data, functions tested with `test_function`, buttons for closed options, knowledge for frequent
questions, `handoff` for complaints, system flows turned on, secrets always via `{{ secret.X }}`, classifications,
reviewing the self-evaluation, testing the draft, publishing to staging and moving to production only with the
person's OK.

## Recommended workflow

`create_agent` and `update_agent` only change the **draft**: real users see nothing until it's published.

1. Edit the draft → `test_conversation` (draft).
2. `diff_agent` → `publish_agent(note, environment="staging")` → `test_conversation(environment="staging")`.
3. With the person's approval: `deploy_version(environment="production", version=N, confirm=True)`.
4. Rollback: `deploy_version` to production with the previous version (`list_versions` shows `previous`).

## Before using it with real data

- Review the `http` steps the AI builds: a bot can call any URL from your server, including your internal network.
- Functions run code on Parla's machine. On a shared Parla, start it with `PARLA_FUNCTIONS=0`.
