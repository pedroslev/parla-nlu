#!/usr/bin/env python3
"""Importar proyectos de Rasa.  .venv/bin/python tests/test_rasa_import.py
1) convert() con un proyecto clásico (nlu + domain + stories + rules + form) y uno CALM (flows con collect, ramas y link):
   lo que sale tiene que validar sin errores con el validador del MCP.  2) La ruta POST /api/agents/import/rasa contra un
   Parla temporal propio (zip y files, con límites)."""
import base64
import io
import json
import os
import shutil
import urllib.error
import urllib.request
import zipfile

import support

TMP = support.temp_data()
from parla import rasa_import  # noqa: E402
from parla import mcp_server  # noqa: E402

CLASSIC = {
    "config.yml": "recipe: default.v1\nlanguage: en\npipeline:\n  - name: WhitespaceTokenizer\npolicies:\n  - name: RulePolicy\n",
    "data/nlu.yml": """version: "3.1"
nlu:
- intent: greet
  examples: |
    - hey
    - hello there
    - good morning
- intent: order_pizza
  examples: |
    - I want a [margherita](flavor) pizza
    - one [pepperoni]{"entity": "flavor", "value": "pepperoni"} please
    - can I get a [peperoni]{"entity": "flavor", "value": "pepperoni"}
    - pizza for [3](number) people
- intent: book_flight
  examples: |
    - fly from [Paris]{"entity": "city", "role": "from"} to [Rome]{"entity": "city", "role": "to"}
- intent: goodbye
  examples: |
    - bye
    - see you
- intent: check_order
  examples: |
    - where is my order
- synonym: pepperoni
  examples: |
    - pepperonni
- lookup: size
  examples: |
    - small
    - large
- regex: zipcode
  examples: |
    - \\b\\d{5}\\b
- regex: account_hint
  examples: |
    - \\bACC\\d+\\b
""",
    "domain.yml": """version: "3.1"
intents: [greet, order_pizza, goodbye, check_order, book_flight]
entities:
  - flavor
  - number
  - size
  - zipcode
  - city:
      roles: [from, to]
slots:
  flavor:
    type: text
    mappings:
    - type: from_entity
      entity: flavor
  pizza_size:
    type: categorical
    values: [small, large]
    mappings:
    - type: from_entity
      entity: size
  zipcode:
    type: text
    mappings:
    - type: from_entity
      entity: zipcode
  origin:
    type: text
    mappings:
    - type: from_entity
      entity: city
      role: from
  vip:
    type: bool
    initial_value: false
    mappings:
    - type: from_intent
      intent: greet
      value: true
forms:
  pizza_form:
    required_slots: [flavor, pizza_size, zipcode]
responses:
  utter_greet:
  - text: "Hello! Want a pizza?"
    buttons:
    - title: "Yes"
      payload: /order_pizza
    - title: "No"
      payload: /goodbye
  - text: "Hi there!"
  utter_ask_flavor:
  - text: "Which flavor?"
  utter_ask_pizza_size:
  - text: "Small or large?"
  utter_ask_zipcode:
  - text: "Your zip code?"
    image: "https://example.com/map.png"
  utter_submit:
  - text: "Ordering a {pizza_size} {flavor} pizza to {zipcode}."
  utter_goodbye:
  - text: "Bye"
  utter_unused:
  - text: "never said"
actions:
  - action_check_order
  - validate_pizza_form
""",
    "data/rules.yml": """version: "3.1"
rules:
- rule: goodbye
  steps:
  - intent: goodbye
  - action: utter_goodbye
- rule: activate form
  steps:
  - intent: order_pizza
  - action: pizza_form
  - active_loop: pizza_form
- rule: submit form
  condition:
  - active_loop: pizza_form
  steps:
  - action: pizza_form
  - active_loop: null
  - slot_was_set:
    - requested_slot: null
  - action: utter_submit
""",
    "data/stories.yml": """version: "3.1"
stories:
- story: greet and check
  steps:
  - intent: greet
  - action: utter_greet
  - intent: check_order
  - action: action_check_order
- story: greet differently
  steps:
  - intent: greet
  - action: utter_goodbye
""",
    "tests/test_stories.yml": "stories: []\n",
    "README.md": "not yaml",
}

