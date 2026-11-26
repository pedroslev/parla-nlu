"""Derivación a contact centers externos y webhooks salientes. Solo biblioteca estándar.

Configuración (no secreta) en el JSON del agente; se lee del borrador (como pii_redaction): aplica sin publicar.
    "handoff": {"mode": "inbox" | "external" | "both", "timeout_minutes": 0, "on_timeout": "bot" | "close",
                "last_messages": 10, "target": "cola-ventas",
                "phone": {"headers": ["session", "intent", "language", "summary", "context_url"], "slots": ["dni"],   # nada = sin encabezados
                          "uui": false, "twilio_workflow_sid": "WW…"}}
    "webhooks": [{"url": "https://cc.example.com/parla", "events": ["handoff.requested", …], "secret_name": "CC_WEBHOOK"}]

- inbox (lo de siempre): la charla espera en la Bandeja. external: no aparece para tomar; la atiende el contact center
  por la API (accept / messages / release / close) y, si nadie la acepta en timeout_minutes, vuelve al bot o se cierra.
  both: las dos cosas.
- Webhooks: cada evento es una fila de webhook_deliveries (db.py), firmada con la clave secret_name de la bóveda
  (Parla-Signature: t=<unix>,v1=<HMAC-SHA256 hex de "t.cuerpo">). Un hilo los manda en orden por (webhook, conversación),
  reintenta con espera creciente (~24 h en total) y después los deja en «dead» (se reintentan a mano desde la interfaz).
  Entrega «al menos una vez»: el que recibe deduplica por «id».
"""
import hashlib
import hmac
import json
import re
import secrets
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

from . import auth, channels, cluster, costs, db, llm, outbound, pii, telemetry, vault

EVENTS = ("handoff.requested", "handoff.released", "conversation.started", "conversation.ended",
          "message.user", "message.bot", "csat.received", "campaign.finished")
MODES = ("inbox", "external", "both")
HEADERS = ("session", "intent", "language", "summary", "context_url")     # encabezados SIP que se pueden mandar
BACKOFF = 30                    # segundos antes del primer reintento; después el doble cada vez…
MAX_WAIT = 4 * 3600             # …hasta 4 h entre intentos
MAX_ATTEMPTS = 14               # 30 s, 1, 2, 4… min, 4 h, 4 h…: ~24 h en total; después «dead»
TIMEOUT = 10                    # segundos por entrega
SUMMARY_WAIT = 10               # segundos que el webhook handoff.requested espera el resumen de la IA (si no, va el fijo)
SIP_VALUE_MAX = 128             # caracteres por encabezado (ya codificado)
SIP_TOTAL_MAX = 1000            # Twilio: los encabezados del URI tienen que sumar menos de 1024
clock = time.time               # las pruebas lo cambian por un reloj propio
_lock = threading.Lock()        # ponytail: un solo hilo por réplica entrega todo (concurrencia 1 por webhook y en total): un webhook
_wake = threading.Event()       # lento (TIMEOUT) demora a los demás; un hilo por webhook si hay muchos


def _app():
    return auth._app()


def _now_text(now=None):
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(now or clock()))


# ---------- configuración ----------

def conf(agent):
    h = (agent or {}).get("handoff")
    h = h if isinstance(h, dict) else {}
    phone = h.get("phone") if isinstance(h.get("phone"), dict) else {}

    def number(key, default, low, high):
        try:
            return min(high, max(low, int(h.get(key, default))))
        except (TypeError, ValueError):
            return default
    return {"mode": h.get("mode") if h.get("mode") in MODES else "inbox", "timeout_minutes": number("timeout_minutes", 0, 0, 7 * 1440),
            "on_timeout": "close" if h.get("on_timeout") == "close" else "bot", "last_messages": number("last_messages", 10, 0, 50),
            "target": str(h.get("target") or "")[:100] or None,
            "phone": {"headers": [x for x in phone.get("headers") or [] if x in HEADERS],
                      "slots": [str(s) for s in phone.get("slots") or [] if isinstance(s, str)][:10], "uui": bool(phone.get("uui")),
                      "twilio_workflow_sid": str(phone.get("twilio_workflow_sid") or "").strip()}}


