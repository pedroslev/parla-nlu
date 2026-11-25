"""Usuarios y roles. Sin usuarios creados, Parla queda abierto como siempre.

users.json (permisos 600; ruta cambiable con PARLA_USERS):
{"users": [{"name", "role", "hash", "salt", "bots", "keys": [{"id", "hash", "label", "created"}]}]}
«bots»: null (ve todos los agentes; el dueño siempre) o la lista de ids de agentes que ve. Ver allowed_bot().
Interfaz: cookie `parla_session`. API/MCP: `Authorization: Bearer <clave>`.
"""
import hashlib
import hmac
import http.cookies
import json
import os
import re
import secrets
import sys
import threading
import time
import urllib.parse

from . import DATA, agents_dir, db, write_json
ROLES = ("owner", "editor", "analyst", "agent")
SESSION_HOURS = 12
LOCK = threading.Lock()
# sesiones de login: tabla logins de parla.db (db.py), con el SHA-256 del token: sobreviven a un reinicio
FAILURES = {}      # (nombre, ip) -> [instantes de intentos fallidos]
NAME = re.compile(r"[\w.@+ -]{1,40}")


def users_path():
    return os.environ.get("PARLA_USERS") or os.path.join(DATA, "users.json")


def _load():
    try:
        with open(users_path(), encoding="utf-8") as f:
            return json.load(f).get("users") or []
    except (OSError, ValueError):
        return []


def _save(users):
    write_json(users_path(), {"users": users}, mode=0o600, indent=2)


def _scrypt(password, salt):
    return hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=2 ** 14, r=8, p=1, dklen=32).hex()


def _set_password(user, password):
    if not isinstance(password, str) or len(password) < 5:      # ponytail: corta a pedido del usuario (admin/admin en su compu); subir si se expone
        raise ValueError("la contraseña tiene que tener al menos 5 caracteres")
    user["salt"] = secrets.token_hex(16)
    user["hash"] = _scrypt(password, user["salt"])


def _add_key(users, user, label):
    key = "parla_" + secrets.token_urlsafe(32)
    entry = {"id": secrets.token_hex(4), "hash": hashlib.sha256(key.encode()).hexdigest(),
             "label": str(label or "Clave").strip()[:60] or "Clave", "created": time.strftime("%Y-%m-%dT%H:%M:%S")}
    user.setdefault("keys", []).append(entry)
    _save(users)
    return {"id": entry["id"], "label": entry["label"], "created": entry["created"], "key": key}


def issue_key(name, label):
    """Una clave de API nueva para ese usuario (la usa «Conectar con IA» para que el MCP pase el login)."""
    users = _load()
    user = _find(users, name)
    return _add_key(users, user, label)["key"] if user else None


def _find(users, name):
    return next((u for u in users if u["name"].lower() == str(name).lower()), None)


def _scope(user):
    return None if user["role"] == "owner" else user.get("bots")


def allowed_bot(user, agent_id):
    """¿Ese usuario ve ese agente? None (sin usuarios o chat público del widget) y bots null: todos."""
    return not user or _scope(user) is None or agent_id in user["bots"]


def grant(user, agent_id):
    """Quien ve solo algunos agentes y crea (o importa) uno, también ve el nuevo."""
    if allowed_bot(user, agent_id):
        return
    with LOCK:
        users = _load()
        found = _find(users, user["name"])
        if found and _scope(found) is not None and agent_id not in found["bots"]:
            found["bots"].append(agent_id)
            _save(users)


def _app():
    return sys.modules.get("parla.server") or sys.modules.get("__main__")      # sin import circular: app ya está cargado


def _valid_bots(bots):
    if bots is None:
        return None
    if not isinstance(bots, list):
        raise ValueError("«bots» tiene que ser null (todos los agentes) o una lista de ids de agentes.")
    for bot in bots:
        if not (isinstance(bot, str) and re.fullmatch(r"[0-9a-f]{8}", bot) and os.path.exists(os.path.join(agents_dir(), bot + ".json"))):
            raise ValueError("No existe el agente «%s»." % bot)
    return list(dict.fromkeys(bots))


