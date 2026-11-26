"""Costos por conversación: lo que se usó (tokens, minutos de audio, caracteres, minutos de teléfono, mensajes) y
cuánto sale con la tabla de precios de esta instalación. Solo biblioteca estándar.

Uso: record(kind, provider, model, qty) desde llm.py, voice.py, phone.py, channels.py y outbound.py. Dentro de un
turno (scope) se junta en memoria y se escribe al salir, sin esperar el COMMIT (db.later): la contabilidad nunca
frena una respuesta. Se guarda el uso crudo (tabla usage, por día y conversación) y el costo se calcula al leer con
los precios de ahora: cambiar un precio cambia también lo pasado ("estimado con los precios actuales").

Precios: DATA/prices.json (lo que editó el dueño) sobre DEFAULTS (solo los verificados, con su fuente y fecha)."""
import contextlib
import fnmatch
import json
import os
import statistics
import threading
import time

from . import DATA, db, telemetry

# kind -> (unidad guardada, cuántas unidades cubre el precio, cómo se lee el precio, grupo del reporte)
KINDS = {
    "llm_input": ("tokens", 1_000_000, "1M tokens", "llm"), "llm_output": ("tokens", 1_000_000, "1M tokens", "llm"),
    "llm_cached": ("tokens", 1_000_000, "1M tokens", "llm"), "llm_compute": ("hours", 1, "CPU hour", "llm"),
    "asr": ("minutes", 1, "minute", "asr"), "tts": ("chars", 1_000_000, "1M characters", "tts"),
    "phone": ("minutes", 1, "minute", "phone"), "phone_call": ("calls", 1, "call", "phone"),
    "whatsapp": ("messages", 1, "message", "messaging"), "telegram": ("messages", 1, "message", "messaging"),
    "turn": ("turns", None, "month (infra)", "engine"),     # el costo fijo del mes se reparte entre los turnos del mes
}
CHECKED = "2026-11-26"
ANTHROPIC = "https://platform.claude.com/docs/en/about-claude/pricing"
OPENAI = "https://developers.openai.com/api/docs/pricing"
GEMINI = "https://aistudio.google.com/docs/pricing"
DEEPGRAM = "https://deepgram.com/pricing"
ELEVEN = "https://elevenlabs.io/pricing/api"
TWILIO = "https://www.twilio.com/en-us/voice/pricing/us"
META = "https://developers.facebook.com/docs/whatsapp/pricing"


def _p(kind, provider, model, price, source=None, note=None):
    return {"kind": kind, "provider": provider, "model": model, "price": price, "source": source,
            "checked": CHECKED if source else None, **({"note": note} if note else {})}


def _llm(provider, model, inp, cached, out, source, note=None):
    return [_p("llm_input", provider, model, inp, source, note), _p("llm_cached", provider, model, cached, source if cached is not None else None, note),
            _p("llm_output", provider, model, out, source, note)]


