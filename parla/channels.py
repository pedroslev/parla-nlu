"""Canales de mensajería: WhatsApp (Cloud API de Meta) y Telegram. Solo biblioteca estándar.

Configuración (no secreta) en el JSON del agente:
    "channels": {"public_url": "https://bots.midominio.com",          # o PARLA_PUBLIC_URL
                 "whatsapp": {"enabled": true, "phone_number_id": "1234567890"},
                 "telegram": {"enabled": true}}
Secretos en la bóveda del agente (vault.py), con nombres fijos: ver SECRETS.

Entrada: POST /api/v1/bots/{bot}/whatsapp (firma X-Hub-Signature-256) y POST /api/v1/bots/{bot}/telegram
(X-Telegram-Bot-Api-Secret-Token). Se contesta 200 enseguida y el mensaje se atiende en un hilo, con la misma
entrada que la API (api_v1 events, entorno production, canal whatsapp/telegram, sesión wa-<teléfono> / tg-<chat>).
Las respuestas (texto, botones, archivos) y lo que escribe una persona desde la Bandeja vuelven por el canal.
"""
import contextvars
import hashlib
import hmac
import json
import os
import re
import secrets as tokens
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from collections import OrderedDict

from . import auth, cluster, costs, db, files, llm, outbound, telemetry, vault, voice

CHANNELS = ("whatsapp", "telegram")
SECRETS = {"whatsapp": ("WHATSAPP_TOKEN", "WHATSAPP_APP_SECRET", "WHATSAPP_VERIFY_TOKEN"),
           "telegram": ("TELEGRAM_TOKEN", "TELEGRAM_WEBHOOK_SECRET")}
MAX_BODY = 1_000_000
TIMEOUT = 10
MEDIA_TIMEOUT = 30
PLACEHOLDER = {"image": "[imagen]", "photo": "[imagen]", "document": "[documento]", "audio": "[audio]", "voice": "[audio]",
               "video": "[video]", "video_note": "[video]", "sticker": "[sticker]", "location": "[ubicación]",
               "venue": "[ubicación]", "contacts": "[contacto]", "contact": "[contacto]"}
KIND = {"photo": "image", "voice": "audio", "video_note": "video", "contact": "contacts", "venue": "location"}   # un nombre por tipo
UNHEARD = "[audio sin transcribir]"
OPTIONS = {"es": "Opciones", "pt": "Opções", "en": "Options"}     # el botón que abre la lista de WhatsApp


class ChannelError(Exception):
    """status: el HTTP que contestó el otro lado (0 = no contestó); code: el código de error de Meta, si vino."""
    status, code = None, None


def _failed(agent_id, detail, status, raw=b""):
    error = ChannelError(vault.mask(detail, agent_id))
    error.status = status
    try:
        error.code = (json.loads(raw or b"{}").get("error") or {}).get("code")
    except (ValueError, AttributeError):
        pass
    return error


def _wa_api():
    return os.environ.get("PARLA_WHATSAPP_API", "https://graph.facebook.com/v21.0").rstrip("/")


def _tg_api():
    return os.environ.get("PARLA_TELEGRAM_API", "https://api.telegram.org").rstrip("/")


def config(agent, channel):
    conf = ((agent or {}).get("channels") or {}).get(channel)
    return conf if isinstance(conf, dict) else {}


def public_url(agent):
    own = ((agent or {}).get("channels") or {}).get("public_url")
    return str(own or os.environ.get("PARLA_PUBLIC_URL") or "").strip().rstrip("/")


def _secret(agent_id, name):
    return vault.values(agent_id).get(name) or ""


# ---------- estado, duplicados y orden ----------

STATUS = {}      # (agente, canal) -> {"last_in", "last_out", "error", "error_at"}. ponytail: en memoria, se pierde al reiniciar
_seen, _seen_lock = OrderedDict(), threading.Lock()
# un lock por conversación en memoria (hasta ~1000); con Postgres, además un advisory lock (cluster.py)
_locks, _locks_guard = {}, threading.Lock()


