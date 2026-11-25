#!/usr/bin/env python3
"""Autochequeo del servidor MCP de Parla.  .venv/bin/python tests/test_mcp.py
1) validate_agent con agentes buenos y rotos (local).  2) punta a punta contra un Parla temporal propio
(puerto libre, datos temporales, sin usuarios): nunca toca el que tengas corriendo."""
import atexit
import copy
import json
import os
import re
import shutil
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import support

TMP = support.temp_data()
_server, _port = support.start_server(TMP)
atexit.register(lambda: (_server.terminate(), _server.wait(), shutil.rmtree(TMP, ignore_errors=True)))
os.environ["PARLA_URL"] = "http://127.0.0.1:%d" % _port
os.environ.pop("PARLA_TOKEN", None)

from parla import mcp_server as m  # noqa: E402
import time  # noqa: E402
m.time = time


def errors_of(agent):
    return m.validate_agent(agent)["errors"]


def has(errors, *needles):
    assert any(all(n in e for n in needles) for e in errors), "no encontré %s en %s" % (needles, errors)


# ---------- validación ----------
good = m.validate_agent(m.DEMO_IVR)
assert good == {"ok": True, "errors": [], "warnings": []}, good
assert m.validate_agent(json.dumps(m.DEMO_IVR))["ok"]                      # también como texto JSON
assert m.validate_agent({"parla": 1, "agent": m.DEMO_IVR})["ok"]           # y con el sobre de exportación

bad = copy.deepcopy(m.DEMO_IVR)
bad["intents"].append({"name": "Consultar saldo", "examples": ["hola [x](color)"]})
bad["entities"] += [{"name": "gusto", "kind": "list", "values": []},
                    {"name": "codigo", "kind": "custom", "regex": "([0-9"},
                    {"name": "nombre_libre", "kind": "examples", "regex": "\\w+"},
                    {"name": "raro", "kind": "colores"}]
bad["slots"] += [{"name": "text", "entity": ""}, {"name": "pedido", "entity": "noexiste"}]
bad["flows"] += [
    {"name": "Inicio 2", "trigger": "__start__", "steps": []},
    {"name": "Fantasma", "trigger": "Intent que no existe", "steps": [
        {"type": "mensaje", "text": "hola"},
        {"type": "ask", "slot": "telefono", "text": "¿Tu teléfono?"},
        {"type": "message", "text": "Hola {{ apellido }}, tenés {{ size(nombre) }} letras"},
        {"type": "if", "cond": {"var": "edad", "op": "gt", "value": "18"}, "then": [{"type": "goto", "flow": "Nada"}]},
        {"type": "if", "cond": {"var": "dni", "op": "parecido", "value": "1"}},
        {"type": "set", "slot": "nombre", "mode": "cel", "expr": "nombre +"},
        {"type": "http", "url": "ftp://x", "saves": [{"expr": "body.x", "slot": "zzz"}]},
        {"type": "classify", "classification": "Venta"},
        {"type": "classify"},
    ]},
]
bad["classifications"] = [{"name": "Reclamo", "color": 9}, {"name": "Reclamo"}]
errs = errors_of(bad)
has(errs, "intent «Consultar saldo» está repetido")
has(errs, "[x](color)", "no existe la entidad")
has(errs, "«gusto»", "list", "values")
has(errs, "«codigo»", "regex", "no es válida")
has(errs, "«nombre_libre»", "examples", "no lleva regex")
has(errs, "«raro»", "kind")
has(errs, "slot «text»", "nombre")
has(errs, "slot «pedido»", "noexiste")
has(errs, "más de un flujo", "__start__")
has(errs, "«Fantasma»", "trigger", "Intent que no existe")
has(errs, "(mensaje)", "desconocido")
has(errs, "el slot «telefono» no existe")
has(errs, "{{ apellido }}", "«apellido»")
has(errs, "«edad»", "no es un slot")
has(errs, "el flujo «Nada» no existe")
has(errs, "«op»")
has(errs, "nombre +", "no es CEL válido")
has(errs, "http://")
has(errs, "el slot «zzz» no existe")
has(errs, "(classify)", "«Venta» no existe")
has(errs, "(classify)", "falta «classification»")
has(errs, "classification «Reclamo» está repetido")
has(errs, "«Reclamo»", "color")
assert not any("usa «size»" in e or "usa «nombre»" in e for e in errs), errs   # funciones y slots reales no son errores

