"""Teléfono: Twilio Programmable Voice y jambonz por webhooks. Solo biblioteca estándar.

Configuración (no secreta) en el JSON del agente:
    "channels": {"phone": {"enabled": true, "provider": "twilio" | "jambonz", "language": "es-AR", "voice": "Polly.Mia",
                           "handoff_to": "+5491112345678" | "sip:mesa@pbx.midominio.com", "tts": "provider" | "parla",
                           "finish_on_key": "#", "greeting": "Hola, ¿en qué te ayudo?"}}
Secretos en la bóveda (vault.py): ver SECRETS.

Cada llamada es una conversación «call-<CallSid>» del canal «phone»: el proveedor pide un webhook al empezar, otro con
cada respuesta (voz ya transcripta por el proveedor, o teclas) y otro cuando corta. Parla contesta qué decir y qué
hacer después: escuchar (Gather / gather), transferir (Dial / dial) o cortar (Hangup / hangup).
Rutas públicas bajo /api/v1/bots/{bot}/phone/…: no pasan por la sesión ni el chequeo de Host; las autentica la firma
del proveedor (X-Twilio-Signature, o Jambonz-Signature / HTTP basic). El audio de Parla (tts «parla»: la voz del agente
en «voice.tts», piper local u otro proveedor con API key) se sirve en /phone/audio/<token>.wav con un token firmado que
vence a los 10 minutos. tts «provider» es la voz propia de Twilio/jambonz.
"""
import base64
import hashlib
import hmac
import json
import re
import secrets as tokens
import time
import unicodedata
import urllib.parse
from xml.sax.saxutils import escape, quoteattr

from . import auth, channels, vault, voice
from .channels import ChannelError

PROVIDERS = ("twilio", "jambonz")
SECRETS = {"twilio": ("TWILIO_AUTH_TOKEN",),
           "jambonz": ("JAMBONZ_WEBHOOK_SECRET", "JAMBONZ_BASIC_USER", "JAMBONZ_BASIC_PASSWORD")}
LANGS = {"es": "es-US", "en": "en-US", "pt": "pt-BR"}        # si el agente no dice otra variante
ENDED = ("completed", "busy", "failed", "no-answer", "canceled")
MAX_SILENCE = 3                 # respuestas vacías seguidas antes de cortar
AUDIO_TTL = 600                 # segundos que vale la dirección de un audio de Parla
TOLERANCE = 300                 # antigüedad máxima de una firma de jambonz (como su SDK)
CALL_ID = re.compile(r"[A-Za-z0-9-]{1,64}")
# lo que la llamada dice por su cuenta, en el idioma de la charla
PRESS = {"es": ("Marcá", "para"), "en": ("Press", "for"), "pt": ("Digite", "para")}
GREETING = {"es": "Hola, ¿en qué te puedo ayudar?", "en": "Hi, how can I help you?", "pt": "Olá, como posso ajudar?"}
FILE_NOTE = {"es": "Tengo un archivo para vos, pero por teléfono no lo puedo mandar.",
             "en": "I have a file for you, but I can't send it over the phone.",
             "pt": "Tenho um arquivo para você, mas não consigo enviar por telefone."}
BYE = {"es": "No te escucho, así que corto. ¡Hasta luego!", "en": "I can't hear you, so I'll hang up. Goodbye!",
       "pt": "Não estou ouvindo, então vou desligar. Até logo!"}
NOBODY = {"es": "Ahora no hay nadie para atenderte. Probá más tarde.", "en": "There's nobody available right now. Please try later.",
          "pt": "Agora não há ninguém para atender. Tente mais tarde."}
SORRY = {"es": "Perdón, tuve un problema. Probá llamar de nuevo.", "en": "Sorry, something went wrong. Please call again.",
         "pt": "Desculpe, tive um problema. Tente ligar de novo."}

# ponytail: clave de los audios y silencios en memoria: se pierden al reiniciar y no sirven con varias réplicas
_KEY = tokens.token_bytes(32)
_silent = {}                    # sesión -> respuestas vacías seguidas


def _lang(language):
    lang = (language or "es").split("-")[0].lower()
    return lang if lang in PRESS else "es"


# ---------- texto para decir en voz alta ----------