def _public(user):
    return {"name": user["name"], "role": user["role"], "bots": _scope(user),
            "keys": [{k: key[k] for k in ("id", "label", "created")} for key in user.get("keys", [])]}


def _owners(users):
    return [u for u in users if u["role"] == "owner"]


def current(handler, users=None):
    """{"name", "role"} de quien hace el pedido (cookie o Bearer), o None."""
    users = _load() if users is None else users
    name = None
    bearer = (handler.headers.get("Authorization") or "").strip()
    if bearer.lower().startswith("bearer "):
        digest = hashlib.sha256(bearer[7:].strip().encode()).hexdigest()
        for user in users:
            if any(hmac.compare_digest(digest, key["hash"]) for key in user.get("keys", [])):
                name = user["name"]
    else:
        cookie = http.cookies.SimpleCookie()
        try:
            cookie.load(handler.headers.get("Cookie") or "")
        except http.cookies.CookieError:
            pass
        token = cookie["parla_session"].value if "parla_session" in cookie else None
        found = db.q("SELECT name, expires FROM logins WHERE token = ?", (_digest(token),)) if token else None
        if found and found[0][1] > time.time():
            name = found[0][0]
        elif found:
            db.q("DELETE FROM logins WHERE token = ?", (_digest(token),))
    user = _find(users, name) if name else None
    return {"name": user["name"], "role": user["role"], "bots": _scope(user)} if user else None


def hosts():
    """PARLA_HOSTS: nombres (host[:puerto]) por los que también se entra a Parla, p. ej. detrás de un proxy."""
    return [h.strip().lower() for h in os.environ.get("PARLA_HOSTS", "").split(",") if h.strip()]


def _secure(handler):
    """¿El pedido llegó por HTTPS? (PARLA_SECURE_COOKIE=1, o el proxy de un PARLA_HOSTS lo avisa)."""
    if os.environ.get("PARLA_SECURE_COOKIE") == "1":
        return True
    host = (handler.headers.get("Host") or "").lower()
    return (handler.headers.get("X-Forwarded-Proto") or "").lower() == "https" and (
        host in hosts() or re.sub(r":\d+$", "", host) in hosts())


def _cookie(handler, token, age):
    secure = "; Secure" if _secure(handler) else ""
    return {"Set-Cookie": "parla_session=%s; HttpOnly; SameSite=Strict; Path=/; Max-Age=%d%s" % (token, age, secure)}


def _digest(token):
    return hashlib.sha256(token.encode()).hexdigest()


def _login(handler, name):
    token = secrets.token_urlsafe(32)
    db.q("INSERT INTO logins (token, name, expires) VALUES (?, ?, ?)", (_digest(token), name, time.time() + SESSION_HOURS * 3600))
    return _cookie(handler, token, SESSION_HOURS * 3600)


def _drop_sessions(name):
    db.q("DELETE FROM logins WHERE name = ?", (name,))       # siempre el user["name"] exacto, como en _login


def handle(handler, method, url, data):
    """Rutas /api/auth/* y /api/users*. Devuelve (status, body, headers) o None si no es suya."""
    if not (url.startswith("/api/auth/") or url == "/api/users" or url.startswith("/api/users/")):
        return None
    with LOCK:
        try:
            return _handle(handler, method, url, data)
        except ValueError as error:
            return 400, {"error": str(error)}, {}


