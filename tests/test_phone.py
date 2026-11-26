"""Teléfono (Twilio y jambonz) con pedidos falsos del proveedor (nada sale a internet):  .venv/bin/python tests/test_phone.py"""
import base64
import hashlib
import os
import hmac
import json
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from http.server import ThreadingHTTPServer

import support
DATA = support.temp_data()

from parla import server as app, vault, phone, voice  # noqa: E402
import numpy as np  # noqa: E402

app._encode = lambda texts: [(lambda v: v / np.linalg.norm(v))(np.random.default_rng(
    int(hashlib.md5(t.encode()).hexdigest()[:8], 16)).normal(size=64)) for t in texts]
os.makedirs(app.AGENTS, exist_ok=True)
voice.speak = lambda text, language="es", keep=True, **kw: b"RIFF-fake-" + text.encode()     # sin piper
agent = app.create({**app.BLANK, "name": "Pizzería", "threshold": 0.9,
    "intents": [{"name": "saludar", "examples": ["hola"]}, {"name": "dni", "examples": ["mi documento"]},
                {"name": "chau", "examples": ["chau"]}, {"name": "archivo", "examples": ["precios"]}],
    "entities": [{"name": "numero", "kind": "number", "regex": r"\b\d+\b", "values": [], "color": 0}],
    "slots": [{"name": "gusto"}, {"name": "dni", "entity": "numero"}],
    "flows": [{"name": "inicio", "trigger": "__start__", "steps": [{"type": "message", "text": "¡Hola! 👋 Soy **Pizzi**. Mirá https://pizza.example.com"}]},
              {"name": "saludo", "trigger": "saludar", "steps": [
                  {"type": "ask", "slot": "gusto", "text": "¿Qué gusto?", "buttons": [
                      {"label": "Muzzarella", "value": "muzza"}, {"label": "Fugazza", "value": "fuga"}]},
                  {"type": "message", "text": "Elegiste {{ gusto }}"}, {"type": "set", "slot": "gusto", "mode": "clear"}]},
              {"name": "documento", "trigger": "dni", "steps": [
                  {"type": "ask", "slot": "dni", "text": "Decime tu DNI"}, {"type": "message", "text": "DNI {{ dni }}"},
                  {"type": "set", "slot": "dni", "mode": "clear"}]},
              {"name": "fin", "trigger": "chau", "steps": [{"type": "message", "text": "¡Chau!"}, {"type": "end"}]}],
    "channels": {"public_url": "https://bots.example.com",
                 "phone": {"enabled": True, "provider": "twilio", "language": "es-AR", "voice": "Polly.Mia",
                           "handoff_to": "+5491100000000"}}})
AID = agent["id"]
vault.put(AID, "TWILIO_AUTH_TOKEN", "tw-token")

srv = ThreadingHTTPServer(("127.0.0.1", 0), app.Handler)
threading.Thread(target=srv.serve_forever, daemon=True).start()
BASE = "http://127.0.0.1:%d" % srv.server_address[1]
FOREIGN = {"Host": "bots.example.com"}

# con un usuario creado, todo pide sesión... menos las llamadas firmadas
assert urllib.request.urlopen(urllib.request.Request(BASE + "/api/users", json.dumps({"name": "dueña", "password": "secreta1"}).encode(),
                                                     {"Content-Type": "application/json"})).status == 200


def call(method, path, raw=None, headers=None):
    req = urllib.request.Request(BASE + path, data=raw, method=method, headers={**FOREIGN, **(headers or {})})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, r.read(), r.headers
    except urllib.error.HTTPError as e:
        return e.code, e.read(), e.headers


def set_phone(**changes):
    a = app.load(AID)
    a["channels"]["phone"].update(changes)
    app.store(a)


