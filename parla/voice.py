"""Voz: transcribir audio (ASR) y leer texto en voz alta (TTS). Por defecto todo local: faster-whisper (CPU int8) y
piper, nada en la nube. Cada agente puede elegir otro proveedor con su propia API key («voice» en el JSON del agente,
la key en «Claves»): OpenAI, Deepgram, ElevenLabs o Google Cloud. Todo TTS sale como WAV (lo que ya sirve Parla al
navegador, al widget y al <Play> del teléfono).

    "voice": {"asr": {"provider": "local" | "openai" | "deepgram" | "elevenlabs" | "google", "model", "api_key_secret"},
              "tts": {"provider": "local" | "openai" | "deepgram" | "elevenlabs" | "google", "voice", "model", "api_key_secret"}}
"""
import base64
import contextlib
import hashlib
import io
import json
import os
import queue
import re
import secrets
import subprocess
import threading
import time
import urllib.parse
import wave
from pathlib import Path

from . import DATA, costs, llm, telemetry, vault

MODELS = Path(DATA) / "models"
PIPER_DIR = MODELS / "piper"
TTS_CACHE = MODELS / "tts-cache"     # audios ya generados de frases fijas: <idioma>/<sha1 del texto>.wav
SENTENCES = re.compile(r"\n+|(?<=[.!?…])\s+")    # igual que static/voice.js: así lo pregenerado coincide con lo que pide
STT_MODEL = os.environ.get("PARLA_WHISPER", "base")   # "tiny" si la máquina es lenta
MAX_SECONDS = 60
# primera voz que se pueda bajar/cargar gana (rhasspy/piper-voices en HuggingFace)
VOICES = {"es": ["es_AR-daniela-high", "es_MX-claude-high", "es_ES-davefx-medium"],
          "pt": ["pt_BR-faber-medium"],
          "en": ["en_US-lessac-medium"]}
FFMPEG = next((p for p in ("/opt/homebrew/bin/ffmpeg", "/usr/local/bin/ffmpeg", "/usr/bin/ffmpeg") if os.path.exists(p)), "ffmpeg")

PROVIDERS = ("local", "openai", "deepgram", "elevenlabs", "google")
NAMES = {"openai": "OpenAI", "deepgram": "Deepgram", "elevenlabs": "ElevenLabs", "google": "Google Cloud"}
SECRETS = {"openai": "OPENAI_API_KEY", "deepgram": "DEEPGRAM_API_KEY", "elevenlabs": "ELEVENLABS_API_KEY", "google": "GOOGLE_API_KEY"}
# direcciones fijas; PARLA_<NOMBRE>_BASE_URL las cambia (pruebas con servidores falsos o un proxy propio)
HOSTS = {"openai": "https://api.openai.com", "deepgram": "https://api.deepgram.com", "elevenlabs": "https://api.elevenlabs.io",
         "google_speech": "https://speech.googleapis.com", "google_tts": "https://texttospeech.googleapis.com"}
ASR_MODELS = {"openai": "gpt-4o-mini-transcribe", "deepgram": "nova-3", "elevenlabs": "scribe_v3", "google": ""}
TTS_MODELS = {"openai": "gpt-4o-mini-tts-2025-12-15", "elevenlabs": "eleven_flash_v2_5"}
TTS_VOICES = {"openai": "coral", "elevenlabs": "JBFqnCBsd6RMkjVDRZzb",
              "deepgram": {"es": "aura-2-celeste-es", "en": "aura-2-thalia-en"}}
