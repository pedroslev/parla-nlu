"""Experimentos A/B: en un entorno (casi siempre production), las conversaciones nuevas se reparten entre 2 a 4
versiones publicadas según su peso. La asignación es determinística: sha256(id del experimento + sessionId), así
cualquier réplica elige la misma variante sin hablar con las demás, y la conversación queda atada a esa versión (como
siempre: open_session guarda record["version"]). La configuración vive en el agente («experiments», como
«environments») y los resultados se calculan de las conversaciones guardadas: valen igual con SQLite o Postgres.

Estadística sin scipy: z de dos proporciones para las tasas; t de Welch (con la beta incompleta regularizada para el
valor p) para promedios (CSAT, costo, turnos). Cada variante se compara contra A, con Bonferroni si hay más de una.
Nunca elige un ganador sola: eso lo decide una persona al parar el experimento."""
import hashlib
import math
import statistics
import time
import uuid

from . import insights

STATUSES = ("draft", "running", "paused", "stopped")
GOALS = ("flow", "intent", "classification")
MAX_VARIANTS = 4
ALPHA = 0.05
MIN_CONVERSATIONS = 100        # por variante, para las tasas
MIN_ANSWERS = 30               # por variante, para promedios (CSAT, costo…)
SKIP_CHANNELS = {"prueba"}     # el chat de prueba del editor no entra en ningún experimento


def _now():
    return time.strftime("%Y-%m-%dT%H:%M:%S")


# ---------- configuración ----------

def validate(data, versions, environments, old=None):
    """El experimento limpio a partir de lo que mandó la interfaz o la API. versions: los números publicados."""
    if not isinstance(data, dict):
        raise ValueError("mandá el experimento como un objeto JSON")
    name = str(data.get("name") or (old or {}).get("name") or "").strip()[:80]
    if not name:
        raise ValueError("ponele un nombre al experimento")
    environment = data.get("environment") or (old or {}).get("environment") or "production"
    if environment not in environments:
        raise ValueError("el entorno tiene que ser production o staging")
    raw = data.get("variants", (old or {}).get("variants"))
    if not isinstance(raw, list) or not 2 <= len(raw) <= MAX_VARIANTS:
        raise ValueError("un experimento tiene de 2 a 4 variantes")
    variants = []
    for n, v in enumerate(raw):
        if not isinstance(v, dict):
            raise ValueError("cada variante es un objeto con «version» y «weight»")
        try:
            version, weight = int(v.get("version")), int(v.get("weight", 50))
        except (TypeError, ValueError):
            raise ValueError("cada variante necesita «version» (una versión publicada) y «weight» (de 1 a 100)") from None
        if version not in versions:
            raise ValueError("no existe la versión %s" % version)
        if not 1 <= weight <= 100:
            raise ValueError("el peso de cada variante va de 1 a 100")
        variants.append({"name": "ABCD"[n], "version": version, "weight": weight})
    channels = data.get("channels", (old or {}).get("channels")) or []
    if not (isinstance(channels, list) and all(isinstance(c, str) for c in channels)):
        raise ValueError("«channels» tiene que ser una lista de canales, por ejemplo [\"whatsapp\"]")
    goal = data.get("goal", (old or {}).get("goal"))
    if goal is not None:
        if not (isinstance(goal, dict) and goal.get("type") in GOALS and isinstance(goal.get("value"), str) and goal["value"].strip()):
            raise ValueError("el objetivo es {\"type\": flow, intent o classification, \"value\": el nombre}")
        goal = {"type": goal["type"], "value": goal["value"].strip()[:120]}
    base = old or {"id": uuid.uuid4().hex[:8], "status": "draft", "created": _now(), "started": None, "stopped": None, "winner": None}
    return dict(base, name=name, environment=environment, variants=variants, channels=[c[:30] for c in channels][:10], goal=goal)


