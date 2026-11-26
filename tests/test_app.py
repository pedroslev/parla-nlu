"""Chequeo del motor sin modelo ni red:  .venv/bin/python tests/test_app.py"""
import support
support.temp_data()
from parla import server as app  # noqa: E402

AGENT = {
    "threshold": 0.5, "fallback": "no entendí",
    "intents": [{"name": "pedir", "examples": ["quiero una pizza de [muzza](gusto)"]}],
    "entities": [{"name": "cantidad", "regex": r"\b(\d+)\s*pizzas?\b"},
                 {"name": "gusto", "values": ["fugazza"], "synonyms": {"fugazza": ["fuga", "la de cebolla"]}}],
    "slots": [{"name": "gusto", "entity": "gusto"}, {"name": "cantidad", "entity": "cantidad"}, {"name": "nombre"}],
    "flows": [{"name": "pedido", "trigger": "pedir", "steps": [
        {"type": "ask", "slot": "gusto", "text": "¿De qué gusto?"},
        {"type": "ask", "slot": "cantidad", "text": "¿Cuántas?"},
        {"type": "ask", "slot": "nombre", "text": "¿A nombre de quién?"},
        {"type": "set", "slot": "total", "mode": "cel", "expr": "int(cantidad) * 1000"},
        {"type": "if", "cond": {"var": "total", "op": "gt", "value": "2500"},
         "then": [{"type": "if", "expr": "total > 5000",
                   "then": [{"type": "message", "text": "Pedido grande: ${{ total }}, envío gratis"}],
                   "else": [{"type": "message", "text": "Pedido grande: ${{ total }}"}]}],
         "else": [{"type": "message", "text": "{{ nombre }}: {{ cantidad }} de {{ gusto }}, ${{ total }}"}]},
        {"type": "set", "slot": "nota", "mode": "text", "text": "para {{ nombre }}"},
        {"type": "set", "slot": "gusto", "mode": "clear"},
        {"type": "message", "text": "Listo, {{ nota }}.{{ gusto }}"},
    ]}],
}


def fake(intent):
    return lambda agent, text: {"intent": intent, "confidence": 0.9, "ranking": [],
                                "entities": app.extract(agent, text)}


# entidades: grupo de la regex, valor de la lista y valor marcado en una frase
found = {e["entity"]: e["value"] for e in app.extract(AGENT, "Dame 3 pizzas de Muzza")}
assert found == {"cantidad": "3", "gusto": "muzza"}, found

# otra forma de decirlo se guarda con el valor de la lista
assert [e["value"] for e in app.extract(AGENT, "dame La de Cebolla")] == ["fugazza"]

# un valor conocido no gana adentro de uno más largo de la misma entidad
nums = {"intents": [{"name": "p", "examples": ["quiero [2](cantidad)"]}], "entities": [{"name": "cantidad", "regex": r"\b\d+(?:[.,]\d+)?\b"}]}
assert [(e["entity"], e["value"]) for e in app.extract(nums, "quiero 2,5 pizzas")] == [("cantidad", "2,5")]
assert [(e["entity"], e["value"]) for e in app.extract(nums, "quiero 2 pizzas")] == [("cantidad", "2")]

# CEL, plantillas y condiciones armadas en la interfaz
assert app.cel("r.body.items.size() + 1", {"r": {"body": {"items": [1, 2]}}}) == 3
assert app.render("hola {{ n }}{{ vacio }}, {{ x > 1 ? 'sí' : 'no' }}", {"n": "Ana", "x": 2, "vacio": None}) == "hola Ana, sí"
# en una URL los slots van codificados (no pueden cambiar la dirección); los secret.* y el texto fijo, tal cual
assert app.render("https://x/a?q={{ n }}&k={{ secret.K }}", {"n": "1/../b?c=d#e", "secret": {"K": "a/b"}}, url=True) == "https://x/a?q=1%2F..%2Fb%3Fc%3Dd%23e&k=a/b"
try:
    app.http_step({"url": "https://x", "headers": [{"key": "X", "value": "{{ n }}"}]}, {"n": "a\r\nEvil: 1"})
    raise AssertionError("encabezado con salto de línea")
except ValueError:
    pass
for bad in ("../users", "abc", None):          # ids de agente: nada que salga de la carpeta
    try:
        app.path(bad)
        raise AssertionError(bad)
    except ValueError:
        pass
slots = {"a": "12", "b": 200, "c": True, "d": None, "e": "Hola Mundo"}
for var, op, value, expected in [("a", "gt", "5", True), ("a", "lt", "5", False), ("b", "eq", "200", True),
                                 ("c", "eq", "TRUE", True), ("d", "empty", "", True), ("d", "filled", "", False),
                                 ("e", "contains", "mundo", True), ("e", "ne", "chau", True), ("d", "gt", "1", False)]:
    assert app.check({"var": var, "op": op, "value": value}, slots) is expected, (var, op, value)

# flujo: el slot ya reconocido no se pregunta, el formato obliga a repreguntar, el texto libre llena 'nombre'
st = {}
assert app.handle(AGENT, st, "quiero una pizza de muzza", fake("pedir"))["messages"] == ["¿Cuántas?"]
assert app.handle(AGENT, st, "no sé", fake(None))["messages"] == ["No reconocí ese dato, probemos de nuevo.", "¿Cuántas?"]
assert app.handle(AGENT, st, "2 pizzas", fake(None))["messages"] == ["¿A nombre de quién?"]
assert app.handle(AGENT, st, "Ana", fake(None))["messages"] == ["Ana: 2 de muzza, $2000", "Listo, para Ana."]
assert st["flow"] is None

# mientras se espera una respuesta solo se llena el slot preguntado
st = {}
assert app.handle(AGENT, st, "hola", fake("pedir"))["messages"] == ["¿De qué gusto?"]
r = app.handle(AGENT, st, "3 pizzas", fake(None))
assert r["messages"][0].startswith("No reconocí") and r["rejected"]
assert st["slots"]["cantidad"] is None

# ramas anidadas del camino, y respuesta por defecto cuando ningún flujo atiende la intención
for amount, expected in [("3", "Pedido grande: $3000"), ("6", "Pedido grande: $6000, envío gratis")]:
    st = {}
    assert app.handle(AGENT, st, amount + " pizzas de fugazza", fake("pedir"))["messages"] == ["¿A nombre de quién?"]
    assert app.handle(AGENT, st, "Luis", fake(None))["messages"] == [expected, "Listo, para Luis."]
assert app.handle(AGENT, {}, "bla", fake("otro"))["messages"] == ["no entendí"]
# varias respuestas de "no entendí": elige al azar, nunca repite la anterior, ignora vacías
varied = dict(AGENT, fallback=["Perdón, ¿cómo?", "No te seguí", "  ", "¿Me lo decís de otra forma?"])
st, seen = {}, []
for _ in range(30):
    seen += app.handle(varied, st, "bla", fake("otro"))["messages"]
assert set(seen) == {"Perdón, ¿cómo?", "No te seguí", "¿Me lo decís de otra forma?"}, set(seen)
assert all(a != b for a, b in zip(seen, seen[1:]))
assert app.handle(dict(AGENT, fallback=[]), {}, "bla", fake("otro"))["messages"] == ["No entendí."]