warn = m.validate_agent({"name": "x", "intents": [{"name": "Hola", "examples": ["hola"]}], "entities": [], "slots": [], "flows": []})
assert warn["ok"], warn
has(warn["warnings"], "«Hola»", "1 frase")
has(warn["warnings"], "«Hola»", "ningún flujo")
assert m.validate_agent({"name": "vacío"})["errors"], "vacío tiene que ser error (Parla no lo importa)"
assert m.validate(m.PIZZA_SNIPPET)[1] == [], m.validate(m.PIZZA_SNIPPET)[1]
assert m.validate_agent(m.TURNOS_SNIPPET) == {"ok": True, "errors": [], "warnings": []}, m.validate_agent(m.TURNOS_SNIPPET)
assert "Cita agendada" in m.GUIDE and "classify" in m.GUIDE
print("validación: ok (%d errores detectados en el agente roto)" % len(errs))

# ---------- validación de funciones ----------
assert not [w for w in m.validate(m.PIZZA_SNIPPET)[2] if "function" in w], m.validate(m.PIZZA_SNIPPET)[2]
fbad = copy.deepcopy(m.PIZZA_SNIPPET)
fbad["functions"] += [
    {"name": "calcular_total", "code": "def run(inputs):\n    return {}"},
    {"name": "rubi", "language": "ruby", "code": "def run(inputs)\nend"},
    {"name": "sin_slot", "inputs": ["noexiste"], "code": "def run(inputs):\n    return {}"},
    {"name": "rota", "code": "def run(inputs):\n    return {"},
    {"name": "sin_run", "code": "x = 1"},
    {"name": "js_sin_run", "language": "javascript", "code": "const x = 1;"},
    {"name": "vacia", "code": "  "},
    {"name": "lee", "language": "javascript", "inputs": ["gusto"],
     "code": "async function run(inputs) { return {a: inputs.gusto + inputs.cantidad + inputs['otro']}; }"},
    {"name": "lee_py", "inputs": ["gusto"],
     "code": "def run(inputs):\n    return {'a': inputs.get('cantidad'), 'b': inputs['gusto'], 'c': inputs.keys()}"}]
fbad["flows"][0]["steps"] += [{"type": "function", "function": "nope"}, {"type": "function"},
                              {"type": "function", "function": "lee", "saves": [{"expr": "ok +", "slot": "total_ok"},
                                                                                {"expr": "result.a", "slot": "zzz"}]},
                              {"type": "function", "function": "lee_py"}]
r = m.validate_agent(fbad)
ferrs, fwarns = r["errors"], r["warnings"]
has(ferrs, "function «calcular_total» está repetido")
has(ferrs, "«rubi»", "python o javascript")
has(ferrs, "«sin_slot»", "«noexiste» no es un slot")
has(ferrs, "«rota»", "sintaxis", "línea 2")
has(ferrs, "«sin_run»", "no define run")
has(ferrs, "«js_sin_run»", "no define run")
has(ferrs, "«vacia»", "falta «code»")
has(ferrs, "(function)", "«nope» no existe en «functions»")
has(ferrs, "(function)", "falta «function»")
has(ferrs, "(function) saves", "ok +", "no es CEL válido")
has(ferrs, "(function) saves", "el slot «zzz» no existe")
assert not any("«lee»" in e or "«lee_py»" in e for e in ferrs), ferrs
has(fwarns, "«lee»", "«cantidad»", "no está en «inputs»")
has(fwarns, "«lee»", "«otro»", "creá ese slot")
has(fwarns, "«lee_py»", "«cantidad»")
assert not any("«keys»" in w or "«gusto»" in w for w in fwarns), fwarns
has(fwarns, "«rota»", "nunca corre")
print("validación de funciones: ok (%d errores, %d advertencias)" % (len(ferrs), len(fwarns)))

