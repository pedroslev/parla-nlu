"""Pruebas de IA: fechas (sin modelo), degradación con la IA apagada y llamadas reales al modelo local.
Si Ollama no está, las pruebas con modelo se saltean con un aviso. Uso: .venv/bin/python tests/test_ai.py"""
import datetime as dt
import time

import support
support.temp_data()
from parla import brain, dates, knowledge, llm  # noqa: E402

# ---------- fechas: hoy = martes 24/11/2026 ----------
T = dt.date(2026, 11, 24)


def one(text):
    found = dates.extract(text, T)
    assert len(found) == 1, (text, found)
    return found[0]["value"]


for text, want in [("hoy", "2026-11-24"), ("mañana", "2026-11-25"), ("pasado mañana", "2026-11-26"),
                   ("el lunes", "2026-11-30"), ("el martes", "2026-12-01"), ("el jueves que viene", "2026-11-26"),
                   ("el próximo miércoles", "2026-11-25"), ("la semana que viene", "2026-11-30"), ("en 3 días", "2026-11-27"),
                   ("en dos semanas", "2026-12-08"), ("15/12", "2026-12-15"), ("15/3", "2027-03-15"), ("1/2/2027", "2027-02-01"),
                   ("15 de diciembre", "2026-12-15"), ("15 de diciembre de 2027", "2027-12-15"),
                   ("a la tarde", "2026-11-24T16:00"), ("a las 5", "2026-11-24T17:00"), ("17:30", "2026-11-24T17:30"),
                   ("al mediodía", "2026-11-24T12:00"), ("mañana a la mañana", "2026-11-25T09:00"),
                   ("el jueves que viene a la tarde", "2026-11-26T16:00"), ("a las 10 de la noche el viernes", "2026-11-27T22:00"),
                   ("Mañana a las 8 de la mañana", "2026-11-25T08:00"), ("mañana 18hs", "2026-11-25T18:00")]:
    assert one(text) == want, (text, one(text), want)
f = dates.extract("quiero turno para el 2/12 a las 9 y media, gracias", T)
assert [(x["value"], x["text"]) for x in f] == [("2026-12-02T09:30", "el 2/12 a las 9 y media")], f
assert dates.extract("mi teléfono es 1155443322 y tengo 300 pesos", T) == []
assert dates.extract("el 31/02", T) == []
assert dates.extract("", T) == [] and dates.extract(None, T) == []
assert len(dates.extract("hoy o mañana", T)) == 2

# ---------- IA apagada: todo igual que antes ----------
OFF = {"intents": [{"name": "saludo", "examples": ["hola"]}], "entities": [], "functions": []}
NLU = {"intent": "saludo", "confidence": 0.3, "ranking": [("saludo", 0.3)], "entities": []}
assert brain.rescue_intent(OFF, "hola", NLU) is NLU
assert brain.fill_slot(OFF, {"name": "nombre", "description": "Nombre"}, "soy Ana", {}) is None
assert brain.fallback(OFF, {}, "cualquier cosa") is None
out = brain.agent_turn(OFF, {"type": "agent"}, {}, "hola", {}, lambda n, i: None)
assert out["done"] and out["messages"] and out["slots"] == {}
assert llm.settings(OFF)["model"] == "qwen2.5:0.5b" and llm.settings({"ai": {"model": "gemma3:1b"}})["model"] == "gemma3:1b"

# base de conocimiento extractiva: anda SIN IA
real_search = knowledge.search
knowledge.search = lambda agent, q, k=3: [{"text": "P: ¿Cuál es el horario?\nR: Atendemos de lunes a viernes de 9 a 18 hs.",
                                           "title": "Preguntas frecuentes", "doc": "k1", "score": 0.8}]
r = brain.fallback(OFF, {}, "a qué hora abren?")
assert r == {"text": "Atendemos de lunes a viernes de 9 a 18 hs.", "sources": [{"title": "Preguntas frecuentes", "doc": "k1", "score": 0.8}], "via": "knowledge"}, r
knowledge.search = lambda agent, q, k=3: [{"text": "otra cosa", "title": "x", "doc": "k1", "score": 0.3}]
assert brain.fallback(OFF, {}, "a qué hora abren?") is None                       # bajo el umbral: no responde
knowledge.search = lambda agent, q, k=3: 1 / 0
assert brain.fallback(OFF, {}, "x") is None                                        # nunca lanza
assert brain._supported("Atendemos de 9 a 18 horas.", "Atendemos de 9 a 18 hs.", "horario")
assert not brain._supported("Atendemos de 9 a 20.", "Atendemos de 9 a 18 hs.", "horario")    # número inventado
assert not brain._supported("Los sábados no abren.", "Los sábados de 9 a 13.", "abren los sábados?")   # negación inventada

# Ollama apagado / dirección equivocada: avisa y no cuelga
DOWN = {"ai": {"enabled": True, "url": "http://127.0.0.1:9"}, **OFF}
s = llm.status(DOWN["ai"])
assert not s["ok"] and "Ollama" in s["hint"], s
assert brain.rescue_intent(DOWN, "hola", NLU) is NLU and brain.fallback(DOWN, {}, "x") is None

# una pregunta en medio de una pregunta: sin IA, solo si la base de conocimiento la contesta
knowledge.search = lambda agent, q, k=3: [{"text": "P: ¿Qué es una cita presencial?\nR: Es la que se atiende en la sede.",
                                           "title": "Citas", "doc": "k1", "score": 0.8}]
