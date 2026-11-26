#!/usr/bin/env python3
"""Pruebas de conversación (parla/bottests.py):  .venv/bin/python tests/test_bottests.py
Contra un Parla temporal propio (necesita el modelo de embeddings) y la CLI de CI."""
import atexit
import copy
import json
import os
import shutil
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request

import support

TMP = support.temp_data()
_server, _port = support.start_server(TMP)
atexit.register(lambda: (_server.terminate(), _server.wait()))
from parla.bottests import shape_errors  # noqa: E402

BASE = "http://127.0.0.1:%d" % _port
PIZZERIA = os.path.join(support.ROOT, "examples", "pizzeria.json")


def call(method, path, body=None):
    request = urllib.request.Request(BASE + path, data=json.dumps(body).encode() if body is not None else None,
                                     headers={"Content-Type": "application/json"}, method=method)
    try:
        with urllib.request.urlopen(request, timeout=300) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as error:
        return error.code, json.loads(error.read())


def ok(method, path, body=None):
    status, data = call(method, path, body)
    assert status == 200, (status, data)
    return data


# ---------- formato (sin servidor) ----------
assert shape_errors([]) == [] and shape_errors({}) == ["«tests» tiene que ser una lista de pruebas"]
errs = shape_errors([{"name": "a", "turns": [{"says": "hola"}, {"say": "x"}, {"user": "y", "says": "/([/"}]},
                     {"name": "a", "turns": [{"user": "z", "intent": "Nada", "slots": {"no": 1}, "flow": "F"}]}],
                    intents={"Saludar"}, slots={"nombre"}, flows={"Pedido"})
for needle in ("turno 2: no conozco say", "turno 2: falta «user»", "regex de «says» no compila", "«a» está repetida",
               "no existe la intención «Nada»", "no existen los slots no", "no existe el flujo «F»"):
    assert any(needle in e for e in errs), (needle, errs)
assert shape_errors([{"name": "a", "turns": [{"says": "hola"}, {"user": "y"}]}]) == []   # el primero sin «user» es el saludo
print("formato: ok")

# ---------- la suite del ejemplo pasa, y viaja con el agente ----------
with open(PIZZERIA, encoding="utf-8") as f:
    exported = json.load(f)
pizza = ok("POST", "/api/agents", {"import": exported})
pid = pizza["id"]
assert [t["name"] for t in pizza["tests"]][:2] == ["Pedido completo", "Pedido directo con el nombre precargado"], pizza
ok("POST", "/api/agents/%s/train" % pid, {})
r = ok("POST", "/api/agents/%s/tests/run" % pid, {})
assert r["passed"] and r["total"] == len(pizza["tests"]) and r["failed"] == 0, json.dumps(r, ensure_ascii=False)[:2000]
first = r["tests"][0]["turns"][0]
assert first["got"]["intent"] == "Saludar" and first["got"]["flow"] == "Tomar pedido" and first["failures"] == [], first
assert ok("POST", "/api/agents/%s/tests/run" % pid, {"names": ["Pedido completo"]})["total"] == 1
assert call("POST", "/api/agents/%s/tests/run" % pid, {"names": "x"})[0] == 400
assert call("POST", "/api/agents/%s/tests/run" % pid, {"environment": "staging"})[0] == 400   # no hay nada en staging
print("ejemplo: ok")

# ---------- fallas con diff, regex, botones, datos de inicio y pasar a una persona ----------
BOT = {
    "name": "Botones", "threshold": 0.5, "fallback": "No entendí.",
    "intents": [{"name": "Saludar", "examples": ["hola", "buenas", "buen día", "qué tal"]},
                {"name": "Reclamo", "examples": ["tengo un reclamo", "quiero quejarme", "hacer un reclamo", "estoy enojado con el servicio"]}],
    "slots": [{"name": "cliente"}],
    "flows": [{"name": "Bienvenida", "trigger": "__start__", "steps": [
        {"type": "message", "text": "Hola {{ cliente }}, ¿en qué te ayudo?",
         "buttons": [{"label": "Reclamo", "value": "tengo un reclamo"}, {"label": "Nada"}]}]},
        {"name": "Reclamos", "trigger": "Reclamo", "steps": [{"type": "handoff", "text": "Te paso con una persona."}]}],
    "tests": [
        {"name": "Reclamo", "start": {"cliente": "Ana"}, "turns": [
            {"says": "/^Hola Ana, ¿en qué/", "buttons": ["Reclamo", "Nada"]},
            {"user": "tengo un reclamo", "intent": "Reclamo", "flow": "Reclamos", "handoff": True, "says": "persona"}]},
        {"name": "Rota", "turns": [
            {"says": "/^Chau/", "buttons": ["Otro"]},
            {"user": "hola", "intent": "Reclamo", "says": "adiós", "slots": {"cliente": "Ana"}, "handoff": True}]},
    ],
}
bot = ok("POST", "/api/agents", {"import": BOT})
bid = bot["id"]
ok("POST", "/api/agents/%s/train" % bid, {})
r = ok("POST", "/api/agents/%s/tests/run" % bid, {})
good, bad = r["tests"]
assert good["passed"], json.dumps(good, ensure_ascii=False)
assert good["turns"][0]["user"] is None and good["turns"][0]["got"]["buttons"] == ["Reclamo", "Nada"], good
assert not r["passed"] and r["failed"] == 1 and not bad["passed"], r
f0 = {f["check"]: f for f in bad["turns"][0]["failures"]}
assert f0["says"]["expected"] == "/^Chau/" and f0["says"]["got"].startswith("Hola"), f0
assert f0["buttons"]["expected"] == ["Otro"] and f0["buttons"]["got"] == ["Reclamo", "Nada"], f0
f1 = {f["check"]: f for f in bad["turns"][1]["failures"]}
assert set(f1) == {"intent", "says", "slots.cliente", "handoff"}, f1
assert f1["intent"]["expected"] == "Reclamo" and f1["intent"]["got"] != "Reclamo", f1
assert f1["slots.cliente"] == {"check": "slots.cliente", "expected": "Ana", "got": None}, f1
assert f1["handoff"] == {"check": "handoff", "expected": True, "got": False}, f1
print("fallas: ok (diff por turno, regex, botones, datos de inicio, persona)")