def _note(agent_id, channel, **fields):
    STATUS.setdefault((agent_id, channel), {}).update(fields)


def _first_time(key):
    """Meta y Telegram reintentan: cada id de mensaje se atiende una sola vez (los últimos 5000; con Postgres, en
    todas las réplicas y por un día)."""
    if db.PG:
        return cluster.first("seen:" + key, 86400)
    with _seen_lock:
        if key in _seen:
            return False
        _seen[key] = True
        if len(_seen) > 5000:
            _seen.popitem(last=False)
        return True


def _session_lock(key):
    with _locks_guard:
        if key not in _locks and len(_locks) >= 1000:
            for old in [k for k, lock in _locks.items() if not lock.locked()][:500]:
                del _locks[old]
        local = _locks.setdefault(key, threading.Lock())
    return cluster.both(local, "chat:" + key) if db.PG else local


def _log(agent_id, channel, message):
    message = vault.mask(str(message), agent_id)
    _note(agent_id, channel, error=message[:500], error_at=time.strftime("%Y-%m-%dT%H:%M:%S"))
    print("[parla] %s %s: %s" % (channel, agent_id, message), file=sys.stderr, flush=True)


# ---------- HTTP de salida ----------

def _post(agent_id, url, payload=None, body=None, ctype="application/json", token=None, authorization=None):
    """POST con tiempo máximo. Un reintento si el otro lado da 5xx o no contesta; los 4xx no se reintentan."""
    headers = {"Content-Type": ctype}
    if token or authorization:
        headers["Authorization"] = authorization or "Bearer " + token
    data = json.dumps(payload, ensure_ascii=False).encode() if payload is not None else body
    for attempt in (1, 2):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, data=data, headers=headers, method="POST"), timeout=TIMEOUT) as r:
                raw = r.read(1_000_000)
            try:
                return json.loads(raw or b"{}")
            except ValueError:
                return {}
        except urllib.error.HTTPError as error:
            raw = error.read(2000)
            detail = "HTTP %d %s" % (error.code, raw[:300].decode("utf-8", "replace"))
            if error.code < 500 or attempt == 2:
                raise _failed(agent_id, detail, error.code, raw) from None
        except OSError as error:             # sin red, DNS, timeout
            if attempt == 2:
                raise _failed(agent_id, "sin respuesta: %s" % getattr(error, "reason", error), 0) from None