# ---------- validación de lo nuevo: idiomas, botones, conocimiento, system, call/handoff/agent, claves ----------
assert m.validate_agent(m.SOPORTE_SNIPPET) == {"ok": True, "errors": [], "warnings": []}, m.validate_agent(m.SOPORTE_SNIPPET)
assert "secret.CRM_TOKEN" in m.GUIDE and '"type": "agent"' in m.GUIDE and "add_knowledge" in m.GUIDE
nbad = copy.deepcopy(m.SOPORTE_SNIPPET)
nbad["languages"] = ["es", "pt"]
nbad["fallback_translations"] = {"en": ["?"]}
nbad["knowledge"].append({"title": "vacío", "text": "  "})
nbad["system"]["cancelar"] = {"enabled": True}
nbad["system"]["handoff"]["translations"] = {"fr": "Je vous passe..."}
nbad["widget"]["origins"] = ["https://mitienda.com/", "mitienda.com"]
nbad["widget"]["position"] = "arriba"
nbad["slots"].append({"name": "humor", "fill": "magia"})
nbad["ai"]["provider"] = "nube"
nbad["intents"].append({"name": "__cancel__", "examples": ["a", "b", "c"]})
nbad["functions"].append({"name": "con_clave", "inputs": ["plan", "secret.API_KEY", "secret.mal-nombre"],
                          "code": "def run(inputs):\n    return {'k': inputs['secret']['API_KEY'], 'p': inputs['plan']}"})
nbad["flows"].append({"name": "Roto", "trigger": "", "steps": [
    {"type": "message", "text": "Tu clave es {{ secret.CRM_TOKEN }}", "translations": {"en": "hi", "pt": "{{ nada }}"},
     "buttons": [{"label": ""}, {"label": "Sí"}, {"label": "sí"}, {"label": "No", "value": ""}, "x"]},
    {"type": "ask", "slot": "plan", "text": "¿Plan?", "buttons": {"label": "x"}},
    {"type": "call", "flow": "No existe"}, {"type": "call"}, {"type": "call", "flow": "Roto"},
    {"type": "agent", "functions": ["volar"], "slots": ["zzz"], "max_turns": 0},
    {"type": "handoff", "reason": 3},
    {"type": "http", "url": "https://x.com/{{ secret.A }}", "headers": [{"key": "X-Api-Key", "value": "abc123"},
                                                                    {"key": "Authorization", "value": "Bearer {{ secret.B }}"}],
     "body": "{\"k\": \"{{ secret.C }}\"}"},
    {"type": "function", "function": "con_clave"}]})
r = m.validate_agent(nbad)
nerrs, nwarns = r["errors"], r["warnings"]
has(nerrs, "fallback_translations", "«en»", "languages")
has(nerrs, "knowledge #2", "falta «text»")
has(nerrs, "system «cancelar»", "no existe")
has(nerrs, "system «handoff»", "«fr»")
has(nerrs, "widget", "https://mitienda.com/")
has(nerrs, "widget", "«mitienda.com»")
has(nerrs, "widget", "position")
has(nerrs, "slot «humor»", "fill")
has(nerrs, "ai", "provider")
has(nerrs, "intent «__cancel__»", "reservados")
has(nerrs, "«con_clave»", "secret.mal-nombre")
assert not any("«con_clave»" in e and "secret.API_KEY" in e for e in nerrs), nerrs        # entrada secret.X válida
assert not any("«con_clave»" in w and "«secret»" in w for w in nwarns), nwarns            # leer inputs["secret"] no avisa
has(nerrs, "(message) text", "clave", "nunca en lo que ve la persona")
has(nerrs, "(message)", "traducción «en»")
has(nerrs, "(message) translations.pt", "«nada»")
has(nerrs, "(message)", "«label»", "no vacío")
has(nerrs, "(message)", "botón «sí» está repetido")
has(nerrs, "(message)", "botón «No»", "value")
has(nerrs, "(ask)", "«buttons» tiene que ser")
has(nerrs, "(call)", "«No existe» no existe")
has(nerrs, "(call)", "falta «flow»")
has(nerrs, "(call)", "a sí mismo")
has(nerrs, "(agent)", "falta «instructions»")
has(nerrs, "(agent)", "«volar» no existe")
has(nerrs, "(agent) slots", "«zzz» no existe")
has(nerrs, "(agent)", "max_turns")
has(nerrs, "(handoff)", "«reason»")
assert not any("(http)" in e for e in nerrs), nerrs                                          # secret vale en http
has(nwarns, "(http)", "X-Api-Key", "Claves")
has(nwarns, "(agent)", "goal")
assert m.secret_refs(nbad) == {"CRM_TOKEN", "A", "B", "C", "API_KEY", "mal"}, m.secret_refs(nbad)
off = copy.deepcopy(m.SOPORTE_SNIPPET)
off["ai"]["enabled"] = False
offw = m.validate_agent(off)
assert offw["ok"], offw
has(offw["warnings"], "slot «motivo»", "ai.enabled")
has(offw["warnings"], "(agent)", "ai.enabled")
dates = m.validate_agent({"name": "d", "entities": [{"name": "cuando", "kind": "date"}], "slots": [{"name": "cuando", "entity": "cuando"}],
                          "intents": [], "flows": []})
