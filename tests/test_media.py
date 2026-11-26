"""Fotos, audios, documentos, ubicaciones y contactos que llegan por WhatsApp y Telegram; plantillas desde la Bandeja y
el contact center fuera de las 24 h; estado de los envíos. Todo contra APIs de mentira.   .venv/bin/python tests/test_media.py"""
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

CALLS, BLOBS, DOWN = [], {}, []         # pedidos que recibió la API falsa; lo que se descarga (ruta -> (bytes, tipo))
OGG = b"OggS" + b"\x00" * 400
JPG = b"\xff\xd8\xff\xe0" + b"\x00" * 300


class Fake(BaseHTTPRequestHandler):
    def answer(self, body, ctype="application/json", code=200):
        out = body if isinstance(body, bytes) else json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(out)))
        self.end_headers()
        self.wfile.write(out)

    def do_GET(self):
        CALLS.append({"method": "GET", "path": self.path, "auth": self.headers.get("Authorization")})
        path = urllib.parse.urlsplit(self.path).path
        if path in BLOBS:
            return self.answer(BLOBS[path][0], BLOBS[path][1])
        if path.startswith("/wa/m-"):           # GET /{media-id}: dónde bajarlo
            mid = path[4:]
            size = len(BLOBS.get("/dl/" + mid, (b"",))[0])
            return self.answer({"url": "http://127.0.0.1:%d/dl/%s" % (fake.server_address[1], mid), "mime_type": BLOBS.get("/dl/" + mid, (0, "x"))[1],
                                "file_size": 99_000_000 if mid == "m-huge" else size, "id": mid})
        if "/getFile" in path:
            fid = urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query)["file_id"][0]
            return self.answer({"ok": True, "result": {"file_id": fid, "file_path": "voice/%s.oga" % fid}})
        return self.answer({"error": "no"}, code=404)

    def do_POST(self):
        body = self.rfile.read(int(self.headers.get("Content-Length") or 0))
        CALLS.append({"method": "POST", "path": self.path, "auth": self.headers.get("Authorization"), "body": body})
        if self.path.endswith("/audio/transcriptions"):
            if DOWN:
                return self.answer({"error": {"message": "caído"}}, code=503)
            return self.answer({"text": "quiero una muzzarella, mi tel +54 9 11 5555-4444", "usage": {"type": "duration", "seconds": 6}})
        if self.path.endswith("/chat/completions"):
            return self.answer({"choices": [{"message": {"content": "Una pizza con un cartel que dice ABIERTO"}}],
                                "usage": {"prompt_tokens": 50, "completion_tokens": 9}})
        return self.answer({"ok": True, "result": {"message_id": 7}, "messages": [{"id": "wamid.%d" % len(CALLS)}]})

    def log_message(self, *args):
        pass


fake = ThreadingHTTPServer(("127.0.0.1", 0), Fake)
threading.Thread(target=fake.serve_forever, daemon=True).start()
FAKE = "http://127.0.0.1:%d" % fake.server_address[1]
os.environ.update(PARLA_WHATSAPP_API=FAKE + "/wa", PARLA_TELEGRAM_API=FAKE + "/tg", PARLA_OPENAI_BASE_URL=FAKE)

from parla import server as app, vault, files, db  # noqa: E402
import numpy as np  # noqa: E402

app._encode = lambda texts: [(lambda v: v / np.linalg.norm(v))(np.random.default_rng(
    int(hashlib.md5(t.encode()).hexdigest()[:8], 16)).normal(size=64)) for t in texts]
os.makedirs(app.AGENTS, exist_ok=True)
agent = app.create({**app.BLANK, "name": "Pizzería", "threshold": 0.9, "pii_redaction": ["phone"],
    "intents": [{"name": "pedir", "examples": ["quiero una muzzarella, mi tel +54 9 11 5555-4444"]}],
    "slots": [{"name": "nombre"}, {"name": "donde"}],
    "flows": [{"name": "pedido", "trigger": "pedir", "steps": [{"type": "message", "text": "Anotado tu pedido"}]}],
    "fallback": "No entendí, ¿me lo escribís?",
    "voice": {"asr": {"provider": "openai"}},
    "ai": {"provider": "openai", "url": FAKE + "/v1", "model": "gpt-test", "vision": True},
    "channels": {"whatsapp": {"enabled": True, "phone_number_id": "111",
                              "templates": [{"name": "retomar", "language": "es", "params": ["nombre"], "category": "utility"}]},
                 "telegram": {"enabled": True}}})