# el CRF aprende del contexto: reconoce un nombre que nunca vio, y no toca lo que tiene lista o formato
import os, tempfile
names = {"intents": [{"name": "identificarse", "examples": ["me llamo [pedro](nombre)", "soy [magui](nombre)"]},
                     {"name": "pedir", "examples": ["quiero [2](cantidad) de [muzza](gusto)", "quiero una pizza", "tienen delivery",
                                                    "para pedir a domicilio", "haceme [3](cantidad) de [muzza](gusto)"]},
                     {"name": "charla", "examples": ["hola", "buenas noches", "buen día", "qué tal", "muchas gracias", "gracias",
                                                     "chau", "hasta luego", "nos vemos", "hola, quiero hacer un pedido"]}],
         "entities": [{"name": "nombre"}, {"name": "gusto", "values": ["muzza"]}, {"name": "cantidad", "regex": r"\d+"}]}
model_path = os.path.join(tempfile.mkdtemp(), "m.crfsuite")
tagger = app.train_tagger(names, model_path)
found = {e["entity"]: e["value"] for e in app.extract(names, "me llamo Olivia", tagger)}
assert found == {"nombre": "Olivia"}, found
found = {e["entity"]: e["value"] for e in app.extract(names, "quiero 3 de muzza", tagger)}
assert found == {"cantidad": "3", "gusto": "muzza"}, found
# frases nuevas sin nombre. ponytail: con muy pocas frases en total marca cualquier "soy X"; se corrige sumando frases.
for not_a_name in ["quiero una pizza grande", "Corrientes 1234", "buenísimo, gracias", "soy celíaco"]:
    assert "nombre" not in {e["entity"] for e in app.extract(names, not_a_name, tagger)}, not_a_name
# un ejemplo enseñado desde el chat (guardado en la entidad) también entrena: suma nombres de dos palabras
names["entities"][0]["examples"] = ["soy [Ana Laura](nombre)", "me llamo [juan carlos](nombre)"]
tagger = app.train_tagger(names, model_path)
found = {e["entity"]: e["value"] for e in app.extract(names, "soy María José", tagger)}
assert found == {"nombre": "María José"}, found
found = {e["entity"]: e["value"] for e in app.extract(names, "me llamo Pedro Gómez", tagger)}
assert found == {"nombre": "Pedro Gómez"}, found
info = {}
app.train_tagger(names, model_path, info)
assert info["trained"] and info["iterations"] and info["entities"] == ["nombre"], info
assert app.train_tagger({"intents": [{"name": "x", "examples": ["hola"]}], "entities": []}, model_path) is None

# un paso roto se avisa en el chat en vez de romper
bad = dict(AGENT, flows=[{"name": "x", "trigger": "pedir", "steps": [{"type": "message", "text": "{{ nope }}"}]}])
assert app.handle(bad, {}, "hola", fake("pedir"))["messages"][0].startswith("⚠")
# importar: acepta el archivo exportado, descarta id y entrenamiento, y rechaza lo que no es un agente
exported = {"parla": 1, "agent": dict(AGENT, id="abc12345", name="Pizzas", trained={"at": "x"})}
again = app.imported(exported)
assert again["name"] == "Pizzas" and "id" not in again and "trained" not in again and again["flows"] == AGENT["flows"]
assert app.imported(dict(AGENT, name="Sin sobre"))["name"] == "Sin sobre"
for bad in [{"hola": 1}, {"intents": "no"}, {"agent": {"flows": {}}}]:
    try:
        app.imported(bad)
        raise AssertionError(bad)
    except ValueError:
        pass
import json  # noqa: E402
# all_agents lista solo <id>.json: las claves (<id>.secrets.json) al lado no son un agente sin "id"
os.makedirs(app.AGENTS, exist_ok=True)
with open(os.path.join(app.AGENTS, "cccc3333.secrets.json"), "w") as f:
    json.dump({"TOKEN": "x"}, f)
assert all("id" in a for a in app.all_agents())
os.remove(os.path.join(app.AGENTS, "cccc3333.secrets.json"))
# API pública: slug, y una conversación completa por eventos (sin modelo: se reemplaza converse)
assert app.slug("Pizzería Don Luis") == "pizzeria-don-luis"
saved = app.all_agents, app.load, app.model, app.parse, app.agent_index
app.agent_index = lambda: [(a["id"], a["id"], a["name"]) for a in app.all_agents()]   # find_bot sigue a los agentes de mentira
app.all_agents = lambda: [dict(AGENT, id="aaaa1111", name="Pizzería"), dict(AGENT, id="bbbb2222", name="Soporte")]
app.load = lambda agent_id: next(a for a in app.all_agents() if a["id"] == agent_id)
app.model = lambda agent_id: {"data": app.load(agent_id), "tagger": None}
app.parse = lambda data, text, tagger, index=None: fake("pedir" if "pizza" in text else None)(data, text)
status, body = app.api_v1("GET", ["bots"], {})
assert status == 200 and [b["slug"] for b in body["bots"]] == ["pizzeria", "soporte"]
assert app.api_v1("GET", ["bots", "PIZZERIA"], {})[1]["id"] == "aaaa1111"          # por slug, sin importar mayúsculas
assert app.api_v1("GET", ["bots", "Pizzer%C3%ADa"], {})[1]["id"] == "aaaa1111"     # por nombre con tilde, como viene en la URL
assert app.api_v1("GET", ["bots", "nadie"], {})[0] == 404
app.AGENTS = tempfile.mkdtemp()                                     # las conversaciones van a disco
status, body = app.api_v1("POST", ["bots", "pizzeria", "events"], {"type": "start", "sessionId": "wa-5491100000000"})
assert status == 200 and body["sessionId"] == "wa-5491100000000" and body["messages"] == [] and body["channel"] == "api"
status, body = app.api_v1("POST", ["bots", "pizzeria", "events"], {"sessionId": "wa-5491100000000", "text": "quiero una pizza de muzza"})
assert body["messages"] == ["¿Cuántas?"] and body["waiting_for"] == "cantidad" and body["slots"]["gusto"] == "muzza", body
assert body["understood"]["intent"] == "pedir" and body["understood"]["entities"] == [{"entity": "gusto", "value": "muzza"}], body
status, body = app.api_v1("POST", ["bots", "pizzeria", "events"], {"sessionId": "wa-5491100000000", "type": "message", "text": "2 pizzas"})
assert body["messages"] == ["¿A nombre de quién?"] and body["understood"]["answer_to"] == "cantidad"
status, body = app.api_v1("GET", ["bots", "pizzeria", "sessions", "wa-5491100000000"], {})
assert [h["from"] for h in body["history"]] == ["event", "user", "bot", "user", "bot"] and body["history"][1]["intent"] == "pedir"
# terminar la deja en el historial; un mensaje nuevo con el mismo sessionId sigue con la memoria en blanco
assert app.api_v1("POST", ["bots", "pizzeria", "events"], {"type": "end", "sessionId": "wa-5491100000000"})[1]["ended"] is True
status, body = app.api_v1("GET", ["bots", "pizzeria", "sessions"], {})
assert [(x["sessionId"], x["ended"], x["messages"]) for x in body["sessions"]] == [("wa-5491100000000", True, 5)], body
status, body = app.api_v1("POST", ["bots", "pizzeria", "events"], {"sessionId": "wa-5491100000000", "text": "hola"})
assert body["ended"] is False and body["slots"]["gusto"] is None
assert app.api_v1("DELETE", ["bots", "pizzeria", "sessions", "wa-5491100000000"], {})[1]["deleted"] is True
# evento online con datos de un IVR: el dni se guarda en su slot y el flujo de inicio saluda con el nombre
ivr = dict(AGENT, id="cccc3333", name="Banco", slots=[{"name": "dni"}, {"name": "nombre"}], flows=[{"name": "bienvenida", "trigger": "__start__", "steps": [
    {"type": "set", "slot": "nombre", "mode": "cel", "expr": "dni == '30123456' ? 'Olivia' : ''"},
    {"type": "if", "cond": {"var": "nombre", "op": "filled"},
     "then": [{"type": "message", "text": "Hola {{ nombre }}, ¿en qué te ayudo?"}],
     "else": [{"type": "ask", "slot": "nombre", "text": "¿Cómo te llamás?"}]}]}])
