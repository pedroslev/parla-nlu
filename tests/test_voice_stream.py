"""Voz en tiempo real (voicestream.py) con proveedores falsos: Twilio Media Streams, jambonz listen, el WebSocket del
navegador, Deepgram live, TTS en streaming y una IA lenta para el barge-in. Nada sale a internet.
    .venv/bin/python tests/test_voice_stream.py"""
import asyncio
import base64
import hashlib
import hmac
import json
import os
import threading
import time
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import support
DATA = support.temp_data()
os.environ["PARLA_METRICS"] = "1"

import numpy as np  # noqa: E402
from parla import aserver, costs, llm, phone, telemetry, vault, voice  # noqa: E402
from parla import server as app  # noqa: E402
from parla import voicestream as vs  # noqa: E402

telemetry.configure()
app._encode = lambda texts: [(lambda v: v / np.linalg.norm(v))(np.random.default_rng(
    int(hashlib.md5(t.encode()).hexdigest()[:8], 16)).normal(size=64)) for t in texts]


def tone(seconds, freq=300, amp=9000, rate=16000):
    return (np.sin(np.arange(int(seconds * rate)) / rate * 2 * np.pi * freq) * amp).astype(np.int16)


def quiet(seconds, rate=16000):
    return np.zeros(int(seconds * rate), np.int16)


# ---------- unidades: μ-law, remuestreo, WAV, VAD ----------
assert vs.ULAW[0xFF] == 0 and vs.ULAW[0x80] == 32124 and vs.ULAW[0x00] == -32124      # tabla G.711
assert vs.ulaw_encode(np.array([0, 32767, -32768], np.int16)) == b"\xff\x80\x00"
x = tone(1, 440, 12000)
assert np.max(np.abs(vs.ulaw_decode(vs.ulaw_encode(x)).astype(int) - x)) < 12000 * 0.03           # error de cuantización μ-law
y = vs.resample(vs.resample(x, 16000, 8000), 8000, 16000)
assert len(y) == len(x) and np.sqrt(np.mean((y.astype(float) - x) ** 2)) < 12000 * 0.1
assert len(vs.resample(x, 16000, 24000)) == 24000 and vs.resample(x, 16000, 16000) is not None
pcm, rate = vs.from_wav(vs.to_wav(x))
assert rate == 16000 and np.array_equal(pcm, x)
vad, events = vs.VAD(silence_ms=400), []
burst = np.concatenate([quiet(0.5), tone(0.6), quiet(0.6), tone(0.1), quiet(0.6), tone(0.8), quiet(0.6)])
for i in range(0, len(burst), 320):
    e = vad.push(burst[i:i + 320])
    if e:
        events.append((e, i / 16000))
assert [e for e, _ in events] == ["start", "end", "start", "end"], events           # el golpe de 100 ms no es voz
assert 0.6 < events[0][1] < 0.8 and 1.4 < events[1][1] < 1.6, events
tok = phone.stream_token("abcd1234", "call-CA1")
assert phone.stream_sid("abcd1234", tok) == "call-CA1" and phone.stream_sid("ffffffff", tok) is None
assert phone.stream_sid("abcd1234", tok, now=time.time() + phone.AUDIO_TTL + 5) is None and phone.stream_sid("abcd1234", tok[:-3] + "xyz") is None

# ---------- proveedores falsos ----------
SPOKEN, HEARD = [], []          # lo que el bot dijo (TTS) y lo que «oye» el ASR local falso, en orden


def fake_speak(text, language="es", keep=True, tts=None):
    SPOKEN.append(text)
    costs.record("tts", "local", "piper", len(text))
    return vs.to_wav(tone(min(1.5, 0.04 * len(text)), 500))


def fake_transcribe(audio, mime="audio/webm", language="es", hint=None, asr=None):
    assert mime == "audio/wav" and audio[:4] == b"RIFF"
    costs.record("asr", "local", "whisper-fake", 0.01)
    return {"text": HEARD.pop(0) if HEARD else "", "language": "es", "ms": 1, "provider": "local"}


voice.speak, voice.transcribe = fake_speak, fake_transcribe
LLM = {"sent": 0, "total": 0, "aborted": False}


