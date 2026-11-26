"""Derivación a un contact center externo: modo external, webhooks firmados (cola, reintentos, dead-letter, orden),
API del contact center (accept / messages / release / close / lookup), transferencia telefónica con contexto y la
clave «integration». Todo contra servidores de mentira:  .venv/bin/python tests/test_handoff_external.py"""
import hashlib
import hmac
import json
import os
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import support
DATA = support.temp_data()

HOOKS, CALLS, FAIL = [], [], {}     # webhooks recibidos; llamadas a Meta/Telegram; ruta -> códigos a devolver


class Fake(BaseHTTPRequestHandler):
    def do_POST(self):
        raw = self.rfile.read(int(self.headers.get("Content-Length") or 0))
        if self.path.startswith("/hook"):
            HOOKS.append({"path": self.path, "raw": raw, "sig": self.headers.get("Parla-Signature"), "event": self.headers.get("Parla-Event")})
            codes = FAIL.get(self.path)
            code = codes.pop(0) if codes else 200
            out = b"{}"
        else:
            CALLS.append({"path": self.path, "body": json.loads(raw or b"{}")})
            code, out = 200, json.dumps({"messages": [{"id": "wamid.1"}]} if "/wa/" in self.path else {"ok": True, "result": {"message_id": 1}}).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(out)))
        self.end_headers()
        self.wfile.write(out)

    def log_message(self, *args):
        pass


fake = ThreadingHTTPServer(("127.0.0.1", 0), Fake)
threading.Thread(target=fake.serve_forever, daemon=True).start()
FAKE = "http://127.0.0.1:%d" % fake.server_address[1]
os.environ.update(PARLA_WHATSAPP_API=FAKE + "/wa", PARLA_TELEGRAM_API=FAKE + "/tg")

from parla import server as app, vault, outbound, handoff, phone, bus, db  # noqa: E402
import numpy as np  # noqa: E402

app._encode = lambda texts: [(lambda v: v / np.linalg.norm(v))(np.random.default_rng(
    int(hashlib.md5(t.encode()).hexdigest()[:8], 16)).normal(size=64)) for t in texts]
os.makedirs(app.AGENTS, exist_ok=True)
NOW = [1_800_000_000.0]
handoff.clock = outbound.clock = lambda: NOW[0]
ALL = list(handoff.EVENTS)

agent = app.create({**app.BLANK, "name": "Soporte", "threshold": 0.5,
    "intents": [{"name": "reclamo", "examples": ["tengo un reclamo", "quiero hacer un reclamo"]}],
    "slots": [{"name": "dni"}, {"name": "producto"}],
    "flows": [{"name": "Reclamo", "trigger": "reclamo", "steps": [{"type": "set", "slot": "producto", "mode": "text", "text": "router"},
                                                                  {"type": "handoff", "text": "Te paso con alguien", "reason": "reclamo"}]},
              {"name": "Seguir", "trigger": "", "steps": [{"type": "message", "text": "Listo {{ dni }}, sigo yo"}]}],
    "channels": {"public_url": "https://bots.example.com", "whatsapp": {"enabled": True, "phone_number_id": "111"}, "telegram": {"enabled": True},
                 "phone": {"enabled": True, "provider": "twilio", "handoff_to": "sip:cola@cc.example.com"}},
    "handoff": {"mode": "external", "timeout_minutes": 10, "on_timeout": "bot", "target": "cola-reclamos", "last_messages": 3,
                "phone": {"headers": ["session", "intent", "language", "summary", "context_url"], "slots": ["dni"], "uui": True}},
    "webhooks": [{"url": FAKE + "/hook/a", "events": ALL, "secret_name": "CC_SECRET"}]})
AID = agent["id"]
for name, value in {"CC_SECRET": "s3cr3t-webhook", "WHATSAPP_TOKEN": "EAAtoken", "TELEGRAM_TOKEN": "123456:ABC-tg"}.items():
    vault.put(AID, name, value)

srv = ThreadingHTTPServer(("127.0.0.1", 0), app.Handler)
threading.Thread(target=srv.serve_forever, daemon=True).start()
BASE = "http://127.0.0.1:%d" % srv.server_address[1]