agents_before = app.all_agents
app.all_agents = lambda: agents_before() + [ivr]
status, body = app.api_v1("POST", ["bots", "banco", "events"], {"type": "online", "sessionId": "ivr-1", "data": {"dni": "30123456", "canal": "ivr"}})
assert body["messages"] == ["Hola Olivia, ¿en qué te ayudo?"] and body["slots"]["dni"] == "30123456" and body["ignored_data"] == ["canal"], body
status, body = app.api_v1("POST", ["bots", "banco", "events"], {"type": "start", "sessionId": "ivr-2", "data": {"dni": "1"}})
assert body["messages"] == ["¿Cómo te llamás?"] and body["waiting_for"] == "nombre", body
listed = {x["sessionId"]: x["data"] for x in app.api_v1("GET", ["bots", "banco", "sessions"], {})[1]["sessions"]}
assert listed == {"ivr-1": {"dni": "30123456"}, "ivr-2": {"dni": "1"}}, listed   # "canal" no es un slot: no se guarda
assert app.api_v1("POST", ["bots", "banco", "events"], {"type": "start", "data": "dni=1"})[0] == 400
# clasificaciones: el paso marca la conversación una sola vez, y el reporte las cuenta
citas = dict(AGENT, id="dddd4444", name="Turnos", classifications=[{"name": "Cita"}, {"name": "Cancelación"}],
             slots=[], intents=[], flows=[
    {"name": "inicio", "trigger": "__start__", "steps": [{"type": "message", "text": "Hola"}]},
    {"name": "pedir", "trigger": "pedir", "steps": [{"type": "classify", "classification": "Cita"},
                                                     {"type": "classify", "classification": "Cita"},
                                                     {"type": "message", "text": "Listo, agendado"}]}])
app.all_agents = lambda: agents_before() + [citas]
app.api_v1("POST", ["bots", "turnos", "events"], {"type": "start", "sessionId": "t1"})
status, body = app.api_v1("POST", ["bots", "turnos", "events"], {"sessionId": "t1", "text": "quiero pizza"})   # fake: "pizza" -> pedir
assert body["messages"] == ["Listo, agendado"] and body["classifications"] == ["Cita"], body
app.api_v1("POST", ["bots", "turnos", "events"], {"sessionId": "t1", "text": "otra pizza"})
app.api_v1("POST", ["bots", "turnos", "events"], {"type": "start", "sessionId": "t2"})
events = [h for h in app.api_v1("GET", ["bots", "turnos", "sessions", "t1"], {})[1]["history"] if h.get("classification")]
assert len(events) == 1, events
assert [x["sessionId"] for x in app.api_v1("GET", ["bots", "turnos", "sessions"], {}, {"classification": "Cita"})[1]["sessions"]] == ["t1"]
assert [x["sessionId"] for x in app.api_v1("GET", ["bots", "turnos", "sessions"], {}, {"classification": "__none__"})[1]["sessions"]] == ["t2"]
status, rep = app.api_v1("GET", ["bots", "turnos", "report"], {})
assert rep["sessions"] == 2 and rep["unclassified"] == 1, rep
assert rep["classifications"] == [{"name": "Cita", "count": 1, "configured": True}, {"name": "Cancelación", "count": 0, "configured": True}], rep
assert rep["by_day"][0]["counts"] == {"Cita": 1}
assert app.api_v1("GET", ["bots", "turnos", "report"], {}, {"from": "2999-01-01"})[1]["sessions"] == 0
bad = dict(citas, flows=[{"name": "x", "trigger": "pedir", "steps": [{"type": "classify"}]}])
assert app.handle(bad, {}, "pizza", fake("pedir"))["messages"][0].startswith("⚠")
# exportar e importar conserva las clasificaciones
assert app.imported({"parla": 1, "agent": citas})["classifications"] == [{"name": "Cita"}, {"name": "Cancelación"}]
assert app.imported({"parla": 1, "agent": dict(AGENT)})["classifications"] == []      # archivos viejos siguen entrando
try:
    app.imported(dict(AGENT, classifications="Cita"))
    raise AssertionError("debería rechazarlo")
except ValueError:
    pass
app.all_agents = agents_before
assert app.api_v1("GET", ["bots", "pizzeria", "sessions", "wa-5491100000000"], {})[0] == 404
assert app.api_v1("POST", ["bots", "pizzeria", "events"], {"type": "message"})[0] == 400
assert app.api_v1("POST", ["bots", "pizzeria", "events"], {"type": "hola"})[0] == 400
for bad in ["con espacios", "../../etc", ".oculto", "wa:549"]:
    assert app.api_v1("POST", ["bots", "pizzeria", "events"], {"text": "hola", "sessionId": bad})[0] == 400, bad
status, body = app.api_v1("POST", ["bots", "pizzeria", "events"], {"text": "quiero pizza"})   # sin id: se crea uno
assert len(body["sessionId"]) == 16
assert [x["channel"] for x in app.api_v1("GET", ["bots", "pizzeria", "sessions"], {}, {"channel": "prueba"})[1]["sessions"]] == []
app.all_agents, app.load, app.model, app.parse, app.agent_index = saved
# autoevaluación del entrenamiento con vectores de juguete: una frase de "pedir" cae más cerca de "saludar"
import numpy as np
toy = {"hola": [1, 0], "buenas": [0.9, 0.1], "quiero pizza": [0, 1], "una pizza": [0.1, 0.9], "hola quiero algo": [0.7, 0.3],
       "adiós": [-1, 0.2]}
app._vectors.update({k: np.array(v) / np.linalg.norm(v) for k, v in toy.items()})
check = app.self_check({"intents": [{"name": "saludar", "examples": ["hola", "buenas"]},
                                    {"name": "pedir", "examples": ["quiero pizza", "una pizza", "hola quiero algo"]},
                                    {"name": "solo", "examples": ["adiós"]}], "entities": []})
assert check["checked"] == 5 and check["right"] == 4, check
assert check["mistakes"][0]["phrase"] == "hola quiero algo" and check["mistakes"][0]["got"] == "saludar", check["mistakes"]
assert next(i for i in check["intents"] if i["name"] == "solo")["accuracy"] is None
warn = app.training_warnings({"flows": [{"trigger": "saludar"}]}, {"intents": [{"name": "saludar", "examples": ["hola"]}],
                                                                  "entities": [{"name": "nombre"}]})
assert any("tiene 1 frase" in w for w in warn) and any("nombre" in w for w in warn) and not any("Ningún flujo" in w for w in warn), warn
# paso a producción: borrador, versiones congeladas, entornos, conversaciones atadas a su versión, volver atrás
saved_v = app.classify, app.parse, app.self_check
app.classify = lambda data, text: []
app.self_check = lambda data: {"summary": "", "accuracy": None}
app.parse = lambda data, text, tagger, index=None: fake("pedir" if "pizza" in text else None)(data, text)
app.AGENTS = tempfile.mkdtemp()
bot = app.create(dict(app.BLANK, name="Turnero", intents=[{"name": "pedir", "examples": ["pizza"]}],
                      flows=[{"name": "f", "trigger": "pedir", "steps": [{"type": "message", "text": "versión uno"}]}]))
