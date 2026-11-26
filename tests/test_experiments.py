"""Experimentos A/B (parla/experiments.py): asignación determinística y pegajosa, reparto por pesos, métricas por
variante, z y t de Welch contra valores conocidos, aviso de muestra chica, terminar con ganador (despliega), roles por
HTTP y dos servidores sobre los mismos datos (como dos réplicas: con PARLA_DATABASE_URL, sobre Postgres).
Sin modelos ni red.   .venv/bin/python tests/test_experiments.py"""
import http.client
import json
import os
import time

import support
DATA = support.temp_data()

from parla import costs, db, experiments as x, server as app  # noqa: E402

near = lambda a, b, tol=1e-3: abs(a - b) <= tol

# ---------- estadística: valores de referencia (calculados con scipy / tablas) ----------
z = x.ztest(50, 100, 65, 100)
assert near(z["z"], 2.1456) and near(z["p"], 0.0319) and near(z["ci"][0], 0.0146) and near(z["ci"][1], 0.2854), z
assert x.ztest(0, 0, 1, 10) is None and x.ztest(5, 10, 5, 10)["p"] == 1.0
assert near(x.t_pvalue(2.228, 10), 0.05) and near(x.t_pvalue(12.706, 1), 0.05) and near(x.t_pvalue(1.96, 1e6), 0.05)
assert near(x.t_pvalue(0, 7), 1.0)
w = x.welch([1, 2, 3, 4, 5], [2, 4, 6, 8, 10])          # scipy.stats.ttest_ind(..., equal_var=False): t=1.8974, p=0.1075
assert near(w["t"], 1.8974) and near(w["df"], 5.8824) and near(w["p"], 0.1075) and w["ci"][0] < 0 < w["ci"][1], w
assert x.welch([1], [2, 3]) is None and x.welch([2, 2], [2, 2])["p"] == 1.0

# ---------- asignación ----------
EXP = {"id": "abcdef01", "variants": [{"name": "A", "version": 1, "weight": 70}, {"name": "B", "version": 2, "weight": 30}]}
first = [x.assign(EXP, "s%d" % i)["name"] for i in range(20000)]
assert first == [x.assign(EXP, "s%d" % i)["name"] for i in range(20000)]                     # determinística
assert near(first.count("A") / len(first), 0.70, 0.015), first.count("A")                   # respeta los pesos
other = [x.assign(dict(EXP, id="12345678"), "s%d" % i)["name"] for i in range(2000)]
assert other != first[:2000]                                                                 # otro experimento, otro reparto
four = dict(EXP, variants=[{"name": n, "version": 1, "weight": 25} for n in "ABCD"])
got = [x.assign(four, "k%d" % i)["name"] for i in range(8000)]
assert all(near(got.count(n) / 8000, 0.25, 0.02) for n in "ABCD"), {n: got.count(n) for n in "ABCD"}

# ---------- validación ----------
for bad in ({"name": "x", "variants": [{"version": 1}]}, {"name": "", "variants": [{"version": 1}, {"version": 2}]},
            {"name": "x", "variants": [{"version": 1}, {"version": 9}]}, {"name": "x", "variants": [{"version": 1, "weight": 0}, {"version": 2}]},
            {"name": "x", "variants": [{"version": 1}] * 5}, {"name": "x", "environment": "qa", "variants": [{"version": 1}, {"version": 2}]},
            {"name": "x", "variants": [{"version": 1}, {"version": 2}], "goal": {"type": "otro", "value": "y"}}):
    try:
        x.validate(bad, [1, 2], app.ENVIRONMENTS)
        raise AssertionError(bad)
    except ValueError as error:
        assert str(error)

# ---------- en el motor: versiones, experimento, conversaciones ----------
os.makedirs(app.AGENTS, exist_ok=True)
app.classify = lambda data, text: []
app.self_check = lambda data: {"summary": "", "accuracy": None}
app.parse = lambda data, text, tagger, index=None: {"intent": "pedir" if "pizza" in text else None, "confidence": 1.0 if "pizza" in text else 0.0,
                                                    "entities": [], "ranking": []}
bot = app.create(dict(app.BLANK, name="Pizzeria AB", intents=[{"name": "pedir", "examples": ["pizza"]}],
                      flows=[{"name": "f", "trigger": "pedir", "steps": [{"type": "message", "text": "versión uno"}]}]))
aid = bot["id"]
app.publish(aid, "uno", "production")
draft = app.load(aid); draft["flows"][0]["steps"][0]["text"] = "versión dos"; draft["flows"][0]["name"] = "g"; app.store(draft)
app.publish(aid, "dos")
api = lambda method, rest=(), data=None: app.experiments_api(aid, method, list(rest), data or {})
status, exp = api("POST", [], {"name": "Saludo nuevo", "variants": [{"version": 1, "weight": 50}, {"version": 2, "weight": 50}],
                               "goal": {"type": "flow", "value": "g"}, "channels": ["api", "whatsapp"]})