URL = re.compile(r"https?://\S+|www\.\S+")


def speakable(text):
    """Sin emojis, Markdown ni direcciones web: lo que se puede leer por teléfono."""
    text = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", str(text or ""))
    text = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", text)
    text = URL.sub("", text)
    text = re.sub(r"\*\*|__|~~|`+|(?<!\w)\*(?=\S)|(?<=\S)\*(?!\w)", "", text)
    text = re.sub(r"(?m)^[ \t]*(?:#+|>|[-*•])[ \t]+", "", text)
    text = "".join(c for c in text if c == "°" or not (unicodedata.category(c) in ("So", "Cs", "Co")
                                                        or (unicodedata.category(c) == "Sk" and ord(c) > 0x1F000)
                                                        or c in "‍️⃣"))
    return "\n".join(re.sub(r"[ \t]+", " ", line).strip(" \t") for line in text.splitlines()).strip()


def chunks(text, size=300):
    """Frases (como voice.sentences, así pega en la caché de audio) juntadas hasta ~size letras."""
    out = []
    for sentence in voice.sentences(text):
        if out and len(out[-1]) + len(sentence) < size:
            out[-1] += " " + sentence
        else:
            out.append(sentence)
    return out


def menu(buttons, lang):
    """«Marcá 1 para Muzzarella, 2 para Fugazza.» (los primeros 9)."""
    verb, word = PRESS[_lang(lang)]
    return "%s %s." % (verb, ", ".join("%d %s %s" % (i + 1, word, speakable(b.get("label") or b.get("value")))
                                       for i, b in enumerate(buttons[:9])))


def lines(replies, lang):
    """Lo que dice el turno: cada respuesta lista para leer, los archivos como aviso y los botones como menú."""
    out, lang = [], _lang(lang)
    for r in replies:
        text = speakable(r.get("text"))
        if r.get("file"):
            text = ("" if text == speakable(r["file"].get("name")) else text + "\n") + FILE_NOTE[lang]
        out += voice.sentences(text)
    buttons = replies[-1].get("buttons") if replies else None
    if buttons:
        out.append(menu(buttons, lang))
    return chunks("\n".join(out))


def pick(record, speech, digits):
    """Teclas: con botones en pantalla, 1..9 eligen el botón; si no, van tal cual (un DNI, un número de pedido)."""
    buttons = ((record or {}).get("state") or {}).get("buttons") or []
    digits = str(digits or "").strip()
    if re.fullmatch(r"[1-9]", digits) and int(digits) <= min(9, len(buttons)):
        return str(buttons[int(digits) - 1]["value"])
    return digits or str(speech or "").strip()


# ---------- audio de Parla con direcciones firmadas ----------

def _b64(raw):
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def _sign(payload):
    return _b64(hmac.new(_KEY, payload.encode(), hashlib.sha256).digest())


def audio_token(agent_id, text, lang, now=None):
    payload = _b64(json.dumps([agent_id, int((now or time.time()) + AUDIO_TTL), lang, text], ensure_ascii=False).encode())
    return payload + "." + _sign(payload)


def audio_text(agent_id, token, now=None):
    """(texto, idioma) de un token válido, sin vencer y de este agente; None si no."""
    payload, _, sig = token.partition(".")
    if not hmac.compare_digest(sig.encode(), _sign(payload).encode()):
        return None
    try:
        owner, expires, lang, text = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
    except (ValueError, TypeError):
        return None
    return (text, lang) if owner == agent_id and expires >= (now or time.time()) else None


def audio(ref, token):
    """GET /phone/audio/<token>.wav -> (status, cuerpo, tipo)."""
    agent = auth._app().find_bot(urllib.parse.unquote(ref))
    found = audio_text(agent["id"], token) if agent and channels.config(agent, "phone").get("enabled") else None
    if not found:
        return 403, b"", "text/plain"
    try:
        return 200, voice.speak(*found, tts=voice.settings(agent)["tts"]), "audio/wav"
    except Exception as error:  # noqa: BLE001 - sin piper: que se vea en Canales
        channels._log(agent["id"], "phone", error)
        return 503, b"", "text/plain"


# ---------- firmas ----------