AID = agent["id"]
for name, value in {"WHATSAPP_TOKEN": "EAAtoken-secreto", "WHATSAPP_APP_SECRET": "app-secret", "TELEGRAM_TOKEN": "123456:ABC-tg_token",
                    "TELEGRAM_WEBHOOK_SECRET": "tg-secret", "OPENAI_API_KEY": "sk-fake"}.items():
    vault.put(AID, name, value)

srv = ThreadingHTTPServer(("127.0.0.1", 0), app.Handler)
threading.Thread(target=srv.serve_forever, daemon=True).start()
BASE = "http://127.0.0.1:%d" % srv.server_address[1]


def call(method, path, body=None, headers=None, raw=None):
    data = raw if raw is not None else json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(BASE + path, data=data, method=method, headers={"Content-Type": "application/json", **(headers or {})})
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return r.status, r.read(), r.headers
    except urllib.error.HTTPError as e:
        return e.code, e.read(), e.headers


def js(method, path, body=None, headers=None):
    status, raw, _ = call(method, path, body, headers)
    return status, json.loads(raw or b"{}")


status, _, hdrs = call("POST", "/api/users", {"name": "dueña", "password": "secreta1"})
assert status == 200
COOKIE = {"Cookie": hdrs["Set-Cookie"].split(";")[0]}
for name, role in (("ana", "analyst"), ("ate", "agent")):
    assert js("POST", "/api/users", {"name": name, "password": "secreta1", "role": role}, COOKIE)[0] == 200
ANALYST = {"Authorization": "Bearer " + js("POST", "/api/users/ana/keys", {"label": "bi"}, COOKIE)[1]["key"]}
ATTEND = {"Authorization": "Bearer " + js("POST", "/api/users/ate/keys", {"label": "x"}, COOKIE)[1]["key"]}
INTEGRATION = {"Authorization": "Bearer " + js("POST", "/api/users/due%C3%B1a/keys", {"label": "cc", "scope": "integration"}, COOKIE)[1]["key"]}
FOREIGN = {"Host": "bots.example.com"}


def wa(messages):
    raw = json.dumps({"entry": [{"changes": [{"value": {"metadata": {"phone_number_id": "111"}, "messages": messages}}]}]}).encode()
    sig = "sha256=" + hmac.new(b"app-secret", raw, hashlib.sha256).hexdigest()
    return call("POST", "/api/v1/bots/%s/whatsapp" % AID, raw=raw, headers={"X-Hub-Signature-256": sig, **FOREIGN})[0]


def tg(update):
    return call("POST", "/api/v1/bots/%s/telegram" % AID, update, headers={"X-Telegram-Bot-Api-Secret-Token": "tg-secret", **FOREIGN})[0]


def turn(sid, n, timeout=8):
    """Espera a que la conversación tenga n mensajes de la persona y devuelve el registro."""
    end = time.time() + timeout
    while time.time() < end:
        record = app.load_session(AID, sid)
        users = [h for h in (record or {}).get("history", []) if h["from"] == "user"]
        if len(users) >= n and record["history"][-1]["from"] == "bot":
            time.sleep(0.15)
            return app.load_session(AID, sid), users[-1]
        time.sleep(0.05)
    raise AssertionError("no llegó el turno %d de %s: %s" % (n, sid, app.load_session(AID, sid)))


def sent_texts():
    out = [json.loads(c["body"]) for c in CALLS if c["method"] == "POST" and c["path"].endswith(("/messages", "/sendMessage"))]
    return [(m.get("text") or {}).get("body") if isinstance(m.get("text"), dict) else m.get("text") for m in out]


# --- WhatsApp: nota de voz -> descarga -> ASR -> el bot contesta lo transcripto
BLOBS["/dl/m-voz"] = (OGG, "audio/ogg; codecs=opus")
assert wa([{"from": "5491112345678", "id": "w1", "type": "audio", "audio": {"id": "m-voz", "mime_type": "audio/ogg; codecs=opus", "voice": True}}]) == 200
record, user = turn("wa-5491112345678", 1)
assert user["text"] == "quiero una muzzarella, mi tel [teléfono]", user       # PII: lo guardado va tapado
media = user["media"]
assert media["type"] == "audio" and media["voice"] and media["mime"] == "audio/ogg" and media["url"].startswith("/files/%s/" % AID), media
assert media["transcript"] == "quiero una muzzarella, mi tel [teléfono]", media     # también en la transcripción
assert "Anotado tu pedido" in sent_texts(), sent_texts()
downloads = [c for c in CALLS if c["method"] == "GET"]
assert [c["path"] for c in downloads] == ["/wa/m-voz", "/dl/m-voz"] and all(c["auth"] == "Bearer EAAtoken-secreto" for c in downloads)
asr = next(c for c in CALLS if c["path"].endswith("/audio/transcriptions"))
assert asr["auth"] == "Bearer sk-fake" and b"OggS" in asr["body"]
assert any(k.startswith("asr|openai|") for k in user["usage"]), user["usage"]       # el costo del ASR, en el mismo turno
FILE_URL = media["url"]