CALM = {
    "config.yml": "language: es\n",
    "domain.yml": """slots:
  monto:
    type: float
    mappings: [{type: from_llm}]
  destinatario:
    type: text
    mappings: [{type: from_llm}]
  confirma:
    type: bool
    mappings: [{type: from_llm}]
responses:
  utter_ask_destinatario:
  - text: "¿A quién le mandás plata?"
  utter_ask_monto:
  - text: "¿Cuánto le mandás a {destinatario}?"
  utter_ask_confirma:
  - text: "¿Confirmás mandar {monto} a {destinatario}?"
    buttons:
    - title: Sí
      payload: /SetSlots(confirma=true)
    - title: No
      payload: /SetSlots(confirma=false)
  utter_demasiado:
  - text: "Es mucho, no puedo."
  utter_listo:
  - text: "¡Listo, enviado!"
  utter_cancelado:
  - text: "Cancelado."
  utter_saldo:
  - text: "Tu saldo es bueno."
actions:
  - action_transferir
""",
    "data/flows.yml": """flows:
  transferir_plata:
    description: Mandarle plata a un amigo o familiar.
    steps:
      - collect: destinatario
      - id: pedir_monto
        collect: monto
        next:
          - if: slots.monto > 1000
            then:
              - action: utter_demasiado
              - set_slots:
                  - monto: null
                next: pedir_monto
          - else: confirmar
      - id: confirmar
        collect: confirma
        ask_before_filling: true
        next:
          - if: not slots.confirma
            then:
              - action: utter_cancelado
                next: END
          - if: slots.monto >= 500 and slots.destinatario != "yo"
            then:
              - action: action_transferir
              - link: ver_saldo
          - else:
              - action: action_transferir
              - action: utter_listo
                next: END
  ver_saldo:
    description: Ver cuánta plata tengo en la cuenta.
    nlu_trigger:
      - intent: consultar_saldo
    steps:
      - action: utter_saldo
  pattern_chitchat:
    description: charla
    steps:
      - action: utter_free_chitchat_response
""",
    "data/nlu.yml": """nlu:
- intent: consultar_saldo
  examples: |
    - cuánta plata tengo
    - mi saldo
    - cuánto me queda en la cuenta
""",
}


def check(agent):
    _, errors, _ = mcp_server.validate(agent)
    assert not errors, errors


def flow(agent, name):
    return next(f for f in agent["flows"] if f["name"] == name)


def has(warnings, *needles):
    assert any(all(n in w for n in needles) for w in warnings), "no encontré %s en:\n%s" % (needles, "\n".join(warnings))


# ---------- clásico ----------
agent, warns = rasa_import.convert(CLASSIC, "Pizzería")
check(agent)
assert agent["name"] == "Pizzería" and agent["languages"] == ["en"], agent["languages"]
assert agent["fallback"].startswith("Sorry") and agent["system"]["cancel"]["examples"][0] == "cancel"
intents = {i["name"]: i["examples"] for i in agent["intents"]}
assert set(intents) == {"greet", "order_pizza", "goodbye", "check_order", "book_flight"}, intents
assert "one [pepperoni](flavor) please" in intents["order_pizza"]
assert "fly from [Paris](city_from) to [Rome](city_to)" in intents["book_flight"]
ents = {e["name"]: e for e in agent["entities"]}
assert ents["flavor"]["kind"] == "examples" and set(ents["flavor"]["synonyms"]["pepperoni"]) == {"peperoni", "pepperonni"}, ents["flavor"]
assert ents["size"]["kind"] == "list" and ents["size"]["values"] == ["small", "large"]
assert ents["zipcode"]["kind"] == "custom" and ents["zipcode"]["regex"] == r"\b\d{5}\b"
assert "city_from" in ents and "city_to" in ents
slots = {s["name"]: s for s in agent["slots"]}
assert slots["flavor"]["entity"] == "flavor" and slots["pizza_size"]["entity"] == "size" and slots["origin"]["entity"] == "city_from"
greet = flow(agent, "greet")["steps"]
assert greet == [{"type": "message", "text": "Hello! Want a pizza?", "buttons": [
    {"label": "Yes", "value": "I want a margherita pizza"}, {"label": "No", "value": "bye"}]}], greet