def webhooks(agent):
    """Los webhooks válidos del agente: [{url, events, secret_name}]."""
    out = []
    for w in (agent or {}).get("webhooks") or []:
        if isinstance(w, dict) and re.fullmatch(r"https?://[^\s/?#]+[^\s]*", str(w.get("url") or "")):
            out.append({"url": w["url"], "events": [e for e in w.get("events") or [] if e in EVENTS],
                        "secret_name": vault._normal(str(w.get("secret_name") or "")) if w.get("secret_name") else ""})
    return out


# ---------- contexto: lo que ve el contact center (webhook, lookup, encabezados SIP) ----------

def customer(record):
    """(canal, dirección) de quien chatea: el teléfono de WhatsApp o de la llamada, el chat de Telegram o el sessionId."""
    found = outbound.address_from_session(record["sessionId"])
    if found:
        return found
    if record.get("channel") == "phone":
        return "phone", record.get("caller")
    return record.get("channel"), record["sessionId"]


def intent_of(record):
    return next((m.get("intent") for m in reversed(record.get("history") or []) if m["from"] == "user" and m.get("intent")), None)


def links(agent, sid=None):
    base = "%s/api/v1/bots/%s" % (channels.public_url(agent), agent["id"])
    if sid is None:
        return {"bot": base}
    s = base + "/sessions/" + urllib.parse.quote(sid, safe="")
    return {"session": s, "messages": s + "/messages", "handoff": s + "/handoff", "lookup": base + "/lookup?sid=" + urllib.parse.quote(sid, safe="")}


def context(agent, record):
    """La conversación para el contact center. Con pii_redaction: dirección, slots y mensajes van tapados."""
    cats = pii.categories(agent.get("pii_redaction"))
    cover = (lambda v: pii.scrub(v, cats)) if cats else (lambda v: v)
    state, hand = record.get("state") or {}, record.get("handoff") or {}
    channel, address = customer(record)
    n = conf(agent)["last_messages"]
    said = [m for m in record.get("history") or [] if m["from"] in ("user", "bot", "human")][-n:] if n else []
    return {"agent": {"id": agent["id"], "name": agent.get("name")}, "sessionId": record["sessionId"], "channel": record.get("channel"),
            "customer": {"channel": channel, "address": outbound.mask(address) if cats and address else address},
            "language": state.get("lang") or (agent.get("languages") or ["es"])[0], "intent": intent_of(record), "flow": state.get("flow"),
            "slots": cover({k: v for k, v in (state.get("slots") or {}).items() if v is not None}),
            "handoff": {k: hand.get(k) for k in ("active", "mode", "reason", "since", "by", "summary", "target")} if hand else None,
            "ended": bool(record.get("ended")),
            **({"experiment": record["experiment"], "variant": record.get("variant")} if record.get("experiment") else {}),
            "messages": [dict({"from": m["from"], "text": cover(m.get("text")), "at": m.get("at")}, **({"by": m["by"]} if m.get("by") else {}))
                         for m in said],
            "links": links(agent, record["sessionId"])}


LABELS = {"es": ("Motivo", "Intención", "Datos"), "en": ("Reason", "Intent", "Data"), "pt": ("Motivo", "Intenção", "Dados")}


def plain_summary(agent, record, reason=None):
    """El resumen fijo, al instante: motivo + intención + slots (tapados con pii_redaction)."""
    cats = pii.categories(agent.get("pii_redaction"))
    cover = (lambda v: pii.scrub(v, cats)) if cats else (lambda v: v)
    state = record.get("state") or {}
    words = LABELS.get(state.get("lang"), LABELS["es"])
    slots = cover({k: v for k, v in (state.get("slots") or {}).items() if v not in (None, "")})
    return "; ".join(filter(None, ["%s: %s" % (words[0], reason) if reason else None,
                                   "%s: %s" % (words[1], intent_of(record)) if intent_of(record) else None,
                                   "%s: %s" % (words[2], ", ".join("%s=%s" % kv for kv in slots.items())) if slots else None]))[:300]


