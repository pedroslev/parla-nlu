# Contributing to Parla

**English** · [Español](CONTRIBUTING_es.md)

Thanks for helping. Parla is an open-source, self-hosted conversational AI builder licensed under
[Apache-2.0](LICENSE), and every feature lives in this repository: there is no closed edition to keep in sync.
Bug reports, docs fixes, translations, tests and code are all welcome.

Please follow the [Code of Conduct](CODE_OF_CONDUCT.md). Security issues go through [SECURITY.md](SECURITY.md),
never a public issue.

## Before you start

- **Small fix** (typo, obvious bug, missing test): open a pull request directly.
- **Anything bigger** (new step type, channel, dependency, API change): open an issue first so we can agree on the
  approach. Check the [roadmap](docs/ROADMAP.md) to see if it's already planned.

## Development setup

Requirements: Python 3.11 or newer. Node.js is optional (JavaScript functions), as are
[Ollama](https://ollama.com) (local AI) and `ffmpeg` (voice).

```sh
git clone https://github.com/pedroslev/parla-nlu.git
cd parla-nlu
scripts/setup.sh            # creates .venv and installs requirements.txt (or: make setup)
scripts/setup.sh --voice    # optional: faster-whisper + piper (or: make setup-voice)
make run                    # http://127.0.0.1:8000
```

The first training downloads the embedding model (~1.2 GB) to `data/models/embeddings`. Set `PARLA_EMBED_CACHE`
to reuse a copy you already have. More in [docs/development.md](docs/development.md).

## Tests

```sh
python tests/run_all.py               # all of them (or: make test, which uses .venv/bin/python)
python tests/run_all.py app mcp       # some, by name
python tests/test_app.py              # a single one
```

Tests are plain scripts with `assert`, no framework, and they never touch your `data/`. Voice tests are skipped
without the voice extras, and the model part of the AI tests is skipped without Ollama; that is not a failure.
`test_knowledge.py` and `test_mcp.py` need the embedding model. CI runs the same command on Python 3.11 and 3.12
(see [`.github/workflows/ci.yml`](.github/workflows/ci.yml)).

Any non-trivial logic you add should leave a test in `tests/`.

## Code style

- **Small and stdlib-first.** Standard library before a new dependency, JSON files before a database, no
  abstractions nobody asked for. A new dependency needs a good reason in the pull request.
- **Small functions** that do one thing and read top to bottom.
- **Comments explain the why.** Many comments are in Spanish today; new comments can be in English or Spanish.
- **UI strings are in Spanish for now** (Rioplatense, saying what to do). Internationalization of the interface is
  [planned](docs/ROADMAP.md); until then, keep new strings in Spanish and consistent with the existing ones.
- **`ponytail:` comments** mark a deliberate shortcut with a known limit, naming the limit and how to improve it.
- Optional modules (AI, voice, dates) must never break a conversation when they fail.
- Docs are in English with a Spanish copy (`name_es.md`) and a language switcher under the title. If you change one,
  update the other or say so in the pull request so someone can help.

Before pushing, a quick check:

```sh
python -m compileall -q app.py mcp_server.py parla tests
for f in web/static/*.js; do node --check "$f"; done
python tests/run_all.py
```

## Sign your commits (DCO)

Parla uses the [Developer Certificate of Origin](https://developercertificate.org/). By signing off you certify
that you wrote the change or have the right to submit it under the project's license. Add the sign-off with `-s`:

```sh
git commit -s -m "Explain what changed and why"
```

It appends `Signed-off-by: Your Name <you@example.com>` to the message. Forgot it? `git commit --amend -s` for the
last commit, or `git rebase --signoff main` for the whole branch.

## Pull requests

1. Branch from `main`, keep the change focused, and describe what and why in the template.
2. Run the tests and the checks above.
3. Update the docs (both languages when you can) and add an entry under **Unreleased** in
   [CHANGELOG.md](CHANGELOG.md) for user-visible changes.

By contributing you agree that your contribution is licensed under Apache-2.0.
