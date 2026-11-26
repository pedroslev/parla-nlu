"""Mensajes salientes, campañas y recordatorios contra APIs de mentira de Meta, Telegram, Twilio y jambonz (nada sale a
internet), con un reloj propio para la cola:  .venv/bin/python tests/test_outbound.py"""
import base64
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
os.environ["PARLA_METRICS"] = "1"

CALLS, FAIL = [], []          # pedidos que recibió la API falsa; (código, cuerpo) a devolver en los próximos
COUNTER = [0]


class Fake(BaseHTTPRequestHandler):
    def do_POST(self):
        body = self.rfile.read(int(self.headers.get("Content-Length") or 0))
        CALLS.append({"path": self.path, "auth": self.headers.get("Authorization"), "type": self.headers.get("Content-Type"), "body": body})
        COUNTER[0] += 1
        n = COUNTER[0]
        code, out = FAIL.pop(0) if FAIL else (200, None)
        if out is None:
            if "/wa/" in self.path:
                out = {"messages": [{"id": "wamid.%d" % n}]}
            elif "/tg/" in self.path:
                out = {"ok": True, "result": {"message_id": n}}
            elif "/twilio/" in self.path:
                out = {"sid": "CA%032x" % n, "status": "queued"}
            else:
                code, out = 201, {"sid": "2531329f-fb09-4ef7-887e-%012d" % n}
        raw = json.dumps(out).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def log_message(self, *args):
        pass


fake = ThreadingHTTPServer(("127.0.0.1", 0), Fake)
threading.Thread(target=fake.serve_forever, daemon=True).start()
FAKE = "http://127.0.0.1:%d" % fake.server_address[1]
os.environ.update(PARLA_WHATSAPP_API=FAKE + "/wa", PARLA_TELEGRAM_API=FAKE + "/tg", PARLA_TWILIO_API=FAKE + "/twilio")

from parla import server as app, vault, outbound, telemetry, db  # noqa: E402
import numpy as np  # noqa: E402

app._encode = lambda texts: [(lambda v: v / np.linalg.norm(v))(np.random.default_rng(
    int(hashlib.md5(t.encode()).hexdigest()[:8], 16)).normal(size=64)) for t in texts]
os.makedirs(app.AGENTS, exist_ok=True)
NOW = [1_800_000_000.0]       # 2027-01-15 08:00 UTC
outbound.clock = lambda: NOW[0]

agent = app.create({**app.BLANK, "name": "Turnos", "threshold": 0.9,
    "intents": [{"name": "turno", "examples": ["quiero un turno"]}, {"name": "pronto", "examples": ["avisame pronto"]}],
    "slots": [{"name": "nombre"}, {"name": "fecha"}],
    "classifications": [{"name": "Confirmó", "color": 0}],
    "flows": [{"name": "Saludo", "trigger": "", "steps": [{"type": "message", "text": "Hola {{ nombre }}"}]},
              {"name": "Confirmar", "trigger": "", "steps": [{"type": "message", "text": "Gracias {{ nombre }}, quedó confirmado"},
                                                              {"type": "classify", "classification": "Confirmó"}]},
              {"name": "Recordatorio", "trigger": "", "steps": [{"type": "message", "text": "Te recuerdo tu turno del {{ fecha }}, {{ nombre }}"}]},
              {"name": "Turno", "trigger": "turno", "steps": [
                  {"type": "set", "slot": "nombre", "mode": "text", "text": "Bea"}, {"type": "set", "slot": "fecha", "mode": "text", "text": "2027-01-20"},
                  {"type": "message", "text": "Te anoto"},
                  {"type": "remind", "after": "24h", "flow": "Recordatorio", "template": "recordatorio"}]},
              {"name": "Pronto", "trigger": "pronto", "steps": [{"type": "remind", "after": "30m", "text": "Ya pasó media hora, {{ nombre }}"}]}],
    "channels": {"public_url": "https://bots.example.com",
                 "whatsapp": {"enabled": True, "phone_number_id": "111", "templates": [{"name": "recordatorio", "language": "es", "params": ["nombre", "fecha"]}]},
                 "telegram": {"enabled": True},
                 "phone": {"enabled": True, "provider": "twilio", "language": "es-AR", "from": "+541100000000"}}})
