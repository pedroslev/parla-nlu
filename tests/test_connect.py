"""Pruebas de connect.py contra un HOME temporal: nunca toca la configuración real. Correr: .venv/bin/python tests/test_connect.py"""
import json
import os
import tempfile
import tomllib

TMP = tempfile.mkdtemp()
os.environ["HOME"] = TMP
os.environ["USERPROFILE"] = TMP
os.environ["APPDATA"] = os.path.join(TMP, "AppData")
os.environ["PATH"] = ""   # sin CLIs: nada de subprocess contra el claude real

import support  # noqa: E402,F401  (repo en sys.path)
from parla import connect  # noqa: E402

assert connect.home() == TMP and all(f.startswith(TMP) for f in connect.files().values())
URL = "http://127.0.0.1:8011"

# JSON: conserva el resto y es idempotente
for cid in ("claude-desktop", "cursor"):
    file = connect.files()[cid]
    os.makedirs(os.path.dirname(file), exist_ok=True)
    original = {"preferences": {"x": 1}, "mcpServers": {"otro": {"command": "node", "args": ["a.js"]}}}
    with open(file, "w") as f:
        json.dump(original, f)
    assert not connect.registered(cid)
    r = connect.connect(cid, URL)
    assert r["ok"] and "Reiniciá" in r["message"]
    first = open(file).read()
    data = json.loads(first)
    assert data["preferences"] == {"x": 1} and data["mcpServers"]["otro"] == original["mcpServers"]["otro"]
    assert data["mcpServers"]["parla"]["env"] == {"PARLA_URL": URL}
    assert data["mcpServers"]["parla"]["args"][0].endswith("mcp_server.py")
    assert json.load(open(file + ".parla-backup")) == original
    connect.connect(cid, URL)
    assert open(file).read() == first, "conectar dos veces da lo mismo"
    assert connect.registered(cid)
    connect.disconnect(cid)
    assert json.load(open(file)) == original
    assert "no estaba" in connect.disconnect(cid)["message"]

# JSON roto: no se pisa
file = connect.files()["cursor"]
with open(file, "w") as f:
    f.write("{roto")
try:
    connect.connect("cursor", URL)
    raise AssertionError("debió fallar")
except ValueError:
    pass
assert open(file).read() == "{roto"

# Claude Desktop sin archivo previo: se crea
os.remove(connect.files()["claude-desktop"])
connect.connect("claude-desktop", URL)
assert list(json.load(open(connect.files()["claude-desktop"]))["mcpServers"]) == ["parla"]

# TOML: agrega / reemplaza sólo [mcp_servers.parla] (y subtablas)
toml = '''model = "gpt-5"

[mcp_servers.otro]
command = "node"

[mcp_servers.parla]
command = "viejo"

[mcp_servers.parla.env]
PARLA_URL = "http://127.0.0.1:1"

[plugins."x@y"]
enabled = true
'''
entry = connect.server(URL)
out = connect.toml_set(toml, entry)
data = tomllib.loads(out)
assert data["model"] == "gpt-5" and data["mcp_servers"]["otro"] == {"command": "node"} and data["plugins"] == {"x@y": {"enabled": True}}
assert data["mcp_servers"]["parla"] == entry
assert connect.toml_set(out, entry) == out, "idempotente"
removed = tomllib.loads(connect.toml_set(out, None))
assert "parla" not in removed["mcp_servers"] and removed["plugins"] == data["plugins"]
assert tomllib.loads(connect.toml_set("", entry))["mcp_servers"]["parla"] == entry

file = connect.files()["codex"]
os.makedirs(os.path.dirname(file), exist_ok=True)
with open(file, "w") as f:
    f.write('model = "gpt-5"\n')
assert connect.installed("codex") and not connect.registered("codex")
connect.connect("codex", URL)
assert connect.registered("codex") and tomllib.load(open(file, "rb"))["model"] == "gpt-5"
assert open(file + ".parla-backup").read() == 'model = "gpt-5"\n'
connect.disconnect("codex")
assert tomllib.load(open(file, "rb")) == {"model": "gpt-5"}

# ids desconocidos: rechazados
for bad in ("../../etc", "rm -rf", "", "None", "claude"):
    for fn in (lambda b: connect.connect(b, URL), connect.disconnect):
        try:
            fn(bad)
            raise AssertionError("aceptó " + bad)
        except ValueError:
            pass

# Claude Code sin CLI: error claro, instrucción manual con rutas absolutas
assert not connect.installed("claude-code")
try:
    connect.connect("claude-code", URL)
    raise AssertionError("debió fallar")
except ValueError as e:
    assert "Hacerlo a mano" in str(e)
status = {c["id"]: c for c in connect.clients_status(URL)}
assert set(status) == set(connect.CLIENTS)
cmd = status["claude-code"]["manual"]["text"]
assert cmd.startswith("claude mcp add --scope user parla -e PARLA_URL=" + URL + " -- /") and cmd.endswith("mcp_server.py")
print("ok: test_connect")
