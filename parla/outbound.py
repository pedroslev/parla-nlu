"""Mensajes salientes: el bot escribe primero (API, campañas y recordatorios). Solo biblioteca estándar.

- send(): empieza una conversación de producción en WhatsApp, Telegram, teléfono o el widget web, con la misma sesión
  que usaría la persona al escribir (wa-<teléfono>, tg-<chat>, call-<CallSid>), datos precargados en los slots y un
  flujo. En WhatsApp, fuera de la ventana de 24 horas desde el último mensaje de la persona, solo vale una plantilla
  aprobada: se elige sola (catálogo en channels.whatsapp.templates) y el flujo corre cuando la persona contesta.
- Campañas: tablas campaigns y campaign_recipients (db.py). Un hilo (start) recorre la cola cada segundo con el
  límite de envíos de cada campaña, el horario de silencio y reintentos con espera (máximo 3). Lo que queda en la base
  sigue al reiniciar.
- Recordatorios: el paso {"type": "remind"} deja una fila en la misma cola para la misma persona.
- Bajas: «STOP», «BAJA»… (agent.outbound.optout_keywords) anotan a la persona en optouts y no se le escribe más.
"""
import csv
import io
import json
import re
import secrets
import sys
import threading
import time
import unicodedata
import urllib.parse
from collections import deque
from datetime import datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from . import auth, bus, channels, costs, db, pii, telemetry, vault

WINDOW = 24 * 3600              # la ventana de atención de WhatsApp
MAX_ATTEMPTS = 3
BACKOFF = 30                    # segundos antes del primer reintento; después el doble cada vez
DEFAULT_RATE = {"count": 20, "per": "minute"}
MAX_PER_SECOND = 50
MAX_RECIPIENTS = 10_000
API_PER_MINUTE = 30             # envíos por la API, por agente (para muchos: una campaña)
OPTOUT = {"es": ["stop", "baja", "no me escriban", "no me escribas", "desuscribir"],
          "en": ["stop", "unsubscribe", "opt out"], "pt": ["parar", "sair", "descadastrar"]}
OPTOUT_REPLY = {"es": "Listo, no te vamos a escribir más. Si cambiás de idea, escribinos cuando quieras.",
                "en": "Done, we won't message you again. If you change your mind, just write to us.",
                "pt": "Pronto, não vamos mais te escrever. Se mudar de ideia, é só nos escrever."}
STATUSES = ("queued", "sending", "sent", "delivered", "read", "replied", "failed", "opted_out", "canceled")
PROGRESS = {"sent": 1, "delivered": 2, "read": 3, "replied": 4}        # un «delivered» tardío no pisa un «read»
TO_COLUMNS = {"to", "phone", "telefono", "teléfono", "numero", "número", "celular", "whatsapp", "chat_id", "chat", "destinatario"}
CAMPAIGN = re.compile(r"[0-9a-f]{12}")

clock = time.time               # las pruebas lo cambian por un reloj propio
_lock = threading.RLock()       # ponytail: un lock para toda la cola; con varias réplicas haría falta reservar filas en la base
_next = {}                      # campaña -> cuándo puede salir el próximo envío (límite de velocidad)
_api = {}                       # agente -> instantes de los últimos envíos por la API
_wake = threading.Event()       # algo nuevo en la cola (encolar, arrancar una campaña): la vuelta no espera
MAX_SLEEP = 5                   # segundos como mucho entre vueltas (horarios de silencio que se abren, reintentos)


class OutboundError(ValueError):
    """Un envío que no se puede hacer (el motivo es para la persona). status: el HTTP para la API."""
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


class OptedOut(OutboundError):
    pass


def _app():
    return auth._app()


def _now_text(now=None):
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(now or clock()))


def mask(address):
    """«5491112345678» -> «549••••••5678»: los teléfonos no van enteros a la consola ni a la auditoría."""
    text = str(address or "")
    return text[:3] + "•" * (len(text) - 7) + text[-4:] if len(text) > 7 else "•" * len(text)


def scrub(text):
    return re.sub(r"\+?\d{7,}", lambda m: mask(m.group()), str(text or ""))


def _log(agent_id, channel, message):
    channels._log(agent_id, channel, scrub(message))


def address_of(channel, to):
    """El destinatario normalizado: teléfono solo con dígitos, chat de Telegram, o sessionId del widget."""
    raw = str(to if to is not None else "").strip()
    if channel in ("whatsapp", "phone"):
        digits = re.sub(r"[\s().+-]", "", raw)
        if re.fullmatch(r"\d{6,15}", digits):
            return digits
        raise OutboundError("«to» tiene que ser un teléfono con código de país, por ejemplo +5491112345678")
    if channel == "telegram":
        if re.fullmatch(r"-?\d{1,20}", raw):
            return raw
        raise OutboundError("«to» tiene que ser el chat id de Telegram (un número)")
    if channel == "web":
        if _app().SESSION_ID.fullmatch(raw):
            return raw
        raise OutboundError("«to» tiene que ser el sessionId de una conversación del widget web")
    raise OutboundError("«channel» tiene que ser whatsapp, telegram, phone o web")


def session_of(channel, address):
    return {"whatsapp": "wa-", "telegram": "tg-"}.get(channel, "") + address


def address_from_session(sid):
    """(canal, destinatario) de una conversación: wa-<teléfono>, tg-<chat> o la del widget. None si no se le puede escribir."""
    for prefix, channel in (("wa-", "whatsapp"), ("tg-", "telegram")):
        if sid.startswith(prefix):
            return channel, sid[len(prefix):]
    return None


# ---------- bajas ----------

def _fold(text):
    plain = unicodedata.normalize("NFD", str(text or "")).encode("ascii", "ignore").decode().lower()
    return " ".join(re.sub(r"[^\w\s]", " ", plain).split())


def keywords(agent):
    own = ((agent or {}).get("outbound") or {}).get("optout_keywords")
    own = own if isinstance(own, dict) else {}
    return {lang: [w for w in (own[lang] if isinstance(own.get(lang), list) else words) if isinstance(w, str) and w.strip()]
            for lang, words in {**OPTOUT, **{k: [] for k in own}}.items()}


def is_optout(agent, text):
    """¿Pide no recibir más mensajes? Una palabra sola tiene que ser todo el mensaje («stop»); una frase, estar adentro."""
    said = _fold(text)
    for word in (w for words in keywords(agent).values() for w in words):
        word = _fold(word)
        if word and (said == word or (" " in word and re.search(r"(?<!\w)%s(?!\w)" % re.escape(word), said))):
            return word
    return None


def opted_out(agent_id, address):
    return bool(db.q("SELECT 1 FROM optouts WHERE agent_id = ? AND address = ?", (agent_id, str(address))))


def opt_out(agent_id, address, channel=None, keyword=None):
    with db.connect() as conn:
        conn.execute("INSERT OR REPLACE INTO optouts (agent_id, address, channel, keyword, at) VALUES (?, ?, ?, ?, ?)",
                     (agent_id, str(address), channel, keyword, _now_text()))
        conn.execute("UPDATE campaign_recipients SET status = 'opted_out', updated = ? WHERE agent_id = ? AND address = ? AND status = 'queued'",
                     (_now_text(), agent_id, str(address)))
    telemetry.count("parla_outbound_messages_total", channel=telemetry.channel(channel), outcome="opted_out")