AID = agent["id"]
TWILIO_SID = "AC" + "0" * 31 + "1"
for name, value in {"WHATSAPP_TOKEN": "EAAtoken", "WHATSAPP_APP_SECRET": "app-secret", "TELEGRAM_TOKEN": "123456:ABC-tg",
                    "TWILIO_AUTH_TOKEN": "tw-auth", "TWILIO_ACCOUNT_SID": TWILIO_SID}.items():
    vault.put(AID, name, value)

srv = ThreadingHTTPServer(("127.0.0.1", 0), app.Handler)
threading.Thread(target=srv.serve_forever, daemon=True).start()
BASE = "http://127.0.0.1:%d" % srv.server_address[1]


def call(method, path, body=None, headers=None, raw=None):
    data = raw if raw is not None else json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(BASE + path, data=data, method=method, headers={"Content-Type": "application/json", **(headers or {})})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, r.read(), r.headers
    except urllib.error.HTTPError as e:
        return e.code, e.read(), e.headers


def js(method, path, body=None, headers=None):
    status, raw, _ = call(method, path, body, headers)
    return status, json.loads(raw or b"{}")


def wait(n, timeout=5):
    end = time.time() + timeout
    while len(CALLS) < n and time.time() < end:
        time.sleep(0.02)
    time.sleep(0.15)
    assert len(CALLS) == n, [c["path"] for c in CALLS]
    out = list(CALLS)
    CALLS.clear()
    return out


def body(c):
    return json.loads(c["body"])


# --- usuarios: dueña (cookie), editor y analista con clave de API
status, _, hdrs = call("POST", "/api/users", {"name": "dueña", "password": "secreta1"})
COOKIE = {"Cookie": hdrs["Set-Cookie"].split(";")[0]}
for name, role in (("edi", "editor"), ("ana", "analyst")):
    assert js("POST", "/api/users", {"name": name, "password": "secreta1", "role": role}, COOKIE)[0] == 200
EDITOR = {"Authorization": "Bearer " + js("POST", "/api/users/edi/keys", {"label": "crm"}, COOKIE)[1]["key"]}
ANALYST = {"Authorization": "Bearer " + js("POST", "/api/users/ana/keys", {"label": "bi"}, COOKIE)[1]["key"]}
FOREIGN = {"Host": "bots.example.com"}
OUT = "/api/v1/bots/%s/outbound" % AID
C = "/api/agents/%s/campaigns" % AID


def wa(messages=None, statuses=None):
    value = {"messaging_product": "whatsapp", "metadata": {"phone_number_id": "111"}, "messages": messages or []}
    if statuses:
        value["statuses"] = statuses
    raw = json.dumps({"entry": [{"changes": [{"field": "messages", "value": value}]}]}).encode()
    sig = "sha256=" + hmac.new(b"app-secret", raw, hashlib.sha256).hexdigest()
    return call("POST", "/api/v1/bots/%s/whatsapp" % AID, raw=raw, headers={"X-Hub-Signature-256": sig, **FOREIGN})[0]


def text(mid, said, sender="5491111110000"):
    return {"from": sender, "id": mid, "type": "text", "text": {"body": said}}


def row(rid):
    r = db.q("SELECT status, error, message_id, attempts, session_id FROM campaign_recipients WHERE id = ?", (rid,))[0]
    return dict(zip(("status", "error", "message_id", "attempts", "session_id"), r))


# ---------- roles: el analista no manda, el editor sí ----------
assert js("POST", OUT, {"channel": "whatsapp", "to": "+54 9 11 1111-0000"}, ANALYST)[0] == 403
assert js("GET", C, None, ANALYST)[0] == 200

# ---------- WhatsApp fuera de la ventana: sin plantilla no se puede; con plantilla, los slots van a {{1}}, {{2}} ----------
s, out = js("POST", OUT, {"channel": "whatsapp", "to": "+54 9 11 1111-0000"}, EDITOR)
assert s == 409 and "24 horas" in out["error"], (s, out)
s, out = js("POST", OUT, {"channel": "whatsapp", "to": "+54 9 11 1111-0000"}, {**EDITOR, "Accept-Language": "en"})
assert "24 hours" in out["error"], out
s, out = js("POST", OUT, {"channel": "whatsapp", "to": "+5491111110000", "template": "recordatorio",
                          "data": {"nombre": "Ana", "fecha": "2027-01-20"}, "flow": "Confirmar"}, EDITOR)