order = flow(agent, "order_pizza")["steps"]
assert [(s["type"], s.get("slot")) for s in order] == [("ask", "flavor"), ("ask", "pizza_size"), ("ask", "zipcode"), ("message", None)], order
assert order[0]["text"] == "Which flavor?" and order[3]["text"] == "Ordering a {{ pizza_size }} {{ flavor }} pizza to {{ zipcode }}."
check_order = flow(agent, "check_order")["steps"]
assert check_order[0]["type"] == "http" and "action_check_order" in check_order[0]["body"] and "TODO" in check_order[0]["note"]
has(warns, "acción personalizada «action_check_order»")
has(warns, "intención «greet»", "quedó la primera")
has(warns, "validate_pizza_form")
has(warns, "utter_unused")
has(warns, "variaciones", "utter_greet")
has(warns, "utter_ask_zipcode", "image")
has(warns, "regex «account_hint»")
has(warns, "slot «vip»", "from_intent")
has(warns, "initial_value")
has(warns, "tests/test_stories.yml")
has(warns, "pipeline")
has(warns, "role")
assert not any("README" in w for w in warns)

# ---------- CALM ----------
agent, warns = rasa_import.convert(CALM)
check(agent)
names = [f["name"] for f in agent["flows"]]
assert names == ["transferir_plata", "transferir_plata · confirmar", "transferir_plata · pedir_monto", "ver_saldo"], names
intents = {i["name"]: i["examples"] for i in agent["intents"]}
assert intents == {"transferir_plata": ["Mandarle plata a un amigo o familiar."],
                   "ver_saldo": ["cuánta plata tengo", "mi saldo", "cuánto me queda en la cuenta"]}, intents
assert flow(agent, "transferir_plata")["trigger"] == "transferir_plata" and flow(agent, "ver_saldo")["trigger"] == "ver_saldo"
main = flow(agent, "transferir_plata")["steps"]
assert main[0] == {"type": "ask", "slot": "destinatario", "text": "¿A quién le mandás plata?"}, main[0]
assert main[1] == {"type": "goto", "goto": "transferir_plata · pedir_monto"}, main
monto = flow(agent, "transferir_plata · pedir_monto")["steps"]
assert monto[0]["text"] == "¿Cuánto le mandás a {{ destinatario }}?"
cond = monto[1]
assert cond["type"] == "if" and cond["cond"] == {"var": "monto", "op": "gt", "value": "1000"}, cond
assert [s["type"] for s in cond["then"]] == ["message", "set", "goto"] and cond["then"][2]["goto"] == "transferir_plata · pedir_monto"
assert cond["else"] == [{"type": "goto", "goto": "transferir_plata · confirmar"}]
confirm = flow(agent, "transferir_plata · confirmar")["steps"]
assert confirm[0] == {"type": "set", "slot": "confirma", "mode": "clear"} and confirm[1]["type"] == "ask"   # ask_before_filling
assert confirm[1]["buttons"][0]["label"] == "Sí"
first = confirm[2]
assert first["cond"] == {"var": "confirma", "op": "ne", "value": "true"}, first
assert first["then"][0]["text"] == "Cancelado." and [s["slot"] for s in first["then"][1:]] == ["destinatario", "monto", "confirma"]  # CALM borra lo preguntado
second = first["else"][0]
assert second["expr"] == 'double(monto) >= 500 && destinatario != "yo"', second
# un slot suelto en una condición compuesta es «tiene valor»: «a && b» con textos rompe en CEL
assert rasa_import.translate("slots.a and not slots.b", {"a": "a", "b": "b"}, {}) == {
    "expr": '(a != null && a != "") && !(b != null && b != "")'}
assert second["then"][0]["type"] == "http" and second["then"][-1] == {"type": "goto", "goto": "ver_saldo"}
assert second["else"][1]["text"] == "¡Listo, enviado!"
ents = {e["name"]: e for e in agent["entities"]}
assert ents["confirma"]["kind"] == "list" and ents["confirma"]["values"] == ["true", "false"]
has(warns, "pattern_chitchat")
has(warns, "transferir_plata", "5 a 10 frases")
has(warns, "acción personalizada «action_transferir»")
has(warns, "que en Rasa llena el LLM")
assert not any("ver_saldo" in w and "frases reales" in w for w in warns)