def optouts(agent_id):
    rows = db.q("SELECT address, channel, keyword, at FROM optouts WHERE agent_id = ? ORDER BY at DESC", (agent_id,))
    return [dict(zip(("address", "channel", "keyword", "at"), r)) for r in rows]


def inbound(agent, record, text):
    """Lo llama api_v1 con cada mensaje de la persona: anota la ventana de 24 h, la respuesta a un envío y las bajas.
    Devuelve el texto de confirmación si pidió la baja (el bot no contesta otra cosa), o None."""
    record["last_inbound"] = clock()
    db.q("UPDATE campaign_recipients SET status = 'replied', updated = ? WHERE agent_id = ? AND session_id = ? AND status IN ('sent', 'delivered', 'read')",
         (_now_text(), agent["id"], record["sessionId"]))
    target = address_from_session(record["sessionId"]) or (("web", record["sessionId"]) if record.get("channel") == "web" else None)
    word = is_optout(agent, text) if target else None
    if not word:
        return None
    opt_out(agent["id"], target[1], target[0], word)
    lang = (record.get("state") or {}).get("lang") or (agent.get("languages") or ["es"])[0]
    return OPTOUT_REPLY.get(lang, OPTOUT_REPLY["es"])


# ---------- WhatsApp: ventana y plantillas ----------

LANG_CODES = {"es": "es", "en": "en_US", "pt": "pt_BR"}
META = {       # códigos de error de la Cloud API -> (mensaje, ¿vale reintentar?)
    131047: ("pasaron más de 24 horas desde el último mensaje de la persona: WhatsApp solo deja mandar una plantilla aprobada", False),
    131026: ("WhatsApp no pudo entregar el mensaje (¿ese número tiene WhatsApp?)", False),
    131050: ("la persona pidió no recibir mensajes de marketing de esta empresa en WhatsApp", False),
    132000: ("la cantidad de datos no coincide con los de la plantilla de WhatsApp: revisá «params»", False),
    132001: ("la plantilla no existe en ese idioma o todavía no está aprobada en WhatsApp", False),
    132005: ("el texto de la plantilla con los datos quedó demasiado largo", False),
    132007: ("la plantilla no cumple las políticas de WhatsApp", False),
    132012: ("un dato no tiene el formato que pide la plantilla de WhatsApp", False),
    132015: ("la plantilla está pausada por baja calidad en WhatsApp", False),
    132016: ("la plantilla está desactivada en WhatsApp", False),
}
SLOW = "WhatsApp pidió ir más despacio (límite de envíos): se reintenta más tarde"
SLOW_CODES = {4, 80007, 130429, 131048, 131056}


def explain(channel, error):
    """(mensaje para la persona, ¿reintentar?) de un ChannelError."""
    code, status = getattr(error, "code", None), getattr(error, "status", None)
    if channel == "whatsapp" and code in META:
        return META[code]
    if channel == "whatsapp" and code in SLOW_CODES:
        return SLOW, True
    if channel == "whatsapp" and isinstance(code, int) and 132000 <= code < 133000:
        return "WhatsApp rechazó la plantilla (código %s)" % code, False
    if channel == "telegram" and status == 403:
        return "la persona bloqueó al bot de Telegram (o nunca le escribió)", False
    return scrub(error), status in (0, None, 429) or (status or 0) >= 500


def in_window(record, now=None):
    last = (record or {}).get("last_inbound")
    return isinstance(last, (int, float)) and (now or clock()) - last < WINDOW


def template_for(agent, template):
    """La plantilla a usar: {name, language, params, components?}, completada con el catálogo del agente. None si no hay."""
    if not template:
        return None
    given = {"name": template} if isinstance(template, str) else template
    if not isinstance(given, dict):
        raise OutboundError("«template» tiene que ser el nombre de una plantilla o {name, language, params}")
    catalog = channels.config(agent, "whatsapp").get("templates") or []
    found = next((t for t in catalog if isinstance(t, dict) and t.get("name") == given.get("name")), {})
    tpl = {**found, **{k: v for k, v in given.items() if v not in (None, "", [])}}
    if not re.fullmatch(r"[a-z0-9_]{1,512}", str(tpl.get("name") or "")):
        raise OutboundError("la plantilla tiene que tener un «name» como el de Meta (minúsculas, números y _)")
    tpl.setdefault("language", LANG_CODES.get((agent.get("languages") or ["es"])[0], "es"))
    if not isinstance(tpl.get("params") or [], list) or not isinstance(tpl.get("components") or [], list):
        raise OutboundError("«params» de la plantilla es la lista de slots para {{1}}, {{2}}…")
    return tpl


def template_message(tpl, address, data):
    """El mensaje de plantilla de la Cloud API: cada slot de «params» va a {{1}}, {{2}}… del cuerpo."""
    components = tpl.get("components")
    if not components and tpl.get("params"):
        values = []
        for name in tpl["params"]:
            value = (data or {}).get(name)
            if value in (None, ""):
                raise OutboundError("falta el dato «%s» para la plantilla «%s»" % (name, tpl["name"]))
            values.append({"type": "text", "text": str(value)[:1024]})
        components = [{"type": "body", "parameters": values}]
    return {"messaging_product": "whatsapp", "recipient_type": "individual", "to": address, "type": "template",
            "template": {"name": tpl["name"], "language": {"code": str(tpl["language"])}, **({"components": components} if components else {})}}


def _post_template(agent, sid, tpl, message):
    token = channels._secret(agent["id"], "WHATSAPP_TOKEN")
    phone_id = str(channels.config(agent, "whatsapp").get("phone_number_id") or "")
    if not token or not re.fullmatch(r"\d{1,30}", phone_id):
        raise OutboundError("falta la clave WHATSAPP_TOKEN o el «phone_number_id»")
    sent = channels._post(agent["id"], "%s/%s/messages" % (channels._wa_api(), phone_id), message, token=token)
    costs.record("whatsapp", "meta", "template:%s" % str(tpl.get("category") or "unknown").lower()[:30], 1,
                 agent=agent["id"], session=sid, channel="whatsapp")
    return sent


def catalog(agent):
    """Las plantillas aprobadas del agente (channels.whatsapp.templates), para elegir una desde la Bandeja."""
    return [{k: t[k] for k in ("name", "language", "params", "category", "text") if k in t}
            for t in channels.config(agent, "whatsapp").get("templates") or [] if isinstance(t, dict) and t.get("name")]


