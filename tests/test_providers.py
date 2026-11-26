"""Proveedores con API key propia (IA, transcripción y voz) contra un servidor falso local: forma de cada pedido,
encabezados de auth, salida JSON, rechazos de Claude, errores con la key tapada, multipart y pistas de vocabulario,
audio WAV y su caché por proveedor y voz, y el teléfono hablando con la voz del agente. Nunca llama a una API real.
Uso: .venv/bin/python tests/test_providers.py"""
import base64
import hashlib
import io
import json
import os
import sys
import threading
import urllib.parse
import wave
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import support
DATA = support.temp_data()

KEY = "sk-secret-0123456789abcdef"
seen = []                          # (método, path, encabezados, cuerpo crudo)
mode = {}                          # path -> (código, cuerpo) para forzar respuestas


def wav_bytes(seconds=0.2, rate=16000):
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1), w.setsampwidth(2), w.setframerate(rate)
        w.writeframes(b"\x01\x00" * int(seconds * rate))
    return buf.getvalue()


WAV = wav_bytes()
CLAUDE = {"id": "msg_1", "type": "message", "role": "assistant", "model": "claude-opus-5-5", "stop_reason": "end_turn",
          "stop_sequence": None, "usage": {"input_tokens": 1, "output_tokens": 1}}


class Fake(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def send(self, code, body, ctype="application/json", headers=None):
        raw = body if isinstance(body, bytes) else json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(raw)))
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(raw)

    def handle_any(self, method):
        raw = self.rfile.read(int(self.headers.get("Content-Length") or 0))
        path = urllib.parse.urlsplit(self.path).path
        seen.append((method, self.path, self.headers, raw))   # encabezados sin distinguir mayúsculas
        if path in mode:
            code, body = mode[path]
            return self.send(code, body, headers={"x-should-retry": "false"})
        body = json.loads(raw) if raw[:1] == b"{" else None
        if path == "/v1/models" and "x-api-key" in self.headers:     # Anthropic
            return self.send(200, {"data": [{"id": "claude-opus-5-5", "type": "model", "display_name": "Claude Opus 5.5",
                                             "created_at": "2026-01-01T00:00:00Z"}], "has_more": False,
                                   "first_id": "claude-opus-5-5", "last_id": "claude-opus-5-5"})
        if path == "/v1/messages":
            fmt = (body.get("output_config") or {}).get("format")
            text = json.dumps({"opcion": "A"}) if fmt else "Hola, soy Claude." if "JSON" not in str(body.get("system")) else 'Claro: {"slots": {"a": 1}, "text": "ok"}'
            return self.send(200, dict(CLAUDE, model=body["model"], content=[{"type": "text", "text": text}]))
        if path == "/v1beta/models":
            return self.send(200, {"models": [{"name": "models/gemini-3.8-flash"}]})
        if path.startswith("/v1beta/models/") and path.endswith(":generateContent"):
            cfg = body.get("generationConfig") or {}
            text = json.dumps({"opcion": "B"}) if cfg.get("responseJsonSchema") else "Hola, soy Gemini."
            return self.send(200, {"candidates": [{"content": {"role": "model", "parts": [{"text": "pensando…", "thought": True},
                                                                                            {"text": text}]}, "finishReason": "STOP"}]})
        if path == "/v1/audio/transcriptions":
            return self.send(200, {"text": "quiero una muzzarella"})
        if path == "/v1/listen":
            return self.send(200, {"results": {"channels": [{"alternatives": [{"transcript": "dos fugazzetas"}]}]}})
        if path == "/v1/speech-to-text":
            return self.send(200, {"text": "una napolitana"})
        if path == "/v1/speech:recognize":
            return self.send(200, {"results": [{"alternatives": [{"transcript": "hola"}]}, {"alternatives": [{"transcript": "che"}]}]})
        if path in ("/v1/audio/speech", "/v1/speak") or path.startswith("/v1/text-to-speech/"):
            return self.send(200, WAV, "audio/wav")
        if path == "/v1/text:synthesize":
            return self.send(200, {"audioContent": base64.b64encode(WAV).decode()})
        if path == "/v1/voices" and "xi-api-key" in self.headers:
            return self.send(200, {"voices": [{"voice_id": "v1", "name": "Ana"}]})
        if path == "/v1/voices":
            return self.send(200, {"voices": [{"name": "es-US-Neural2-A", "languageCodes": ["es-US"]}]})
        self.send(404, {"error": "no existe"})

    def do_GET(self):
        self.handle_any("GET")

    def do_POST(self):
        self.handle_any("POST")


