"""Voz local: transcribir audio (faster-whisper, CPU int8) y leer texto en voz alta (piper). Nada en la nube."""
import hashlib
import io
import os
import re
import subprocess
import threading
import time
import wave
from pathlib import Path

from . import DATA

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

_lock = threading.Lock()   # ponytail: un lock global (cargar + inferir en serie); alcanza para un servidor local
_stt = None
_tts = {}                  # idioma -> PiperVoice
_errors = {}


def _installed(mod):
    import importlib.util
    return importlib.util.find_spec(mod) is not None


def status():
    stt, tts = _installed("faster_whisper"), _installed("piper")
    voices = sorted(p.name[:-5] for p in PIPER_DIR.glob("*.onnx")) if PIPER_DIR.exists() else []
    hint = ("" if stt and tts else
            "Falta instalar: .venv/bin/pip install " + " ".join(n for n, ok in (("faster-whisper", stt), ("piper-tts", tts)) if not ok))
    if stt and tts and not (MODELS / "whisper").exists():
        hint = "La primera vez se bajan los modelos de voz (~150 MB), puede tardar un minuto."
    return {"stt": stt, "tts": tts, "hint": hint, "errors": dict(_errors),
            "models": {"stt": "faster-whisper " + STT_MODEL + " (int8, CPU)", "stt_loaded": _stt is not None,
                       "tts_voices": voices, "tts_loaded": sorted(_tts)}}


def _whisper():
    global _stt
    if _stt is None:
        try:
            from faster_whisper import WhisperModel
        except ImportError:
            raise ValueError("La transcripción de voz no está instalada (faster-whisper).")
        _stt = WhisperModel(STT_MODEL, device="cpu", compute_type="int8", download_root=str(MODELS / "whisper"))
    return _stt


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


def transcribe(audio_bytes, mime="audio/webm", language="es", hint=None):
    """hint: palabras del bot (valores de entidades) para que Whisper las escriba bien: «muzzarella», no «multareza»."""
    if not audio_bytes or len(audio_bytes) < 200:
        raise ValueError("No llegó audio. Probá grabar de nuevo.")
    t0 = time.time()
    lang = (language or "es").split("-")[0].lower() or None
    with _lock:
        model = _whisper()
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
    return {"text": text, "language": info.language, "ms": int((time.time() - t0) * 1000)}


def _voice(lang):
    if lang in _tts:
        return _tts[lang]
    try:
        from piper import PiperVoice
        from piper.download_voices import download_voice
    except ImportError:
        raise ValueError("La voz no está disponible: falta instalar piper-tts.")
    PIPER_DIR.mkdir(parents=True, exist_ok=True)
    for name in VOICES.get(lang, VOICES["es"]):
        onnx = PIPER_DIR / (name + ".onnx")
        try:
            if not onnx.exists() or not (PIPER_DIR / (name + ".onnx.json")).exists():
                download_voice(name, PIPER_DIR)
            _tts[lang] = PiperVoice.load(str(onnx))
            _errors.pop("tts", None)
            return _tts[lang]
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


def _cached(lang, text):
    return TTS_CACHE / lang / (hashlib.sha1(text.encode()).hexdigest() + ".wav")


def prewarm(texts, language="es"):
    """Genera de antemano el audio de las frases sin variables ({{ }}) para que la llamada las diga al instante.
    Las frases con variables se generan en el momento y no se guardan (si no, la caché crece con cada charla).
    Devuelve cuántas generó. No lanza: si no hay voz instalada, no hace nada."""
    lang = _lang(language)
    done = 0
    try:
        for text in texts:
            for sentence in sentences(text):
                if "{{" in sentence or _cached(lang, sentence).exists():
                    continue
                audio = speak(sentence, lang, keep=False)
                path = _cached(lang, sentence)
                path.parent.mkdir(parents=True, exist_ok=True)
                tmp = path.with_suffix(".tmp")
                tmp.write_bytes(audio)
                tmp.replace(path)
                done += 1
    except Exception as error:  # noqa: BLE001 - sin piper o sin modelo: la llamada genera en el momento
        _errors["prewarm"] = str(error)
    return done


def speak(text, language="es", keep=True):
    text = (text or "").strip()
    if not text:
        raise ValueError("No hay texto para leer.")
    lang = _lang(language)
    if keep:
        hit = _cached(lang, text)
        if hit.exists():                     # frase fija pregenerada: al instante
            return hit.read_bytes()
    buf = io.BytesIO()
    with _lock:
        v = _voice(lang)
        with wave.open(buf, "wb") as w:
            v.synthesize_wav(text, w)
    return buf.getvalue()