assert status == 200 and exp["status"] == "draft" and [v["name"] for v in exp["variants"]] == ["A", "B"], exp
eid = exp["id"]
say = lambda sid, text="pizza", channel="api": app.api_v1("POST", ["bots", aid, "events"], {"sessionId": sid, "text": text, "channel": channel})[1]
assert say("antes")["variant"] is None                                  # en borrador no reparte
assert api("PUT", [eid], {"name": "Saludo nuevo (v2)"})[1]["name"] == "Saludo nuevo (v2)"
assert api("POST", [eid, "start"])[0] == 200
try:
    api("PUT", [eid], {"name": "otro"})
    raise AssertionError("no se cambia corriendo")
except ValueError:
    pass
_, second = api("POST", [], {"name": "otro", "variants": [{"version": 1}, {"version": 2}]})
try:
    api("POST", [second["id"], "start"])                                # uno por entorno
    raise AssertionError("dos corriendo")
except ValueError:
    pass
assert api("DELETE", [second["id"]])[1]["deleted"]

seen = {}
for i in range(60):
    sid = "c%02d" % i
    r = say(sid)
    assert r["experiment"] == eid and r["variant"] == x.assign(exp, sid)["name"], r
    assert r["messages"] == ["versión uno" if r["variant"] == "A" else "versión dos"], r
    seen[sid] = r["variant"]
assert set(seen.values()) == {"A", "B"}
app.deploy(aid, "production", 1)                                        # aunque cambie el entorno, la charla sigue en su variante
for sid in list(seen)[:10]:
    assert say(sid)["variant"] == seen[sid]
assert say("web1", channel="web")["variant"] is None                    # filtro de canal
assert say("p1", channel="prueba")["variant"] is None

# métricas: una B con handoff, CSAT y costo; una A que no entendió
rec = app.load_session(aid, "c00"); vb = next(s for s in seen if seen[s] == "B"); va = next(s for s in seen if seen[s] == "A")
b = app.load_session(aid, vb); b["csat"] = 5; b["handoff"] = {"active": True}; app.save_session(aid, b)
a = app.load_session(aid, va); a["csat"] = 3; a["history"].append({"from": "user", "text": "qué", "fallback": True, "intent": None}); app.save_session(aid, a)
costs.record("llm_input", "anthropic", "claude-opus-5-5", 1_000_000, agent=aid, session=vb, channel="api")      # $4
while db.pending():
    time.sleep(0.05)
status, res = api("GET", [eid, "results"])
assert status == 200 and res["experiment"]["id"] == eid
va_row, vb_row = res["variants"]
nA, nB = list(seen.values()).count("A"), list(seen.values()).count("B")
assert (va_row["conversations"], vb_row["conversations"]) == (nA, nB), res["variants"]
assert vb_row["handoff_rate"]["count"] == 1 and vb_row["resolved_rate"]["count"] == nB - 1
assert va_row["fallback_rate"]["count"] == 1 and va_row["csat"] == {"count": 1, "avg": 3} and vb_row["csat"]["avg"] == 5
assert vb_row["goal_rate"]["count"] == nB and va_row["goal_rate"]["count"] == 0       # B pasó por el flujo «g»
assert near(vb_row["cost"]["avg"], 4 / nB, 1e-6) and va_row["cost"]["avg"] == 0
assert vb_row["turns"]["avg"] >= 1 and va_row["latency_ms"] is not None
assert {w["variant"] for w in res["warnings"] if w["metric"] == "conversations"} == {"A", "B"}       # menos de 100 por variante
goal = res["comparisons"][0]["metrics"]["goal_rate"]
assert goal["p"] < 0.05 and not goal["enough_data"] and not goal["significant"]     # muestra chica: todavía no
assert res["summary"] == "sin diferencia significativa todavía" and res["winner"] is None
# sesiones, reportes y costos filtrados por experimento / variante; el webhook lleva la variante
assert {s["variant"] for s in app.api_v1("GET", ["bots", aid, "sessions"], {}, {"experiment": eid, "variant": "B"})[1]["sessions"]} == {"B"}
assert app.report(app.load(aid), {"experiment": eid})["sessions"] == nA + nB
assert near(app.cost_report(aid, {"experiment": eid, "variant": "B"})["total"], 4, 1e-6)
assert app.cost_report(aid, {"experiment": eid, "variant": "A"})["total"] == 0
from parla import handoff  # noqa: E402
assert handoff.context(app.load(aid), b)["variant"] == "B"
assert app.api_v1("GET", ["bots", aid, "experiments", eid, "results"], {})[1]["variants"][1]["name"] == "B"
assert app.api_v1("GET", ["bots", aid, "experiments", eid, "results"], {}, public=True)[0] == 403
# con muestra grande: diferencia significativa, pero el ganador lo elige una persona
big = [{"sessionId": "z%d" % i, "variant": "AB"[i % 2], "history": [], "flows": ["g"] if i % 2 and i % 10 else []} for i in range(600)]
res2 = x.results(app.load(aid), app.load(aid)["experiments"][0], big, lambda s: 0.0)
assert res2["comparisons"][0]["metrics"]["goal_rate"]["significant"] and res2["comparisons"][0]["metrics"]["goal_rate"]["direction"] == "better"
assert res2["summary"] == "hay diferencias significativas" and res2["winner"] is None

