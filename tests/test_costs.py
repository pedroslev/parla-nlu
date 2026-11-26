"""Costos por conversación (parla/costs.py): uso medido de cada proveedor contra servidores falsos (tokens de Claude,
OpenAI, Gemini y Ollama; segundos de audio; caracteres de voz), minutos de teléfono del status callback, WhatsApp
(servicio y plantillas) y Telegram; la suma por conversación y por día; la tabla de precios (solo el dueño) y el
recálculo hacia atrás; el reporte y la API agrupados; las métricas; que la cuenta no frene el turno; y el resumen de
la IA del handoff en segundo plano (el webhook lo espera, el turno no). Nunca llama a una API real.
Uso: .venv/bin/python tests/test_costs.py"""
import base64
import hashlib
import hmac
import io
import json
import os
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import wave
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import support
DATA = support.temp_data()
os.environ["PARLA_METRICS"] = "1"
KEY = "sk-test-0123456789"
SLOW = {"summary": 0.0}            # segundos que tarda el resumen de la IA
HOOKS = []


def wav(seconds, rate=16000):
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1), w.setsampwidth(2), w.setframerate(rate)
        w.writeframes(b"\x01\x00" * int(seconds * rate))
    return buf.getvalue()


class Fake(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def send(self, body, ctype="application/json"):
        raw = body if isinstance(body, bytes) else json.dumps(body).encode()
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_POST(self):
        raw = self.rfile.read(int(self.headers.get("Content-Length") or 0))
        path = urllib.parse.urlsplit(self.path).path
        body = json.loads(raw) if raw[:1] == b"{" else {}
        if path.startswith("/hook"):
            HOOKS.append(json.loads(raw))
            return self.send({})
        if path == "/v1/messages":          # Anthropic: entrada sin caché + escritura de caché + lectura de caché
            return self.send({"id": "msg_1", "type": "message", "role": "assistant", "model": body["model"], "stop_reason": "end_turn",
                              "stop_sequence": None, "content": [{"type": "text", "text": "hola"}],
                              "usage": {"input_tokens": 7, "cache_creation_input_tokens": 3, "cache_read_input_tokens": 5, "output_tokens": 4}})
        if path.endswith("/chat/completions"):
            system = " ".join(m["content"] for m in body["messages"] if m["role"] == "system")
            if "Resumí" in system:
                time.sleep(SLOW["summary"])
                text = "Quiere reclamar por su router."
            else:
                text = json.dumps({"respuesta": "Hola", "text": "Hola", "intent": None, "opcion": None})
            return self.send({"choices": [{"message": {"content": text}}],
                              "usage": {"prompt_tokens": 100, "completion_tokens": 20, "prompt_tokens_details": {"cached_tokens": 40}}})
        if ":generateContent" in path:
            return self.send({"candidates": [{"content": {"parts": [{"text": "hola"}]}, "finishReason": "STOP"}],
                              "usageMetadata": {"promptTokenCount": 50, "cachedContentTokenCount": 10, "candidatesTokenCount": 6, "thoughtsTokenCount": 9}})
        if path == "/api/chat":             # Ollama
            return self.send({"message": {"content": "hola"}, "done": True, "prompt_eval_count": 30, "eval_count": 12,
                              "prompt_eval_duration": 1_800_000_000, "eval_duration": 1_800_000_000})
        if path == "/v1/listen":            # Deepgram informa la duración
            return self.send({"metadata": {"duration": 12.5}, "results": {"channels": [{"alternatives": [{"transcript": "dos muzzas"}]}]}})
        if path == "/v1/audio/transcriptions":
            return self.send({"text": "una muzza", "usage": {"type": "duration", "seconds": 9}})
        if path == "/v1/speech-to-text":    # ElevenLabs no la informa: sale del encabezado WAV
            return self.send({"text": "una napo"})
        if path.startswith("/v1/text-to-speech/"):
            return self.send(wav(0.1), "audio/wav")
        if path.startswith("/wa/"):
            return self.send({"messages": [{"id": "wamid.%d" % time.time_ns()}]})
        if path.startswith("/tg/"):
            return self.send({"ok": True, "result": {"message_id": 1}})
        self.send_response(404)
        self.end_headers()


fake = ThreadingHTTPServer(("127.0.0.1", 0), Fake)
threading.Thread(target=fake.serve_forever, daemon=True).start()
FAKE = "http://127.0.0.1:%d" % fake.server_address[1]
os.environ.update(PARLA_WHATSAPP_API=FAKE + "/wa", PARLA_TELEGRAM_API=FAKE + "/tg", PARLA_ANTHROPIC_BASE_URL=FAKE, PARLA_GEMINI_BASE_URL=FAKE,
                  PARLA_DEEPGRAM_BASE_URL=FAKE, PARLA_OPENAI_BASE_URL=FAKE, PARLA_ELEVENLABS_BASE_URL=FAKE)

from parla import server as app, costs, db, handoff, llm, outbound, channels, telemetry, vault, voice  # noqa: E402
import numpy as np  # noqa: E402

app._encode = lambda texts: [(lambda v: v / np.linalg.norm(v))(np.random.default_rng(
    int(hashlib.md5(t.encode()).hexdigest()[:8], 16)).normal(size=64)) for t in texts]
os.makedirs(app.AGENTS, exist_ok=True)


def flush():
    """Las escrituras de la cuenta no se esperan: una escritura que sí espera pasa después de todas las anteriores."""
    db.q("DELETE FROM usage WHERE 0")


def rows(sid=None):
    where, args = ("session_id = ?", (sid,)) if sid is not None else ("1", ())
    return {(k, p, m): q for k, p, m, q in db.q("SELECT kind, provider, model, sum(qty) FROM usage WHERE %s GROUP BY 1, 2, 3" % where, args)}


# ---------- 1. cada proveedor informa lo suyo ----------
with costs.scope("aaaaaaaa", "unit", "api") as spent:
    llm.chat({"provider": "anthropic", "model": "claude-opus-5-5", "api_key": KEY}, [{"role": "user", "content": "hola"}])
    llm.chat({"provider": "openai_compatible", "url": FAKE + "/v1", "model": "qwen"}, [{"role": "user", "content": "hola"}])
    llm.chat({"provider": "gemini", "model": "gemini-3.8-flash", "api_key": KEY, "url": FAKE}, [{"role": "user", "content": "hola"}])
    llm.chat({"provider": "ollama", "url": FAKE, "model": "qwen2.5:0.5b"}, [{"role": "user", "content": "hola"}])
    voice.transcribe(wav(0.5), "audio/wav", "es", None, {"provider": "deepgram", "api_key": KEY})
    voice.transcribe(wav(0.5), "audio/wav", "es", None, {"provider": "openai", "api_key": KEY})
    voice.transcribe(wav(3.0), "audio/wav", "es", None, {"provider": "elevenlabs", "api_key": KEY})
    voice.speak("Hola, ¿cómo estás?", "es", keep=False, tts={"provider": "elevenlabs", "api_key": KEY, "voice": "v1", "model": "eleven_flash_v2_5"})
    got = costs.totals(spent.take())
assert spent.take() == []
expect = {"llm_input|anthropic|claude-opus-5-5": 10, "llm_cached|anthropic|claude-opus-5-5": 5, "llm_output|anthropic|claude-opus-5-5": 4,
          "llm_input|openai_compatible|qwen": 60, "llm_cached|openai_compatible|qwen": 40, "llm_output|openai_compatible|qwen": 20,
          "llm_input|gemini|gemini-3.8-flash": 40, "llm_cached|gemini|gemini-3.8-flash": 10, "llm_output|gemini|gemini-3.8-flash": 15,
          "llm_input|ollama|qwen2.5:0.5b": 30, "llm_output|ollama|qwen2.5:0.5b": 12, "llm_compute|ollama|qwen2.5:0.5b": 0.001,
          "asr|deepgram|nova-3": round(12.5 / 60, 6), "asr|openai|gpt-4o-mini-transcribe": 0.15, "asr|elevenlabs|scribe_v3": 0.05,
          "tts|elevenlabs|eleven_flash_v2_5": len("Hola, ¿cómo estás?")}
assert got == expect, (got, expect)
flush()
assert rows("unit")[("llm_input", "anthropic", "claude-opus-5-5")] == 10
prices = costs.table()
opus = costs.cost_of(prices, "llm_input", "anthropic", "claude-opus-5-5", 1_000_000)
assert opus == 4.0 and costs.cost_of(prices, "llm_output", "anthropic", "claude-opus-5-5", 1_000_000) == 20.0
assert costs.cost_of(prices, "tts", "deepgram", "aura-2-celeste-es", 1_000_000) == 30.0     # patrón «aura-2-*»
assert costs.cost_of(prices, "llm_cached", "anthropic", "claude-haiku-5-5", 1000) is None   # sin verificar: vacío
assert all(r["source"] and r["checked"] for r in costs.DEFAULTS if r["price"] and r["source"] != "local"), "precio de fábrica sin fuente"
print("ok: uso de Claude, OpenAI, Gemini, Ollama, ASR y TTS")

# ---------- 2. un agente de verdad por HTTP: turnos, teléfono, WhatsApp, Telegram ----------
agent = app.create({**app.BLANK, "name": "Costos", "threshold": 0.5,
    "ai": {"enabled": True, "provider": "openai_compatible", "url": FAKE + "/v1", "model": "qwen"},
    "intents": [{"name": "reclamo", "examples": ["tengo un reclamo", "quiero hacer un reclamo"]},
                {"name": "saludo", "examples": ["buen día", "buenas tardes"]}],
    "slots": [{"name": "producto"}],
    "flows": [{"name": "Reclamo", "trigger": "reclamo", "steps": [{"type": "set", "slot": "producto", "mode": "text", "text": "router"},
                                                                  {"type": "handoff", "text": "Te paso con alguien", "reason": "reclamo"}]},
              {"name": "Saludo", "trigger": "saludo", "steps": [{"type": "message", "text": "¡Hola!"}]}],
    "channels": {"public_url": "https://bots.example.com", "whatsapp": {"enabled": True, "phone_number_id": "111",
                 "templates": [{"name": "recordatorio", "language": "es", "category": "UTILITY"}]}, "telegram": {"enabled": True},
                 "phone": {"enabled": True, "provider": "twilio", "handoff_to": "sip:cola@cc.example.com"}},
    "handoff": {"mode": "external", "phone": {"headers": ["summary"]}},
    "webhooks": [{"url": FAKE + "/hook", "events": ["handoff.requested"], "secret_name": "CC_SECRET"}]})
AID = agent["id"]
for name, value in {"CC_SECRET": "s3cr3t", "WHATSAPP_TOKEN": "EAAtoken", "TELEGRAM_TOKEN": "123456:ABC-tg", "TWILIO_AUTH_TOKEN": "tw-token"}.items():
    vault.put(AID, name, value)
app.train(AID)

srv = ThreadingHTTPServer(("127.0.0.1", 0), app.Handler)
threading.Thread(target=srv.serve_forever, daemon=True).start()
BASE = "http://127.0.0.1:%d" % srv.server_address[1]


def js(method, path, body=None, headers=None):
    req = urllib.request.Request(BASE + path, data=json.dumps(body).encode() if body is not None else None, method=method,
                                 headers={"Content-Type": "application/json", **(headers or {})})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            raw = r.read()
            return r.status, json.loads(raw) if r.headers.get("Content-Type", "").startswith("application/json") else raw.decode()
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}")