class FakeHTTP(BaseHTTPRequestHandler):
    """Ollama lento (para cortarlo con barge-in) y ElevenLabs /stream (PCM 16 kHz en pedazos)."""
    protocol_version = "HTTP/1.1"

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        if self.path == "/api/chat":
            text = '{"respuesta": "Perdón, no te entendí bien. ¿Me lo decís de otra forma? Te cuento que hacemos pizzas muy ricas. Abrimos todos los días."}'
            pieces = [text[i:i + 6] for i in range(0, len(text), 6)]
            LLM["total"] = len(pieces)
            self.send_response(200)
            self.send_header("Transfer-Encoding", "chunked")
            self.end_headers()
            try:
                for piece in pieces:
                    line = (json.dumps({"message": {"content": piece}, "done": False}) + "\n").encode()
                    self.wfile.write(b"%x\r\n%s\r\n" % (len(line), line))
                    self.wfile.flush()
                    LLM["sent"] += 1
                    time.sleep(0.12)
                line = json.dumps({"message": {"content": ""}, "done": True}).encode() + b"\n"
                self.wfile.write(b"%x\r\n%s\r\n0\r\n\r\n" % (len(line), line))
            except (BrokenPipeError, ConnectionResetError):
                LLM["aborted"] = True
            return
        assert self.path.startswith("/v1/text-to-speech/voz-1/stream?output_format=pcm_16000"), self.path
        assert self.headers["xi-api-key"] == "el-key"
        SPOKEN.append(body["text"])
        audio = tone(min(2.0, 0.05 * len(body["text"])), 600).astype("<i2").tobytes()
        self.send_response(200)
        self.send_header("Transfer-Encoding", "chunked")
        self.end_headers()
        try:
            for i in range(0, len(audio), 3200):           # 100 ms por pedazo
                part = audio[i:i + 3200]
                self.wfile.write(b"%x\r\n%s\r\n" % (len(part), part))
                self.wfile.flush()
                time.sleep(0.01)
            self.wfile.write(b"0\r\n\r\n")
        except (BrokenPipeError, ConnectionResetError):
            pass

    def log_message(self, *a):
        pass


fake_http = ThreadingHTTPServer(("127.0.0.1", 0), FakeHTTP)
threading.Thread(target=fake_http.serve_forever, daemon=True).start()
FAKE = "http://127.0.0.1:%d" % fake_http.server_address[1]
os.environ["PARLA_ELEVENLABS_BASE_URL"] = FAKE
DG = {"texts": [], "auth": None, "query": None, "closed": False}


async def fake_deepgram(reader, writer):
    """Deepgram live: VAD sobre lo que llega; SpeechStarted y un parcial al empezar, el final al callarse."""
    head = await reader.readuntil(b"\r\n\r\n")
    lines = head.decode().split("\r\n")
    DG["query"] = dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(lines[0].split(" ")[1]).query))
    hdrs = {k.lower(): v.strip() for k, _, v in (line.partition(":") for line in lines[1:] if line)}
    DG["auth"] = hdrs.get("authorization")
    aserver.upgrade(writer, {"Sec-WebSocket-Key": hdrs["sec-websocket-key"]})
    vad, pos, start = vs.VAD(silence_ms=300), 0, 0
    send = lambda d: writer.write(aserver.frame(1, json.dumps(d).encode()))
    try:
        while True:
            fin, op, data = await aserver.read_frame(reader)
            if op == 8 or (op == 1 and b"CloseStream" in data):
                DG["closed"] = True
                break
            pcm = np.frombuffer(data, "<i2")
            for i in range(0, len(pcm), 320):
                pos += 320
                e = vad.push(pcm[i:i + 320])
                if e == "start":
                    start = pos / 16000 - 0.2
                    send({"type": "SpeechStarted"})
                    send({"type": "Results", "is_final": False, "channel": {"alternatives": [{"transcript": "es"}]}})
                elif e == "end":
                    text = DG["texts"].pop(0) if DG["texts"] else ""
                    send({"type": "Results", "is_final": True, "speech_final": True, "start": start,
                          "duration": pos / 16000 - 0.3 - start, "channel": {"alternatives": [{"transcript": text}]}})
            await writer.drain()
    except (asyncio.IncompleteReadError, ConnectionError):
        pass
    writer.close()