srv = ThreadingHTTPServer(("127.0.0.1", 0), Fake)
threading.Thread(target=srv.serve_forever, daemon=True).start()
BASE = "http://127.0.0.1:%d" % srv.server_address[1]
for name in ("ANTHROPIC", "GEMINI", "OPENAI", "DEEPGRAM", "ELEVENLABS", "GOOGLE_SPEECH", "GOOGLE_TTS"):
    os.environ["PARLA_%s_BASE_URL" % name] = BASE

from parla import server as app, llm, phone, vault, voice  # noqa: E402
import numpy as np  # noqa: E402

app._encode = lambda texts: [(lambda v: v / np.linalg.norm(v))(np.random.default_rng(
    int(hashlib.md5(t.encode()).hexdigest()[:8], 16)).normal(size=64)) for t in texts]
os.makedirs(app.AGENTS, exist_ok=True)
AID = "abcd1234"
for secret in ("ANTHROPIC_API_KEY", "GEMINI_API_KEY", "OPENAI_API_KEY", "DEEPGRAM_API_KEY", "ELEVENLABS_API_KEY", "GOOGLE_API_KEY"):
    vault.put(AID, secret, KEY)


def last(path_start):
    return next(r for r in reversed(seen) if r[1].startswith(path_start))


def masked(fn):
    try:
        fn()
    except (llm.LLMError, ValueError) as error:
        assert KEY not in str(error), error
        return error
    raise AssertionError("debió fallar")


SCHEMA = {"type": "object", "properties": {"opcion": {"type": "string", "enum": ["A", "B"]}}, "required": ["opcion"]}
FREE = {"type": "object", "properties": {"text": {"type": "string"}, "slots": {"type": "object"}}, "required": ["text"]}
MSGS = [{"role": "system", "content": "Sos Pizzi."}, {"role": "user", "content": "hola"}]

# ---------- configuración: nombres de clave por defecto, la key solo del vault ----------
cfg = llm.settings({"id": AID, "ai": {"provider": "anthropic", "api_key": "robada"}})
assert cfg["api_key"] == KEY and cfg["api_key_secret"] == "ANTHROPIC_API_KEY" and cfg["model"] == "claude-opus-5-5", cfg
assert llm.settings({"id": AID, "ai": {"provider": "gemini"}})["api_key_secret"] == "GEMINI_API_KEY"
assert llm.settings({"ai": {"provider": "openai"}})["url"] == "https://api.openai.com/v1"
old = llm.settings({"ai": {"provider": "openai", "url": "http://127.0.0.1:1234/v1"}})        # agente viejo: compatible con URL propia
assert old["url"] == "http://127.0.0.1:1234/v1" and "api_key_secret" not in old, old
assert llm.settings({})["provider"] == "ollama" and llm.settings({})["url"] == "http://127.0.0.1:11434"

# ---------- Anthropic (SDK oficial) ----------
try:
    import anthropic  # noqa: F401
    HAVE_SDK = True
except ImportError:
    HAVE_SDK = False
    print("(Claude con el SDK: saltado, falta pip install -r requirements-providers.txt)")