assert js("POST", "/api/users", {"name": "duena", "password": "secreta1"})[0] == 200
import http.cookiejar  # noqa: E402
jar = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
jar.open(urllib.request.Request(BASE + "/api/auth/login", data=json.dumps({"name": "duena", "password": "secreta1"}).encode(),
                                headers={"Content-Type": "application/json"}, method="POST")).read()
with jar.open(urllib.request.Request(BASE + "/api/users/duena/keys", data=b'{"label": "t"}', headers={"Content-Type": "application/json"}, method="POST")) as r:
    OWNER = {"Authorization": "Bearer " + json.loads(r.read())["key"]}
for name, role in (("edi", "editor"), ("ana", "analyst"), ("ate", "agent")):
    assert js("POST", "/api/users", {"name": name, "password": "secreta1", "role": role}, OWNER)[0] == 200
key = lambda name, **extra: {"Authorization": "Bearer " + js("POST", "/api/users/%s/keys" % name, {"label": "x", **extra}, OWNER)[1]["key"]}
EDITOR, ANALYST, ATTEND, INTEG = key("edi"), key("ana"), key("ate"), key("edi", scope="integration")
V1 = "/api/v1/bots/%s" % AID

s, r = js("POST", V1 + "/events", {"sessionId": "c1", "text": "algo que ningún flujo entiende", "channel": "api"}, OWNER)
assert s == 200, r
s, r = js("POST", V1 + "/events", {"sessionId": "c1", "text": "buen día", "channel": "api"}, OWNER)
assert s == 200 and r["messages"] == ["¡Hola!"], r
flush()
rec = app.load_session(AID, "c1")
users = [h for h in rec["history"] if h["from"] == "user"]
assert users[0]["usage"]["llm_input|openai_compatible|qwen"] >= 60 and users[0]["usage"]["turn|parla|engine"] == 1, users[0]
assert rec["usage"]["turn|parla|engine"] == 2 and rec["usage"]["llm_output|openai_compatible|qwen"] >= 20, rec["usage"]
s, detail = js("GET", V1 + "/sessions/c1", headers=ANALYST)
assert s == 200 and detail["usage"]["estimated"] and detail["usage"]["currency"] == "USD", detail.get("usage")
kinds = {(i["kind"], i["provider"]) for i in detail["usage"]["items"]}
assert ("llm_input", "openai_compatible") in kinds and ("turn", "parla") in kinds, kinds
assert not next(i for i in detail["usage"]["items"] if i["provider"] == "openai_compatible")["priced"]   # sin precio: «completá el precio»