def js(method, path, body=None, headers=None):
    req = urllib.request.Request(BASE + path, data=json.dumps(body).encode() if body is not None else None, method=method,
                                 headers={"Content-Type": "application/json", **(headers or {})})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}")


def say(sid, text, channel="api"):
    return js("POST", "/api/v1/bots/%s/events" % AID, {"sessionId": sid, "text": text, "channel": channel}, OWNER)[1]


def verify(secret, header, raw):
    """Lo que hace el que recibe (docs/contact-centers.md): t y v1, HMAC-SHA256 de «t.cuerpo», compare_digest.
    (El chequeo de que t sea reciente queda afuera: acá el reloj es de mentira.)"""
    parts = dict(p.split("=", 1) for p in header.split(","))
    expected = hmac.new(secret.encode(), parts["t"].encode() + b"." + raw, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, parts["v1"])


def drain():
    for _ in range(20):
        if not handoff.tick():
            break
    out = list(HOOKS)
    HOOKS.clear()
    return out


def events(hooks, sid=None):
    return [(json.loads(h["raw"])["type"]) for h in hooks if sid is None or json.loads(h["raw"]).get("sessionId") == sid]


# --- usuarios: dueña (cookie no hace falta: clave), editor, analista y una clave de integración
status, body = js("POST", "/api/users", {"name": "duena", "password": "secreta1"})
assert status == 200, body
import http.cookiejar  # noqa: E402   la primera clave sale con la cookie del login; después, claves para todos
jar = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
jar.open(urllib.request.Request(BASE + "/api/auth/login", data=json.dumps({"name": "duena", "password": "secreta1"}).encode(),
                                headers={"Content-Type": "application/json"}, method="POST")).read()


def owner_call(method, path, body=None):
    req = urllib.request.Request(BASE + path, data=json.dumps(body).encode() if body is not None else None, method=method,
                                 headers={"Content-Type": "application/json"})
    with jar.open(req) as r:
        return json.loads(r.read())


OWNER = {"Authorization": "Bearer " + owner_call("POST", "/api/users/duena/keys", {"label": "tests"})["key"]}
for name, role in (("edi", "editor"), ("ana", "analyst")):
    assert js("POST", "/api/users", {"name": name, "password": "secreta1", "role": role}, OWNER)[0] == 200
EDITOR = {"Authorization": "Bearer " + js("POST", "/api/users/edi/keys", {"label": "cc"}, OWNER)[1]["key"]}
ANALYST = {"Authorization": "Bearer " + js("POST", "/api/users/ana/keys", {"label": "bi"}, OWNER)[1]["key"]}
s, made = js("POST", "/api/users/edi/keys", {"label": "genesys", "scope": "integration"}, OWNER)
assert s == 200 and made["scope"] == "integration", made
INTEG = {"Authorization": "Bearer " + made["key"]}
assert js("POST", "/api/users/edi/keys", {"label": "x", "scope": "root"}, OWNER)[0] == 400
V1 = "/api/v1/bots/%s" % AID

# --- modo external: pasa a una persona, el bot se calla, el webhook lleva el contexto firmado
r = say("s1", "hola, mi dni es 30123456")
r = say("s1", "tengo un reclamo")
assert r["handoff"] is True and r["messages"] == ["Te paso con alguien"], r
r = say("s1", "¿hay alguien?")
assert r["messages"] == [] and r["handoff"] is True, r          # callado
rec = app.load_session(AID, "s1")
assert rec["handoff"]["mode"] == "external" and rec["handoff"]["target"] == "cola-reclamos"
assert "reclamo" in rec["handoff"]["summary"] and "producto=router" in rec["handoff"]["summary"], rec["handoff"]   # resumen fijo (sin IA)

got = drain()
kinds = events(got, "s1")
assert kinds[0] == "conversation.started" and "handoff.requested" in kinds, kinds
assert kinds.index("handoff.requested") > kinds.index("message.bot"), kinds
for h in got:
    assert verify("s3cr3t-webhook", h["sig"], h["raw"]), h["sig"]
    assert not verify("otra-clave", h["sig"], h["raw"])