assert s == 200 and out["via"] == "template" and out["sessionId"] == "wa-5491111110000", out
(sent,) = wait(1)
msg = body(sent)
assert sent["path"] == "/wa/111/messages" and msg["type"] == "template", msg
assert msg["template"] == {"name": "recordatorio", "language": {"code": "es"}, "components": [
    {"type": "body", "parameters": [{"type": "text", "text": "Ana"}, {"type": "text", "text": "2027-01-20"}]}]}, msg
first = out["id"]
assert row(first)["status"] == "sent" and row(first)["message_id"] == out["message_id"]
# falta un dato de la plantilla: error claro, nada sale
s, out = js("POST", OUT, {"channel": "whatsapp", "to": "+5491111110009", "template": "recordatorio", "data": {"nombre": "X"}}, EDITOR)
assert s == 400 and "fecha" in out["error"], out
wait(0)

# --- estados de entrega: delivered y read, sin volver atrás
wid = row(first)["message_id"]
assert wa(statuses=[{"id": wid, "status": "delivered"}]) == 200
assert wa(statuses=[{"id": wid, "status": "read"}, {"id": wid, "status": "delivered"}]) == 200
assert row(first)["status"] == "read", row(first)

# --- contesta: corre el flujo pedido (on_reply) y el envío queda como respondido
assert wa([text("in1", "sí, dale")]) == 200
(sent,) = wait(1)
assert body(sent)["text"]["body"] == "Gracias Ana, quedó confirmado", body(sent)
assert row(first)["status"] == "replied"
record = app.load_session(AID, "wa-5491111110000")
assert record["last_inbound"] == NOW[0] and any(h.get("outbound") for h in record["history"])

# ---------- dentro de la ventana: texto libre con el flujo ----------
NOW[0] += 3600
s, out = js("POST", OUT, {"channel": "whatsapp", "to": "5491111110000", "flow": "Saludo", "data": {"nombre": "Ana"}}, EDITOR)
assert s == 200 and out["via"] == "message" and out["messages"] == ["Hola Ana"], out
assert body(wait(1)[0])["text"] == {"body": "Hola Ana"}

# ---------- errores de plantilla de Meta, traducidos ----------
NOW[0] += 2 * 86400
FAIL.append((400, {"error": {"code": 132001, "message": "Template name does not exist in the translation"}}))
s, out = js("POST", OUT, {"channel": "whatsapp", "to": "5491111110000", "template": {"name": "recordatorio"},
                          "data": {"nombre": "Ana", "fecha": "x"}}, {**EDITOR, "Accept-Language": "en"})
assert s == 502 and out["error"] == "the template doesn't exist in that language or isn't approved on WhatsApp yet", out
wait(1)
# un «failed» del webhook (131047) queda en la fila con el motivo
s, out = js("POST", OUT, {"channel": "whatsapp", "to": "5491111110000", "template": "recordatorio", "data": {"nombre": "Ana", "fecha": "x"}}, EDITOR)
wait(1)
assert wa(statuses=[{"id": out["message_id"], "status": "failed", "errors": [{"code": 131047}]}]) == 200
assert row(out["id"])["status"] == "failed" and "24 horas" in row(out["id"])["error"]

# ---------- Telegram: solo a quien ya le escribió al bot ----------
s, out = js("POST", OUT, {"channel": "telegram", "to": "777", "flow": "Saludo", "data": {"nombre": "Tom"}}, EDITOR)
assert s == 400 and "nunca le escribió" in out["error"], out
assert app.api_v1("POST", ["bots", AID, "events"], {"type": "start", "sessionId": "tg-777", "channel": "telegram"})[0] == 200
s, out = js("POST", OUT, {"channel": "telegram", "to": "777", "flow": "Saludo", "data": {"nombre": "Tom"}}, EDITOR)
assert s == 200 and out["sessionId"] == "tg-777", out
(sent,) = wait(1)
assert sent["path"] == "/tg/bot123456:ABC-tg/sendMessage" and body(sent) == {"chat_id": "777", "text": "Hola Tom"}, body(sent)


# ---------- teléfono: Twilio ----------
def twilio_sign(url, params):
    data = url + "".join(k + v for k, v in sorted(params.items()))
    return base64.b64encode(hmac.new(b"tw-auth", data.encode(), hashlib.sha1).digest()).decode()