def find(agent, eid):
    found = next((e for e in agent.get("experiments") or [] if e["id"] == eid), None)
    if not found:
        raise LookupError(eid)
    return found


def transition(agent, exp, action, winner=None):
    """start / pause / stop sobre exp (en el agente). -> la versión ganadora a desplegar, o None."""
    if action == "start":
        if exp["status"] not in ("draft", "paused"):
            raise ValueError("ese experimento ya terminó o ya está corriendo")
        if any(e["status"] == "running" and e["environment"] == exp["environment"] and e["id"] != exp["id"] for e in agent.get("experiments") or []):
            raise ValueError("ya hay un experimento corriendo en ese entorno: pausalo o terminalo primero")
        exp.update(status="running", started=exp.get("started") or _now())
        return None
    if action == "pause":
        if exp["status"] != "running":
            raise ValueError("solo se puede pausar un experimento que está corriendo")
        exp["status"] = "paused"
        return None
    if exp["status"] not in ("running", "paused"):
        raise ValueError("solo se puede terminar un experimento que está corriendo o en pausa")
    chosen = None
    if winner not in (None, ""):
        chosen = next((v for v in exp["variants"] if v["name"] == winner), None)
        if not chosen:
            raise ValueError("«winner» tiene que ser el nombre de una variante (A, B, C o D)")
    exp.update(status="stopped", stopped=_now(), winner=chosen["name"] if chosen else None)
    return chosen["version"] if chosen else None


# ---------- asignación ----------

def running(agent, environment, channel):
    """El experimento que reparte las conversaciones nuevas de ese entorno y canal, o None."""
    if channel in SKIP_CHANNELS:
        return None
    for e in agent.get("experiments") or []:
        if e["status"] == "running" and e["environment"] == environment and (not e.get("channels") or channel in e["channels"]):
            return e
    return None


def assign(exp, sid):
    """La variante de esa conversación: siempre la misma para el mismo experimento y sessionId."""
    total = sum(v["weight"] for v in exp["variants"])
    point = int.from_bytes(hashlib.sha256(("%s:%s" % (exp["id"], sid)).encode()).digest()[:8], "big") % total
    for v in exp["variants"]:
        point -= v["weight"]
        if point < 0:
            return v
    return exp["variants"][-1]


# ---------- estadística ----------

def _betacf(a, b, x):
    """Fracción continua de la beta incompleta (Lentz; Numerical Recipes 6.4)."""
    tiny = 1e-300
    qab, qap, qam = a + b, a + 1, a - 1
    c, d = 1.0, 1 - qab * x / qap
    d = 1 / (d if abs(d) > tiny else tiny)
    h = d
    for m in range(1, 300):
        m2 = 2 * m
        for aa in (m * (b - m) * x / ((qam + m2) * (a + m2)), -(a + m) * (qab + m) * x / ((a + m2) * (qap + m2))):
            d = 1 + aa * d
            d = 1 / (d if abs(d) > tiny else tiny)
            c = 1 + aa / c
            c = c if abs(c) > tiny else tiny
            h *= d * c
        if abs(d * c - 1) < 3e-14:
            break
    return h


def betainc(a, b, x):
    """La beta incompleta regularizada I_x(a, b)."""
    if x <= 0:
        return 0.0
    if x >= 1:
        return 1.0
    front = math.exp(math.lgamma(a + b) - math.lgamma(a) - math.lgamma(b) + a * math.log(x) + b * math.log(1 - x))
    if x < (a + 1) / (a + b + 2):
        return front * _betacf(a, b, x) / a
    return 1 - front * _betacf(b, a, 1 - x) / b


def t_pvalue(t, df):
    """P(|T| >= |t|) con df grados de libertad (dos colas)."""
    return betainc(df / 2, 0.5, df / (df + t * t))