# teléfono: los minutos salen del status callback firmado (Twilio CallDuration)
def twilio(path, params):
    url = "https://bots.example.com" + path
    sig = base64.b64encode(hmac.new(b"tw-token", (url + "".join(k + v for k, v in sorted(params.items()))).encode(), hashlib.sha1).digest()).decode()
    req = urllib.request.Request(BASE + path, data=urllib.parse.urlencode(params).encode(), method="POST",
                                 headers={"Content-Type": "application/x-www-form-urlencoded", "X-Twilio-Signature": sig})
    with urllib.request.urlopen(req, timeout=10) as r:
        return r.status


assert twilio(V1 + "/phone/twilio/status", {"CallSid": "CA1", "CallStatus": "completed", "CallDuration": "90"}) == 200
assert twilio(V1 + "/phone/twilio/status", {"CallSid": "CA2", "CallStatus": "ringing"}) == 200     # sin terminar: nada
# WhatsApp (servicio y plantilla) y Telegram
draft = app.load(AID)
channels._send(draft, "whatsapp", "wa-5491100000001", [{"text": "uno"}, {"text": "dos"}], "es")
channels._send(draft, "telegram", "tg-77", [{"text": "hola"}], "es")
sent = outbound.send(draft, "whatsapp", "5491100000002", template="recordatorio")
assert sent["via"] == "template", sent
flush()
assert rows("call-CA1") == {("phone", "twilio", "inbound"): 1.5} and rows("call-CA2") == {}
assert rows("wa-5491100000001") == {("whatsapp", "meta", "service"): 2} and rows("tg-77") == {("telegram", "telegram", "bot"): 1}
assert rows("wa-5491100000002")[("whatsapp", "meta", "template:utility")] == 1
print("ok: turnos, minutos de teléfono, WhatsApp (servicio y plantilla) y Telegram")