VOICE_LISTS = {"openai": ["alloy", "ash", "ballad", "coral", "echo", "fable", "onyx", "nova", "sage", "shimmer", "verse", "marin", "cedar"],
               "deepgram": ["aura-2-celeste-es", "aura-2-estrella-es", "aura-2-nestor-es", "aura-2-sirio-es", "aura-2-carina-es",
                            "aura-2-diana-es", "aura-2-javier-es", "aura-2-agustina-es", "aura-2-antonia-es", "aura-2-luciano-es",
                            "aura-2-olivia-es", "aura-2-silvia-es", "aura-2-valerio-es", "aura-2-alvaro-es", "aura-2-aquila-es",
                            "aura-2-selena-es", "aura-2-gloria-es", "aura-2-thalia-en", "aura-2-andromeda-en", "aura-2-helena-en",
                            "aura-2-apollo-en", "aura-2-arcas-en", "aura-2-aries-en", "aura-2-asteria-en", "aura-2-luna-en",
                            "aura-2-orion-en", "aura-2-zeus-en"]}
BCP47 = {"es": "es-US", "en": "en-US", "pt": "pt-BR"}
MAX_UPLOAD = 25_000_000          # bytes: lo que aceptan los proveedores (OpenAI corta en 25 MB)
TIMEOUT = 30                     # segundos por pedido a un proveedor de voz

