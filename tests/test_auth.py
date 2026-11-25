"""Usuarios, roles y claves. Levanta su propia copia del servidor (puerto libre) con datos y users.json temporales."""
import http.client
import json
import os
import shutil
import stat
import time
import urllib.parse

import support  # noqa: E402

TMP = support.temp_data()
AGENTS = TMP          # vault.py lee AGENTS de __main__ cuando app no está cargado: las claves de prueba van acá

# ---------- vault (en este proceso) ----------
from parla import vault  # noqa: E402

vid = "abcd1234"
assert vault.names(vid) == [] and vault.values(vid) == {}
assert vault.put(vid, "api key clima", "s3cr3t-valor") == "API_KEY_CLIMA"
vault.put(vid, "Token", "xyz")
assert vault.names(vid) == ["API_KEY_CLIMA", "TOKEN"]
assert vault.values(vid) == {"API_KEY_CLIMA": "s3cr3t-valor", "TOKEN": "xyz"}
secret_file = os.path.join(TMP, vid + ".secrets.json")
assert stat.S_IMODE(os.stat(secret_file).st_mode) == 0o600
assert vault.mask("Bearer s3cr3t-valor y xyz", vid) == "Bearer •••• y xyz"     # menos de 4 letras no se tapa
for bad in (("", "v"), ("!!!", "v"), ("OK", "")):
    try:
        vault.put(vid, *bad)
        raise AssertionError(bad)
    except ValueError as error:
        assert str(error)
vault.delete(vid, "api_key_clima")
vault.delete(vid, "TOKEN")
assert not os.path.exists(secret_file) and vault.names(vid) == []
assert vault.names("../etc") == [] and vault.mask("hola", "../etc") == "hola"

# ---------- servidor ----------
USERS = os.path.join(TMP, "users.json")
REAL_USERS = os.path.join(support.ROOT, "data", "users.json")
real_before = open(REAL_USERS, "rb").read() if os.path.exists(REAL_USERS) else None
DATA = os.path.join(TMP, "server")       # el servidor de prueba guarda todo acá
server, PORT = support.start_server(DATA, USERS)


def call(method, path, body=None, cookie=None, token=None):
    conn = http.client.HTTPConnection("127.0.0.1", PORT, timeout=30)
    headers = {"Content-Type": "application/json"}
    if cookie:
        headers["Cookie"] = cookie
    if token:
        headers["Authorization"] = "Bearer " + token
    conn.request(method, path, json.dumps(body) if body is not None else None, headers)
    r = conn.getresponse()
    raw = r.read()
    conn.close()
    try:
        data = json.loads(raw)
    except ValueError:
        data = raw
    return r.status, data, r.getheader("Set-Cookie")


def cookie_of(set_cookie):
    assert set_cookie and "HttpOnly" in set_cookie and "SameSite=Strict" in set_cookie and "Path=/" in set_cookie
    return set_cookie.split(";")[0]


def login(name, password):
    status, data, sc = call("POST", "/api/auth/login", {"name": name, "password": password})
    assert status == 200, data
    return cookie_of(sc)


