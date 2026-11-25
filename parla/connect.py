"""Conectar con IA: registra el servidor MCP de Parla (mcp_server.py) en Claude Code, Codex, Claude Desktop o Cursor.

Sólo se aceptan los ids de CLIENTS; nada que venga del pedido se usa como comando o ruta.
"""
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import tomllib

from . import ROOT as HERE          # el .venv y el mcp_server.py de la raíz (las configs ya apuntan ahí)
NAME = "parla"
CLIENTS = {"claude-code": "Claude Code", "codex": "Codex", "claude-desktop": "Claude Desktop", "cursor": "Cursor"}
NEXT = "Abrí una conversación nueva y pedile: «armame un bot que…». Parla tiene que estar abierto mientras lo usás."


def home(*parts):
    return os.path.join(os.path.expanduser("~"), *parts)


def python():
    for p in (os.path.join(HERE, ".venv", "bin", "python"), os.path.join(HERE, ".venv", "Scripts", "python.exe")):
        if os.path.exists(p):
            return p
    return sys.executable


def server(parla_url, token=None):
    env = {"PARLA_URL": parla_url, **({"PARLA_TOKEN": token} if token else {})}   # token: clave de API si Parla tiene usuarios
    return {"command": python(), "args": [os.path.join(HERE, "mcp_server.py")], "env": env}


def desktop_config():
    if sys.platform == "win32":
        return os.path.join(os.environ.get("APPDATA") or home("AppData", "Roaming"), "Claude", "claude_desktop_config.json")
    if sys.platform == "darwin":
        return home("Library", "Application Support", "Claude", "claude_desktop_config.json")
    return home(".config", "Claude", "claude_desktop_config.json")


def files():
    return {"codex": home(".codex", "config.toml"), "claude-desktop": desktop_config(), "cursor": home(".cursor", "mcp.json")}


def claude_cli():
    # una app abierta desde el Dock no siempre tiene ~/.local/bin en el PATH
    found = shutil.which("claude")
    return found or next((p for p in (home(".local", "bin", "claude"), home(".claude", "local", "claude")) if os.path.exists(p)), None)


# ---------- archivos de configuración ----------
def backup_and_write(file, text):
    os.makedirs(os.path.dirname(file), exist_ok=True)
    if os.path.exists(file):
        shutil.copy2(file, file + ".parla-backup")
    tmp = file + ".parla-tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(text)
    os.replace(tmp, file)


def read_json(file):
    if not os.path.exists(file):
        return {}
    with open(file, encoding="utf-8") as f:
        raw = f.read()
    try:
        data = json.loads(raw) if raw.strip() else {}
    except ValueError:
        raise ValueError("%s no es un JSON válido; no lo toqué para no romperlo. Arreglalo o agregá Parla a mano." % file)
    if not isinstance(data, dict) or not isinstance(data.get("mcpServers", {}), dict):
        raise ValueError("%s tiene un formato inesperado; no lo toqué. Agregá Parla a mano." % file)
    return data


def json_set(data, entry):
    """Devuelve una copia con mcpServers.parla = entry (o sin parla si entry es None); el resto queda igual."""
    servers = {k: v for k, v in data.get("mcpServers", {}).items() if k != NAME}
    if entry is not None:
        servers[NAME] = entry
    return {**data, "mcpServers": servers}


TABLE = re.compile(r'\s*\[\s*mcp_servers\s*\.\s*"?%s"?\s*[.\]]' % NAME)


def toml_block(entry):
    q = json.dumps   # un string JSON es un string básico TOML válido
    env = ", ".join("%s = %s" % (k, q(v)) for k, v in entry["env"].items())
    return "[mcp_servers.%s]\ncommand = %s\nargs = [%s]\nenv = { %s }\n" % (NAME, q(entry["command"]), ", ".join(map(q, entry["args"])), env)


def toml_set(text, entry):
    """Saca la tabla [mcp_servers.parla] (y sus subtablas) y, si entry no es None, agrega la nueva al final."""
    kept, inside = [], False
    for line in text.splitlines(keepends=True):
        if line.lstrip().startswith("["):
            inside = bool(TABLE.match(line))
        if not inside:
            kept.append(line)
    out = "".join(kept).rstrip("\n")
    if entry is not None:
        out = (out + "\n\n" if out else "") + toml_block(entry)
    elif out:
        out += "\n"
    try:
        tomllib.loads(out)   # si algo quedó mal, falla acá y el archivo no se toca
    except tomllib.TOMLDecodeError as error:
        raise ValueError("No pude editar la configuración de Codex sin romperla (%s); no la toqué. Usá «Hacerlo a mano»." % error)
    return out


def has_toml(text):
    return any(TABLE.match(line) for line in text.splitlines())