DEFAULTS = (
    _llm("anthropic", "claude-opus-5-5", 4.0, 0.20, 20.0, ANTHROPIC) + _llm("anthropic", "claude-sonnet-5-5", 2.0, 0.10, 10.0, ANTHROPIC)
    + _llm("anthropic", "claude-haiku-5-5", 0.10, None, 0.50, ANTHROPIC, "prompts ≤100K tokens; $0.50/$2.50 beyond")
    + _llm("openai", "gpt-6-luna", 0.10, 0.01, 0.50, OPENAI) + _llm("openai", "gpt-6.1-terra", 1.00, 0.05, 5.00, OPENAI)
    + _llm("openai", "gpt-6.2-sol", 2.00, 0.10, 10.00, OPENAI)
    + _llm("gemini", "gemini-3.8-flash", 0.75, 0.075, 3.75, GEMINI, "until 2026-12-31; $1.50 / $0.15 / $7.50 from 2027-01-01")
    + _llm("gemini", "gemini-3.5-flash-lite", 0.30, 0.03, 2.50, GEMINI)
    + _llm("gemini", "gemini-3.1-pro-preview", 2.00, 0.20, 12.00, GEMINI, "prompts ≤200K tokens; $4 / $0.40 / $18 beyond")
    + _llm("ollama", "*", 0, 0, 0, "local", "runs on your hardware: see llm_compute")
    + [_p("llm_compute", "ollama", "*", None, None, "your infra cost per CPU-hour"),
       _p("asr", "local", "*", 0, "local", "faster-whisper on this computer"), _p("tts", "local", "*", 0, "local", "Piper on this computer"),
       _p("asr", "openai", "gpt-4o-mini-transcribe", 0.003, OPENAI),
       _p("asr", "deepgram", "nova-3", 0.0043, DEEPGRAM, "monolingual; multilingual $0.0052"),
       _p("asr", "elevenlabs", "scribe_v3", round(0.20 / 60, 6), ELEVEN, "$0.20 per hour"), _p("asr", "google", "*", None),
       _p("tts", "openai", "*", None, None, "priced per audio token, not per character"),
       _p("tts", "deepgram", "aura-2-*", 30.0, DEEPGRAM, "$0.030 per 1K characters"),
       _p("tts", "elevenlabs", "eleven_flash_v2_5", 40.0, ELEVEN, "$0.04 per 1K characters"),
       _p("tts", "elevenlabs", "eleven_turbo_v2_5", 40.0, ELEVEN, "$0.04 per 1K characters"),
       _p("tts", "elevenlabs", "eleven_multilingual_v2", 80.0, ELEVEN, "$0.08 per 1K characters"), _p("tts", "google", "*", None),
       _p("phone", "twilio", "inbound", 0.0085, TWILIO, "US local number; other countries differ"),
       _p("phone", "twilio", "outbound", 0.014, TWILIO, "US local; other countries differ"),
       _p("phone", "jambonz", "*", None, None, "your carrier's per-minute rate"),
       _p("whatsapp", "meta", "service", None, META, "per message, by country; 1,000 free service messages per number per month"),
       _p("whatsapp", "meta", "template:*", None, META, "per delivered template, by country and category"),
       _p("telegram", "telegram", "*", 0, "https://core.telegram.org/bots/faq", "the Bot API is free"),
       _p("turn", "parla", "*", None, None, "your Parla server cost per month, spread over the month's turns")]
)
_local = threading.local()
_cache = {"mtime": None, "table": None}


def _path():
    return os.path.join(DATA, "prices.json")


# ---------- medir ----------

class _Scope:
    def __init__(self, agent, session, channel):
        self.agent, self.session, self.channel, self.items, self.taken = agent, session or "", channel or "", [], 0

    def take(self):
        """Lo medido desde la última vez (para el turno y el registro de la conversación)."""
        new, self.taken = self.items[self.taken:], len(self.items)
        return new


@contextlib.contextmanager
def scope(agent, session=None, channel=None):
    """Lo que se mida adentro es de esta conversación. Anidado (audio -> turno) es el mismo: completa sesión y canal."""
    outer = getattr(_local, "scope", None)
    if outer is not None and outer.agent == agent:
        outer.session, outer.channel = session or outer.session, channel or outer.channel
        yield outer
        return
    _local.scope = current = _Scope(agent, session, channel)
    try:
        yield current
    finally:
        _local.scope = outer
        for item in current.items:
            _write(current.agent, current.session, current.channel, *item)


def record(kind, provider, model, qty, agent=None, session=None, channel=None):
    """Uso medido. Sin agent: el del scope actual (si no hay, solo cuenta en las métricas). Nunca lanza."""
    try:
        qty = float(qty or 0)
        if kind not in KINDS or qty <= 0:
            return
        provider, model = str(provider or "other")[:40], str(model or "")[:80]
        current = getattr(_local, "scope", None)
        who = agent or (current.agent if current else "")
        telemetry.count("parla_usage_total", qty, agent=who or "none", kind=kind, provider=provider, unit=KINDS[kind][0])
        cost = cost_of(table(), kind, provider, model, qty)
        if cost:
            telemetry.count("parla_cost_total", cost, agent=who or "none", kind=kind, provider=provider, currency=table()["currency"])
        if agent:
            _write(agent, session or "", channel or "", kind, provider, model, qty)
        elif current:
            current.items.append((kind, provider, model, qty))
    except Exception:  # noqa: BLE001 - la contabilidad no puede romper una conversación
        pass