def _get(agent_id, url, token=None, limit=files.MAX_INBOUND):
    """GET con tiempo máximo y tope de tamaño: (contenido, tipo). ChannelError si falla o se pasa del tope."""
    if not url.startswith(("http://", "https://")):
        raise _failed(agent_id, "dirección de descarga inválida", 0)
    headers = {"Authorization": "Bearer " + token} if token else {}
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=MEDIA_TIMEOUT) as r:
            body = r.read(limit + 1)
            ctype = r.headers.get("Content-Type") or ""
    except urllib.error.HTTPError as error:
        raise _failed(agent_id, "HTTP %d al descargar" % error.code, error.code) from None
    except OSError as error:
        raise _failed(agent_id, "sin respuesta: %s" % getattr(error, "reason", error), 0) from None
    if len(body) > limit:
        raise ChannelError("el archivo es muy grande (máximo %d MB)" % (limit // 1024 // 1024))
    return body, ctype


def _download(agent_id, channel, media):
    """El archivo de un mensaje entrante: (contenido, tipo, nombre). WhatsApp: GET /{media-id} -> url -> GET con el
    token; Telegram: getFile -> file_path -> /file/bot<token>/<file_path>."""
    if not re.fullmatch(r"[A-Za-z0-9_.:-]{1,300}", str(media.get("id") or "")):
        raise ChannelError("el mensaje no trae el id del archivo")
    if channel == "whatsapp":
        token = _secret(agent_id, "WHATSAPP_TOKEN")
        info = json.loads(_get(agent_id, "%s/%s" % (_wa_api(), media["id"]), token, 100_000)[0] or b"{}")
        if int(info.get("file_size") or 0) > files.MAX_INBOUND:
            raise ChannelError("el archivo es muy grande (máximo %d MB)" % (files.MAX_INBOUND // 1024 // 1024))
        body, ctype = _get(agent_id, str(info.get("url") or ""), token)
        return body, media.get("mime") or info.get("mime_type") or ctype, media.get("name")
    base = _tg_base(agent_id)
    info = (json.loads(_get(agent_id, base + "getFile?file_id=" + urllib.parse.quote(media["id"]), None, 100_000)[0] or b"{}").get("result") or {})
    if int(info.get("file_size") or 0) > files.MAX_INBOUND:
        raise ChannelError("el archivo es muy grande (máximo %d MB)" % (files.MAX_INBOUND // 1024 // 1024))
    path = str(info.get("file_path") or "")
    if not re.fullmatch(r"[A-Za-z0-9_./-]{1,300}", path) or ".." in path:
        raise ChannelError("Telegram no devolvió el archivo")
    body, ctype = _get(agent_id, "%s/file/bot%s/%s" % (_tg_api(), _secret(agent_id, "TELEGRAM_TOKEN"), path))
    mime = media.get("mime") or ("image/jpeg" if media["type"] == "image" else ctype)
    return body, mime, media.get("name") or path.rpartition("/")[2]


def _vision(agent, body, mime, lang):
    """Con ai.vision: true y un proveedor que ve imágenes, una descripción corta de la foto para la IA. None si no."""
    if not (agent.get("ai") or {}).get("vision") or not mime.startswith("image/"):
        return None
    cfg = llm.settings(agent)
    if cfg.get("provider") not in llm.VISION:
        return None
    return llm.describe(cfg, body, mime, lang) or None


def _media(agent, channel, sid, item):
    """Descarga y guarda el archivo del mensaje, y arma lo que recibe el turno: (texto para el bot, media).
    Un audio se transcribe con el ASR del agente; una ubicación o un contacto llegan como texto."""
    app, media = auth._app(), dict(item["media"])
    text, kind = item["text"], media["type"]
    if kind in ("location", "contacts"):
        return text, media
    lang = ((app.load_session(agent["id"], sid) or {}).get("state") or {}).get("lang") or app.languages(agent)[0]
    try:
        body, mime, name = _download(agent["id"], channel, media)
        saved = files.store(agent["id"], sid, name or kind, mime, body)
    except (ChannelError, ValueError) as error:
        _log(agent["id"], channel, "no se pudo guardar un archivo: %s" % error)
        media.update(error=str(error))
        return (UNHEARD if kind == "audio" else text), {k: v for k, v in media.items() if k != "id"}
    media = {k: v for k, v in media.items() if k not in ("id", "mime")} | {"url": saved["url"], "file": saved["id"], "mime": saved["mime"],
                                                                         "name": saved["name"], "size": saved["size"]}
    if kind == "audio":
        try:
            heard = voice.transcribe(body, saved["mime"], lang, app.vocabulary(agent), voice.settings(agent)["asr"])
            media["transcript"] = str((heard or {}).get("text") or "").strip()[:4000]
        except Exception as error:  # noqa: BLE001 - sin ASR, formato raro: el bot recibe el aviso y contesta lo de siempre
            _log(agent["id"], channel, "audio sin transcribir: %s" % error)
            media["error"] = "no se pudo transcribir"
        return media.get("transcript") or UNHEARD, media
    try:
        media["description"] = _vision(agent, body, saved["mime"], lang)
    except Exception as error:  # noqa: BLE001 - la foto igual llega; solo falta la descripción
        _log(agent["id"], channel, "no se pudo describir la imagen: %s" % error)
    return text, {k: v for k, v in media.items() if v is not None}


def _multipart(fields, field, name, mime, content):
    boundary = uuid.uuid4().hex
    out = [('--%s\r\nContent-Disposition: form-data; name="%s"\r\n\r\n%s\r\n' % (boundary, k, v)).encode() for k, v in fields.items()]
    plain = re.sub(r'[^A-Za-z0-9._ -]', "_", name)
    out.append(('--%s\r\nContent-Disposition: form-data; name="%s"; filename="%s"\r\nContent-Type: %s\r\n\r\n'
                % (boundary, field, plain, mime)).encode() + content + b"\r\n")
    out.append(("--%s--\r\n" % boundary).encode())
    return b"".join(out), "multipart/form-data; boundary=" + boundary


def _button_id(button, index, limit):
    """El valor del botón viaja como id (vuelve al tocarlo); si no entra, «#n» y se busca en la conversación."""
    value = str(button.get("value") or button.get("label") or "")
    return value if value and len(value.encode()) <= limit else "#%d" % index


def _photo(mime, size):
    return mime in ("image/jpeg", "image/png") and size <= 5 * 1024 * 1024    # el resto va como documento


def _attachment(agent_id, reply):
    """(contenido, mime, nombre) del archivo de la respuesta, o None si ya no existe."""
    found = files.read(agent_id, (reply.get("file") or {}).get("id")) if reply.get("file") else None
    return (found[0], found[1]["Content-Type"].split(";")[0], reply["file"]["name"]) if found else None


def _wa_send(agent, to, reply, lang):
    conf, token = config(agent, "whatsapp"), _secret(agent["id"], "WHATSAPP_TOKEN")
    phone_id = str(conf.get("phone_number_id") or "")
    if not token or not re.fullmatch(r"\d{1,30}", phone_id):
        raise ChannelError("falta la clave WHATSAPP_TOKEN o el «phone_number_id»")
    base = {"messaging_product": "whatsapp", "recipient_type": "individual", "to": to}
    text, buttons, sent = reply["text"], reply.get("buttons") or [], _attachment(agent["id"], reply)
    if sent:
        content, mime, name = sent
        body, ctype = _multipart({"messaging_product": "whatsapp", "type": mime}, "file", name, mime, content)
        media = _post(agent["id"], "%s/%s/media" % (_wa_api(), phone_id), body=body, ctype=ctype, token=token)
        kind = "image" if _photo(mime, len(content)) else "document"
        item = {"id": media.get("id"), "caption": text[:1024], **({"filename": name} if kind == "document" else {})}
        message = dict(base, type=kind, **{kind: item})
    elif buttons:
        ids = [_button_id(b, i, 200) for i, b in enumerate(buttons)]
        if len(buttons) <= 3:
            action = {"buttons": [{"type": "reply", "reply": {"id": ids[i], "title": b["label"][:20]}} for i, b in enumerate(buttons)]}
            kind = "button"
        else:    # ponytail: WhatsApp muestra hasta 10 opciones en una lista; las que sobran no se ven
            action = {"button": OPTIONS.get(lang, OPTIONS["es"]),
                      "sections": [{"title": OPTIONS.get(lang, OPTIONS["es"]),
                                    "rows": [{"id": ids[i], "title": b["label"][:24]} for i, b in enumerate(buttons[:10])]}]}
            kind = "list"
        message = dict(base, type="interactive", interactive={"type": kind, "body": {"text": text[:1024]}, "action": action})
    else:
        message = dict(base, type="text", text={"body": text[:4096]})
    return _post(agent["id"], "%s/%s/messages" % (_wa_api(), phone_id), message, token=token)


def _tg_base(agent_id):
    token = _secret(agent_id, "TELEGRAM_TOKEN")
    if not re.fullmatch(r"\d+:[A-Za-z0-9_-]+", token):
        raise ChannelError("falta la clave TELEGRAM_TOKEN (o no tiene el formato 123456:ABC… que da BotFather)")
    return "%s/bot%s/" % (_tg_api(), token)


def _tg_send(agent, chat_id, reply, lang):
    base, text, buttons, sent = _tg_base(agent["id"]), reply["text"], reply.get("buttons") or [], _attachment(agent["id"], reply)
    if sent:
        content, mime, name = sent
        method, field = ("sendPhoto", "photo") if _photo(mime, len(content)) else ("sendDocument", "document")
        body, ctype = _multipart({"chat_id": chat_id, "caption": text[:1024]}, field, name, mime, content)
        return _post(agent["id"], base + method, body=body, ctype=ctype)
    message = {"chat_id": chat_id, "text": text[:4096]}
    if buttons:
        message["reply_markup"] = {"inline_keyboard": [[{"text": b["label"][:64], "callback_data": _button_id(b, i, 64)}]
                                                       for i, b in enumerate(buttons)]}
    return _post(agent["id"], base + "sendMessage", message)


def _send(agent, channel, sid, replies, lang):
    """Manda las respuestas; devuelve el id del último mensaje (wamid de WhatsApp o message_id de Telegram)."""
    to, last = sid.split("-", 1)[1], None
    for reply in replies:
        sent = (_wa_send if channel == "whatsapp" else _tg_send)(agent, to, reply, lang) or {}
        costs.record(channel, "meta" if channel == "whatsapp" else "telegram", "service" if channel == "whatsapp" else "bot", 1,
                     agent=agent["id"], session=sid, channel=channel)
        last = ((sent.get("messages") or [{}])[0].get("id") if channel == "whatsapp"
                else (sent.get("result") or {}).get("message_id") if isinstance(sent.get("result"), dict) else None) or last
    if replies:
        _note(agent["id"], channel, last_out=time.strftime("%Y-%m-%dT%H:%M:%S"))
    return last


# ---------- Entrada ----------

def parse_statuses(agent, payload):
    """[(wamid, estado, código de error)] de los «statuses» de un webhook (sent, delivered, read, failed)."""
    out, phone_id = [], str(config(agent, "whatsapp").get("phone_number_id") or "")
    for entry in payload.get("entry") or []:
        for change in (entry or {}).get("changes") or []:
            value = (change or {}).get("value") or {}
            if phone_id and str((value.get("metadata") or {}).get("phone_number_id") or "") == phone_id:
                out += [(str(s.get("id") or ""), s.get("status"), ((s.get("errors") or [{}])[0] or {}).get("code"))
                        for s in value.get("statuses") or [] if isinstance(s, dict)]
    return out


def _place(loc):
    """Una ubicación como texto que sirve para un slot («-34.6037,-58.3816» o «Nombre, dirección (-34.6, -58.3)»)."""
    try:
        lat, lng = float(loc.get("latitude")), float(loc.get("longitude"))
    except (TypeError, ValueError, AttributeError):
        return None
    if not (-90 <= lat <= 90 and -180 <= lng <= 180):
        return None
    name, address = (str(loc.get(k) or "").strip()[:200] for k in ("name", "address"))
    where = ", ".join(p for p in (name, address) if p)
    return {"type": "location", "lat": lat, "lng": lng, **({"name": name} if name else {}), **({"address": address} if address else {}),
            "text": "%s (%s,%s)" % (where, lat, lng) if where else "%s,%s" % (lat, lng)}


def _person(card):
    """Un contacto compartido (WhatsApp contacts[0] o Telegram contact) -> {type, name, phone, text}."""
    if not isinstance(card, dict):
        return None
    names = card.get("name") if isinstance(card.get("name"), dict) else {}
    name = str(names.get("formatted_name") or " ".join(str(card.get(k) or "") for k in ("first_name", "last_name"))).strip()[:120]
    phone = str(card.get("phone_number") or ((card.get("phones") or [{}])[0] or {}).get("phone") or "").strip()[:40]
    if not (name or phone):
        return None
    return {"type": "contacts", **({"name": name} if name else {}), **({"phone": phone} if phone else {}), "text": " ".join(p for p in (name, phone) if p)}


def parse_whatsapp(agent, payload):
    """Los mensajes de un webhook de WhatsApp para el número configurado (los «statuses» van por parse_statuses)."""
    out, phone_id = [], str(config(agent, "whatsapp").get("phone_number_id") or "")
    for entry in payload.get("entry") or []:
        for change in (entry or {}).get("changes") or []:
            value = (change or {}).get("value") or {}
            if not phone_id or str((value.get("metadata") or {}).get("phone_number_id") or "") != phone_id:
                continue
            for m in value.get("messages") or []:
                sender, kind, media = str(m.get("from") or ""), m.get("type"), None
                if kind == "text":
                    text = (m.get("text") or {}).get("body")
                elif kind == "interactive":       # tocó un botón o eligió de la lista: vuelve el id que mandamos
                    inter = m.get("interactive") or {}
                    text = (inter.get("button_reply") or inter.get("list_reply") or {}).get("id")
                elif kind == "button":            # respuesta rápida de una plantilla
                    text = (m.get("button") or {}).get("payload") or (m.get("button") or {}).get("text")
                elif kind in ("location", "contacts"):
                    media = _place(m.get("location")) if kind == "location" else _person((m.get("contacts") or [{}])[0])
                    text = media.pop("text") if media else None
                elif kind in PLACEHOLDER:
                    item = m.get(kind) if isinstance(m.get(kind), dict) else {}
                    media = {"type": KIND.get(kind, kind), "id": item.get("id"), "mime": item.get("mime_type"), "name": item.get("filename"),
                             **({"caption": item["caption"]} if item.get("caption") else {}), **({"voice": True} if item.get("voice") else {})}
                    text = item.get("caption") or PLACEHOLDER[kind]
                else:
                    continue                      # reacciones, mensajes que WhatsApp no soporta
                if re.fullmatch(r"\d{5,20}", sender) and isinstance(text, str) and text.strip():
                    out.append({"sid": "wa-" + sender, "id": "wa:" + str(m.get("id") or uuid.uuid4().hex), "text": text, "media": media})
    return out


def parse_telegram(update):
    """Un update de Telegram: mensaje o botón tocado (callback_query). [] si no es para el bot."""
    query = update.get("callback_query")
    message = (query or {}).get("message") if query else update.get("message")
    chat = ((message or {}).get("chat") or {}).get("id")
    if not isinstance(chat, int) or isinstance(chat, bool):
        return []
    media = None
    if query:
        text = query.get("data")
    else:
        text = message.get("text") or message.get("caption")
        kind = next((k for k in PLACEHOLDER if k in message), None)
        if kind in ("location", "venue", "contact"):
            venue = message.get("venue") if isinstance(message.get("venue"), dict) else {}
            media = (_place(dict(venue.get("location") or message.get("location") or {}, name=venue.get("title"), address=venue.get("address")))
                     if kind != "contact" else _person(message["contact"]))
            text = media.pop("text") if media else None
        elif kind:
            item = message[kind][-1] if isinstance(message[kind], list) and message[kind] else message[kind]
            item = item if isinstance(item, dict) else {}
            media = {"type": KIND.get(kind, kind), "id": item.get("file_id"), "mime": item.get("mime_type"), "name": item.get("file_name"),
                     **({"caption": message["caption"]} if message.get("caption") else {}), **({"voice": True} if kind == "voice" else {})}
            text = text or PLACEHOLDER[kind]
    if not isinstance(text, str) or not text.strip():
        return []
    return [{"sid": "tg-%d" % chat, "id": "tg:%s" % update.get("update_id", uuid.uuid4().hex), "text": text, "media": media,
             "callback": query.get("id") if query else None, "start": not query and re.fullmatch(r"/start(@\w+)?(\s.*)?", text) is not None}]


def _resolve(record, text):
    """«#n» (un botón cuyo valor no entraba en el id) -> el valor de ese botón de la última pregunta."""
    match = re.fullmatch(r"#(\d+)", text.strip())
    buttons = ((record or {}).get("state") or {}).get("buttons") or []
    return buttons[int(match.group(1))]["value"] if match and int(match.group(1)) < len(buttons) else text


def _handle(agent_id, channel, item):
    app = auth._app()
    with _session_lock(agent_id + "/" + item["sid"]), telemetry.span("channel.message", **{"parla.agent.id": agent_id, "parla.channel": channel}):
        try:
            if item.get("callback"):         # que el botón de Telegram deje de girar
                _post(agent_id, _tg_base(agent_id) + "answerCallbackQuery", {"callback_query_id": item["callback"]})
            data = {"type": "start" if item.get("start") else "message", "sessionId": item["sid"], "channel": channel,
                    "environment": "production"}
            if not item.get("start"):
                data["text"] = _resolve(app.load_session(agent_id, item["sid"]), item["text"])
            with costs.scope(agent_id, item["sid"], channel):     # la transcripción cuenta en el mismo turno
                if item.get("media"):        # se descarga, se guarda y (si es audio) se transcribe: el bot recibe el texto
                    data["text"], data["media"] = _media(app.load(agent_id), channel, item["sid"], item)
                status, body = app.api_v1("POST", ["bots", agent_id, "events"], data)
            if status != 200:
                raise ChannelError(body.get("error"))
            _send(app.load(agent_id), channel, item["sid"], body.get("replies") or [], body.get("language"))
        except Exception as error:  # noqa: BLE001 - en un hilo: que quede en la consola y en el estado del canal
            _log(agent_id, channel, error)


def _run(agent_id, channel, items):
    for item in items:
        _handle(agent_id, channel, item)


def webhook(headers, rfile, method, ref, channel, query, length):
    """Las rutas públicas de los canales. Devuelve (status, cuerpo, tipo). Los rechazos no dan detalles."""
    app = auth._app()
    deny = (403, b"", "text/plain")
    agent = app.find_bot(urllib.parse.unquote(ref))
    if not agent or not config(agent, channel).get("enabled"):
        return deny
    agent_id = agent["id"]
    if method == "GET" and channel == "whatsapp":          # verificación de Meta al configurar el webhook
        expected, challenge = _secret(agent_id, "WHATSAPP_VERIFY_TOKEN"), query.get("hub.challenge") or ""
        if (query.get("hub.mode") == "subscribe" and expected and re.fullmatch(r"[A-Za-z0-9_.-]{1,200}", challenge)
                and hmac.compare_digest(str(query.get("hub.verify_token") or "").encode(), expected.encode())):
            return 200, challenge.encode(), "text/plain"
        return deny
    if method != "POST":
        return 405, b"", "text/plain"
    if length > MAX_BODY:
        return 413, b"", "text/plain"
    raw = rfile.read(length) if length else b""
    if channel == "whatsapp":
        key = _secret(agent_id, "WHATSAPP_APP_SECRET")
        given = str(headers.get("X-Hub-Signature-256") or "").encode()
        ok = bool(key) and hmac.compare_digest(given, b"sha256=" + hmac.new(key.encode(), raw, hashlib.sha256).hexdigest().encode())
    else:
        key = _secret(agent_id, "TELEGRAM_WEBHOOK_SECRET")
        ok = bool(key) and hmac.compare_digest(str(headers.get("X-Telegram-Bot-Api-Secret-Token") or "").encode(), key.encode())
    if not ok:
        return deny
    try:
        payload = json.loads(raw or b"{}")
        items = (parse_whatsapp(agent, payload) if channel == "whatsapp" else parse_telegram(payload)) if isinstance(payload, dict) else []
        for wamid, state, code in (parse_statuses(agent, payload) if channel == "whatsapp" else []):
            outbound.delivery(agent_id, wamid, state, code)     # entregado, leído o falló: el estado de cada envío
    except (ValueError, TypeError, AttributeError):    # firmado pero con otra forma: no reintentar en loop
        items = []
    _note(agent_id, channel, last_in=time.strftime("%Y-%m-%dT%H:%M:%S"))
    items = [i for i in items if _first_time(agent_id + "/" + i["id"])]
    if items:            # contestar 200 ya: Meta y Telegram reintentan si tardamos
        # con la traza del webhook: el turno queda como hijo de su pedido aunque se responda antes
        threading.Thread(target=contextvars.copy_context().run, args=(_run, agent_id, channel, items), daemon=True).start()
    return 200, b"{}" if channel == "telegram" else b"ok", "application/json" if channel == "telegram" else "text/plain"


# ---------- Bandeja y administración ----------

def send_now(agent_id, record, replies):
    """Manda ya, en el WhatsApp o Telegram de la conversación, y espera: ChannelError si no salió."""
    channel = record.get("channel")
    with _session_lock(agent_id + "/" + record["sessionId"]):
        agent = auth._app().load(agent_id)
        if not config(agent, channel).get("enabled"):
            raise ChannelError("el canal está apagado: el mensaje no se envió")
        return _send(agent, channel, record["sessionId"], replies, (record.get("state") or {}).get("lang"))


def human_reply(agent_id, record, text, replies=None):
    """Lo que escribe una persona desde la Bandeja (o lo que dice el bot al volver) también llega al WhatsApp o
    Telegram de quien chatea. En otro hilo: el error queda en el estado del canal."""
    if record.get("channel") not in CHANNELS:
        return
    def deliver():
        try:
            send_now(agent_id, record, replies or [{"text": text, "buttons": []}])
        except Exception as error:  # noqa: BLE001
            _log(agent_id, record.get("channel"), error)
    threading.Thread(target=deliver, daemon=True).start()


def info(agent):
    """Lo que muestra la pantalla «Canales»: direcciones de webhook, qué claves faltan y el último estado."""
    names, base = set(vault.names(agent["id"])), public_url(agent)
    return {"public_url": base, "env_public_url": os.environ.get("PARLA_PUBLIC_URL") or None,
            **{c: {"enabled": bool(config(agent, c).get("enabled")),
                   "webhook": "%s/api/v1/bots/%s/%s" % (base, agent["id"], c),
                   "secrets": {n: n in names for n in SECRETS[c]}, "status": dict(STATUS.get((agent["id"], c)) or {})}
               for c in CHANNELS}}


def telegram_webhook(agent, connect):
    """Conecta (setWebhook con el secreto) o desconecta (deleteWebhook) el bot de Telegram. ValueError para la persona."""
    try:
        base = _tg_base(agent["id"])
        if not connect:
            _post(agent["id"], base + "deleteWebhook", {})
            return {"connected": False}
        url = public_url(agent)
        if not url.startswith("https://"):
            raise ChannelError("falta la dirección pública con https:// (PARLA_PUBLIC_URL o «Dirección pública» acá arriba)")
        secret = _secret(agent["id"], "TELEGRAM_WEBHOOK_SECRET")
        if not secret:              # Telegram lo manda en cada pedido; nadie tiene que copiarlo
            secret = tokens.token_urlsafe(32)
            vault.put(agent["id"], "TELEGRAM_WEBHOOK_SECRET", secret)
        _post(agent["id"], base + "setWebhook", {"url": "%s/api/v1/bots/%s/telegram" % (url, agent["id"]), "secret_token": secret,
                                                 "allowed_updates": ["message", "callback_query"]})
        _note(agent["id"], "telegram", error=None, connected_at=time.strftime("%Y-%m-%dT%H:%M:%S"))
        return {"connected": True}
    except ChannelError as error:
        _log(agent["id"], "telegram", error)
        raise ValueError("Telegram: %s" % error) from None