if HAVE_SDK:
    assert llm.chat(cfg, MSGS, max_tokens=20) == "Hola, soy Claude."
    method, path, headers, raw = last("/v1/messages")
    body = json.loads(raw)
    assert headers["x-api-key"] == KEY and "server-side-fallback-2026-07-01" in headers.get("anthropic-beta", ""), headers
    assert body["model"] == "claude-opus-5-5" and body["fallbacks"] == "default" and body["system"] == "Sos Pizzi.", body
    assert body["messages"] == [{"role": "user", "content": "hola"}] and body["max_tokens"] >= 2048, body
    assert body["output_config"] == {"effort": "low"} and "thinking" not in body and "temperature" not in body, body
    # JSON: salida estructurada con additionalProperties false
    assert llm.chat(cfg, MSGS, schema=SCHEMA) == {"opcion": "A"}
    fmt = json.loads(last("/v1/messages")[3])["output_config"]["format"]
    assert fmt == {"type": "json_schema", "schema": dict(SCHEMA, additionalProperties=False)}, fmt
    # objetos libres (slots): el esquema va en el prompt y se saca el JSON del texto
    assert llm.chat(cfg, MSGS, schema=FREE) == {"slots": {"a": 1}, "text": "ok"}
    body = json.loads(last("/v1/messages")[3])
    assert "format" not in body["output_config"] and "JSON" in body["system"], body
    # Haiku: sin fallback del servidor (no lo tiene): messages.create común
    llm.chat(dict(cfg, model="claude-haiku-5-5"), MSGS)
    assert "fallbacks" not in json.loads(last("/v1/messages")[3]) and "anthropic-beta" not in last("/v1/messages")[2]
    # stop_reason refusal / max_tokens
    mode["/v1/messages"] = (200, dict(CLAUDE, content=[], stop_reason="refusal"))
    assert "filtro de seguridad" in str(masked(lambda: llm.chat(cfg, MSGS)))
    mode["/v1/messages"] = (200, dict(CLAUDE, content=[{"type": "text", "text": "{"}], stop_reason="max_tokens"))
    assert "máximo de tokens" in str(masked(lambda: llm.chat(cfg, MSGS)))
    # errores tipados del SDK -> LLMError con la key tapada (aunque el proveedor la repita)
    mode["/v1/messages"] = (401, {"type": "error", "error": {"type": "authentication_error", "message": "invalid x-api-key " + KEY}})
    error = masked(lambda: llm.chat(cfg, MSGS))
    assert error.code == 401 and "Claves" in str(error), error
    mode["/v1/messages"] = (429, {"type": "error", "error": {"type": "rate_limit_error", "message": "slow down " + KEY}})
    error = masked(lambda: llm.chat(cfg, MSGS))
    assert error.code == 429 and "••••" in str(error), error
    mode["/v1/messages"] = (529, {"type": "error", "error": {"type": "overloaded_error", "message": "Overloaded"}})
    assert "falló" in str(masked(lambda: llm.chat(cfg, MSGS)))
    del mode["/v1/messages"]
    # status: lista los modelos y prueba
    st = llm.status(dict(cfg, prompt="hola"))
    assert st["ok"] and st["model_ready"] and st["reply"] == "Hola, soy Claude." and st["local"] is False, st
    assert "claude-sonnet-5-5" in st["suggested"]
    assert llm.status(llm.settings({"ai": {"provider": "anthropic"}}))["error"].startswith("falta la API key")

# sin el SDK: un error claro con cómo instalarlo
saved = sys.modules.get("anthropic")
sys.modules["anthropic"] = None
assert "requirements-providers.txt" in str(masked(lambda: llm.chat(cfg, MSGS)))
if saved:
    sys.modules["anthropic"] = saved
else:
    del sys.modules["anthropic"]

# ---------- Google Gemini ----------
g = llm.settings({"id": AID, "ai": {"provider": "gemini"}})
assert llm.chat(g, MSGS, max_tokens=20) == "Hola, soy Gemini."         # sin las partes «thought»
method, path, headers, raw = last("/v1beta/models/gemini-3.8-flash:generateContent")
body = json.loads(raw)
assert headers["X-Goog-Api-Key"] == KEY and KEY not in path, (headers, path)
assert body["systemInstruction"] == {"parts": [{"text": "Sos Pizzi."}]} and body["contents"] == [{"role": "user", "parts": [{"text": "hola"}]}], body
assert body["generationConfig"]["maxOutputTokens"] >= 2048 and "responseJsonSchema" not in body["generationConfig"]
assert llm.chat(g, MSGS + [{"role": "assistant", "content": "¿Qué?"}, {"role": "user", "content": "nada"}], schema=SCHEMA) == {"opcion": "B"}
body = json.loads(last("/v1beta/models/")[3])
assert body["generationConfig"]["responseMimeType"] == "application/json" and body["generationConfig"]["responseJsonSchema"] == SCHEMA
assert [c["role"] for c in body["contents"]] == ["user", "model", "user"], body
mode["/v1beta/models/gemini-3.8-flash:generateContent"] = (200, {"promptFeedback": {"blockReason": "SAFETY"}})
assert "filtro de seguridad" in str(masked(lambda: llm.chat(g, MSGS)))
mode["/v1beta/models/gemini-3.8-flash:generateContent"] = (400, {"error": {"code": 400, "message": "API key not valid: " + KEY}})
error = masked(lambda: llm.chat(g, MSGS))
assert error.code == 400 and "••••" in str(error), error
del mode["/v1beta/models/gemini-3.8-flash:generateContent"]
st = llm.status(dict(g, prompt="hola"))
assert st["ok"] and st["model_ready"] and st["reply"] == "Hola, soy Gemini.", st

# ---------- ASR ----------
VS = {"id": AID, "voice": {"asr": {"provider": "openai"}, "tts": {"provider": "deepgram"}}}
conf = voice.settings(VS)
assert conf["asr"]["api_key"] == KEY and conf["asr"]["api_key_secret"] == "OPENAI_API_KEY" and conf["tts"]["api_key_secret"] == "DEEPGRAM_API_KEY"
assert voice.settings({"id": AID})["asr"] == {"provider": "local"} and voice.settings({"voice": {"tts": {"provider": "x"}}})["tts"]["provider"] == "local"
AUDIO = b"\x1aE\xdf\xa3" + b"\x00" * 400        # «webm»
HINT = "muzzarella, napolitana, fugazzeta"