def operator_template(agent, record, template):
    """Una persona (Bandeja o contact center) le escribe fuera de las 24 h: manda una plantilla aprobada.
    template: nombre o {name, language?, params?}; params es la lista de valores para {{1}}, {{2}}… y, si no viene,
    salen de los slots de la conversación (los nombres de «params» del catálogo). -> {text (para el historial), template}."""
    given = {"name": template} if isinstance(template, str) else template
    if not isinstance(given, dict):
        raise OutboundError("«template» tiene que ser el nombre de una plantilla o {name, language, params}")
    found = next((t for t in catalog(agent) if t["name"] == given.get("name")), None)
    if not found:
        raise OutboundError("no existe la plantilla «%s» en Canales → WhatsApp → Plantillas" % str(given.get("name") or "")[:80])
    names = [str(n) for n in found.get("params") or []]
    values = given.get("params")
    if isinstance(values, list):
        names = [names[i] if i < len(names) else str(i + 1) for i in range(len(values))]
        data = {names[i]: v for i, v in enumerate(values)}
    elif values is None:
        data = (record.get("state") or {}).get("slots") or {}
    else:
        raise OutboundError("«params» de la plantilla es la lista de valores para {{1}}, {{2}}…")
    tpl = template_for(agent, {"name": found["name"], "language": given.get("language") or found.get("language"), "params": names})
    sent = _post_template(agent, record["sessionId"], tpl, template_message(tpl, address_from_session(record["sessionId"])[1], data))
    shown = [str(data.get(n)) for n in names]
    return {"text": "[%s%s]" % (tpl["name"], ": " + " · ".join(shown) if shown else ""),
            "template": {"name": tpl["name"], "message_id": ((sent.get("messages") or [{}])[0]).get("id")}}


# ---------- enviar ----------

def _production_flows(agent):
    return {f["name"] for f in _app().target(agent, "production")[1]["flows"]}


def send(agent, channel, to, data=None, flow=None, template=None, text=None, campaign=None, row=None, now=None):
    """Escribe primero. -> {"sessionId", "via": "message"|"template"|"call", "messages", "message_id"}.
    OutboundError si no se puede (canal apagado, baja, fuera de la ventana sin plantilla…); ChannelError si falla el canal."""
    app, now = _app(), now or clock()
    address = address_of(channel, to)
    data = data if isinstance(data, dict) else {}
    if channel != "web" and not channels.config(agent, channel).get("enabled"):
        raise OutboundError("el canal «%s» está apagado: prendelo en Canales" % channel)
    if opted_out(agent["id"], address):
        raise OptedOut("esa persona pidió no recibir más mensajes de este bot", 409)
    if flow and flow not in _production_flows(agent):
        raise OutboundError("no existe el flujo «%s»" % flow)
    if channel == "phone":
        return _call(agent, address, data, flow, campaign, row)
    sid = session_of(channel, address)
    record = app.load_session(agent["id"], sid)
    if channel == "telegram" and not record:
        raise OutboundError("esa persona nunca le escribió al bot por Telegram: Telegram solo deja escribirle a quien empezó el chat")
    if channel == "web" and (record or {}).get("channel") != "web":
        raise OutboundError("no hay una conversación del widget web con ese id")
    if ((record or {}).get("handoff") or {}).get("active") and not record.get("ended"):
        raise OutboundError("una persona del equipo está atendiendo esa conversación", 409)
    tpl = template_for(agent, template) if channel == "whatsapp" else None
    if channel == "whatsapp" and (not in_window(record, now) or not (flow or text)):
        if not tpl:
            raise OutboundError("pasaron más de 24 horas desde el último mensaje de esa persona en WhatsApp (o nunca escribió): "
                                "solo se puede mandar una plantilla aprobada. Elegí una en «template»", 409)
        sent = _post_template(agent, sid, tpl, template_message(tpl, address, data))
        app.outbound_session(agent["id"], sid, channel, data, flow=None, campaign=campaign, on_reply=flow,
                             note="Se envió la plantilla «%s»" % tpl["name"])
        return {"sessionId": sid, "via": "template", "messages": [], "message_id": ((sent.get("messages") or [{}])[0]).get("id")}
    record, result = app.outbound_session(agent["id"], sid, channel, data, flow=flow, campaign=campaign, text=text)
    if not result["replies"]:
        raise OutboundError("no hay nada que mandar: elegí un flujo (o armá uno «Al empezar la conversación»), un texto o una plantilla")
    last = channels._send(agent, channel, sid, result["replies"], result.get("language")) if channel != "web" else None
    return {"sessionId": sid, "via": "message", "messages": result["messages"], "message_id": str(last) if last else None}


def _call(agent, address, data, flow, campaign, row):
    """Llamada saliente por Twilio o jambonz. El proveedor pide el webhook de siempre con ?o=<token>, y phone.py
    empieza la conversación con estos datos y este flujo (pending)."""
    from . import phone
    conf, keys = channels.config(agent, "phone"), vault.values(agent["id"])
    provider, caller = conf.get("provider") or "twilio", str(conf.get("from") or "").strip()
    if not re.fullmatch(r"\+?\d{6,15}|sips?:\S+", caller):
        raise OutboundError("falta «Número desde el que se llama» (channels.phone.from) en Canales → Teléfono")
    if not channels.public_url(agent).startswith("https://"):
        raise OutboundError("falta la dirección pública con https:// (PARLA_PUBLIC_URL o «Dirección pública» en Canales)")
    token = secrets.token_urlsafe(18)
    db.q("UPDATE campaign_recipients SET token = ? WHERE id = ?", (token, row))
    hook, status = phone._hook(agent, provider) + "?o=" + token, phone._hook(agent, provider, "status") + "?o=" + token
    if provider == "twilio":
        sid_, auth_token = keys.get("TWILIO_ACCOUNT_SID") or "", keys.get("TWILIO_AUTH_TOKEN") or ""
        if not re.fullmatch(r"AC[0-9a-fA-F]{32}", sid_) or not auth_token:
            raise OutboundError("faltan las claves TWILIO_ACCOUNT_SID (AC…) y TWILIO_AUTH_TOKEN")
        form = urllib.parse.urlencode([("To", "+" + address), ("From", caller), ("Url", hook), ("Method", "POST"),
                                       ("StatusCallback", status), ("StatusCallbackMethod", "POST")]
                                      + [("StatusCallbackEvent", e) for e in ("initiated", "ringing", "answered", "completed")]).encode()
        basic = "Basic " + __import__("base64").b64encode(("%s:%s" % (sid_, auth_token)).encode()).decode()
        base = (__import__("os").environ.get("PARLA_TWILIO_API") or "https://api.twilio.com").rstrip("/")
        made = channels._post(agent["id"], "%s/2010-04-01/Accounts/%s/Calls.json" % (base, sid_), body=form,
                              ctype="application/x-www-form-urlencoded", authorization=basic)
    else:
        key, account = keys.get("JAMBONZ_API_KEY") or "", keys.get("JAMBONZ_ACCOUNT_SID") or ""
        if not key or not re.fullmatch(r"[A-Za-z0-9-]{8,64}", account):
            raise OutboundError("faltan las claves JAMBONZ_API_KEY y JAMBONZ_ACCOUNT_SID")
        login = {"username": keys["JAMBONZ_BASIC_USER"], "password": keys["JAMBONZ_BASIC_PASSWORD"]} \
            if keys.get("JAMBONZ_BASIC_USER") and keys.get("JAMBONZ_BASIC_PASSWORD") else {}
        body = {"from": caller, "to": {"type": "phone", "number": "+" + address},
                "call_hook": {"url": hook, "method": "POST", **login}, "call_status_hook": {"url": status, "method": "POST", **login},
                "tag": {"parla": token}, **({"application_sid": conf["application_sid"]} if conf.get("application_sid") else {})}
        base = str(conf.get("api_url") or "https://api.jambonz.cloud").rstrip("/")
        made = channels._post(agent["id"], "%s/v1/Accounts/%s/Calls" % (base, account), body, token=key)
    call = str((made or {}).get("sid") or "")
    if not phone.CALL_ID.fullmatch(call):
        raise channels.ChannelError("el proveedor no devolvió el id de la llamada")
    db.q("UPDATE campaign_recipients SET session_id = ? WHERE id = ?", ("call-" + call, row))
    costs.record("phone_call", provider, "outbound", 1, agent=agent["id"], session="call-" + call, channel="phone")
    return {"sessionId": "call-" + call, "via": "call", "messages": [], "message_id": call}