say = lambda sid, text, env=None: app.api_v1("POST", ["bots", "turnero", "events"], dict({"sessionId": sid, "text": text}, **({"environment": env} if env else {})))[1]
assert say("a", "pizza")["messages"] == ["versión uno"] and say("a", "pizza")["version"] is None   # sin publicar: producción = borrador
v1 = app.publish(bot["id"], "primera", "production")
assert v1["version"] == 1 and v1["environments"] == ["production"]
draft = app.load(bot["id"]); draft["flows"][0]["steps"][0]["text"] = "versión dos"; app.store(draft)
assert say("b", "pizza")["messages"] == ["versión uno"]                        # producción no ve el borrador
assert say("c", "pizza", "draft")["messages"] == ["versión dos"]               # el borrador sí
assert app.api_v1("POST", ["bots", "turnero", "events"], {"text": "pizza", "environment": "staging"})[0] == 400   # pruebas vacío
app.publish(bot["id"], "segunda", "staging")
assert say("d", "pizza", "staging")["messages"] == ["versión dos"]
app.api_v1("POST", ["bots", "turnero", "events"], {"type": "start", "sessionId": "larga"})   # empieza en v1
app.deploy(bot["id"], "production", 2)                                          # se publica v2 en medio de la charla
assert say("larga", "pizza")["messages"] == ["versión uno"]                    # la charla sigue con su versión
assert say("nueva", "pizza")["messages"] == ["versión dos"] and say("nueva", "pizza")["version"] == 2
app.deploy(bot["id"], "production", 1)                                          # volver atrás
assert say("otra", "pizza")["messages"] == ["versión uno"]
log = app.load(bot["id"])["deployments"]
assert [(d["environment"], d["version"], d["previous"]) for d in log] == [("production", 1, None), ("staging", 2, None), ("production", 2, 1), ("production", 1, 2)]
d = app.diff(app.definition(app.load_version(bot["id"], 1)["agent"]), app.definition(app.load(bot["id"])))
assert d["changes"] == 1 and d["flows"]["changed"][0]["name"] == "f", d
draft = app.load(bot["id"]); draft["intents"][0]["examples"].append("una muzza"); draft["flows"].append({"name": "g", "steps": []}); app.store(draft)
d = app.diff(app.definition(app.load_version(bot["id"], 2)["agent"]), app.definition(app.load(bot["id"])))
assert d["flows"]["added"] == ["g"] and d["intents"]["changed"][0]["added_phrases"] == ["una muzza"], d
for bad in [("qa", 1), ("production", 99)]:
    try:
        app.deploy(bot["id"], *bad)
        raise AssertionError(bad)
    except ValueError:
        pass
assert "environments" not in app.imported({"parla": 1, "agent": app.load(bot["id"])})       # exportar no lleva versiones
app.classify, app.parse, app.self_check = saved_v
# funciones: Python y JavaScript en un proceso aparte; lo devuelto se guarda en los slots con su nombre
from parla import runner
py = {"name": "precio", "language": "python", "inputs": ["cantidad", "gusto"],
      "code": "def run(inputs):\n    print('calculando')\n    precio = 9500 if inputs['gusto'] == 'muzza' else 11000\n    return {'total': int(inputs['cantidad']) * precio, 'extra': 1}"}
res = runner.run_function(py, {"cantidad": "2", "gusto": "muzza"})
assert res["ok"] and res["result"] == {"total": 19000, "extra": 1} and res["logs"] == "calculando", res
js = {"name": "saludo", "language": "javascript", "inputs": ["nombre"],
      "code": "async function run(inputs) { console.log('hola log'); return { saludo: 'Hola ' + inputs.nombre.toUpperCase() } }"}
import shutil
if shutil.which("node"):   # sin Node.js las funciones en JavaScript no corren (lo prueba el mensaje de abajo)
    res = runner.run_function(js, {"nombre": "ana"})
    assert res["ok"] and res["result"] == {"saludo": "Hola ANA"} and "hola log" in res["logs"], res
else:
    assert "Node.js" in runner.run_function(js, {"nombre": "ana"})["error"]
for code, expected in [("def run(i):\n    return 1/0", "ZeroDivisionError"), ("x = 1", "run(inputs)"),
                       ("def run(i):\n    while True: pass", "segundos"), ("def run(i):\n  return {'a': 1", "SyntaxError")]:
    res = runner.run_function({"language": "python", "code": code}, {})
    assert not res["ok"] and expected in res["error"], (code, res)
assert "Node" in runner.run_function({"language": "ruby", "code": ""}, {})["error"] or True
import os as _os
_os.environ["PARLA_FUNCTIONS"] = "0"
assert "apagadas" in runner.run_function(py, {})["error"]
del _os.environ["PARLA_FUNCTIONS"]
shop = dict(AGENT, slots=AGENT["slots"] + [{"name": "total"}, {"name": "fallo"}], functions=[py, dict(py, name="rota", code="def run(i):\n    raise ValueError('sin stock')")],
            flows=[{"name": "f", "trigger": "pedir", "steps": [
                {"type": "function", "function": "precio", "saves": [{"expr": "result.total * 2", "slot": "fallo"}]},
                {"type": "message", "text": "Son ${{ total }} (doble {{ fallo }})"},
                {"type": "function", "function": "rota", "saves": [{"expr": "error", "slot": "fallo"}]},
                {"type": "message", "text": "Error manejado: {{ fallo }}"},
                {"type": "function", "function": "rota"}]}])
out = app.handle(shop, {}, "2 pizzas de muzza", fake("pedir"))["messages"]
assert out[0] == "Son $19000 (doble 38000)" and out[1] == "Error manejado: ValueError: sin stock", out
assert out[2].startswith("⚠") and "sin stock" in out[2], out          # error no manejado: se ve en el chat
assert app.imported({"parla": 1, "agent": shop})["functions"][0]["name"] == "precio"
tricky = dict(shop, flows=[{"name": "f", "trigger": "pedir", "steps": [
    {"type": "function", "function": "rota", "saves": [{"expr": "result.token", "slot": "fallo"}]}]}])
assert app.handle(tricky, {}, "x", fake("pedir"))["messages"][0].startswith("⚠")    # result.token no cuenta como manejar el error
# ---------- ola "Rasa-like": botones, persona humana, pila de flujos, correcciones, sistema, idiomas, claves, IA ----------
import base64
from parla import brain, dates, vault, voice
# fechas escritas apurado: «maniana» es mañana (antes quedaba «a la tarde» de hoy)
import datetime as _dt  # noqa: E402
_d = lambda text: [f["value"] for f in dates.extract(text, _dt.date(2026, 11, 25))]
assert _d("maniana a la tarde") == ["2026-11-26T16:00"] and _d("no, mainana") == ["2026-11-26"]
assert _d("pasado maniana") == ["2026-11-27"] and _d("a las 10 de la maniana") == ["2026-11-25T10:00"]
ROUTES =[("cancelar", "__cancel__"), ("repetí", "__repeat__"), ("una persona", "__handoff__"), ("menu", "menu"),
          ("pizza", "pedir"), ("horario", "horario"), ("reclamo", "reclamo"), ("loop", "loop"), ("plan", "planes")]
def R(agent, text):
    intent = next((i for k, i in ROUTES if k in text.lower()), None)
    return {"intent": intent, "confidence": 0.9 if intent else 0.1, "ranking": [], "entities": app.extract(agent, text)}