assert dates["ok"] and not any("cuando" in w for w in dates["warnings"]), dates               # date: ni regex ni marcas
src = open(m.__file__, encoding="utf-8").read()
assert not re.search(r'call\("(PUT|DELETE)", "/api/agents/%s/secrets"', src), "el MCP no puede escribir claves"
print("validación de lo nuevo: ok (%d errores, %d advertencias)" % (len(nerrs), len(nwarns)))

# ---------- punta a punta contra Parla ----------
NAME = "zz MCP test " + m.uuid.uuid4().hex[:6]
TEST = {
    "name": NAME, "threshold": 0.5, "fallback": "No entendí.",
    "intents": [{"name": "Pedir turno", "examples": [
        "quiero un turno", "necesito sacar turno", "me das un turno para el [lunes](dia)", "turno para el [martes](dia)",
        "quiero reservar", "sacame un turno"]},
                {"name": "Saludar", "examples": ["hola", "buenas", "buen día", "qué tal"]}],
    "entities": [{"name": "dia", "kind": "list", "values": ["lunes", "martes", "miércoles"],
                  "synonyms": {"miércoles": ["miercoles"]}},
                 {"name": "dni", "kind": "dni"}],
    "classifications": [{"name": "Turno dado", "color": 2, "description": "Se confirmó el turno"}, {"name": "Saludo"}],
    "slots": [{"name": "dia", "entity": "dia"}, {"name": "dni", "entity": "dni"}, {"name": "cliente"}],
    "flows": [{"name": "Inicio", "trigger": "__start__", "steps": [
                  {"type": "if", "cond": {"var": "cliente", "op": "filled"},
                   "then": [{"type": "message", "text": "Hola {{ cliente }}."}], "else": []}]},
              {"name": "Saludo", "trigger": "Saludar", "steps": [{"type": "message", "text": "¡Hola! ¿Querés un turno?"},
                                                                  {"type": "classify", "classification": "Saludo"}]},
              {"name": "Turno", "trigger": "Pedir turno", "steps": [
                  {"type": "ask", "slot": "dia", "text": "¿Qué día?"},
                  {"type": "ask", "slot": "dni", "text": "¿Tu DNI?"},
                  {"type": "message", "text": "Turno el {{ dia }} para {{ dni }}."},
                  {"type": "classify", "classification": "Turno dado"}, {"type": "classify", "classification": "Turno dado"},
                  {"type": "set", "slot": "dia", "mode": "clear"}, {"type": "goto", "flow": "Cierre"}]},
              {"name": "Cierre", "trigger": "", "steps": [{"type": "message", "text": "Gracias."}, {"type": "end"}]}],
}
before = {b["id"] for b in m.list_agents()["bots"]}
created = None
try:
    created = m.create_agent(TEST)
    assert created["slug"].startswith("zz-mcp-test"), created
    assert created["trained"]["phrases"] == 10, created
    stored = m.get_agent(created["slug"])
    assert stored["entities"][1]["regex"] == m.PRESETS["dni"], stored["entities"]   # preset completado

    r = m.test_conversation(NAME, ["quiero un turno", "el domingo", "el miercoles", "30.123.456"], {"cliente": "Ana", "otro": 1})
    t = r["transcript"]
    assert t[0]["bot"] == ["Hola Ana."] and t[0]["ignored_data"] == ["otro"], t[0]
    assert t[1]["intent"] == "Pedir turno" and t[1]["bot"] == ["¿Qué día?"] and t[1]["waiting_for"] == "dia", t[1]
    assert t[2]["answer_to"] == "dia" and t[2]["bot"][0] == "No reconocí ese dato, probemos de nuevo.", t[2]
    assert t[3]["answer_to"] == "dia" and t[3]["entities"][0]["value"] == "miércoles", t[3]
    assert t[4]["bot"] == ["Turno el miércoles para 30.123.456.", "Gracias."], t[4]
    assert t[3]["classifications"] == [] and t[4]["classifications"] == ["Turno dado"], t   # una sola vez
    assert r["classifications"] == ["Turno dado"], r
    assert r["final_slots"] == {"dia": None, "dni": "30.123.456", "cliente": "Ana"}, r["final_slots"]
    assert r["problems"] == [] and r["sessionId"] is None
    assert m.list_sessions(created["id"])["sessions"] == [], "la sesión de prueba tenía que borrarse"

    kept = m.test_conversation(created["id"], ["hola"], keep=True)
    assert kept["transcript"][1]["intent"] == "Saludar" and kept["classifications"] == ["Saludo"], kept
    session = m.get_session(created["id"], kept["sessionId"])
    assert session["channel"] == "mcp" and session["classifications"] == ["Saludo"], session
    assert any(h.get("classification") == "Saludo" for h in session["history"]), session["history"]
    plain = m.test_conversation(created["id"], ["asdf qwerty zxcv"], keep=True)      # sin clasificar
    today = m.time.strftime("%Y-%m-%d")
    by = lambda **f: [x["sessionId"] for x in m.list_sessions(created["id"], **f)["sessions"]]
    assert by(classification="Saludo") == [kept["sessionId"]]
    assert by(classification="__none__") == [plain["sessionId"]]
    assert sorted(by(date_from=today, date_to=today, channel="mcp")) == sorted([kept["sessionId"], plain["sessionId"]])
    assert by(date_to="2000-01-01") == []
    rep = m.get_report(created["slug"], date_from=today, date_to=today)
    assert rep["sessions"] == 2 and rep["unclassified"] == 1, rep
    assert {c["name"]: c["count"] for c in rep["classifications"]} == {"Turno dado": 0, "Saludo": 1}, rep
    assert rep["by_day"] == [{"date": today, "sessions": 2, "unclassified": 1, "counts": {"Saludo": 1}}], rep
    assert m.get_report(created["id"], channel="api")["sessions"] == 0

    changed = copy.deepcopy(TEST)
    changed["fallback"] = "Perdón, no te entendí."
    assert m.update_agent(created["id"], changed)["id"] == created["id"]
    assert m.test_conversation(created["id"], ["asdf qwerty zxcv"])["transcript"][1]["bot"] == ["Perdón, no te entendí."]
    assert m.train_agent(NAME)["phrases"] == 10

    # ---------- versiones y entornos ----------
    agent_id, junk = created["id"], ["asdf qwerty zxcv"]
    fallback = lambda r: r["transcript"][1]["bot"]
    def fails(fn, *args, **kw):
        try:
            fn(*args, **kw)
        except m.ToolError as error:
            return str(error)
        raise AssertionError("%s%s tenía que fallar" % (fn.__name__, args))
    assert m.list_versions(agent_id)["versions"] == []
    assert m.test_conversation(agent_id, junk, environment="production")["version"] is None   # sin versiones: borrador
    assert "confirm=True" in fails(m.publish_agent, agent_id, "primera", environment="production")
    assert "staging" in fails(m.test_conversation, agent_id, junk, environment="staging")       # staging vacío: 400
    v1 = m.publish_agent(agent_id, "primera", environment="production", confirm=True)
    assert v1["version"] == 1 and v1["environments"] == ["production"], v1

    draft = copy.deepcopy(changed)
    draft["fallback"] = "Fallback nuevo."
    m.update_agent(agent_id, draft)
    d = m.test_conversation(agent_id, junk)
    p = m.test_conversation(agent_id, junk, environment="production")
    assert fallback(d) == ["Fallback nuevo."] and d["environment"] == "draft" and d["version"] is None, d
    assert fallback(p) == ["Perdón, no te entendí."] and p["environment"] == "production" and p["version"] == 1, p
    pinned = m.test_conversation(agent_id, ["hola"], keep=True, environment="production")      # empieza en v1

    v2 = m.publish_agent(agent_id, "fallback nuevo", environment="staging")
    assert v2["version"] == 2 and v2["environments"] == ["staging"], v2
    s = m.test_conversation(agent_id, junk, environment="staging")
    assert fallback(s) == ["Fallback nuevo."] and s["version"] == 2, s
    for diff in (m.diff_agent(agent_id), m.diff_agent(agent_id, "production", "2"), m.diff_agent(agent_id, 1, 2)):
        assert diff["changes"] == 1 and diff["settings"] == ["fallback"] and diff["from"] == 1, diff
    assert m.diff_agent(agent_id, "staging")["changes"] == 0

    assert "confirm=True" in fails(m.deploy_version, agent_id, "production", 2)
    assert "production o staging" in fails(m.deploy_version, agent_id, "prod", 2, confirm=True)
    assert m.deploy_version(agent_id, "production", 2, confirm=True) == {"environment": "production", "version": 2, "previous": 1}
    assert fallback(m.test_conversation(agent_id, junk, environment="production")) == ["Fallback nuevo."]
    later = m.call("POST", "/api/v1/bots/%s/events" % agent_id, {"sessionId": pinned["sessionId"], "text": "asdf qwerty"})
    assert later["version"] == 1 and later["messages"] == ["Perdón, no te entendí."], later    # sigue atada a v1
    assert m.call("GET", "/api/v1/bots/" + agent_id)["environments"] == {"production": 2, "staging": 2}

    assert m.deploy_version(agent_id, "production", 1, confirm=True)["previous"] == 2           # rollback
    assert fallback(m.test_conversation(agent_id, junk, environment="production")) == ["Perdón, no te entendí."]
    lv = m.list_versions(agent_id)
    assert [v["version"] for v in lv["versions"]] == [2, 1] and lv["environments"] == {"production": 1, "staging": 2}, lv
    assert lv["deployments"][0] == {**lv["deployments"][0], "environment": "production", "version": 1, "previous": 2}, lv

    assert "confirm=True" in fails(m.restore_version, agent_id, 1)
    assert m.restore_version(agent_id, 1, confirm=True)["restored"] == 1
    assert fallback(m.test_conversation(agent_id, junk)) == ["Perdón, no te entendí."]
    assert m.diff_agent(agent_id)["changes"] == 0
    print("versiones: ok (publicar, staging, diff, deploy con confirm, conversación atada, rollback, restore)")

    for call, args in ((m.create_agent, ({"name": "roto", "flows": [{"name": "f", "trigger": "nada", "steps": []}]},)),
                       (m.get_agent, ("no-existe-este-bot",)), (m.delete_agent, (created["id"],))):
        try:
            call(*args)
            raise AssertionError("%s tenía que fallar" % call.__name__)
        except m.ToolError as error:
            print("  error esperado de %s: %s" % (call.__name__, str(error).splitlines()[0][:110]))
    print("punta a punta: ok (agente %s)" % created["id"])
