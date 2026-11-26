"""Pruebas de conversación: cada bot guarda en agent["tests"] charlas con lo que se espera de cada turno.

    python -m parla.bottests examples/pizzeria.json [--env draft]     # para CI: sale con 1 si alguna falla

Una prueba: {"name", "start"?: {slot: valor}, "environment"?: "draft", "turns": [
    {"user": "hola", "intent"?: "Saludar", "says"?: "texto" | "/regex/", "buttons"?: ["Sí"],
     "slots"?: {"nombre": "Juan"}, "flow"?: "Pedido", "handoff"?: true}]}
Un primer turno sin "user" revisa lo que dice el bot al empezar (el flujo __start__).
Corren con handle() sobre un estado en memoria: no se guarda ninguna conversación, así que no aparecen en
Conversaciones, Bandeja, Para enseñar ni Reportes. Los pasos http, function y agent (IA) corren de verdad.
"""
import argparse
import json
import os
import re
import shutil
import sys
import tempfile

from . import telemetry

CHECKS = {"user", "intent", "says", "buttons", "slots", "flow", "handoff"}
FLOW_TRACE = re.compile(r"(?:empieza el flujo|llama al flujo) «(.+?)»")
ENVIRONMENTS = ("draft", "staging", "production")


def shape_errors(tests, intents=None, slots=None, flows=None):
    """Lo que está mal en agent["tests"]. intents/slots/flows: nombres que existen (None = no se chequean)."""
    if not isinstance(tests, list):
        return ["«tests» tiene que ser una lista de pruebas"]
    errors, seen = [], set()
    for i, test in enumerate(tests):
        if not isinstance(test, dict) or not isinstance(test.get("name"), str) or not test["name"].strip():
            errors.append("prueba #%d: tiene que ser un objeto con «name»" % (i + 1))
            continue
        w = "prueba «%s»" % test["name"]
        if test["name"] in seen:
            errors.append("%s está repetida" % w)
        seen.add(test["name"])
        if not isinstance(test.get("start", {}), dict):
            errors.append("%s: «start» tiene que ser un objeto {slot: valor}" % w)
        if test.get("environment", "draft") not in ENVIRONMENTS:
            errors.append("%s: «environment» tiene que ser draft, staging o production" % w)
        turns = test.get("turns")
        if not isinstance(turns, list) or not turns or not all(isinstance(t, dict) for t in turns):
            errors.append("%s: «turns» tiene que ser una lista de turnos {user, intent?, says?, …}" % w)
            continue
        for n, turn in enumerate(turns):
            t = "%s, turno %d" % (w, n + 1)
            if sorted(set(turn) - CHECKS):
                errors.append("%s: no conozco %s (vale: %s)" % (t, ", ".join(sorted(set(turn) - CHECKS)), ", ".join(sorted(CHECKS))))
            if not isinstance(turn.get("user"), str) and (n or "user" in turn):
                errors.append("%s: falta «user» con lo que escribe la persona (solo el primero puede no tenerlo: es el saludo)" % t)
            says = turn.get("says")
            if says is not None and not isinstance(says, str):
                errors.append("%s: «says» tiene que ser un texto o una /regex/" % t)
            elif is_regex(says):
                try:
                    re.compile(says[1:-1])
                except re.error as error:
                    errors.append("%s: la regex de «says» no compila (%s)" % (t, error))
            if not isinstance(turn.get("buttons", []), list) or not all(isinstance(b, str) for b in turn.get("buttons", [])):
                errors.append("%s: «buttons» tiene que ser una lista de textos" % t)
            if not isinstance(turn.get("slots", {}), dict):
                errors.append("%s: «slots» tiene que ser un objeto {slot: valor}" % t)
            elif slots is not None and set(turn.get("slots", {})) - set(slots):
                errors.append("%s: no existen los slots %s" % (t, ", ".join(sorted(set(turn["slots"]) - set(slots)))))
            if "handoff" in turn and not isinstance(turn["handoff"], bool):
                errors.append("%s: «handoff» tiene que ser true o false" % t)
            if intents is not None and turn.get("intent") and turn["intent"] not in intents:
                errors.append("%s: no existe la intención «%s»" % (t, turn["intent"]))
            if flows is not None and turn.get("flow") and turn["flow"] not in flows:
                errors.append("%s: no existe el flujo «%s»" % (t, turn["flow"]))
    return errors