# ---------- 3. precios: solo el dueño; el cambio recalcula lo pasado ----------
s, table = js("GET", "/api/prices", headers=ANALYST)
assert s == 200 and table["currency"] == "USD" and any(r["kind"] == "llm_input" and r["provider"] == "anthropic" for r in table["prices"])
new = {"currency": "USD", "prices": [{"kind": "llm_input", "provider": "openai_compatible", "model": "*", "price": 1000},
                                     {"kind": "llm_output", "provider": "openai_compatible", "model": "*", "price": 2000},
                                     {"kind": "phone", "provider": "twilio", "model": "inbound", "price": 0.02},
                                     {"kind": "turn", "provider": "parla", "model": "*", "price": 30}]}
for who in (EDITOR, ANALYST, ATTEND, INTEG):
    assert js("PUT", "/api/prices", new, who)[0] == 403
assert js("PUT", "/api/prices", {"prices": [{"kind": "nada", "provider": "x"}]}, OWNER)[0] == 400
assert js("PUT", "/api/prices", {"currency": "dólar", "prices": []}, OWNER)[0] == 400
s, before = js("GET", V1 + "/costs", headers=ANALYST)
assert s == 200 and before["missing_prices"], before
s, saved = js("PUT", "/api/prices", new, OWNER)
assert s == 200 and next(r for r in saved["prices"] if r["kind"] == "phone" and r["provider"] == "twilio" and r["model"] == "inbound")["price"] == 0.02
assert any(r["kind"] == "llm_input" and r["provider"] == "anthropic" and r["default"] for r in saved["prices"])   # los de fábrica siguen
s, after = js("GET", V1 + "/costs", headers=ANALYST)
llm_used = rows("c1")
expected = (llm_used[("llm_input", "openai_compatible", "qwen")] * 1000 + llm_used[("llm_output", "openai_compatible", "qwen")] * 2000) / 1e6
turns = sum(q for (k, _, _), q in rows().items() if k == "turn")
expected += 1.5 * 0.02 + 30                                     # el costo fijo del motor, repartido entre los turnos del mes
assert abs(after["total"] - expected) < 1e-6 and after["total"] > (before["total"] or 0), (after["total"], expected)
assert abs(sum(i["cost"] for i in js("GET", V1 + "/sessions/c1", headers=ANALYST)[1]["usage"]["items"]) - (expected - 0.03 - 30 + 30 * 2 / turns)) < 1e-6
print("ok: tabla de precios (solo el dueño) y recálculo hacia atrás")