def read_text(file):
    if not os.path.exists(file):
        return ""
    with open(file, encoding="utf-8") as f:
        return f.read()


# ---------- estado ----------
def registered(cid):
    try:
        if cid == "claude-code":
            return NAME in read_json(home(".claude.json")).get("mcpServers", {})
        if cid == "codex":
            return has_toml(read_text(files()["codex"]))
        return NAME in read_json(files()[cid]).get("mcpServers", {})
    except (OSError, ValueError):
        return False


def installed(cid):
    if cid == "claude-code":
        return bool(claude_cli())
    if cid == "codex":
        return bool(shutil.which("codex")) or os.path.isdir(home(".codex"))
    if cid == "cursor":
        return bool(shutil.which("cursor")) or os.path.isdir(home(".cursor"))
    return os.path.isdir(os.path.dirname(desktop_config()))


def claude_add_args(parla_url, token=None):
    s = server(parla_url, token)
    env = [x for k, v in s["env"].items() for x in ("-e", "%s=%s" % (k, v))]
    return ["mcp", "add", "--scope", "user", NAME, *env, "--", s["command"], *s["args"]]


def manual(cid, parla_url):
    s = server(parla_url)
    if cid == "claude-code":
        return {"kind": "command", "file": None, "text": shlex.join(["claude", *claude_add_args(parla_url)]),
                "how": "Pegá esto en la Terminal y apretá Enter."}
    file = files()[cid]
    if cid == "codex":
        return {"kind": "toml", "file": file, "text": toml_block(s), "how": "Agregá esto al final del archivo %s (crealo si no existe)." % file}
    return {"kind": "json", "file": file, "text": json.dumps({"mcpServers": {NAME: s}}, indent=2, ensure_ascii=False),
            "how": "Abrí %s y agregá «parla» adentro de «mcpServers» (si el archivo no existe, crealo con esto)." % file}


def clients_status(parla_url):
    return [{"id": cid, "name": name, "installed": installed(cid), "connected": registered(cid), "manual": manual(cid, parla_url)}
            for cid, name in CLIENTS.items()]


# ---------- conectar / desconectar ----------
def run_claude(args):
    cli = claude_cli()
    if not cli:
        raise ValueError("No encontré Claude Code (el comando «claude») en esta compu. Instalalo o usá «Hacerlo a mano».")
    try:
        done = subprocess.run([cli, *args], capture_output=True, text=True, timeout=30, stdin=subprocess.DEVNULL)
    except subprocess.TimeoutExpired:
        raise ValueError("Claude Code tardó demasiado en responder. Probá de nuevo o usá «Hacerlo a mano».")
    return done.returncode, (done.stderr or done.stdout).strip()


def check(cid):
    if cid not in CLIENTS:
        raise ValueError("no conozco ese asistente")


def connect(cid, parla_url, token=None):
    check(cid)
    name = CLIENTS[cid]
    if cid == "claude-code":
        if registered(cid):
            run_claude(["mcp", "remove", "--scope", "user", NAME])   # se vuelve a agregar con la ruta y el puerto de ahora
        code, out = run_claude(claude_add_args(parla_url, token))
        if code:
            raise ValueError("Claude Code no aceptó el cambio: %s" % (out or "error %d" % code))
        return {"ok": True, "message": "Listo, Parla quedó conectado a Claude Code. " + NEXT}
    file = files()[cid]
    if cid == "codex":
        backup_and_write(file, toml_set(read_text(file), server(parla_url, token)))
        return {"ok": True, "message": "Listo, Parla quedó conectado a Codex. Si Codex estaba abierto, cerralo y volvé a abrirlo. " + NEXT}
    backup_and_write(file, json.dumps(json_set(read_json(file), server(parla_url, token)), indent=2, ensure_ascii=False) + "\n")
    return {"ok": True, "message": "Listo, Parla quedó conectado a %s. Reiniciá %s (cerralo del todo y volvé a abrirlo). %s" % (name, name, NEXT)}


def disconnect(cid):
    check(cid)
    name = CLIENTS[cid]
    if not registered(cid):
        return {"ok": True, "message": "Parla no estaba conectado a %s." % name}
    if cid == "claude-code":
        code, out = run_claude(["mcp", "remove", "--scope", "user", NAME])
        if code:
            raise ValueError("Claude Code no aceptó el cambio: %s" % (out or "error %d" % code))
    elif cid == "codex":
        backup_and_write(files()[cid], toml_set(read_text(files()[cid]), None))
    else:
        file = files()[cid]
        backup_and_write(file, json.dumps(json_set(read_json(file), None), indent=2, ensure_ascii=False) + "\n")
    return {"ok": True, "message": "Listo, Parla ya no está conectado a %s. Si estaba abierto, reinicialo." % name}