def _write(agent, session, channel, kind, provider, model, qty):
    db.later("INSERT INTO usage (agent_id, session_id, day, channel, provider, model, kind, qty) VALUES (?, ?, ?, ?, ?, ?, ?, ?) "
             "ON CONFLICT (agent_id, day, session_id, channel, provider, model, kind) DO UPDATE SET qty = qty + excluded.qty",
             (agent, session, time.strftime("%Y-%m-%d"), channel, provider, model, kind, qty))


def llm(provider, model, inp=None, out=None, cached=None, seconds=None):
    """Lo que informó el proveedor del modelo en una llamada (inp sin los tokens leídos de caché)."""
    for kind, n in (("llm_input", inp), ("llm_output", out), ("llm_cached", cached)):
        if isinstance(n, (int, float)) and n > 0:
            record(kind, provider, model, n)
    if seconds:
        record("llm_compute", provider, model, seconds / 3600)


def totals(items):
    """[(kind, provider, model, qty)] -> {"kind|provider|model": qty} (lo que va en record["usage"])."""
    out = {}
    for kind, provider, model, qty in items:
        key = "%s|%s|%s" % (kind, provider, model)
        out[key] = round(out.get(key, 0) + qty, 6)
    return out


def merge(into, items):
    for key, qty in totals(items).items():
        into[key] = round(into.get(key, 0) + qty, 6)
    return into


def forget(agent_id, before=None, session=None):
    """Privacidad (retención, borrar una conversación): el detalle por conversación pasa a la fila sin conversación
    del mismo día; los totales y los reportes por día siguen."""
    where, args = "agent_id = ? AND session_id != ''", [agent_id]
    if before:
        where, args = where + " AND day < ?", args + [before[:10]]
    if session:
        where, args = where + " AND session_id = ?", args + [session]
    with db.connect() as conn:
        conn.execute("INSERT INTO usage (agent_id, session_id, day, channel, provider, model, kind, qty) "
                     "SELECT agent_id, '', day, channel, provider, model, kind, sum(qty) FROM usage WHERE %s "
                     "GROUP BY agent_id, day, channel, provider, model, kind ON CONFLICT (agent_id, day, session_id, channel, provider, model, kind) "
                     "DO UPDATE SET qty = qty + excluded.qty" % where, args)
        conn.execute("DELETE FROM usage WHERE " + where, args)


# ---------- precios ----------

def _key(row):
    return (row["kind"], row["provider"], row["model"])


def table():
    """{"currency", "prices": [...], con lo del dueño encima de DEFAULTS}. Releída si cambió el archivo."""
    try:
        mtime = os.path.getmtime(_path())
    except OSError:
        mtime = None
    if _cache["table"] is None or _cache["mtime"] != mtime:
        saved = {}
        if mtime is not None:
            try:
                with open(_path(), encoding="utf-8") as f:
                    saved = json.load(f)
            except (OSError, ValueError):
                saved = {}
        own = [dict(r, default=False) for r in saved.get("prices") or []]
        keys = {_key(r) for r in own}
        rows = own + [dict(r, default=True) for r in DEFAULTS if _key(r) not in keys]
        for r in rows:
            r["unit"] = KINDS[r["kind"]][2]
        _cache.update(mtime=mtime, table={"currency": saved.get("currency") or "USD", "prices": rows})
    return _cache["table"]


def save(data):
    """El dueño guarda la tabla: {"currency", "prices": [{kind, provider, model, price, source?, checked?, note?}]}."""
    if not isinstance(data, dict) or not isinstance(data.get("prices"), list):
        raise ValueError("mandá {\"currency\": \"USD\", \"prices\": [...]}")
    currency = str(data.get("currency") or "USD").strip().upper()
    if not (len(currency) == 3 and currency.isalpha()):
        raise ValueError("«currency» tiene que ser un código de 3 letras (USD, EUR, ARS…)")
    rows = []
    for r in data["prices"]:
        if not isinstance(r, dict) or r.get("kind") not in KINDS or not str(r.get("provider") or "").strip():
            raise ValueError("cada precio necesita «kind» (%s) y «provider»" % ", ".join(KINDS))
        price = r.get("price")
        if price not in (None, "") and (isinstance(price, bool) or not isinstance(price, (int, float)) or price < 0):
            raise ValueError("«price» tiene que ser un número ≥ 0 o vacío")
        rows.append({"kind": r["kind"], "provider": str(r["provider"]).strip()[:40], "model": str(r.get("model") or "*").strip()[:80] or "*",
                     "price": None if price in (None, "") else float(price),
                     **{k: str(r[k])[:300] for k in ("source", "checked", "note") if r.get(k)}})
    os.makedirs(DATA, exist_ok=True)
    tmp = _path() + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump({"currency": currency, "prices": rows}, f, ensure_ascii=False, indent=1)
    os.replace(tmp, _path())
    _cache["table"] = None
    return table()


