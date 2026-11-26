"""WhatsApp y Telegram contra APIs de mentira (nada sale a internet):  .venv/bin/python tests/test_channels.py"""
import base64
import hashlib
import hmac
import json
import os
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import support
DATA = support.temp_data()

CALLS, FAIL = [], []          # pedidos que recibió la API falsa; códigos a devolver en los próximos pedidos


class Fake(BaseHTTPRequestHandler):
    def do_POST(self):
        body = self.rfile.read(int(self.headers.get("Content-Length") or 0))
        CALLS.append({"path": self.path, "auth": self.headers.get("Authorization"), "type": self.headers.get("Content-Type"), "body": body})
        code = FAIL.pop(0) if FAIL else 200
        out = json.dumps({"ok": code == 200, "id": "media-1", "result": True,
                          "echo": self.headers.get("Authorization")}).encode()      # un 4xx que repite el token: tiene que taparse
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(out)))
        self.end_headers()
        self.wfile.write(out)

    def log_message(self, *args):
        pass


fake = ThreadingHTTPServer(("127.0.0.1", 0), Fake)
threading.Thread(target=fake.serve_forever, daemon=True).start()
os.environ["PARLA_WHATSAPP_API"] = "http://127.0.0.1:%d/wa" % fake.server_address[1]
os.environ["PARLA_TELEGRAM_API"] = "http://127.0.0.1:%d/tg" % fake.server_address[1]

from parla import server as app, vault, files, channels  # noqa: E402
import numpy as np  # noqa: E402

# vectores de juguete: la misma frase da el mismo vector, frases distintas casi ortogonales (sin bajar el modelo)
app._encode = lambda texts: [(lambda v: v / np.linalg.norm(v))(np.random.default_rng(
    int(hashlib.md5(t.encode()).hexdigest()[:8], 16)).normal(size=64)) for t in texts]
os.makedirs(app.AGENTS, exist_ok=True)
LONG = "una opción con un valor larguísimo que no entra en los 64 bytes de Telegram ni de casualidad"
agent = app.create({**app.BLANK, "name": "Pizzería", "threshold": 0.9,
    "intents": [{"name": "saludar", "examples": ["hola"]}, {"name": "menu", "examples": ["menu"]},
                {"name": "archivo", "examples": ["precios"]}],
    "slots": [{"name": "gusto"}],
    "flows": [{"name": "saludo", "trigger": "saludar", "steps": [
                  {"type": "ask", "slot": "gusto", "text": "¿Qué gusto?", "buttons": [
                      {"label": "Muzzarella", "value": "muzza"}, {"label": "Fugazza", "value": "fuga"}]},
                  {"type": "message", "text": "Elegiste {{ gusto }}"}, {"type": "set", "slot": "gusto", "mode": "clear"}]},
              {"name": "carta", "trigger": "menu", "steps": [
                  {"type": "ask", "slot": "gusto", "text": "Elegí", "buttons": [{"label": "Opción %d" % i, "value": "o%d" % i} for i in range(4)]
                   + [{"label": "Larga", "value": LONG}]},
                  {"type": "message", "text": "Elegiste {{ gusto }}"}, {"type": "set", "slot": "gusto", "mode": "clear"}]},
              {"name": "lista", "trigger": "archivo", "steps": [{"type": "file", "file": "precios.pdf", "text": "Acá va"}]}],
    "channels": {"public_url": "https://bots.example.com", "whatsapp": {"enabled": False, "phone_number_id": "111"},
                 "telegram": {"enabled": True}}})
AID = agent["id"]
files.save(AID, "precios.pdf", base64.b64encode(b"%PDF-1.4 lista").decode())
for name, value in {"WHATSAPP_TOKEN": "EAAtoken-secreto", "WHATSAPP_APP_SECRET": "app-secret", "WHATSAPP_VERIFY_TOKEN": "verificame",
                    "TELEGRAM_TOKEN": "123456:ABC-tg_token"}.items():
    vault.put(AID, name, value)

srv = ThreadingHTTPServer(("127.0.0.1", 0), app.Handler)
threading.Thread(target=srv.serve_forever, daemon=True).start()
BASE = "http://127.0.0.1:%d" % srv.server_address[1]