def pending(agent_id, token):
    """La llamada saliente que espera este token (phone.py): {id, data, flow, campaign}, o None."""
    if not token or not re.fullmatch(r"[A-Za-z0-9_-]{10,64}", token):
        return None
    rows = db.q("SELECT id, spec, campaign_id FROM campaign_recipients WHERE agent_id = ? AND token = ?", (agent_id, token))
    if not rows:
        return None
    spec, flow = json.loads(rows[0][1]), None
    if rows[0][2]:
        flow = (_campaign(rows[0][2]) or {}).get("config", {}).get("flow")
    return {"id": rows[0][0], "data": spec.get("data") or {}, "flow": spec.get("flow") or flow, "campaign": rows[0][2]}


def call_status(row, status):
    """Lo que avisa el proveedor de una llamada saliente: atendió (entregado), o no atendió / falló."""
    if status in ("answered", "in-progress"):
        db.q("UPDATE campaign_recipients SET status = 'delivered', updated = ? WHERE id = ? AND status = 'sent'", (_now_text(), row))
    elif status in ("busy", "failed", "no-answer", "canceled"):
        db.q("UPDATE campaign_recipients SET status = 'failed', error = ?, updated = ? WHERE id = ? AND status IN ('sent', 'sending')",
             ("no atendió (%s)" % status, _now_text(), row))


def delivery(agent_id, wamid, state, code=None):
    """Webhook de estado de WhatsApp: sent, delivered, read o failed de un mensaje que mandamos."""
    if not wamid or state not in ("sent", "delivered", "read", "failed"):
        return
    rows = db.q("SELECT id, status FROM campaign_recipients WHERE agent_id = ? AND message_id = ?", (agent_id, wamid))
    for row, current in rows:
        if state == "failed":
            message = META.get(code, ("WhatsApp no pudo entregar el mensaje (código %s)" % code, False))[0]
            db.q("UPDATE campaign_recipients SET status = 'failed', error = ?, updated = ? WHERE id = ?", (message, _now_text(), row))
            telemetry.count("parla_outbound_messages_total", channel="whatsapp", outcome="failed")
        elif PROGRESS.get(state, 0) > PROGRESS.get(current, -1) and current != "failed":
            db.q("UPDATE campaign_recipients SET status = ?, updated = ? WHERE id = ?", (state, _now_text(), row))


# ---------- la cola ----------

