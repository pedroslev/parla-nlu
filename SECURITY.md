# Security policy

**English** · [Español](SECURITY_es.md)

## Supported versions

Parla is released from `main`. Security fixes go to the **latest `main`** (and the next tagged release cut from
it); older releases and branches don't get backports. Upgrade to the latest version before reporting.

| Version | Supported |
|---|---|
| latest `main` / latest release | Yes |
| anything older | No |

## Reporting a vulnerability

**Please don't open a public issue, discussion or pull request for a security problem.**

Report it privately through GitHub's private vulnerability reporting:
**<https://github.com/pedroslev/parla-nlu/security/advisories/new>** (or **Security → Report a vulnerability** on
the repository page).

Include, if you can:

- The affected version or commit, and how Parla was run (local, Docker, Kubernetes; behind a proxy or not).
- Steps to reproduce, a proof of concept, and what an attacker gains.
- Whether users had been created (with no users Parla is open by design, see below).

What to expect: an acknowledgement within a few days, a fix or mitigation plan once the issue is confirmed, and
credit in the advisory and [CHANGELOG.md](CHANGELOG.md) if you want it. Please give us reasonable time to release a
fix before disclosing publicly.

## Scope

In scope: the code in this repository, including the HTTP server and engine (`parla/`), authentication, roles and
API keys, the secret vault, the public API and web widget (`/api/v1`, `web/static/widget.js`), the MCP server,
«Conectar con IA», the `Dockerfile`, `docker-compose.yml` and the manifests in `deploy/`.

Out of scope, or working as documented in [docs/security.md](docs/security.md):

- An instance with **no users created**: until the first user exists, anyone who reaches the port is the owner.
- Behavior of someone who can **edit a bot**: they are trusted (they can make `http` steps call any URL and, as
  owner with functions on, run code). Functions are not a sandbox.
- Exposing the admin interface to the internet without the steps in
  [Before exposing it to the internet](docs/security.md#before-exposing-it-to-the-internet).
- Vulnerabilities in third-party dependencies or models with no Parla-specific impact (report them upstream;
  Dependabot tracks updates here).
- Denial of service that needs large volumes of traffic, and findings from automated scanners without a working
  impact.

The threat model, what Parla protects and what it doesn't yet, is in [docs/security.md](docs/security.md).