# pausa: las nuevas van al entorno; terminar con ganador lo despliega
assert api("POST", [eid, "pause"])[1]["experiment"]["status"] == "paused"
assert say("nueva-pausa")["variant"] is None
try:
    api("POST", [eid, "stop"], {"winner": "Z"})
    raise AssertionError("ganador inválido")
except ValueError:
    pass
status, done = api("POST", [eid, "stop"], {"winner": "B"})
assert status == 200 and done["experiment"]["status"] == "stopped" and done["experiment"]["winner"] == "B" and done["deployed"] == 2
assert app.load(aid)["environments"]["production"] == 2 and app.load(aid)["deployments"][-1]["version"] == 2
assert say("despues")["variant"] is None and say("despues")["messages"] == ["versión dos"]
assert api("GET", [eid])[1]["status"] == "stopped"
kept = app.load(aid); kept["name"] = "Pizzeria AB"
app.store(kept)
assert app.load(aid)["experiments"][0]["id"] == eid                                    # PUT de la interfaz no los pisa (keep)

# ---------- por HTTP: roles y dos servidores sobre los mismos datos ----------
_, exp3 = api("POST", [], {"name": "Réplicas", "variants": [{"version": 1}, {"version": 2}]})
api("POST", [exp3["id"], "start"])
USERS = os.path.join(DATA, "users.json")
procs = [support.start_server(DATA, USERS) for _ in range(2)]


def call(port, method, path, body=None, cookie=None):
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=30)
    conn.request(method, path, json.dumps(body) if body is not None else None, dict({"Content-Type": "application/json"}, **({"Cookie": cookie} if cookie else {})))
    r = conn.getresponse()
    data = json.loads(r.read() or b"{}")
    cookie_out = (r.getheader("Set-Cookie") or "").split(";")[0]
    conn.close()
    return r.status, data, cookie_out


try:
    (p1, port1), (p2, port2) = procs
    for i in range(30):                         # la misma charla por las dos «réplicas»: la misma variante siempre
        sid = "r%d" % i
        got = {call(port, "POST", "/api/v1/bots/%s/events" % aid, {"type": "start", "sessionId": sid, "channel": "api"})[1]["variant"] for port in (port1, port2)}
        assert got == {x.assign(exp3, sid)["name"]}, got
    owner = call(port1, "POST", "/api/users", {"name": "duena", "password": "secreta123"})[2]
    for name, role in (("ana", "analyst"), ("edu", "editor"), ("ati", "agent")):
        assert call(port1, "POST", "/api/users", {"name": name, "password": "secreta123", "role": role}, owner)[0] == 200
    login = lambda name: call(port2, "POST", "/api/auth/login", {"name": name, "password": "secreta123"})[2]
    ana, edu, ati = login("ana"), login("edu"), login("ati")
    base = "/api/agents/%s/experiments" % aid
    r1 = call(port1, "GET", base + "/%s/results" % exp3["id"], cookie=ana)[1]
    r2 = call(port2, "GET", base + "/%s/results" % exp3["id"], cookie=owner)[1]
    assert [v["conversations"] for v in r1["variants"]] == [v["conversations"] for v in r2["variants"]] and sum(v["conversations"] for v in r1["variants"]) == 30
    assert call(port1, "POST", base, {"name": "n", "variants": [{"version": 1}, {"version": 2}]}, ana)[0] == 403          # analista: solo mirar
    assert call(port1, "POST", base + "/%s/pause" % exp3["id"], cookie=ana)[0] == 403
    assert call(port1, "GET", base, cookie=ati)[0] == 403                                                                   # atención: no
    assert call(port2, "POST", base + "/%s/pause" % exp3["id"], cookie=edu)[1]["experiment"]["status"] == "paused"          # editor sí
    assert call(port1, "GET", base + "/" + exp3["id"], cookie=ana)[1]["status"] == "paused"                                 # la otra réplica lo ve
    assert call(port1, "POST", base + "/%s/stop" % exp3["id"], {"winner": "A"}, owner)[1]["deployed"] == 1
    assert call(port2, "GET", "/api/agents/" + aid + "/versions", cookie=owner)[1]["environments"]["production"] == 1
finally:
    for proc, _ in procs:
        proc.kill()
print("ok: experimentos A/B (%s)" % ("postgres" if db.PG else "sqlite"))
