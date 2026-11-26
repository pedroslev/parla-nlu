"""parla.db: conversaciones, migración desde JSON, logins que sobreviven un reinicio, retención, auditoría y datos
personales tapados en lo guardado.   .venv/bin/python tests/test_storage.py"""
import http.client
import json
import os
import time

import support

TMP = support.temp_data()
from parla import db, pii, server as app  # noqa: E402

# ---------- pii.py ----------
r = pii.redact
assert r("escribime a ana.p+x@mail.com.ar") == "escribime a [email]"
assert r("tarjeta 4111 1111 1111 1111") == "tarjeta [tarjeta]" and r("4111-1111-1111-1111") == "[tarjeta]"
assert r("4111111111111112", ("card",)) == "4111111111111112"         # no pasa Luhn: no es tarjeta
assert pii.luhn("79927398713") and not pii.luhn("79927398710")
assert r("cbu 0110599520000001234567") == "cbu [cuenta]" and r("ES91 2100 0418 4502 0005 1332") == "[cuenta]"
assert r("ES00 2100 0418 4502 0005 1332") != "[cuenta]"                # IBAN con dígito verificador mal
assert r("cuit 20-30123456-7") == "cuit [documento]" and r("dni 30.123.456") == "dni [documento]" and r("30123456") == "[documento]"
assert r("llamame al +54 9 11 1234-5678 o al 11 4567-8901") == "llamame al [teléfono] o al [teléfono]"
for same in ("quiero 2 pizzas", "son $1500000", "el 2024-01-15 a las 10:30", "1.500,50 pesos", "versión 3.2"):
    assert r(same) == same, same
assert r("ana@x.com 30123456", ("email",)) == "[email] 30123456"
assert pii.categories(True) == pii.CATEGORIES and pii.categories(["card", "nada"]) == ("card",) and pii.categories(False) == ()
assert pii.scrub({"dni": 30123456, "ok": True, "n": 2, "l": ["a@b.co"]}) == {"dni": "[documento]", "ok": True, "n": 2, "l": ["[email]"]}

# ---------- en este proceso: retención ----------
os.makedirs(app.AGENTS, exist_ok=True)
keep = app.create(dict(app.BLANK, name="Para siempre"))
short = app.create(dict(app.BLANK, name="Corto", retention_days=2))
forever = app.create(dict(app.BLANK, name="Cero", retention_days=0))
old = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(time.time() - 5 * 86400))
for agent in (keep, short, forever):
    for sid, when in (("viejo", old), ("nuevo", app.now())):
        app.save_session(agent["id"], {"sessionId": sid, "channel": "api", "started": when, "updated": when, "ended": True, "state": {}, "history": []})
app.cleanup()
left = lambda agent: sorted(r["sessionId"] for r in app.sessions_of(agent["id"], {}))
assert left(keep) == ["nuevo", "viejo"] and left(short) == ["nuevo"] and left(forever) == ["nuevo", "viejo"]
os.environ["PARLA_RETENTION_DAYS"] = "3"                                 # el valor general: vale para los que no dicen nada
app.cleanup()
assert left(keep) == ["nuevo"] and left(forever) == ["nuevo", "viejo"]
del os.environ["PARLA_RETENTION_DAYS"]
db.q("INSERT INTO audit (at, action) VALUES (?, 'viejo')", (time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(time.time() - 400 * 86400)),))
db.q("INSERT INTO logins VALUES ('vencido', 'x', ?)", (time.time() - 1,))
app.cleanup()
assert db.q("SELECT count(*) FROM audit WHERE action = 'viejo'") == [(0,)] and db.q("SELECT count(*) FROM logins") == [(0,)]
# con pii_redaction, una charla abierta y quieta un día se cierra: su estado (con los datos reales) se borra
private = app.create(dict(app.BLANK, name="Privado", pii_redaction=True))
yesterday = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(time.time() - 2 * 86400))
app.save_session(private["id"], {"sessionId": "q", "channel": "api", "started": yesterday, "updated": yesterday, "ended": False,
                                 "state": {"slots": {"email": "ana@mail.com"}}, "history": [{"from": "user", "text": "soy ana@mail.com"}]})
assert app.load_session(private["id"], "q")["history"][0]["text"] == "soy [email]"
app.cleanup()
closed = app.load_session(private["id"], "q")
assert closed["ended"] is True and closed["state"] == {} and closed["updated"] == yesterday, closed
# guardar y releer: mismo registro; la Bandeja filtra por handoff en la base
record = {"sessionId": "b1", "channel": "web", "started": app.now(), "updated": app.now(), "ended": False, "state": {},
          "history": [{"from": "user", "text": "hola", "at": app.now()}], "handoff": {"active": True}}
app.save_session(keep["id"], record)
assert app.load_session(keep["id"], "b1") == record and [s["sessionId"] for s in app.inbox(keep["id"])["sessions"]] == ["b1"]
assert app.load_session(keep["id"], "../b1") is None and app.load_session(keep["id"], "nada") is None


# ---------- servidor: migración desde los JSON de antes ----------
def call(port, method, path, body=None, cookie=None):
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=30)
    conn.request(method, path, json.dumps(body) if body is not None else None, dict({"Content-Type": "application/json"}, **({"Cookie": cookie} if cookie else {})))
    res = conn.getresponse()
    data = json.loads(res.read() or b"null")
    conn.close()
    return res.status, data, res.getheader("Set-Cookie")


OLD = os.path.join(TMP, "viejo")
os.makedirs(os.path.join(OLD, "agents", "abcd0001.sessions"))
with open(os.path.join(OLD, "agents", "abcd0001.json"), "w") as f:
    json.dump(dict(app.BLANK, id="abcd0001", name="Viejo"), f)
