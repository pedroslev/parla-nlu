"""Varias réplicas sobre la misma Postgres (y la misma carpeta de datos): dos servidores de verdad en puertos distintos.
Turnos alternados y a la vez entre réplicas, login válido en las dos, la respuesta de una persona en A llega a un
WebSocket en B, la cola de envíos sin duplicados, una sola líder (y otra toma su lugar si se muere) y el /after de
una llamada en la otra réplica. Sin PARLA_DATABASE_URL se saltea."""
import base64
import hashlib
import hmac
import json
import os
import socket
import struct
import sys
import threading
import time
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import support

if not os.environ.get("PARLA_DATABASE_URL"):
    print("saltado: sin PARLA_DATABASE_URL (Postgres)")
    sys.exit(0)

DATA = support.temp_data()
os.environ.setdefault("PARLA_SECRET_KEY", "clave-de-prueba")
os.environ["PARLA_METRICS"] = "1"
SENT = []


class Fake(BaseHTTPRequestHandler):          # la API de Telegram
    def do_POST(self):
        SENT.append(json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0))))
        raw = json.dumps({"ok": True, "result": {"message_id": len(SENT)}}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def log_message(self, *args):
        pass


fake = ThreadingHTTPServer(("127.0.0.1", 0), Fake)
threading.Thread(target=fake.serve_forever, daemon=True).start()
os.environ["PARLA_TELEGRAM_API"] = "http://127.0.0.1:%d/tg" % fake.server_address[1]

from parla import db, phone, vault  # noqa: E402

A, PA = support.start_server(DATA)
B, PB = support.start_server(DATA)
procs = [A, B]


def call(port, method, path, body=None, cookie=None, headers=None, raw=None):
    data = raw if raw is not None else json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request("http://127.0.0.1:%d%s" % (port, path), data, method=method, headers={
        "Content-Type": "application/json", **({"Cookie": cookie} if cookie else {}), **(headers or {})})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            out = r.read()
            return r.status, json.loads(out) if out[:1] in (b"{", b"[") else out.decode(), r.headers.get("Set-Cookie")
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}"), None


def ws(port, path, cookie):
    s = socket.create_connection(("127.0.0.1", port), timeout=30)
    key = base64.b64encode(os.urandom(16)).decode()
    s.sendall(("GET %s HTTP/1.1\r\nHost: 127.0.0.1:%d\r\nUpgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Key: %s\r\n"
               "Sec-WebSocket-Version: 13\r\nCookie: %s\r\n\r\n" % (path, port, key, cookie)).encode())
    head = b""
    while b"\r\n\r\n" not in head:
        head += s.recv(1)
    assert head.startswith(b"HTTP/1.1 101"), head
    return s


def send(s, data):
    raw, mask = json.dumps(data).encode(), os.urandom(4)
    size = bytes([0x80 | len(raw)]) if len(raw) < 126 else bytes([0x80 | 126]) + struct.pack("!H", len(raw))
    s.sendall(b"\x81" + size + mask + bytes(b ^ mask[i % 4] for i, b in enumerate(raw)))


def recv(s, kind):
    while True:
        b1, b2 = s.recv(1)[0], s.recv(1)[0]
        n = b2 & 0x7F
        n = struct.unpack("!H", s.recv(2))[0] if n == 126 else struct.unpack("!Q", s.recv(8))[0] if n == 127 else n
        data = b""
        while len(data) < n:
            data += s.recv(n - len(data))
        if b1 & 0x0F == 1 and json.loads(data).get("type") == kind:
            return json.loads(data)


def leaders():
    return [call(p, "GET", "/readyz")[1]["leader"] for p in (PA, PB)]


