# Skills for AI assistants

**English** · [Español](skills_es.md)

Parla's [MCP server](mcp.md) gives an assistant the *tools* to build bots. The **skills** in
[`skills/`](../skills) give it the *know-how*: how Parla's NLU really scores phrases, which entity kind to pick,
how to design questions, buttons and handoffs, how to call APIs without touching secrets, how to test and
publish safely. They use the [Agent Skills](https://agentskills.io) format (a folder with a `SKILL.md` that has a
`name` and a `description`, plus reference files the assistant reads only when needed), so Claude Code, Claude
Desktop / claude.ai, Codex, Cursor and others can load them.

| Skill | What it is for |
|---|---|
| [`parla-build-bot`](../skills/parla-build-bot/SKILL.md) | The end-to-end workflow with the MCP tools: discover, design, create, validate, read the self-check, test, publish. Includes a verified example bot ([`dental-clinic.json`](../skills/parla-build-bot/examples/dental-clinic.json)). |
| [`parla-nlu-design`](../skills/parla-nlu-design/SKILL.md) | Intents, phrases, entity kinds, marks, synonyms, `phrasings`, thresholds, with scores measured on the real model. |
| [`parla-flow-design`](../skills/parla-flow-design/SKILL.md) | Flows and steps, questions and re-asks, buttons per channel, conditions, interruptions, system flows, voice and multilingual bots. |
| [`parla-integrations`](../skills/parla-integrations/SKILL.md) | `http` steps and secrets, functions, files, knowledge base, AI features and privacy, widget, WhatsApp and Telegram, personal data. |
| [`parla-testing-and-release`](../skills/parla-testing-and-release/SKILL.md) | Conversation tests (including negative paths), the publish gate, staging/production, rollback, improving from real traffic. |
| [`parla-migrate-from-rasa`](../skills/parla-migrate-from-rasa/SKILL.md) | `import_rasa_project` and the checklist after it. |

A human-readable summary of the same advice is in [best-practices.md](best-practices.md).

## Without installing anything: the MCP resources

Once Parla is connected («Conectar con IA», see [mcp.md](mcp.md)), the MCP server itself serves the skills as
resources: `parla://skills` (the index) and `parla://skills/<skill>/<file>` (each `SKILL.md` and its reference
files). The `build_bot` prompt and the server instructions tell the model to read
`parla://skills/parla-build-bot/SKILL.md` first. Clients that let the model read resources (or let you attach
them, like Claude Desktop's «+» menu or `@` mentions in Claude Code) get the skills with no extra setup.

Installing them as skills (below) is still better where it's supported: the assistant then loads the right one
automatically from its description, even before it talks to Parla.

## Claude Code

Personal (every project), as symlinks that follow `git pull`:

```sh
make skills-install                     # links skills/* into ~/.claude/skills/
```

It prints what it links, updates its own links, and skips (with a message) any folder that already exists and
isn't a link. By hand, or for a single project:

```sh
mkdir -p ~/.claude/skills && ln -s "$PWD"/skills/* ~/.claude/skills/          # personal
mkdir -p .claude/skills && cp -R /path/to/parla/skills/* .claude/skills/       # in your bot's repository
```

Restart Claude Code; `/skills` (or asking «what skills do you have?») lists them. Then just ask «armame un bot
que tome turnos para la peluquería».

## Claude Desktop and claude.ai

Skills are uploaded as zip files (one per skill) in **Settings → Capabilities → Skills** (the exact menu name may
vary with the app version; code execution must be on):

```sh
cd skills && for d in */; do (cd "$d" && zip -qr "../../parla-${d%/}.zip" .); done; cd ..
```

Upload each `parla-*.zip`. Connect the MCP server too (see [mcp.md](mcp.md)): the skills tell the model how to
use its tools.

## Codex, Cursor and other assistants

They don't need a special format: point them at the files.

- **Codex** (`AGENTS.md` in your repository or `~/.codex/AGENTS.md`):

  ```markdown
  When building or changing Parla bots, first read /path/to/parla/skills/parla-build-bot/SKILL.md
  and then the skill in /path/to/parla/skills/ that matches the task (nlu-design, flow-design,
  integrations, testing-and-release, migrate-from-rasa).
  ```

- **Cursor**: a project rule (`.cursor/rules/parla.mdc`) with the same text, or add the `skills/` folder to the
  chat context.
- **Any MCP client**: rely on the `parla://skills` resources and the `build_bot` prompt.

## How they pair with the MCP

The skills never replace the tools: they tell the model to call `agent_format_guide` for exact field shapes,
`validate_agent` before saving, `test_conversation` and `run_tests` before publishing, and to ask the person
before anything reaches production. They also forbid handling secret values: the model references
`{{ secret.NAME }}` and asks the person to load the value in «Claves».

## For contributors

Every ```` ```json parla-agent ```` block in the skills is an agent (or a small self-contained one) that must pass
`validate_agent` with no errors. `tests/test_skills.py` checks that, the frontmatter (`name` = folder,
kebab-case, `description` ≤ 1024 characters), that each `SKILL.md` stays under 500 lines, that relative links
exist, that the example bot validates with no warnings, and that the MCP server serves every file. When the
engine changes, re-check the numbers in `parla-nlu-design/reference.md`.