def call(method, path, body=None, headers=None, raw=None):
    data = raw if raw is not None else json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(BASE + path, data=data, method=method,
                                 headers={"Content-Type": "application/json", **(headers or {})})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, r.read(), r.headers
    except urllib.error.HTTPError as e:
        return e.code, e.read(), e.headers


# con un usuario creado, todo pide sesión... menos los webhooks
status, _, hdrs = call("POST", "/api/users", {"name": "dueña", "password": "secreta1"})
assert status == 200
COOKIE = {"Cookie": hdrs["Set-Cookie"].split(";")[0]}
FOREIGN = {"Host": "bots.example.com"}            # vienen de Meta/Telegram: otro Host, sin cookie


def wait(n, timeout=5):
    end = time.time() + timeout
    while len(CALLS) < n and time.time() < end:
        time.sleep(0.02)
    time.sleep(0.1)                               # que no lleguen de más
    assert len(CALLS) == n, [c["path"] for c in CALLS]
    out = list(CALLS)
    CALLS.clear()
    return out


def wa(messages, secret="app-secret", statuses=None):
    payload = {"object": "whatsapp_business_account", "entry": [{"id": "waba", "changes": [{"field": "messages", "value": {
        "messaging_product": "whatsapp", "metadata": {"phone_number_id": "111"}, "messages": messages, **({"statuses": statuses} if statuses else {})}}]}]}
    raw = json.dumps(payload).encode()
    sig = "sha256=" + hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()
    return call("POST", "/api/v1/bots/%s/whatsapp" % AID, raw=raw, headers={"X-Hub-Signature-256": sig, **FOREIGN})[0]


def text(mid, body, sender="5491112345678"):
    return {"from": sender, "id": mid, "type": "text", "text": {"body": body}}


# --- WhatsApp apagado: 403 sin detalles
assert wa([text("m0", "hola")]) == 403
assert call("GET", "/api/v1/bots/%s/whatsapp?hub.mode=subscribe&hub.verify_token=verificame&hub.challenge=42" % AID, headers=FOREIGN)[0] == 403
agent = app.load(AID)
agent["channels"]["whatsapp"]["enabled"] = True
app.store(agent)

# --- verificación GET
s, body, _ = call("GET", "/api/v1/bots/%s/whatsapp?hub.mode=subscribe&hub.verify_token=verificame&hub.challenge=1158201444" % AID, headers=FOREIGN)
assert (s, body) == (200, b"1158201444"), (s, body)
assert call("GET", "/api/v1/bots/%s/whatsapp?hub.mode=subscribe&hub.verify_token=otro&hub.challenge=1" % AID, headers=FOREIGN)[0] == 403

# --- firma mala o ausente: 403 y no se atiende nada
assert wa([text("m1", "hola")], secret="otro") == 403
assert call("POST", "/api/v1/bots/%s/whatsapp" % AID, raw=b"{}", headers=FOREIGN)[0] == 403
try:                                          # más de 1 MB: se corta sin leerlo (el cliente puede ver la conexión cerrada)
    assert call("POST", "/api/v1/bots/%s/whatsapp" % AID, raw=b"x" * 1_000_001, headers=FOREIGN)[0] == 413
except OSError:
    pass
wait(0)

# --- firma buena: el bot contesta con botones interactivos
assert wa([text("m2", "hola")]) == 200
(sent,) = wait(1)
assert sent["path"] == "/wa/111/messages" and sent["auth"] == "Bearer EAAtoken-secreto"
msg = json.loads(sent["body"])
assert msg["to"] == "5491112345678" and msg["type"] == "interactive", msg
assert msg["interactive"]["type"] == "button" and msg["interactive"]["body"]["text"] == "¿Qué gusto?"
assert [b["reply"] for b in msg["interactive"]["action"]["buttons"]] == [{"id": "muzza", "title": "Muzzarella"}, {"id": "fuga", "title": "Fugazza"}]
record = app.load_session(AID, "wa-5491112345678")
assert record["channel"] == "whatsapp" and record["environment"] == "production"

# --- el mismo mensaje otra vez (Meta reintenta): no se atiende dos veces; los statuses se ignoran
assert wa([text("m2", "hola")]) == 200
assert wa([], statuses=[{"id": "wamid.out", "status": "read"}]) == 200
wait(0)