def twilio_ok(token, url, params, given):
    """X-Twilio-Signature: base64(HMAC-SHA1(token, URL completa + cada clave y valor del POST, por clave))."""
    data = url + "".join(k + v for k, v in sorted(params))
    expected = base64.b64encode(hmac.new(token.encode(), data.encode(), hashlib.sha1).digest())
    return bool(token) and hmac.compare_digest(str(given or "").encode(), expected)


def jambonz_ok(agent_id, headers, raw, now=None):
    """Jambonz-Signature «t=<unix>,v1=<hex>» = HMAC-SHA256(secreto, "<t>.<cuerpo>") y/o HTTP basic. Las que estén
    cargadas tienen que dar bien todas; sin ninguna cargada, nada pasa."""
    keys = vault.values(agent_id)
    secret, user, password = (keys.get(n) or "" for n in SECRETS["jambonz"])
    if not secret and not (user and password):
        return False
    if secret:
        parts = dict(p.split("=", 1) for p in str(headers.get("Jambonz-Signature") or "").split(",") if "=" in p)
        stamp = parts.get("t", "")
        if not stamp.isdigit() or abs((now or time.time()) - int(stamp)) > TOLERANCE:
            return False
        expected = hmac.new(secret.encode(), stamp.encode() + b"." + raw, hashlib.sha256).hexdigest()
        if not hmac.compare_digest(parts.get("v1", "").encode(), expected.encode()):
            return False
    if user and password:
        want = "Basic " + base64.b64encode(("%s:%s" % (user, password)).encode()).decode()
        if not hmac.compare_digest(str(headers.get("Authorization") or "").encode(), want.encode()):
            return False
    return True


# ---------- el turno ----------

def _hook(agent, provider, action=""):
    return "%s/api/v1/bots/%s/phone/%s%s" % (channels.public_url(agent), agent["id"], provider, "/" + action if action else "")


def plan(agent, conf, sid, kind, text=None, caller=None):
    """Corre un turno y decide: {"say": [frases], "then": "gather"|"dial"|"hangup", "lang", "digits": n, "to"}."""
    app = auth._app()
    record = app.load_session(agent["id"], sid)
    if kind == "silence":
        _silent[sid] = _silent.get(sid, 0) + 1
        state = (record or {}).get("state") or {}
        lang = state.get("lang") or "es"
        if not record or (state.get("handoff") or {}).get("active"):
            say, handoff, finished = [], bool(record), False      # una persona la tomó desde la Bandeja: transferir
        elif _silent[sid] >= MAX_SILENCE:
            return _close(app, agent, sid, {"say": [BYE[_lang(lang)]], "then": "hangup", "lang": lang})
        else:
            say, handoff, finished = lines(state.get("last_bot") or [], lang), False, False
    else:
        _silent.pop(sid, None)
        data = {"type": kind, "sessionId": sid, "channel": "phone", "environment": "production"}
        if kind == "start":
            data["data"] = {k: v for k, v in (("caller", caller), ("language", conf.get("language"))) if v}
        else:
            data["text"] = text
        status, body = app.api_v1("POST", ["bots", agent["id"], "events"], data)
        if status != 200:
            raise ChannelError(body.get("error"))
        record = app.load_session(agent["id"], sid)
        lang, handoff = body.get("language") or "es", body.get("handoff")
        finished = record["state"].get("finished")
        say = lines(body.get("replies") or [], lang)
        if kind == "start" and not say and not handoff:
            say = [speakable(conf.get("greeting")) or GREETING[_lang(lang)]]
    out = {"say": say, "lang": lang, "then": "gather"}
    if handoff:
        to = str(conf.get("handoff_to") or "").strip()
        if not to:
            channels._log(agent["id"], "phone", "falta «handoff_to»: no hay a dónde transferir la llamada")
            return _close(app, agent, sid, dict(out, say=say + [NOBODY[_lang(lang)]], then="hangup"))
        record["history"].append({"from": "event", "text": "Transferida a %s" % to, "at": app.now()})
        app.save_session(agent["id"], record)
        return dict(out, then="dial", to=to)
    if finished:
        return _close(app, agent, sid, dict(out, then="hangup"))
    buttons = (record["state"].get("buttons") or []) if record else []
    return dict(out, digits=1 if 0 < len(buttons) <= 9 else None,
                hints=", ".join(filter(None, [app.vocabulary(agent)] + [str(b.get("label")) for b in buttons]))[:900] or None)