# ---------- el borrador sin entrenar: las pruebas usan lo que se publicaría ----------
edited = ok("GET", "/api/agents/" + bid)
edited["intents"].append({"name": "Despedirse", "examples": ["chau", "adiós", "hasta luego", "nos vemos"]})
edited["flows"].append({"name": "Chau", "trigger": "Despedirse", "steps": [{"type": "message", "text": "¡Hasta pronto!"}]})
edited["tests"].append({"name": "Despedida", "turns": [{"user": "chau, nos vemos", "intent": "Despedirse", "says": "Hasta pronto"}]})
ok("PUT", "/api/agents/" + bid, edited)
assert ok("POST", "/api/agents/%s/tests/run" % bid, {"names": ["Despedida"]})["passed"]

# ---------- publicar en Producción: primero las pruebas ----------
status, body = call("POST", "/api/agents/%s/versions" % bid, {"note": "x", "environment": "production"})
assert status == 409 and "«Rota»" in body["error"] and body["tests"]["failed"] == 1, (status, body)
assert ok("GET", "/api/agents/%s/versions" % bid)["versions"] == []                      # no publicó nada
assert ok("POST", "/api/agents/%s/versions" % bid, {"note": "a pruebas", "environment": "staging"})["version"] == 1
v2 = ok("POST", "/api/agents/%s/versions" % bid, {"note": "igual", "environment": "production", "force": True})
assert v2["version"] == 2 and v2["environments"] == ["production"], v2
assert [t["name"] for t in ok("GET", "/api/agents/%s/versions/2" % bid)["agent"]["tests"]] == ["Reclamo", "Rota", "Despedida"]
assert ok("POST", "/api/agents/%s/tests/run" % bid, {"environment": "production", "names": ["Reclamo"]})["tests"][0]["version"] == 2
assert ok("POST", "/api/agents/%s/versions" % pid, {"note": "todo verde", "environment": "production"})["version"] == 1
print("publicar: ok (409 con las fallas, force, staging sin trabas, versión con sus pruebas)")

# ---------- las pruebas no dejan conversaciones: ni Conversaciones, ni Bandeja, ni reportes ----------
for agent_id in (pid, bid):
    assert ok("GET", "/api/v1/bots/%s/sessions" % agent_id)["sessions"] == []
    assert ok("GET", "/api/agents/%s/inbox" % agent_id)["sessions"] == []
    assert ok("GET", "/api/agents/%s/insights/analytics" % agent_id)["sessions"] == 0
    assert ok("GET", "/api/v1/bots/%s/report" % agent_id)["sessions"] == 0
    assert not os.path.exists(os.path.join(TMP, "agents", agent_id + ".sessions"))
print("aislamiento: ok")

# ---------- CLI para CI ----------
cli = lambda file, **env: subprocess.run([sys.executable, "-m", "parla.bottests", file], cwd=support.ROOT, capture_output=True,
                                         text=True, env=dict(os.environ, **env), timeout=600)
done = cli(PIZZERIA)
assert done.returncode == 0 and "pasaron las %d pruebas" % len(pizza["tests"]) in done.stdout, done.stdout + done.stderr
folder = tempfile.mkdtemp(prefix="parla-cli-")
atexit.register(shutil.rmtree, folder, True)
broken = copy.deepcopy(exported)
broken["agent"]["tests"][0]["turns"][0]["says"] = "¡Bienvenido a la heladería!"
with open(os.path.join(folder, "rota.parla.json"), "w", encoding="utf-8") as f:
    json.dump(broken, f, ensure_ascii=False)
done = cli(os.path.join(folder, "rota.parla.json"), GITHUB_ACTIONS="true")
assert done.returncode == 1 and "FALLÓ  Pedido completo" in done.stdout and "heladería" in done.stdout, done.stdout + done.stderr
assert "::error file=" in done.stdout and "title=Prueba «Pedido completo»" in done.stdout, done.stdout
del broken["agent"]["tests"]
with open(os.path.join(folder, "sin.parla.json"), "w", encoding="utf-8") as f:
    json.dump(broken, f, ensure_ascii=False)
done = cli(os.path.join(folder, "sin.parla.json"))
assert done.returncode == 1 and "no tiene pruebas" in done.stdout, done.stdout + done.stderr
print("cli: ok (0 si pasan, 1 con anotaciones de GitHub si falla, 1 sin pruebas)")