s, out = js("POST", OUT, {"channel": "phone", "to": "+54 9 11 2222-3333", "flow": "Saludo", "data": {"nombre": "Lía"}}, EDITOR)
assert s == 200 and out["via"] == "call" and out["sessionId"].startswith("call-CA"), out
(made,) = wait(1)
assert made["path"] == "/twilio/2010-04-01/Accounts/%s/Calls.json" % TWILIO_SID, made["path"]
assert made["auth"] == "Basic " + base64.b64encode(("%s:tw-auth" % TWILIO_SID).encode()).decode()
form = urllib.parse.parse_qs(made["body"].decode())
assert form["To"] == ["+5491122223333"] and form["From"] == ["+541100000000"] and form["Method"] == ["POST"], form
hook = form["Url"][0]
assert hook.startswith("https://bots.example.com/api/v1/bots/%s/phone/twilio?o=" % AID), hook
assert form["StatusCallback"][0].startswith("https://bots.example.com/api/v1/bots/%s/phone/twilio/status?o=" % AID)
assert form["StatusCallbackEvent"] == ["initiated", "ringing", "answered", "completed"]
# Twilio atiende y pide el webhook: la llamada empieza con los datos y el flujo pedidos
params = {"CallSid": out["sessionId"][5:], "CallStatus": "in-progress", "From": "+541100000000", "To": "+5491122223333"}
path = hook[len("https://bots.example.com"):]
s, twiml, _ = call("POST", path, raw=urllib.parse.urlencode(params).encode(),
                   headers={"Content-Type": "application/x-www-form-urlencoded", "X-Twilio-Signature": twilio_sign(hook, params), **FOREIGN})
assert s == 200 and b"Hola L\xc3\xada" in twiml, twiml
assert row(out["id"])["status"] == "delivered"
assert app.load_session(AID, out["sessionId"])["state"]["slots"]["nombre"] == "Lía"
# y un turno de voz sigue la misma conversación
gather = hook.replace("/twilio?", "/twilio/gather?")
params = {"CallSid": out["sessionId"][5:], "SpeechResult": "quiero un turno"}
s, twiml, _ = call("POST", gather[len("https://bots.example.com"):], raw=urllib.parse.urlencode(params).encode(),
                   headers={"Content-Type": "application/x-www-form-urlencoded", "X-Twilio-Signature": twilio_sign(gather, params), **FOREIGN})
assert s == 200 and b"Te anoto" in twiml, twiml
assert row(out["id"])["status"] == "replied"

# ---------- teléfono: jambonz ----------
a = app.load(AID)
a["channels"]["phone"].update(provider="jambonz", api_url=FAKE + "/jambonz", application_sid="app-123")
app.store(a)
vault.put(AID, "JAMBONZ_API_KEY", "jz-key")
vault.put(AID, "JAMBONZ_ACCOUNT_SID", "acc-12345678")
vault.put(AID, "JAMBONZ_WEBHOOK_SECRET", "jz-secret")
s, out = js("POST", OUT, {"channel": "phone", "to": "5491133334444", "flow": "Saludo", "data": {"nombre": "Jo"}}, EDITOR)
assert s == 200 and out["via"] == "call", out
(made,) = wait(1)
req = body(made)
assert made["path"] == "/jambonz/v1/Accounts/acc-12345678/Calls" and made["auth"] == "Bearer jz-key", made
assert req["from"] == "+541100000000" and req["to"] == {"type": "phone", "number": "+5491133334444"} and req["application_sid"] == "app-123", req
assert req["call_hook"]["url"].startswith("https://bots.example.com/api/v1/bots/%s/phone/jambonz?o=" % AID) and req["call_hook"]["method"] == "POST"
assert req["call_status_hook"]["url"].startswith("https://bots.example.com/api/v1/bots/%s/phone/jambonz/status?o=" % AID)
payload = json.dumps({"call_sid": out["sessionId"][5:], "call_status": "in-progress", "from": "+541100000000", "to": "+5491133334444"}).encode()
stamp = str(int(time.time()))
sig = "t=%s,v1=%s" % (stamp, hmac.new(b"jz-secret", stamp.encode() + b"." + payload, hashlib.sha256).hexdigest())
s, verbs, _ = call("POST", req["call_hook"]["url"][len("https://bots.example.com"):], raw=payload, headers={"Jambonz-Signature": sig, **FOREIGN})
assert s == 200 and "Hola Jo" in json.dumps(json.loads(verbs), ensure_ascii=False), verbs
# el estado «no atendió» de otra llamada la marca como fallida
s, out = js("POST", OUT, {"channel": "phone", "to": "5491133335555", "flow": "Saludo"}, EDITOR)
(made,) = wait(1)
status_url = body(made)["call_status_hook"]["url"][len("https://bots.example.com"):]
payload = json.dumps({"call_sid": out["sessionId"][5:], "call_status": "no-answer"}).encode()
sig = "t=%s,v1=%s" % (stamp, hmac.new(b"jz-secret", stamp.encode() + b"." + payload, hashlib.sha256).hexdigest())
assert call("POST", status_url, raw=payload, headers={"Jambonz-Signature": sig, **FOREIGN})[0] == 200
assert row(out["id"])["status"] == "failed" and "no-answer" in row(out["id"])["error"]