res = voice.transcribe(AUDIO, "audio/webm;codecs=opus", "es-AR", HINT, conf["asr"])
assert res["text"] == "quiero una muzzarella" and res["provider"] == "openai", res
method, path, headers, raw = last("/v1/audio/transcriptions")
assert headers["Authorization"] == "Bearer " + KEY and headers["Content-Type"].startswith("multipart/form-data; boundary=")
for part in (b'name="model"\r\n\r\ngpt-4o-mini-transcribe\r\n', b'name="language"\r\n\r\nes\r\n', b'name="prompt"\r\n\r\n' + HINT.encode(),
             b'filename="audio.webm"\r\nContent-Type: audio/webm\r\n\r\n' + AUDIO):
    assert part in raw, (part, raw[:400])

dg = voice.settings({"id": AID, "voice": {"asr": {"provider": "deepgram"}}})["asr"]
assert voice.transcribe(AUDIO, "audio/webm", "es", HINT, dg)["text"] == "dos fugazzetas"
method, path, headers, raw = last("/v1/listen")
query = urllib.parse.parse_qs(urllib.parse.urlsplit(path).query)
assert query["model"] == ["nova-3"] and query["language"] == ["es"] and query["keyterm"] == ["muzzarella", "napolitana", "fugazzeta"], query
assert headers["Authorization"] == "Token " + KEY and headers["Content-Type"] == "audio/webm" and raw == AUDIO

el = voice.settings({"id": AID, "voice": {"asr": {"provider": "elevenlabs"}}})["asr"]
assert voice.transcribe(AUDIO, "audio/webm", "pt", HINT, el)["text"] == "una napolitana"
method, path, headers, raw = last("/v1/speech-to-text")
assert headers["Xi-Api-Key"] == KEY and b'name="model_id"\r\n\r\nscribe_v3' in raw and b'name="language_code"\r\n\r\npt' in raw
assert raw.count(b'name="keyterms"') == 3

go = voice.settings({"id": AID, "voice": {"asr": {"provider": "google"}}})["asr"]
assert voice.transcribe(AUDIO, "audio/webm", "es", HINT, go)["text"] == "hola che"
method, path, headers, raw = last("/v1/speech:recognize")
body = json.loads(raw)
assert headers["X-Goog-Api-Key"] == KEY and "key=" not in path
assert body["config"] == {"encoding": "WEBM_OPUS", "sampleRateHertz": 48000, "languageCode": "es-US",
                          "speechContexts": [{"phrases": ["muzzarella", "napolitana", "fugazzeta"]}]}, body
assert base64.b64decode(body["audio"]["content"]) == AUDIO
voice.transcribe(WAV, "audio/wav", "en", None, go)
assert json.loads(last("/v1/speech:recognize")[3])["config"] == {"encoding": "LINEAR16", "languageCode": "en-US"}

# errores: la key no aparece; sin key, un aviso de Claves
mode["/v1/listen"] = (401, {"err_msg": "Invalid credentials " + KEY})
assert masked(lambda: voice.transcribe(AUDIO, "audio/webm", "es", None, dg)).code == 401
del mode["/v1/listen"]
assert "Claves" in str(masked(lambda: voice.transcribe(AUDIO, "audio/webm", "es", None, voice.settings({"voice": {"asr": {"provider": "deepgram"}}})["asr"])))

# ---------- TTS: WAV de cada proveedor, caché por proveedor y voz ----------
voice.TTS_CACHE = voice.Path(DATA) / "tts-cache"
for provider, path, check in (
        ("openai", "/v1/audio/speech", lambda h, b: h["Authorization"] == "Bearer " + KEY and json.loads(b) == {
            "model": "gpt-4o-mini-tts-2025-12-15", "input": "Hola.", "voice": "coral", "response_format": "wav"}),
        ("deepgram", "/v1/speak", lambda h, b: h["Authorization"] == "Token " + KEY and json.loads(b) == {"text": "Hola."}),
        ("elevenlabs", "/v1/text-to-speech/JBFqnCBsd6RMkjVDRZzb", lambda h, b: h["Xi-Api-Key"] == KEY and json.loads(b) == {
            "text": "Hola.", "model_id": "eleven_flash_v2_5", "language_code": "es"}),
        ("google", "/v1/text:synthesize", lambda h, b: h["X-Goog-Api-Key"] == KEY and json.loads(b) == {
            "input": {"text": "Hola."}, "voice": {"languageCode": "es-US"}, "audioConfig": {"audioEncoding": "LINEAR16", "sampleRateHertz": 16000}})):
    tts = voice.settings({"id": AID, "voice": {"tts": {"provider": provider}}})["tts"]
    audio = voice.speak("Hola.", "es", tts=tts)
    assert audio[:4] == b"RIFF" and wave.open(io.BytesIO(audio)).getnframes() > 0, provider
    method, got, headers, raw = last(path)
    assert check(headers, raw), (provider, headers, raw)