def price_of(prices, kind, provider, model):
    """El precio que aplica (el modelo exacto primero, después el patrón más largo: «aura-2-*», «*»), o None."""
    best = None
    for r in prices["prices"]:
        if r["kind"] == kind and r["provider"] == provider and fnmatch.fnmatchcase(model or "", r["model"] or "*"):
            if best is None or len(r["model"]) > len(best["model"]):
                best = r
    return best


def cost_of(prices, kind, provider, model, qty, per_turn=None):
    """Costo de qty unidades, o None si no hay precio. «turn»: per_turn (el costo fijo del mes / turnos del mes)."""
    row = price_of(prices, kind, provider, model)
    if row is None or row["price"] is None:
        return None
    if KINDS[kind][1] is None:
        return qty * per_turn if per_turn is not None else None
    return qty * row["price"] / KINDS[kind][1]


def _per_turn(prices):
    """{"YYYY-MM": costo por turno} con el costo fijo mensual del motor repartido entre todos los turnos del mes."""
    row = price_of(prices, "turn", "parla", "engine")
    if not row or not row["price"]:
        return {}
    return {month: row["price"] / n for month, n in db.q("SELECT substr(day, 1, 7), sum(qty) FROM usage WHERE kind = 'turn' GROUP BY 1") if n}


# ---------- reportes ----------

def _rows(where, args):
    return db.q("SELECT day, session_id, channel, provider, model, kind, sum(qty) FROM usage WHERE %s "
                "GROUP BY day, session_id, channel, provider, model, kind" % where, args)


def _priced(rows):
    prices = table()
    turns = _per_turn(prices)
    out = []
    for day, sid, channel, provider, model, kind, qty in rows:
        cost = cost_of(prices, kind, provider, model, qty, turns.get(day[:7]))
        out.append({"day": day, "sessionId": sid, "channel": channel, "provider": provider, "model": model, "kind": kind,
                    "qty": qty, "cost": cost})
    return prices, out


def _breakdown(items):
    """Por proveedor, modelo y tipo: cantidad, unidad y costo (None = falta el precio)."""
    groups = {}
    for i in items:
        g = groups.setdefault((i["kind"], i["provider"], i["model"]), {"kind": i["kind"], "group": KINDS[i["kind"]][3], "provider": i["provider"],
                                                                         "model": i["model"], "qty": 0, "unit": KINDS[i["kind"]][0], "cost": 0.0, "priced": True})
        g["qty"] += i["qty"]
        if i["cost"] is None:
            g["priced"] = False
        else:
            g["cost"] += i["cost"]
    for g in groups.values():
        g["qty"], g["cost"] = round(g["qty"], 4), round(g["cost"], 6)
    return sorted(groups.values(), key=lambda g: -g["cost"])


def session_usage(agent_id, sid):
    """El uso y costo de una conversación (API de sesiones y visor de conversaciones)."""
    prices, items = _priced(_rows("agent_id = ? AND session_id = ?", (agent_id, sid)))
    lines = _breakdown(items)
    return {"currency": prices["currency"], "estimated": True, "total": round(sum(i["cost"] or 0 for i in items), 6), "items": lines}


def by_session(agent_id):
    """{sessionId: costo estimado} de todas las conversaciones del agente (resultados de los experimentos A/B).
    ponytail: suma todo el uso del agente; filtrar por fechas del experimento si la tabla usage crece mucho."""
    out = {}
    for i in _priced(_rows("agent_id = ? AND session_id IS NOT NULL", [agent_id]))[1]:
        out[i["sessionId"]] = out.get(i["sessionId"], 0.0) + (i["cost"] or 0)
    return out