# ---------- campañas: CSV, mapeo, repetidos, bajas, límite, horario de silencio, pausa, reintentos ----------
outbound.opt_out(AID, "5491100000009", "whatsapp", "a mano")
CSV = ("telefono;nombre;fecha;otro\n+54 9 11 0000-0001;Uno;2027-01-20;x\n+5491100000002;Dos;2027-01-21;y\n"
       "5491100000001;Uno bis;2027-01-20;z\nno-es-un-numero;Tres;;\n+5491100000009;Baja;;\n"
       "+5491100000003;Tres;2027-01-22;\n+5491100000004;Cuatro;2027-01-23;\n")
s, pre = js("POST", C + "/preview", {"csv": CSV}, COOKIE)
assert s == 200 and pre["count"] == 7 and pre["mapping"] == {"telefono": "to", "nombre": "nombre", "fecha": "fecha", "otro": ""}, pre
assert js("POST", C, {"name": "Recordatorios", "channel": "whatsapp", "csv": CSV}, COOKIE)[0] == 400       # sin plantilla ni flujo
s, camp = js("POST", C, {"name": "Recordatorios", "channel": "whatsapp", "template": {"name": "recordatorio"}, "flow": "Confirmar",
                         "csv": CSV, "mapping": pre["mapping"], "rate": {"count": 2, "per": "minute"},
                         "quiet_hours": {"start": "21:00", "end": "09:00"}, "schedule": {"timezone": "UTC"},
                         "conversion": {"classification": "Confirmó"}}, COOKIE)
assert s == 200 and camp["status"] == "draft", camp
assert camp["imported"] == {"added": 4, "duplicates": 1, "invalid": 1, "opted_out": 1}, camp["imported"]
CID = camp["id"]
assert js("POST", C + "/" + CID + "/pause", None, COOKIE)[0] == 409       # no está en marcha
assert js("POST", C + "/" + CID + "/start", None, ANALYST)[0] == 403
assert js("POST", C + "/" + CID + "/start", None, COOKIE)[1]["status"] == "running"
NOW[0] = 1_800_000_000.0 + 10 * 86400 + 4 * 3600           # 12:00 UTC, días después: fuera de la ventana de todos
outbound.tick()
(sent,) = wait(1)                                           # 2 por minuto: uno ahora
assert body(sent)["to"] == "5491100000001" and body(sent)["template"]["components"][0]["parameters"][0]["text"] == "Uno"
outbound.tick(NOW[0] + 10)
wait(0)                                                     # todavía no pasaron 30 segundos
NOW[0] += 30
outbound.tick()
assert body(wait(1)[0])["to"] == "5491100000002"
assert js("POST", C + "/" + CID + "/pause", None, COOKIE)[1]["status"] == "paused"
NOW[0] += 300
outbound.tick()
wait(0)                                                     # en pausa no sale nada
assert js("POST", C + "/" + CID + "/resume", None, COOKIE)[1]["status"] == "running"
FAIL += [(500, {"error": {"message": "boom"}}), (500, {"error": {"message": "boom"}})]      # 5xx dos veces (con su reintento)
outbound.tick()
wait(2)
r3 = db.q("SELECT id FROM campaign_recipients WHERE campaign_id = ? AND address = '5491100000003'", (CID,))[0][0]
assert row(r3)["status"] == "queued" and row(r3)["attempts"] == 1 and row(r3)["error"], row(r3)
NOW[0] = 1_800_000_000.0 + 10 * 86400 + 14 * 3600          # 22:00 UTC: horario de silencio
assert js("GET", C + "/" + CID, None, COOKIE)[1]["waiting"] == "quiet_hours"
outbound.tick()
wait(0)
NOW[0] += 12 * 3600                                         # 10:00 del día siguiente: sigue, y el reintento sale a su turno
outbound.tick()
assert [body(c)["to"] for c in wait(1)] == ["5491100000004"]
NOW[0] += 30
outbound.tick()
assert [body(c)["to"] for c in wait(1)] == ["5491100000003"] and row(r3)["status"] == "sent", row(r3)
# «reinicio»: lo que estaba enviándose queda fallido (no se manda dos veces); lo encolado sigue
s, more = js("POST", C + "/" + CID + "/recipients", {"recipients": [{"to": "+5491100000005", "nombre": "Cinco", "fecha": "2027-02-01"},
                                                                     {"to": "5491100000001"}, {"to": "5491100000006", "nombre": "Seis", "fecha": "2027-02-02"}]}, COOKIE)