dq = urllib.parse.parse_qs(urllib.parse.urlsplit(last("/v1/speak")[1]).query)
assert dq == {"model": ["aura-2-celeste-es"], "encoding": ["linear16"], "container": ["wav"], "sample_rate": ["24000"]}, dq
assert "output_format=wav_16000" in last("/v1/text-to-speech/")[1]
assert "Deepgram" in str(masked(lambda: voice.speak("Olá.", "pt", tts=voice.settings({"id": AID, "voice": {"tts": {"provider": "deepgram"}}})["tts"])))

tts = conf["tts"]                                           # deepgram, voz por defecto
assert voice.prewarm(["Hola. ¿Qué gusto querés?", "Hola {{ nombre }}."], "es", tts) == 2
count = len(seen)
assert voice.speak("¿Qué gusto querés?", "es", tts=tts)[:4] == b"RIFF" and len(seen) == count     # de la caché, sin pedir
assert voice._cached("es", "Hola.", tts) != voice._cached("es", "Hola.", dict(tts, voice="aura-2-sirio-es")) != voice._cached("es", "Hola.")
voice.speak("¿Qué gusto querés?", "es", tts=dict(tts, voice="aura-2-sirio-es"))            # otra voz: no sirve la de antes
assert len(seen) == count + 1 and "aura-2-sirio-es" in seen[-1][1]

# voces para elegir
assert {"id": "v1", "name": "Ana"} in voice.voices(voice.settings({"id": AID, "voice": {"tts": {"provider": "elevenlabs"}}})["tts"])
assert voice.voices(voice.settings({"id": AID, "voice": {"tts": {"provider": "google"}}})["tts"], "es")[0]["id"] == "es-US-Neural2-A"
assert "languageCode=es-US" in last("/v1/voices?")[1]
assert all(v["id"].endswith("-es") for v in voice.voices({"provider": "deepgram"}, "es")) and voice.voices({"provider": "openai"})[0]["id"] == "alloy"

# ---------- teléfono: tts «parla» = la voz del agente (acá Deepgram) ----------
agent = app.create({**app.BLANK, "name": "Tel", "flows": [{"name": "inicio", "trigger": "__start__", "steps": [{"type": "message", "text": "Hola."}]}],
                    "voice": {"tts": {"provider": "deepgram", "voice": "aura-2-nestor-es"}},
                    "channels": {"public_url": "https://bots.example.com", "phone": {"enabled": True, "provider": "twilio", "tts": "parla"}}})
vault.put(agent["id"], "DEEPGRAM_API_KEY", KEY)
count = len(seen)
code, audio, ctype = phone.audio(agent["id"], phone.audio_token(agent["id"], "Te paso con una persona.", "es"))
assert code == 200 and ctype == "audio/wav" and audio[:4] == b"RIFF", (code, ctype)
assert any("aura-2-nestor-es" in r[1] for r in seen[count:]), seen[count:]

# ---------- MCP validate: proveedores nuevos y claves por defecto ----------
from parla import mcp_server  # noqa: E402
FLOWS = {"flows": [{"name": "inicio", "trigger": "__start__", "steps": [{"type": "message", "text": "Hola."}]}]}
_, errors, _ = mcp_server.validate({**app.BLANK, **FLOWS, "ai": {"provider": "anthropic", "model": "claude-opus-5-5"},
                                    "voice": {"asr": {"provider": "deepgram"}, "tts": {"provider": "elevenlabs", "voice": "v1"}}})
assert not errors, errors
_, errors, _ = mcp_server.validate({**app.BLANK, **FLOWS, "ai": {"provider": "otro"}, "voice": {"asr": {"provider": "x", "api_key": "no"}}})
assert len(errors) >= 3, errors
refs = mcp_server.secret_refs({"ai": {"provider": "gemini"}, "voice": {"asr": {"provider": "deepgram"}, "tts": {"provider": "google"}}})
assert {"GEMINI_API_KEY", "DEEPGRAM_API_KEY", "GOOGLE_API_KEY"} <= refs, refs
print("ok")