def summary(agent, record, reason=None):
    """Una o dos líneas para quien atiende: con la IA del agente si está prendida; si no (o si falla), el fijo.
    Tarda lo que tarde el modelo (hasta 8 s): started() la corre en segundo plano, nunca en el turno."""
    cats = pii.categories(agent.get("pii_redaction"))
    cover = (lambda v: pii.scrub(v, cats)) if cats else (lambda v: v)
    plain = plain_summary(agent, record, reason)
    if not ((agent.get("ai") or {}).get("enabled")):
        return plain
    talk = "\n".join("%s: %s" % (m["from"], cover(m.get("text") or "")) for m in (record.get("history") or [])[-20:] if m["from"] in ("user", "bot"))
    try:
        text = llm.chat(llm.settings(agent), [
            {"role": "system", "content": "Resumí en una o dos líneas, en el idioma de la conversación, qué necesita la persona y qué datos ya dio, "
                                          "para el agente humano que la va a atender. Solo el resumen."},
            {"role": "user", "content": talk + ("\n\n(%s)" % plain if plain else "")}], max_tokens=120, timeout=8)
        return " ".join(str(text or "").split())[:300] or plain[:300]
    except Exception:  # noqa: BLE001 - sin IA o caída: el resumen fijo alcanza
        return plain[:300]


def started(agent, record):
    """La charla acaba de pasar a una persona: completa el handoff (modo, destino, resumen fijo) y avisa a los
    webhooks. Con IA, el resumen de la IA se hace en segundo plano (el turno contesta ya): el webhook
    handoff.requested espera hasta SUMMARY_WAIT segundos para llevarlo; si no llega, sale con el fijo. La
    transferencia telefónica (encabezados SIP, Flex) usa el fijo, sin esperar."""
    c, hand = conf(agent), record["state"].get("handoff") or {}
    plain = plain_summary(agent, record, hand.get("reason"))
    hand.update(mode=c["mode"], target=c["target"], summary=plain)
    record["handoff"] = hand
    ai = bool((agent.get("ai") or {}).get("enabled"))
    event_id = "evt_" + secrets.token_hex(12)
    emit(agent, "handoff.requested", record, _event_id=event_id, _hold=SUMMARY_WAIT if ai else 0)
    if ai:
        snapshot = json.loads(json.dumps(record))
        threading.Thread(target=_ai_summary, args=(agent, snapshot, plain, event_id), daemon=True, name="parla-summary").start()


def _ai_summary(agent, record, plain, event_id):
    """En segundo plano: el resumen de la IA va al webhook que lo espera y a la conversación guardada."""
    text = plain
    try:
        with costs.scope(agent["id"], record["sessionId"], record.get("channel")):
            text = summary(agent, record, (record.get("handoff") or {}).get("reason"))
        for rid, raw in db.q("SELECT id, body FROM webhook_deliveries WHERE event_id = ? AND status = 'queued'", (event_id,)):
            body = json.loads(raw)
            if text != plain and isinstance(body.get("handoff"), dict):
                body["handoff"]["summary"] = text
            db.q("UPDATE webhook_deliveries SET body = ?, next_at = 0 WHERE id = ? AND status = 'queued'",
                 (json.dumps(body, ensure_ascii=False, separators=(",", ":")), rid))
        _wake.set()
        app = _app()
        # ponytail: el turno guarda la conversación justo después de started(); se reintenta un poco hasta verla.
        # Un turno que guarda en el mismo instante puede pisar el resumen (queda el fijo); un lock por conversación si molesta
        for _ in range(10) if text != plain else ():
            saved = app.load_session(agent["id"], record["sessionId"])
            hand = (saved or {}).get("handoff") or {}
            if hand.get("summary") == plain and hand.get("active"):
                for where in (hand, (saved.get("state") or {}).get("handoff") or {}):
                    where["summary"] = text
                app.save_session(agent["id"], saved)
                return
            time.sleep(0.2)
    except Exception:  # noqa: BLE001 - el webhook sale igual con el fijo cuando vence la espera
        import traceback
        traceback.print_exc(file=sys.stderr)


# ---------- encabezados SIP para transferir la llamada con contexto ----------

def _ascii(text):
    return re.sub(r"[^\x20-\x7e]", "", " ".join(str(text or "").split()))