legacy = {"sessionId": "s-legacy", "channel": "api", "started": app.now(), "updated": app.now(), "ended": True, "state": {},
          "history": [{"from": "user", "text": "hola de antes", "at": app.now()}]}
with open(os.path.join(OLD, "agents", "abcd0001.sessions", "s-legacy.json"), "w") as f:
    json.dump(legacy, f)
with open(os.path.join(OLD, "agents", "abcd0001.sessions", "roto.json"), "w") as f:
    f.write("{no es json")
for _ in range(2):                                                       # la segunda vez no hay nada que migrar
    proc, port = support.start_server(OLD)
    try:
        status, body, _ = call(port, "GET", "/api/v1/bots/abcd0001/sessions/s-legacy")
        assert status == 200 and body["history"][0]["text"] == "hola de antes", body
    finally:
        proc.terminate(), proc.wait()
assert not os.path.exists(os.path.join(OLD, "agents", "abcd0001.sessions"))
assert sorted(os.listdir(os.path.join(OLD, "agents", "abcd0001.sessions.migrated"))) == ["roto.json", "s-legacy.json"]   # nada se borra
assert os.environ.get("PARLA_DATABASE_URL") or os.stat(os.path.join(OLD, "parla.db")).st_mode & 0o777 == 0o600

# ---------- servidor: todo sobrevive un reinicio; auditoría; PII guardado vs en vivo ----------
DATA = os.path.join(TMP, "srv")
proc, port = support.start_server(DATA)
try:
    status, owner, sc = call(port, "POST", "/api/users", {"name": "ana", "password": "secreta123"})
    ana = sc.split(";")[0]
    assert call(port, "POST", "/api/auth/login", {"name": "ana", "password": "mal"})[0] == 401
    bot = call(port, "POST", "/api/agents", {"name": "Privado"}, ana)[1]
    A = "/api/agents/" + bot["id"]
    bot.update(pii_redaction=True, retention_days=30, slots=[{"name": "email"}, {"name": "tarjeta"}],
               flows=[{"name": "inicio", "trigger": "__start__", "steps": [{"type": "message", "text": "Te escribo a {{ email }} por la {{ tarjeta }}"}]}])
    assert call(port, "PUT", A, bot, ana)[0] == 200
    assert call(port, "PUT", A + "/secrets", {"name": "TOKEN", "value": "valor-super-secreto"}, ana)[0] == 200
    status, live, _ = call(port, "POST", "/api/v1/bots/%s/events" % bot["id"],
                           {"type": "start", "sessionId": "p1", "environment": "draft", "data": {"email": "ana@mail.com", "tarjeta": "4111 1111 1111 1111"}}, ana)
    assert live["messages"] == ["Te escribo a ana@mail.com por la 4111 1111 1111 1111"], live            # en vivo: el dato real
    assert live["slots"]["email"] == "ana@mail.com"
    call(port, "POST", "/api/users", {"name": "eli", "password": "secreta123", "role": "editor"}, ana)
    eli = call(port, "POST", "/api/auth/login", {"name": "eli", "password": "secreta123"})[2].split(";")[0]
    assert call(port, "GET", "/api/audit", cookie=eli)[0] == 403                                       # solo el dueño
finally:
    proc.terminate(), proc.wait()

proc, port = support.start_server(DATA)                                  # mismo DATA: reinicio
try:
    assert call(port, "GET", "/api/auth/me", cookie=ana)[1]["user"]["name"] == "ana"                  # la sesión sigue
    status, stored, _ = call(port, "GET", "/api/v1/bots/%s/sessions/p1" % bot["id"], cookie=ana)
    assert status == 200 and stored["history"][1]["text"] == "Te escribo a [email] por la [tarjeta]", stored["history"]
    assert stored["history"][0]["data"] == {"email": "[email]", "tarjeta": "[tarjeta]"}, stored["history"][0]
    assert stored["slots"]["email"] == "ana@mail.com"            # la charla sigue abierta: su memoria tiene el dato real
    entries = call(port, "GET", "/api/audit", cookie=ana)[1]["entries"]
    seen = {(e["action"], e["detail"].split(" ")[0]) for e in entries}
    assert {("login", "falló"), ("user.create", "eli"), ("secret.set", "TOKEN"), ("agent.create", ""), ("agent.save", "")} <= seen, seen
    assert next(e for e in entries if e["action"] == "secret.set")["user"] == "ana"
    assert [e["action"] for e in call(port, "GET", "/api/audit?user=eli&limit=5", cookie=ana)[1]["entries"]] == ["login"]
    assert call(port, "GET", "/api/audit?agent=%s&since=2999-01-01" % bot["id"], cookie=ana)[1]["entries"] == []
    assert call(port, "POST", "/api/auth/logout", {}, ana)[0] == 200
    assert call(port, "GET", "/api/auth/me", cookie=ana)[1]["user"] is None                           # cerrar sesión la borra
finally:
    proc.terminate(), proc.wait()
if os.environ.get("PARLA_DATABASE_URL"):        # Postgres: todas las tablas como texto
    from parla import db  # noqa: E402
    dump = "".join(str(db.q("SELECT * FROM %s" % t)) for t in db.TABLES).encode()
else:
    dump = b"".join(open(f, "rb").read() for f in (os.path.join(DATA, "parla.db"), os.path.join(DATA, "parla.db-wal")) if os.path.exists(f))
assert b"valor-super-secreto" not in dump and b"secreta123" not in dump and ana.split("=")[1].encode() not in dump   # ni secretos, ni claves, ni tokens
print("ok")