req = next(json.loads(h["raw"]) for h in got if h["event"] == "handoff.requested")
for key in ("id", "type", "created", "agent", "sessionId", "channel", "customer", "language", "intent", "flow", "slots", "handoff", "messages", "links"):
    assert key in req, key
assert req["intent"] == "reclamo" and req["slots"]["producto"] == "router" and req["handoff"]["reason"] == "reclamo", req
assert len(req["messages"]) == 3 and req["links"]["lookup"] == "https://bots.example.com/api/v1/bots/%s/lookup?sid=s1" % AID, req
assert req["customer"] == {"channel": "api", "address": "s1"}, req["customer"]
assert len({json.loads(h["raw"])["id"] for h in got}) == len(got)      # cada evento con su id

# --- la Bandeja la muestra pero no la deja tomar
s, inbox = js("GET", "/api/agents/%s/inbox" % AID, None, OWNER)
assert any(x["sessionId"] == "s1" and x["handoff"]["mode"] == "external" for x in inbox["sessions"]), inbox
assert js("POST", "/api/agents/%s/sessions/s1/take" % AID, {}, OWNER)[0] == 409

# --- reintentos con espera creciente, orden por conversación y dead-letter
FAIL["/hook/a"] = [500]
say("s1", "otra vez")             # message.user (el bot no contesta)
say("s2", "hola")                 # otra conversación: no espera a s1
got = drain()
assert events(got, "s1") == ["message.user"] and events(got, "s2")[0] == "conversation.started", events(got)   # s1 falló (500); s2 no espera
assert sum(1 for h in got if json.loads(h["raw"])["sessionId"] == "s1") == 1                               # nada de s1 se adelanta
row = db.q("SELECT status, attempts, next_at, code FROM webhook_deliveries WHERE session_id = 's1' AND status = 'queued' ORDER BY id LIMIT 1")[0]
assert row[0] == "queued" and row[1] == 1 and row[2] == NOW[0] + 30 and row[3] == 500, row
assert not drain()
NOW[0] += 31
assert events(drain(), "s1") == ["message.user"]

FAIL["/hook/a"] = [503] * 50
say("s3", "hola")
waits = []
for attempt in range(handoff.MAX_ATTEMPTS):
    handoff.tick()
    st, nxt = db.q("SELECT status, next_at FROM webhook_deliveries WHERE session_id = 's3' ORDER BY id LIMIT 1")[0]
    if st == "dead":
        break
    waits.append(nxt - NOW[0])
    NOW[0] = nxt
assert st == "dead" and attempt == handoff.MAX_ATTEMPTS - 1, (st, attempt)
assert waits[:4] == [30, 60, 120, 240] and max(waits) == handoff.MAX_WAIT and 20 * 3600 < sum(waits) < 28 * 3600, waits
FAIL["/hook/a"] = []
HOOKS.clear()
dead = db.q("SELECT id FROM webhook_deliveries WHERE session_id = 's3' AND status = 'dead' ORDER BY id LIMIT 1")[0][0]
s, log = js("GET", "/api/agents/%s/webhooks/deliveries" % AID, None, ANALYST)
assert s == 200 and any(d["id"] == dead and d["status"] == "dead" and d["code"] == 503 for d in log["deliveries"]), log
assert js("POST", "/api/agents/%s/webhooks/deliveries/%d/retry" % (AID, dead), {}, ANALYST)[0] == 403
assert js("POST", "/api/agents/%s/webhooks/deliveries/%d/retry" % (AID, dead), {}, EDITOR)[0] == 200
assert "conversation.started" in events(drain(), "s3")
s, sent = js("POST", "/api/agents/%s/webhooks/test" % AID, {"url": FAKE + "/hook/a"}, EDITOR)
assert s == 200 and sent["status"] == "delivered" and sent["code"] == 200 and HOOKS[-1]["event"] == "test", sent
HOOKS.clear()
assert js("POST", "/api/agents/%s/webhooks/test" % AID, {"url": "https://otro.example.com"}, EDITOR)[0] == 400

