#!/usr/bin/env python3
"""Autochequeo de skills/ (buenas prácticas para asistentes de IA).  .venv/bin/python tests/test_skills.py
- Cada skills/<nombre>/SKILL.md tiene frontmatter válido (name = carpeta, kebab-case; description ≤ 1024) y < 500 líneas.
- Los links relativos de los .md existen.
- Cada bloque ```json parla-agent es un agente (o fragmento) que validate_agent acepta sin errores.
- El ejemplo completo (dental-clinic.json) valida sin errores ni advertencias.
- El servidor MCP publica cada archivo como recurso parla://skills/<skill>/<archivo>."""
import asyncio
import glob
import json
import os
import re

import support

from parla import mcp_server as m  # noqa: E402

SKILLS = os.path.join(support.ROOT, "skills")
names = sorted(os.listdir(SKILLS))
assert len(names) >= 6, names
blocks = 0
for name in names:
    folder = os.path.join(SKILLS, name)
    text = open(os.path.join(folder, "SKILL.md"), encoding="utf-8").read()
    front = re.match(r"---\n(.*?)\n---\n", text, re.S)
    assert front, "%s: falta el frontmatter" % name
    fields = dict(l.split(":", 1) for l in front.group(1).splitlines() if ":" in l)
    assert fields.get("name", "").strip() == name and re.fullmatch(r"[a-z0-9]+(-[a-z0-9]+)*", name), (name, fields)
    desc = fields.get("description", "").strip()
    assert 50 <= len(desc) <= 1024 and "<" not in desc, (name, len(desc))
    assert text.count("\n") < 500, "%s: SKILL.md tiene %d líneas" % (name, text.count("\n"))
    for md in glob.glob(os.path.join(folder, "**", "*.md"), recursive=True):
        body = open(md, encoding="utf-8").read()
        for link in re.findall(r"\]\(([\w/.-]+\.(?:md|json))\)", body):
            assert os.path.exists(os.path.join(os.path.dirname(md), link)), "%s: link roto %s" % (md, link)
        for block in re.findall(r"```json parla-agent\n(.*?)```", body, re.S):
            blocks += 1
            result = m.validate_agent(json.loads(block))
            assert result["ok"], "%s: %s" % (md, result["errors"])
assert blocks >= 6, blocks

example = json.load(open(os.path.join(SKILLS, "parla-build-bot", "examples", "dental-clinic.json"), encoding="utf-8"))
result = m.validate_agent(example)
assert result["ok"] and not result["warnings"], result
assert len(example["agent"]["tests"]) >= 4

uris = {str(r.uri) for r in asyncio.run(m.mcp.list_resources())}
assert "parla://skills" in uris
for name in names:
    assert "parla://skills/%s/SKILL.md" % name in uris, name
assert "parla://skills/parla-build-bot/examples/dental-clinic.json" in uris
assert "parla://skills/parla-build-bot/SKILL.md" in m.build_bot("un bot")
print("ok: %d skills, %d bloques parla-agent validados" % (len(names), blocks))