def _critical(pvalue, alpha):
    """El valor c con pvalue(c) = alpha (bisección: pvalue baja con c)."""
    lo, hi = 0.0, 1e3
    for _ in range(200):
        mid = (lo + hi) / 2
        lo, hi = (mid, hi) if pvalue(mid) > alpha else (lo, mid)
    return (lo + hi) / 2


def z_pvalue(z):
    return math.erfc(abs(z) / math.sqrt(2))


def ztest(x1, n1, x2, n2, alpha=ALPHA):
    """Dos proporciones: x2/n2 contra x1/n1. -> diff, IC (1 - alpha, sin agrupar), z y p (agrupado), o None."""
    if not n1 or not n2:
        return None
    p1, p2, pool = x1 / n1, x2 / n2, (x1 + x2) / (n1 + n2)
    se = math.sqrt(pool * (1 - pool) * (1 / n1 + 1 / n2))
    z = (p2 - p1) / se if se else 0.0
    half = _critical(z_pvalue, alpha) * math.sqrt(p1 * (1 - p1) / n1 + p2 * (1 - p2) / n2)
    return {"diff": p2 - p1, "ci": [p2 - p1 - half, p2 - p1 + half], "z": z, "p": z_pvalue(z) if se else 1.0}


def welch(a, b, alpha=ALPHA):
    """t de Welch: media de b menos media de a. -> diff, IC (1 - alpha), t, df y p, o None con menos de 2 por lado."""
    n1, n2 = len(a), len(b)
    if n1 < 2 or n2 < 2:
        return None
    m1, m2 = statistics.fmean(a), statistics.fmean(b)
    q1, q2 = statistics.variance(a) / n1, statistics.variance(b) / n2
    diff, se2 = m2 - m1, q1 + q2
    if se2 == 0:
        return {"diff": diff, "ci": [diff, diff], "t": 0.0, "df": n1 + n2 - 2, "p": 1.0 if diff == 0 else 0.0}
    df = se2 ** 2 / (q1 ** 2 / (n1 - 1) + q2 ** 2 / (n2 - 1))
    t = diff / math.sqrt(se2)
    half = _critical(lambda c: t_pvalue(c, df), alpha) * math.sqrt(se2)
    return {"diff": diff, "ci": [diff - half, diff + half], "t": t, "df": df, "p": t_pvalue(t, df)}


# ---------- resultados ----------

def reached(record, goal):
    """¿La conversación cumplió el objetivo? flow: pasó por ese flujo; intent: la persona dijo esa intención;
    classification: quedó clasificada así."""
    if not goal:
        return False
    kind, value = goal["type"], goal["value"]
    if kind == "flow":
        return value in (record.get("flows") or []) or any(e.get("flow") == value for e in record.get("history") or [])
    if kind == "intent":
        return any(e.get("from") == "user" and e.get("intent") == value for e in record.get("history") or [])
    return value in [m["name"] for m in record.get("classifications") or []]


RATES = (("resolved_rate", "higher"), ("handoff_rate", "lower"), ("fallback_rate", "lower"), ("goal_rate", "higher"))
MEANS = (("csat", "higher"), ("cost", "lower"), ("turns", None))


def _variant_stats(agent, variant, records, cost_of):
    n = len(records)
    flags = {"resolved_rate": [], "handoff_rate": [], "fallback_rate": [], "goal_rate": []}
    samples = {"csat": [], "cost": [], "turns": []}
    latency = []
    for r in records:
        users = [e for e in r.get("history") or [] if e.get("from") == "user"]
        handed = insights._handed(r)
        flags["resolved_rate"].append(not handed)
        flags["handoff_rate"].append(handed)
        flags["fallback_rate"].append(any(insights.is_fallback(agent, e) for e in users))
        flags["goal_rate"].append(reached(r, agent.get("_goal")))
        if r.get("csat") in (1, 2, 3, 4, 5):
            samples["csat"].append(r["csat"])
        samples["cost"].append(cost_of(r["sessionId"]))
        samples["turns"].append(len(users))
        latency += [e["ms"] for e in users if isinstance(e.get("ms"), (int, float))]
    mean = lambda xs, d=4: round(statistics.fmean(xs), d) if xs else None
    out = dict(variant, conversations=n, latency_ms=mean(latency, 1))
    for key, xs in flags.items():
        out[key] = {"count": sum(xs), "rate": round(sum(xs) / n, 4) if n else None}
    for key, xs in samples.items():
        out[key] = {"count": len(xs), "avg": mean(xs, 6 if key == "cost" else 3)}
    if not agent.get("_goal"):
        out["goal_rate"] = None
    return out, flags, samples