def sip_headers(agent, record):
    """{nombre: valor} para la transferencia: X-Parla-* (y User-to-User si se pidió). Cada valor recortado a
    SIP_VALUE_MAX y el total a SIP_TOTAL_MAX ya codificado. Nunca claves ni nada de la bóveda: solo lo elegido."""
    c = conf(agent)["phone"]
    ctx = context(agent, record)
    values = {"session": ("X-Parla-Session", record["sessionId"]), "intent": ("X-Parla-Intent", ctx["intent"]),
              "language": ("X-Parla-Language", ctx["language"]), "summary": ("X-Parla-Summary", (record.get("handoff") or {}).get("summary")),
              "context_url": ("X-Parla-Context", ctx["links"]["lookup"])}
    out, total = {}, 0
    pairs = [values[k] for k in c["headers"]] + [("X-Parla-Slot-" + re.sub(r"[^A-Za-z0-9-]", "-", s)[:30], ctx["slots"].get(s)) for s in c["slots"]]
    if c["uui"]:     # User-to-User: el sessionId en hex (RFC 7433), lo que la mayoría de las centrales sabe leer
        pairs.append(("User-to-User", record["sessionId"].encode().hex() + ";encoding=hex"))
    vault_values = set(vault.values(agent["id"]).values())
    for name, value in pairs:
        value = _ascii(value)
        if not value or value in vault_values:
            continue
        while value and len(urllib.parse.quote(value, safe="")) > SIP_VALUE_MAX:
            value = value[:-1]
        size = len(name) + 2 + len(urllib.parse.quote(value, safe=""))
        if total + size > SIP_TOTAL_MAX:
            break
        out[name], total = value, total + size
    return out


def sip_uri(uri, headers):
    """sip:mesa@pbx?X-Parla-Session=…&… (lo que entiende el <Sip> de Twilio)."""
    if not headers:
        return uri
    return uri + ("&" if "?" in uri else "?") + "&".join("%s=%s" % (k, urllib.parse.quote(v, safe="")) for k, v in headers.items())


def task_attributes(agent, record):
    """Los atributos de la tarea de TaskRouter (Twilio Flex): el contexto sin los mensajes ni los links largos."""
    ctx = context(agent, record)
    return {"parla_session": record["sessionId"], "parla_agent": agent["id"], "intent": ctx["intent"], "language": ctx["language"],
            "summary": (record.get("handoff") or {}).get("summary"), "slots": ctx["slots"], "context_url": ctx["links"]["lookup"],
            "customer": ctx["customer"]["address"]}


# ---------- webhooks: encolar ----------

def emit(agent, event, record=None, _event_id=None, _hold=0, **extra):
    """Encola el evento para cada webhook del agente que lo pidió. agent: el borrador (o lo que tenga «webhooks»).
    _hold: segundos antes de entregarlo (handoff.requested espera el resumen de la IA)."""
    hooks = [w for w in webhooks(agent) if event in w["events"]]
    if not hooks:
        return 0
    body = {"id": _event_id or "evt_" + secrets.token_hex(12), "type": event, "created": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(clock()))}
    body.update(context(agent, record) if record is not None else {"agent": {"id": agent["id"], "name": agent.get("name")}, "links": links(agent)})
    cats = pii.categories(agent.get("pii_redaction"))
    body.update(pii.scrub(extra, cats) if cats else extra)
    raw = json.dumps(body, ensure_ascii=False, separators=(",", ":"))
    for w in hooks:
        enqueue(agent["id"], w["url"], event, body["id"], record["sessionId"] if record is not None else None, raw,
                clock() + _hold if _hold else 0)
    return len(hooks)


def emit_by_id(agent_id, event, record=None, **extra):
    """emit() desde donde solo se tiene el id (lee el borrador). Nunca rompe lo que lo llamó."""
    try:
        agent = _app().settings_of(agent_id)
        if agent and webhooks(agent):
            emit(agent, event, record, **extra)
    except Exception:  # noqa: BLE001 - un webhook mal configurado no puede cortar una conversación
        import traceback
        traceback.print_exc(file=sys.stderr)


def enqueue(agent_id, url, event, event_id, session_id, raw, next_at=0):
    db.q("INSERT INTO webhook_deliveries (agent_id, url, event, event_id, session_id, body, status, next_at, created, updated) "
         "VALUES (?, ?, ?, ?, ?, ?, 'queued', ?, ?, ?)", (agent_id, url, event, event_id, session_id, raw, next_at, _now_text(), _now_text()))
    _wake.set()


# ---------- webhooks: entregar ----------

def sign(secret, raw, ts):
    return "t=%d,v1=%s" % (ts, hmac.new(secret.encode(), b"%d." % ts + raw.encode(), hashlib.sha256).hexdigest())


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):     # un 3xx cuenta como falla: no seguimos a otra dirección
        return None


_opener = urllib.request.build_opener(_NoRedirect)