try:
    # ---------- login en A, vale en B (logins en Postgres, users.json en la carpeta compartida) ----------
    status, _, cookie = call(PA, "POST", "/api/users", {"name": "ana", "password": "secreta123"})
    assert status == 200, status
    cookie = cookie.split(";")[0]
    assert call(PB, "GET", "/api/auth/me", cookie=cookie)[1]["user"]["name"] == "ana"
    assert call(PB, "GET", "/readyz")[1]["database"] == "postgres"

    # ---------- un agente creado y entrenado en A responde en B ----------
    agent = call(PA, "POST", "/api/agents", {"name": "Pizzería"}, cookie)[1]
    AID = agent["id"]
    agent.update(threshold=0.5, slots=[{"name": "gusto"}],
                 intents=[{"name": "pedir", "examples": ["quiero una pizza", "quiero pedir", "una pizza por favor"]}],
                 flows=[{"name": "inicio", "trigger": "__start__", "steps": [{"type": "message", "text": "Hola"}]},
                        {"name": "pedido", "trigger": "pedir", "steps": [{"type": "ask", "slot": "gusto", "text": "¿Qué gusto?"},
                                                                         {"type": "message", "text": "Elegiste {{ gusto }}"}]}],
                 channels={"public_url": "https://bots.example.com", "telegram": {"enabled": True},
                           "phone": {"enabled": True, "provider": "twilio", "mode": "stream", "language": "es-AR"}})
    assert call(PA, "PUT", "/api/agents/" + AID, agent, cookie)[0] == 200
    assert call(PA, "POST", "/api/agents/%s/train" % AID, {}, cookie)[0] == 200
    EV = "/api/v1/bots/%s/events" % AID
    vault.put(AID, "TELEGRAM_TOKEN", "123456:ABC-tg")          # la carpeta de datos es la misma: lo ven las dos

    # ---------- turnos alternados: el estado sigue de una réplica a la otra ----------
    assert call(PA, "POST", EV, {"type": "start", "sessionId": "alt", "environment": "draft"}, cookie)[1]["messages"] == ["Hola"]
    assert call(PB, "POST", EV, {"type": "message", "sessionId": "alt", "text": "quiero una pizza", "environment": "draft"},
                cookie)[1]["messages"] == ["¿Qué gusto?"]
    assert call(PA, "POST", EV, {"type": "message", "sessionId": "alt", "text": "muzza", "environment": "draft"},
                cookie)[1]["messages"] == ["Elegiste muzza"]
    print("ok: turnos alternados entre réplicas")

    # ---------- 30 mensajes a la vez, mitad por cada réplica: ninguno se pierde (advisory lock por conversación) ----------
    call(PA, "POST", EV, {"type": "start", "sessionId": "rafaga", "environment": "draft"}, cookie)
    with ThreadPoolExecutor(30) as pool:
        codes = list(pool.map(lambda i: call((PA, PB)[i % 2], "POST", EV, {"type": "message", "sessionId": "rafaga", "text": "m%d" % i,
                                                                          "environment": "draft"}, cookie)[0], range(30)))
    assert codes == [200] * 30, codes
    history = call(PB, "GET", "/api/v1/bots/%s/sessions/rafaga" % AID, cookie=cookie)[1]["history"]
    said = [h["text"] for h in history if h["from"] == "user"]
    assert sorted(said) == sorted("m%d" % i for i in range(30)), said
    print("ok: 30 turnos concurrentes en 2 réplicas, ninguno perdido")

    # ---------- la persona de la Bandeja contesta en A: llega al WebSocket abierto en B (LISTEN/NOTIFY) ----------
    s = ws(PB, "/api/v1/bots/%s/ws" % AID, cookie)
    send(s, {"id": 1, "type": "start", "sessionId": "ws-1", "environment": "draft"})
    assert recv(s, "reply")["status"] == 200
    assert call(PA, "POST", "/api/agents/%s/sessions/ws-1/take" % AID, {}, cookie)[0] == 200
    assert call(PA, "POST", "/api/agents/%s/sessions/ws-1/reply" % AID, {"text": "Hola, soy Ana"}, cookie)[0] == 200
    t0, pushed = time.time(), []
    while not any(m.get("from") == "human" and m.get("text") == "Hola, soy Ana" for p in pushed for m in p["messages"]):
        assert time.time() - t0 < 10, pushed
        pushed.append(recv(s, "messages"))
    s.close()
    print("ok: respuesta de la persona en A -> WebSocket en B")

    # ---------- la cola: 200 envíos encolados, las dos réplicas reservan filas (SKIP LOCKED): cada uno sale una vez ----------
    with ThreadPoolExecutor(10) as pool:            # Telegram solo deja escribirle a quien ya tiene una charla
        list(pool.map(lambda a: call(PA, "POST", EV, {"type": "start", "sessionId": "tg-%d" % a, "channel": "telegram"}, cookie),
                      list(range(1000, 1200)) + list(range(2000, 2020))))
    SENT.clear()
    now = time.strftime("%Y-%m-%dT%H:%M:%S")
    with db.connect() as conn:
        for i in range(200):
            conn.execute("INSERT INTO campaign_recipients (campaign_id, agent_id, kind, channel, address, spec, status, next_at, created, updated) "
                         "VALUES (NULL, ?, 'api', 'telegram', ?, ?, 'queued', 0, ?, ?)", (AID, str(1000 + i), json.dumps({"flow": "inicio"}), now, now))
    t0 = time.time()
    while db.q("SELECT count(*) FROM campaign_recipients WHERE status IN ('queued', 'sending')")[0][0]:
        assert time.time() - t0 < 30, db.q("SELECT status, count(*) FROM campaign_recipients GROUP BY status")
        time.sleep(0.1)
    chats = sorted(m["chat_id"] for m in SENT)
    assert chats == sorted(str(1000 + i) for i in range(200)), (chats, db.q("SELECT status, error, count(*) FROM campaign_recipients GROUP BY 1, 2"))   # ni uno repetido, ni uno de menos
    def sent_by(port):
        lines = call(port, "GET", "/metrics")[1].splitlines()
        return sum(float(x.rsplit(" ", 1)[1]) for x in lines if x.startswith("parla_outbound_messages_total") and 'outcome="sent"' in x)
    print("ok: 200 envíos de la cola entre 2 réplicas, sin duplicados (A mandó %d, B %d)" % (sent_by(PA), sent_by(PB)))
    # una campaña (el ritmo lo lleva solo la líder)
    SENT.clear()
    camp = call(PB, "POST", "/api/agents/%s/campaigns" % AID, {"name": "C", "channel": "telegram", "flow": "inicio",
                                                               "rate": {"count": 50, "per": "second"},
                                                               "recipients": [{"to": str(2000 + i)} for i in range(20)]}, cookie)[1]
    assert call(PB, "POST", "/api/agents/%s/campaigns/%s/start" % (AID, camp["id"]), None, cookie)[1]["status"] == "running"
    t0 = time.time()
    while call(PA, "GET", "/api/agents/%s/campaigns/%s" % (AID, camp["id"]), cookie=cookie)[1]["status"] != "done":
        assert time.time() - t0 < 30
        time.sleep(0.2)
    assert sorted(m["chat_id"] for m in SENT) == sorted(str(2000 + i) for i in range(20)), SENT
    print("ok: campaña de 20 sin duplicados")

    # ---------- /after de una llamada en la otra réplica: el plan está en kv, la firma de audio es la misma ----------
    vault.put(AID, "TWILIO_AUTH_TOKEN", "tw-token")

    def twilio(port, action, params):
        path = "/api/v1/bots/%s/phone/twilio%s" % (AID, "/" + action if action else "")
        sig = base64.b64encode(hmac.new(b"tw-token", ("https://bots.example.com" + path + "".join(k + v for k, v in sorted(params.items()))).encode(),
                                        hashlib.sha1).digest()).decode()
        return call(port, "POST", path, raw=urllib.parse.urlencode(params).encode(), headers={
            "Host": "bots.example.com", "Content-Type": "application/x-www-form-urlencoded", "X-Twilio-Signature": sig})

    status, xml, _ = twilio(PA, "", {"CallSid": "CA1", "From": "+5491111111111", "CallStatus": "ringing"})
    assert status == 200 and "<Stream" in xml, xml
    assert phone.unstash(phone._greet, "call-CA1") is not None        # el saludo del stream: lo puede leer cualquier réplica
    phone.stash(phone._after, "call-CA1", {"say": [], "then": "dial", "to": "+5491100000000", "lang": "es"})
    status, xml, _ = twilio(PB, "after", {"CallSid": "CA1", "CallStatus": "in-progress"})
    assert status == 200 and "<Dial><Number>+5491100000000</Number></Dial>" in xml, xml
    print("ok: /after en la otra réplica transfiere")

    # ---------- una sola líder; si se muere, la otra toma su lugar ----------
    assert sorted(leaders()) == [False, True], leaders()
    lead, other = (A, PB) if leaders()[0] else (B, PA)
    lead.kill()
    lead.wait()
    t0 = time.time()
    while not call(other, "GET", "/readyz")[1]["leader"]:
        assert time.time() - t0 < 15
        time.sleep(0.2)
    print("ok: la líder murió; la otra réplica es líder en %.1f s" % (time.time() - t0))
    C, PC = support.start_server(DATA)          # una nueva réplica arranca como seguidora
    procs.append(C)
    assert call(PC, "GET", "/readyz")[1]["leader"] is False
    assert call(PC, "GET", "/api/auth/me", cookie=cookie)[1]["user"]["name"] == "ana"
