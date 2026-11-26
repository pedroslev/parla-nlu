"""Voz en tiempo real: audio en vivo por WebSocket, respuesta apenas está la primera oración y barge-in de verdad.

Tres puntas, un mismo motor (Call):
- Navegador: /api/v1/bots/{bot}/voice/ws. Binario PCM16 LE 16 kHz de ida y vuelta + mensajes JSON (docs/api.md).
  Mismas reglas que /ws (sesión, API key o widget público con su Origin).
- Twilio Media Streams: /api/v1/bots/{bot}/phone/twilio/stream (<Connect><Stream>). μ-law 8 kHz en base64, «clear»
  para cortar al bot, «dtmf». Firma X-Twilio-Signature del upgrade sobre la URL wss://.
- jambonz «listen»: /api/v1/bots/{bot}/phone/jambonz/stream?t=<token firmado>. L16 8 kHz binario de ida y vuelta,
  «killAudio» para cortar, «dtmf» por texto. Token del webhook (ya autenticado) + HTTP basic si está cargado.

Motor: ASR en streaming (Deepgram live con parciales y endpointing; si no, VAD por energía + el ASR de siempre por
frase: faster-whisper local u otro proveedor) -> turno (los tokens de la IA llegan por el bus) -> oraciones -> TTS
por oración (streaming HTTP con OpenAI, Deepgram Aura y ElevenLabs; piper, Google y la caché de frases fijas, por
oración entera) -> audio del canal. Si la persona habla mientras suena el bot: se vacía el audio, se corta la IA
(llm.CANCEL) y queda anotado en el historial.
Config del agente: "voice": {"stream": {"barge_in": true, "barge_in_chars": 2, "silence_ms": 600, "idle_seconds": 8}}.
"""
import asyncio
import base64
import bisect
import contextlib
import hmac
import io
import json
import os
import re
import ssl
import struct
import threading
import time
import urllib.parse
import wave

import numpy as np

from . import aserver, bus, channels, costs, llm, phone, telemetry, vault, voice

RATE = 16000                    # todo el motor trabaja en PCM16 mono 16 kHz
FRAME = 320                     # 20 ms
STREAMING_TTS = ("openai", "deepgram", "elevenlabs")
TTS_RATES = {"openai": 24000, "deepgram": 16000, "elevenlabs": 16000}
MAX_UTTERANCE = 30              # segundos: una frase más larga se corta y se transcribe igual
MAX_CALL = float(os.environ.get("PARLA_VOICE_MAX_SECONDS") or 3600)     # una llamada (o un widget abierto) no transmite para siempre


# ---------- audio (sin audioop, que no está en 3.13) ----------

def _ulaw_table():
    u = ~np.arange(256) & 0xFF
    s = (((u & 0x0F) << 3) + 0x84 << ((u >> 4) & 7)) - 0x84
    return np.where(u & 0x80, -s, s).astype(np.int16)


ULAW = _ulaw_table()


def ulaw_decode(data):
    return ULAW[np.frombuffer(data, np.uint8)]


def ulaw_encode(pcm):
    """G.711 μ-law (como audioop.lin2ulaw)."""
    x = np.asarray(pcm, np.int32)
    sign = (x < 0).astype(np.int32)
    x = np.minimum(np.abs(x), 32635) + 0x84
    exp = np.floor(np.log2(x)).astype(np.int32) - 7
    return (~((sign << 7) | (exp << 4) | ((x >> (exp + 3)) & 0x0F)) & 0xFF).astype(np.uint8).tobytes()


def resample(pcm, src, dst):
    """Lineal; al bajar, un promedio móvil antes como antialias. ponytail: suficiente para voz telefónica; un
    polifásico (scipy.signal.resample_poly) si hiciera falta calidad de música."""
    pcm = np.asarray(pcm, np.int16)
    if src == dst or not len(pcm):
        return pcm
    x = pcm.astype(np.float32)
    k = int(round(src / dst))
    if k > 1:
        x = np.convolve(x, np.ones(k, np.float32) / k, "same")
    n = int(round(len(x) * dst / src))
    out = np.interp(np.arange(n) * (src / dst), np.arange(len(x)), x)
    return np.clip(np.round(out), -32768, 32767).astype(np.int16)


def from_wav(data):
    with wave.open(io.BytesIO(data)) as w:
        rate, channels_, width, frames = w.getframerate(), w.getnchannels(), w.getsampwidth(), w.readframes(w.getnframes())
    if width != 2:
        raise ValueError("WAV de %d bits: se espera 16" % (width * 8))
    pcm = np.frombuffer(frames, "<i2")
    if channels_ > 1:
        pcm = pcm.reshape(-1, channels_).mean(axis=1).astype(np.int16)
    return pcm, rate