# Un pool de PARLA_VOICE_WORKERS juegos de modelos (Whisper + voces de Piper): hasta N transcripciones o síntesis a la
# vez; cada juego se usa de a uno (los modelos no son seguros entre hilos). Cada juego ocupa su RAM (~0.5 GB Whisper small).
WORKERS = max(1, int(os.environ.get("PARLA_VOICE_WORKERS") or min(2, max(1, (os.cpu_count() or 4) // 4))))
_pool = queue.Queue()
_slots = [{"stt": None, "tts": {}} for _ in range(WORKERS)]
for _s in _slots:
    _pool.put(_s)
_loading = threading.Lock()
_stt = None                # el Whisper del primer juego (status)
_tts = {}                  # idioma -> PiperVoice del primer juego (status)


@contextlib.contextmanager
def _slot():
    slot = _pool.get()
    try:
        yield slot
    finally:
        _pool.put(slot)
_errors = {}


def _installed(mod):
    import importlib.util
    return importlib.util.find_spec(mod) is not None


def status():
    stt, tts = _installed("faster_whisper"), _installed("piper")
    voices = sorted(p.name[:-5] for p in PIPER_DIR.glob("*.onnx")) if PIPER_DIR.exists() else []
    hint = ("" if stt and tts else
            "Falta instalar: .venv/bin/pip install %s" % " ".join(n for n, ok in (("faster-whisper", stt), ("piper-tts", tts)) if not ok))
    if stt and tts and not (MODELS / "whisper").exists():
        hint = "La primera vez se bajan los modelos de voz (~150 MB), puede tardar un minuto."
    return {"stt": stt, "tts": tts, "hint": hint, "errors": dict(_errors),
            "models": {"stt": "faster-whisper " + STT_MODEL + " (int8, CPU)", "stt_loaded": _stt is not None,
                       "tts_voices": voices, "tts_loaded": sorted(_tts)}}


def _whisper(slot):
    global _stt
    if slot["stt"] is None:
        try:
            from faster_whisper import WhisperModel
        except ImportError:
            raise ValueError("La transcripción de voz no está instalada (faster-whisper).")
        with _loading:
            slot["stt"] = WhisperModel(STT_MODEL, device="cpu", compute_type="int8", download_root=str(MODELS / "whisper"))
        _stt = _stt or slot["stt"]
    return slot["stt"]


def _to_wav(audio_bytes):
    """Cualquier formato del navegador -> wav 16 kHz mono con ffmpeg (por si PyAV no lo abre)."""
    r = subprocess.run([FFMPEG, "-v", "error", "-i", "pipe:0", "-ac", "1", "-ar", "16000", "-f", "wav", "pipe:1"],
                       input=audio_bytes, capture_output=True, timeout=60)
    if r.returncode or not r.stdout:
        raise ValueError("No pude leer el audio (formato no reconocido).")
    return r.stdout


def _decode(audio_bytes):
    from faster_whisper import decode_audio
    try:
        return decode_audio(io.BytesIO(audio_bytes), sampling_rate=16000)
    except Exception:
        return decode_audio(io.BytesIO(_to_wav(audio_bytes)), sampling_rate=16000)


def transcribe(audio_bytes, mime="audio/webm", language="es", hint=None, asr=None):
    provider = (asr or {}).get("provider") or "local"
    provider = provider if provider in PROVIDERS else "other"
    with telemetry.span("asr", kind="internal" if provider == "local" else "client", metric="parla_asr_duration_seconds",
                        labels={"provider": provider}, **{"parla.voice.provider": provider, "parla.audio.bytes": len(audio_bytes or b"")}):
        return _transcribe(audio_bytes, mime, language, hint, asr)


def _transcribe(audio_bytes, mime, language, hint, asr):
    """hint: palabras del bot (valores de entidades) para que el ASR las escriba bien: «muzzarella», no «multareza».
    asr: settings(agent)["asr"]; sin él (o «local»), faster-whisper en esta compu."""
    if not audio_bytes or len(audio_bytes) < 200:
        raise ValueError("No llegó audio. Probá grabar de nuevo.")
    t0 = time.time()
    lang = (language or "es").split("-")[0].lower() or None
    if asr and asr.get("provider", "local") != "local":
        if len(audio_bytes) > MAX_UPLOAD:
            raise ValueError("El audio es muy largo (máximo %d segundos)." % MAX_SECONDS)
        text, seconds = _remote_asr(asr, audio_bytes, mime, language or "es", hint)
        costs.record("asr", asr["provider"], asr.get("model") or ASR_MODELS.get(asr["provider"]) or "default",
                     (seconds if seconds is not None else _seconds(audio_bytes) or 0) / 60)
        return {"text": text.strip(), "language": lang, "ms": int((time.time() - t0) * 1000), "provider": asr["provider"]}
    with _slot() as slot:
        model = _whisper(slot)
        samples = _decode(audio_bytes)
        seconds = len(samples) / 16000
        if seconds < 0.3:
            raise ValueError("El audio está vacío o es demasiado corto.")
        if seconds > MAX_SECONDS:
            raise ValueError("El audio es muy largo (máximo %d segundos)." % MAX_SECONDS)
        # hotwords y no initial_prompt: con la lista como prompt Whisper imita la lista («sí, sí», «no, no,», «el martes,»)
        # Sin initial_prompt: con la pregunta del bot como prompt, Whisper la repetía («¿En qué ciudad la quieres?» en
        # vez de «en Medellín»). Medido con 64 respuestas: hotwords 52/64, prompt 48/64, ambos 53/64 pero repitiendo.
        segments, info = model.transcribe(samples, language=lang, vad_filter=True, hotwords=(hint or None),
                                          condition_on_previous_text=False)
        # Whisper inventa con audio casi mudo («No, no, no, no»): fuera lo que el propio modelo marca como «no es voz»
        # o como repetición anormal
        kept = [s for s in segments if not (s.no_speech_prob > 0.6 and s.avg_logprob < -0.8) and s.compression_ratio < 2.4]
        text = " ".join(s.text.strip() for s in kept).strip()
    costs.record("asr", "local", "whisper-" + STT_MODEL, seconds / 60)
    return {"text": text, "language": info.language, "ms": int((time.time() - t0) * 1000), "provider": "local"}


def _seconds(audio):
    """Duración del audio para la cuenta de costos cuando el proveedor no la informa: WAV por el encabezado; lo demás
    decodificado (PyAV, viene con faster-whisper). None si no se puede."""
    try:
        if audio[:4] == b"RIFF":
            with wave.open(io.BytesIO(audio)) as w:
                return w.getnframes() / float(w.getframerate())
        return len(_decode(audio)) / 16000
    except Exception:  # noqa: BLE001 - sin decodificador: ese audio no se cuenta
        return None


def _voice(lang, slot):
    if lang in slot["tts"]:
        return slot["tts"][lang]
    try:
        from piper import PiperVoice
        from piper.download_voices import download_voice
    except ImportError:
        raise ValueError("La voz no está disponible: falta instalar piper-tts.")
    PIPER_DIR.mkdir(parents=True, exist_ok=True)
    for name in VOICES.get(lang, VOICES["es"]):
        onnx = PIPER_DIR / (name + ".onnx")
        try:
            with _loading:      # descargar y cargar de a uno: dos juegos no bajan la misma voz a la vez
                if not onnx.exists() or not (PIPER_DIR / (name + ".onnx.json")).exists():
                    download_voice(name, PIPER_DIR)
                slot["tts"][lang] = PiperVoice.load(str(onnx))
            _tts.setdefault(lang, slot["tts"][lang])
            _errors.pop("tts", None)
            return slot["tts"][lang]
        except Exception as e:   # descarga cortada o voz rota: borro y pruebo la siguiente
            _errors["tts"] = "%s: %s" % (name, e)
            for p in (onnx, PIPER_DIR / (name + ".onnx.json")):
                p.unlink(missing_ok=True)
    raise ValueError("La voz no está disponible en este momento (no pude bajar ni cargar el modelo de voz).")


def sentences(text):
    return [t.strip() for t in SENTENCES.split(text or "") if t.strip()]


def _lang(language):
    """«es-AR» -> «es»; un idioma sin voz habla (y se guarda en la caché) con la de español."""
    lang = (language or "es").split("-")[0].lower()
    return lang if lang in VOICES else "es"


def _cached(lang, text, tts=None):
    """Piper: <idioma>/<sha1>.wav (como siempre). Otro proveedor: <proveedor>-<hash de modelo y voz>/<idioma>/…, así
    cambiar de proveedor o de voz no sirve audio viejo."""
    folder = lang
    if tts and tts.get("provider", "local") != "local":
        folder = "%s-%s/%s" % (tts["provider"], hashlib.sha1(json.dumps([tts.get("model"), tts.get("voice")]).encode()).hexdigest()[:10], lang)
    return TTS_CACHE / folder / (hashlib.sha1(text.encode()).hexdigest() + ".wav")


def ready(tts=None):
    """¿Hay con qué hablar? Piper con alguna voz ya bajada, u otro proveedor con su API key."""
    if tts and tts.get("provider", "local") != "local":
        return bool(tts.get("api_key"))
    return any(PIPER_DIR.glob("*.onnx")) if PIPER_DIR.exists() else False


def prewarm(texts, language="es", tts=None):
    """Genera de antemano el audio de las frases sin variables ({{ }}) para que la llamada las diga al instante.
    Las frases con variables se generan en el momento y no se guardan (si no, la caché crece con cada charla).
    Devuelve cuántas generó. No lanza: si no hay voz instalada, no hace nada."""
    lang = _lang(language)
    done = 0
    try:
        for text in texts:
            for sentence in sentences(text):
                if "{{" in sentence or _cached(lang, sentence, tts).exists():
                    continue
                audio = speak(sentence, lang, keep=False, tts=tts)
                path = _cached(lang, sentence, tts)
                path.parent.mkdir(parents=True, exist_ok=True)
                tmp = path.with_suffix(".tmp")
                tmp.write_bytes(audio)
                tmp.replace(path)
                done += 1
    except Exception as error:  # noqa: BLE001 - sin piper o sin modelo: la llamada genera en el momento
        _errors["prewarm"] = llm.mask(error, (tts or {}).get("api_key"))
    return done


def speak(text, language="es", keep=True, tts=None):
    """WAV con el texto leído. tts: settings(agent)["tts"]; sin él (o «local»), piper en esta compu."""
    text = (text or "").strip()
    if not text:
        raise ValueError("No hay texto para leer.")
    lang = _lang(language)
    if keep:
        hit = _cached(lang, text, tts)
        if hit.exists():                     # frase fija pregenerada: al instante
            return hit.read_bytes()
    provider = (tts or {}).get("provider") or "local"
    provider = provider if provider in PROVIDERS else "other"
    with telemetry.span("tts", kind="internal" if provider == "local" else "client", metric="parla_tts_duration_seconds",
                        labels={"provider": provider}, **{"parla.voice.provider": provider, "parla.text.chars": len(text)}):
        if tts and tts.get("provider", "local") != "local":
            audio = _remote_tts(tts, text, language or lang)
            costs.record("tts", tts["provider"], tts.get("model") or TTS_MODELS.get(tts["provider"]) or tts.get("voice")
                         or (TTS_VOICES.get("deepgram", {}).get(lang) if tts["provider"] == "deepgram" else "") or "default", len(text))
            return audio
        costs.record("tts", "local", "piper", len(text))
        buf = io.BytesIO()
        with _slot() as slot:
            v = _voice(lang, slot)
            with wave.open(buf, "wb") as w:
                v.synthesize_wav(text, w)
        return buf.getvalue()


# ---------- proveedores con API key propia ----------

def settings(agent, override=None):
    """{"asr": {...}, "tts": {...}} del agente (o `override`, lo que manda la interfaz sin guardar), con la API key
    sacada del vault. Nunca del JSON."""
    conf = override if isinstance(override, dict) else (agent or {}).get("voice")
    conf = conf if isinstance(conf, dict) else {}
    out = {}
    for kind in ("asr", "tts"):
        part = {k: v for k, v in (conf.get(kind) if isinstance(conf.get(kind), dict) else {}).items() if v not in (None, "")}
        part.pop("api_key", None)
        part["provider"] = part.get("provider") if part.get("provider") in PROVIDERS else "local"
        if part["provider"] != "local":
            part.setdefault("api_key_secret", SECRETS[part["provider"]])
            if (agent or {}).get("id"):
                part["api_key"] = vault.values(agent["id"]).get(vault._normal(str(part["api_key_secret"])))
        out[kind] = part
    return out


def _base(name):
    return (os.environ.get("PARLA_%s_BASE_URL" % name.upper()) or HOSTS[name]).rstrip("/")


def _key(conf):
    if not conf.get("api_key"):
        raise ValueError("Falta la API key de %s: guardala en «Claves» como %s." % (NAMES[conf["provider"]], conf.get("api_key_secret")))
    return conf["api_key"]


def multipart(fields, files=()):
    """multipart/form-data con la biblioteca estándar. fields: [(nombre, valor)] (se pueden repetir);
    files: [(nombre, archivo, tipo, bytes)]. -> (cuerpo, Content-Type)."""
    boundary = "parla" + secrets.token_hex(12)
    out = io.BytesIO()
    for name, value in fields:
        out.write(('--%s\r\nContent-Disposition: form-data; name="%s"\r\n\r\n' % (boundary, name)).encode())
        out.write(str(value).encode() + b"\r\n")
    for name, filename, ctype, data in files:
        out.write(('--%s\r\nContent-Disposition: form-data; name="%s"; filename="%s"\r\nContent-Type: %s\r\n\r\n'
                   % (boundary, name, filename, ctype)).encode())
        out.write(data + b"\r\n")
    out.write(("--%s--\r\n" % boundary).encode())
    return out.getvalue(), "multipart/form-data; boundary=" + boundary


def _call(url, data, headers, key, as_json=True):
    response = llm.fetch(url, data, headers, TIMEOUT, key, method="POST" if data is not None else "GET")
    return llm.read_json(response, TIMEOUT) if as_json else _read(response)


def _read(response):
    with response as r:
        try:
            return r.read()
        except OSError:
            raise llm.LLMError("tardó más de %s s en contestar" % TIMEOUT) from None


def _terms(hint):
    """«muzzarella, napolitana» -> ["muzzarella", "napolitana"] (las palabras del bot como pistas)."""
    return [t.strip()[:50] for t in str(hint or "").split(",") if t.strip()][:100]


def _bcp(language):
    lang = (language or "es").lower()
    return language if "-" in lang else BCP47.get(lang, lang)


def _remote_asr(asr, audio, mime, language, hint):
    key, provider = _key(asr), asr["provider"]
    lang = language.split("-")[0].lower()
    model = asr.get("model") or ASR_MODELS[provider]
    ctype = (mime or "audio/webm").split(";")[0].strip() or "audio/webm"
    ext = {"mpeg": "mp3", "x-wav": "wav", "wave": "wav", "x-m4a": "m4a"}.get(ctype.split("/")[-1], ctype.split("/")[-1])
    if provider == "openai":
        fields = [("model", model), ("language", lang), ("response_format", "json")] + ([("prompt", hint)] if hint else [])
        body, form = multipart(fields, [("file", "audio." + ext, ctype, audio)])
        data = _call(_base("openai") + "/v1/audio/transcriptions", body, {"Content-Type": form, "Authorization": "Bearer " + key}, key)
        usage = data.get("usage") or {}       # whisper-1: {"type": "duration", "seconds"}; los gpt-4o-*: por tokens (sin duración)
        return data.get("text") or "", usage.get("seconds") if usage.get("type") == "duration" else None
    if provider == "deepgram":
        query = [("model", model), ("language", lang), ("smart_format", "true")]
        if model.startswith("nova-3"):                # keyterm: solo Nova-3 (keywords no anda con Nova-3)
            query += [("keyterm", t) for t in _terms(hint)]
        data = _call(_base("deepgram") + "/v1/listen?" + urllib.parse.urlencode(query), audio,
                     {"Content-Type": ctype, "Authorization": "Token " + key}, key)
        channels = (data.get("results") or {}).get("channels") or [{}]
        return ((channels[0].get("alternatives") or [{}])[0]).get("transcript") or "", (data.get("metadata") or {}).get("duration")
    if provider == "elevenlabs":
        fields = [("model_id", model), ("language_code", lang)] + [("keyterms", t) for t in _terms(hint)]
        body, form = multipart(fields, [("file", "audio." + ext, ctype, audio)])
        return _call(_base("elevenlabs") + "/v1/speech-to-text", body, {"Content-Type": form, "xi-api-key": key}, key).get("text") or "", None
    # google: Speech-to-Text v1. WAV/FLAC traen su frecuencia; webm/ogg del navegador son Opus a 48 kHz; lo demás -> WAV
    if audio[:4] == b"RIFF":
        encoding = {"encoding": "LINEAR16"}
    elif audio[:4] == b"\x1aE\xdf\xa3":
        encoding = {"encoding": "WEBM_OPUS", "sampleRateHertz": 48000}
    elif audio[:4] == b"OggS":
        encoding = {"encoding": "OGG_OPUS", "sampleRateHertz": 48000}
    else:
        audio, encoding = _to_wav(audio), {"encoding": "LINEAR16"}
    config = dict(encoding, languageCode=_bcp(language), **({"model": model} if model else {}))
    if _terms(hint):
        config["speechContexts"] = [{"phrases": _terms(hint)}]
    data = _call(_base("google_speech") + "/v1/speech:recognize",
                 json.dumps({"config": config, "audio": {"content": base64.b64encode(audio).decode()}}).encode(),
                 {"Content-Type": "application/json", "x-goog-api-key": key}, key)
    billed = (data.get("totalBilledTime") or "").rstrip("s")      # «3.5s»
    return (" ".join(((r.get("alternatives") or [{}])[0].get("transcript") or "").strip() for r in data.get("results") or []).strip(),
            float(billed) if billed.replace(".", "", 1).isdigit() else None)


def _wav(audio):
    """Reescribe el encabezado WAV (algunos lo mandan con largo «desconocido», como en streaming)."""
    if audio[:4] != b"RIFF":
        raise ValueError("El proveedor de voz no devolvió audio WAV.")
    try:
        with wave.open(io.BytesIO(audio)) as r:
            params, frames = r.getparams(), r.readframes(r.getnframes())
        out = io.BytesIO()
        with wave.open(out, "wb") as w:
            w.setparams(params)
            w.writeframes(frames)
        return out.getvalue()
    except (wave.Error, EOFError):
        return audio


def _remote_tts(tts, text, language):
    key, provider = _key(tts), tts["provider"]
    lang = _lang(language)
    model = tts.get("model") or TTS_MODELS.get(provider)
    voice = tts.get("voice")
    as_json = {"Content-Type": "application/json"}
    if provider == "openai":
        body = {"model": model, "input": text, "voice": voice or TTS_VOICES["openai"], "response_format": "wav"}
        audio = _call(_base("openai") + "/v1/audio/speech", json.dumps(body).encode(), dict(as_json, Authorization="Bearer " + key), key, False)
    elif provider == "deepgram":
        voice = voice or TTS_VOICES["deepgram"].get(lang)
        if not voice:
            raise ValueError("Deepgram no tiene voces en ese idioma: elegí otra voz u otro proveedor.")
        query = urllib.parse.urlencode({"model": voice, "encoding": "linear16", "container": "wav", "sample_rate": 24000})
        audio = _call(_base("deepgram") + "/v1/speak?" + query, json.dumps({"text": text}).encode(),
                      dict(as_json, Authorization="Token " + key), key, False)
    elif provider == "elevenlabs":
        body = {"text": text, "model_id": model}
        if "flash_v2_5" in model or "turbo_v2_5" in model:     # language_code solo en estos (multilingual_v2 lo rechaza)
            body["language_code"] = lang
        url = "%s/v1/text-to-speech/%s?output_format=wav_16000" % (_base("elevenlabs"), urllib.parse.quote(voice or TTS_VOICES["elevenlabs"], safe=""))
        audio = _call(url, json.dumps(body).encode(), dict(as_json, **{"xi-api-key": key}), key, False)
    else:   # google: LINEAR16 ya trae el encabezado WAV
        selection = {"languageCode": _bcp(language)} | ({"name": voice} if voice else {})
        body = {"input": {"text": text}, "voice": selection, "audioConfig": {"audioEncoding": "LINEAR16", "sampleRateHertz": 16000}}
        data = _call(_base("google_tts") + "/v1/text:synthesize", json.dumps(body).encode(), dict(as_json, **{"x-goog-api-key": key}), key)
        audio = base64.b64decode(data.get("audioContent") or "")
    return _wav(audio)


def voices(tts, language="es"):
    """Voces para elegir: [{id, name}]. ElevenLabs y Google las listan por API; OpenAI y Deepgram tienen una lista fija."""
    provider = (tts or {}).get("provider", "local")
    if provider == "local":
        return [{"id": v, "name": v} for v in VOICES.get(_lang(language), VOICES["es"])]
    if provider in VOICE_LISTS:
        lang = _lang(language)
        names = VOICE_LISTS[provider]
        if provider == "deepgram":
            names = [n for n in names if n.endswith("-" + lang)] or names
        return [{"id": n, "name": n} for n in names]
    key = _key(tts)
    if provider == "elevenlabs":
        data = _call(_base("elevenlabs") + "/v1/voices", None, {"xi-api-key": key}, key)
        return [{"id": v.get("voice_id"), "name": v.get("name") or v.get("voice_id")} for v in data.get("voices") or []]
    data = _call(_base("google_tts") + "/v1/voices?languageCode=" + urllib.parse.quote(_bcp(language)), None, {"x-goog-api-key": key}, key)
    return [{"id": v.get("name"), "name": v.get("name")} for v in data.get("voices") or []]