# ---------- 4. reporte: agrupado, por conversación, resueltas, campaña, CSV ----------
s, by = js("GET", V1 + "/costs?group=channel", headers=ANALYST)
assert s == 200 and {g["channel"] for g in by["groups"]} >= {"api", "phone", "whatsapp"}, by["groups"]
assert js("GET", V1 + "/costs?group=day", headers=ANALYST)[1]["groups"][0]["date"] == time.strftime("%Y-%m-%d")
providers = {(g["provider"], g["kind"]) for g in js("GET", V1 + "/costs?group=provider", headers=ANALYST)[1]["groups"]}
assert ("twilio", "phone") in providers and ("meta", "whatsapp") in providers
assert by["conversations"]["count"] >= 4 and by["conversations"]["p95"] >= by["conversations"]["median"]
assert by["top"][0]["sessionId"] == "c1" and by["resolved"]["count"] >= 1
assert js("GET", V1 + "/costs?from=2000-01-01&to=2000-01-02", headers=ANALYST)[1]["total"] == 0
assert js("GET", V1 + "/costs", headers=ATTEND)[0] == 403 and js("GET", V1 + "/costs", headers=INTEG)[0] == 403
csv_text = js("GET", "/api/agents/%s/costs?format=csv" % AID, headers=ANALYST)[1]
assert csv_text.splitlines()[0] == "day,session,channel,provider,model,kind,qty,unit,cost_usd" and "call-CA1" in csv_text
cid = js("POST", "/api/agents/%s/campaigns" % AID, {"name": "Avisos", "channel": "whatsapp", "template": "recordatorio"}, OWNER)
assert cid[0] == 200, cid
camp = cid[1]["id"]
db.q("INSERT INTO campaign_recipients (campaign_id, agent_id, channel, address, spec, status, session_id, created, updated) "
     "VALUES (?, ?, 'whatsapp', '5491100000001', '{}', 'sent', 'wa-5491100000001', '', '')", (camp, AID))