# ---------- unidades ----------
assert phone.speakable("¡Hola! 👋🏽 Soy **Pizzi**. Mirá [la carta](https://x.com/c) y https://pizza.example.com ⚠") == "¡Hola! Soy Pizzi. Mirá la carta y"
assert phone.speakable("# Título\n- uno\n* dos\n1️⃣ `código` 20°") == "Título\nuno\ndos\n1 código 20°"
assert phone.menu([{"label": "A", "value": "a"}, {"label": "B", "value": "b"}], "en") == "Press 1 for A, 2 for B."
assert phone.menu([{"label": "A", "value": "a"}], "pt-BR") == "Digite 1 para A."
assert phone.lines([{"text": "precios.pdf", "buttons": [], "file": {"name": "precios.pdf"}}], "es") == [phone.FILE_NOTE["es"]]
long = " ".join("Frase número %d." % i for i in range(60))
assert all(len(c) <= 320 for c in phone.chunks(long)) and len(phone.chunks(long)) > 2
# audio firmado: vale para ese agente y hasta que vence
token = phone.audio_token(AID, "Hola", "es")
assert phone.audio_text(AID, token) == ("Hola", "es")
assert phone.audio_text("ffffffff", token) is None
assert phone.audio_text(AID, token, now=time.time() + phone.AUDIO_TTL + 5) is None
assert phone.audio_text(AID, token[:-2] + ("AA" if token[-2:] != "AA" else "BB")) is None
assert call("GET", "/api/v1/bots/%s/phone/audio/%s.wav" % (AID, token))[:2] == (200, b"RIFF-fake-Hola")
expired = phone.audio_token(AID, "Hola", "es", now=time.time() - phone.AUDIO_TTL - 5)
assert call("GET", "/api/v1/bots/%s/phone/audio/%s.wav" % (AID, expired))[0] == 403
assert call("GET", "/api/v1/bots/%s/phone/audio/x.y.wav" % AID)[0] == 403


# ---------- Twilio ----------
def tw(action, params, token="tw-token", sign=True):
    path = "/api/v1/bots/%s/phone/twilio%s" % (AID, "/" + action if action else "")
    url = "https://bots.example.com" + path
    sig = base64.b64encode(hmac.new(token.encode(), (url + "".join(k + v for k, v in sorted(params.items()))).encode(), hashlib.sha1).digest()).decode()
    s, body, hdrs = call("POST", path, urllib.parse.urlencode(params).encode(),
                         {"Content-Type": "application/x-www-form-urlencoded", **({"X-Twilio-Signature": sig} if sign else {})})
    return s, body.decode()


CALL = {"CallSid": "CA0001", "From": "+5491112345678", "To": "+5491199999999"}
assert tw("", CALL, token="otro")[0] == 403
assert tw("", CALL, sign=False)[0] == 403
# primer turno: el saludo (sin emoji, Markdown ni link) dentro de un Gather con voz y teclado
s, xml = tw("", CALL)
assert s == 200 and xml.startswith('<?xml version="1.0" encoding="UTF-8"?><Response><Gather '), xml
assert 'input="speech dtmf"' in xml and 'language="es-AR"' in xml and 'speechTimeout="auto"' in xml and 'actionOnEmptyResult="true"' in xml
assert 'action="https://bots.example.com/api/v1/bots/%s/phone/twilio/gather"' % AID in xml and 'finishOnKey="#"' in xml
assert '<Say voice="Polly.Mia" language="es-AR">¡Hola! Soy Pizzi. Mirá</Say></Gather>' in xml, xml
record = app.load_session(AID, "call-CA0001")
assert record["channel"] == "phone" and record["environment"] == "production"
# lo que dijo (SpeechResult) -> la próxima pregunta, con el menú de teclas
s, xml = tw("gather", dict(CALL, SpeechResult="hola"))
assert "¿Qué gusto? Marcá 1 para Muzzarella, 2 para Fugazza.</Say>" in xml and 'numDigits="1"' in xml, xml
assert "Muzzarella" in re.search(r'hints="([^"]*)"', xml).group(1)
# tecla 2 -> el segundo botón
s, xml = tw("gather", dict(CALL, Digits="2"))
assert "Elegiste fuga</Say>" in xml and "numDigits" not in xml, xml
# silencio: repite lo último; a la tercera corta
s, xml = tw("gather", CALL)
assert "Elegiste fuga</Say>" in xml and "<Gather" in xml
tw("gather", CALL)
s, xml = tw("gather", CALL)
assert phone.BYE["es"] in xml and xml.endswith("<Hangup/></Response>") and app.load_session(AID, "call-CA0001")["ended"]

