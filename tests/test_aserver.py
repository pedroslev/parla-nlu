"""Servidor asyncio (aserver.py): WebSocket (handshake, frames, límites), SSE, una fila por conversación, el escritor
de SQLite y el streaming de la IA (deltas + replace). Correr: .venv/bin/python tests/test_aserver.py"""
import base64
import concurrent.futures
import hashlib
import json
import os
import socket
import struct
import subprocess
import sys
import threading
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from support import ROOT, start_server, temp_data

DATA = temp_data()
proc, port = start_server(DATA)
BASE = "http://127.0.0.1:%d" % port


def api(method, path, body=None, headers=None):
    req = urllib.request.Request(BASE + path, json.dumps(body).encode() if body is not None else None,
                                 dict({"Content-Type": "application/json"}, **(headers or {})), method=method)
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}")


def raw(request, read=65536):
    s = socket.create_connection(("127.0.0.1", port), timeout=30)
    s.sendall(request)
    return s, s.recv(read)


def ws_open(path, origin=None, version="13"):
    key = base64.b64encode(os.urandom(16)).decode()
    s, head = raw(("GET %s HTTP/1.1\r\nHost: 127.0.0.1:%d\r\nUpgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Key: %s\r\n"
                   "Sec-WebSocket-Version: %s\r\n%s\r\n" % (path, port, key, version, "Origin: %s\r\n" % origin if origin else "")).encode())
    return s, head, key


def frame(payload, op=1, fin=True, mask=True):
    data = payload.encode() if isinstance(payload, str) else payload
    n, key = len(data), os.urandom(4)
    size = bytes([n]) if n < 126 else bytes([126]) + struct.pack("!H", n) if n < 65536 else bytes([127]) + struct.pack("!Q", n)
    size = bytes([size[0] | (0x80 if mask else 0)]) + size[1:]
    body = bytes(b ^ key[i % 4] for i, b in enumerate(data)) if mask else data
    return bytes([(0x80 if fin else 0) | op]) + size + (key if mask else b"") + body


def recv_exact(s, n):
    out = b""
    while len(out) < n:
        chunk = s.recv(n - len(out))
        if not chunk:
            raise ConnectionError("cerró")
        out += chunk
    return out


def read(s):
    b1, b2 = recv_exact(s, 2)
    n = b2 & 0x7F
    if n == 126:
        n = struct.unpack("!H", recv_exact(s, 2))[0]
    elif n == 127:
        n = struct.unpack("!Q", recv_exact(s, 8))[0]
    return b1 & 0x0F, recv_exact(s, n)


def read_json(s, kind=None):
    while True:
        op, data = read(s)
        assert op == 1, (op, data)
        msg = json.loads(data)
        if kind is None or msg.get("type") == kind:
            return msg


def close_code(s):
    while True:
        op, data = read(s)
        if op == 8:
            return struct.unpack("!H", data[:2])[0]