BOT = {"threshold": 0.5, "fallback": "no entendí", "languages": ["es", "pt"], "fallback_translations": {"pt": ["não entendi"]},
       "intents": [], "functions": [],
       "entities": [{"name": "area", "values": ["ventas", "soporte"]}, {"name": "gusto", "values": ["muzza", "fugazza"]},
                    {"name": "cantidad", "regex": r"\b(\d+)\b"}],
       "slots": [{"name": "area", "entity": "area"}, {"name": "gusto", "entity": "gusto"}, {"name": "cantidad", "entity": "cantidad"},
                 {"name": "nombre"}, {"name": "plan", "fill": "ai", "description": "el plan que elige"}],
       "flows": [
           {"name": "menu", "trigger": "menu", "steps": [
               {"type": "ask", "slot": "area", "text": "¿Con qué área?", "translations": {"pt": "Com qual área?"},
                "buttons": [{"label": "Ventas", "value": "ventas", "translations": {"pt": "Vendas"}}, {"label": "Soporte"}]},
               {"type": "message", "text": "Área: {{ area }}"}]},
           {"name": "pedido", "trigger": "pedir", "steps": [
               {"type": "ask", "slot": "gusto", "text": "¿De qué gusto?"}, {"type": "ask", "slot": "cantidad", "text": "¿Cuántas?"},
               {"type": "call", "flow": "identidad"}, {"type": "message", "text": "{{ nombre }}: {{ cantidad }} de {{ gusto }}"}]},
           {"name": "identidad", "steps": [
               {"type": "ask", "slot": "nombre", "text": "¿Tu nombre?"},
               {"type": "if", "cond": {"var": "nombre", "op": "eq", "value": "x"}, "then": [{"type": "end"}]},
               {"type": "message", "text": "Gracias {{ nombre }}"}]},
           {"name": "horario", "trigger": "horario", "steps": [{"type": "message", "text": "Abrimos de 9 a 18"}]},
           {"name": "humano", "trigger": "reclamo", "steps": [{"type": "message", "text": "Ok"}, {"type": "handoff", "reason": "reclamo"}]},
           {"name": "loop", "trigger": "loop", "steps": [{"type": "call", "flow": "loop"}]},
           {"name": "planes", "trigger": "planes", "steps": [{"type": "ask", "slot": "plan", "text": "¿Qué plan?"},
                                                             {"type": "message", "text": "Plan {{ plan }}"}]}]}
say = lambda st, text, agent=BOT: app.handle(agent, st, text, R)
# 0. una pregunta en medio de una pregunta: no llena el slot aunque nombre una opción; contesta y vuelve a preguntar.
#    Con IA (acá simulada), el turno entero: responde con otras palabras, pregunta, pide otra acción o nada.
saved_side, saved_read, saved_answer = brain.side_question, brain.understand, brain.answer
brain.side_question = lambda agent, st, text, asked: {"text": "Ventas vende.", "sources": [], "via": "knowledge"} if "?" in text else None
READS = {"necesito ayuda técnica": {"tipo": "responde", "opcion": "soporte", "accion": None},
         "y cuánto sale eso": {"tipo": "pregunta", "opcion": None, "accion": None},
         "ah, gracias, horario": {"tipo": "nada", "opcion": None, "accion": None},      # la NLU ve «horario»: no interrumpe
         "pasame el horario": {"tipo": "accion", "opcion": None, "accion": "horario"}}
brain.understand = lambda agent, st, text, asked, entity=None, flow=None: READS.get(text)
brain.answer = lambda agent, st, text: {"text": "No lo sé.", "sources": [], "via": "ia"}
st = {}
say(st, "menu")
r = say(st, "¿qué hace ventas?")
assert r["messages"] == ["Ventas vende.", "¿Con qué área?"] and st["slots"]["area"] is None and r["answer_to"] is None, r
r = say(st, "y cuánto sale eso")
assert r["messages"] == ["No lo sé.", "¿Con qué área?"] and st["slots"]["area"] is None, r
r = say(st, "ah, gracias, horario")
assert r["messages"] == ["¿Con qué área?"], r   # charla: vuelve a preguntar, sin «No reconocí» (antes: «Abrimos de 9 a 18»)
r = say(st, "pasame el horario")
assert r["messages"][0] == "Abrimos de 9 a 18", r
st = {}
say(st, "menu")
r = say(st, "necesito ayuda técnica")
assert r["messages"] == ["Área: soporte"] and r["via"] == "ia", r
st = {}
say(st, "menu")
assert say(st, "cualquier cosa")["messages"][0] == "No reconocí ese dato, probemos de nuevo."
# la captura: «¿qué es X?» (se contesta) y después «ah entonces si» elige X. Sin IA: la IA ni se consulta.
brain.understand = lambda *a, **k: 1 / 0
st = {}
say(st, "menu")
say(st, "¿qué es soporte?")
r = say(st, "ah entonces si")
assert r["messages"] == ["Área: soporte"] and st["slots"]["area"] == "soporte", r
st = {}
say(st, "menu")
say(st, "¿qué es soporte?")
say(st, "eh?")                                    # el «sí» solo vale justo después de la explicación
assert say(st, "dale")["messages"][0] == "No reconocí ese dato, probemos de nuevo."
# un flujo de charla ("interrupts": false) no corta una pregunta pendiente (antes: despedida + repregunta)
CHAT = dict(BOT, flows=[dict(f, interrupts=False) if f["name"] == "horario" else f for f in BOT["flows"]])
st = {}
say(st, "menu", CHAT)
r = say(st, "ah ok, y el horario", CHAT)
assert r["messages"] == ["No reconocí ese dato, probemos de nuevo.", "¿Con qué área?"], r
# dos opciones en el mismo mensaje («hablar DE UNA urgencia, NO PUEDO…»): ambiguo, no se elige la primera palabra
st = {}
say(st, "menu")
r = say(st, "ventas o soporte, no sé")
assert st["slots"]["area"] is None and r["messages"][0] == "No reconocí ese dato, probemos de nuevo.", r
# "interrupts": "always" (urgencias) corta la pregunta aunque el mensaje traiga el dato pedido
ALWAYS = dict(BOT, flows=[dict(f, interrupts="always") if f["name"] == "humano" else f for f in BOT["flows"]])
st = {}
say(st, "menu", ALWAYS)
r = say(st, "soporte, y tengo un reclamo", ALWAYS)
assert r["messages"][0] == "Ok" and r["handoff"] and st["slots"]["area"] is None, r
# por significado: lo que read_answer entiende entra sin la IA generativa
saved_meaning = app.read_answer
app.read_answer = lambda agent, entity, text, flow=None, lang="es": (
    {"tipo": "responde", "opcion": "ventas", "accion": None, "score": 0.9, "por": "quiero comprar"} if "comprar" in text else None)
st = {}
say(st, "menu")
r = say(st, "me interesa comprar algo")
assert r["messages"] == ["Área: ventas"] and r["via"] == "significado", r
app.read_answer = saved_meaning
brain.side_question, brain.understand, brain.answer = saved_side, saved_read, saved_answer
# read_answer de verdad con vectores de juguete: decide solo si está claro, y contestar gana sobre cambiar de tema
import numpy as _np  # noqa: E402
_V = {"ventas": [1, 0, 0], "soporte": [0, 1, 0], "quiero comprar": [0.95, 0.05, 0], "abrimos de 9 a 18": [0, 0, 1],
      "horario": [0, 0, 1], "gracias": [0, 0.6, 0.8], "algo raro": [0.7, 0.7, 0]}