# DNI por teclado: los dígitos van tal cual como respuesta
CALL2 = dict(CALL, CallSid="CA0002")
tw("", CALL2)
assert "Decime tu DNI" in tw("gather", dict(CALL2, SpeechResult="mi documento"))[1]
assert "DNI 30123456</Say>" in tw("gather", dict(CALL2, Digits="30123456"))[1]
# un paso «end» corta la llamada
s, xml = tw("gather", dict(CALL2, SpeechResult="chau"))
assert "¡Chau!</Say><Hangup/>" in xml and app.load_session(AID, "call-CA0002")["ended"], xml
# pasar con una persona -> Dial al número configurado; queda en la Bandeja
CALL3 = dict(CALL, CallSid="CA0003")
tw("", CALL3)
s, xml = tw("gather", dict(CALL3, SpeechResult="quiero hablar con una persona"))
assert "<Dial><Number>+5491100000000</Number></Dial><Hangup/>" in xml, xml
assert [x["sessionId"] for x in app.inbox(AID)["sessions"]] == ["call-CA0003"]
assert any(h["text"] == "Transferida a +5491100000000" for h in app.load_session(AID, "call-CA0003")["history"])
# fin de la llamada (status callback) -> la conversación termina
assert tw("status", dict(CALL3, CallStatus="completed"))[0] == 200 and app.load_session(AID, "call-CA0003")["ended"]
# una persona toma la llamada desde la Bandeja: al próximo silencio se transfiere a una dirección SIP
set_phone(handoff_to="sip:mesa@pbx.example.com")
CALL4 = dict(CALL, CallSid="CA0004")
tw("", CALL4)
app.human(AID, "call-CA0004", "take", "", "Ana")
assert "<Dial><Sip>sip:mesa@pbx.example.com</Sip></Dial>" in tw("gather", CALL4)[1]
# un archivo se avisa; tts «parla»: <Play> con direcciones firmadas que se pueden bajar
set_phone(tts="parla")
CALL5 = dict(CALL, CallSid="CA0005")
s, xml = tw("", CALL5)
urls = re.findall(r"<Play>([^<]+)</Play>", xml)
assert urls and all(u.startswith("https://bots.example.com/api/v1/bots/%s/phone/audio/" % AID) for u in urls), xml
assert call("GET", urllib.parse.urlsplit(urls[0]).path)[:2] == (200, "RIFF-fake-¡Hola! Soy Pizzi. Mirá".encode())
app.load(AID)
assert phone.FILE_NOTE["es"] in phone.lines([{"text": "Acá va", "buttons": [], "file": {"name": "x.pdf"}}], "es")[0]
set_phone(tts="provider")
# otro proveedor u apagado: 403
set_phone(provider="jambonz")
assert tw("", dict(CALL, CallSid="CA0006"))[0] == 403


# ---------- jambonz ----------
def jz(action, payload, secret="jz-secret", stamp=None, auth=None):
    raw = json.dumps(payload).encode()
    t = str(int(stamp or time.time()))
    headers = {"Content-Type": "application/json"}
    if secret:
        headers["Jambonz-Signature"] = "t=%s,v1=%s" % (t, hmac.new(secret.encode(), t.encode() + b"." + raw, hashlib.sha256).hexdigest())
    if auth:
        headers["Authorization"] = "Basic " + base64.b64encode(auth.encode()).decode()
    s, body, _ = call("POST", "/api/v1/bots/%s/phone/jambonz%s" % (AID, "/" + action if action else ""), raw, headers)
    return s, json.loads(body) if s == 200 and body else body