try:
    with open(os.path.join(ROOT, "examples", "pizzeria.json"), encoding="utf-8") as f:
        status, body = api("POST", "/api/agents", {"import": json.load(f)})
    bot = body.get("agent", body)["id"]
    assert api("POST", "/api/agents/%s/train" % bot, {})[0] == 200

    # --- HTTP/1.1 keep-alive: dos pedidos por la misma conexión; encabezados gigantes -> 431
    s, first = raw(b"GET /api/auth/me HTTP/1.1\r\nHost: 127.0.0.1\r\n\r\n")
    assert first.startswith(b"HTTP/1.1 200"), first[:80]
    s.sendall(b"GET /static/widget.js HTTP/1.1\r\nHost: 127.0.0.1\r\n\r\n")
    assert s.recv(100).startswith(b"HTTP/1.1 200")
    s.close()
    s, out = raw(b"GET / HTTP/1.1\r\nX-Big: " + b"a" * 70000 + b"\r\n\r\n")
    assert out.startswith(b"HTTP/1.1 431"), out[:60]
    s, out = raw(b"POST /api/v1/bots/x/events HTTP/1.1\r\nHost: 127.0.0.1\r\nContent-Length: 999999999\r\n\r\n")
    assert out.startswith(b"HTTP/1.1 413"), out[:60]

    # --- WebSocket: handshake
    s, head, key = ws_open("/api/v1/bots/%s/ws" % bot)
    accept = base64.b64encode(hashlib.sha1((key + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11").encode()).digest()).decode()
    assert head.startswith(b"HTTP/1.1 101") and accept.encode() in head, head
    assert ws_open("/api/v1/bots/%s/ws" % bot, version="8")[1].startswith(b"HTTP/1.1 400")
    assert ws_open("/api/v1/bots/%s/ws" % bot, origin="https://evil.example")[1].startswith(b"HTTP/1.1 403")    # CSWSH
    assert ws_open("/api/v1/bots/nadie/ws")[1].startswith(b"HTTP/1.1 404")

    # una charla por el socket: start + message (fragmentado en 3 frames) con un id que vuelve en la respuesta
    s.sendall(frame(json.dumps({"id": 1, "type": "start", "sessionId": "ws-1", "environment": "draft"})))
    reply = read_json(s, "reply")
    assert reply["id"] == 1 and reply["status"] == 200 and reply["body"]["sessionId"] == "ws-1", reply
    text = json.dumps({"id": 2, "type": "message", "sessionId": "ws-1", "text": "quiero 2 de muzza", "environment": "draft"})
    s.sendall(frame(text[:10], fin=False) + frame(b"\x01", op=9) + frame(text[10:20], op=0, fin=False) + frame(text[20:], op=0))
    op, data = read(s)
    assert (op, data) == (10, b"\x01"), (op, data)             # el ping en el medio del mensaje fragmentado: pong
    reply = read_json(s, "reply")
    assert reply["id"] == 2 and reply["status"] == 200 and reply["body"]["messages"], reply
    # la persona de la bandeja escribe: llega por el mismo socket (bus), sin polling
    assert api("POST", "/api/agents/%s/sessions/ws-1/take" % bot, {})[0] == 200
    assert api("POST", "/api/agents/%s/sessions/ws-1/reply" % bot, {"text": "Hola, soy Ana"})[0] == 200
    pushed = [read_json(s, "messages") for _ in range(2)]
    assert any(m.get("from") == "human" and m["text"] == "Hola, soy Ana" for p in pushed for m in p["messages"]), pushed
    s.sendall(frame("no es json"))
    assert read_json(s)["type"] == "error"
    s.sendall(frame(b"", op=8))
    assert close_code(s) == 1000
    # límites: binario -> 1003, sin máscara -> 1002, más de 1 MB -> 1009, UTF-8 roto -> 1007
    for bad, code in ((frame(b"\x00", op=2), 1003), (frame("hola", mask=False), 1002), (bytes([0x81, 0xFF]) + struct.pack("!Q", 1_000_001), 1009),
                      (frame(b"\xff\xfe"), 1007), (frame("x", op=0), 1002)):
        s = ws_open("/api/v1/bots/%s/ws" % bot)[0]
        s.sendall(bad)
        assert close_code(s) == code, code

    # --- SSE: el stream de una conversación recibe lo nuevo, y la bandeja avisa
    api("POST", "/api/v1/bots/%s/events" % bot, {"type": "start", "sessionId": "sse-1", "environment": "draft"})
    s, head = raw(("GET /api/v1/bots/%s/sessions/sse-1/stream HTTP/1.1\r\nHost: 127.0.0.1:%d\r\n\r\n" % (bot, port)).encode(), 300)
    assert head.startswith(b"HTTP/1.1 200") and b"text/event-stream" in head, head
    buf = head
    while buf.count(b"event: messages") < 1:
        buf += s.recv(65536)
    api("POST", "/api/v1/bots/%s/events" % bot, {"type": "message", "sessionId": "sse-1", "text": "hola", "environment": "draft"})
    while buf.count(b"event: messages") < 2:
        buf += s.recv(65536)
    assert b'"from": "user", "text": "hola"' in buf, buf[-400:]
    s.close()
    s, head = raw(("GET /api/agents/%s/inbox/stream HTTP/1.1\r\nHost: 127.0.0.1:%d\r\n\r\n" % (bot, port)).encode(), 300)
    buf = head
    while b"event: inbox" not in buf:
        buf += s.recv(65536)
    assert api("POST", "/api/agents/%s/sessions/sse-1/take" % bot, {})[0] == 200
    while buf.count(b"event: inbox") < 2:          # tomarla cambia la bandeja: llega sola
        buf += s.recv(65536)
    s.close()
    s, head = raw(("GET /api/v1/bots/%s/sessions/sse-1/stream HTTP/1.1\r\nHost: 127.0.0.1:%d\r\nOrigin: https://evil.example\r\n\r\n" % (bot, port)).encode(), 300)
    assert head.startswith(b"HTTP/1.1 403"), head[:60]      # mismas reglas que el polling

    # --- una fila por conversación: 15 turnos a la vez en la MISMA charla no se pisan (todos quedan en el historial)
    api("POST", "/api/v1/bots/%s/events" % bot, {"type": "start", "sessionId": "same", "environment": "draft"})
    with concurrent.futures.ThreadPoolExecutor(15) as pool:
        codes = list(pool.map(lambda i: api("POST", "/api/v1/bots/%s/events" % bot, {
            "type": "message", "sessionId": "same", "text": "mensaje %d" % i, "environment": "draft"})[0], range(15)))
    assert codes == [200] * 15, codes
    history = api("GET", "/api/v1/bots/%s/sessions/same" % bot)[1]["history"]
    said = [h["text"] for h in history if h["from"] == "user"]
    assert sorted(said) == sorted("mensaje %d" % i for i in range(15)), said
finally:
    proc.terminate()
    proc.wait(10)

# --- el escritor de SQLite: lo que q() devolvió ya está commiteado (otra conexión lo ve). Si el proceso muere con
# la escritura en la cola (antes del COMMIT), no queda nada y quien la pidió nunca recibió respuesta.
script = r"""
import os, sys, sqlite3, threading, time
sys.path.insert(0, %r)
from parla import db
db.q("INSERT INTO audit (at, action) VALUES ('t', 'committed')")
assert sqlite3.connect(db.path()).execute("SELECT count(*) FROM audit WHERE action = 'committed'").fetchone()[0] == 1
db.WRITE.acquire()                     # el escritor no puede commitear: la escritura queda en la cola
t = threading.Thread(target=db.q, args=("INSERT INTO audit (at, action) VALUES ('t', 'lost')",), daemon=True)
t.start()
time.sleep(0.3)
assert t.is_alive()                    # q() no volvió: nadie recibió un OK por esa escritura
os._exit(0)                            # "se cae" entre encolar y commitear
""" % ROOT
if not os.environ.get("PARLA_DATABASE_URL"):     # con Postgres no hay escritor propio: cada q() es su transacción
    subprocess.run([sys.executable, "-c", script], check=True, env=dict(os.environ, PARLA_DATA=DATA))
    import sqlite3  # noqa: E402
    conn = sqlite3.connect(os.path.join(DATA, "parla.db"))
    assert conn.execute("SELECT count(*) FROM audit WHERE action = 'committed'").fetchone()[0] == 1
    assert conn.execute("SELECT count(*) FROM audit WHERE action = 'lost'").fetchone()[0] == 0

# --- streaming de la IA: deltas desde Ollama (NDJSON), OpenAI-compatible (SSE, campo de un JSON) y Gemini (SSE)
from parla import llm  # noqa: E402


class Fake(BaseHTTPRequestHandler):
    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        self.send_response(200)
        self.end_headers()
        if self.path == "/api/chat":
            assert body["stream"] is True
            for piece in ["Ab", "rimos ", "a las 9."]:
                self.wfile.write((json.dumps({"message": {"content": piece}, "done": False}) + "\n").encode())
            self.wfile.write(json.dumps({"message": {"content": ""}, "done": True, "eval_count": 3}).encode() + b"\n")
        elif self.path.endswith("/chat/completions"):
            for piece in ['{"respuesta": "Perd', 'ón, ¿me lo', ' decís de nuevo?"}']:
                self.wfile.write(b"data: " + json.dumps({"choices": [{"delta": {"content": piece}}]}).encode() + b"\n\n")
            self.wfile.write(b"data: [DONE]\n\n")
        else:
            assert "streamGenerateContent" in self.path and "alt=sse" in self.path, self.path
            for piece in ["Hola", " qué tal"]:
                self.wfile.write(b"data: " + json.dumps({"candidates": [{"content": {"parts": [{"text": piece}]}}]}).encode() + b"\n\n")

    def log_message(self, *a):
        pass


fake = ThreadingHTTPServer(("127.0.0.1", 0), Fake)
threading.Thread(target=fake.serve_forever, daemon=True).start()
url = "http://127.0.0.1:%d" % fake.server_address[1]
events = []
llm.STREAM.sink = events.append
assert llm.chat({"provider": "ollama", "url": url, "model": "m"}, [{"role": "user", "content": "?"}], stream=True) == "Abrimos a las 9."
assert [e["text"] for e in events] == ["Ab", "rimos ", "a las 9."] and all(e["type"] == "delta" for e in events), events
llm.settle("Abrimos a las 9.")                 # igual a lo mostrado: sin replace
assert len(events) == 3
events.clear()
out = llm.chat({"provider": "openai_compatible", "url": url + "/v1", "model": "m"}, [{"role": "user", "content": "?"}],
               schema={"type": "object", "properties": {"respuesta": {"type": "string"}}}, stream="respuesta")
assert out == {"respuesta": "Perdón, ¿me lo decís de nuevo?"}, out
assert "".join(e["text"] for e in events) == "Perdón, ¿me lo decís de nuevo?", events     # solo el texto, nunca el JSON
llm.settle("Perdón, ¿me lo decís de nuevo? Puedo ayudarte con: pedidos.")      # el guardrail agregó algo: replace
assert events[-1] == {"type": "replace", "stream": events[0]["stream"], "text": "Perdón, ¿me lo decís de nuevo? Puedo ayudarte con: pedidos."}
events.clear()
from parla import vault  # noqa: E402,F401
assert llm._gemini({"provider": "gemini", "url": url, "model": "g", "api_key": "k"}, [{"role": "user", "content": "?"}], None, 10, 50,
                   llm._streamer(True)) == "Hola qué tal"
assert [e["text"] for e in events] == ["Hola", " qué tal"], events
llm.STREAM.sink = None
fake.shutdown()
print("ok: aserver (WebSocket, SSE, fila por conversación, escritor de SQLite, streaming de la IA)")