# el archivo: solo quien ve las conversaciones del agente (no el id solo, como los archivos del bot)
assert call("GET", FILE_URL)[0] == 404
status, body, headers = call("GET", FILE_URL, headers=COOKIE)
assert status == 200 and body == OGG and headers["Content-Type"] == "audio/ogg" and headers["X-Content-Type-Options"] == "nosniff"
assert call("GET", FILE_URL, headers=ANALYST)[0] == 200 and call("GET", FILE_URL, headers=INTEGRATION)[0] == 200
assert files.listing(AID) == []                         # no aparece entre los archivos del bot
CALLS.clear()

# --- sin ASR (falla el proveedor): aviso claro y el «no entendí» del bot
DOWN.append(1)
BLOBS["/dl/m-voz2"] = (OGG, "audio/ogg")
assert wa([{"from": "5491112345678", "id": "w2", "type": "audio", "audio": {"id": "m-voz2", "mime_type": "audio/ogg"}}]) == 200
record, user = turn("wa-5491112345678", 2)
assert user["text"] == "[audio sin transcribir]" and user["media"]["error"] == "no se pudo transcribir" and user["media"]["url"]
assert "No entendí, ¿me lo escribís?" in sent_texts(), sent_texts()
DOWN.clear()
CALLS.clear()

# --- Telegram: voz por getFile -> file_path -> /file/bot<token>/…
BLOBS["/tg/file/bot123456:ABC-tg_token/voice/tg-voz.oga"] = (OGG, "application/octet-stream")
assert tg({"update_id": 1, "message": {"chat": {"id": 777}, "voice": {"file_id": "tg-voz", "mime_type": "audio/ogg", "duration": 3}}}) == 200
record, user = turn("tg-777", 1)
assert user["media"]["type"] == "audio" and user["media"]["transcript"].startswith("quiero una muzzarella") and user["intent"] == "pedir", user
assert any("/getFile?file_id=tg-voz" in c["path"] for c in CALLS)
CALLS.clear()

# --- foto con texto: se guarda, el turno recibe media (url, caption) y, con ai.vision, la IA sabe qué hay
BLOBS["/dl/m-foto"] = (JPG, "image/jpeg")
assert wa([{"from": "5491100000001", "id": "w3", "type": "image", "image": {"id": "m-foto", "mime_type": "image/jpeg", "caption": "así está el local"}}]) == 200
record, user = turn("wa-5491100000001", 1)
assert user["text"] == "así está el local" and user["media"]["type"] == "image" and user["media"]["caption"] == "así está el local"
assert user["media"]["description"].startswith("Una pizza"), user["media"]
assert record["state"]["slots"]["media"]["url"] == user["media"]["url"]          # {{ media.url }} en los pasos
vision = json.loads(next(c for c in CALLS if c["path"].endswith("/chat/completions"))["body"])
assert vision["messages"][0]["content"][1]["image_url"]["url"].startswith("data:image/jpeg;base64,")
assert any(r["text"] == "así está el local\n[imagen: Una pizza con un cartel que dice ABIERTO]" for r in record["state"]["recent"]), record["state"]["recent"]
assert app.render("{{ media.type }} {{ media.caption }}", record["state"]["slots"]) == "image así está el local"
assert call("GET", user["media"]["url"], headers=COOKIE)[1] == JPG

# documento por Telegram; un tipo que no se acepta (HTML) y uno muy grande no se guardan
BLOBS["/tg/file/bot123456:ABC-tg_token/voice/doc1.oga"] = (b"%PDF-1.4 hola", "application/pdf")
assert tg({"update_id": 2, "message": {"chat": {"id": 778}, "document": {"file_id": "doc1", "mime_type": "application/pdf", "file_name": "dni.pdf"}}}) == 200
record, user = turn("tg-778", 1)
assert user["text"] == "[documento]" and user["media"]["name"] == "dni.pdf" and user["media"]["mime"] == "application/pdf"
BLOBS["/dl/m-html"] = (b"<script>alert(1)</script>" * 20, "text/html")
assert wa([{"from": "5491100000002", "id": "w4", "type": "document", "document": {"id": "m-html", "mime_type": "text/html", "filename": "x.html"}}]) == 200
record, user = turn("wa-5491100000002", 1)
assert "url" not in user["media"] and "no se acepta" in user["media"]["error"], user["media"]
BLOBS["/dl/m-huge"] = (JPG, "image/jpeg")
assert wa([{"from": "5491100000002", "id": "w5", "type": "image", "image": {"id": "m-huge", "mime_type": "image/jpeg"}}]) == 200
record, user = turn("wa-5491100000002", 2)
assert "url" not in user["media"] and "muy grande" in user["media"]["error"], user["media"]
assert not any(c["path"] == "/dl/m-huge" for c in CALLS)       # ni se bajó
CALLS.clear()