J = {"call_sid": "6f1e2d3c-0000-4000-8000-000000000001", "from": "+5491112345678", "to": "+5491199999999", "direction": "inbound"}
assert jz("", J)[0] == 403                                   # sin claves cargadas no pasa nada
vault.put(AID, "JAMBONZ_WEBHOOK_SECRET", "jz-secret")
assert jz("", J, secret="otro")[0] == 403
assert jz("", J, secret=None)[0] == 403
assert jz("", J, stamp=time.time() - 3600)[0] == 403        # firma vieja
s, verbs = jz("", J)
assert s == 200 and len(verbs) == 1 and verbs[0]["verb"] == "gather", verbs
g = verbs[0]
assert g["input"] == ["speech", "digits"] and g["bargein"] and g["dtmfBargein"] and g["finishOnKey"] == "#"
assert g["actionHook"] == "https://bots.example.com/api/v1/bots/%s/phone/jambonz/gather" % AID
assert g["recognizer"]["language"] == "es-AR" and g["say"]["text"] == "¡Hola! Soy Pizzi. Mirá"
assert g["say"]["synthesizer"] == {"vendor": "default", "language": "es-AR", "voice": "Polly.Mia"}
speech = lambda text: dict(J, reason="speechDetected", speech={"is_final": True, "alternatives": [{"transcript": text, "confidence": 0.9}]})
s, verbs = jz("gather", speech("hola"))
assert verbs[0]["numDigits"] == 1 and verbs[0]["say"]["text"] == "¿Qué gusto? Marcá 1 para Muzzarella, 2 para Fugazza."
s, verbs = jz("gather", dict(J, reason="dtmfDetected", digits="1"))
assert verbs[0]["say"]["text"] == "Elegiste muzza", verbs
s, verbs = jz("gather", speech("quiero hablar con una persona"))
assert verbs[-2:] == [{"verb": "dial", "answerOnBridge": True, "target": [{"type": "sip", "sipUri": "sip:mesa@pbx.example.com"}]},
                      {"verb": "hangup"}] and verbs[0]["verb"] == "say", verbs
assert jz("status", dict(J, call_status="completed"))[0] == 200 and app.load_session(AID, "call-" + J["call_sid"])["ended"]
J2 = dict(J, call_sid="6f1e2d3c-0000-4000-8000-000000000002")
set_phone(language="en-US")          # el agente habla español: la variante del proveedor sale por defecto
assert jz("", J2)[1][0]["recognizer"]["language"] == "es-US"
s, verbs = jz("gather", dict(speech("chau"), call_sid=J2["call_sid"]))
assert verbs == [{"verb": "say", "text": "¡Chau!", "synthesizer": {"vendor": "default", "language": "es-US", "voice": "Polly.Mia"}}, {"verb": "hangup"}], verbs
# HTTP basic además de la firma: tienen que dar bien las dos; el actionHook lleva las credenciales
vault.put(AID, "JAMBONZ_BASIC_USER", "parla")
vault.put(AID, "JAMBONZ_BASIC_PASSWORD", "clave-larga")
J3 = dict(J, call_sid="6f1e2d3c-0000-4000-8000-000000000003")
assert jz("", J3)[0] == 403
assert jz("", J3, auth="parla:otra")[0] == 403
s, verbs = jz("", J3, auth="parla:clave-larga")
assert verbs[0]["actionHook"]["username"] == "parla" and verbs[0]["actionHook"]["url"].endswith("/phone/jambonz/gather")
vault.delete(AID, "JAMBONZ_WEBHOOK_SECRET")
assert jz("", J3, secret=None, auth="parla:clave-larga")[0] == 200      # solo basic (jambonz propio)

# ---------- Canales y MCP ----------
cookie = urllib.request.urlopen(urllib.request.Request(BASE + "/api/auth/login", json.dumps({"name": "dueña", "password": "secreta1"}).encode(),
                                                       {"Content-Type": "application/json"})).headers["Set-Cookie"].split(";")[0]
info = json.loads(urllib.request.urlopen(urllib.request.Request(BASE + "/api/agents/%s/channels" % AID, headers={"Cookie": cookie})).read())["phone"]
assert info["provider"] == "jambonz" and info["webhook"] == "https://bots.example.com/api/v1/bots/%s/phone/jambonz" % AID
assert info["status_webhook"].endswith("/phone/jambonz/status") and info["secrets"]["JAMBONZ_BASIC_USER"] and info["status"]["last_in"]
from parla import mcp_server  # noqa: E402
base = {k: app.load(AID)[k] for k in ("name", "intents", "entities", "slots", "flows")}
errors = mcp_server.validate({**base, "channels": {"phone": {"enabled": True, "provider": "twilio", "handoff_to": "+541100"}}})[1]
assert not errors, errors
assert mcp_server.validate({**base, "channels": {"phone": {"provider": "asterisk"}}})[1]
assert mcp_server.validate({**base, "channels": {"phone": {"auth_token": "x"}}})[1]

srv.shutdown()
print("teléfono ok")
