"""Chequeo de insights sin modelo:  .venv/bin/python tests/test_insights.py"""
import time

import numpy as np

import support  # noqa: F401  (repo en sys.path)
from parla import insights, knowledge

AGENT = {"threshold": 0.5, "ignored_phrases": ["hola che"],
         "intents": [{"name": "horarios", "examples": ["a qué hora abren", "horario de atención"]},
                     {"name": "precios", "examples": ["cuánto sale", "precio del [plan](plan)"]},
                     {"name": "__cancel", "examples": ["cancelar"]}]}
T = lambda m: time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(NOW - m * 60))
NOW = time.mktime((2026, 11, 20, 12, 0, 0, 0, 0, -1))
u = lambda text, **kw: dict({"from": "user", "text": text, "at": T(100)}, **kw)

RECORDS = [
    # formato viejo: sin "fallback", se decide por confianza/umbral
    {"sessionId": "old1", "started": T(200), "updated": T(100), "ended": True, "history": [
        u("¿Hacen envíos?", intent="precios", confidence=0.2),
        u("hacen envios", intent=None, confidence=0),
        u("cuanto sale", intent="precios", confidence=0.9),           # entendido
        u("Juan", intent=None, confidence=0, answer_to="nombre"),     # respuesta a una pregunta: no cuenta
        {"from": "bot", "text": "No entendí"}]},
    # formato nuevo
    {"sessionId": "new1", "started": T(90), "updated": T(60), "ended": False, "csat": 4, "history": [
        u("hacen ENVÍOS!!", fallback=True, flow=None, waiting=None),
        u("hola che", fallback=True),                                  # ignorada
        u("a que hora abren", fallback=True),                          # ya es frase de ejemplo
        u("mandan a domicilio", fallback=True),
        u("quiero turno", fallback=False, flow="Turnos", waiting=None)],
     "state": {"stack": [{"flow": "Turnos", "pc": 1, "kind": "call", "waiting": "fecha"}]}},
    {"sessionId": "new2", "started": T(30), "updated": T(5), "ended": False, "csat": 2,
     "handoff": {"active": True, "since": T(5)}, "history": [
        u("quiero turno", fallback=False, flow=None), {"from": "human", "text": "Hola, soy Ana", "at": T(5), "by": "ana"}],
     "state": {"flow": "Turnos", "waiting": "fecha"}},
    {"sessionId": "new3", "started": T(50), "updated": T(45), "ended": False, "history": [
        u("quiero turno", fallback=False)], "state": {"flow": "Turnos", "waiting": "fecha"}},   # formato viejo de st
]

# sin encoder: agrupa por texto normalizado
knowledge.encode = None
g = insights.unrecognized(AGENT, RECORDS)["groups"]
assert [(x["count"], insights.norm(x["label"])) for x in g] == [(3, "hacen envios"), (1, "mandan a domicilio")], g
assert {e["sessionId"] for e in g[0]["examples"]} == {"old1", "new1"}
assert g[0]["suggested_intent"] == "precios" and g[1]["suggested_intent"] is None
assert len(g[0]["texts"]) == 3

# con encoder: "mandan a domicilio" se junta con "hacen envíos" y la sugerencia sale por parecido
VEC = {"hacen envios": [1, 0, 0], "mandan a domicilio": [0.9, 0.1, 0], "a que hora abren": [0, 1, 0],
       "horario de atencion": [0, 1, 0], "cuanto sale": [0, 0, 1], "precio del plan": [0.2, 0, 1]}
knowledge.encode = lambda texts: [np.array(VEC[t], float) / np.linalg.norm(VEC[t]) for t in texts]
g = insights.unrecognized(AGENT, RECORDS)["groups"]
assert [x["count"] for x in g] == [4] and g[0]["suggested_intent"] == "precios", g
solo = [{"sessionId": "s", "history": [u("mandan a domicilio", fallback=True)]}]
assert insights.unrecognized(AGENT, solo)["groups"][0]["suggested_intent"] == "precios"   # el ejemplo más parecido

# un encoder que falla no rompe: vuelve a agrupar por texto
knowledge.encode = lambda texts: 1 / 0
assert len(insights.unrecognized(AGENT, RECORDS)["groups"]) == 2

a = insights.analytics(AGENT, RECORDS, now=NOW)
assert (a["sessions"], a["handoff"], a["contained"], a["contained_rate"]) == (4, 1, 3, 0.75), a
assert (a["user_messages"], a["fallbacks"]) == (11, 6), a          # 2 viejas + 4 nuevas con fallback
assert a["fallback_rate"] == 0.545
assert a["csat"] == {"average": 3.0, "answered": 2, "distribution": {"1": 0, "2": 1, "3": 0, "4": 1, "5": 0}}, a["csat"]
# abandono: new1 (60 min, stack) y new3 (45 min, st viejo); new2 está con una persona; old1 terminó
assert a["abandoned"] == 2 and a["drop_off"] == [{"flow": "Turnos", "question": "fecha", "count": 2}], a["drop_off"]
assert a["flows"] == [{"flow": "Turnos", "started": 3, "dropped": 2}], a["flows"]
assert sum(d["sessions"] for d in a["by_day"]) == 4
assert insights.analytics(AGENT, [])["fallback_rate"] is None
print("ok")