# condiciones sueltas
T = rasa_import.translate
sm, st = {"a": "a", "ok": "ok"}, {"a": "text", "ok": "bool"}
assert T('slots.a = "x"', sm, st) == {"cond": {"var": "a", "op": "eq", "value": "x"}}
assert T("slots.a is not null", sm, st) == {"cond": {"var": "a", "op": "filled", "value": ""}}
assert T("slots.ok", sm, st) == {"cond": {"var": "ok", "op": "eq", "value": "true"}}
assert T("slots.ok is true", sm, st) == {"cond": {"var": "ok", "op": "eq", "value": "true"}}
assert T("slots.a matches \"^x\"", sm, st) is None
assert T("slots.otro > 3", sm, st) is None

try:
    rasa_import.convert({"README.md": "hola"})
    raise AssertionError("tenía que fallar")
except ValueError:
    pass

# ---------- ruta HTTP ----------
server, port = support.start_server(TMP)
try:
    def post(body):
        request = urllib.request.Request("http://127.0.0.1:%d/api/agents/import/rasa" % port, json.dumps(body).encode(),
                                         {"Content-Type": "application/json"}, method="POST")
        try:
            with urllib.request.urlopen(request, timeout=120) as r:
                return r.status, json.loads(r.read())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read())

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for p, text in CLASSIC.items():
            z.writestr("moodbot/" + p, text)          # una carpeta raíz, como sale al comprimir la carpeta
        z.writestr("../evil.yml", "nlu: []")
        z.writestr("/abs.yml", "nlu: []")
    status, body = post({"zip": base64.b64encode(buf.getvalue()).decode(), "name": "Desde zip"})
    assert status == 200, body
    assert body["agent"]["name"] == "Desde zip" and len(body["agent"]["flows"]) == 4, body["agent"]["flows"]
    assert body["agent"]["trained"], "lo entrena al importarlo"
    assert any("evil.yml" in w for w in body["warnings"]), body["warnings"]
    status, listed = 200, json.loads(urllib.request.urlopen("http://127.0.0.1:%d/api/agents" % port).read())
    assert any(a["name"] == "Desde zip" for a in listed)
    status, body = post({"files": CALM})
    assert status == 200 and body["agent"]["name"] == "Bot importado de Rasa", body

    def say(text, agent_id=body["agent"]["id"]):
        request = urllib.request.Request("http://127.0.0.1:%d/api/agents/%s/chat" % (port, agent_id),
                                         json.dumps({"session": "rasa", "text": text}).encode(), {"Content-Type": "application/json"})
        with urllib.request.urlopen(request, timeout=120) as r:
            return [m if isinstance(m, str) else m["text"] for m in json.loads(r.read())["messages"]]
    assert say("quiero mandarle plata a un amigo") == ["¿A quién le mandás plata?"]
    assert say("Ana") == ["¿Cuánto le mandás a Ana?"]
    assert say("5000") == ["Es mucho, no puedo.", "¿Cuánto le mandás a Ana?"]      # la rama vuelve a preguntar (goto)
    assert say("100") == ["¿Confirmás mandar 100 a Ana?"]
    assert say("no") == ["Cancelado."]

    folder = os.path.join(TMP, "moodbot")                 # la herramienta del MCP lee una carpeta local
    for p, text in CLASSIC.items():
        os.makedirs(os.path.dirname(os.path.join(folder, p)), exist_ok=True)
        with open(os.path.join(folder, p), "w", encoding="utf-8") as f:
            f.write(text)
    mcp_server.PARLA_URL = "http://127.0.0.1:%d" % port
    made = mcp_server.import_rasa_project(folder)
    assert made["name"] == "moodbot" and not made["validation"]["errors"] and any("action_check_order" in w for w in made["warnings"]), made
    assert post({"files": {"a.yml": "version: 3"}})[0] == 400
    assert post({"zip": "no es base64!!"})[0] == 400
    bomb = io.BytesIO()
    with zipfile.ZipFile(bomb, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("data/nlu.yml", "#" * 60_000_000)
    status, body = post({"zip": base64.b64encode(bomb.getvalue()).decode()})
    assert status == 400 and "grande" in body["error"], body
finally:
    server.terminate()
    server.wait()
shutil.rmtree(TMP, ignore_errors=True)
print("ok")