def results(agent, exp, records, cost_of):
    """Métricas por variante y comparación de cada una contra A. records: las conversaciones de este experimento.
    cost_of(sessionId) -> costo estimado de esa conversación."""
    agent = dict(agent, _goal=exp.get("goal"))
    groups = {v["name"]: [] for v in exp["variants"]}
    for r in records:
        if r.get("variant") in groups:
            groups[r["variant"]].append(r)
    rows = [_variant_stats(agent, v, groups[v["name"]], cost_of) for v in exp["variants"]]
    alpha = ALPHA / max(1, len(rows) - 1)                     # Bonferroni: varias variantes contra A
    base, base_flags, base_samples = rows[0]
    comparisons, warnings = [], []
    for row, flags, samples in rows:
        if row["conversations"] < MIN_CONVERSATIONS:
            warnings.append({"variant": row["name"], "metric": "conversations", "have": row["conversations"], "need": MIN_CONVERSATIONS})
        if 0 < row["csat"]["count"] < MIN_ANSWERS:        # sin encuestas no se avisa: el CSAT es opcional
            warnings.append({"variant": row["name"], "metric": "csat", "have": row["csat"]["count"], "need": MIN_ANSWERS})
    for row, flags, samples in rows[1:]:
        metrics = {}
        for key, better in RATES:
            if key == "goal_rate" and not exp.get("goal"):
                continue
            test = ztest(sum(base_flags[key]), len(base_flags[key]), sum(flags[key]), len(flags[key]), alpha)
            enough = min(base["conversations"], row["conversations"]) >= MIN_CONVERSATIONS
            metrics[key] = _verdict(test, alpha, enough, better)
        for key, better in MEANS:
            test = welch(base_samples[key], samples[key], alpha)
            need = MIN_ANSWERS if key == "csat" else MIN_CONVERSATIONS
            metrics[key] = _verdict(test, alpha, min(len(base_samples[key]), len(samples[key])) >= need, better)
        comparisons.append({"variant": row["name"], "vs": base["name"], "metrics": metrics})
    significant = [{"variant": c["variant"], "metric": k, "direction": m["direction"]}
                   for c in comparisons for k, m in c["metrics"].items() if m["significant"]]
    return {"experiment": exp, "variants": [r for r, _, _ in rows], "comparisons": comparisons, "alpha": round(alpha, 4),
            "confidence": round(1 - alpha, 4), "min_sample": {"conversations": MIN_CONVERSATIONS, "csat": MIN_ANSWERS},
            "warnings": warnings, "significant": significant, "winner": None,     # el ganador lo elige una persona (stop)
            "summary": "hay diferencias significativas" if significant else "sin diferencia significativa todavía"}


def _verdict(test, alpha, enough, better):
    if test is None:
        return {"diff": None, "ci": None, "p": None, "significant": False, "enough_data": False, "direction": None, "better": better}
    significant = enough and test["p"] < alpha
    direction = None
    if significant and better and test["diff"]:
        direction = "better" if (test["diff"] > 0) == (better == "higher") else "worse"
    r = lambda v: round(v, 6)
    return {"diff": r(test["diff"]), "ci": [r(test["ci"][0]), r(test["ci"][1])], "p": r(test["p"]), "significant": significant,
            "enough_data": enough, "direction": direction, "better": better}
