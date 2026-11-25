"""Analítica y "lo que no entendió": se calcula al vuelo sobre las conversaciones guardadas (sin app al importar)."""
import re
import time
import unicodedata
from collections import Counter

from . import knowledge

ANNOT = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")
IDLE = 30 * 60            # una conversación sin cerrar y quieta más de 30 min cuenta como abandonada
SIMILAR = 0.8


def norm(text):
    t = unicodedata.normalize("NFD", ANNOT.sub(r"\1", str(text or ""))).lower()
    t = "".join(c for c in t if not unicodedata.combining(c))
    return " ".join(re.sub(r"[^\w\s]", " ", t).split())


def is_fallback(agent, entry):
    """Las entradas nuevas traen "fallback"; en las viejas: no la tomó como respuesta y no llegó al umbral."""
    if "fallback" in entry:
        return bool(entry["fallback"]) and not entry.get("via")   # la base de conocimiento o la IA la respondieron
    if entry.get("answer_to"):
        return False
    return entry.get("intent") is None or float(entry.get("confidence") or 0) < float(agent.get("threshold") or 0)


def _encode(texts, cache=False):
    """cache=True solo para textos acotados (ejemplos de intenciones); lo que escribe la gente no se guarda."""
    try:
        return (knowledge._vecs(texts) if cache else knowledge.encode(texts)) if knowledge.encode and texts else None
    except Exception:
        return None


def unrecognized(agent, records):
    known = {norm(e) for i in agent.get("intents", []) for e in i.get("examples", [])}
    skip = known | {norm(p) for p in agent.get("ignored_phrases", [])}
    intents = [i["name"] for i in agent.get("intents", []) if not i["name"].startswith("__")]
    by_text = {}          # texto normalizado -> entradas
    for r in records:
        for e in r.get("history", []):
            if e.get("from") == "user" and is_fallback(agent, e) and norm(e.get("text")) and norm(e["text"]) not in skip:
                by_text.setdefault(norm(e["text"]), []).append(dict(e, sessionId=r.get("sessionId")))
    keys = sorted(by_text, key=lambda k: -len(by_text[k]))
    vecs = _encode(keys)
    clusters = []         # [(vector semilla, [claves])]; ponytail: greedy O(n·clusters), alcanza para miles de frases
    for n, k in enumerate(keys):
        v = vecs[n] if vecs is not None else None
        home = next((c for c in clusters if v is not None and float(c[0] @ v) >= SIMILAR), None)
        if home:
            home[1].append(k)
        else:
            clusters.append((v, [k]))
    ex_vecs = None
    groups = []
    for v, ks in clusters:
        entries = [e for k in ks for e in by_text[k]]
        guess = Counter(e.get("intent") for e in entries if e.get("intent") in intents).most_common(1)
        suggested = guess[0][0] if guess else None
        if suggested is None and v is not None:
            if ex_vecs is None:
                pairs = [(norm(e), i["name"]) for i in agent.get("intents", []) if i["name"] in intents for e in i.get("examples", []) if norm(e)]
                found = _encode([p for p, _ in pairs], cache=True)
                ex_vecs = (pairs, [] if found is None else found)
            scored = [(float(x @ v), name) for (_, name), x in zip(*ex_vecs)]
            suggested = max(scored)[1] if scored else None
        entries.sort(key=lambda e: e.get("at") or "", reverse=True)
        groups.append({"label": Counter(e["text"] for e in entries).most_common(1)[0][0], "count": len(entries),
                       "texts": sorted({e["text"] for e in entries}),
                       "examples": [{"text": e["text"], "sessionId": e["sessionId"], "at": e.get("at")} for e in entries[:20]],
                       "suggested_intent": suggested})
    groups.sort(key=lambda g: -g["count"])
    return {"groups": groups}


def _handed(r):
    return bool(r.get("handoff")) or any(e.get("from") == "human" or e.get("handoff") for e in r.get("history", []))


def _where(r):
    """(flujo, pregunta) en que quedó parada la conversación, o None si no esperaba nada."""
    st = r.get("state") or {}
    top = (st.get("stack") or [None])[-1] or st
    if top.get("flow") and top.get("waiting") is not None:
        return top["flow"], top["waiting"]
    return None


def _ts(iso):
    try:
        return time.mktime(time.strptime(iso[:19], "%Y-%m-%dT%H:%M:%S"))
    except (TypeError, ValueError):
        return None


def analytics(agent, records, now=None):
    now = time.time() if now is None else now
    n = len(records)
    handed = user = fallbacks = 0
    csat = Counter()
    drops, flows, days = Counter(), {}, {}
    for r in records:
        day = days.setdefault((r.get("started") or "")[:10], {"date": (r.get("started") or "")[:10], "sessions": 0,
                                                              "handoff": 0, "messages": 0, "fallbacks": 0, "abandoned": 0})
        day["sessions"] += 1
        h = _handed(r)
        handed += h
        day["handoff"] += h
        if r.get("csat") in (1, 2, 3, 4, 5):
            csat[r["csat"]] += 1
        seen = set()
        for e in r.get("history", []):
            if e.get("from") != "user":
                continue
            user += 1
            day["messages"] += 1
            if is_fallback(agent, e):
                fallbacks += 1
                day["fallbacks"] += 1
            if e.get("flow"):
                seen.add(e["flow"])
        where = _where(r)
        if where:
            seen.add(where[0])
        for f in seen:
            flows.setdefault(f, {"flow": f, "started": 0, "dropped": 0})["started"] += 1
        idle = _ts(r.get("updated"))
        if where and not r.get("ended") and not h and idle is not None and now - idle > IDLE:
            drops[where] += 1
            flows[where[0]]["dropped"] += 1
            day["abandoned"] += 1
    answered = sum(csat.values())
    pct = lambda x, total: round(x / total, 3) if total else None
    return {
        "sessions": n, "contained": n - handed, "handoff": handed,
        "contained_rate": pct(n - handed, n), "handoff_rate": pct(handed, n),
        "user_messages": user, "fallbacks": fallbacks, "fallback_rate": pct(fallbacks, user),
        "csat": {"average": round(sum(k * v for k, v in csat.items()) / answered, 2) if answered else None,
                 "answered": answered, "distribution": {str(k): csat[k] for k in range(1, 6)}},
        "abandoned": sum(drops.values()),
        "drop_off": [{"flow": f, "question": q, "count": c} for (f, q), c in drops.most_common()],
        "flows": sorted(flows.values(), key=lambda f: (-f["dropped"], -f["started"])),
        "by_day": [days[d] for d in sorted(days)],
    }