# --- tocar un botón
assert wa([{"from": "5491112345678", "id": "m3", "type": "interactive",
            "interactive": {"type": "button_reply", "button_reply": {"id": "muzza", "title": "Muzzarella"}}}]) == 200
(sent,) = wait(1)
assert json.loads(sent["body"])["text"] == {"body": "Elegiste muzza"}

# --- más de 3 botones: lista; un valor que no entra viaja como «#n» y vuelve al valor
assert wa([text("m4", "menu")]) == 200
inter = json.loads(wait(1)[0]["body"])["interactive"]
assert inter["type"] == "list" and inter["action"]["button"] == "Opciones"
rows = inter["action"]["sections"][0]["rows"]
assert [r["id"] for r in rows] == ["o0", "o1", "o2", "o3", LONG], rows       # 200 bytes de id en WhatsApp: entra
assert wa([{"from": "5491112345678", "id": "m5", "type": "interactive",
            "interactive": {"type": "list_reply", "list_reply": {"id": "o2", "title": "Opción 2"}}}]) == 200
assert json.loads(wait(1)[0]["body"])["text"]["body"] == "Elegiste o2"

# --- archivo: se sube a /media y se manda como documento
assert wa([text("m6", "precios")]) == 200
up, doc = wait(2)
assert up["path"] == "/wa/111/media" and up["type"].startswith("multipart/form-data") and b"%PDF-1.4 lista" in up["body"]
doc = json.loads(doc["body"])
assert doc["type"] == "document" and doc["document"] == {"id": "media-1", "caption": "Acá va", "filename": "precios.pdf"}, doc

# --- un 5xx se reintenta una vez; un 4xx no, y el error queda con el token tapado
FAIL.extend([500])
assert wa([text("m7", "hola")]) == 200
assert len(wait(2)) == 2
FAIL.extend([400])
assert wa([text("m8", "fuga")]) == 200
wait(1)
s, body, _ = call("GET", "/api/agents/%s/channels" % AID, headers=COOKIE)
st = json.loads(body)["whatsapp"]
assert st["enabled"] and st["webhook"] == "https://bots.example.com/api/v1/bots/%s/whatsapp" % AID
assert st["secrets"] == {"WHATSAPP_TOKEN": True, "WHATSAPP_APP_SECRET": True, "WHATSAPP_VERIFY_TOKEN": True}
assert "HTTP 400" in st["status"]["error"] and "EAAtoken-secreto" not in st["status"]["error"] and "••••" in st["status"]["error"], st
assert call("GET", "/api/agents/%s/channels" % AID, headers=FOREIGN)[0] == 401      # la administración sí pide sesión

# --- pasar con una persona: el bot se calla, la Bandeja ve el mensaje y la respuesta humana llega por WhatsApp
assert wa([text("m9", "quiero hablar con una persona")]) == 200
assert "persona" in json.loads(wait(1)[0]["body"])["text"]["body"]
assert wa([text("m10", "¿hay alguien?")]) == 200
wait(0)
inbox = json.loads(call("GET", "/api/agents/%s/inbox" % AID, headers=COOKIE)[1])
assert [s["sessionId"] for s in inbox["sessions"]] == ["wa-5491112345678"]
assert app.load_session(AID, "wa-5491112345678")["history"][-1]["text"] == "¿hay alguien?"
s, _, _ = call("POST", "/api/agents/%s/sessions/wa-5491112345678/reply" % AID, {"text": "Hola, soy Ana"}, headers=COOKIE)
assert s == 200
(sent,) = wait(1)
assert json.loads(sent["body"])["text"]["body"] == "Hola, soy Ana" and json.loads(sent["body"])["to"] == "5491112345678"

# --- una imagen sin texto llega como «[imagen]»; si no se puede bajar (esta API falsa no tiene GET), queda el motivo
# (la descarga, el ASR y lo demás: tests/test_media.py)
assert wa([{"from": "5491112345678", "id": "m11", "type": "image", "image": {"id": "img-1", "mime_type": "image/jpeg"}}]) == 200
deadline = time.time() + 5
while time.time() < deadline and app.load_session(AID, "wa-5491112345678")["history"][-1].get("media") is None:
    time.sleep(0.05)
last = app.load_session(AID, "wa-5491112345678")["history"][-1]
assert last["text"] == "[imagen]" and last["media"]["type"] == "image" and "al descargar" in last["media"]["error"], last
wait(0)