def _pct(values, q):
    if not values:
        return None
    values = sorted(values)
    return values[min(len(values) - 1, int(round(q * (len(values) - 1))))]


def report(agent_id, query=None, records=None, handed=None):
    """El panel «Costos»: total, por día, canal, proveedor y tipo; por conversación (promedio, mediana, p95), por
    conversación resuelta (records sin derivar a una persona: handed(r) False) y las más caras."""
    query = query or {}
    where, args = "agent_id = ?", [agent_id]
    for key, op in (("from", ">="), ("to", "<=")):
        if query.get(key):
            where, args = where + " AND day %s ?" % op, args + [str(query[key])[:10]]
    if query.get("channel"):
        where, args = where + " AND channel = ?", args + [query["channel"]]
    if query.get("sessions") is not None:      # solo estas conversaciones (una campaña)
        sids = list(query["sessions"]) or [""]
        where, args = where + " AND session_id IN (%s)" % ",".join("?" * len(sids)), args + sids
    prices, items = _priced(_rows(where, args))
    total = sum(i["cost"] or 0 for i in items)
    days, chans, per = {}, {}, {}
    for i in items:
        days[i["day"]] = days.get(i["day"], 0) + (i["cost"] or 0)
        chans[i["channel"] or "—"] = chans.get(i["channel"] or "—", 0) + (i["cost"] or 0)
        if i["sessionId"]:
            s = per.setdefault(i["sessionId"], {"sessionId": i["sessionId"], "channel": i["channel"], "cost": 0.0})
            s["cost"] += i["cost"] or 0
    lines = _breakdown(items)
    kinds = {}
    for g in lines:
        kinds[g["group"]] = kinds.get(g["group"], 0) + g["cost"]
    costs = [s["cost"] for s in per.values()]
    resolved = [r for r in records or [] if not (handed or (lambda r: False))(r)]
    top = sorted(per.values(), key=lambda s: -s["cost"])[:10]
    r6 = lambda v: round(v, 6) if v is not None else None
    out = {"currency": prices["currency"], "estimated": True, "from": query.get("from"), "to": query.get("to"), "total": r6(total),
           "by_day": [{"date": d, "cost": r6(days[d])} for d in sorted(days)],
           "by_channel": [{"channel": c, "cost": r6(v)} for c, v in sorted(chans.items(), key=lambda kv: -kv[1])],
           "by_kind": [{"group": k, "cost": r6(v)} for k, v in sorted(kinds.items(), key=lambda kv: -kv[1])],
           "by_provider": lines,
           "conversations": {"count": len(costs), "avg": r6(statistics.fmean(costs)) if costs else None,
                             "median": r6(statistics.median(costs)) if costs else None, "p95": r6(_pct(costs, 0.95))},
           "resolved": {"count": len(resolved), "cost_per": r6(total / len(resolved)) if resolved else None},
           "top": [dict(s, cost=r6(s["cost"])) for s in top],
           "missing_prices": [{"kind": g["kind"], "provider": g["provider"], "model": g["model"]} for g in lines if not g["priced"]]}
    group = query.get("group")
    if group in ("day", "channel", "provider"):
        out["groups"] = {"day": out["by_day"], "channel": out["by_channel"], "provider": lines}[group]
    return out


def csv_rows(agent_id, query=None):
    """El detalle para exportar: una fila por día, conversación, canal, proveedor, modelo y tipo."""
    where, args = "agent_id = ?", [agent_id]
    for key, op in (("from", ">="), ("to", "<=")):
        if (query or {}).get(key):
            where, args = where + " AND day %s ?" % op, args + [str(query[key])[:10]]
    prices, items = _priced(_rows(where, args))
    head = ["day", "session", "channel", "provider", "model", "kind", "qty", "unit", "cost_" + prices["currency"].lower()]
    return [head] + [[i["day"], i["sessionId"], i["channel"], i["provider"], i["model"], i["kind"], round(i["qty"], 6), KINDS[i["kind"]][0],
                      "" if i["cost"] is None else round(i["cost"], 6)] for i in sorted(items, key=lambda i: (i["day"], i["sessionId"]))]