# ---------- Parla en este proceso (aserver en un hilo) ----------
app.migrate()
os.makedirs(app.AGENTS, exist_ok=True)
FLOWS = [{"name": "inicio", "trigger": "__start__", "steps": [{"type": "message", "text": "¡Hola! Soy Pizzi."}]},
         {"name": "saludo", "trigger": "saludar", "steps": [
             {"type": "ask", "slot": "gusto", "text": "¿Qué gusto?", "buttons": [
                 {"label": "Muzzarella", "value": "muzza"}, {"label": "Fugazza", "value": "fuga"}]},
             {"type": "message", "text": "Elegiste {{ gusto }}"}, {"type": "set", "slot": "gusto", "mode": "clear"}]},
         {"name": "fin", "trigger": "chau", "steps": [{"type": "message", "text": "¡Chau!"}, {"type": "end"}]}]
BASE_AGENT = {**app.BLANK, "threshold": 0.9, "flows": FLOWS, "slots": [{"name": "gusto"}],
              "intents": [{"name": "saludar", "examples": ["hola"]}, {"name": "chau", "examples": ["chau"]}],
              "ai": {"enabled": True, "provider": "ollama", "url": FAKE, "model": "lento", "generative_fallback": True}}
tw_agent = app.create({**BASE_AGENT, "name": "Pizzería TW", "channels": {"public_url": "https://bots.example.com", "phone": {
    "enabled": True, "provider": "twilio", "mode": "stream", "language": "es-AR", "handoff_to": "+5491100000000"}}})
jz_agent = app.create({**BASE_AGENT, "name": "Pizzería JZ", "channels": {"public_url": "https://bots.example.com", "phone": {
    "enabled": True, "provider": "jambonz", "mode": "stream", "language": "es-AR"}}})
dg_agent = app.create({**BASE_AGENT, "name": "Pizzería DG", "voice": {"asr": {"provider": "deepgram"},
                                                                       "tts": {"provider": "elevenlabs", "voice": "voz-1"}}})
TW, JZ, DGA = tw_agent["id"], jz_agent["id"], dg_agent["id"]
vault.put(TW, "TWILIO_AUTH_TOKEN", "tw-token")
vault.put(JZ, "JAMBONZ_WEBHOOK_SECRET", "jz-secret")
vault.put(DGA, "DEEPGRAM_API_KEY", "dg-key")
vault.put(DGA, "ELEVENLABS_API_KEY", "el-key")

PORT = {}
threading.Thread(target=aserver.serve, args=("127.0.0.1", 0, lambda p: PORT.setdefault("p", p)), daemon=True).start()
while "p" not in PORT:
    time.sleep(0.05)
BASE = "http://127.0.0.1:%d" % PORT["p"]


def post(path, raw, headers):
    req = urllib.request.Request(BASE + path, data=raw, method="POST", headers={"Host": "bots.example.com", **headers})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, r.read().decode()
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()


def tw_sign(url, params=()):
    return base64.b64encode(hmac.new(b"tw-token", (url + "".join(k + v for k, v in sorted(params))).encode(), hashlib.sha1).digest()).decode()


def tw_hook(action, params):
    path = "/api/v1/bots/%s/phone/twilio%s" % (TW, "/" + action if action else "")
    return post(path, urllib.parse.urlencode(params).encode(), {"Content-Type": "application/x-www-form-urlencoded",
                                                                "X-Twilio-Signature": tw_sign("https://bots.example.com" + path, params.items())})


def jz_hook(action, payload):
    raw, stamp = json.dumps(payload).encode(), str(int(time.time()))
    sig = hmac.new(b"jz-secret", stamp.encode() + b"." + raw, hashlib.sha256).hexdigest()
    return post("/api/v1/bots/%s/phone/jambonz%s" % (JZ, "/" + action if action else ""), raw,
                {"Content-Type": "application/json", "Jambonz-Signature": "t=%s,v1=%s" % (stamp, sig)})


async def ws(path, headers=None):
    return await vs.WSClient.connect("ws://127.0.0.1:%d%s" % (PORT["p"], path), headers or {})


async def refused(path, headers=None):
    try:
        await ws(path, headers)
    except ValueError as error:
        return "403" in str(error) or "400" in str(error)
    return False