def _handle(handler, method, url, data):
    users = _load()
    me = current(handler, users)
    if url == "/api/auth/me" and method == "GET":
        return 200, {"enabled": bool(users), "user": me}, {}
    if url == "/api/auth/login" and method == "POST":
        name, password = str(data.get("name") or "").strip(), str(data.get("password") or "")
        key = (name.lower(), handler.client_address[0])
        now = time.time()
        for old in [k for k, times in FAILURES.items() if times[-1] <= now - 60]:     # que no crezca sin fin
            FAILURES.pop(old, None)
        recent = [t for t in FAILURES.get(key, []) if t > now - 60]
        if len(recent) >= 5:
            FAILURES[key] = recent
            return 429, {"error": "Demasiados intentos. Esperá un minuto y probá de nuevo."}, {}
        user = _find(users, name)
        ok = hmac.compare_digest(_scrypt(password, user["salt"] if user else "00" * 16), user["hash"] if user else "")   # mismo tiempo exista o no
        if not user or not ok:
            FAILURES[key] = recent + [now]
            return 401, {"error": "Usuario o contraseña incorrectos."}, {}
        FAILURES.pop(key, None)
        return 200, {"enabled": True, "user": {"name": user["name"], "role": user["role"], "bots": _scope(user)}}, _login(handler, user["name"])
    if url == "/api/auth/logout" and method == "POST":
        cookie = http.cookies.SimpleCookie()
        try:
            cookie.load(handler.headers.get("Cookie") or "")
        except http.cookies.CookieError:
            pass
        if "parla_session" in cookie:
            db.q("DELETE FROM logins WHERE token = ?", (_digest(cookie["parla_session"].value),))
        return 200, {"enabled": bool(users), "user": None}, _cookie(handler, "", 0)
    if url.startswith("/api/auth/"):
        return 404, {"error": "no existe"}, {}

    # /api/users*: solo el dueño. Excepción: crear el primer usuario (que queda como dueño)
    parts = [urllib.parse.unquote(p) for p in url[len("/api/users"):].split("/") if p]
    if not users and parts == [] and method == "POST":
        user = {"name": _valid_name(data.get("name"), users), "role": "owner", "keys": []}
        _set_password(user, data.get("password"))
        _save([user])
        return 200, _public(user), _login(handler, user["name"])
    if not users:
        if parts == [] and method == "GET":
            return 200, {"users": []}, {}
        return 400, {"error": "Todavía no hay usuarios: creá primero el usuario dueño."}, {}
    if not me:
        return 401, {"error": "Iniciá sesión para seguir."}, {}
    if me["role"] != "owner":
        return 403, {"error": "Solo el dueño puede manejar usuarios."}, {}
    if parts == [] and method == "GET":
        return 200, {"users": [_public(u) for u in users]}, {}
    if parts == [] and method == "POST":
        user = {"name": _valid_name(data.get("name"), users), "role": _valid_role(data.get("role")), "keys": []}
        if user["role"] != "owner":
            user["bots"] = _valid_bots(data.get("bots"))
        _set_password(user, data.get("password"))
        _save(users + [user])
        return 200, _public(user), {}
    user = _find(users, parts[0]) if parts else None
    if not user:
        return 404, {"error": "no hay un usuario «%s»" % (parts[0] if parts else "")}, {}
    if len(parts) == 1 and method == "PUT":
        if "role" in data:
            role = _valid_role(data["role"])
            if user["role"] == "owner" and role != "owner" and len(_owners(users)) == 1:
                raise ValueError("Tiene que quedar al menos un dueño: nombrá a otro dueño antes de cambiarle el rol.")
            user["role"] = role
            if role == "owner":
                user.pop("bots", None)
        if "bots" in data and user["role"] != "owner":
            user["bots"] = _valid_bots(data["bots"])
        if data.get("password"):
            _set_password(user, data["password"])
            _drop_sessions(user["name"])
        _save(users)
        return 200, _public(user), {}
    if len(parts) == 1 and method == "DELETE":
        if user["role"] == "owner" and len(_owners(users)) == 1:
            raise ValueError("No se puede borrar al único dueño.")
        _save([u for u in users if u is not user])
        _drop_sessions(user["name"])
        return 200, {"deleted": user["name"]}, {}
    if parts[1:] == ["keys"] and method == "POST":
        return 200, _add_key(users, user, data.get("label")), {}
    if len(parts) == 3 and parts[1] == "keys" and method == "DELETE":
        before = len(user.get("keys", []))
        user["keys"] = [k for k in user.get("keys", []) if k["id"] != parts[2]]
        if len(user["keys"]) == before:
            return 404, {"error": "no existe esa clave"}, {}
        _save(users)
        return 200, _public(user), {}
    return 405, {"error": "método no permitido"}, {}


