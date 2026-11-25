"""Ida y vuelta de voz: piper habla -> whisper transcribe (wav y webm/opus). Corre: .venv/bin/python tests/test_voice.py"""
import shutil
import subprocess
import sys
import time

import support  # noqa: F401  (repo en sys.path)
from parla import voice

_st = voice.status()
if not (_st["stt"] and _st["tts"]) or not shutil.which(voice.FFMPEG):
    print("(saltado: falta la voz -> pip install -r requirements-voice.txt y ffmpeg)")
    sys.exit(0)

PHRASE = "Hola, quiero pedir dos pizzas de muzzarella"


def timed(label, fn, *a):
    t = time.time()
    r = fn(*a)
    print("%-28s %6d ms" % (label, (time.time() - t) * 1000))
    return r


def check(res):
    words = res["text"].lower()
    print("   ->", repr(res["text"]), res["language"], res["ms"], "ms")
    # "hola" y "muzzarella" con la voz rioplatense a veces salen "o la" / "mozzarella" (límite del modelo base)
    # y piper es aleatorio (cada síntesis suena un poco distinta): pido "pizza" + 3 de las otras 5 claves
    hits = sum(any(w in words for w in alts) for alts in (("hola",), ("quiero",), ("pedir",), ("dos", "2"), ("zzarella", "zareja")))
    assert "pizza" in words and hits >= 3, res


print(voice.status())
wav = timed("speak (carga+descarga)", voice.speak, PHRASE, "es")
assert wav[:4] == b"RIFF" and len(wav) > 20000
timed("speak (en caliente)", voice.speak, PHRASE, "es")
check(timed("transcribe wav (carga)", voice.transcribe, wav, "audio/wav", "es", "muzzarella, napolitana, fugazzeta"))
check(timed("transcribe wav (caliente)", voice.transcribe, wav, "audio/wav", "es", "muzzarella, napolitana, fugazzeta"))

webm = subprocess.run([voice.FFMPEG, "-v", "error", "-i", "pipe:0", "-c:a", "libopus", "-f", "webm", "pipe:1"],
                      input=wav, capture_output=True, check=True).stdout
check(timed("transcribe webm/opus", voice.transcribe, webm, "audio/webm", "es", "muzzarella, napolitana, fugazzeta"))
mp4 = subprocess.run([voice.FFMPEG, "-v", "error", "-i", "pipe:0", "-c:a", "aac", "-ar", "48000", "-b:a", "128k", "-f", "mp4", "-movflags", "frag_keyframe+empty_moov",
                      "pipe:1"], input=wav, capture_output=True, check=True).stdout
check(timed("transcribe mp4/aac", voice.transcribe, mp4, "audio/mp4", "es", "muzzarella, napolitana, fugazzeta"))

for bad in (b"", b"x" * 500):
    try:
        voice.transcribe(bad, "audio/webm", "es")
        raise AssertionError("debió fallar")
    except ValueError as e:
        print("   error amable:", e)
try:
    voice.speak("  ", "es")
    raise AssertionError("debió fallar")
except ValueError:
    pass
print(voice.status())
print("ok")