def _close(app, agent, sid, out):
    app.end_session(agent["id"], sid)
    _silent.pop(sid, None)
    return out


def _language(conf, lang):
    """La variante que pide el proveedor: la del agente si es del mismo idioma que la charla; si no, una por defecto."""
    own = str(conf.get("language") or "")
    return own if own and _lang(own) == _lang(lang) else LANGS[_lang(lang)]


def twiml(agent, conf, p):
    lang = _language(conf, p["lang"])
    if conf.get("tts") == "parla":
        speech = "".join("<Play>%s</Play>" % escape(_audio_url(agent, s, p["lang"])) for s in p["say"])
    else:
        voice_attr = " voice=%s" % quoteattr(str(conf["voice"])) if conf.get("voice") else ""
        speech = "".join("<Say%s language=%s>%s</Say>" % (voice_attr, quoteattr(lang), escape(s)) for s in p["say"])
    if p["then"] == "gather":
        attrs = {"input": "speech dtmf", "language": lang, "speechTimeout": "auto", "timeout": "6",
                 "action": _hook(agent, "twilio", "gather"), "method": "POST", "actionOnEmptyResult": "true",
                 "finishOnKey": str(conf.get("finish_on_key") or "#")}
        if p.get("digits"):
            attrs["numDigits"] = str(p["digits"])
        if p.get("hints"):
            attrs["hints"] = p["hints"]
        body = "<Gather %s>%s</Gather>" % (" ".join("%s=%s" % (k, quoteattr(v)) for k, v in attrs.items()), speech)
    elif p["then"] == "dial":
        to = p["to"]
        body = speech + "<Dial>%s</Dial><Hangup/>" % ("<Sip>%s</Sip>" % escape(to) if to.startswith(("sip:", "sips:")) else escape(to))
    else:
        body = speech + "<Hangup/>"
    return ('<?xml version="1.0" encoding="UTF-8"?><Response>%s</Response>' % body).encode()


def verbs(agent, conf, p):
    lang, keys = _language(conf, p["lang"]), vault.values(agent["id"])
    if not p["say"]:
        prompt = {}
    elif conf.get("tts") == "parla":
        prompt = {"play": {"url": [_audio_url(agent, s, p["lang"]) for s in p["say"]]}}
    else:
        prompt = {"say": {"text": " ".join(p["say"]),
                          **({"synthesizer": {"vendor": "default", "language": lang, "voice": conf["voice"]}} if conf.get("voice") else {})}}
    if p["then"] == "gather":
        hook = _hook(agent, "jambonz", "gather")
        if keys.get("JAMBONZ_BASIC_USER") and keys.get("JAMBONZ_BASIC_PASSWORD"):
            hook = {"url": hook, "method": "POST", "username": keys["JAMBONZ_BASIC_USER"], "password": keys["JAMBONZ_BASIC_PASSWORD"]}
        gather = {"verb": "gather", "input": ["speech", "digits"], "actionHook": hook, "bargein": True, "dtmfBargein": True,
                  "listenDuringPrompt": True, "timeout": 6, "finishOnKey": str(conf.get("finish_on_key") or "#"),
                  "recognizer": {"vendor": "default", "language": lang,
                                 **({"hints": [h.strip() for h in p["hints"].split(",") if h.strip()]} if p.get("hints") else {})},
                  **prompt}
        if p.get("digits"):
            gather["numDigits"] = p["digits"]
        return [gather]
    out = [{"verb": k, **v} for k, v in prompt.items()]
    if p["then"] == "dial":
        to = p["to"]
        out.append({"verb": "dial", "answerOnBridge": True,
                    "target": [{"type": "sip", "sipUri": to} if to.startswith(("sip:", "sips:")) else {"type": "phone", "number": to}]})
    return out + [{"verb": "hangup"}]


def _audio_url(agent, text, lang):
    return "%s/api/v1/bots/%s/phone/audio/%s.wav" % (channels.public_url(agent), agent["id"], audio_token(agent["id"], text, lang))