def deliver(row, now=None, claimed=False):
    """Manda una fila y la deja como quedó: delivered, queued (reintento) o dead. claimed: ya la reservó _claim."""
    now = now or clock()
    rid, agent_id, url, event, raw, attempts = row
    claimed or db.q("UPDATE webhook_deliveries SET status = 'sending', attempts = attempts + 1, updated = ? WHERE id = ?", (_now_text(now), rid))
    hook = next((w for w in webhooks(_app().settings_of(agent_id)) if w["url"] == url), None)
    code, error, started_at = None, None, time.monotonic()
    secret = vault.values(agent_id).get(hook["secret_name"]) if hook and hook["secret_name"] else None
    if not hook:
        error = "ese webhook ya no está configurado"
    elif not secret:
        error = "falta la clave %s en Claves" % (hook["secret_name"] or "(secret_name)")
    else:
        headers = {"Content-Type": "application/json", "User-Agent": "Parla-Webhooks/1", "Parla-Event": event,
                   "Parla-Delivery": str(rid), "Parla-Signature": sign(secret, raw, int(clock()))}
        try:
            with _opener.open(urllib.request.Request(url, data=raw.encode(), headers=headers, method="POST"), timeout=TIMEOUT) as r:
                code = r.status
                r.read(10_000)
        except urllib.error.HTTPError as e:
            code, error = e.code, "HTTP %d" % e.code
        except (OSError, ValueError) as e:      # sin red, DNS, timeout, URL rara
            code, error = 0, "sin respuesta: %s" % getattr(e, "reason", e)
    latency = time.monotonic() - started_at
    if code and 200 <= code < 300:
        status, error, next_at = "delivered", None, 0
    elif not hook or attempts + 1 >= MAX_ATTEMPTS:
        status, next_at = "dead", 0
    else:
        status, next_at = "queued", now + min(MAX_WAIT, BACKOFF * 2 ** attempts)
    db.q("UPDATE webhook_deliveries SET status = ?, code = ?, error = ?, latency_ms = ?, next_at = ?, updated = ? WHERE id = ?",
         (status, code, vault.mask(str(error), agent_id)[:300] if error else None, int(latency * 1000), next_at, _now_text(now), rid))
    telemetry.count("parla_webhook_deliveries_total", outcome={"queued": "retry"}.get(status, status))
    if code is not None:
        telemetry.observe("parla_webhook_delivery_duration_seconds", latency)
    return status


def _due(now, limit=50):
    """Lo que vence, sin pasar delante de un evento anterior de la misma conversación al mismo webhook."""
    return db.q("SELECT id, agent_id, url, event, body, attempts FROM webhook_deliveries d WHERE status = 'queued' AND next_at <= ? "
                "AND NOT EXISTS (SELECT 1 FROM webhook_deliveries e WHERE e.agent_id = d.agent_id AND e.url = d.url "
                "AND e.session_id IS d.session_id AND e.status IN ('queued', 'sending') AND e.id < d.id) ORDER BY id LIMIT ?", (now, limit))


def _claim(now, limit=50):
    """Con Postgres: como _due, pero reserva las filas («sending») con FOR UPDATE SKIP LOCKED: cada entrega la hace
    una sola réplica, y el NOT EXISTS sigue cuidando el orden por conversación (la anterior está «queued» o «sending»)."""
    rows = db.q("UPDATE webhook_deliveries SET status = 'sending', attempts = attempts + 1, updated = ? WHERE id IN ("
                "SELECT id FROM webhook_deliveries d WHERE status = 'queued' AND next_at <= ? "
                "AND NOT EXISTS (SELECT 1 FROM webhook_deliveries e WHERE e.agent_id = d.agent_id AND e.url = d.url "
                "AND e.session_id IS d.session_id AND e.status IN ('queued', 'sending') AND e.id < d.id) ORDER BY id LIMIT ? "
                "FOR UPDATE SKIP LOCKED) RETURNING id, agent_id, url, event, body, attempts - 1", (_now_text(now), now, limit))
    return sorted(rows, key=lambda r: r[0])


def tick(now=None):
    now = now or clock()
    with _lock:
        rows = _claim(now) if db.PG else _due(now)
        for row in rows:
            deliver(row, now, claimed=db.PG)
        return len(rows)


def depth():
    """Para el gauge parla_queue_depth{queue="webhooks"}: entregas pendientes (en cola o saliendo)."""
    return db.q("SELECT count(*) FROM webhook_deliveries WHERE status IN ('queued', 'sending')")[0][0]