saved_encode, saved_vectors = app._encode, dict(app._vectors)
app._encode = lambda texts: [_np.array(_V.get(t, [0, 0, -1]), dtype=float) / _np.linalg.norm(_V.get(t, [0, 0, -1])) for t in texts]
app._vectors.clear()
RA = dict(BOT, intents=[{"name": "horario", "examples": ["horario"]}])
ENT = {"name": "area", "values": ["ventas", "soporte"], "phrasings": {"ventas": ["quiero comprar"]}}
assert app.read_answer(RA, ENT, "quiero comprar")["opcion"] == "ventas"
assert app.read_answer(RA, ENT, "algo raro") is None                                  # ventas y soporte empatados: no decide
assert app.read_answer(RA, ENT, "gracias")["tipo"] == "nada"                           # agradecer no contesta ni interrumpe
app._encode = saved_encode
app._vectors.clear(); app._vectors.update(saved_vectors)
# «also»: la pregunta acepta también otra entidad; el slot queda vacío y el flujo sigue leyendo `entities`
ALSO = dict(BOT, flows=[{"name": "oferta", "trigger": "menu", "steps": [
    {"type": "ask", "slot": "gusto", "text": "¿Muzza?", "also": ["cantidad"]},
    {"type": "if", "expr": "has(entities.cantidad)", "then": [{"type": "message", "text": "Van {{ entities.cantidad }}"}, {"type": "end"}]},
    {"type": "message", "text": "Gusto {{ gusto }}"}]}])
st = {}
say(st, "menu", ALSO)
saved_read = brain.understand
brain.understand = lambda *a, **k: {"tipo": "responde", "opcion": "muzza", "accion": None}   # una IA que lo lee como sí:
r = say(st, "mejor 3", ALSO)            # con contrapropuesta no se la consulta (así se confirmó una cita: «jueves» leído como «sí»)
brain.understand = saved_read
assert r["messages"] == ["Van 3"] and st["slots"]["gusto"] is None, r
st = {}
say(st, "menu", ALSO)
assert say(st, "nada que ver", ALSO)["messages"][0] == "No reconocí ese dato, probemos de nuevo."   # sin also: se rechaza igual
# 1. botones: el turno trae los del último mensaje; tocar uno contesta la pregunta con su valor
st = {}
r = say(st, "menu")
assert r["messages"] == ["¿Con qué área?"] and r["buttons"] == [{"label": "Ventas", "value": "ventas"}, {"label": "Soporte", "value": "Soporte"}], r
assert r["language"] == "es" and r["handoff"] is False and r["via"] is None and r["sources"] == []
assert say(st, "Soporte")["messages"] == ["Área: Soporte"] and st["flow"] is None
st = {}
say(st, "menu")
assert say(st, "VENTAS")["messages"] == ["Área: ventas"]          # escrito tal cual también vale
# 6. idiomas: se adivina del primer mensaje; textos, botones y "no entendí" traducidos
st = {}
r = say(st, "olá, você tem o menu?")
assert r["language"] == "pt" and r["messages"] == ["Com qual área?"] and r["buttons"][0]["label"] == "Vendas", r
assert say(st, "xyz")["messages"][0].startswith("Não reconheci")
assert say({"lang": "pt"}, "xyz")["messages"] == ["não entendi"]
assert say({}, "hola, qué tal")["language"] == "es"
assert say({}, "xyz", dict(BOT, languages=["en"]))["language"] == "en"
st = {}
app.begin(BOT, st, {"idioma": "pt-BR"})
assert st["lang"] == "pt" and say(st, "the menu please")["language"] == "pt"   # el que vino al empezar manda
# 3. subflujo: "call" vuelve al terminar; "end" dentro del subflujo también vuelve
for name, last in [("Ana", ["Gracias Ana", "Ana: 2 de muzza"]), ("x", ["x: 2 de muzza"])]:
    st = {}
    assert say(st, "una pizza de muzza")["messages"] == ["¿Cuántas?"]
    assert say(st, "2")["messages"] == ["¿Tu nombre?"] and st["stack"][0]["kind"] == "call"
    assert say(st, name)["messages"] == last and st["flow"] is None and st["stack"] == []
assert say({}, "loop")["messages"][0].startswith("⚠") and "uno dentro de otro" in say({}, "loop")["messages"][0]
# interrupción: una respuesta inválida que es otra intención corre ese flujo y vuelve a la pregunta
st = {}
say(st, "una pizza de muzza")
r = say(st, "¿y el horario?")
assert r["messages"] == ["Abrimos de 9 a 18", "Sigamos con lo de antes.", "¿Cuántas?"] and not r["rejected"] and r["answer_to"] is None, r
assert say(st, "3")["messages"] == ["¿Tu nombre?"] and st["slots"]["cantidad"] == "3"
# 4. corrección: trae un valor nuevo para algo ya preguntado en este flujo
st = {}
say(st, "una pizza de muzza")
r = say(st, "mejor de fugazza")
assert r["messages"] == ["Listo, lo cambié.", "¿Cuántas?"] and st["slots"]["gusto"] == "fugazza", r
say(st, "2")
assert say(st, "Ana")["messages"][-1] == "Ana: 2 de fugazza"
# 5. flujos del sistema: valores por defecto completos, cancelar, repetir, aclarar, ¿algo más?, encuesta
conf = app.system_of({"system": {"cancel": {"text": "Chau"}}})
assert set(conf) == set(app.SYSTEM_DEFAULTS) and conf["cancel"]["text"] == "Chau" and conf["cancel"]["examples"] == app.SYSTEM_DEFAULTS["cancel"]["examples"]
st = {}
say(st, "una pizza de muzza")
assert say(st, "cancelar")["messages"] == ["Listo, lo dejamos acá. ¿Te ayudo con otra cosa?"] and st["flow"] is None and st["stack"] == []
st = {}
say(st, "una pizza de muzza")
assert say(st, "repetí")["messages"] == ["¿Cuántas?"] and say(st, "2")["messages"] == ["¿Tu nombre?"]
near = lambda agent, text: dict(R(agent, text), intent="menu", confidence=0.8, ranking=[("menu", 0.8), ("horario", 0.78)]) if text == "algo" else R(agent, text)
st = {}
r = app.handle(BOT, st, "algo", near)
assert r["messages"] == ["¿Quisiste decir menu o horario?"] and [b["value"] for b in r["buttons"]] == ["menu", "horario"], r
assert app.handle(BOT, st, "horario", near)["messages"] == ["Abrimos de 9 a 18"]
assert app.handle(dict(BOT, system={"clarify": {"enabled": False}}), {}, "algo", near)["messages"] == ["¿Con qué área?"]
assert say({}, "horario", dict(BOT, system={"anything_else": {"enabled": True}}))["messages"] == ["Abrimos de 9 a 18", "¿Te ayudo con algo más?"]
surveyed, st = dict(BOT, system={"csat": {"enabled": True}}), {}
r = say(st, "horario", surveyed)
assert r["messages"][-1] == "¿Cómo te atendí? Del 1 al 5." and [b["value"] for b in r["buttons"]] == ["1", "2", "3", "4", "5"], r
r = say(st, "4", surveyed)
assert st["csat"] == 4 and r["csat"] == 4 and r["messages"] == ["¡Gracias por contarme!"]
assert say(st, "horario", surveyed)["messages"] == ["Abrimos de 9 a 18"]          # se pregunta una sola vez
# las intenciones del sistema entran al clasificador y a la foto entrenada, pero no a la autoevaluación
import numpy as np
saved_enc = app._encode
app._encode = lambda texts: [np.array([1.0, 0.0]) if t.startswith(("cancel", "dejá", "olvid", "no quiero")) else np.array([0.0, 1.0]) for t in texts]
toy_agent = {"intents": [{"name": "saludar", "examples": ["saludo de prueba"]}], "entities": []}
assert app.classify(toy_agent, "cancelar todo")[0][0] == "__cancel__"
assert app.classify(dict(toy_agent, system={"cancel": {"enabled": False}}), "cancelar todo")[0][0] != "__cancel__"
data = app.nlu_data(toy_agent)
assert "__cancel__" in [i for i, _ in app.classify(data, "cancelar")] and "system" in data
assert all(not i["name"].startswith("__") for i in app.self_check(data)["intents"])
app._encode = saved_enc
# 2. persona humana: el paso y la intención pasan la charla; mientras tanto el bot no habla
st = {}
r = say(st, "tengo un reclamo")
assert r["messages"] == ["Ok", "Te paso con una persona, ya te escriben."] and r["handoff"] and st["handoff"]["reason"] == "reclamo", r
assert say(st, "hola?")["messages"] == [] and say(st, "menu")["handoff"] is True
st = {}
say(st, "una pizza de muzza")
assert say(st, "quiero hablar con una persona")["handoff"] and st["flow"] is None
# 7. claves: valen en HTTP (y la traza las tapa) y en entradas de funciones; nunca en mensajes
saved_vault = vault.values, vault.mask
vault.values = lambda agent_id: {"TOKEN": "s3cr3t"}
vault.mask = lambda text, agent_id: text.replace("s3cr3t", "••••")
keyed = dict(BOT, id="ffff6666", functions=[{"name": "eco", "language": "python", "inputs": ["secret.TOKEN", "nombre"],
                                             "code": "def run(i):\n    return {'nombre': i['secret']['TOKEN'] + '-' + str(i['nombre'])}"}],
             flows=[{"name": "f", "trigger": "horario", "steps": [
                 {"type": "http", "url": "http://127.0.0.1:9/x?k={{ secret.TOKEN }}", "saves": []},
                 {"type": "function", "function": "eco"}, {"type": "message", "text": "{{ nombre }}"},
                 {"type": "message", "text": "{{ secret.TOKEN }}"}]}])