# ---------- entrada ----------

def webhook(headers, rfile, method, ref, provider, action, path, length):
    """Las rutas públicas del teléfono. Devuelve (status, cuerpo, tipo). Los rechazos no dan detalles."""
    app = auth._app()
    deny = (403, b"", "text/plain")
    agent = app.find_bot(urllib.parse.unquote(ref))
    conf = channels.config(agent, "phone") if agent else {}
    if not agent or not conf.get("enabled") or (conf.get("provider") or "twilio") != provider:
        return deny
    if method != "POST":
        return 405, b"", "text/plain"
    if length > channels.MAX_BODY:
        return 413, b"", "text/plain"
    raw = rfile.read(length) if length else b""
    agent_id = agent["id"]
    if provider == "twilio":
        params = urllib.parse.parse_qsl(raw.decode("utf-8", "replace"), keep_blank_values=True)
        if not twilio_ok(channels._secret(agent_id, "TWILIO_AUTH_TOKEN"), channels.public_url(agent) + path, params,
                         headers.get("X-Twilio-Signature")):
            return deny
        params = dict(params)
        call, status, caller = params.get("CallSid"), params.get("CallStatus"), params.get("From")
        speech, digits = params.get("SpeechResult"), params.get("Digits")
    else:
        if not jambonz_ok(agent_id, headers, raw):
            return deny
        try:
            params = json.loads(raw or b"{}")
            params = params if isinstance(params, dict) else {}
        except ValueError:
            params = {}
        call, status, caller = params.get("call_sid"), params.get("call_status"), params.get("from")
        alternatives = (params.get("speech") or {}).get("alternatives") if isinstance(params.get("speech"), dict) else None
        speech = (alternatives[0] or {}).get("transcript") if isinstance(alternatives, list) and alternatives else None
        digits = params.get("digits")
    channels._note(agent_id, "phone", last_in=time.strftime("%Y-%m-%dT%H:%M:%S"))
    if not isinstance(call, str) or not CALL_ID.fullmatch(call):
        return 400, b"", "text/plain"
    sid = "call-" + call
    if action == "status":           # cortó (o no atendió): la conversación termina
        if status in ENDED:
            with channels._session_lock(agent_id + "/" + sid):
                if (app.load_session(agent_id, sid) or {}).get("ended") is False:
                    app.end_session(agent_id, sid)
                _silent.pop(sid, None)
        return 200, b"{}" if provider == "jambonz" else b"", "application/json" if provider == "jambonz" else "text/plain"
    with channels._session_lock(agent_id + "/" + sid):
        try:
            if action == "gather":
                said = pick(app.load_session(agent_id, sid), speech, digits)
                p = plan(agent, conf, sid, "message" if said else "silence", said)
            else:
                p = plan(agent, conf, sid, "start", caller=caller if isinstance(caller, str) else None)
        except Exception as error:  # noqa: BLE001 - que quede en Canales y la persona no se quede colgada en silencio
            channels._log(agent_id, "phone", error)
            lang = ((app.load_session(agent_id, sid) or {}).get("state") or {}).get("lang") or "es"
            p = _close(app, agent, sid, {"say": [SORRY[_lang(lang)]], "then": "hangup", "lang": lang})
    channels._note(agent_id, "phone", last_out=time.strftime("%Y-%m-%dT%H:%M:%S"))
    if provider == "twilio":
        return 200, twiml(agent, conf, p), "text/xml"
    return 200, json.dumps(verbs(agent, conf, p), ensure_ascii=False).encode(), "application/json"


def info(agent):
    """Lo que muestra «Canales → Teléfono»: proveedor, webhooks para pegar, claves y estado."""
    conf, names = channels.config(agent, "phone"), set(vault.names(agent["id"]))
    provider = conf.get("provider") if conf.get("provider") in PROVIDERS else "twilio"
    return {"enabled": bool(conf.get("enabled")), "provider": provider, "webhook": _hook(agent, provider),
            "status_webhook": _hook(agent, provider, "status"),
            "secrets": {n: n in names for p in PROVIDERS for n in SECRETS[p]}, "status": dict(channels.STATUS.get((agent["id"], "phone")) or {})}