class Peer:
    """Lo que manda Parla por un socket, leído en segundo plano."""

    def __init__(self, sock):
        self.sock, self.items, self.task = sock, [], asyncio.ensure_future(self._read())

    async def _read(self):
        try:
            async for op, data in self.sock.messages():
                self.items.append((time.monotonic(), op, data if op == 2 else json.loads(data)))
        except (asyncio.IncompleteReadError, ConnectionError):
            pass
        self.items.append((time.monotonic(), 8, None))

    async def wait(self, test, after=0, timeout=8):
        t = time.monotonic() + timeout
        while time.monotonic() < t:
            for at, op, data in self.items[after:]:
                if test(op, data):
                    return at
            await asyncio.sleep(0.01)
        raise AssertionError("no llegó: %s" % [d if op != 2 else "<%d bytes>" % len(d) for _, op, d in self.items[after:]][-8:])


async def stream_audio(send, pcm, realtime=True):
    """Manda audio de a 20 ms (a tiempo real: así el fin de la voz y la latencia son los de una llamada)."""
    for i in range(0, len(pcm), 320):
        send(pcm[i:i + 320])
        if realtime:
            await asyncio.sleep(0.02)
    return time.monotonic()


LAT = {}


async def twilio():
    s, xml = tw_hook("", {"CallSid": "CA77", "From": "+5491112345678", "To": "+5491199999999"})
    url = "wss://bots.example.com/api/v1/bots/%s/phone/twilio/stream" % TW
    assert s == 200 and '<Connect><Stream url="%s"><Parameter name="sid" value="call-CA77"/></Stream></Connect>' % url in xml, xml
    assert '<Redirect method="POST">https://bots.example.com/api/v1/bots/%s/phone/twilio/after</Redirect>' % TW in xml
    path = "/api/v1/bots/%s/phone/twilio/stream" % TW
    assert await refused(path) and await refused(path, {"X-Twilio-Signature": tw_sign(url + "x")})          # sin firma o mal firmada
    sock = await ws(path, {"X-Twilio-Signature": tw_sign(url)})
    peer = Peer(sock)
    sock.send(1, json.dumps({"event": "connected", "protocol": "Call", "version": "1.0.0"}).encode())
    sock.send(1, json.dumps({"event": "start", "sequenceNumber": "1", "streamSid": "MZ1", "start": {
        "callSid": "CA77", "streamSid": "MZ1", "customParameters": {"sid": "call-CA77"},
        "mediaFormat": {"encoding": "audio/x-mulaw", "sampleRate": 8000, "channels": 1}}}).encode())
    media = lambda op, d: op == 1 and d.get("event") == "media" and d.get("streamSid") == "MZ1"
    await peer.wait(media)                                       # el saludo, en μ-law 8 kHz
    first = next(d for _, op, d in peer.items if media(op, d))
    assert len(base64.b64decode(first["media"]["payload"])) > 1000 and SPOKEN[-2:] == ["¡Hola!", "Soy Pizzi."]

    def send(pcm):
        payload = base64.b64encode(vs.ulaw_encode(vs.resample(pcm, 16000, 8000))).decode()
        sock.send(1, json.dumps({"event": "media", "streamSid": "MZ1", "media": {"track": "inbound", "payload": payload}}).encode())
    await stream_audio(send, quiet(1.6), realtime=False)       # que termine de sonar el saludo
    await asyncio.sleep(1.2)
    # «hola» -> la pregunta con menú, en vivo
    HEARD.append("hola")
    n = len(peer.items)
    end = await stream_audio(send, np.concatenate([tone(0.6), quiet(0.05)]))
    await stream_audio(send, quiet(1.0))
    got = await peer.wait(media, n)
    LAT["twilio_local_client"] = got - end
    assert any("¿Qué gusto?" in t for t in SPOKEN), SPOKEN
    await asyncio.sleep(2.0)
    # DTMF «2» -> el segundo botón
    sock.send(1, json.dumps({"event": "dtmf", "streamSid": "MZ1", "dtmf": {"track": "inbound_track", "digit": "2"}}).encode())
    await asyncio.sleep(0.6)
    assert "Elegiste fuga" in SPOKEN, SPOKEN
    await stream_audio(send, quiet(1.6), realtime=False)
    await asyncio.sleep(1.0)
    # barge-in: la IA (lenta) empieza a hablar y la persona la interrumpe -> clear + IA cortada + anotado
    HEARD.extend(["xyz qwerty", "hola"])
    LLM.update(sent=0, aborted=False)
    await stream_audio(send, np.concatenate([tone(0.6), quiet(0.05)]))
    n = len(peer.items)
    await stream_audio(send, quiet(0.7))
    await peer.wait(media, n, timeout=10)                       # la primera oración de la IA ya suena
    n = len(peer.items)
    await stream_audio(send, tone(0.5))
    await peer.wait(lambda op, d: op == 1 and d.get("event") == "clear" and d.get("streamSid") == "MZ1", n)
    await stream_audio(send, quiet(1.0))
    await asyncio.sleep(1.5)
    assert LLM["sent"] < LLM["total"], LLM                      # el stream de la IA se cortó antes de terminar
    history = app.load_session(TW, "call-CA77")["history"]
    assert any(h.get("interrupted") and "Perdón, no te entendí bien." in h["text"] for h in history), history[-4:]
    assert history[-1]["from"] == "bot" and "Qué gusto" in history[-1]["text"]      # y siguió con lo nuevo
    await asyncio.sleep(2.5)
    # pedir una persona -> el stream se cierra y <Redirect> trae el <Dial>
    HEARD.append("quiero hablar con una persona")
    await stream_audio(send, np.concatenate([tone(0.6), quiet(0.05)]))
    await stream_audio(send, quiet(1.0))
    await peer.wait(lambda op, d: op == 8, timeout=10)
    s, xml = tw_hook("after", {"CallSid": "CA77"})
    assert s == 200 and "<Dial><Number>+5491100000000</Number></Dial>" in xml and "<Connect>" not in xml, xml
    assert any(h["text"] == "Transferida a +5491100000000" for h in app.load_session(TW, "call-CA77")["history"])
    sock.close()
    s, xml = tw_hook("after", {"CallSid": "CA78"})             # stream que se cortó sin plan: corta
    assert s == 200 and xml.endswith("<Hangup/></Response>"), xml