finally:
    for p in procs:
        p.kill()
        p.wait()

# ---------- python -m parla.migrate sqlite-to-postgres: un parla.db de antes, a esta base (y de nuevo: no duplica) ----------
import subprocess  # noqa: E402
OLD = os.path.join(DATA, "viejo")
env = {k: v for k, v in os.environ.items() if k != "PARLA_DATABASE_URL"}
subprocess.run([sys.executable, "-c", "from parla import db; db.audit('eli', 'owner', None, 'migrada'); "
                "db.q(\"INSERT INTO sessions (agent_id, session_id, updated, record) VALUES ('abcd0001', 'vieja', 'x', '{\\\"ended\\\": true}')\")"],
               check=True, cwd=support.ROOT, env=dict(env, PARLA_DATA=OLD))
FRESH = os.environ["PARLA_DATABASE_SCHEMA"] + "_mig"           # a una base vacía, como se usa
import atexit  # noqa: E402
atexit.register(support._drop_schema, FRESH)
for _ in range(2):
    subprocess.run([sys.executable, "-m", "parla.migrate", "sqlite-to-postgres", os.path.join(OLD, "parla.db")], check=True, cwd=support.ROOT,
                   stdout=subprocess.DEVNULL, env=dict(os.environ, PARLA_DATABASE_SCHEMA=FRESH))
import psycopg  # noqa: E402
with psycopg.connect(os.environ["PARLA_DATABASE_URL"], options="-c search_path=" + FRESH) as conn:
    assert conn.execute("SELECT count(*) FROM sessions WHERE session_id = 'vieja'").fetchone()[0] == 1
    assert conn.execute("SELECT \"user\" FROM audit WHERE action = 'migrada'").fetchall() == [("eli",)]
print("ok: sqlite-to-postgres")
print("ok")