def _enqueue(agent_id, kind, channel, address, spec, campaign=None, status="queued", next_at=0):
    with db.connect() as conn:
        cur = conn.execute("INSERT OR IGNORE INTO campaign_recipients (campaign_id, agent_id, kind, channel, address, spec, status, next_at, created, updated) "
                           "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                           (campaign, agent_id, kind, channel, address, json.dumps(spec, ensure_ascii=False), status, next_at, _now_text(), _now_text()))
        row = cur.lastrowid if cur.rowcount else None
    _wake.set()
    return row


def _finish(row, agent_id, channel, status, error=None, sent=None, spec=None):
    fields = {"status": status, "error": error, "updated": _now_text()}
    if sent:
        fields.update(session_id=sent.get("sessionId"), message_id=sent.get("message_id"), sent_at=_now_text())
    if spec is not None:
        fields["spec"] = json.dumps(spec, ensure_ascii=False)
    db.q("UPDATE campaign_recipients SET %s WHERE id = ?" % ", ".join("%s = ?" % k for k in fields), tuple(fields.values()) + (row,))
    bus.publish("campaign:" + agent_id, {"type": "campaign"})      # la pantalla de Campañas en vivo (SSE)
    outcome = {"sent": "sent", "queued": "retry"}.get(status, status)
    telemetry.count("parla_outbound_messages_total", channel=telemetry.channel(channel), outcome=outcome)


def deliver_row(row, now=None):
    """Manda una fila de la cola (campaña o recordatorio) y la deja como quedó: enviada, reintento, falló o baja."""
    now = now or clock()
    rid, agent_id, kind, channel, address, spec, campaign, attempts = row
    spec = json.loads(spec)
    conf = (_campaign(campaign) or {}).get("config", {}) if campaign else {}
    db.q("UPDATE campaign_recipients SET status = 'sending', attempts = attempts + 1, updated = ? WHERE id = ?", (_now_text(now), rid))
    try:
        agent = _app().load(agent_id)
        sent = send(agent, channel, address, spec.get("data"), spec.get("flow") or conf.get("flow"), spec.get("template") or conf.get("template"),
                    spec.get("text"), campaign or spec.get("campaign"), rid, now)
    except OutboundError as error:
        _finish(rid, agent_id, channel, "opted_out" if isinstance(error, OptedOut) else "failed", str(error))
        return
    except channels.ChannelError as error:
        message, transient = explain(channel, error)
        _log(agent_id, channel, "%s a %s: %s" % ("campaña %s" % campaign if campaign else kind, mask(address), message))
        if transient and attempts + 1 < MAX_ATTEMPTS:
            db.q("UPDATE campaign_recipients SET next_at = ? WHERE id = ?", (now + BACKOFF * 2 ** attempts, rid))
            _finish(rid, agent_id, channel, "queued", message)
        else:
            _finish(rid, agent_id, channel, "failed", message)
        return
    except Exception as error:  # noqa: BLE001 - un agente borrado o roto: que falle esa fila, no la cola
        _finish(rid, agent_id, channel, "failed", scrub(error))
        return
    cats = pii.categories(_app().settings_of(agent_id).get("pii_redaction"))
    _finish(rid, agent_id, channel, "sent", None, sent, dict(spec, data=pii.scrub(spec.get("data") or {}, cats)) if cats else None)


def _due(where, args, now, limit):
    return db.q("SELECT id, agent_id, kind, channel, address, spec, campaign_id, attempts FROM campaign_recipients "
                "WHERE status = 'queued' AND next_at <= ? AND %s ORDER BY next_at, id LIMIT ?" % where, (now,) + tuple(args) + (limit,))


def _seconds(rate):
    rate = rate or DEFAULT_RATE
    return (1 if rate.get("per") == "second" else 60) / max(1, int(rate.get("count") or 1))


def _clock_of(conf, now):
    try:
        zone = ZoneInfo((conf.get("schedule") or {}).get("timezone") or "UTC")
    except (ZoneInfoNotFoundError, ValueError):
        zone = ZoneInfo("UTC")
    return datetime.fromtimestamp(now, zone)


def quiet(conf, now):
    """¿Es horario de silencio en la zona horaria de la campaña? 21:00–09:00 cruza la medianoche."""
    hours = conf.get("quiet_hours")
    if not hours:
        return False
    here = _clock_of(conf, now).strftime("%H:%M")
    start, end = hours.get("start"), hours.get("end")
    return (start <= here or here < end) if start > end else start <= here < end


def starts_at(conf):
    at = (conf.get("schedule") or {}).get("at")
    if not at:
        return 0
    zone = _clock_of(conf, 0).tzinfo
    return datetime.fromisoformat(at).replace(tzinfo=zone).timestamp()


def waiting(campaign, now=None):
    now = now or clock()
    if campaign["status"] != "running":
        return None
    if starts_at(campaign["config"]) > now:
        return "schedule"
    return "quiet_hours" if quiet(campaign["config"], now) else None


def tick(now=None):
    """Una vuelta de la cola: las campañas en marcha (con su límite y su horario) y los recordatorios que vencieron."""
    now = now or clock()
    with _lock:
        for (cid,) in db.q("SELECT id FROM campaigns WHERE status = 'running' ORDER BY created"):
            _tick_campaign(cid, now)
        for row in _due("campaign_id IS NULL", (), now, 50):
            deliver_row(row, now)


def _tick_campaign(cid, now):
    campaign = _campaign(cid)
    if not campaign or waiting(campaign, now):
        return
    interval, sent = _seconds(campaign["config"].get("rate")), 0
    while sent < 200:
        if _next.get(cid, 0) > now or (_campaign(cid) or {}).get("status") != "running":    # pausa o cancelación a mitad
            return
        rows = _due("campaign_id = ?", (cid,), now, 1)
        if not rows:
            break
        _next[cid] = max(_next.get(cid, 0), now - 1) + interval     # hasta 1 segundo de ráfaga, nunca más rápido que el límite
        deliver_row(rows[0], now)
        sent += 1
    if not db.q("SELECT 1 FROM campaign_recipients WHERE campaign_id = ? AND status IN ('queued', 'sending') LIMIT 1", (cid,)):
        db.q("UPDATE campaigns SET status = 'done', updated = ? WHERE id = ? AND status = 'running'", (_now_text(now), cid))
        from . import handoff         # aquí: handoff importa outbound
        handoff.emit_by_id(campaign["agent_id"], "campaign.finished", None,
                           campaign={"id": cid, "name": campaign["name"], "channel": campaign["channel"], "stats": stats(campaign)})


def recover():
    """Al arrancar: lo que quedó «enviando» cuando se cortó no se sabe si salió. Mejor no mandarlo dos veces."""
    db.q("UPDATE campaign_recipients SET status = 'failed', error = 'se cortó por un reinicio: no se sabe si salió', updated = ? "
         "WHERE status = 'sending'", (_now_text(),))


def _sleep():
    """Hasta el próximo envío que vence (fila con next_at o el límite de velocidad de una campaña), como mucho MAX_SLEEP.
    Recordatorios y envíos de la API ya vencidos que no entraron en la vuelta (50 por vuelta): enseguida."""
    now = clock()
    if db.q("SELECT 1 FROM campaign_recipients WHERE status = 'queued' AND campaign_id IS NULL AND next_at <= ? LIMIT 1", (now,)):
        return 0.05
    due = db.q("SELECT min(r.next_at) FROM campaign_recipients r LEFT JOIN campaigns c ON c.id = r.campaign_id WHERE r.status = 'queued' "
               "AND r.next_at > ? AND (r.campaign_id IS NULL OR c.status = 'running')", (now,))[0][0]
    soon = [t for t in list(_next.values()) + [due] if t and t > now]
    return max(0.05, min([MAX_SLEEP] + [t - now for t in soon]))


def _loop():
    while True:
        try:
            tick()
            wait = _sleep()
        except Exception:  # noqa: BLE001 - que la cola no se muera por una fila rara: sigue en un segundo
            import traceback
            traceback.print_exc(file=sys.stderr)
            wait = 1
        _wake.wait(wait)
        _wake.clear()


def start():
    recover()
    threading.Thread(target=_loop, daemon=True, name="parla-outbound").start()


# ---------- recordatorios (paso remind) ----------

def remind_at(step, ctx, agent, now=None):
    """Cuándo sale el recordatorio (segundos epoch): «after» (30m, 24h, 2d) o «at» (texto con {{ }}, «2026-12-01 09:00»)."""
    now = now or clock()
    if step.get("after"):
        m = re.fullmatch(r"\s*(\d+)\s*([mhd])\s*", str(step["after"]))
        if not m:
            raise ValueError("«after» tiene que ser algo como 30m, 24h o 2d")
        return now + int(m.group(1)) * {"m": 60, "h": 3600, "d": 86400}[m.group(2)]
    if not step.get("at"):
        raise ValueError("elegí cuándo mandar el recordatorio («after» o «at»)")
    text = _app().render(str(step["at"]), ctx).strip()
    try:
        when = datetime.fromisoformat(text.replace(" ", "T", 1))
    except ValueError:
        raise ValueError("no entendí la fecha del recordatorio: «%s» (tiene que quedar como 2026-12-01 09:00)" % text) from None
    zone = ((agent.get("outbound") or {}).get("timezone")) or None
    try:
        return when.replace(tzinfo=ZoneInfo(zone)).timestamp() if zone and when.tzinfo is None else when.timestamp()
    except (ZoneInfoNotFoundError, ValueError):
        return when.timestamp()


def remind(agent_id, record, item):
    """Deja en la cola el recordatorio que pidió un paso remind. Devuelve el texto para el historial."""
    target = address_from_session(record["sessionId"]) or (("web", record["sessionId"]) if record.get("channel") == "web" else None)
    if record.get("channel") == "phone":
        caller = ((record.get("state") or {}).get("slots") or {}).get("caller")
        target = ("phone", re.sub(r"\D", "", str(caller))) if caller else None
    when = _now_text(item["at"])
    if not target:
        return "Recordatorio para %s: no se envía desde este canal (%s)" % (when, record.get("channel"))
    slots = {k: v for k, v in ((record.get("state") or {}).get("slots") or {}).items() if v not in (None, "")}
    spec = {"data": slots, "flow": item.get("flow"), "template": item.get("template"), "text": item.get("text"),
            "campaign": record.get("campaign")}
    _enqueue(agent_id, "remind", target[0], target[1], spec, next_at=item["at"])
    return "Recordatorio programado para %s" % when


# ---------- campañas ----------

def _campaign(cid):
    rows = db.q("SELECT id, agent_id, name, channel, status, config, created, updated, created_by FROM campaigns WHERE id = ?", (cid,))
    if not rows:
        return None
    out = dict(zip(("id", "agent_id", "name", "channel", "status", "config", "created", "updated", "created_by"), rows[0]))
    out["config"] = json.loads(out["config"])
    return out


def _owned(agent, cid):
    campaign = _campaign(cid) if CAMPAIGN.fullmatch(cid or "") else None
    if not campaign or campaign["agent_id"] != agent["id"]:
        raise OutboundError("no existe esa campaña", 404)
    return campaign


def stats(campaign):
    counts = dict.fromkeys(STATUSES, 0)
    for status, n in db.q("SELECT status, count(*) FROM campaign_recipients WHERE campaign_id = ? GROUP BY status", (campaign["id"],)):
        counts[status] = n
    if not sum(counts.values()) and campaign["config"].get("final_stats"):      # la retención ya borró los destinatarios
        return campaign["config"]["final_stats"]
    counts["total"] = sum(counts.values())
    counts["conversions"] = conversions(campaign)
    return counts


def converted(record, goal):
    """¿La conversación llegó a la meta de la campaña? Clasificación, intención, flujo o una nota de CSAT mínima."""
    if not goal:
        return False
    names = [m.get("name") for m in record.get("classifications") or []]
    said = [h for h in record.get("history") or [] if h.get("from") == "user"]
    return bool((goal.get("classification") and goal["classification"] in names)
                or (goal.get("intent") and any(h.get("intent") == goal["intent"] for h in said))
                or (goal.get("flow") and any(h.get("flow") == goal["flow"] for h in said))
                or (goal.get("csat") and (record.get("csat") or 0) >= int(goal["csat"])))


def conversions(campaign):
    goal = campaign["config"].get("conversion")
    if not goal:
        return 0
    rows = db.q("SELECT record FROM sessions WHERE agent_id = ? AND json_extract(record, '$.campaign') = ?", (campaign["agent_id"], campaign["id"]))
    return sum(converted(json.loads(r[0]), goal) for r in rows)


def public(campaign, now=None):
    conf = campaign["config"]
    return {"id": campaign["id"], "name": campaign["name"], "channel": campaign["channel"], "status": campaign["status"],
            "waiting": waiting(campaign, now), "created": campaign["created"], "updated": campaign["updated"],
            "created_by": campaign["created_by"], "flow": conf.get("flow"), "template": conf.get("template"),
            "schedule": conf.get("schedule"), "rate": conf.get("rate"), "quiet_hours": conf.get("quiet_hours"),
            "conversion": conf.get("conversion"), "stats": stats(campaign)}


def _hhmm(value):
    if not re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", str(value or "")):
        raise OutboundError("el horario de silencio va como HH:MM, por ejemplo 21:00 a 09:00")
    return value


def settings(agent, data, base=None):
    """Valida y completa la configuración de una campaña (lo que no se manda queda como estaba)."""
    conf = dict((base or {}).get("config") or {})
    name = str(data.get("name", (base or {}).get("name")) or "").strip()[:80]
    channel = data.get("channel", (base or {}).get("channel"))
    if not name:
        raise OutboundError("ponele un nombre a la campaña")
    if channel not in ("whatsapp", "telegram", "phone"):
        raise OutboundError("«channel» tiene que ser whatsapp, telegram o phone")
    if "flow" in data:
        if data["flow"] and data["flow"] not in _production_flows(agent):        # lo que corre es lo publicado
            raise OutboundError("no existe el flujo «%s»" % data["flow"])
        conf["flow"] = data["flow"] or None
    if "template" in data:
        conf["template"] = {k: v for k, v in template_for(agent, data["template"]).items() if k in ("name", "language", "params", "components")} \
            if data["template"] and channel == "whatsapp" else None
    if channel == "whatsapp" and not conf.get("template"):
        raise OutboundError("en WhatsApp la campaña necesita una plantilla aprobada (y opcionalmente un flujo para cuando contesten)")
    if "schedule" in data or "schedule" not in conf:
        schedule = data.get("schedule") or {}
        zone = str(schedule.get("timezone") or "UTC")
        try:
            ZoneInfo(zone)
        except (ZoneInfoNotFoundError, ValueError):
            raise OutboundError("no conozco la zona horaria «%s» (usá una como America/Argentina/Buenos_Aires)" % zone) from None
        at = schedule.get("at") or None
        if at:
            try:
                at = datetime.fromisoformat(str(at)).strftime("%Y-%m-%dT%H:%M")
            except ValueError:
                raise OutboundError("la fecha de envío va como 2026-12-01T10:00") from None
        conf["schedule"] = {"at": at, "timezone": zone}
    if "rate" in data or "rate" not in conf:
        rate = data.get("rate") or DEFAULT_RATE
        try:
            count = int(rate.get("count"))
        except (TypeError, ValueError, AttributeError):
            raise OutboundError("el límite de envíos es {count, per: second|minute}") from None
        per = rate.get("per") if rate.get("per") in ("second", "minute") else "minute"
        if count < 1 or (count > MAX_PER_SECOND if per == "second" else count > MAX_PER_SECOND * 60):
            raise OutboundError("el límite de envíos va de 1 por minuto a %d por segundo" % MAX_PER_SECOND)
        conf["rate"] = {"count": count, "per": per}
    if "quiet_hours" in data:
        hours = data["quiet_hours"]
        conf["quiet_hours"] = {"start": _hhmm(hours.get("start")), "end": _hhmm(hours.get("end"))} if isinstance(hours, dict) and hours else None
    if "conversion" in data:
        goal = data["conversion"] if isinstance(data["conversion"], dict) else {}
        conf["conversion"] = {k: goal[k] for k in ("classification", "intent", "flow", "csat") if goal.get(k) not in (None, "")} or None
    return name, channel, conf


def read_csv(text):
    """(columnas, filas) de un CSV con encabezado; separado por coma o punto y coma."""
    text = str(text or "").lstrip("﻿")
    first = text.split("\n", 1)[0]
    rows = [r for r in csv.reader(io.StringIO(text), delimiter=";" if first.count(";") > first.count(",") else ",") if any(c.strip() for c in r)]
    if not rows:
        raise OutboundError("el CSV está vacío: la primera fila tiene que ser el encabezado (to, nombre, …)")
    return [c.strip() for c in rows[0]], rows[1:]


def guess(columns, agent):
    slots = {s["name"].lower(): s["name"] for s in agent["slots"]}
    out = {}
    for c in columns:
        key = c.strip().lower()
        out[c] = "to" if key in TO_COLUMNS and "to" not in out.values() else slots.get(key, "")
    return out


def preview(agent, data):
    columns, rows = read_csv(data.get("csv"))
    return {"columns": columns, "rows": rows[:5], "count": len(rows), "mapping": guess(columns, agent)}


def add_recipients(agent, campaign, data):
    """Suma destinatarios (lista o CSV con mapping columna -> «to» | slot | ""). Sin repetidos ni bajas."""
    if data.get("csv") is not None:
        columns, rows = read_csv(data["csv"])
        mapping = data.get("mapping") if isinstance(data.get("mapping"), dict) else guess(columns, agent)
        items = [{mapping.get(c) or "": v.strip() for c, v in zip(columns, r)} for r in rows]
    elif isinstance(data.get("recipients"), list):
        items = [r if isinstance(r, dict) else {"to": r} for r in data["recipients"]]
    else:
        return {"added": 0, "duplicates": 0, "invalid": 0, "opted_out": 0}
    limit = int(((agent.get("outbound") or {}).get("max_recipients")) or __import__("os").environ.get("PARLA_CAMPAIGN_MAX") or MAX_RECIPIENTS)
    have = db.q("SELECT count(*) FROM campaign_recipients WHERE campaign_id = ?", (campaign["id"],))[0][0]
    names = {s["name"] for s in agent["slots"]}
    out = {"added": 0, "duplicates": 0, "invalid": 0, "opted_out": 0}
    rows = []
    for item in items:
        try:
            address = address_of(campaign["channel"], item.get("to"))
        except OutboundError:
            out["invalid"] += 1
            continue
        if opted_out(agent["id"], address):
            out["opted_out"] += 1
            continue
        rows.append((address, {k: v for k, v in item.items() if k in names and v not in (None, "")}))
    if have + len({a for a, _ in rows}) > limit:
        raise OutboundError("la campaña supera el máximo de %d destinatarios" % limit)
    for address, values in rows:
        if _enqueue(agent["id"], "campaign", campaign["channel"], address, {"data": values}, campaign["id"]):
            out["added"] += 1
        else:
            out["duplicates"] += 1
    if campaign["status"] == "canceled":
        db.q("UPDATE campaign_recipients SET status = 'canceled' WHERE campaign_id = ? AND status = 'queued'", (campaign["id"],))
    return out


def create(agent, data, user=None):
    name, channel, conf = settings(agent, data)
    cid = secrets.token_hex(6)
    db.q("INSERT INTO campaigns (id, agent_id, name, channel, status, config, created, updated, created_by) VALUES (?, ?, ?, ?, 'draft', ?, ?, ?, ?)",
         (cid, agent["id"], name, channel, json.dumps(conf, ensure_ascii=False), _now_text(), _now_text(), (user or {}).get("name")))
    try:
        imported = add_recipients(agent, _campaign(cid), data)
    except OutboundError:
        db.q("DELETE FROM campaigns WHERE id = ?", (cid,))
        raise
    return dict(public(_campaign(cid)), imported=imported)


ACTIONS = {"start": ("draft",), "pause": ("running",), "resume": ("paused",), "cancel": ("draft", "running", "paused")}


def act(agent, cid, action):
    campaign = _owned(agent, cid)
    if campaign["status"] not in ACTIONS[action]:
        raise OutboundError("la campaña no está en un estado que permita eso (está «%s»)" % campaign["status"], 409)
    if action == "start":
        if not db.q("SELECT 1 FROM campaign_recipients WHERE campaign_id = ? LIMIT 1", (cid,)):
            raise OutboundError("la campaña no tiene destinatarios")
        if not channels.config(agent, campaign["channel"]).get("enabled"):
            raise OutboundError("el canal «%s» está apagado: prendelo en Canales" % campaign["channel"])
    status = {"start": "running", "pause": "paused", "resume": "running", "cancel": "canceled"}[action]
    with _lock:
        db.q("UPDATE campaigns SET status = ?, updated = ? WHERE id = ?", (status, _now_text(), cid))
        if action == "cancel":
            db.q("UPDATE campaign_recipients SET status = 'canceled', updated = ? WHERE campaign_id = ? AND status = 'queued'", (_now_text(), cid))
    _wake.set()
    bus.publish("campaign:" + agent["id"], {"type": "campaign"})
    return public(_campaign(cid))


def recipients(agent, cid, query):
    _owned(agent, cid)
    where, args = "campaign_id = ?", [cid]
    if query.get("status"):
        where, args = where + " AND status = ?", args + [query["status"]]
    try:
        limit, offset = min(500, max(1, int(query.get("limit") or 50))), max(0, int(query.get("offset") or 0))
    except ValueError:
        raise OutboundError("«limit» y «offset» tienen que ser números") from None
    total = db.q("SELECT count(*) FROM campaign_recipients WHERE " + where, args)[0][0]
    rows = db.q("SELECT id, address, spec, status, error, attempts, updated, sent_at, session_id FROM campaign_recipients WHERE %s "
                "ORDER BY id LIMIT ? OFFSET ?" % where, args + [limit, offset])
    return {"total": total, "recipients": [{"id": r[0], "to": r[1], "data": json.loads(r[2]).get("data") or {}, "status": r[3], "error": r[4],
                                            "attempts": r[5], "updated": r[6], "sent_at": r[7], "sessionId": r[8]} for r in rows]}


def export(agent, cid):
    """Los resultados en CSV: destinatario, estado, error, intentos, fechas, conversación y los datos de cada uno."""
    campaign = _owned(agent, cid)
    rows = recipients(agent, cid, {"limit": 500})["recipients"]
    offset = 500
    while len(rows) < db.q("SELECT count(*) FROM campaign_recipients WHERE campaign_id = ?", (cid,))[0][0]:
        rows += recipients(agent, cid, {"limit": 500, "offset": offset})["recipients"]
        offset += 500
    keys = sorted({k for r in rows for k in r["data"]})
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(["to", "status", "error", "attempts", "sent_at", "updated", "sessionId"] + keys)
    for r in rows:
        writer.writerow([r["to"], r["status"], r["error"] or "", r["attempts"], r["sent_at"] or "", r["updated"], r["sessionId"] or ""]
                        + [r["data"].get(k, "") for k in keys])
    return out.getvalue().encode("utf-8-sig"), "campana-%s.csv" % re.sub(r"[^a-z0-9]+", "-", campaign["name"].lower()).strip("-")


def admin(method, agent, action, data, query, user=None):
    """Rutas /api/agents/{id}/campaigns… y /optouts. -> (status, cuerpo) o (status, bytes, tipo, nombre de archivo)."""
    parts = action.split("/")
    if parts == ["optouts"]:
        if method == "GET":
            return 200, {"optouts": optouts(agent["id"])}
        address = re.sub(r"[\s().+-]", "", str(data.get("address") or ""))
        if not re.fullmatch(r"-?[\w.@-]{1,100}", address):
            raise OutboundError("«address» tiene que ser el teléfono o el chat id")
        if method == "POST":
            opt_out(agent["id"], address, data.get("channel"), "a mano")
        elif method == "DELETE":
            db.q("DELETE FROM optouts WHERE agent_id = ? AND address = ?", (agent["id"], address))
        return 200, {"optouts": optouts(agent["id"])}
    if parts == ["campaigns"]:
        if method == "GET":
            rows = db.q("SELECT id FROM campaigns WHERE agent_id = ? ORDER BY created DESC", (agent["id"],))
            return 200, {"campaigns": [public(_campaign(r[0])) for r in rows]}
        if method == "POST":
            return 200, create(agent, data, user)
    if parts == ["campaigns", "preview"] and method == "POST":
        return 200, preview(agent, data)
    if len(parts) >= 2 and parts[0] == "campaigns":
        campaign, rest = _owned(agent, parts[1]), parts[2:]
        if not rest and method == "GET":
            return 200, public(campaign)
        if not rest and method == "PUT":
            if campaign["status"] not in ("draft", "paused"):
                raise OutboundError("solo se puede cambiar una campaña en borrador o pausada", 409)
            name, channel, conf = settings(agent, dict(data, channel=campaign["channel"]), campaign)
            db.q("UPDATE campaigns SET name = ?, config = ?, updated = ? WHERE id = ?", (name, json.dumps(conf, ensure_ascii=False), _now_text(), campaign["id"]))
            return 200, public(_campaign(campaign["id"]))
        if not rest and method == "DELETE":
            if campaign["status"] == "running":
                raise OutboundError("pausá o cancelá la campaña antes de borrarla", 409)
            with _lock:
                db.q("DELETE FROM campaign_recipients WHERE campaign_id = ?", (campaign["id"],))
                db.q("DELETE FROM campaigns WHERE id = ?", (campaign["id"],))
            return 200, {"deleted": campaign["id"]}
        if rest == ["recipients"] and method == "GET":
            return 200, recipients(agent, campaign["id"], query)
        if rest == ["recipients"] and method == "POST":
            if campaign["status"] in ("done", "canceled"):
                raise OutboundError("la campaña ya terminó: armá otra", 409)
            return 200, dict(public(_campaign(campaign["id"])), imported=add_recipients(agent, campaign, data))
        if rest == ["export"] and method == "GET":
            body, name = export(agent, campaign["id"])
            return 200, body, "text/csv; charset=utf-8", name
        if len(rest) == 1 and rest[0] in ACTIONS and method == "POST":
            return 200, act(agent, campaign["id"], rest[0])
    return 405, {"error": "método no permitido"}


def api_send(agent, data, now=None):
    """POST /api/v1/bots/{bot}/outbound. -> (status, cuerpo)."""
    now = now or clock()
    channel = data.get("channel") or "whatsapp"
    limit = int(((agent.get("outbound") or {}).get("api_per_minute")) or API_PER_MINUTE)
    with _lock:
        recent = _api.setdefault(agent["id"], deque())
        while recent and recent[0] <= now - 60:
            recent.popleft()
        if len(recent) >= limit:
            return 429, {"error": "demasiados envíos por minuto con la API (máximo %d): para muchos, armá una campaña" % limit}
        recent.append(now)
    if data.get("data") is not None and not isinstance(data.get("data"), dict):
        return 400, {"error": "«data» tiene que ser un objeto, por ejemplo {\"dni\": \"30123456\"}"}
    if data.get("flow") is not None and not isinstance(data.get("flow"), str):
        return 400, {"error": "«flow» tiene que ser el nombre de un flujo"}
    try:
        address = address_of(channel, data.get("to"))
    except OutboundError as error:
        return error.status, {"error": str(error)}
    spec = {"data": data.get("data") or {}, "flow": data.get("flow"), "template": data.get("template")}
    row = _enqueue(agent["id"], "api", channel, address, spec, status="sending")
    try:
        sent = send(agent, channel, address, spec["data"], spec["flow"], spec["template"], row=row, now=now)
    except OutboundError as error:
        _finish(row, agent["id"], channel, "opted_out" if isinstance(error, OptedOut) else "failed", str(error))
        return error.status, {"error": str(error)}
    except channels.ChannelError as error:
        message, _ = explain(channel, error)
        _finish(row, agent["id"], channel, "failed", message)
        _log(agent["id"], channel, "envío a %s: %s" % (mask(address), message))
        return 502, {"error": message}
    cats = pii.categories(_app().settings_of(agent["id"]).get("pii_redaction"))
    _finish(row, agent["id"], channel, "sent", None, sent, dict(spec, data=pii.scrub(spec["data"], cats)) if cats else None)
    return 200, dict(sent, id=row, channel=channel, to=address, status="sent")


ROW = "id, kind, channel, address, status, error, attempts, session_id, message_id, campaign_id, created, sent_at, updated"


def _row(r):
    return dict(zip(("id", "kind", "channel", "to", "status", "error", "attempts", "sessionId", "message_id", "campaign",
                     "created", "sent_at", "updated"), r))


def api_status(agent, rest, query):
    """GET /api/v1/bots/{bot}/outbound[/{id}]: el estado de un envío (el id que devolvió POST /outbound) o la lista,
    con ?to=&status=&from=&to_date=&kind=&limit=. -> (status, cuerpo)."""
    if rest:
        if not re.fullmatch(r"\d{1,18}", rest[0]):
            return 404, {"error": "no existe ese envío"}
        rows = db.q("SELECT %s FROM campaign_recipients WHERE agent_id = ? AND id = ?" % ROW, (agent["id"], int(rest[0])))
        return (200, _row(rows[0])) if rows else (404, {"error": "no existe ese envío"})
    where, args = ["agent_id = ?"], [agent["id"]]
    if query.get("to"):
        try:
            where, args = where + ["address = ?"], args + [address_of(query.get("channel") or "whatsapp", query["to"])]
        except OutboundError as error:
            return error.status, {"error": str(error)}
    for key, sql in (("status", "status = ?"), ("kind", "kind = ?"), ("channel", "channel = ?"), ("from", "created >= ?"), ("to_date", "created <= ?")):
        if query.get(key):
            value = str(query[key])
            where, args = where + [sql], args + [value + "T23:59:59" if key == "to_date" and len(value) == 10 else value]
    if query.get("status") and query["status"] not in STATUSES:
        return 400, {"error": "«status» tiene que ser uno de: %s" % ", ".join(STATUSES)}
    try:
        limit = min(500, max(1, int(query.get("limit") or 100)))
    except ValueError:
        return 400, {"error": "«limit» tiene que ser un número"}
    rows = db.q("SELECT %s FROM campaign_recipients WHERE %s ORDER BY id DESC LIMIT ?" % (ROW, " AND ".join(where)), args + [limit])
    return 200, {"outbound": [_row(r) for r in rows]}


def gauge_rows():
    """parla_campaign_recipients{status}: destinatarios de campañas por estado."""
    return [({"status": s}, n) for s, n in db.q("SELECT status, count(*) FROM campaign_recipients WHERE kind = 'campaign' GROUP BY status")]


def cleanup(days_of):
    """Retención: los destinatarios (con sus datos) de campañas terminadas hace más de los días del agente se borran;
    la campaña guarda sus números. También las filas viejas de envíos por API y recordatorios."""
    for (agent_id,) in db.q("SELECT DISTINCT agent_id FROM campaign_recipients"):
        days = days_of(agent_id)
        if not days:
            continue
        since = _now_text(clock() - days * 86400)
        for (cid,) in db.q("SELECT id FROM campaigns WHERE agent_id = ? AND status IN ('done', 'canceled') AND updated < ?", (agent_id, since)):
            campaign = _campaign(cid)
            if db.q("SELECT 1 FROM campaign_recipients WHERE campaign_id = ? LIMIT 1", (cid,)):
                conf = dict(campaign["config"], final_stats=stats(campaign))
                db.q("UPDATE campaigns SET config = ? WHERE id = ?", (json.dumps(conf, ensure_ascii=False), cid))
                db.q("DELETE FROM campaign_recipients WHERE campaign_id = ?", (cid,))
        db.q("DELETE FROM campaign_recipients WHERE agent_id = ? AND campaign_id IS NULL AND status != 'queued' AND updated < ?", (agent_id, since))