assert more["imported"] == {"added": 2, "duplicates": 1, "invalid": 0, "opted_out": 0}, more
r5 = db.q("SELECT id FROM campaign_recipients WHERE campaign_id = ? AND address = '5491100000005'", (CID,))[0][0]
db.q("UPDATE campaign_recipients SET status = 'sending' WHERE id = ?", (r5,))
outbound.recover()
outbound._next.clear()
assert row(r5)["status"] == "failed" and "reinicio" in row(r5)["error"]
NOW[0] += 60
outbound.tick()
assert body(wait(1)[0])["to"] == "5491100000006"
NOW[0] += 60
outbound.tick()
assert js("GET", C + "/" + CID, None, COOKIE)[1]["status"] == "done"

# --- respuesta a la campaña: corre el flujo, cuenta como respondida y como conversión; Reportes filtra por campaña
assert wa([text("c1", "confirmo", sender="5491100000001")]) == 200
assert body(wait(1)[0])["text"]["body"] == "Gracias Uno, quedó confirmado"
stats = js("GET", C + "/" + CID, None, ANALYST)[1]["stats"]
assert stats["total"] == 6 and stats["replied"] == 1 and stats["sent"] == 4 and stats["failed"] == 1 and stats["conversions"] == 1, stats
sessions = js("GET", "/api/v1/bots/%s/sessions?campaign=%s" % (AID, CID), None, COOKIE)[1]["sessions"]
assert sorted(x["sessionId"] for x in sessions) == ["wa-5491100000001", "wa-5491100000002", "wa-5491100000003", "wa-5491100000004", "wa-5491100000006"], sessions
assert js("GET", "/api/v1/bots/%s/report?campaign=%s" % (AID, CID), None, COOKIE)[1]["classifications"][0]["count"] == 1
listing = js("GET", C + "/" + CID + "/recipients?status=failed", None, COOKIE)[1]
assert listing["total"] == 1 and listing["recipients"][0]["to"] == "5491100000005"
s, csv_raw, hdrs = call("GET", C + "/" + CID + "/export", headers=COOKIE)
assert s == 200 and hdrs["Content-Type"].startswith("text/csv") and "attachment" in hdrs["Content-Disposition"]
lines = csv_raw.decode("utf-8-sig").splitlines()
assert lines[0] == "to,status,error,attempts,sent_at,updated,sessionId,fecha,nombre" and len(lines) == 7, lines

# ---------- bajas: «BAJA» confirma, anota y ya no se le escribe ----------
s, c2 = js("POST", C, {"name": "Segunda", "channel": "whatsapp", "template": "recordatorio",
                       "recipients": [{"to": "5491100000002", "nombre": "Dos", "fecha": "x"}, {"to": "5491100000007", "nombre": "Siete", "fecha": "y"}]}, COOKIE)