def to_wav(pcm, rate=RATE):
    out = io.BytesIO()
    with wave.open(out, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(np.asarray(pcm, "<i2").tobytes())
    return out.getvalue()


# ---------- VAD ----------

class VAD:
    """Energía por cuadro de 20 ms con piso de ruido adaptativo. push(cuadro) -> "start" | "end" | None.
    ponytail: con mucho ruido de fondo corta mal -> webrtcvad o silero si hace falta."""

    def __init__(self, start_ms=200, silence_ms=600, level=None):
        self.start_ms, self.silence_ms, self.level = start_ms, silence_ms, level
        self.floor, self.on, self.loud, self.quiet = 100.0, False, 0, 0

    def push(self, frame):
        rms = float(np.sqrt(np.mean(np.asarray(frame, np.float32) ** 2))) if len(frame) else 0.0
        loud = rms > (self.level or max(500.0, self.floor * 3))      # 500 ≈ -36 dBFS
        if not self.on:
            if not loud:
                self.floor = self.floor * 0.95 + rms * 0.05
            self.loud = self.loud + 20 if loud else max(0, self.loud - 10)      # aguanta las pausas entre sílabas
            if self.loud >= self.start_ms:
                self.on, self.quiet = True, 0
                return "start"
            return None
        self.quiet = 0 if loud else self.quiet + 20
        if self.quiet >= self.silence_ms:
            self.on, self.loud = False, 0
            return "end"
        return None


# ---------- cliente WebSocket mínimo (para Deepgram) ----------

class WSClient:
    def __init__(self, reader, writer):
        self.reader, self.writer = reader, writer

    @classmethod
    async def connect(cls, url, headers, timeout=10):
        u = urllib.parse.urlsplit(url)
        tls = u.scheme == "wss"
        reader, writer = await asyncio.wait_for(asyncio.open_connection(
            u.hostname, u.port or (443 if tls else 80), ssl=ssl.create_default_context() if tls else None, limit=2 ** 22), timeout)
        key = base64.b64encode(os.urandom(16)).decode()
        writer.write(("GET %s HTTP/1.1\r\nHost: %s\r\nUpgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Key: %s\r\n"
                      "Sec-WebSocket-Version: 13\r\n%s\r\n" % (u.path + ("?" + u.query if u.query else ""), u.netloc, key,
                                                             "".join("%s: %s\r\n" % kv for kv in headers.items()))).encode())
        head = await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), timeout)
        line = head.split(b"\r\n", 1)[0].decode("latin-1")
        if " 101 " not in line + " ":
            writer.close()
            raise ValueError("el proveedor rechazó el WebSocket: %s" % line[:80])
        return cls(reader, writer)

    def send(self, op, data):
        n, mask = len(data), os.urandom(4)
        size = bytes([0x80 | n]) if n < 126 else b"\xfe" + struct.pack("!H", n) if n < 65536 else b"\xff" + struct.pack("!Q", n)
        body = (np.frombuffer(data, np.uint8) ^ np.resize(np.frombuffer(mask, np.uint8), n)).tobytes() if n else b""
        self.writer.write(bytes([0x80 | op]) + size + mask + body)

    async def messages(self):
        """(opcode, datos) de lo que manda el servidor (sin máscara); termina al cerrarse."""
        buf, kind = b"", 1
        while True:
            b1, b2 = await self.reader.readexactly(2)
            n = b2 & 0x7F
            if n == 126:
                n = struct.unpack("!H", await self.reader.readexactly(2))[0]
            elif n == 127:
                n = struct.unpack("!Q", await self.reader.readexactly(8))[0]
            data, op = await self.reader.readexactly(n), b1 & 0x0F
            if op == 8:
                return
            if op == 9:
                self.send(10, data)
                continue
            if op in (1, 2):
                buf, kind = data, op
            elif op == 0:
                buf += data
            else:
                continue
            if b1 & 0x80:
                yield kind, buf

    def close(self):
        with contextlib.suppress(Exception):
            self.send(8, struct.pack("!H", 1000))
            self.writer.close()


# ---------- ASR en streaming ----------