finally:
    if created:
        m.delete_agent(created["id"], confirm=True)
    after = {b["id"] for b in m.list_agents()["bots"]}
    assert after == before, "quedaron agentes de prueba: %s" % (after - before)

# ---------- funciones punta a punta (agente temporal con el fragmento de pizzería de la guía) ----------
PIZZA = dict(copy.deepcopy(m.PIZZA_SNIPPET), name="zz MCP funciones " + m.uuid.uuid4().hex[:6], threshold=0.3,
             fallback="No entendí.")
pizza = None
try:
    pizza = m.create_agent(PIZZA)
    pid = pizza["id"]
    r = m.test_function(pid, "calcular_total", {"gusto": "muzzarella", "cantidad": "3", "extra": 1})   # por nombre
    assert r["ok"] and r["result"] == {"total": 25650, "promo": True}, r
    assert "total calculado: 25650" in r["logs"] and r["ignored_inputs"] == ["extra"], r
    r = m.test_function(pid, "calcular_total", {"gusto": "muzzarella", "cantidad": "dos"})              # caso borde
    assert not r["ok"] and "ValueError" in r["error"] and r["traceback"], r
    r = m.test_function(pid, {"name": "doble", "language": "python", "inputs": ["cantidad"],
                              "code": "async def run(inputs):\n    return {'cantidad': int(inputs['cantidad']) * 2}"},
                        {"cantidad": "4"})                                                                  # definición
    assert r["ok"] and r["result"] == {"cantidad": 8} and r["sent"] == {"cantidad": "4"}, r
    r = m.test_function(pid, json.dumps({"name": "falla", "code": "def run(inputs):\n    raise RuntimeError('ups')"}), {})
    assert not r["ok"] and "RuntimeError: ups" in r["error"], r
    try:
        m.test_function(pid, "no_existe", {})
        raise AssertionError("test_function con un nombre que no existe tenía que fallar")
    except m.ToolError as error:
        assert "no_existe" in str(error)
    if shutil.which("node"):
        js = m.GUIDE.split("```javascript\n")[1].split("```")[0]          # el ejemplo JS de la guía
        r = m.test_function(pid, {"name": "js", "language": "javascript", "inputs": ["gusto", "cantidad"], "code": js},
                            {"gusto": "napolitana", "cantidad": "3"})
        assert r["ok"] and r["result"] == {"total": 28350, "promo": True}, r
        r = m.test_function(pid, {"name": "js", "language": "javascript", "inputs": ["cantidad"], "code": js}, {})
        assert not r["ok"] and "1 o más" in r["error"], r
        print("  javascript: ok")
    else:
        print("  javascript: sin node, no lo probé")

    c = m.test_conversation(pid, ["quiero 2 pizzas de muzzarella", "Pedro"])
    assert c["problems"] == [] and c["transcript"][-1]["bot"] == ["Listo Pedro: 2 de muzzarella, total $ 19000.",
                                                                  "¡Gracias por elegirnos!"], c["transcript"]
    assert c["final_slots"]["total"] == 19000 and c["final_slots"]["promo"] is False and c["final_slots"]["total_ok"] is True, c
    c = m.test_conversation(pid, ["quiero 3 pizzas de napolitana", "Ana"])
    assert c["transcript"][-1]["bot"][0] == "Listo Ana: 3 de napolitana, total $ 28350 (con 10% off).", c["transcript"]
    c = m.test_conversation(pid, ["quiero 0 pizzas de muzzarella", "Pedro"])                     # error manejado
    last = c["transcript"][-1]
    assert c["problems"] == [] and last["bot"][0].startswith("Uy, no pude calcular el total (ValueError: la cantidad tiene que ser 1 o más)"), last
    assert c["final_slots"]["total_ok"] is False and c["final_slots"]["cantidad"] is None and c["final_slots"]["total"] is None, c
    unhandled = copy.deepcopy(PIZZA)
    unhandled["flows"][0]["steps"][3]["saves"] = []                                               # sin mirar ok/error
    assert unhandled["flows"][0]["steps"][3]["type"] == "function"
    m.update_agent(pid, unhandled)
    c = m.test_conversation(pid, ["quiero 0 pizzas de muzzarella", "Pedro"])
    assert c["problems"] and c["final_slots"]["total"] is None, c                                 # el flujo se corta con ⚠
    print("funciones: ok (test_function por nombre/definición, auto_save en slots, error manejado y sin manejar)")