# --- ubicación y contacto: texto que sirve para un slot, sin descargar nada
assert wa([{"from": "5491100000003", "id": "w6", "type": "location",
            "location": {"latitude": -34.6037, "longitude": -58.3816, "name": "Obelisco", "address": "Av. 9 de Julio"}}]) == 200
record, user = turn("wa-5491100000003", 1)
assert user["text"] == "Obelisco, Av. 9 de Julio (-34.6037,-58.3816)" and user["media"]["lat"] == -34.6037 and user["media"]["type"] == "location"
assert tg({"update_id": 3, "message": {"chat": {"id": 779}, "location": {"latitude": 1.5, "longitude": 2.25}}}) == 200
assert turn("tg-779", 1)[1]["text"] == "1.5,2.25"
assert tg({"update_id": 4, "message": {"chat": {"id": 779}, "contact": {"phone_number": "+54 9 11 5555-3333", "first_name": "Ana", "last_name": "Pérez"}}}) == 200
user = turn("tg-779", 2)[1]
assert user["media"]["type"] == "contacts" and user["media"]["name"] == "Ana Pérez" and user["media"]["phone"] == "[teléfono]", user
assert not [c for c in CALLS if c["method"] == "GET"]

# --- la Bandeja / Conversaciones ven media en el historial (misma API)
status, body = js("GET", "/api/v1/bots/%s/sessions/wa-5491100000001" % AID, headers=ANALYST)
assert status == 200 and next(h for h in body["history"] if h["from"] == "user")["media"]["type"] == "image"
assert body["whatsapp_window"] == {"open": True}
# media que manda la API: solo campos conocidos y url de /files/ de este agente
assert app.inbound_media(AID, {"type": "image", "url": "https://evil.example/x.png", "extra": 1, "size": True}) == {"type": "image"}

# --- retención: borrar la conversación borra sus archivos
fid = FILE_URL.rsplit("/", 1)[1]
assert files.session_of(AID, fid) == "wa-5491112345678"
assert js("DELETE", "/api/v1/bots/%s/sessions/wa-5491112345678" % AID, headers=COOKIE)[0] == 200
assert files.session_of(AID, fid) is None and call("GET", FILE_URL, headers=COOKIE)[0] == 404
photo = app.load_session(AID, "wa-5491100000001")
photo_id = next(h for h in photo["history"] if h["from"] == "user")["media"]["file"]
db.q("UPDATE sessions SET updated = '2000-01-01T00:00:00' WHERE agent_id = ? AND session_id = 'wa-5491100000001'", (AID,))
agent = app.load(AID)
agent["retention_days"] = 30
app.store(agent)
app.cleanup()
assert app.load_session(AID, "wa-5491100000001") is None and files.session_of(AID, photo_id) is None
assert files.session_of(AID, next(h for h in app.load_session(AID, "tg-778")["history"] if h["from"] == "user")["media"]["file"]) == "tg-778"
CALLS.clear()

# --- plantilla fuera de las 24 h: Bandeja
assert wa([{"from": "5491100000009", "id": "w9", "type": "text", "text": {"body": "hola"}}]) == 200
record, _ = turn("wa-5491100000009", 1)
record["last_inbound"] = time.time() - 25 * 3600
record["state"]["slots"]["nombre"] = "Ana"
app.save_session(AID, record)
SID = "/api/agents/%s/sessions/wa-5491100000009/reply" % AID
CALLS.clear()
status, body = js("POST", SID, {"text": "¿seguís ahí?"}, COOKIE)
assert status == 409 and body["code"] == "template_required" and body["templates"][0]["name"] == "retomar", body
assert not CALLS                                           # no se intentó mandar el texto (131047)
assert js("GET", "/api/v1/bots/%s/sessions/wa-5491100000009" % AID, headers=COOKIE)[1]["whatsapp_window"]["open"] is False
assert js("POST", SID, {"template": {"name": "otra"}}, COOKIE)[1]["code"] == "template_invalid"
status, body = js("POST", SID, {"template": {"name": "retomar", "params": ["Anita"]}}, COOKIE)
assert status == 200, body
payload = json.loads(next(c for c in CALLS if c["path"] == "/wa/111/messages")["body"])
assert payload["type"] == "template" and payload["template"]["name"] == "retomar" and payload["template"]["language"]["code"] == "es"
assert payload["template"]["components"] == [{"type": "body", "parameters": [{"type": "text", "text": "Anita"}]}]
last = body["history"][-1]
assert last["from"] == "human" and last["text"] == "[retomar: Anita]" and last["template"]["name"] == "retomar"
CALLS.clear()