def is_regex(says):
    return isinstance(says, str) and len(says) > 2 and says.startswith("/") and says.endswith("/")


def says_ok(expected, text):
    if is_regex(expected):
        return re.search(expected[1:-1], text) is not None
    return expected.strip().lower() in text.lower()      # texto: que aparezca, sin importar mayúsculas


def same(want, got):
    return want == got or (want is not None and got is not None and str(want).strip().lower() == str(got).strip().lower())


_fresh = {}   # agente -> (foto de frases y entidades, modelo) entrenado solo para las pruebas


def draft_model(app, agent):
    """El borrador tal como está, aunque no se haya entrenado: es lo que se publicaría.
    Si el último entrenamiento coincide, usa ese; si no, entrena uno aparte que no toca el del chat."""
    data = app.nlu_data(agent)
    trained = app.model(agent["id"])
    if trained["data"] == data:
        return trained
    key = json.dumps(data, sort_keys=True, ensure_ascii=False)
    hit = _fresh.get(agent["id"])
    if not hit or hit[0] != key:
        app.classify(data, "calentar")
        # ponytail: un archivo por agente en la carpeta temporal; dos corridas a la vez del mismo agente se pisan
        file = os.path.join(tempfile.gettempdir(), "parla-tests-%s.crfsuite" % agent["id"])
        with app.training(agent["id"]):
            hit = _fresh[agent["id"]] = (key, app.model_entry(data, app.train_tagger(data, file)))
    return hit[1]


def check(turn, result, st):
    nlu = result["nlu"]
    labels = [str(x) for b in result["buttons"] for x in (b.get("label"), b.get("value")) if x is not None]
    flows = FLOW_TRACE.findall(" | ".join(result["trace"]))
    got = {"intent": None if result["fallback"] or result["answer_to"] else nlu["intent"],
           "says": "\n".join(result["messages"]), "buttons": [b.get("label") for b in result["buttons"]],
           "slots": {k: v for k, v in result["slots"].items() if v not in (None, "")},
           "flow": st.get("flow") or (flows[-1] if flows else None), "handoff": bool(result["handoff"])}
    fails = []
    fail = lambda name, want, have: fails.append({"check": name, "expected": want, "got": have})
    if turn.get("intent") and turn["intent"] != got["intent"]:
        fail("intent", turn["intent"], got["intent"])
    if turn.get("says") and not says_ok(turn["says"], got["says"]):
        fail("says", turn["says"], got["says"])
    missing = [b for b in turn.get("buttons") or [] if not any(same(b, x) for x in labels)]
    if missing:
        fail("buttons", missing, got["buttons"])
    for name, want in (turn.get("slots") or {}).items():
        if not same(want, result["slots"].get(name)):
            fail("slots." + name, want, result["slots"].get(name))
    if turn.get("flow") and turn["flow"] != got["flow"]:
        fail("flow", turn["flow"], got["flow"])
    if "handoff" in turn and bool(turn["handoff"]) != got["handoff"]:
        fail("handoff", bool(turn["handoff"]), got["handoff"])
    errors = [m for m in result["messages"] if m.startswith("⚠")]
    if errors and not turn.get("says"):          # un paso que falló es una falla, salvo que se la espere
        fail("error", None, errors[0])
    return {"user": turn.get("user"), "passed": not fails, "failures": fails, "got": got}


def run_test(app, agent_id, test, environment=None):
    env = environment or test.get("environment") or "draft"
    number, agent = app.target(app.load(agent_id), env)
    snap = draft_model(app, agent) if number is None else app.trained_for(agent_id, number)
    parse = lambda a, text: app.parse(snap["data"], text, snap["tagger"], snap.get("index"))
    st, turns, out = {}, list(test["turns"]), []
    result, _ = app.begin(agent, st, dict(test.get("start") or {}))
    if "user" not in turns[0]:
        out.append(check(turns.pop(0), result, st))
    for turn in turns:
        out.append(check(turn, app.handle(agent, st, turn["user"][:4000], parse=parse), st))
    return {"name": test["name"], "environment": env, "version": number, "passed": all(t["passed"] for t in out), "turns": out}