finally:
    if pizza:
        m.delete_agent(pizza["id"], confirm=True)
    assert {b["id"] for b in m.list_agents()["bots"]} == before, "quedó el agente de prueba de funciones"
# ---------- lo nuevo punta a punta: botones, idiomas, conocimiento, handoff, csat, claves, para enseñar, métricas ----------
class Page(BaseHTTPRequestHandler):
    def do_GET(self):
        body = ("<html><head><title>Envíos y cambios</title></head><body><h1>Envíos</h1><p>Enviamos a todo el país "
                "por correo. El envío tarda entre 2 y 5 días hábiles.</p></body></html>").encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


page = ThreadingHTTPServer(("127.0.0.1", 0), Page)
threading.Thread(target=page.serve_forever, daemon=True).start()
SOP = dict(copy.deepcopy(m.SOPORTE_SNIPPET), name="zz MCP soporte " + m.uuid.uuid4().hex[:6])
SOP["ai"]["enabled"] = False                       # sin Ollama: el resto anda igual y es determinista
sop = None
try:
    sop = m.create_agent(SOP)
    sid_ = sop["id"]
    has(sop["warnings"], "CRM_TOKEN", "Claves")                                   # falta cargar la clave
    names = m.list_secret_names(sid_)
    assert names["secrets"] == [] and names["used"] == ["CRM_TOKEN"] and names["missing"] == ["CRM_TOKEN"], names
    assert "value" not in json.dumps(names), names

    c = m.test_conversation(sid_, ["Mi pedido", "48213", "5"])
    t = c["transcript"]
    assert [b["label"] for b in t[0]["buttons"]] == ["Mi pedido", "Devoluciones", "Planes"] and t[0]["language"] == "es", t[0]
    assert t[1]["intent"] == "Estado del pedido" and t[1]["bot"] == ["¿Cuál es el número de pedido?"], t[1]   # tocó el botón
    assert t[2]["bot"][0] == "El pedido 48213 está en camino: llega en 48 h." and [b["value"] for b in t[2]["buttons"]] == list("12345"), t[2]
    assert t[3]["bot"] == ["¡Gracias por contarme!"] and c["classifications"] == ["Pedido consultado"], t[3]

    pt = m.test_conversation(sid_, [], {"idioma": "pt"})["transcript"][0]
    assert pt["language"] == "pt" and pt["bot"][0].startswith("Olá!") and pt["buttons"][0]["label"] == "Meu pedido", pt

    faq = m.test_conversation(sid_, ["¿Hacen envíos a todo el país?"])["transcript"][1]
    assert faq["via"] == "knowledge" and "2 a 5 días" in faq["bot"][0] and faq["sources"][0]["title"] == "Preguntas frecuentes", faq

    k = m.add_knowledge(sid_, "Horarios del local", text="P: ¿Abren los feriados?\nR: Los feriados abrimos de 10 a 14.")
    assert k["source"] == "texto" and not k["replaced"] and k["documents"] == 2, k
    k2 = m.add_knowledge(sid_, "Horarios del local", text="P: ¿Abren los feriados?\nR: Los feriados abrimos de 10 a 18.")
    assert k2["replaced"] and k2["id"] == k["id"] and k2["documents"] == 2, k2
    s_ = m.search_knowledge(sid_, "¿abren los feriados?")
    assert s_["answers"] and "10 a 18" in s_["results"][0]["text"] and s_["threshold"] == 0.55, s_
    u = m.add_knowledge(sid_, url="http://127.0.0.1:%d/envios" % page.server_address[1])
    assert u["source"] == "url" and u["title"] == "Envíos y cambios" and "todo el país" in u["preview"] and u["documents"] == 3, u
    doc = [d for d in m.get_agent(sid_)["knowledge"] if d["id"] == u["id"]][0]
    assert doc["url"].endswith("/envios") and "2 y 5 días hábiles" in doc["text"], doc
    for bad in ({}, {"text": "x", "url": "https://x"}):
        try:
            m.add_knowledge(sid_, **bad)
            raise AssertionError("add_knowledge %s tenía que fallar" % bad)
        except m.ToolError as error:
            assert "«text» o «url»" in str(error)

    angry = m.test_conversation(sid_, ["quiero hacer un reclamo", "hola?"], keep=True)
    t = angry["transcript"]
    assert t[1]["handoff"] and t[1]["bot"][0].startswith("Lamento lo que pasó") and angry["classifications"] == ["Reclamo derivado"], t[1]
    assert t[2]["bot"] == [] and t[2]["handoff"] and angry["handoff"] is True, t[2]           # el bot se calla
    junk = m.test_conversation(sid_, ["asdf qwerty zxcv", "Mi pedido", "777", "4"], keep=True)
    assert junk["transcript"][1]["bot"][0] in SOP["fallback"], junk["transcript"][1]

    groups = m.list_unrecognized(sid_)["groups"]
    assert any("asdf qwerty zxcv" in g["texts"] for g in groups), groups
    assert m.list_unrecognized(sid_, date_to="2000-01-01")["groups"] == []
    a = m.get_analytics(sid_)
    assert a["sessions"] == 2 and a["handoff"] == 1 and a["contained"] == 1 and a["fallbacks"] >= 1, a
    assert a["csat"]["answered"] == 1 and a["csat"]["average"] == 4, a["csat"]
    assert m.get_analytics(sid_, date_to="2000-01-01")["sessions"] == 0

    tp = m.teach_phrases(sid_, "Reclamo", ["asdf qwerty zxcv", "quiero hacer un reclamo", "  ", "me trataron mal en el local [3](pedido)"])
    assert tp["added"] == ["asdf qwerty zxcv", "me trataron mal en el local [3](pedido)"] and "train_agent" in tp["next"], tp
    assert len(tp["skipped"]) == 2 and tp["total"] == 10, tp
    for args in (("No existe", ["x"]), ("Reclamo", ["[x](color)"])):
        try:
            m.teach_phrases(sid_, *args)
            raise AssertionError("teach_phrases %s tenía que fallar" % (args,))
        except m.ToolError as error:
            assert args[0] in str(error) or "color" in str(error), error
    m.train_agent(sid_)
    assert m.test_conversation(sid_, ["asdf qwerty zxcv"])["transcript"][1]["intent"] == "Reclamo"
    print("lo nuevo punta a punta: ok (botones, pt, conocimiento texto/url, handoff, csat, claves, para enseñar, métricas)")
finally:
    page.shutdown()
    if sop:
        m.delete_agent(sop["id"], confirm=True)
    assert {b["id"] for b in m.list_agents()["bots"]} == before, "quedó el agente de prueba de soporte"
print("todo ok")