# --- Telegram: conectar el webhook genera el secreto y llama a setWebhook
assert call("POST", "/api/agents/%s/channels/telegram" % AID, {"connect": True}, headers=FOREIGN)[0] == 401
s, body, _ = call("POST", "/api/agents/%s/channels/telegram" % AID, {"connect": True}, headers=COOKIE)
assert s == 200 and json.loads(body) == {"connected": True}, body
(hook,) = wait(1)
TG_SECRET = vault.values(AID)["TELEGRAM_WEBHOOK_SECRET"]
assert hook["path"] == "/tg/bot123456:ABC-tg_token/setWebhook"
assert json.loads(hook["body"]) == {"url": "https://bots.example.com/api/v1/bots/%s/telegram" % AID, "secret_token": TG_SECRET,
                                    "allowed_updates": ["message", "callback_query"]}


def tg(update, secret=None):
    return call("POST", "/api/v1/bots/%s/telegram" % AID, update,
                headers={"X-Telegram-Bot-Api-Secret-Token": TG_SECRET if secret is None else secret, **FOREIGN})[0]


chat = {"id": -100777, "type": "group"}
assert tg({"update_id": 1, "message": {"message_id": 1, "chat": chat, "text": "hola"}}, secret="mal") == 403
assert tg({"update_id": 1, "message": {"message_id": 1, "chat": chat, "text": "hola"}}, secret="") == 403
wait(0)
assert tg({"update_id": 2, "message": {"message_id": 2, "chat": chat, "text": "menu"}}) == 200
(sent,) = wait(1)
msg = json.loads(sent["body"])
assert sent["path"] == "/tg/bot123456:ABC-tg_token/sendMessage" and msg["chat_id"] == "-100777" and msg["text"] == "Elegí"
keyboard = [row[0] for row in msg["reply_markup"]["inline_keyboard"]]
assert [k["callback_data"] for k in keyboard] == ["o0", "o1", "o2", "o3", "#4"], keyboard     # 64 bytes: el largo va como #4
assert tg({"update_id": 2, "message": {"message_id": 2, "chat": chat, "text": "menu"}}) == 200   # repetido
wait(0)
assert tg({"update_id": 3, "callback_query": {"id": "cb1", "data": "#4", "message": {"message_id": 3, "chat": chat}}}) == 200
ack, sent = wait(2)
assert ack["path"].endswith("/answerCallbackQuery") and json.loads(ack["body"]) == {"callback_query_id": "cb1"}
assert json.loads(sent["body"])["text"] == "Elegiste " + LONG
assert app.load_session(AID, "tg--100777")["channel"] == "telegram"

# --- archivo por Telegram: se sube como documento
assert tg({"update_id": 4, "message": {"message_id": 4, "chat": chat, "text": "precios"}}) == 200
(sent,) = wait(1)
assert sent["path"].endswith("/sendDocument") and b"%PDF-1.4 lista" in sent["body"] and b'name="chat_id"' in sent["body"]

# --- la Bandeja también responde por Telegram; desconectar llama a deleteWebhook
app.human(AID, "tg--100777", "reply", "Te escribe una persona", "Ana")
assert json.loads(wait(1)[0]["body"]) == {"chat_id": "-100777", "text": "Te escribe una persona"}
s, body, _ = call("POST", "/api/agents/%s/channels/telegram" % AID, {"connect": False}, headers=COOKIE)
assert s == 200 and wait(1)[0]["path"].endswith("/deleteWebhook")

# --- otros canales no mandan nada al responder desde la Bandeja
app.save_session(AID, {**app.open_session(AID, "web-1", "web"), "history": []})
app.human(AID, "web-1", "reply", "hola", "Ana")
wait(0)

# --- el MCP acepta la configuración no secreta y rechaza tokens en el JSON del agente
from parla import mcp_server  # noqa: E402
base = {k: app.load(AID)[k] for k in ("name", "intents", "slots", "flows")}
assert not mcp_server.validate({**base, "channels": {"whatsapp": {"enabled": True, "phone_number_id": "111"}}})[1]
_, errors, _ = mcp_server.validate({**base, "channels": {"telegram": {"enabled": True, "token": "123:abc"}}})
assert any("Claves" in e for e in errors), errors

srv.shutdown()
fake.shutdown()
print("canales ok")