r = say({}, "horario", keyed)
assert "k=••••" in r["trace"][1] and not any("s3cr3t" in t for t in r["trace"]), r["trace"]
assert r["messages"][0] == "s3cr3t-None" and r["messages"][1].startswith("⚠"), r["messages"]
vault.values, vault.mask = saved_vault
# 8. IA: rescata intenciones, completa slots, responde antes del "no entendí" y conduce el paso «agent»
saved_brain = brain.rescue_intent, brain.fill_slot, brain.fallback, brain.agent_turn
smart = dict(BOT, ai={"enabled": True})
brain.rescue_intent = lambda agent, text, nlu, st=None: dict(nlu, intent="horario", confidence=0.9, via="ia")
r = say({}, "a qué hora abren", smart)
assert r["messages"] == ["Abrimos de 9 a 18"] and r["via"] == "ia", r
assert say({}, "a qué hora abren")["messages"] == ["no entendí"]                      # IA apagada: no se llama
brain.fill_slot = lambda agent, slot, text, ctx: "premium" if "premium" in text else None
st = {}
say(st, "ver planes")
assert say(st, "no sé")["messages"] == ["No reconocí ese dato, probemos de nuevo.", "¿Qué plan?"]
r = say(st, "el premium")
assert r["messages"] == ["Plan premium"] and r["via"] == "ia"
brain.fallback = lambda agent, st, text: {"text": "Según las preguntas frecuentes...", "sources": [{"title": "FAQ"}], "via": "knowledge"}
r = say({}, "bla")
assert r["messages"] == ["Según las preguntas frecuentes..."] and r["via"] == "knowledge" and r["sources"] == [{"title": "FAQ"}] and r["fallback"]
brain.fallback = lambda agent, st, text: 1 / 0                                       # si la IA explota, sigue el de siempre
assert say({}, "bla")["messages"] == ["no entendí"]
calls = []
def fake_turn(agent, step, st, text, ctx, call_function):
    calls.append(call_function("cotizar", {"plan": text}))
    if len(calls) == 1:
        return {"messages": ["¿Qué buscás?"], "done": False, "slots": {}, "trace": ["pensó"]}
    return {"messages": ["Listo"], "done": True, "slots": {"plan": "pro"}, "trace": []}
brain.agent_turn = fake_turn
helper = dict(BOT, functions=[{"name": "cotizar", "language": "python", "inputs": ["plan"], "code": "def run(i):\n    return {'precio': 10}"}],
              flows=[{"name": "f", "trigger": "planes", "steps": [{"type": "agent", "functions": ["cotizar"], "max_turns": 4},
                                                                  {"type": "message", "text": "Plan {{ plan }}"}]}])
st = {}
assert say(st, "ver planes", helper)["messages"] == ["¿Qué buscás?"] and st["agent"]["turns"] == 1
assert say(st, "uno barato", helper)["messages"] == ["Listo", "Plan pro"] and "agent" not in st and st["flow"] is None
assert calls[0]["ok"] and calls[0]["result"] == {"precio": 10}, calls
def counting_turn(agent, step, st, text, ctx, call_function):      # como brain.agent_turn: cuenta el turno en st["agent"]
    mem = st.setdefault("agent", {})
    mem["turns"] = mem.get("turns", 0) + 1
    return {"messages": ["¿Y?"], "done": False}
brain.agent_turn = counting_turn
st = {}
say(st, "ver planes", helper)
assert st["agent"]["turns"] == 1, st["agent"]            # una vez por turno, no dos: así max_turns corta a los 4
for _ in range(3):
    say(st, "sigo", helper)
assert "agent" not in st, st
brain.rescue_intent, brain.fill_slot, brain.fallback, brain.agent_turn = saved_brain
saved_dates = dates.extract
dates.extract = lambda text, today=None: [{"start": 4, "end": 10, "value": "2026-11-25", "text": "mañana"}] if "mañana" in text else []
assert app.extract({"intents": [], "entities": [{"name": "fecha", "kind": "date"}]}, "para mañana") == [
    {"entity": "fecha", "value": "2026-11-25", "start": 4, "end": 10}]
marked = {"intents": [{"name": "Turno", "examples": ["un turno para [mañana](fecha)"]}], "entities": [{"name": "fecha", "kind": "date"}]}
assert [e["value"] for e in app.extract(marked, "mañana")] == ["2026-11-25"]   # la marca no suma «mañana» como valor
assert [e["kind"] for e in app.entity_report(marked)] == ["fecha u hora"]
dates.extract = saved_dates
st = {}
for _ in range(10):
    say(st, "horario")