r = brain.side_question(OFF, {}, "que es presencial?", "¿Presencial o virtual?")
assert r and r["text"] == "Es la que se atiende en la sede." and r["via"] == "knowledge", r
assert brain.side_question(OFF, {}, "presencial", "¿Presencial o virtual?") is None          # no parece pregunta
knowledge.search = lambda agent, q, k=3: []
assert brain.side_question(OFF, {}, "¿qué es eso?", "¿Presencial o virtual?") is None          # sin datos ni IA: sigue el flujo
assert brain.side_question(DOWN, {}, "¿qué es eso?", "x") is None                             # IA caída: igual
# opción dicha con otras palabras: sin IA (o caída) no adivina
SI_NO = {"name": "si_no", "values": ["si", "no"]}
assert brain.understand(OFF, {}, "dale nomás", "¿Te sirve?", SI_NO) is None and brain.understand(DOWN, {}, "dale", "x", SI_NO) is None
knowledge.search = real_search

# ---------- con el modelo local de verdad ----------
CFG = {"enabled": True, "temperature": 0}
s = llm.status(CFG)
if not s["ok"] or not s["model_ready"]:
    print("(se saltean las pruebas con modelo: %s)" % (s.get("hint") or s.get("error")))
else:
    ON = {"ai": CFG, "threshold": 0.7, "entities": [{"name": "fecha", "kind": "date"}], "functions": [
        {"name": "cotizar", "inputs": ["plan"], "description": "precio mensual de un plan: basico o premium"}], "intents": [
        {"name": "pedir_turno", "examples": ["quiero sacar un turno", "necesito una cita", "quiero reservar"]},
        {"name": "consultar_precios", "examples": ["cuánto sale", "precio de la consulta"]},
        {"name": "cancelar_turno", "examples": ["quiero cancelar mi turno", "no voy a poder ir"]}]}
    times = {}

    def timed(name, fn):
        t = time.time()
        out = fn()
        times[name] = round(time.time() - t, 2)
        return out

    llm.chat(CFG, [{"role": "user", "content": "hola"}], max_tokens=5)          # carga el modelo en memoria
    nlu = {"intent": "consultar_precios", "confidence": 0.5, "entities": [],
           "ranking": [("consultar_precios", 0.5), ("pedir_turno", 0.48), ("cancelar_turno", 0.4)]}
    r = timed("rescue_intent", lambda: brain.rescue_intent(ON, "che al final no puedo ir, cancelalo", nlu))
    assert r is nlu or r["intent"] == "cancelar_turno", r      # el modelo chico a veces no se anima: nunca elige mal
    assert r is nlu or (r["via"] == "ia" and r["confidence"] >= 0.7)
    far = {"intent": "pedir_turno", "confidence": 0.1, "ranking": [("pedir_turno", 0.1)], "entities": []}
    assert brain.rescue_intent(ON, "qué opinás del fútbol", far) is far           # nada parecido: ni pregunta
    name = {"name": "nombre", "description": "Nombre de la persona"}
    assert timed("fill_slot", lambda: brain.fill_slot(ON, name, "hola, me llamo Juan Pérez", {})) == "Juan Pérez"
    assert brain.fill_slot(ON, name, "quiero un turno", {}) is None
    assert brain.fill_slot(ON, {"name": "fecha", "entity": "fecha"}, "el jueves a la tarde", {}).endswith("T16:00")
    knowledge.search = lambda agent, q, k=3: [{"text": "Los envíos a domicilio cuestan $1500 en CABA.", "title": "Envíos", "doc": "k2", "score": 0.85}]   # por encima del umbral por defecto (0.75 con embeddinggemma)
    r = timed("fallback_knowledge", lambda: brain.fallback(ON, {}, "cuánto sale el envío?"))
    assert r["via"] == "knowledge" and "1500" in r["text"] and r["sources"][0]["doc"] == "k2", r
    knowledge.search = lambda agent, q, k=3: []
    r = timed("fallback_generative", lambda: brain.fallback(ON, {"lang": "es", "recent": []}, "asdf qwerty"))
    assert r["via"] == "ia" and "pedir turno" in r["text"] and not any(c.isdigit() for c in r["text"]), r
    knowledge.search = real_search
    calls = []

    def call(fn, inputs):
        calls.append((fn, inputs))
        return {"ok": True, "result": {"precio": 1000 if inputs.get("plan") == "basico" else 2500}}

    step = {"type": "agent", "instructions": "Ayudá a elegir un plan (basico o premium) y decí su precio.",
            "functions": ["cotizar", "borrar_todo"], "slots": ["plan"], "goal": "cuando el plan esté elegido", "max_turns": 3}
    st = {"recent": [], "lang": "es"}
    r = timed("agent_turn", lambda: brain.agent_turn(ON, step, st, "¿cuánto sale el plan premium?", {}, call))
    assert r["messages"] and len(r["messages"][0]) <= 400 and len(calls) <= 4, r
    assert all(fn == "cotizar" for fn, _ in calls), calls                            # solo funciones que existen y están permitidas
    assert set(r["slots"]) <= {"plan"}, r
    for _ in range(3):
        if r["done"]:
            break
        r = brain.agent_turn(ON, step, st, "dale", {}, call)
    assert r["done"] and "agent" not in st, r                                         # max_turns corta la isla
    print("latencia (s):", times)
print("ok")