async def jambonz():
    s, body = jz_hook("", {"call_sid": "jz-1", "from": "+5491112345678", "to": "+5491199999999"})
    listen = json.loads(body)[0]
    assert s == 200 and listen["verb"] == "listen" and listen["passDtmf"] and listen["bidirectionalAudio"] == {
        "enabled": True, "streaming": True, "sampleRate": 8000} and listen["actionHook"].endswith("/phone/jambonz/after"), listen
    path = urllib.parse.urlsplit(listen["url"])
    assert listen["url"].startswith("wss://bots.example.com/api/v1/bots/%s/phone/jambonz/stream?t=" % JZ)
    assert await refused(path.path + "?t=x." + path.query[2:].split(".")[1]) and await refused(path.path)
    sock = await ws(path.path + "?" + path.query)
    peer = Peer(sock)
    sock.send(1, json.dumps({"callSid": "jz-1", "sampleRate": 8000, "mixType": "mono"}).encode())
    await peer.wait(lambda op, d: op == 2 and len(d) > 1000)    # el saludo en L16 8 kHz
    send = lambda pcm: sock.send(2, vs.resample(pcm, 16000, 8000).astype("<i2").tobytes())
    await stream_audio(send, quiet(1.6), realtime=False)
    await asyncio.sleep(1.0)
    HEARD.append("hola")
    await stream_audio(send, np.concatenate([tone(0.6), quiet(0.7)]))
    await asyncio.sleep(0.5)
    assert any("¿Qué gusto?" in t for t in SPOKEN[-3:]), SPOKEN
    n = len(peer.items)                                         # suena el menú: una tecla lo corta (killAudio)
    sock.send(1, json.dumps({"event": "dtmf", "dtmf": "1", "duration": "1600"}).encode())
    await peer.wait(lambda op, d: op == 1 and d.get("type") == "killAudio", n)
    await asyncio.sleep(0.5)
    assert "Elegiste muzza" in SPOKEN, SPOKEN
    await stream_audio(send, quiet(1.6), realtime=False)
    await asyncio.sleep(1.0)
    HEARD.append("chau")                                        # paso «end»: disconnect y el actionHook corta
    await stream_audio(send, np.concatenate([tone(0.6), quiet(0.7)]))
    await peer.wait(lambda op, d: op == 1 and d.get("type") == "disconnect", timeout=10)
    s, body = jz_hook("after", {"call_sid": "jz-1"})
    assert s == 200 and json.loads(body) == [{"verb": "hangup"}], body
    sock.close()