def _valid_name(name, users):
    name = str(name or "").strip()
    if not NAME.fullmatch(name):
        raise ValueError("El nombre de usuario tiene que tener de 1 a 40 letras, números, espacios o . @ + - _")
    if _find(users, name):
        raise ValueError("Ya hay un usuario «%s»." % name)
    return name


def _valid_role(role):
    if role not in ROLES:
        raise ValueError("El rol tiene que ser uno de: dueño (owner), editor, analista (analyst) o atención (agent).")
    return role


AGENT_ROUTES = (     # rol «agent» (atención): solo la Bandeja
    ("GET", r"/api/agents(/[0-9a-f]{8})?"),
    ("GET|POST", r"/api/agents/[0-9a-f]{8}/(inbox|sessions/[A-Za-z0-9_.@+-]+/(reply|take|release))"),
    ("GET", r"/api/v1/bots/[^/]+/sessions/[^/]+(/messages)?"),
)


def _public_widget(method, url):
    """POST /api/v1/bots/{bot}/(events|audio) de un bot con el widget prendido: es el chat público."""
    # también GET …/sessions/{sid}/messages de una charla del widget (canal «web»): el sessionId hace de llave
    post = method == "POST" and re.fullmatch(r"/api/v1/bots/([^/]+)/(events|audio)", url)
    poll = method == "GET" and re.fullmatch(r"/api/v1/bots/([^/]+)/sessions/([^/]+)/messages", url)
    match = post or poll
    if not match:
        return False
    main = _app()
    find_bot = getattr(main, "find_bot", None)
    agent = find_bot(urllib.parse.unquote(match.group(1))) if find_bot else None
    if not ((agent or {}).get("widget") or {}).get("enabled"):
        return False
    if post:
        return True
    sid = urllib.parse.unquote(match.group(2))
    if not main.SESSION_ID.fullmatch(sid):
        return False
    record = main.load_session(agent["id"], sid)
    return (record or {}).get("channel") == "web"


def _bot_of(url, data):
    """El id del agente al que apunta el pedido (/api/agents/<id>/…, /api/v1/bots/<bot>/…), o None."""
    match = re.fullmatch(r"/api/agents/([0-9a-f]{8})(/.*)?", url)
    if match:
        return match.group(1)
    match = re.fullmatch(r"/api/v1/bots/([^/]+)(/.*)?", url)
    if match:
        agent = _app().find_bot(urllib.parse.unquote(match.group(1)))
        return agent["id"] if agent else None      # si no existe (o es ambiguo), que conteste server.py
    return None      # /api/ai/status {"agent"}: lo chequea server.py, que es el que lee el cuerpo


def guard(handler, method, url, data):
    """Antes de cada /api/ (sin leer el cuerpo): None si puede seguir, o (status, body) para cortar.
    Deja handler.user y handler.public (True = chat público del widget sin sesión: server.py lo limita)."""
    handler.user, handler.public = None, False
    users = _load()
    if not users:
        return None
    handler.user = current(handler, users)
    if _public_widget(method, url):
        handler.public = not handler.user or not allowed_bot(handler.user, _bot_of(url, data))
        return None
    role = (handler.user or {}).get("role")
    if not role:
        return 401, {"error": "Iniciá sesión para seguir."}
    bot = _bot_of(url, data)
    if bot and not allowed_bot(handler.user, bot):
        return 404, {"error": "no existe ese agente"}      # ni que existe: para ese usuario no está
    if role in ("owner", "editor"):
        return None
    if role == "analyst":
        return None if method == "GET" else (403, {"error": "Tu usuario es de solo lectura: podés mirar, pero no cambiar nada."})
    if any(re.fullmatch(m, method) and re.fullmatch(p, url) for m, p in AGENT_ROUTES):
        return None
    return 403, {"error": "Tu usuario es de atención: solo podés usar la Bandeja para leer y responder conversaciones."}