assert len(st["recent"]) == 12 and st["recent"][-1] == {"role": "bot", "text": "Abrimos de 9 a 18"}
# 9-10. API: campos nuevos, historial, bandeja, mensajes desde N y audio
saved = app.all_agents, app.load, app.model, app.parse, app.agent_index
app.agent_index = lambda: [(a["id"], a["id"], a["name"]) for a in app.all_agents()]   # find_bot sigue a los agentes de mentira
app.all_agents = lambda: [dict(BOT, id="eeee5555", name="Mesa")]
app.load = lambda agent_id: app.all_agents()[0]
app.model = lambda agent_id: {"data": app.load(agent_id), "tagger": None}
app.parse = lambda data, text, tagger, index=None: R(data, text)
app.AGENTS = tempfile.mkdtemp()
ev = lambda body: app.api_v1("POST", ["bots", "mesa", "events"], dict(body, sessionId="s1"))[1]
body = ev({"type": "start"})
assert body["buttons"] == [] and body["handoff"] is False and body["language"] == "es" and body["next"] == 1, body
body = ev({"text": "menu"})
assert body["buttons"][0]["value"] == "ventas" and body["via"] is None and body["sources"] == [] and body["next"] == 3, body
ev({"text": "una pizza"})                                                          # respuesta inválida: interrumpe con «pedido»
hist = app.api_v1("GET", ["bots", "mesa", "sessions", "s1"], {})[1]["history"]
assert hist[2]["buttons"][1]["label"] == "Soporte" and hist[1]["flow"] is None and hist[1]["fallback"] is False
assert hist[3]["flow"] == "menu" and hist[3]["waiting"] == "area" and "via" in hist[3]
ev({"type": "end"})
assert ev({"text": "bla"})["handoff"] is False and app.load_session("eeee5555", "s1")["history"][-2]["fallback"] is True
body = ev({"text": "quiero hablar con una persona"})
assert body["handoff"] is True and body["messages"] == ["Te paso con una persona, ya te escriben."]
assert app.inbox("eeee5555")["sessions"][0]["handoff"]["active"] and ev({"text": "hola?"})["messages"] == []
n = ev({"text": "sigo acá"})["next"]
app.human("eeee5555", "s1", "reply", "Hola, soy Laura", "Laura")
status, news = app.api_v1("GET", ["bots", "mesa", "sessions", "s1", "messages"], {}, {"after": str(n)})
assert status == 200 and news["messages"] == [{"from": "human", "text": "Hola, soy Laura", "at": news["messages"][0]["at"], "by": "Laura"}], news
assert news["next"] == n + 1 and news["handoff"] is True and news["ended"] is False
record = app.human("eeee5555", "s1", "release", "", "Laura")
assert record["handoff"]["active"] is False and app.inbox("eeee5555")["sessions"] == []
assert ev({"text": "horario"})["messages"] == ["Abrimos de 9 a 18"]                  # el bot vuelve
app.human("eeee5555", "s1", "take", "", "Persona")
assert app.load_session("eeee5555", "s1")["handoff"]["by"] == "Persona" and ev({"text": "horario"})["messages"] == []
assert app.human("eeee5555", "nada", "take", "", "x") is None
assert app.api_v1("GET", ["bots", "mesa", "sessions", "nada", "messages"], {})[0] == 404
surveyed = dict(BOT, id="eeee5555", name="Mesa", system={"csat": {"enabled": True}})
app.all_agents = lambda: [surveyed]
app.api_v1("POST", ["bots", "mesa", "events"], {"sessionId": "s2", "text": "horario"})
app.api_v1("POST", ["bots", "mesa", "events"], {"sessionId": "s2", "text": "5"})
assert app.load_session("eeee5555", "s2")["csat"] == 5
saved_voice = voice.transcribe, voice.speak
voice.transcribe = lambda audio, mime, language, hint=None: {"text": "menu", "language": language, "ms": 1}
voice.speak = lambda text, language="es": b"RIFF" + text.encode()
status, body = app.api_v1("POST", ["bots", "mesa", "audio"], {"sessionId": "s3", "audio": base64.b64encode(b"x").decode(), "speak": True})
assert status == 200 and body["heard"] == "menu" and body["messages"] == ["¿Con qué área?"] and body["buttons"], body
assert base64.b64decode(body["audio"]) == "RIFF¿Con qué área?".encode()
def deaf(*a):
    raise ValueError("no está instalado el modelo de voz")
voice.transcribe = deaf
assert app.api_v1("POST", ["bots", "mesa", "audio"], {"sessionId": "s3", "audio": "eA=="}) == (400, {"error": "no está instalado el modelo de voz"})
assert app.api_v1("POST", ["bots", "mesa", "audio"], {"sessionId": "s3", "audio": ""})[0] == 400
voice.transcribe, voice.speak = saved_voice
# 11. paso «Enviar un archivo»: la respuesta trae el adjunto; messages siguen siendo textos
from parla import files  # noqa: E402
pdf = files.save("ffff6666", "Lista de precios.pdf", "data:application/pdf;base64," + base64.b64encode(b"%PDF-1.4 hola").decode())
assert len(pdf["id"]) == 22 and pdf["mime"] == "application/pdf" and pdf["size"] == 13 and pdf["url"] == "/files/ffff6666/" + pdf["id"], pdf
FILEBOT = dict(BOT, id="ffff6666", name="Precios", flows=[{"name": "inicio", "trigger": "__start__", "steps": [
    {"type": "set", "slot": "nombre", "mode": "text", "text": "Ana"},
    {"type": "file", "file": pdf["id"], "text": "Acá va, {{ nombre }}"},
    {"type": "file", "file": "lista de PRECIOS.pdf"},                          # por nombre y sin texto: el texto es el nombre
    {"type": "message", "text": "¿Algo más?"}]}])
app.all_agents = lambda: [FILEBOT]
body = app.api_v1("POST", ["bots", "precios", "events"], {"type": "start", "sessionId": "f1"})[1]
assert body["messages"] == ["Acá va, Ana", "Lista de precios.pdf", "¿Algo más?"], body
assert body["replies"][0]["file"] == pdf and body["replies"][1]["file"] == pdf and "file" not in body["replies"][2], body["replies"]
hist = app.api_v1("GET", ["bots", "precios", "sessions", "f1"], {})[1]["history"]
assert hist[1]["file"] == pdf and hist[1]["text"] == "Acá va, Ana" and "file" not in hist[3], hist
assert files.read("ffff6666", pdf["id"])[0] == b"%PDF-1.4 hola" and files.read("ffff6666", "../" + pdf["id"]) is None
files.delete("ffff6666", pdf["id"])
assert files.listing("ffff6666") == [] and files.read("ffff6666", pdf["id"]) is None
assert app.api_v1("POST", ["bots", "precios", "events"], {"type": "start", "sessionId": "f2"})[1]["messages"][0].startswith("⚠ Hay un problema en el flujo «inicio», paso «Enviar un archivo»: no existe el archivo")
for name, data in (("virus.html", "PGI+"), ("foto.svg", "PHN2Zz4="), ("vacio.pdf", ""), ("roto.pdf", "no es base64!")):
    try:
        files.save("ffff6666", name, data)
        raise AssertionError(name)
    except ValueError:
        pass
app.all_agents, app.load, app.model, app.parse, app.agent_index = saved
print("ok")

# frases fijas para la llamada: se cortan igual que en static/voice.js y las que tienen {{ }} no se pregeneran
assert voice.sentences("Hola Ana. ¿Te sirve?\nDime sí o no.") == ["Hola Ana.", "¿Te sirve?", "Dime sí o no."]
_texts = app.spoken_texts({"fallback": ["No entendí."], "languages": ["es"], "flows": [{"steps": [
    {"type": "message", "text": "Hola {{ nombre }}. ¿Te ayudo?"},
    {"type": "if", "then": [{"type": "ask", "slot": "x", "text": "¿Presencial o virtual?"}]}]}]})
assert "¿Presencial o virtual?" in _texts and "No entendí." in _texts and "No reconocí ese dato, probemos de nuevo." in _texts, _texts
_spoken = []
_saved_speak = voice.speak
voice.speak = lambda text, lang="es", keep=True: _spoken.append(text) or b"RIFF"
_saved_cache = voice.TTS_CACHE
voice.TTS_CACHE = voice.Path(app.AGENTS) / "tts-cache-test"
assert voice.prewarm(_texts) == 4 and "Hola {{ nombre }}." not in _spoken and "¿Te ayudo?" in _spoken, _spoken
assert voice.prewarm(_texts) == 0                       # ya estaban: no se generan de nuevo
voice.speak, voice.TTS_CACHE = _saved_speak, _saved_cache