async def browser():
    sid = "voz-dg-1"
    s, body = post("/api/v1/bots/%s/events" % DGA, json.dumps({"type": "start", "sessionId": sid}).encode(),
                   {"Content-Type": "application/json", "Host": "127.0.0.1:%d" % PORT["p"]})
    assert s == 200, body
    sock = await ws("/api/v1/bots/%s/voice/ws" % DGA)
    peer = Peer(sock)
    await peer.wait(lambda op, d: op == 1 and d == {"type": "ready", "rate": 16000})
    sock.send(1, json.dumps({"type": "start", "sessionId": sid, "language": "es", "replay": True}).encode())
    await peer.wait(lambda op, d: op == 2)                       # el saludo, por ElevenLabs en streaming
    assert DG["auth"] == "Token dg-key" and DG["query"]["interim_results"] == "true" and DG["query"]["encoding"] == "linear16"
    assert DG["query"]["endpointing"] == "300" and DG["query"]["model"] == "nova-3" and "¡Hola!" in SPOKEN[-2:]
    send = lambda pcm: sock.send(2, pcm.astype("<i2").tobytes())
    await stream_audio(send, quiet(2.0))
    DG["texts"].append("hola")
    n = len(peer.items)
    end = await stream_audio(send, np.concatenate([tone(0.6), quiet(0.05)]))
    await stream_audio(send, quiet(0.6))
    await peer.wait(lambda op, d: op == 1 and d == {"type": "partial", "text": "es"}, n)
    await peer.wait(lambda op, d: op == 1 and d == {"type": "transcript", "text": "hola"}, n)
    got = await peer.wait(lambda op, d: op == 2, n)
    LAT["browser_cloud_client"] = got - end
    speaking = next(d for _, op, d in peer.items[n:] if op == 1 and d.get("type") == "speaking")
    LAT["browser_cloud_server"] = speaking["latency_ms"] / 1000
    reply = next(d for _, op, d in peer.items[n:] if op == 1 and d.get("type") == "reply")
    assert reply["status"] == 200 and "¿Qué gusto?" in reply["body"]["messages"][0]
    # barge-in por un parcial de Deepgram mientras habla
    await asyncio.sleep(0.2)
    n = len(peer.items)
    await stream_audio(send, np.concatenate([tone(0.5), quiet(0.5)]))
    await peer.wait(lambda op, d: op == 1 and d == {"type": "clear"}, n)
    sock.send(1, b'{"type": "stop"}')
    await peer.wait(lambda op, d: op == 8)
    await asyncio.sleep(0.3)
    assert DG["closed"]
    for _ in range(50):                                         # costos de la charla: segundos de ASR y letras de TTS
        kinds = {(i.get("kind"), i.get("provider")) for i in costs.session_usage(DGA, sid)["items"]}
        if {("asr", "deepgram"), ("tts", "elevenlabs")} <= kinds:
            break
        time.sleep(0.1)
    assert {("asr", "deepgram"), ("tts", "elevenlabs")} <= kinds, kinds
    # sin sesión de start no hace nada; con un mensaje que no es JSON contesta error
    sock = await ws("/api/v1/bots/%s/voice/ws" % DGA)
    peer = Peer(sock)
    sock.send(1, b"hola")
    await peer.wait(lambda op, d: op == 1 and d.get("type") == "error")
    sock.close()
    assert await refused("/api/v1/bots/%s/voice/ws" % DGA, {"Origin": "https://malo.example.com"})


async def main():
    dg = await asyncio.start_server(fake_deepgram, "127.0.0.1", 0)
    os.environ["PARLA_DEEPGRAM_BASE_URL"] = "http://127.0.0.1:%d" % dg.sockets[0].getsockname()[1]
    await twilio()
    await jambonz()
    await browser()
    dg.close()


asyncio.run(main())
metrics = telemetry.render()
assert 'parla_voice_e2e_latency_seconds_count{asr="local",channel="phone",tts="local"}' in metrics, [m for m in metrics.splitlines() if "voice" in m]
assert 'parla_voice_e2e_latency_seconds_count{asr="deepgram",channel="web",tts="elevenlabs"} 1' in metrics
assert 'parla_voice_barge_ins_total{channel="phone"}' in metrics and 'parla_voice_barge_ins_total{channel="web"} 1' in metrics
print("latencias (fin de la voz -> primer audio, proveedores falsos): " + ", ".join("%s %.0f ms" % (k, v * 1000) for k, v in LAT.items()), flush=True)
print("ok: voz en tiempo real (Twilio Media Streams, jambonz listen, navegador, Deepgram live, TTS en streaming, barge-in, DTMF, handoff)", flush=True)
os._exit(0)