agent_id = None
made = []            # otros agentes de prueba, para borrarlos al final
try:
    for _ in range(100):
        try:
            if call("GET", "/api/auth/me")[0] == 200:
                break
        except OSError:
            time.sleep(0.2)

    # sin usuarios: abierto como siempre
    assert call("GET", "/api/auth/me")[1] == {"enabled": False, "user": None}
    assert call("GET", "/api/agents")[0] == 200
    agent = call("POST", "/api/agents", {"name": "tmp test_auth widget"})[1]
    agent_id = agent["id"]
    agent["widget"] = {"enabled": True, "origins": []}
    assert call("PUT", "/api/agents/" + agent_id, agent)[0] == 200

    # primer usuario: siempre dueño, y queda con sesión
    status, owner, sc = call("POST", "/api/users", {"name": "ana", "password": "abc"})
    assert status == 400 and "5" in owner["error"]
    status, owner, sc = call("POST", "/api/users", {"name": "ana", "password": "secreta123", "role": "agent"})
    assert status == 200 and owner["role"] == "owner", owner
    ana = cookie_of(sc)
    assert stat.S_IMODE(os.stat(USERS).st_mode) == 0o600
    assert "secreta123" not in open(USERS).read()
    assert call("GET", "/api/auth/me", cookie=ana)[1] == {"enabled": True, "user": {"name": "ana", "role": "owner", "bots": None}}
    assert call("GET", "/api/auth/me")[1] == {"enabled": True, "user": None}

    # sin sesión: 401; crear más usuarios ya pide dueño
    assert call("GET", "/api/agents")[0] == 401
    assert call("POST", "/api/users", {"name": "intruso", "password": "secreta123"})[0] == 401
    assert call("GET", "/api/agents", cookie="parla_session=inventada")[0] == 401
    assert call("POST", "/api/auth/login", {"name": "ana", "password": "mal"})[0] == 401
    assert call("POST", "/api/auth/login", {"name": "nadie", "password": "mal"})[0] == 401
    ana2 = login("ANA", "secreta123")          # el nombre no distingue mayúsculas
    assert call("GET", "/api/agents", cookie=ana2)[0] == 200

    for name, role in (("eli", "editor"), ("ale", "analyst"), ("ato", "agent")):
        status, data, _ = call("POST", "/api/users", {"name": name, "password": "secreta123", "role": role}, cookie=ana)
        assert status == 200 and data["role"] == role, data
    assert call("POST", "/api/users", {"name": "Eli", "password": "secreta123", "role": "editor"}, cookie=ana)[0] == 400
    assert call("POST", "/api/users", {"name": "x", "password": "secreta123", "role": "rey"}, cookie=ana)[0] == 400
    users = call("GET", "/api/users", cookie=ana)[1]["users"]
    assert [u["name"] for u in users] == ["ana", "eli", "ale", "ato"] and all("hash" not in u for u in users)
    eli, ale, ato = login("eli", "secreta123"), login("ale", "secreta123"), login("ato", "secreta123")

    # roles
    A = "/api/agents/" + agent_id
    assert call("GET", "/api/users", cookie=eli)[0] == 403
    assert call("PUT", A, agent, cookie=eli)[0] == 200
    assert call("POST", A + "/train", {}, cookie=eli)[0] != 403
    assert call("GET", "/api/agents", cookie=ale)[0] == 200
    assert call("GET", A + "/secrets", cookie=ale)[0] == 200
    for method, path in (("POST", A + "/train"), ("POST", A + "/chat"), ("PUT", A), ("DELETE", A), ("POST", "/api/agents"),
                         ("PUT", A + "/secrets"), ("POST", A + "/sessions/s1/reply")):
        assert call(method, path, {}, cookie=ale)[0] == 403, (method, path)
    assert call("GET", "/api/users", cookie=ale)[0] == 403
    for method, path in (("GET", "/api/agents"), ("GET", A), ("GET", A + "/inbox"), ("POST", A + "/sessions/s1/reply"),
                         ("POST", A + "/sessions/s1/take"), ("POST", A + "/sessions/s1/release"),
                         ("GET", "/api/v1/bots/%s/sessions/s1" % agent_id), ("GET", "/api/v1/bots/%s/sessions/s1/messages" % agent_id)):
        assert call(method, path, {}, cookie=ato)[0] not in (401, 403), (method, path)
    for method, path in (("GET", A + "/versions"), ("GET", A + "/secrets"), ("PUT", A), ("POST", A + "/chat"),
                         ("GET", "/api/v1/bots"), ("GET", "/api/ai/progress")):
        status, data, _ = call(method, path, {}, cookie=ato)
        assert status == 403 and "Bandeja" in data["error"], (method, path, status)

    # qué agentes ve: «dev» es un editor que solo mantiene el agente del widget
    other = call("POST", "/api/agents", {"name": "tmp test_auth otro"}, cookie=ana)[1]
    made.append(other["id"])
    O = "/api/agents/" + other["id"]
    other["widget"] = {"enabled": True, "origins": []}
    assert call("PUT", O, other, cookie=ana)[0] == 200
    assert call("POST", "/api/users", {"name": "x1", "password": "secreta123", "role": "editor", "bots": ["ffffffff"]}, cookie=ana)[0] == 400
    assert call("POST", "/api/users", {"name": "x2", "password": "secreta123", "role": "editor", "bots": "todos"}, cookie=ana)[0] == 400
    status, data, _ = call("POST", "/api/users", {"name": "dev", "password": "secreta123", "role": "editor", "bots": [agent_id]}, cookie=ana)
    assert status == 200 and data["bots"] == [agent_id], data
    scopes = {u["name"]: u["bots"] for u in call("GET", "/api/users", cookie=ana)[1]["users"]}
    assert scopes == {"ana": None, "eli": None, "ale": None, "ato": None, "dev": [agent_id]}, scopes
    dev = login("dev", "secreta123")
    assert call("GET", "/api/auth/me", cookie=dev)[1]["user"]["bots"] == [agent_id]
    assert [a["id"] for a in call("GET", "/api/agents", cookie=dev)[1]] == [agent_id]
    assert {agent_id, other["id"]} <= {a["id"] for a in call("GET", "/api/agents", cookie=ana)[1]}      # el dueño ve todos
    assert call("GET", A, cookie=dev)[0] == 200 and call("PUT", A, agent, cookie=dev)[0] == 200
    V = "/api/v1/bots/"
    for method, path in (("GET", O), ("PUT", O), ("DELETE", O), ("GET", O + "/versions"), ("GET", O + "/secrets"), ("POST", O + "/chat"),
                         ("GET", V + other["id"]), ("GET", V + urllib.parse.quote(other["name"])), ("GET", V + other["id"] + "/sessions"),
                         ("GET", V + other["id"] + "/report"), ("POST", "/api/ai/status")):
        status, data, _ = call(method, path, {"agent": other["id"]}, cookie=dev)
        assert status == 404 and data["error"] == "no existe ese agente", (method, path, status, data)
    assert os.path.exists(os.path.join(DATA, "agents", other["id"] + ".json"))          # el DELETE de arriba no lo borró
    assert [b["id"] for b in call("GET", V[:-1], cookie=dev)[1]["bots"]] == [agent_id]
    assert other["id"] in [b["id"] for b in call("GET", V[:-1], cookie=ana)[1]["bots"]]
    assert call("GET", V + agent_id, cookie=dev)[0] == 200
    # el chat público del widget sigue abierto, con o sin sesión
    assert call("POST", V + other["id"] + "/events", {"type": "start", "environment": "draft"})[0] == 200
    assert call("POST", V + other["id"] + "/events", {"type": "start", "environment": "draft"}, cookie=dev)[0] == 200
    # archivos del paso «Enviar un archivo»: suben dueño/editor, se sirven sin sesión solo con su id aleatorio
    import base64
    pdf = {"name": "Lista de precios (2026).pdf", "data": "data:application/pdf;base64," + base64.b64encode(b"%PDF-1.4 x").decode()}
    assert call("POST", O + "/files", pdf, cookie=dev)[0] == 404                       # no es un bot suyo
    assert call("POST", O + "/files", pdf, cookie=ale)[0] == 403 and call("POST", O + "/files", pdf, cookie=ato)[0] == 403
    assert call("POST", O + "/files", pdf)[0] == 401
    assert call("POST", O + "/files", dict(pdf, name="x.html"), cookie=ana)[0] == 400
    up = call("POST", O + "/files", pdf, cookie=ana)[1]
    fid = up["id"]
    assert up["files"] == [{k: up[k] for k in ("id", "name", "mime", "size", "url")}] and call("GET", O + "/files", cookie=ale)[1]["files"] == up["files"]

    def raw(path):
        conn = http.client.HTTPConnection("127.0.0.1", PORT, timeout=30)
        conn.request("GET", path)
        r = conn.getresponse()
        out = r.status, r.read(), dict(r.getheaders())
        conn.close()
        return out
    status, body, headers = raw(up["url"])
    assert status == 200 and body == b"%PDF-1.4 x" and headers["Content-Type"] == "application/pdf", (status, headers)
    assert headers["X-Content-Type-Options"] == "nosniff" and "filename*=UTF-8''Lista%20de%20precios%20%282026%29.pdf" in headers["Content-Disposition"]
    assert headers["Content-Disposition"].startswith("inline;")
    for bad in ("/files/%s/%s" % (agent_id, fid), "/files/%s/%s.json" % (other["id"], fid), "/files/%s/..%%2F..%%2F%s" % (other["id"], fid[:16]),
                "/files/%s/../%s.json" % (other["id"], other["id"]), "/files/%s/%s" % (other["id"], "A" * 22)):
        assert raw(bad)[0] == 404, bad                                             # otro agente, metadatos, saltos de carpeta, ids inventados
    assert call("DELETE", O + "/files/" + fid, cookie=ana)[1] == {"files": []} and raw(up["url"])[0] == 404
    # lo que crea (o importa) dev queda en su lista
    mine = call("POST", "/api/agents", {"name": "tmp test_auth de dev"}, cookie=dev)[1]
    made.append(mine["id"])
    assert call("POST", "/api/agents/%s/files" % mine["id"], pdf, cookie=dev)[0] == 200
    assert os.path.isdir(os.path.join(DATA, "agents", mine["id"] + ".files"))
    imp = call("POST", "/api/agents", {"import": dict(agent, name="tmp test_auth importado", intents=[{"name": "hola", "examples": ["hola"]}])}, cookie=dev)[1]
    made.append(imp["id"])
    assert [a["id"] for a in call("GET", "/api/agents", cookie=dev)[1]] == sorted([agent_id, mine["id"], imp["id"]])
    assert call("GET", "/api/users", cookie=ana)[1]["users"][-1]["bots"] == [agent_id, mine["id"], imp["id"]]
    # la clave de API de dev hereda lo que ve (así un MCP conectado con ella solo ve esos)
    dkey = call("POST", "/api/users/dev/keys", {"label": "MCP"}, cookie=ana)[1]["key"]
    assert agent_id in [a["id"] for a in call("GET", "/api/agents", token=dkey)[1]]
    assert other["id"] not in [a["id"] for a in call("GET", "/api/agents", token=dkey)[1]]
    assert other["id"] not in [b["id"] for b in call("GET", V[:-1], token=dkey)[1]["bots"]]
    assert call("GET", V + other["id"], token=dkey)[0] == 404 and call("GET", O, token=dkey)[0] == 404
    # borrar un agente de la lista no rompe al usuario; null vuelve a «todos»
    assert call("DELETE", "/api/agents/" + mine["id"], cookie=dev)[0] == 200
    assert not os.path.exists(os.path.join(DATA, "agents", mine["id"] + ".files"))     # borrar el agente borra sus archivos
    assert call("GET", "/api/agents", cookie=dev)[0] == 200 and call("GET", "/api/users", cookie=ana)[0] == 200
    assert call("PUT", "/api/users/dev", {"bots": [agent_id, "ffffffff"]}, cookie=ana)[0] == 400
    assert call("PUT", "/api/users/dev", {"bots": None}, cookie=ana)[1]["bots"] is None
    assert call("GET", O, cookie=dev)[0] == 200
    assert call("PUT", "/api/users/dev", {"bots": []}, cookie=ana)[1]["bots"] == []
    assert call("GET", "/api/agents", cookie=dev)[1] == [] and call("GET", A, cookie=dev)[0] == 404
    assert call("PUT", "/api/users/dev", {"role": "owner"}, cookie=ana)[1]["bots"] is None       # el dueño ve todos
    assert call("GET", A, cookie=dev)[0] == 200
    assert call("DELETE", "/api/users/dev", cookie=ana)[0] == 200

    # clave de API (Bearer), se ve una sola vez y se puede revocar
    status, key, _ = call("POST", "/api/users/ale/keys", {"label": "MCP"}, cookie=ana)
    assert status == 200 and key["key"].startswith("parla_")
    assert key["key"] not in open(USERS).read()
    assert call("GET", "/api/agents", token=key["key"])[0] == 200
    assert call("POST", A + "/train", {}, token=key["key"])[0] == 403          # con los permisos de ale
    assert call("GET", "/api/agents", token="parla_inventada")[0] == 401
    assert call("POST", "/api/users/ale/keys", {}, cookie=eli)[0] == 403
    assert call("GET", "/api/users", cookie=ana)[1]["users"][2]["keys"][0]["label"] == "MCP"
    assert call("DELETE", "/api/users/ale/keys/" + key["id"], cookie=ana)[0] == 200
    assert call("GET", "/api/agents", token=key["key"])[0] == 401

    # widget prendido: el chat público queda abierto; apagado, no
    event = {"type": "start", "environment": "draft"}
    assert call("POST", "/api/v1/bots/%s/events" % agent_id, event)[0] not in (401, 403)
    assert call("GET", "/api/v1/bots/%s" % agent_id)[0] == 401
    # leer los mensajes nuevos: abierto solo para charlas del widget (canal «web»); el sessionId hace de llave
    B = "/api/v1/bots/%s/sessions/" % agent_id
    for sid, channel in (("webtest-a1b2c3d4", "web"), ("apitest-a1b2c3d4", "api")):
        status, data, _ = call("POST", "/api/v1/bots/%s/events" % agent_id, dict(event, sessionId=sid, channel=channel))
        assert status == 200, data
    status, data, _ = call("GET", B + "webtest-a1b2c3d4/messages?after=0")
    assert status not in (401, 403), (status, data)   # 200 cuando ENGINE implemente /messages
    assert call("GET", B + "webtest-a1b2c3d4")[0] == 401                  # la conversación entera, no
    assert call("GET", B + "apitest-a1b2c3d4/messages")[0] == 401
    assert call("GET", B + "noexiste-123/messages")[0] == 401
    assert call("GET", B + "..%2Fx/messages")[0] == 401
    agent["widget"]["enabled"] = False
    assert call("PUT", A, agent, cookie=ana)[0] == 200
    assert call("POST", "/api/v1/bots/%s/events" % agent_id, event)[0] == 401
    assert call("GET", B + "webtest-a1b2c3d4/messages")[0] == 401
    assert call("POST", "/api/v1/bots/%s/events" % agent_id, event, cookie=eli)[0] not in (401, 403)

    # siempre queda un dueño
    assert call("PUT", "/api/users/ana", {"role": "editor"}, cookie=ana)[0] == 400
    assert call("DELETE", "/api/users/ana", cookie=ana)[0] == 400
    assert call("PUT", "/api/users/eli", {"role": "owner"}, cookie=ana)[1]["role"] == "owner"
    assert call("PUT", "/api/users/ana", {"role": "editor"}, cookie=eli)[1]["role"] == "editor"
    assert call("GET", "/api/users", cookie=ana)[0] == 403                    # el rol se aplica en el acto
    assert call("PUT", "/api/users/ana", {"role": "owner"}, cookie=eli)[0] == 200

    # cambiar contraseña corta las sesiones; borrar un usuario también
    assert call("PUT", "/api/users/ato", {"password": "otra-clave-1"}, cookie=ana)[0] == 200
    assert call("GET", "/api/agents", cookie=ato)[0] == 401
    ato = login("ato", "otra-clave-1")
    assert call("DELETE", "/api/users/ato", cookie=ana)[0] == 200
    assert call("GET", "/api/agents", cookie=ato)[0] == 401
    assert call("DELETE", "/api/users/nadie", cookie=ana)[0] == 404

    # muchos intentos fallidos: un minuto de espera (aunque después acierte)
    for _ in range(5):
        assert call("POST", "/api/auth/login", {"name": "ale", "password": "mal"})[0] == 401
    status, data, _ = call("POST", "/api/auth/login", {"name": "ale", "password": "secreta123"})
    assert status == 429 and "minuto" in data["error"]

    # cerrar sesión
    status, _, sc = call("POST", "/api/auth/logout", cookie=ana2)
    assert status == 200 and "Max-Age=0" in sc
    assert call("GET", "/api/agents", cookie=ana2)[0] == 401
    assert call("GET", "/api/agents", cookie=ana)[0] == 200                   # la otra sesión sigue
finally:
    server.terminate()
    server.wait()
    shutil.rmtree(TMP, ignore_errors=True)

assert (open(REAL_USERS, "rb").read() if os.path.exists(REAL_USERS) else None) == real_before     # el users.json de verdad, intacto
print("ok")