assert c2["imported"]["added"] == 2
assert wa([text("b1", "BAJA", sender="5491100000002")]) == 200
assert "no te vamos a escribir" in body(wait(1)[0])["text"]["body"]
assert any(o["address"] == "5491100000002" and o["keyword"] == "baja" for o in js("GET", "/api/agents/%s/optouts" % AID, None, COOKIE)[1]["optouts"])
assert outbound.is_optout(agent, "No me escriban más, gracias") and not outbound.is_optout(agent, "stop a la pizza")
s, out = js("POST", OUT, {"channel": "whatsapp", "to": "5491100000002", "template": "recordatorio", "data": {"nombre": "a", "fecha": "b"}}, EDITOR)
assert s == 409 and "no recibir" in out["error"], out
js("POST", C + "/" + c2["id"] + "/start", None, COOKIE)
NOW[0] += 60
outbound.tick()
assert [body(c)["to"] for c in wait(1)] == ["5491100000007"]          # la baja no recibe
st = js("GET", C + "/" + c2["id"], None, COOKIE)[1]["stats"]
assert st["opted_out"] == 1 and st["sent"] == 1, st
assert js("DELETE", "/api/agents/%s/optouts" % AID, {"address": "+5491100000002"}, COOKIE)[1]["optouts"] == [
    o for o in outbound.optouts(AID)] and not outbound.opted_out(AID, "5491100000002")
# cancelar una campaña: lo encolado queda cancelado
s, c3 = js("POST", C, {"name": "Tercera", "channel": "telegram", "flow": "Saludo", "recipients": [{"to": "777"}]}, COOKIE)
js("POST", C + "/" + c3["id"] + "/start", None, COOKIE)
assert js("POST", C + "/" + c3["id"] + "/cancel", None, COOKIE)[1]["stats"]["canceled"] == 1
outbound.tick()
wait(0)
assert js("DELETE", C + "/" + c3["id"], None, COOKIE)[0] == 200

# ---------- recordatorio desde un flujo: se encola y sale a su hora, con plantilla si pasaron más de 24 h ----------
assert wa([text("r1", "quiero un turno", sender="5491144445555")]) == 200
assert body(wait(1)[0])["text"]["body"] == "Te anoto"
(rid, due), = db.q("SELECT id, next_at FROM campaign_recipients WHERE kind = 'remind' AND address = '5491144445555'")
assert abs(due - (NOW[0] + 86400)) < 1 and any(h.get("reminder") for h in app.load_session(AID, "wa-5491144445555")["history"])
outbound.tick(NOW[0] + 3600)
wait(0)                                                     # todavía no
NOW[0] += 86400 + 5
outbound.tick()
msg = body(wait(1)[0])
assert msg["type"] == "template" and [p["text"] for p in msg["template"]["components"][0]["parameters"]] == ["Bea", "2027-01-20"], msg
assert row(rid)["status"] == "sent"
# contesta a la plantilla: corre el flujo del recordatorio; después, otro recordatorio dentro de la ventana va como texto libre
assert wa([text("r2", "ok", sender="5491144445555")]) == 200
assert body(wait(1)[0])["text"]["body"] == "Te recuerdo tu turno del 2027-01-20, Bea"
assert wa([text("r3", "avisame pronto", sender="5491144445555")]) == 200
wait(0)
NOW[0] += 1801
outbound.tick()
assert body(wait(1)[0])["text"]["body"] == "Ya pasó media hora, Bea"

# ---------- límite de la API por minuto ----------
a = app.load(AID)
a["outbound"] = {"api_per_minute": 1}
app.store(a)
NOW[0] += 120
assert js("POST", OUT, {"channel": "telegram", "to": "777", "flow": "Saludo"}, EDITOR)[0] == 200
wait(1)
assert js("POST", OUT, {"channel": "telegram", "to": "777", "flow": "Saludo"}, EDITOR)[0] == 429

# ---------- auditoría (sin teléfonos enteros) y métricas ----------
entries = js("GET", "/api/audit?agent=%s&limit=500" % AID, None, COOKIE)[1]["entries"]
actions = {e["action"] for e in entries}
assert {"outbound.send", "campaign.create", "campaign.start", "campaign.pause", "campaign.resume", "campaign.cancel",
        "campaign.delete", "campaign.recipients", "optout.remove"} <= actions, actions
assert not any("5491111110000" in (e["detail"] or "") or "5491100000002" in (e["detail"] or "") for e in entries), entries
assert any(e["action"] == "outbound.send" and e["detail"].startswith("whatsapp → 549") and "•" in e["detail"] for e in entries)
metrics = call("GET", "/metrics")[1].decode()
assert 'parla_outbound_messages_total{channel="whatsapp",outcome="sent"}' in metrics, metrics[-2000:]
assert 'parla_campaign_recipients{status="sent"}' in metrics and 'route="/api/agents/{id}/campaigns/{campaign}"' in metrics
print("ok: salientes, campañas y recordatorios")