# --- API del contact center: roles y scope
assert js("POST", V1 + "/sessions/s1/handoff", {"action": "accept"}, ANALYST)[0] == 403
assert js("GET", "/api/agents/%s" % AID, None, INTEG)[0] == 403          # la clave de integración no ve el bot
assert js("PUT", "/api/agents/%s" % AID, {"name": "x"}, INTEG)[0] == 403
assert js("POST", V1 + "/events", {"text": "hola"}, INTEG)[0] == 403
assert js("POST", V1 + "/sessions/s1/handoff", {"action": "nada"}, INTEG)[0] == 400
s, out = js("POST", V1 + "/sessions/s1/handoff", {"action": "accept", "agent_name": "Ana (Genesys)"}, INTEG)
assert s == 200 and out["handoff"]["by"] == "Ana (Genesys)", out
s, out = js("POST", V1 + "/sessions/s1/messages", {"text": "Hola, soy Ana", "from_name": "Ana"}, INTEG)
assert s == 200 and out["delivered"] is False, out              # canal api: lo lee quien consulta …/messages
hist = js("GET", V1 + "/sessions/s1", None, INTEG)[1]["history"]
assert hist[-1]["from"] == "human" and hist[-1]["by"] == "Ana" and hist[-1]["text"] == "Hola, soy Ana", hist[-1]
assert js("POST", V1 + "/sessions/s1/handoff", {"action": "release", "flow": "NoExiste"}, INTEG)[0] == 400
assert js("POST", V1 + "/sessions/s1/handoff", {"action": "release", "data": [1]}, INTEG)[0] == 400
drain()
s, out = js("POST", V1 + "/sessions/s1/handoff", {"action": "release", "data": {"dni": "40999888"}, "flow": "Seguir"}, INTEG)
assert s == 200 and out["handoff"]["active"] is False and out["slots"]["dni"] == "40999888", out
hist = js("GET", V1 + "/sessions/s1", None, INTEG)[1]["history"]
assert hist[-1] == {"from": "bot", "text": "Listo 40999888, sigo yo", "at": hist[-1]["at"]}, hist[-3:]
assert events(drain(), "s1") == ["handoff.released"]
r = say("s1", "gracias")
assert r["handoff"] is False                                       # el bot volvió
say("s1", "tengo un reclamo")
s, out = js("POST", V1 + "/sessions/s1/handoff", {"action": "close", "resolution": "resuelto"}, EDITOR)
assert s == 200 and out["ended"] is True, out
ended = [json.loads(h["raw"]) for h in drain() if h["event"] == "conversation.ended"]
assert ended and ended[0]["resolution"] == "resuelto", ended
assert js("POST", V1 + "/sessions/s1/messages", {"text": "hola"}, INTEG)[0] == 409   # ya terminó
assert js("POST", V1 + "/sessions/nada/handoff", {"action": "accept"}, INTEG)[0] == 404

# --- mensajes del operador por el canal de la conversación: WhatsApp (ventana de 24 h), Telegram y el widget web
say("wa-5491112345678", "tengo un reclamo", channel="whatsapp")
s, out = js("POST", V1 + "/sessions/wa-5491112345678/messages", {"text": "Hola desde el CC"}, INTEG)
assert s == 200 and out["delivered"] is True, out
assert CALLS[-1]["path"] == "/wa/111/messages" and CALLS[-1]["body"]["to"] == "5491112345678" and CALLS[-1]["body"]["text"]["body"] == "Hola desde el CC", CALLS[-1]
NOW[0] += 25 * 3600
s, out = js("POST", V1 + "/sessions/wa-5491112345678/messages", {"text": "¿seguís?"}, INTEG)
assert s == 409 and "24" in out["error"], out
say("tg-777", "tengo un reclamo", channel="telegram")
s, out = js("POST", V1 + "/sessions/tg-777/messages", {"text": "Hola tg"}, INTEG)
assert s == 200 and CALLS[-1]["path"].endswith("/sendMessage") and CALLS[-1]["body"] == {"chat_id": "777", "text": "Hola tg"}, CALLS[-1]
published = []
real_publish, bus.publish = bus.publish, lambda topic, event: published.append((topic, event))
say("web1", "tengo un reclamo", channel="web")
published.clear()
s, out = js("POST", V1 + "/sessions/web1/messages", {"text": "Hola web", "from_name": "Leo"}, INTEG)
bus.publish = real_publish
assert s == 200 and out["delivered"] is True, out
pushed = [e for t, e in published if t == "session:%s:web1" % AID]
assert pushed and pushed[-1]["record"]["history"][-1] == {"from": "human", "text": "Hola web", "at": pushed[-1]["record"]["history"][-1]["at"], "by": "Leo"}, pushed