class LocalASR:
    """VAD + el ASR por frase de siempre (faster-whisper, o el proveedor del agente con su API batch). Sin parciales:
    el barge-in lo dispara la voz que detecta el VAD. ponytail: sin decodificación parcial cada ~500 ms (con whisper
    base en CPU no da; con un proveedor pago, cuesta cada vez)."""
    partials = False

    def __init__(self, call):
        self.call, self.vad = call, VAD(silence_ms=call.silence_ms)
        self.pre, self.buf, self.rest, self.pos, self.last = [], None, np.zeros(0, np.int16), 0, None

    async def start(self):
        pass

    def feed(self, pcm):
        pcm = np.concatenate([self.rest, pcm])
        whole = len(pcm) // FRAME * FRAME
        self.rest = pcm[whole:]
        for i in range(0, whole, FRAME):
            frame = pcm[i:i + FRAME]
            self.pos += FRAME
            event = self.vad.push(frame)
            if self.buf is not None:
                self.buf.append(frame)
            else:
                self.pre = (self.pre + [frame])[-15:]                    # 300 ms de antes: no se pierde la primera sílaba
            if event == "start":
                self.buf, self.pre = list(self.pre), []
                self.call.heard("speech")
            elif event == "end" or (self.buf and len(self.buf) * FRAME >= MAX_UTTERANCE * RATE):
                audio, self.buf, self.vad.on = np.concatenate(self.buf), None, False
                end = (self.pos - (self.vad.quiet if event == "end" else 0) * RATE // 1000) / RATE
                self.last = asyncio.ensure_future(self._final(audio, end, self.last))

    async def _final(self, audio, end, before):
        try:
            text = await aserver.run(self.call.transcribe, audio)
        except Exception as error:  # noqa: BLE001 - sin modelo de voz: que se vea en Canales
            self.call.log(error)
            text = ""
        if before:
            await asyncio.wait({before})                              # en orden: una frase no se adelanta a la anterior
        if text:
            self.call.heard("final", text, end)

    async def close(self):
        pass


class DeepgramASR:
    """Deepgram live (wss://api.deepgram.com/v1/listen): parciales (interim_results), fin de frase (endpointing +
    utterance_end_ms), voz detectada (vad_events) y keyterm con las palabras del bot."""
    partials = True

    def __init__(self, call):
        self.call, self.conf, self.ws, self.task, self.seconds = call, call.asr_conf, None, None, 0.0

    async def start(self):
        key, model = voice._key(self.conf), self.conf.get("model") or voice.ASR_MODELS["deepgram"]
        query = [("model", model), ("language", voice._lang(self.call.lang)), ("encoding", "linear16"), ("sample_rate", RATE),
                 ("channels", 1), ("interim_results", "true"), ("endpointing", self.call.silence_ms), ("utterance_end_ms", 1000),
                 ("vad_events", "true"), ("smart_format", "true")]
        if model.startswith("nova-3"):
            query += [("keyterm", t) for t in voice._terms(self.call.hints)]
        url = re.sub(r"^http", "ws", voice._base("deepgram")) + "/v1/listen?" + urllib.parse.urlencode(query)
        self.ws = await WSClient.connect(url, {"Authorization": "Token " + key})
        self.task = asyncio.ensure_future(self._read())

    def feed(self, pcm):
        if self.ws:
            self.ws.send(2, np.asarray(pcm, "<i2").tobytes())
            self.seconds += len(pcm) / RATE

    async def _read(self):
        done = ""
        try:
            async for _, raw in self.ws.messages():
                try:
                    msg = json.loads(raw)
                except ValueError:
                    continue
                kind = msg.get("type")
                if kind == "SpeechStarted":
                    self.call.heard("speech")
                elif kind == "Results":
                    text = (((msg.get("channel") or {}).get("alternatives") or [{}])[0].get("transcript") or "").strip()
                    if msg.get("is_final"):
                        done = (done + " " + text).strip()
                        if msg.get("speech_final") and done:
                            self.call.heard("final", done, (msg.get("start") or 0) + (msg.get("duration") or 0))
                            done = ""
                        elif text:
                            self.call.heard("partial", done)
                    elif text:
                        self.call.heard("partial", (done + " " + text).strip())
                elif kind == "UtteranceEnd" and done:
                    self.call.heard("final", done, msg.get("last_word_end"))
                    done = ""
        except (asyncio.IncompleteReadError, ConnectionError):
            pass

    async def close(self):
        if self.ws:
            with contextlib.suppress(Exception):
                self.ws.send(1, b'{"type": "CloseStream"}')
                await self.ws.writer.drain()
            self.ws.close()
        if self.task:
            self.task.cancel()
        costs.record("asr", "deepgram", self.conf.get("model") or voice.ASR_MODELS["deepgram"], self.seconds / 60,
                     agent=self.call.agent["id"], session=self.call.sid, channel=self.call.channel)


# ---------- TTS por oración ----------

def speech(tts, text, language, stop):
    """(PCM16 bytes, frecuencia) por pedazos, en un hilo. Frase fija en caché, piper y Google: la oración entera
    (voice.speak, como siempre). OpenAI, Deepgram Aura y ElevenLabs: streaming HTTP, sale apenas llega el primer pedazo."""
    provider = (tts or {}).get("provider") or "local"
    if provider not in STREAMING_TTS or voice._cached(voice._lang(language), text, tts).exists():
        pcm, rate = from_wav(voice.speak(text, language, tts=tts))
        yield pcm.tobytes(), rate
        return
    key, lang, model, name = voice._key(tts), voice._lang(language), tts.get("model") or voice.TTS_MODELS.get(provider), tts.get("voice")
    headers = {"Content-Type": "application/json"}
    if provider == "openai":
        url = voice._base("openai") + "/v1/audio/speech"
        body = {"model": model, "input": text, "voice": name or voice.TTS_VOICES["openai"], "response_format": "pcm"}
        headers["Authorization"] = "Bearer " + key
    elif provider == "deepgram":
        model = name or voice.TTS_VOICES["deepgram"].get(lang)
        if not model:
            raise ValueError("Deepgram no tiene voces en ese idioma: elegí otra voz u otro proveedor.")
        url = voice._base("deepgram") + "/v1/speak?" + urllib.parse.urlencode({"model": model, "encoding": "linear16", "sample_rate": RATE, "container": "none"})
        body, headers["Authorization"] = {"text": text}, "Token " + key
    else:
        url = "%s/v1/text-to-speech/%s/stream?output_format=pcm_16000" % (voice._base("elevenlabs"), urllib.parse.quote(name or voice.TTS_VOICES["elevenlabs"], safe=""))
        body = {"text": text, "model_id": model, **({"language_code": lang} if "flash_v2_5" in model or "turbo_v2_5" in model else {})}
        headers["xi-api-key"] = key
    with telemetry.span("tts", kind="client", metric="parla_tts_duration_seconds", labels={"provider": provider},
                        **{"parla.voice.provider": provider, "parla.text.chars": len(text)}):
        response = llm.fetch(url, json.dumps(body).encode(), headers, voice.TIMEOUT, key, method="POST")
        costs.record("tts", provider, model or "default", len(text))
        with response as r:
            carry = b""
            while not stop.is_set():
                chunk = r.read1(8192) if hasattr(r, "read1") else r.read(8192)
                if not chunk:
                    break
                chunk, even = carry + chunk, (len(carry) + len(chunk)) // 2 * 2
                carry = chunk[even:]
                if even:
                    yield chunk[:even], TTS_RATES[provider]


# ---------- el motor ----------

class Call:
    """Una conversación de voz en vivo. out: send(pcm16k), clear(), event(dict), end(plan).
    turn: async (kind, text) -> {"say": [frases], "then": "gather"|"dial"|"hangup", "lang", "digits", "hints"}."""

    def __init__(self, agent, sid, channel, out, turn, lang="es", hints=None, finish_key="#", serial=None, idle=True):
        self.agent, self.sid, self.channel, self.out, self.turn = agent, sid, channel, out, turn
        self.lang, self.hints, self.base_hints, self.finish_key, self.serial = lang or "es", hints, hints, finish_key, serial
        conf = voice.settings(agent)
        self.asr_conf, self.tts_conf = conf["asr"], conf["tts"]
        opts = (agent.get("voice") or {}).get("stream") if isinstance(agent.get("voice"), dict) else None
        opts = opts if isinstance(opts, dict) else {}
        deepgram = self.asr_conf["provider"] == "deepgram"
        self.barge_on = opts.get("barge_in", True) is not False
        self.min_chars = int(opts.get("barge_in_chars", 2))
        self.silence_ms = int(opts.get("silence_ms") or (300 if deepgram else 600))
        self.idle_s = float(opts.get("idle_seconds") or 8) if idle else 0
        self.asr = DeepgramASR(self) if deepgram else LocalASR(self)
        self.labels = {"channel": channel, "asr": self.asr_conf["provider"], "tts": self.tts_conf["provider"]}
        self.topic = "session:%s:%s" % (agent["id"], sid)
        self.lock, self.speaker, self.tasks = asyncio.Lock(), None, set()
        self.busy = self.cut = self.closed = False
        self.cut_heard, self.sent, self.last, self.latency = None, [], None, None
        self.playing_until, self.fed, self.clock, self.digits, self.dtimer = 0.0, 0.0, [], "", None
        self.idle_from = time.monotonic()

    def log(self, error):
        channels._log(self.agent["id"], "phone" if self.channel == "phone" else "web", llm.mask(error, self.asr_conf.get("api_key")))

    def spawn(self, coro):
        task = asyncio.ensure_future(coro)
        self.tasks.add(task)
        task.add_done_callback(self.tasks.discard)
        return task

    async def begin(self, greet=None):
        try:
            await self.asr.start()
        except Exception as error:  # noqa: BLE001 - Deepgram no conecta: VAD local + el ASR por frase
            self.log(error)
            self.asr = LocalASR(self)
        if greet:
            self.spawn(self.respond(plan=greet))
        if self.idle_s:
            self.spawn(self._idle())

    # entrada
    def feed(self, pcm):
        self.fed += len(pcm) / RATE
        if self.fed > MAX_CALL:
            raise aserver.Closed(1008, "llamada demasiado larga")
        self.clock.append((self.fed, time.monotonic()))
        if len(self.clock) > 6000:
            del self.clock[:3000]
        self.asr.feed(pcm)

    def wall(self, seconds):
        """Hora (monotonic) en que llegó el audio del segundo `seconds` del stream: el fin real de lo que dijo."""
        if seconds is None or not self.clock:
            return time.monotonic()
        return self.clock[min(bisect.bisect_left(self.clock, (seconds,)), len(self.clock) - 1)][1]

    def speaking(self):
        return bool(self.speaker and not self.speaker.done()) or time.monotonic() < self.playing_until

    def heard(self, kind, text="", end=None):
        self.idle_from = time.monotonic()
        if self.closed:
            return
        if kind == "speech":
            if self.speaking() and not self.asr.partials:
                self.barge()
        elif kind == "partial":
            self.out.event({"type": "partial", "text": text})
            if self.speaking() and len(text.strip()) >= self.min_chars:
                self.barge()
        elif kind == "final" and text.strip():
            if self.speaking():
                self.barge()
            self.out.event({"type": "transcript", "text": text.strip()})
            self.spawn(self.respond("message", text.strip(), self.wall(end)))

    def digit(self, d):
        self.idle_from = time.monotonic()
        if self.speaking():
            self.barge()
        if self.dtimer:
            self.dtimer.cancel()
        if d == self.finish_key:
            digits, self.digits = self.digits, ""
        else:
            self.digits += d
            if (self.last or {}).get("digits") != 1:      # varios dígitos (un DNI): hasta «#» o 2 s sin teclas
                self.dtimer = asyncio.get_running_loop().call_later(2, lambda: self.digit(self.finish_key))
                return
            digits, self.digits = self.digits, ""
        if digits:
            self.spawn(self.respond("digits", digits, time.monotonic()))

    def transcribe(self, pcm):
        """En un hilo del pool (el de modelos de voz.py lo reparte: sin lock global)."""
        with costs.scope(self.agent["id"], self.sid, self.channel):
            return voice.transcribe(to_wav(pcm), "audio/wav", self.lang, self.hints, self.asr_conf)["text"]

    # barge-in
    def barge(self):
        if not self.barge_on:
            return
        now = time.monotonic()
        heard = [text for at, text in self.sent if at <= now]
        self.out.clear()
        self.playing_until = 0.0
        if self.speaker and not self.speaker.done():
            self.speaker.cancel()
        self.cut = True
        telemetry.count("parla_voice_barge_ins_total", channel=self.channel)
        if self.busy:
            llm.CANCEL.add(self.topic)                    # la IA deja de escribir (llm._streamer)
            self.cut_heard = heard
        else:
            self.spawn(self.note(heard))

    async def note(self, heard):
        app = aserver._app()

        def write():
            with channels._session_lock(self.agent["id"] + "/" + self.sid):
                record = app.load_session(self.agent["id"], self.sid)
                if record:
                    said = " ".join(heard)
                    record["history"].append({"from": "event", "at": app.now(), "interrupted": True,
                                              "text": "La persona interrumpió al bot" + (" después de «%s»" % said[:200] if said else "")})
                    app.save_session(self.agent["id"], record)
        async with aserver.serial(self.serial):
            await aserver.run(write)

    # salida
    async def tts(self, text):
        loop, queue, stop = asyncio.get_running_loop(), asyncio.Queue(), threading.Event()

        def work():
            try:
                with costs.scope(self.agent["id"], self.sid, self.channel):
                    for data, rate in speech(self.tts_conf, text, self.lang, stop):
                        loop.call_soon_threadsafe(queue.put_nowait, resample(np.frombuffer(data, "<i2"), rate, RATE))
            except Exception as error:  # noqa: BLE001
                loop.call_soon_threadsafe(queue.put_nowait, error)
            finally:
                loop.call_soon_threadsafe(queue.put_nowait, None)
        aserver.POOL.submit(work)
        try:
            while True:
                item = await queue.get()
                if item is None:
                    return
                if isinstance(item, Exception):
                    self.log(item)
                    return
                yield item
        finally:
            stop.set()

    async def _speak(self, queue, t_end):
        first = True
        while True:
            text = await queue.get()
            if text is None:
                return
            t0, started = time.monotonic(), False
            async for pcm in self.tts(text):
                now = time.monotonic()
                if not started:
                    started = True
                    telemetry.observe("parla_voice_tts_first_byte_seconds", now - t0, provider=self.labels["tts"])
                    self.sent.append((max(now, self.playing_until), text))
                if first:
                    first = False
                    if t_end:
                        self.latency = now - t_end
                        telemetry.observe("parla_voice_e2e_latency_seconds", self.latency, **self.labels)
                    self.out.event({"type": "speaking", "latency_ms": int(self.latency * 1000) if t_end else None})
                self.out.send(pcm)
                self.playing_until = max(now, self.playing_until) + len(pcm) / RATE

    async def respond(self, kind=None, text=None, t_end=None, plan=None):
        """Un turno (o, con plan, lo que ya se decidió: el saludo). Habla cada oración apenas está."""
        async with self.lock:
            if self.closed:
                return
            self.busy, self.cut, self.cut_heard, self.sent = plan is None, False, None, []
            queue, queued = asyncio.Queue(), set()
            self.speaker = asyncio.ensure_future(self._speak(queue, t_end))

            def put(sentence):
                sentence = phone.speakable(sentence)
                if sentence and sentence not in queued and not self.cut:
                    queued.add(sentence)
                    queue.put_nowait(sentence)
            try:
                if plan is None:
                    with bus.subscribe(self.topic) as events:     # con alguien escuchando, la IA manda tokens (server.converse)
                        job = asyncio.ensure_future(self.turn(kind, text))
                        buf, live = "", True
                        while not job.done():
                            get = asyncio.ensure_future(events.get())
                            await asyncio.wait({job, get}, return_when=asyncio.FIRST_COMPLETED)
                            if not get.done():
                                get.cancel()
                                continue
                            event = get.result()
                            if event.get("type") == "delta" and live:
                                parts = voice.SENTENCES.split(buf + event.get("text", ""))
                                buf = parts.pop()
                                for part in parts:
                                    put(part)
                            elif event.get("type") == "replace":      # los guardrails cambiaron el texto: vale el final
                                live = False
                        plan = job.result()
            except Exception as error:  # noqa: BLE001
                self.log(error)
                plan = {"say": [], "then": "gather"}
            finally:
                llm.CANCEL.discard(self.topic)
                self.busy = False
            self.last, self.lang = plan, plan.get("lang") or self.lang
            self.hints = plan.get("hints") or self.base_hints
            for chunk in plan.get("say") or []:
                for sentence in voice.sentences(chunk):
                    put(sentence)
            queue.put_nowait(None)
            await asyncio.wait({self.speaker})
            if self.cut_heard is not None:
                await self.note(self.cut_heard)
                self.cut_heard = None
            self.idle_from = time.monotonic()
            if plan.get("then") in ("dial", "hangup"):
                await asyncio.sleep(max(0.0, self.playing_until - time.monotonic()))     # que termine de sonar
                self.closed = True
                self.out.end(plan)

    async def _idle(self):
        """Teléfono: si no dice nada, el bot repregunta (y a la tercera corta), como el Gather."""
        while not self.closed:
            await asyncio.sleep(0.5)
            vad_on = getattr(getattr(self.asr, "vad", None), "on", False)
            quiet_from = max(self.idle_from, self.playing_until)
            if not (self.busy or self.speaking() or vad_on or self.lock.locked()) and time.monotonic() - quiet_from > self.idle_s:
                self.idle_from = time.monotonic()
                await self.respond("silence")

    async def close(self):
        self.closed = True
        if self.dtimer:
            self.dtimer.cancel()
        for task in [self.speaker, *self.tasks]:
            if task:
                task.cancel()
        llm.CANCEL.discard(self.topic)
        await self.asr.close()


# ---------- puntas ----------

class _Out:
    def __init__(self, writer):
        self.writer = writer

    def text(self, data):
        self.writer.write(aserver.frame(1, json.dumps(data, ensure_ascii=False).encode()))

    def event(self, data):
        pass

    def close(self):
        self.writer.write(aserver.frame(8, struct.pack("!H", 1000)))


class TwilioOut(_Out):
    def __init__(self, writer, stream, sid):
        super().__init__(writer)
        self.stream, self.sid = stream, sid

    def send(self, pcm):
        self.text({"event": "media", "streamSid": self.stream,
                   "media": {"payload": base64.b64encode(ulaw_encode(resample(pcm, RATE, 8000))).decode()}})

    def clear(self):
        self.text({"event": "clear", "streamSid": self.stream})

    def end(self, plan):
        phone.stash(phone._after, self.sid, plan)   # al cerrarse el stream, <Redirect> pide /after: Dial o Hangup
        self.close()


class JambonzOut(_Out):
    def __init__(self, writer, sid):
        super().__init__(writer)
        self.sid = sid

    def send(self, pcm):
        self.writer.write(aserver.frame(2, resample(pcm, RATE, 8000).astype("<i2").tobytes()))

    def clear(self):
        self.text({"type": "killAudio"})

    def end(self, plan):
        phone.stash(phone._after, self.sid, plan)   # «disconnect» termina el listen y jambonz llama a su actionHook (/after)
        self.text({"type": "disconnect"})


class BrowserOut(_Out):
    def send(self, pcm):
        self.writer.write(aserver.frame(2, np.asarray(pcm, "<i2").tobytes()))

    def clear(self):
        self.text({"type": "clear"})

    def event(self, data):
        self.text(data)

    def end(self, plan):
        self.text({"type": "end", "then": plan.get("then")})


def _deny(writer, status=403):
    writer.write(aserver._simple(status, "pedido rechazado"))


async def serve(reader, writer, headers, peer, target, ref, provider):
    if provider:
        return await _phone(reader, writer, headers, target, ref, provider)
    return await _browser(reader, writer, headers, peer, ref)


async def _session(reader, writer, on_text, on_binary, call_of):
    aserver.STATS["voice"] += 1
    code = 1000
    try:
        async for kind, data in aserver.messages(reader, binary=True):
            if kind == "ping":
                writer.write(aserver.frame(10, data))
            elif kind == "binary":
                on_binary(data)
            elif await on_text(data) is False:
                break
            await writer.drain()
    except aserver.Closed as closed:
        code = closed.code
    except (asyncio.TimeoutError, asyncio.IncompleteReadError, ConnectionError):
        code = 1001
    finally:
        aserver.STATS["voice"] -= 1
        if call_of():
            await call_of().close()
        with contextlib.suppress(Exception):
            writer.write(aserver.frame(8, struct.pack("!H", code)))
            await writer.drain()


async def _phone(reader, writer, headers, target, ref, provider):
    app = aserver._app()
    agent = await aserver.run(app.find_bot, urllib.parse.unquote(ref))
    conf = channels.config(agent, "phone") if agent else {}
    if not agent or not conf.get("enabled") or (conf.get("provider") or "twilio") != provider or not phone.streaming(conf) \
            or not aserver.handshake_ok(headers):
        return _deny(writer)
    agent_id, query = agent["id"], dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(target).query))
    if provider == "twilio":           # firma del upgrade: HMAC-SHA1 de la URL (wss://…; también se acepta https://…)
        token, url = channels._secret(agent_id, "TWILIO_AUTH_TOKEN"), channels.public_url(agent) + target
        ok, expected = any(phone.twilio_ok(token, u, [], headers.get("X-Twilio-Signature")) for u in (re.sub(r"^http", "ws", url), url)), None
    else:
        expected = phone.stream_sid(agent_id, query.get("t"))
        keys = await aserver.run(vault.values, agent_id)
        user, password = keys.get("JAMBONZ_BASIC_USER"), keys.get("JAMBONZ_BASIC_PASSWORD")
        want = "Basic " + base64.b64encode(("%s:%s" % (user, password)).encode()).decode() if user and password else None
        ok = expected is not None and (not want or hmac.compare_digest(str(headers.get("Authorization") or "").encode(), want.encode()))
    if not ok:
        return _deny(writer)
    aserver.upgrade(writer, headers)
    hints = await aserver.run(app.vocabulary, agent)
    state = {"call": None}

    def make(sid, out):
        greet = phone._greet.pop(sid, None)
        lang = (greet or {}).get("lang") or conf.get("language") or "es"

        async def turn(kind, text):
            return await aserver.run(phone.stream_turn, agent, conf, sid, kind, text)
        call = Call(agent, sid, "phone", out, turn, lang, (greet or {}).get("hints") or hints, str(conf.get("finish_on_key") or "#"))
        call.base_hints = hints
        state["call"] = call
        return call, greet

    async def on_text(raw):
        try:
            msg = json.loads(raw)
        except ValueError:
            return None
        msg = msg if isinstance(msg, dict) else {}
        call = state["call"]
        if provider == "twilio":
            event = msg.get("event")
            if event == "start" and not call:
                start = msg.get("start") or {}
                call_sid = str(start.get("callSid") or "")
                if not phone.CALL_ID.fullmatch(call_sid):
                    return False
                sid = "call-" + call_sid
                call, greet = make(sid, TwilioOut(writer, msg.get("streamSid") or start.get("streamSid"), sid))
                await call.begin(greet)
            elif event == "media" and call:
                call.feed(resample(ulaw_decode(base64.b64decode((msg.get("media") or {}).get("payload") or "")), 8000, RATE))
            elif event == "dtmf" and call:
                call.digit(str((msg.get("dtmf") or {}).get("digit") or "")[:1])
            elif event == "stop":
                return False
        elif not call:                     # jambonz: el primer texto son los datos de la llamada
            call_sid = str(msg.get("callSid") or msg.get("call_sid") or "")
            if not phone.CALL_ID.fullmatch(call_sid) or "call-" + call_sid != expected:
                return False
            state["rate"] = int(msg.get("sampleRate") or 8000)
            call, greet = make(expected, JambonzOut(writer, expected))
            await call.begin(greet)
        elif msg.get("event") == "dtmf":
            call.digit(str(msg.get("dtmf") or "")[:1])
        return None

    def on_binary(data):
        if provider == "jambonz" and state["call"]:
            state["call"].feed(resample(np.frombuffer(data[:len(data) // 2 * 2], "<i2"), state.get("rate", 8000), RATE))

    await _session(reader, writer, on_text, on_binary, lambda: state["call"])


async def _browser(reader, writer, headers, peer, ref):
    if not await aserver.authorize(writer, headers, peer, ref):
        return
    app = aserver._app()
    agent = await aserver.run(app.find_bot, urllib.parse.unquote(ref))
    if not agent:
        return _deny(writer, 404)
    aserver.upgrade(writer, headers)
    out = BrowserOut(writer)
    out.text({"type": "ready", "rate": RATE})
    state = {"call": None}
    hints = await aserver.run(app.vocabulary, agent)

    async def on_text(raw):
        try:
            msg = json.loads(raw)
            msg = msg if isinstance(msg, dict) else {}
        except ValueError:
            msg = {}
        if msg.get("type") == "stop":
            return False
        if msg.get("type") != "start" or state["call"] or not isinstance(msg.get("sessionId"), str):
            out.text({"type": "error", "error": "mandá primero {\"type\": \"start\", \"sessionId\": …}"})
            return None
        sid = msg["sessionId"][:200]
        extra = {k: msg[k] for k in ("channel", "environment") if isinstance(msg.get(k), str)}

        async def turn(kind, text):            # por el Handler, como POST /events: mismas reglas (widget público incluido)
            payload = json.dumps(dict(extra, type="message", sessionId=sid, text=text)).encode()
            h = aserver._headers(headers, Content_Type="application/json", Content_Length=str(len(payload)))
            async with aserver.serial((ref, sid)):
                status, _, body = aserver._parse(await aserver.run(aserver.call, "POST", "/api/v1/bots/%s/events" % ref, h, payload, peer))
            out.text({"type": "reply", "status": status, "body": body})
            if status != 200 or not isinstance(body, dict):
                return {"say": [], "then": "gather"}
            return {"say": phone.lines(body.get("replies") or [], body.get("language")), "then": "gather", "lang": body.get("language")}
        call = state["call"] = Call(agent, sid, extra.get("channel") or "web", out, turn, str(msg.get("language") or "es"), hints,
                                    serial=(ref, sid), idle=False)
        greet = None
        if msg.get("replay"):                  # el saludo que ya está en la charla (lo escribió el bot): se dice en voz alta
            status, _, body = aserver._parse(await aserver.run(aserver.call, "GET", "/api/v1/bots/%s/sessions/%s/messages?after=0" % (
                ref, urllib.parse.quote(sid, safe="")), headers, b"", peer))
            items = (body or {}).get("messages") or [] if status == 200 else []
            tail = []
            for item in reversed(items):
                if item.get("from") == "user":
                    break
                if item.get("from") in ("bot", "human") and item.get("text"):
                    tail.insert(0, {"text": item["text"]})
            greet = {"say": phone.lines(tail, call.lang), "then": "gather"} if tail else None
        await call.begin(greet)
        return None

    def on_binary(data):
        if state["call"]:
            state["call"].feed(np.frombuffer(data[:len(data) // 2 * 2], "<i2"))

    await _session(reader, writer, on_text, on_binary, lambda: state["call"])