def run_suite(agent_id, environment=None, names=None):
    """Corre las pruebas del agente (todas o las de names). environment pisa el de cada prueba (si no, draft).
    -> {passed, total, failed, tests: [{name, passed, error?, turns: [{user, passed, failures, got}]}]}"""
    from . import server as app
    agent = app.load(agent_id)
    tests = [t for t in agent.get("tests") or [] if not isinstance(t, dict) or names is None or t.get("name") in names]
    results = []
    for test in tests:
        problems = shape_errors([test])
        name = test.get("name") if isinstance(test, dict) else None
        if problems:
            results.append({"name": name, "passed": False, "error": "; ".join(problems), "turns": []})
            continue
        try:
            results.append(run_test(app, agent_id, test, environment))
        except Exception as error:  # noqa: BLE001 - una prueba rota no corta las demás
            results.append({"name": name, "passed": False, "error": str(error), "turns": []})
    failed = sum(not r["passed"] for r in results)
    telemetry.count("parla_test_runs_total", agent=agent_id, outcome="failed" if failed else "passed")
    return {"passed": not failed, "total": len(results), "failed": failed, "tests": results}


def short(value, n=120):
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
    text = text.replace("\n", " ⏎ ")
    return text if len(text) <= n else text[:n - 1] + "…"


def failure_lines(test):
    """Las fallas de una prueba en palabras, una por línea."""
    if test.get("error"):
        return ["no se pudo correr: " + test["error"]]
    out = []
    for n, turn in enumerate(test["turns"]):
        where = "turno %d%s" % (n + 1, " «%s»" % short(turn["user"], 60) if turn["user"] is not None else " (al empezar)")
        out += ["%s: %s: esperaba %s, recibió %s" % (where, f["check"], short(f["expected"]), short(f["got"])) for f in turn["failures"]]
    return out


def summary(results):
    """Una línea: cuántas fallaron y cuáles."""
    if results["passed"]:
        return "pasaron las %d pruebas" % results["total"]
    names = [t["name"] or "?" for t in results["tests"] if not t["passed"]]
    return "fallaron %d de %d pruebas: %s" % (results["failed"], results["total"], ", ".join("«%s»" % n for n in names))


def main(argv=None):
    parser = argparse.ArgumentParser(prog="python -m parla.bottests",
                                     description="Corre las pruebas de conversación de un agente exportado (.json).")
    parser.add_argument("file", help="el agente: el .parla.json que exporta Parla o el JSON del agente")
    parser.add_argument("--env", default="draft", choices=ENVIRONMENTS[:1],
                        help="contra qué correr (un archivo solo tiene el borrador)")
    args = parser.parse_args(argv)
    with open(args.file, encoding="utf-8") as f:
        data = json.load(f)
    from . import server as app
    folder = tempfile.mkdtemp(prefix="parla-bottests-")
    app.AGENTS = os.path.join(folder, "agents")         # el agente vive en una carpeta descartable
    os.makedirs(app.AGENTS)
    github = os.environ.get("GITHUB_ACTIONS") == "true"
    try:
        agent = app.create(app.imported(data))
        if not agent.get("tests"):
            print("%s no tiene pruebas (agent.tests): no hay nada que correr" % args.file)
            return 1
        app.train(agent["id"])
        results = run_suite(agent["id"], args.env)
    finally:
        shutil.rmtree(folder, ignore_errors=True)
    for test in results["tests"]:
        print(("ok     " if test["passed"] else "FALLÓ  ") + str(test["name"]))
        for line in failure_lines(test):
            print("       " + line)
            if github:
                print("::error file=%s,title=Prueba «%s»::%s" % (args.file, test["name"], line.replace("%", "%25").replace("\n", "%0A")))
    print("\n%s: %s" % (agent["name"], summary(results)))
    return 0 if results["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