# --- lookup: por teléfono (WhatsApp o llamada), chat de Telegram o sessionId
s, found = js("GET", V1 + "/lookup?phone=" + urllib.parse.quote("+54 911 1234-5678"), None, INTEG)
assert s == 200 and found["sessionId"] == "wa-5491112345678" and found["handoff"]["active"] and found["customer"]["address"] == "5491112345678", found
s, found = js("GET", V1 + "/lookup?chat=777", None, INTEG)
assert s == 200 and found["sessionId"] == "tg-777", found
assert js("GET", V1 + "/lookup?sid=web1", None, INTEG)[1]["sessionId"] == "web1"
assert js("GET", V1 + "/lookup?phone=1199", None, INTEG)[0] == 404
call = app.open_session(AID, "call-CA1", "phone")
call["caller"] = "5491187654321"
app.save_session(AID, call)
assert js("GET", V1 + "/lookup?phone=%2B5491187654321", None, INTEG)[1]["sessionId"] == "call-CA1"

# --- tiempo máximo: nadie la aceptó -> vuelve al bot (o se cierra)
say("s4", "tengo un reclamo")
drain()
assert handoff.expire(time.time() + 5 * 60) == 0
assert handoff.expire(time.time() + 11 * 60) >= 1
assert app.load_session(AID, "s4")["handoff"]["active"] is False
assert "handoff.released" in events(drain(), "s4")

# --- PII: con pii_redaction el webhook va tapado (dirección, slots y mensajes)
a = app.load(AID)
a["pii_redaction"] = True
app.store(a)
say("wa-5491199990000", "mi mail es ana@example.com y mi dni 30123456", channel="whatsapp")
say("wa-5491199990000", "tengo un reclamo", channel="whatsapp")
for h in drain():       # el sessionId de WhatsApp es wa-<teléfono> (así lo ubica la API): eso no se tapa
    body = json.loads(h["raw"])
    seen = json.dumps([body.get(k) for k in ("customer", "slots", "messages", "text", "handoff")], ensure_ascii=False)
    assert "ana@example.com" not in seen and "30123456" not in seen and "5491199990000" not in seen, seen
a["pii_redaction"] = False
app.store(a)