s, camp_cost = js("GET", "/api/agents/%s/costs?campaign=%s" % (AID, camp), headers=ANALYST)
assert s == 200 and camp_cost["conversations"]["count"] == 1, camp_cost
print("ok: reporte por día, canal, proveedor, conversación, resueltas, campaña y CSV")

# ---------- 5. métricas ----------
text = telemetry.render()
assert 'parla_usage_total{agent="%s",kind="phone",provider="twilio",unit="minutes"} 1.5' % AID in text, text[-2000:]
assert 'parla_usage_total{agent="aaaaaaaa",kind="llm_input",provider="anthropic",unit="tokens"} 10' in text
assert 'parla_cost_total{agent="aaaaaaaa",currency="USD",kind="llm_input",provider="anthropic"}' in text
print("ok: parla_usage_total y parla_cost_total")

# ---------- 6. la cuenta no frena el turno: con el escritor de la base trabado, medir y cerrar el scope es instantáneo ----------
db.WRITE.acquire()
try:
    t0 = time.perf_counter()
    with costs.scope(AID, "lento", "api"):
        for _ in range(200):
            costs.record("llm_input", "openai", "gpt-6-luna", 10)
    costs.record("whatsapp", "meta", "service", 1, agent=AID, session="lento")
    took = time.perf_counter() - t0
finally:
    db.WRITE.release()
assert took < 0.25, took
flush()
assert rows("lento")[("llm_input", "openai", "gpt-6-luna")] == 2000
print("ok: la cuenta va por la cola del escritor (%.1f ms con la base trabada)" % (took * 1000))

# ---------- 7. privacidad: borrar la conversación deja el total del día sin el id ----------
total_before = sum(rows().values())
assert js("DELETE", V1 + "/sessions/c1", headers=OWNER)[0] == 200
flush()
assert rows("c1") == {} and abs(sum(rows().values()) - total_before) < 1e-6
print("ok: borrar una conversación conserva los totales sin su id")

# ---------- 8. handoff: el resumen de la IA sale del turno ----------
handoff.SUMMARY_WAIT = 5
SLOW["summary"] = 0.8
t0 = time.perf_counter()
s, r = js("POST", V1 + "/events", {"sessionId": "h1", "text": "tengo un reclamo", "channel": "api"}, OWNER)
took = time.perf_counter() - t0
assert s == 200 and r["handoff"] is True, r
assert took < SLOW["summary"], "el turno esperó el resumen de la IA (%.2f s)" % took
rec = app.load_session(AID, "h1")
plain = rec["handoff"]["summary"]
assert "reclamo" in plain and "router" in plain, plain                              # el fijo, al instante
assert handoff.sip_headers(app.load(AID), rec)["X-Parla-Summary"] == handoff._ascii(plain)   # el teléfono no espera
assert handoff.tick() == 0 and not HOOKS                                             # el webhook espera el resumen
for _ in range(50):
    handoff.tick()
    if HOOKS:
        break
    time.sleep(0.1)
assert HOOKS and HOOKS[0]["handoff"]["summary"] == "Quiere reclamar por su router.", HOOKS
for _ in range(30):
    if app.load_session(AID, "h1")["handoff"]["summary"] != plain:
        break
    time.sleep(0.1)
assert app.load_session(AID, "h1")["handoff"]["summary"] == "Quiere reclamar por su router."
flush()
assert rows("h1").get(("llm_output", "openai_compatible", "qwen"), 0) >= 20       # el resumen también cuenta en la charla
# si la IA tarda más que la espera, el webhook sale con el fijo
HOOKS.clear()
handoff.SUMMARY_WAIT, SLOW["summary"] = 0.3, 3
s, r = js("POST", V1 + "/events", {"sessionId": "h2", "text": "tengo un reclamo", "channel": "api"}, OWNER)
assert r["handoff"] is True
time.sleep(0.5)
handoff.tick()
assert HOOKS and "router" in HOOKS[0]["handoff"]["summary"] and HOOKS[0]["handoff"]["summary"] != "Quiere reclamar por su router.", HOOKS
print("ok: resumen de la IA en segundo plano (el webhook lo espera hasta SUMMARY_WAIT; el turno y el SIP no)")
print("ok")