def deliveries(agent_id, limit=50):
    rows = db.q("SELECT id, url, event, event_id, session_id, status, attempts, code, error, latency_ms, next_at, created, updated "
                "FROM webhook_deliveries WHERE agent_id = ? ORDER BY id DESC LIMIT ?", (agent_id, limit))
    keys = ("id", "url", "event", "event_id", "sessionId", "status", "attempts", "code", "error", "latency_ms", "next_at", "created", "updated")
    return [dict(zip(keys, r)) for r in rows]


def retry(agent_id, rid):
    """«Reintentar»: vuelve a la cola ya, con los intentos en cero. False si no existe o ya salió bien."""
    found = db.q("SELECT status FROM webhook_deliveries WHERE id = ? AND agent_id = ?", (rid, agent_id))
    if not found or found[0][0] in ("delivered", "sending"):
        return False
    db.q("UPDATE webhook_deliveries SET status = 'queued', attempts = 0, next_at = 0, updated = ? WHERE id = ?", (_now_text(), rid))
    _wake.set()
    return True


def test(agent, url):
    """«Enviar evento de prueba»: un evento «test» a ese webhook (sin mirar sus eventos), entregado ya. -> la fila."""
    hook = next((w for w in webhooks(agent) if w["url"] == url), None)
    if not hook:
        raise ValueError("ese webhook no está guardado en el agente")
    body = {"id": "evt_" + secrets.token_hex(12), "type": "test", "created": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(clock())),
            "agent": {"id": agent["id"], "name": agent.get("name")}, "links": links(agent)}
    raw = json.dumps(body, ensure_ascii=False, separators=(",", ":"))
    with db.connect() as conn:
        rid = conn.execute("INSERT INTO webhook_deliveries (agent_id, url, event, event_id, session_id, body, status, created, updated) "
                           "VALUES (?, ?, 'test', ?, NULL, ?, 'queued', ?, ?)", (agent["id"], url, body["id"], raw, _now_text(), _now_text())).lastrowid
    with _lock:
        deliver((rid, agent["id"], url, "test", raw, 0))
    return next(d for d in deliveries(agent["id"], 20) if d["id"] == rid)


# ---------- tiempo máximo del handoff externo ----------

def expire(now=None):
    """Handoffs external/both que nadie aceptó en timeout_minutes: vuelven al bot o se cierran (on_timeout)."""
    now, app, done = now or clock(), _app(), 0
    for agent_id, sid, raw in db.q("SELECT agent_id, session_id, record FROM sessions WHERE handoff = 1"):
        hand = json.loads(raw).get("handoff") or {}
        c = conf(app.settings_of(agent_id))
        if hand.get("mode") not in ("external", "both") or hand.get("by") or not c["timeout_minutes"] or not hand.get("since"):
            continue
        if time.mktime(time.strptime(hand["since"], "%Y-%m-%dT%H:%M:%S")) + c["timeout_minutes"] * 60 <= now:
            app.human(agent_id, sid, "close" if c["on_timeout"] == "close" else "release", "", "tiempo máximo",
                      resolution="timeout" if c["on_timeout"] == "close" else None)
            done += 1
    return done


STALE = 300         # con Postgres: «sending» hace más de 5 minutos (TIMEOUT es 10 s) = la réplica que entregaba se murió


def recover(stale=0):
    """Al arrancar: lo que quedó «sending» no se sabe si llegó; se manda de nuevo (el que recibe deduplica por id).
    Con Postgres lo hace la líder cada minuto, solo con lo trabado hace más de STALE."""
    db.q("UPDATE webhook_deliveries SET status = 'queued', updated = ? WHERE status = 'sending'" + (" AND updated <= ?" if stale else ""),
         (_now_text(),) + ((_now_text(clock() - stale),) if stale else ()))


def cleanup(days=30):
    db.q("DELETE FROM webhook_deliveries WHERE status IN ('delivered', 'dead') AND updated < ?",
         (time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(clock() - days * 86400)),))


def _loop():
    last = 0
    while True:
        try:
            tick()
            if clock() - last >= 30 and cluster.is_leader():        # con varias réplicas, solo la líder
                last = clock()
                expire()
                if db.PG:
                    recover(STALE)
        except Exception:  # noqa: BLE001 - que la cola no se muera por una fila rara
            import traceback
            traceback.print_exc(file=sys.stderr)
        _wake.wait(5)
        _wake.clear()


def start():
    if not db.PG:
        recover()
    threading.Thread(target=_loop, daemon=True, name="parla-webhooks").start()