# --- teléfono: Twilio <Sip> con encabezados, <Number>, Enqueue de Flex; jambonz dial con headers y User-to-User
rec = app.load_session(AID, "wa-5491112345678")
rec["state"]["slots"]["dni"] = "30123456"
heads = handoff.sip_headers(app.load(AID), rec)
assert heads["X-Parla-Session"] == "wa-5491112345678" and heads["X-Parla-Intent"] == "reclamo" and heads["X-Parla-Language"] == "es", heads
assert heads["X-Parla-Slot-dni"] == "30123456" and heads["X-Parla-Context"].endswith("/lookup?sid=wa-5491112345678"), heads
assert heads["User-to-User"] == "wa-5491112345678".encode().hex() + ";encoding=hex", heads
assert "EAAtoken" not in json.dumps(heads) and "s3cr3t" not in json.dumps(heads)
conf = {"provider": "twilio"}
xml = phone.twiml(app.load(AID), conf, {"say": [], "lang": "es", "then": "dial", "to": "sip:cola@cc.example.com", "headers": heads}).decode()
assert "<Dial><Sip>sip:cola@cc.example.com?X-Parla-Session=wa-5491112345678&amp;X-Parla-Intent=reclamo&amp;" in xml, xml
assert "User-to-User=" + "wa-5491112345678".encode().hex() + "%3Bencoding%3Dhex</Sip></Dial>" in xml, xml
xml = phone.twiml(app.load(AID), conf, {"say": [], "lang": "es", "then": "dial", "to": "+5491100000000", "headers": heads}).decode()
assert "<Dial><Number>+5491100000000</Number></Dial>" in xml, xml
task = handoff.task_attributes(app.load(AID), rec)
xml = phone.twiml(app.load(AID), conf, {"say": [], "lang": "es", "then": "dial", "to": "", "workflow": "WW" + "a" * 32, "task": task}).decode()
assert '<Enqueue workflowSid="WW%s"><Task>' % ("a" * 32) in xml and "</Task></Enqueue>" in xml, xml
from xml.etree import ElementTree  # noqa: E402
body = json.loads(ElementTree.fromstring(xml).find("Enqueue/Task").text)
assert body["parla_session"] == "wa-5491112345678" and body["intent"] == "reclamo" and body["slots"]["dni"] == "30123456", body
verbs = phone.verbs(app.load(AID), {"provider": "jambonz"}, {"say": [], "lang": "es", "then": "dial", "to": "sip:cola@cc.example.com", "headers": heads})
assert verbs[0]["verb"] == "dial" and verbs[0]["headers"] == heads and verbs[0]["headers"]["User-to-User"].endswith(";encoding=hex"), verbs
# truncado: cada valor y el total
rec["handoff"]["summary"] = "ñandú " + "x" * 2000
rec["state"]["slots"]["dni"] = "9" * 500
heads = handoff.sip_headers(app.load(AID), rec)
assert all(len(urllib.parse.quote(v, safe="")) <= handoff.SIP_VALUE_MAX for v in heads.values()), heads
assert sum(len(k) + 2 + len(urllib.parse.quote(v, safe="")) for k, v in heads.items()) <= handoff.SIP_TOTAL_MAX
assert heads["X-Parla-Summary"].startswith("and ")         # sin lo que no es ASCII
# por el webhook de Twilio de verdad: Flex con la tarea
a = app.load(AID)
a["handoff"]["phone"]["twilio_workflow_sid"] = "WW" + "b" * 32
app.store(a)
call = app.open_session(AID, "call-CA2", "phone")
app.save_session(AID, call)
p = phone.plan(app.load(AID), app.load(AID)["channels"]["phone"], "call-CA2", "message", text="tengo un reclamo")
assert p["then"] == "dial" and p["workflow"] == "WW" + "b" * 32 and p["task"]["parla_session"] == "call-CA2", p

# --- resumen con la IA del agente (solo si está prendida); si falla, el fijo
real_chat = handoff.llm.chat
handoff.llm.chat = lambda cfg, messages, **kw: "  Quiere reclamar\npor su router. "
rec = app.load_session(AID, "s4")
assert handoff.summary(dict(app.load(AID), ai={"enabled": True}), rec) == "Quiere reclamar por su router."
handoff.llm.chat = lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("sin IA"))
assert "reclamo" in handoff.summary(dict(app.load(AID), ai={"enabled": True}), rec)
handoff.llm.chat = real_chat

# --- auditoría
actions = {r[0] for r in db.q("SELECT action FROM audit")}
for needed in ("handoff.accept", "handoff.release", "handoff.close", "handoff.message", "webhook.retry", "webhook.test"):
    assert needed in actions, (needed, actions)
s, saved = js("PUT", "/api/agents/%s" % AID, dict(app.load(AID), webhooks=[]), EDITOR)
for _ in range(50):          # la auditoría se escribe después de contestar
    if "handoff.update" in {r[0] for r in db.q("SELECT action FROM audit")}:
        break
    time.sleep(0.05)
assert s == 200 and "handoff.update" in {r[0] for r in db.q("SELECT action FROM audit")}, saved
assert js("PUT", "/api/agents/%s" % AID, dict(app.load(AID), webhooks=[{"url": FAKE + "/hook/b", "events": ALL}]), ANALYST)[0] == 403
print("ok: modo external, webhooks firmados (orden, reintentos, dead-letter), API del contact center, lookup, SIP/Flex/jambonz, scope y auditoría")