# --- contact center: sin plantilla -> 409; con plantilla (params de los slots) -> sale
CC = "/api/v1/bots/%s/sessions/wa-5491100000009/messages" % AID
status, body = js("POST", CC, {"text": "hola"}, INTEGRATION)
assert status == 409 and body["code"] == "template_required"
status, body = js("POST", CC, {"template": {"name": "retomar"}, "from_name": "Lucía"}, INTEGRATION)
assert status == 200 and body["template"] == "retomar", body
payload = json.loads(next(c for c in CALLS if c["path"] == "/wa/111/messages")["body"])
assert payload["template"]["components"][0]["parameters"][0]["text"] == "Ana"
# la persona contesta: la ventana se abre y se le escribe normal
assert wa([{"from": "5491100000009", "id": "w10", "type": "text", "text": {"body": "sí, acá estoy"}}]) == 200
end = time.time() + 5
while not app.outbound.in_window(app.load_session(AID, "wa-5491100000009")) and time.time() < end:
    time.sleep(0.05)
CALLS.clear()
assert js("POST", SID, {"text": "¡genial!"}, COOKIE)[0] == 200
end = time.time() + 5
while "¡genial!" not in sent_texts() and time.time() < end:
    time.sleep(0.05)
assert "¡genial!" in sent_texts(), sent_texts()

# --- estado de los envíos: POST /outbound devuelve el id; GET uno y la lista; roles
status, body = js("POST", "/api/v1/bots/%s/outbound" % AID, {"channel": "whatsapp", "to": "+5491166667777", "template": "retomar",
                                                              "data": {"nombre": "Beto"}}, COOKIE)
assert status == 200 and body["status"] == "sent", body
OID = body["id"]
status, one = js("GET", "/api/v1/bots/%s/outbound/%d" % (AID, OID), headers=ANALYST)
assert status == 200 and one["status"] == "sent" and one["to"] == "5491166667777" and one["message_id"] and one["created"] and one["sent_at"], one
raw = json.dumps({"entry": [{"changes": [{"value": {"metadata": {"phone_number_id": "111"},
                                                     "statuses": [{"id": one["message_id"], "status": "delivered"}]}}]}]}).encode()
call("POST", "/api/v1/bots/%s/whatsapp" % AID, raw=raw, headers={"X-Hub-Signature-256": "sha256=" + hmac.new(b"app-secret", raw, hashlib.sha256).hexdigest(), **FOREIGN})
assert js("GET", "/api/v1/bots/%s/outbound/%d" % (AID, OID), headers=INTEGRATION)[1]["status"] == "delivered"
status, listed = js("GET", "/api/v1/bots/%s/outbound?to=%%2B5491166667777&status=delivered&from=2000-01-01&to_date=2999-12-31" % AID, headers=ANALYST)
assert status == 200 and [r["id"] for r in listed["outbound"]] == [OID], listed
assert js("GET", "/api/v1/bots/%s/outbound?status=delivered&from=2999-01-01" % AID, headers=ANALYST)[1]["outbound"] == []
assert js("GET", "/api/v1/bots/%s/outbound?status=nada" % AID, headers=ANALYST)[0] == 400
assert js("GET", "/api/v1/bots/%s/outbound/999999" % AID, headers=ANALYST)[0] == 404
assert js("GET", "/api/v1/bots/%s/outbound/%d" % (AID, OID), headers=ATTEND)[0] == 403
assert js("GET", "/api/v1/bots/%s/outbound/%d" % (AID, OID))[0] == 401
assert js("POST", "/api/v1/bots/%s/outbound" % AID, {"channel": "whatsapp", "to": "+5491166667777"}, ANALYST)[0] == 403
print("ok: media entrante (audio, foto, documento, ubicación, contacto), plantillas fuera de las 24 h y estado de envíos")
