#!/usr/bin/env python3
"""Parla: armá bots que entienden. Agentes con intenciones, entidades, slots y flujos (HTTP + CEL).

    .venv/bin/python app.py [puerto]   ->   http://127.0.0.1:8000
"""
import base64
import concurrent.futures
import json
import queue
import random
import os
import re
import shutil
import sys
import threading
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
import uuid
from http.server import BaseHTTPRequestHandler

from . import DATA, ROOT, write_json, auth, bus, db, i18n, oidc, pii, bottests, brain, channels, connect, dates, files, handoff, insights, knowledge, llm, mcp_client, outbound, phone, rasa_import, runner, telemetry, vault, voice

import celpy
import pycrfsuite

HERE = os.path.join(ROOT, "web")              # index.html y static/
AGENTS = os.path.join(DATA, "agents")
# Embeddings para intenciones, respuestas por significado y base de conocimiento. Elegido midiendo con el bot de citas
# (50 respuestas y 41 pedidos escritos a mano): embeddinggemma con prefijo de similitud dio 44/50 sin errores en ~10 ms,
# contra 40/50 con 2 errores de paraphrase-multilingual-MiniLM y 43/50 con 2 de mpnet.
MODEL = "google/embeddinggemma-300m"
EMBED_PREFIX = "task: sentence similarity | query: "     # embeddinggemma rinde mejor con el prefijo de la tarea
# Fijo al repo (no a PARLA_DATA): las pruebas usan datos temporales y no deben bajar 1,2 GB cada vez.
EMBED_CACHE = os.environ.get("PARLA_EMBED_CACHE") or os.path.join(ROOT, "data", "models", "embeddings")
ANNOT = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")      # "[1234](pedido)" dentro de una frase
TEMPLATE = re.compile(r"\{\{(.+?)\}\}", re.S)        # "{{ slot }}" o "{{ expresión CEL }}" dentro de un texto
MAX_STEPS = 200                                      # corta flujos que se quedan en loop
STEP_NAMES = {"message": "Enviar un mensaje", "ask": "Hacer una pregunta", "set": "Guardar un valor",
              "http": "Consultar un servicio", "if": "Tomar un camino", "goto": "Seguir con otro flujo",
              "classify": "Clasificar la conversación",
              "function": "Ejecutar una función", "handoff": "Pasar con una persona", "call": "Llamar a otro flujo",
              "agent": "Dejar que la IA converse", "file": "Enviar un archivo", "remind": "Programar un recordatorio"}
MAX_DEPTH = 5                                        # flujos apilados: subflujos e interrupciones
# "flujos del sistema": reparaciones de la charla que el dueño puede editar (agent["system"])
SYSTEM_DEFAULTS = {
    "cancel":        {"enabled": True, "examples": ["cancelar", "dejá", "olvidalo", "no quiero seguir"], "text": "Listo, lo dejamos acá. ¿Te ayudo con otra cosa?"},
    "repeat":        {"enabled": True, "examples": ["repetí", "¿cómo?", "no te escuché"]},
    "clarify":       {"enabled": True, "margin": 0.04, "text": "¿Quisiste decir…?"},
    "anything_else": {"enabled": False, "text": "¿Te ayudo con algo más?"},
    "resume":        {"enabled": True, "text": "Sigamos con lo de antes."},
    "correction":    {"enabled": True, "text": "Listo, lo cambié."},
    "handoff":       {"enabled": True, "examples": ["quiero hablar con una persona", "pasame con alguien"], "text": "Te paso con una persona, ya te escriben."},
    "csat":          {"enabled": False, "text": "¿Cómo te atendí? Del 1 al 5."},
}
RESERVED = {"cancel": "__cancel__", "repeat": "__repeat__", "handoff": "__handoff__"}   # intenciones del sistema
REJECT = {"es": "No reconocí ese dato, probemos de nuevo.", "pt": "Não reconheci esse dado, vamos tentar de novo.",
          "en": "I didn't get that, let's try again."}
THANKS = {"es": "¡Gracias por contarme!", "pt": "Obrigado pela resposta!", "en": "Thanks for your feedback!"}
STOPWORDS = {   # ponytail: detector de idioma de juguete por palabras frecuentes; usar un modelo si suman idiomas
    "es": "el la los las y en un una es mi quiero hola gracias cómo qué está tengo necesito buen buenos día puedo yo muy pero dónde cuándo".split(),
    "pt": "o os as e em um uma é meu quero olá obrigado obrigada você não tenho preciso bom dia posso eu muito mas onde quando".split(),
    "en": "the an of and in is for to with not i my want hello hi thanks how you what need can good day please where when".split(),
}


def system_of(agent):
    """La configuración de los flujos del sistema, completa con los valores por defecto en el idioma principal
    (i18n.SYSTEM: en, pt; si no, español). Un valor igual al de fábrica en cualquier idioma no cuenta como cambio: la
    interfaz guarda agent["system"] completo, y así los textos de fábrica siguen al idioma principal si se cambia."""
    own = agent.get("system") if isinstance(agent.get("system"), dict) else {}
    lang = i18n.SYSTEM.get(languages(agent)[0], {})
    out = dict(own)
    for k, v in SYSTEM_DEFAULTS.items():
        factory = [v.get] + [d.get(k, {}).get for d in i18n.SYSTEM.values()]
        mine = {f: x for f, x in (own.get(k) or {}).items() if all(x != get(f) for get in factory)}
        out[k] = {**v, **lang.get(k, {}), **mine}
    return out


def reserved_intents(agent):
    conf = system_of(agent)
    return [{"name": name, "examples": conf[key].get("examples") or []} for key, name in RESERVED.items() if conf[key].get("enabled")]


def hook(fn, *args, default=None):
    """Llama a un módulo enchufable (IA, fechas, claves). Si explota, el bot sigue como si no estuviera."""
    try:
        return fn(*args)
    except Exception:  # noqa: BLE001 - un error de la IA no puede cortar la conversación
        return default


# ---------- NLU: intención por vecino más cercano + entidades por formato y valores ----------

_model = None
_model_lock = threading.Lock()   # dos pedidos a la vez no cargan el modelo dos veces
_vectors = {}  # frase de entrenamiento -> vector. ponytail: nunca se vacía; purgar si hay miles de frases borradas
CORES = os.cpu_count() or 2
EMBED_WORKERS = int(os.environ.get("PARLA_EMBED_WORKERS") or max(1, CORES // 2))    # llamadas a ONNX en paralelo
EMBED_THREADS = int(os.environ.get("PARLA_EMBED_THREADS") or 2)                     # hilos de ONNX por llamada (intra-op)
EMBED_BATCH = int(os.environ.get("PARLA_EMBED_BATCH") or 16)                        # textos por llamada, como mucho
EMBED_WAIT = float(os.environ.get("PARLA_EMBED_WAIT_MS") or 0) / 1000                # esperar a juntar más (0 = solo lo que ya está en la cola)
_jobs = queue.Queue()
EMBED_STATS = {"batches": 0, "items": 0}


def _embed_worker():
    """Micro-batching: junta los textos que esperan (todas las conversaciones a la vez) y hace UNA llamada a ONNX.
    Con varios workers sobre el mismo modelo (ONNX suelta el GIL) se usan todos los núcleos."""
    import numpy as np
    while True:
        batch = [_jobs.get()]
        deadline = time.monotonic() + EMBED_WAIT
        while len(batch) < EMBED_BATCH:
            try:
                left = deadline - time.monotonic()
                batch.append(_jobs.get(timeout=left) if left > 0 else _jobs.get_nowait())
            except queue.Empty:
                break
        try:
            vectors = list(_model.embed([EMBED_PREFIX + t for t, _ in batch], batch_size=len(batch)))
            EMBED_STATS["batches"] += 1
            EMBED_STATS["items"] += len(batch)
            for (_, future), v in zip(batch, vectors):
                future.set_result(v / np.linalg.norm(v))
        except Exception as error:  # noqa: BLE001 - se le devuelve a cada pedido
            for _, future in batch:
                future.set_exception(error)


def _encode(texts):
    global _model
    if _model is None:
        with _model_lock:
            if _model is None:
                from fastembed import TextEmbedding
                model = TextEmbedding(MODEL, cache_dir=EMBED_CACHE, threads=EMBED_THREADS)
                for _ in range(EMBED_WORKERS):
                    threading.Thread(target=_embed_worker, daemon=True, name="parla-embed").start()
                _model = model
    futures = [concurrent.futures.Future() for _ in texts]
    for text, future in zip(texts, futures):
        _jobs.put((text, future))
    return [f.result() for f in futures]


_queries = {}   # texto de la persona -> (_encode que lo calculó, vector): classify y read_answer lo piden en el mismo turno


def _query(text):
    hit = _queries.get(text)
    if hit is None or hit[0] is not _encode:       # las pruebas cambian _encode por vectores de juguete
        if len(_queries) >= 256:
            _queries.clear()
        vector = _encode([text])[0]
        vector.setflags(write=False)               # compartido entre llamadas: que nadie lo modifique
        hit = _queries[text] = (_encode, vector)
    return hit[1]


knowledge.encode = _encode   # la base de conocimiento usa el mismo modelo, cargado una sola vez


def classify(agent, text):
    """[(intención, similitud)] de mayor a menor. Aprender = agregar una frase: no hay reentrenamiento.
    Incluye las intenciones del sistema (__cancel__, __repeat__, __handoff__) con los ejemplos de agent["system"]."""
    pairs = [(ANNOT.sub(r"\1", e).strip().lower(), i["name"])
             for i in agent["intents"] + reserved_intents(agent) for e in i["examples"] if e.strip()]
    if not pairs or not text.strip():
        return []
    missing = sorted({p for p, _ in pairs if p not in _vectors})
    if missing:
        _vectors.update(zip(missing, _encode(missing)))
    query = _query(text.strip().lower())
    best = {}
    for phrase, intent in pairs:
        sim = float(_vectors[phrase] @ query)
        best[intent] = max(sim, best.get(intent, -1.0))
    return sorted(best.items(), key=lambda kv: -kv[1])


# ---------- Entender una respuesta por significado (sin IA generativa) ----------
# Cuando la respuesta no trae literalmente una opción («la quiero desde mi casa» a «¿presencial o virtual?»), se compara
# por significado con: las formas de decir cada opción (entity["phrasings"], más valores y sinónimos), las acciones
# que pueden interrumpir (sus frases de ejemplo) y la charla que no contesta nada (saludar, agradecer). Mismo modelo y
# misma caché que classify: unos milisegundos. Solo decide si está claro; si no, None (sigue la IA o el «No reconocí»).
SMALL_TALK = {"es": ["gracias", "muchas gracias", "hola", "buenas", "jaja", "ok gracias", "un momento", "espera",
                     "dame un segundo", "ya te digo", "mmm", "a ver"],
              "pt": ["obrigado", "olá", "um momento", "espera"], "en": ["thanks", "hello", "one moment", "wait"]}
READ_MIN, READ_MARGIN, READ_ACTION_MARGIN = 0.60, 0.04, 0.10   # medidos con embeddinggemma y el bot de citas (44/50, 0 errores)


def read_answer(agent, entity, text, current_flow=None, lang="es"):
    """{"tipo": "responde"|"accion"|"nada", "opcion", "accion", "score", "por"} o None si no está claro.
    Solo para entidades con «phrasings» (el armador enseñó qué significa cada opción): comparar palabras sueltas contra
    una lista cerrada llenaba valores que la persona no dijo («el domingo» -> «sábado»)."""
    text = (text or "").strip().lower()
    if not text or not (entity or {}).get("phrasings"):
        return None
    flows = {f.get("trigger"): f for f in agent["flows"] if f.get("trigger")}
    current = next((f.get("trigger") for f in agent["flows"] if f.get("name") == current_flow), None)
    labeled = []
    for v in (entity or {}).get("values") or []:
        ways = [v] + ((entity.get("synonyms") or {}).get(v) or []) + ((entity.get("phrasings") or {}).get(v) or [])
        labeled += [(w, ("responde", v)) for w in ways]
    for i in agent["intents"]:
        flow = flows.get(i["name"])
        if not flow or i["name"] == current:
            continue
        kind = "nada" if flow.get("interrupts", True) is False else "accion"     # saludar o agradecer no interrumpe
        labeled += [(ANNOT.sub(r"\1", e).strip(), (kind, i["name"] if kind == "accion" else None)) for e in i["examples"]]
    labeled += [(w, ("nada", None)) for w in SMALL_TALK.get(lang, SMALL_TALK["es"])]
    labeled = [(w.lower(), label) for w, label in labeled if w and w.strip()]
    missing = sorted({w for w, _ in labeled if w not in _vectors})
    if missing:
        _vectors.update(zip(missing, _encode(missing)))
    query = _query(text)
    best = {}
    for phrase, label in labeled:
        sim = float(_vectors[phrase] @ query)
        if sim > best.get(label, (-1.0, ""))[0]:
            best[label] = (sim, phrase)
    ranked = sorted(best.items(), key=lambda kv: -kv[1][0])
    if not ranked:
        return None
    (kind, value), (score, phrase) = ranked[0]
    second = ranked[1][1][0] if len(ranked) > 1 else -1.0
    if score < READ_MIN or score - second < READ_MARGIN:
        return None
    answer = max((v[0] for (k, _), v in best.items() if k == "responde"), default=-1.0)
    if kind == "accion" and score - answer < READ_ACTION_MARGIN:
        return None          # se esperaba una respuesta: una acción solo gana si se despega claro (si no, que decida la IA)
    return {"tipo": kind, "opcion": value if kind == "responde" else None, "accion": value if kind == "accion" else None,
            "score": round(score, 3), "por": phrase}


# ---------- Entidades aprendidas: un CRF, como el CRFEntityExtractor de Rasa ----------
# Aprende del contexto de las palabras marcadas ("me llamo [pedro](nombre)") y reconoce valores
# nuevos en frases parecidas ("me llamo olivia"). Se usa solo para entidades sin formato ni lista.

TOKEN = re.compile(r"\w+(?:[.'@-]\w+)*")


def tokenize(text):
    return [(m.group(), m.start(), m.end()) for m in TOKEN.finditer(text)]


def unmark(phrase):
    """'me llamo [pedro](nombre)' -> ('me llamo pedro', [(9, 14, 'nombre')])"""
    text, spans, last = "", [], 0
    for m in ANNOT.finditer(phrase):
        text += phrase[last:m.start()]
        spans.append((len(text), len(text) + len(m.group(1)), m.group(2)))
        text += m.group(1)
        last = m.end()
    return text + phrase[last:], spans


def training_phrases(data):
    return ([e for i in data["intents"] for e in i["examples"]] +
            [e for ent in data["entities"] for e in ent.get("examples") or []])


def learned(data):
    """Entidades que aprende el CRF: las que no tienen formato ni lista de opciones."""
    return {e["name"] for e in data["entities"] if not e.get("regex") and not e.get("values") and e.get("kind") != "date"}


def features(toks, lookup):
    rows = []
    for i, (word, _, _) in enumerate(toks):
        w = word.lower()
        row = ["bias", "w=" + w, "suf3=" + w[-3:], "title=%s" % word.istitle(), "digit=%s" % word.isdigit(),
               "pos=" + ("solo" if len(toks) == 1 else "first" if i == 0 else "last" if i == len(toks) - 1 else "mid")]
        row += ["list=" + name for name in lookup.get(w, ())]
        for d in (-2, -1, 1, 2):
            j = i + d
            row.append("%+d:w=%s" % (d, toks[j][0].lower()) if 0 <= j < len(toks) else "%+d:pad" % d)
        rows.append(row)
    return rows


def lookup_table(data):
    table = {}
    for e in data["entities"]:
        for value in list(e.get("values") or []) + [o for os_ in (e.get("synonyms") or {}).values() for o in os_]:
            for word, _, _ in tokenize(value.lower()):
                table.setdefault(word, set()).add(e["name"])
    return table


def train_tagger(data, model_path, info=None):
    """Entrena el CRF con todas las frases. Devuelve el Tagger, o None si no hay nada marcado para aprender."""
    names, lookup = learned(data), lookup_table(data)
    trainer, useful = pycrfsuite.Trainer(verbose=False), False
    for phrase in training_phrases(data):
        text, spans = unmark(phrase)
        toks = tokenize(text)
        if not toks:
            continue
        labels = []
        for word, start, end in toks:
            span = next((s for s in spans if s[0] < end and start < s[1]), None)
            labels.append("O" if not span else ("B-" if start <= span[0] else "I-") + span[2])
            useful |= bool(span and span[2] in names)
        # con pocos ejemplos el modelo queda tímido: las frases con datos marcados pesan triple
        for _ in range(3 if any(label != "O" for label in labels) else 1):
            trainer.append(features(toks, lookup), labels)
    if os.path.exists(model_path):
        os.remove(model_path)
    info = {} if info is None else info
    info.update(trained=useful, entities=sorted(names))
    if not useful:
        info["reason"] = ("no hay entidades para aprender: todas tienen lista de opciones o formato" if not names
                          else "todavía no marcaste ninguna de estas entidades en una frase: " + ", ".join(sorted(names)))
        return None
    trainer.set_params({"c1": 0.0, "c2": 0.01, "max_iterations": 200, "feature.possible_transitions": True})
    trainer.train(model_path)
    last = (trainer.logparser.last_iteration or {}) if trainer.logparser else {}
    info.update(iterations=last.get("num"), loss=round(last["loss"], 3) if last.get("loss") is not None else None,
                labels=sorted({l for l in trainer.labels() if l != "O"}) if hasattr(trainer, "labels") else None)
    tagger = pycrfsuite.Tagger()
    tagger.open(model_path)
    return tagger


def tag(text, tagger, index):
    toks = tokenize(text)
    if not tagger or not toks:
        return []
    found, names = [], index["learned"]
    for (word, start, end), label in zip(toks, tagger.tag(features(toks, index["lookup"]))):
        name = label[2:]
        if label.startswith("I-") and found and found[-1]["entity"] == name and found[-1]["open"]:
            found[-1]["end"] = end
        elif label != "O" and name in names:
            found.append({"entity": name, "start": start, "end": end, "open": True})
        else:
            if found:
                found[-1]["open"] = False
    return [{"entity": f["entity"], "value": text[f["start"]:f["end"]], "start": f["start"], "end": f["end"]} for f in found]


def nlu_index(data):
    """Lo que extract necesita de las entidades: se calcula una vez por foto entrenada (va en MODELS, junto al tagger)."""
    known = {}          # entidad -> {forma en que se dice: valor que se guarda}
    defs = {e["name"]: e for e in data["entities"]}
    for name, e in defs.items():
        forms = known.setdefault(name, {})
        for value in e.get("values") or []:
            forms[value.lower()] = value
        for value, others in (e.get("synonyms") or {}).items():      # "muzza" -> "muzzarella"
            for other in others:
                forms.setdefault(other.lower(), value)
    for example in training_phrases(data):
        for value, name in ANNOT.findall(example):
            if (defs.get(name) or {}).get("kind") == "date":
                continue     # «[mañana](fecha)» no es un valor: las reglas de fechas lo pasan a AAAA-MM-DD
            known.setdefault(name, {}).setdefault(value.lower(), value)
    return {"defs": defs, "known": known, "lookup": lookup_table(data), "learned": learned(data)}


def extract(agent, text, tagger=None, index=None):
    """Entidades en el texto: por el formato (regex), por valores conocidos (la lista, sus otras
    formas de decirlo y lo marcado en las frases) y por lo que aprendió el CRF del contexto."""
    index = index or nlu_index(agent)
    defs, known = index["defs"], index["known"]
    found, guesses, free = [], tag(text, tagger, index), index["learned"]
    for name, e in defs.items():       # fechas en lenguaje natural ("el martes a las 10") -> "YYYY-MM-DD[THH:MM]"
        if e.get("kind") == "date":
            found += [{"entity": name, "value": d["value"], "start": d["start"], "end": d["end"]} for d in hook(dates.extract, text, default=[])]
    for name, forms in known.items():
        pattern = (defs.get(name) or {}).get("regex")
        if pattern:
            try:
                for m in re.finditer(pattern, text, re.I):
                    value = m.group(1) if m.groups() and m.group(1) is not None else m.group(0)
                    found.append({"entity": name, "value": value, "start": m.start(), "end": m.end()})
            except re.error:
                pass
        for form in sorted(forms, key=len, reverse=True):
            m = form and re.search(r"(?<!\w)%s(?!\w)" % re.escape(form), text, re.I)
            if not m:
                continue
            if name in free:     # sin lista: se guarda como lo escribió, y si el modelo vio algo más largo ("Pedro Gómez"), gana el modelo
                if any(g["entity"] == name and g["start"] <= m.start() and m.end() <= g["end"] for g in guesses):
                    continue
                found.append({"entity": name, "value": m.group(), "start": m.start(), "end": m.end()})
            else:
                found.append({"entity": name, "value": forms[form], "start": m.start(), "end": m.end()})
    # dentro de una misma entidad, una coincidencia contenida en otra más larga sobra: "2" dentro de "2,5"
    found = [f for f in found if not any(g is not f and g["entity"] == f["entity"] and g["start"] <= f["start"]
                                         and f["end"] <= g["end"] and g["end"] - g["start"] > f["end"] - f["start"] for g in found)]
    for guess in guesses:         # lo aprendido no pisa lo que ya se reconoció seguro
        if not any(f["start"] < guess["end"] and guess["start"] < f["end"] for f in found):
            found.append(guess)
    unique = {(f["entity"], f["value"].lower()): f for f in reversed(found)}   # formato y lista pueden coincidir
    return sorted(unique.values(), key=lambda f: f["start"])


def parse(agent, text, tagger=None, index=None):
    with telemetry.span("nlu.classify", metric="parla_nlu_duration_seconds", labels={"stage": "classify"}) as sp:
        ranking = classify(agent, text)
        intent, confidence = ranking[0] if ranking else (None, 0.0)
        sp.set(**{"parla.intent": intent, "parla.confidence": round(confidence, 3)})
    with telemetry.span("nlu.extract", metric="parla_nlu_duration_seconds", labels={"stage": "extract"}) as sp:
        entities = extract(agent, text, tagger, index)
        sp.set(**{"parla.entities": ",".join(sorted({e["entity"] for e in entities}))})     # los nombres, no los valores
    return {"intent": intent, "confidence": confidence, "ranking": ranking[:5], "entities": entities}


# ---------- Entrenamiento: el chat usa la última versión entrenada, el resto del agente es en vivo ----------

MODELS = {}  # agente -> {"data": frases y entidades entrenadas, "tagger": CRF o None, "index": nlu_index(data)}
_training = {}   # agente -> RLock: entrenar o cargar un agente no frena a los demás


def training(agent_id):
    return _training.get(agent_id) or _training.setdefault(agent_id, threading.RLock())


def model_entry(data, tagger):
    return {"data": data, "tagger": tagger, "index": nlu_index(data)}


def nlu_data(agent):
    """La foto que se entrena: intenciones, entidades y los ejemplos de los flujos del sistema."""
    return {"intents": agent["intents"], "entities": agent["entities"], "system": system_of(agent)}


def train(agent_id, fingerprint=None):
    """Toma una foto de las frases y entidades, entrena el CRF y deja listos los vectores.
    El bot sigue atendiendo con la versión anterior hasta que termina: entrenar no lo apaga."""
    with training(agent_id):          # dos chats a la vez sin modelo no entrenan dos veces ni pisan el .crfsuite
        return _train(agent_id, fingerprint)


def _train(agent_id, fingerprint):
    started = time.perf_counter()
    clock = lambda since: round((time.perf_counter() - since) * 1000)
    agent = load(agent_id)
    data = nlu_data(agent)
    steps = []
    t = time.perf_counter()
    cached = len(_vectors)
    classify(data, "calentar")                      # calcula los vectores de las frases nuevas
    steps.append({"name": "Frases de las intenciones", "ms": clock(t),
                  "detail": "%d frases en %d intenciones; %d nuevas pasadas a vectores" % (
                      sum(len(i["examples"]) for i in data["intents"]), len(data["intents"]), len(_vectors) - cached)})
    t = time.perf_counter()
    crf = {}
    tagger = train_tagger(data, path(agent_id, ".crfsuite"), crf)
    steps.append({"name": "Entidades aprendidas", "ms": clock(t),
                  "detail": ("modelo entrenado en %s vueltas para: %s" % (crf.get("iterations"), ", ".join(crf["entities"])))
                  if crf["trained"] else "no hizo falta: " + crf["reason"]})
    t = time.perf_counter()
    check = self_check(data)
    steps.append({"name": "Autoevaluación", "ms": clock(t), "detail": check["summary"]})
    write_json(path(agent_id, ".model.json"), data)
    MODELS[agent_id] = model_entry(data, tagger)
    phrases = training_phrases(data)
    log = {"duration_ms": clock(started), "steps": steps, "crf": crf, "self_check": check,
           "entities": entity_report(data), "warnings": training_warnings(agent, data)}
    agent["trained"] = {"at": time.strftime("%Y-%m-%d %H:%M"), "fingerprint": fingerprint,
                        "phrases": len(phrases), "marked": sum(len(ANNOT.findall(p)) for p in phrases), "log": log}
    store(agent)
    return agent["trained"]


def self_check(data):
    """Para cada frase de ejemplo: si el bot no la conociera, ¿a qué intención la mandaría? (deja una afuera)."""
    pairs = [(ANNOT.sub(r"\1", e).strip().lower(), e, i["name"]) for i in data["intents"] for e in i["examples"] if e.strip()]
    per = {i["name"]: {"name": i["name"], "phrases": len(i["examples"]), "checked": 0, "right": 0} for i in data["intents"]}
    mistakes = []
    confusion = {}     # intención esperada -> {a cuál la mandó: cuántas frases}
    if pairs:          # todas contra todas de una: sin la misma frase (ni la propia ni repetidas en otra intención)
        import numpy as np
        vecs = np.stack([_vectors[key] for key, _, _ in pairs])
        sims = vecs @ vecs.T
        same = np.array([[key] for key, _, _ in pairs], dtype=object)
        sims[same == same.T] = -np.inf
    for k, (key, raw, intent) in enumerate(pairs):
        row = sims[k]
        if per[intent]["phrases"] < 2 or np.isneginf(row).all():
            continue                                # con una sola frase no hay contra qué comparar
        top = row.max()                             # empate: gana la misma que con max() de tuplas
        score, got, closest = max((float(top), pairs[j][2], pairs[j][0]) for j in np.flatnonzero(row == top))
        per[intent]["checked"] += 1
        row = confusion.setdefault(intent, {})
        row[got] = row.get(got, 0) + 1
        if got == intent:
            per[intent]["right"] += 1
        else:
            mistakes.append({"phrase": ANNOT.sub(r"\1", raw), "expected": intent, "got": got, "score": round(score, 2),
                             "closest": closest})
    checked = sum(p["checked"] for p in per.values())
    right = sum(p["right"] for p in per.values())
    for p in per.values():
        p["accuracy"] = round(p["right"] / p["checked"], 2) if p["checked"] else None
    accuracy = round(right / checked, 2) if checked else None
    summary = ("acertó %d de %d frases (%d%%)" % (right, checked, accuracy * 100)) if checked else "faltan frases para evaluar"
    return {"accuracy": accuracy, "checked": checked, "right": right, "summary": summary,
            "intents": list(per.values()), "mistakes": sorted(mistakes, key=lambda m: -m["score"])[:20], "confusion": confusion}


def entity_report(data):
    marks = {}
    for phrase in training_phrases(data):
        for _, name in ANNOT.findall(phrase):
            marks[name] = marks.get(name, 0) + 1
    kind = lambda e: "fecha u hora" if e.get("kind") == "date" else "aprende de ejemplos" if not e.get("regex") and not e.get("values") else (
        "lista de %d opciones" % len(e["values"]) if e.get("values") else "formato fijo")
    return [{"name": e["name"], "kind": kind(e), "marked": marks.get(e["name"], 0)} for e in data["entities"]]


# ponytail: un piso fijo; la autoevaluación no mide frases de otro tema, así que no sugiere un umbral propio
THRESHOLD_MIN = 0.65    # con embeddinggemma, una frase de otro tema suele quedar entre 0.55 y 0.65 de la más parecida


def training_warnings(agent, data):
    """Consejos concretos para mejorar lo que se acaba de entrenar."""
    out = []
    threshold = float(agent.get("threshold") or 0)
    if threshold < THRESHOLD_MIN:
        out.append("El umbral es %s: con menos de %s, frases que no tienen nada que ver («me llegó fría») caen en la "
                   "intención más parecida. Subilo y sumá intenciones para lo que falte (reclamos, estado del pedido)."
                   % ("%.2f" % threshold, "%.2f" % THRESHOLD_MIN))
    triggers = {f.get("trigger") for f in agent["flows"]}
    for i in data["intents"]:
        n = len(i["examples"])
        if n < 3:
            out.append("«%s» tiene %d frase%s: sumale al menos %d más para que la reconozca bien." % (i["name"], n, "" if n == 1 else "s", 5 - n))
        if i["name"] not in triggers:
            out.append("Ningún flujo responde a «%s»: el bot la va a entender pero no va a hacer nada." % i["name"])
    for e in entity_report(data):
        if e["kind"] == "aprende de ejemplos" and e["marked"] < 3:
            out.append(("La entidad «%s» está marcada %d vez: con 3 o más ejemplos en distintas frases la reconoce mejor."
                        if e["marked"] == 1 else
                        "La entidad «%s» está marcada %d veces: con 3 o más ejemplos en distintas frases la reconoce mejor.")
                       % (e["name"], e["marked"]))
    return out


# ---------- Versiones y entornos (como los alias de Amazon Lex o los entornos de Dialogflow CX) ----------
# El agente que se edita es el BORRADOR. "Publicar" congela una copia numerada (v1, v2…) con su propio modelo
# entrenado. Los entornos "production" y "staging" apuntan a una versión; la API habla con un entorno, nunca con
# el borrador. Volver atrás = apuntar el entorno a una versión anterior. Cada conversación queda atada a la versión
# con la que empezó, así una publicación no cambia los pasos a mitad de una charla.

ENVIRONMENTS = {"production": "Producción", "staging": "Pruebas"}
EDITABLE_ONLY = ("id", "trained", "environments", "deployments", "retention_days", "pii_redaction", "handoff", "webhooks")   # no son parte de la definición del bot


def definition(agent):
    return {k: v for k, v in agent.items() if k not in EDITABLE_ONLY}


def version_path(agent_id, number, ext=".json"):
    return os.path.join(AGENTS, agent_id + ".versions", "%d%s" % (number, ext))


def versions(agent_id):
    folder = os.path.join(AGENTS, agent_id + ".versions")
    numbers = sorted(int(n[:-5]) for n in os.listdir(folder) if n.endswith(".json") and n[:-5].isdigit()) if os.path.isdir(folder) else []
    return numbers


_versions = {}   # archivo -> versión publicada: no cambian nunca (se borran con el agente, ver DELETE)


def load_version(agent_id, number):
    """Compartida entre llamadas: quien la use la lee o la copia ({**v["agent"], ...}), no la modifica."""
    file = version_path(agent_id, number)
    if file not in _versions:
        if not os.path.exists(file):
            raise ValueError("no existe la versión %s" % number)
        with open(file, encoding="utf-8") as f:
            _versions[file] = json.load(f)
    return _versions[file]


def publish(agent_id, note="", environment=None):
    """Congela el borrador actual como una versión nueva, la entrena y (si se pide) la pone en un entorno."""
    agent = load(agent_id)
    number = (versions(agent_id) or [0])[-1] + 1
    snapshot = definition(agent)
    data = nlu_data(snapshot)
    os.makedirs(os.path.dirname(version_path(agent_id, number)), exist_ok=True)
    classify(data, "calentar")
    train_tagger(data, version_path(agent_id, number, ".crfsuite"))
    record = {"version": number, "created": now(), "note": str(note or "").strip()[:500], "agent": snapshot,
              "stats": {"intents": len(snapshot["intents"]), "flows": len(snapshot["flows"]),
                        "phrases": len(training_phrases(data))}}
    with open(version_path(agent_id, number), "w", encoding="utf-8") as f:
        json.dump(record, f, ensure_ascii=False)
    if environment:
        deploy(agent_id, environment, number)
    return version_summary(record, load(agent_id))


def version_summary(record, agent):
    envs = [e for e, n in (agent.get("environments") or {}).items() if n == record["version"]]
    return {"version": record["version"], "created": record["created"], "note": record["note"],
            "stats": record.get("stats", {}), "environments": envs}


def deploy(agent_id, environment, number):
    """Pone una versión en un entorno (o lo deja vacío con None) y lo anota en el registro de despliegues."""
    if environment not in ENVIRONMENTS:
        raise ValueError("el entorno tiene que ser production o staging")
    if number is not None:
        number = int(number)
        load_version(agent_id, number)           # que exista
    agent = load(agent_id)
    envs = agent.setdefault("environments", {})
    previous = envs.get(environment)
    envs[environment] = number
    agent.setdefault("deployments", []).append({"environment": environment, "version": number, "previous": previous, "at": now()})
    del agent["deployments"][:-200]
    store(agent)
    return {"environment": environment, "version": number, "previous": previous}


def target(agent, environment):
    """Qué responde en ese entorno: (versión o None = borrador, definición del bot)."""
    if environment == "draft":
        return None, agent
    if environment not in ENVIRONMENTS:
        raise ValueError("«environment» tiene que ser production, staging o draft")
    number = (agent.get("environments") or {}).get(environment)
    if number is None:
        if environment == "production":
            return None, agent       # todavía no se publicó nada: producción usa el borrador, como antes
        raise ValueError("no hay ninguna versión publicada en Pruebas (staging)")
    return number, {**load_version(agent["id"], number)["agent"], "id": agent["id"]}


def trained_for(agent_id, number):
    """El modelo entrenado del borrador (number=None) o de una versión publicada."""
    if number is None:
        return model(agent_id)
    key = "%s@%d" % (agent_id, number)
    if key not in MODELS:
        snapshot = load_version(agent_id, number)["agent"]
        tagger = None
        if os.path.exists(version_path(agent_id, number, ".crfsuite")):
            tagger = pycrfsuite.Tagger()
            tagger.open(version_path(agent_id, number, ".crfsuite"))
        MODELS[key] = model_entry(nlu_data(snapshot), tagger)
    return MODELS[key]


def diff(old, new):
    """Qué cambia de una definición a otra, por nombre, en palabras que entiende cualquiera."""
    out, total = {}, 0
    for key, label in (("intents", "intenciones"), ("entities", "entidades"), ("slots", "slots"), ("flows", "flujos"),
                       ("classifications", "clasificaciones"), ("functions", "funciones"), ("tests", "pruebas")):
        a = {x["name"]: x for x in old.get(key) or []}
        b = {x["name"]: x for x in new.get(key) or []}
        changed = []
        for name in sorted(set(a) & set(b)):
            if a[name] == b[name]:
                continue
            item = {"name": name}
            if key == "intents":
                item["added_phrases"] = sorted(set(b[name]["examples"]) - set(a[name]["examples"]))
                item["removed_phrases"] = sorted(set(a[name]["examples"]) - set(b[name]["examples"]))
            if key == "flows":
                item["steps"] = [len(a[name].get("steps", [])), len(b[name].get("steps", []))]
                item["trigger"] = [a[name].get("trigger"), b[name].get("trigger")] if a[name].get("trigger") != b[name].get("trigger") else None
            changed.append(item)
        part = {"label": label, "added": sorted(set(b) - set(a)), "removed": sorted(set(a) - set(b)), "changed": changed}
        total += len(part["added"]) + len(part["removed"]) + len(changed)
        out[key] = part
    settings = [k for k in ("name", "threshold", "fallback") if old.get(k) != new.get(k)]
    total += len(settings)
    return {"changes": total, "settings": settings, **out}


def model(agent_id):
    if agent_id not in MODELS:
        with training(agent_id):
            if agent_id in MODELS:
                pass                        # lo cargó otro pedido mientras esperaba
            elif not os.path.exists(path(agent_id, ".model.json")):
                train(agent_id)
            else:
                with open(path(agent_id, ".model.json"), encoding="utf-8") as f:
                    data = json.load(f)
                tagger = None
                if os.path.exists(path(agent_id, ".crfsuite")):
                    tagger = pycrfsuite.Tagger()
                    tagger.open(path(agent_id, ".crfsuite"))
                MODELS[agent_id] = model_entry(data, tagger)
    return MODELS[agent_id]


# ---------- Expresiones ----------

_cel = celpy.Environment()


def cel(expr, ctx):
    try:
        result = _cel.program(_cel.compile(expr)).evaluate(celpy.json_to_cel(ctx))
        return json.loads(json.dumps(result, cls=celpy.CELJSONEncoder))
    except Exception as error:  # noqa: BLE001 - los errores de CEL son crípticos: decir qué expresión falló
        raise ValueError("no pude resolver «%s». Revisá que los slots que usa existan." % expr) from error


def render(template, ctx, url=False):
    """Reemplaza cada {{ expr }} por su valor. Un slot vacío queda como texto vacío.
    url=True: los valores van codificados (lo que escribió la persona no puede cambiar la dirección); secret.* no."""
    def show(match):
        expr = match.group(1).strip()
        value = cel(expr, ctx)
        if value is None:
            return ""
        text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
        return urllib.parse.quote(text, safe="") if url and not expr.startswith("secret.") else text
    return TEMPLATE.sub(show, template or "")


def check(cond, slots):
    """Condición armada en la interfaz: {var, op, value}. Compara sin distinguir mayúsculas."""
    value = slots.get(cond.get("var"))
    op, other = cond.get("op"), str(cond.get("value") or "").strip().lower()
    if op in ("empty", "filled"):
        return (value in (None, "")) == (op == "empty")
    if op in ("gt", "lt"):
        try:
            a, b = float(value), float(other.replace(",", "."))
        except (TypeError, ValueError):
            return False
        return a > b if op == "gt" else a < b
    text = "" if value is None else value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
    text = text.strip().lower()
    if op == "contains":
        return other in text
    return (text == other) == (op != "ne")


# ---------- Flujos ----------

def http_step(step, ctx, timeout=10, body_ctx=None):
    """Hace la consulta y devuelve {status, body}. status 0 = no se pudo conectar."""
    url = render(step.get("url"), ctx, url=True).strip()
    if not url.startswith(("http://", "https://")):
        raise ValueError("la dirección tiene que empezar con http:// o https://")
    headers = {render(h.get("key"), ctx).strip(): render(h.get("value"), ctx)
               for h in step.get("headers") or [] if (h.get("key") or "").strip()}
    if any(re.search(r"[\r\n]", k + v) for k, v in headers.items()):
        raise ValueError("un encabezado no puede tener saltos de línea")
    body = render(step.get("body"), body_ctx or ctx).encode() or None
    if body:
        headers.setdefault("Content-Type", "application/json")
    method = step.get("method") or "GET"
    # el host sí, la ruta y la query no: pueden traer datos de la persona o claves
    with telemetry.span("http.step", kind="client", metric="parla_http_step_duration_seconds", **{
            "http.request.method": method, "server.address": urllib.parse.urlsplit(url).hostname}) as sp:
        if telemetry.traceparent() and not any(k.lower() == "traceparent" for k in headers):
            headers["traceparent"] = telemetry.traceparent()    # el servicio de afuera sigue la misma traza
        request = urllib.request.Request(url, data=body, headers=headers, method=method)
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                status, raw = response.status, response.read(1_000_000)
        except urllib.error.HTTPError as error:       # 4xx/5xx: el flujo decide qué hacer con el código
            status, raw = error.code, error.read(1_000_000)
        except urllib.error.URLError as error:        # sin red, DNS, timeout
            sp.outcome = "unreachable"
            return {"status": 0, "body": str(error.reason)}
        sp.set(**{"http.response.status_code": status})
        sp.outcome = "http_error" if status >= 400 else None
    text = raw.decode("utf-8", "replace")
    try:
        return {"status": status, "body": json.loads(text)}
    except ValueError:
        return {"status": status, "body": text}


def flatten(steps, prefix=""):
    """Los 'if' guardan sus ramas anidadas (then/else); el motor corre una lista plana con saltos."""
    flat = []
    for index, step in enumerate(steps or []):
        if step.get("type") != "if":
            flat.append(step)
            continue
        tag = "%s%d" % (prefix, index)
        flat.append(dict(step, goto="then:" + tag))
        flat += flatten(step.get("else"), tag + "n.")
        flat.append({"type": "goto", "goto": "end:" + tag})
        flat.append({"type": "label", "label": "then:" + tag})
        flat += flatten(step.get("then"), tag + "s.")
        flat.append({"type": "label", "label": "end:" + tag})
    return flat


def secrets(agent):
    """Las claves del agente (vault). Solo se usan al armar consultas HTTP y entradas de funciones."""
    return (hook(vault.values, agent["id"], default={}) or {}) if agent.get("id") else {}


def mask(agent, text):
    """Tapa los valores de las claves en lo que se muestra (trazas, logs)."""
    return hook(vault.mask, text, agent["id"], default=text) if agent.get("id") else text


def secret_inputs(agent, fn):
    """Una entrada «secret.NOMBRE» de una función le llega como inputs["secret"]["NOMBRE"]."""
    wanted = [n[len("secret."):] for n in fn.get("inputs") or [] if n.startswith("secret.")]
    if not wanted:
        return {}
    values = secrets(agent)
    return {"secret": {n: values.get(n) for n in wanted}}


def function_step(agent, fn, step, slots, ctx):
    """Corre una función con los slots que declara como entradas y guarda lo que devuelve.
    Lo que devuelve con el nombre de un slot se guarda solo; además, cada «saves» {expr, slot} evalúa CEL
    sobre result / ok / error. Si falla y el flujo no mira ok ni error, se corta y avisa: un error silencioso
    confunde más que uno visible."""
    inputs = {name: slots.get(name) for name in fn.get("inputs") or [] if not name.startswith("secret.")}
    inputs.update(secret_inputs(agent, fn))
    res = runner.run_function(fn, inputs)
    names = {s["name"] for s in agent["slots"]}
    if res["ok"] and isinstance(res.get("result"), dict) and step.get("auto_save", True):
        for key, value in res["result"].items():
            if key in names:
                slots[key] = value
    scope = dict(ctx, result=res.get("result"), ok=res["ok"], error=res.get("error"))
    for save in step.get("saves") or []:
        if save.get("slot"):
            try:
                slots[save["slot"]] = cel(save.get("expr") or "result", scope)
            except ValueError:
                slots[save["slot"]] = None
    # maneja la falla si alguna expresión usa las variables ok o error (no result.token ni result.error_code)
    handled = any(re.search(r"(?<![\w.])(ok|error)\b", s.get("expr") or "") for s in step.get("saves") or [])
    if not res["ok"] and not handled:
        raise ValueError("la función «%s» falló: %s" % (fn["name"], res["error"]))
    return res


def jump(agent, st, steps, target):
    """Salta a una etiqueta del flujo actual o, si no hay, al inicio del flujo con ese nombre."""
    for index, step in enumerate(steps):
        if step.get("label") and step["label"] == target:
            st["pc"] = index
            return
    if target and any(f["name"] == target for f in agent["flows"]):
        st["flow"], st["pc"] = target, 0
        return
    raise ValueError("elegí con qué flujo seguir")


def languages(agent):
    return agent.get("languages") or ["es"]


def localized(item, st, key="text"):
    """El texto en el idioma de la conversación (item["translations"][idioma]) o el original."""
    return (item.get("translations") or {}).get(st.get("lang")) or item.get(key) or ""


def language_of(agent, st, text):
    """El idioma de la charla: el que vino al empezar, o el que se adivina del primer mensaje."""
    if not st.get("lang"):
        langs = languages(agent)
        words = re.findall(r"\w+", text.lower())
        hits = {l: sum(w in STOPWORDS.get(l, ()) for w in words) for l in langs}
        best = max(langs, key=lambda l: hits[l])         # en empate gana el primero: el idioma por defecto
        st["lang"] = best if hits[best] else langs[0]
    return st["lang"]


def bubble(step, st, ctx):
    """Un mensaje del bot: el texto (con sus {{ }}) y, si tiene, los botones de respuesta rápida."""
    text = render(localized(step, st), ctx)
    buttons = [{"label": localized(b, st, "label"), "value": b.get("value") or b["label"]}
               for b in step.get("buttons") or [] if b.get("label")]
    return {"text": text, "buttons": buttons} if buttons else text


def steps_of(agent, name):
    flow = next((f for f in agent["flows"] if f["name"] == name), None)
    return flow, (flatten(flow["steps"]) if flow else [])


def stop(st):
    """Corta todo lo que estaba en curso: flujo, pila de flujos y paso de IA."""
    st.update(flow=None, stack=[])
    st.pop("agent", None)
    st.pop("worked", None)


def back(agent, st, out):
    """Al terminar un subflujo o una interrupción, sigue con el flujo de abajo de la pila. False si no hay."""
    if not st.get("stack"):
        return False
    frame = st["stack"].pop()
    st["flow"], st["pc"] = frame["flow"], frame["pc"]
    if frame.get("kind") == "interrupt" and system_of(agent)["resume"].get("enabled"):
        out.append(localized(system_of(agent)["resume"], st))
    return True


def start_handoff(st, reason, by=None):
    """La charla pasa a una persona: el bot se calla hasta que la devuelvan (/release)."""
    stop(st)
    st.pop("waiting", None)
    st["handoff"] = {"active": True, "since": now(), "reason": reason, "by": by}


# ---------- herramientas del paso de IA: funciones, consultas HTTP y servidores MCP ----------
TOOL_RESULT_MAX = 1500       # caracteres de resultado que ve el modelo
TOOL_TYPES = {"string": str, "integer": int, "number": (int, float), "boolean": bool}
FIXED_HOST = re.compile(r"https?://[^/?#{}\s]+(?:[/?#]|$)")   # la dirección de una herramienta http no sale de la IA


def http_params(params):
    """params de una herramienta http ({nombre: "descripción"} o {nombre: {type, description, required}}) -> esquema."""
    props, required = {}, []
    for name, spec in (params if isinstance(params, dict) else {}).items():
        spec = spec if isinstance(spec, dict) else {"description": str(spec or "")}
        props[name] = {"type": "string", **{k: spec[k] for k in ("type", "description", "enum") if k in spec}}
        if spec.get("required", True) is not False:
            required.append(name)
    return {"type": "object", "properties": props, "required": required}


def check_args(schema, args):
    """Valida lo que mandó la IA contra el esquema (lo de más se descarta). -> (args limpios, error o None)."""
    if not isinstance(args, dict):
        return {}, "«args» tiene que ser un objeto"
    props = schema.get("properties") if isinstance(schema.get("properties"), dict) else {}
    clean = {}
    for name, value in args.items():
        if name not in props or value in (None, ""):
            continue
        kind = (props[name] or {}).get("type")
        if kind in ("integer", "number") and isinstance(value, str):
            try:
                value = int(value) if kind == "integer" else float(value.replace(",", "."))
            except ValueError:
                return {}, "«%s» tiene que ser un número" % name
        elif kind == "string" and isinstance(value, (int, float)) and not isinstance(value, bool):
            value = str(value)
        if kind in TOOL_TYPES and (not isinstance(value, TOOL_TYPES[kind]) or (kind != "boolean" and isinstance(value, bool))):
            return {}, "«%s» tiene que ser %s" % (name, kind)
        if (props[name] or {}).get("enum") and value not in props[name]["enum"]:
            return {}, "«%s» tiene que ser uno de: %s" % (name, ", ".join(map(str, props[name]["enum"])))
        if len(json.dumps(value, default=str)) > 2000:
            return {}, "«%s» es demasiado largo" % name
        clean[name] = value
    missing = [n for n in schema.get("required") or [] if n not in clean]
    return clean, ("faltan: %s" % ", ".join(missing)) if missing else None


def mcp_server(agent, name):
    """(url, Authorization) de un servidor MCP del agente. La dirección sale de la config, nunca de la IA."""
    server = next((s for s in agent.get("mcp_servers") or [] if isinstance(s, dict) and s.get("name") == name), None)
    if not server or not re.match(r"https?://", str(server.get("url") or "")):
        raise ValueError("no existe el servidor MCP «%s»" % name)
    auth_value = secrets(agent).get(vault._normal(server["headers_secret"])) if server.get("headers_secret") else None
    return server["url"].strip(), auth_value


def agent_tools(agent, step, trace=None):
    """Las herramientas que puede usar este paso: {nombre: {kind, description, params, schema, ...}}.
    De un servidor MCP solo las que el paso habilitó (allow-list) y el servidor ofrece."""
    fns = {f["name"]: f for f in agent.get("functions") or [] if f.get("name")}
    wanted = [{"type": "function", "name": n} for n in step.get("functions") or []] + [t for t in step.get("tools") or [] if isinstance(t, dict)]
    out = {}
    for spec in wanted:
        kind, name = spec.get("type"), spec.get("name")
        if kind == "function" and name in fns:
            inputs = [i for i in fns[name].get("inputs") or [] if not i.startswith("secret.")]
            out.setdefault(name, {"kind": "function", "fn": fns[name], "description": fns[name].get("description") or "",
                                  "schema": {"type": "object", "properties": {i: {} for i in inputs}, "required": inputs}})
        elif kind == "http" and isinstance(name, str) and re.fullmatch(r"[A-Za-z_][\w-]{0,63}", name):
            out.setdefault(name, {"kind": "http", "spec": spec, "description": spec.get("description") or "", "schema": http_params(spec.get("params"))})
        elif kind == "mcp":
            allowed = [n for n in spec.get("tools") or [] if isinstance(n, str)]
            try:
                url, auth_value = mcp_server(agent, spec.get("server"))
                listed = mcp_client.list_tools(url, auth_value, timeout=5) if allowed else []
            except (ValueError, mcp_client.MCPError) as error:
                if trace is not None:
                    trace.append(mask(agent, "herramientas de «%s» no disponibles: %s" % (spec.get("server"), error)))
                continue
            for tool in listed:
                if tool["name"] in allowed:
                    out.setdefault(tool["name"], {"kind": "mcp", "server": spec.get("server"), "description": tool["description"],
                                                  "schema": tool["inputSchema"]})
    for tool in out.values():
        props = (tool["schema"] or {}).get("properties") or {}
        tool["params"] = {p: str((d or {}).get("description") or "") if isinstance(d, dict) else "" for p, d in props.items()}
    return out


def run_tool(agent, tool, args, ctx, timeout=10):
    """Corre una herramienta con lo que pidió la IA. -> {ok, result: texto} (con las claves tapadas y recortado)."""
    if tool["kind"] == "function":     # las entradas que ya están en un slot no hace falta que las mande la IA
        args = dict({k: v for k, v in (ctx or {}).items() if k in tool["schema"]["properties"] and v not in (None, "")},
                    **(args if isinstance(args, dict) else {}))
    args, problem = check_args(tool["schema"] or {}, args)
    if problem:
        return {"ok": False, "result": problem, "args": args}
    try:
        if tool["kind"] == "function":
            inputs = {k: args.get(k) for k in tool["schema"]["properties"]}
            res = runner.run_function(tool["fn"], dict(inputs, **secret_inputs(agent, tool["fn"])))
            ok, value = res["ok"], res.get("result") if res["ok"] else res.get("error")
        elif tool["kind"] == "http":
            spec = tool["spec"]
            if not FIXED_HOST.match(str(spec.get("url") or "").strip()):
                raise ValueError("la dirección de la herramienta tiene que ser fija (https://servidor/...)")
            scope = dict(ctx or {}, **args, secret=secrets(agent))
            # en el body, los textos van escapados para JSON: lo que manda la IA no puede romper el objeto
            body_scope = dict(scope, **{k: json.dumps(v, ensure_ascii=False)[1:-1] if isinstance(v, str) else v for k, v in args.items()})
            res = http_step(spec, scope, timeout=timeout, body_ctx=body_scope)
            ok, value = 200 <= res["status"] < 300, {"status": res["status"], "body": res["body"]}
        else:
            url, auth_value = mcp_server(agent, tool["server"])
            ok, value = mcp_client.call_tool(url, tool["name"], args, auth_value, timeout=timeout)
    except (ValueError, mcp_client.MCPError) as error:
        ok, value = False, str(error)
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, default=str)
    return {"ok": ok, "result": mask(agent, text)[:TOOL_RESULT_MAX], "args": args}


def agent_step(agent, st, step, text, ctx, out, trace):
    """Paso de IA: conversa (con las herramientas del paso a mano) hasta cumplir su objetivo o agotar los turnos.
    True = sigue esperando a la persona (la charla queda en este paso, st["agent"])."""
    tools = agent_tools(agent, step, trace)
    _, budget = brain.tool_limits(step)
    deadline = time.time() + budget

    def call_tool(name, args):
        tool = dict(tools[name], name=name)
        started = time.time()
        res = run_tool(agent, tool, args, ctx, timeout=max(2, min(10, deadline - started)))
        st.setdefault("tool_log", []).append({"tool": name, "type": tool["kind"], "args": json.loads(mask(agent, json.dumps(res.get("args"), default=str))),
                                              "ok": res["ok"], "result": res["result"][:300], "ms": int((time.time() - started) * 1000)})
        return res

    turns = (st.get("agent") or {}).get("turns", 0)
    with telemetry.span("agent.step", **{"parla.tools": ",".join(sorted(tools)), "parla.agent.turn": turns + 1}) as sp:
        res = hook(brain.agent_turn, agent, step, st, text, ctx, call_tool, {n: {"description": t["description"], "params": t["params"]} for n, t in tools.items()}) \
            or {"messages": [], "done": True, "trace": ["la IA falló"]}
        sp.set(**{"parla.agent.done": bool(res.get("done"))})
    out += [m for m in res.get("messages") or [] if isinstance(m, str)]
    st["slots"].update(res.get("slots") or {})
    trace += [mask(agent, str(t)) for t in res.get("trace") or []]
    state = st.setdefault("agent", {"turns": turns})
    state["turns"] = max(state.get("turns", 0), turns + 1)   # una vez por turno: brain.agent_turn ya lo cuenta (si no falló)
    if res.get("done") or state["turns"] >= int(step.get("max_turns") or 8):
        st.pop("agent", None)
        return False
    st["pc"] -= 1
    return True


WORK_STEPS = {"http", "function", "handoff", "file", "agent", "remind", "classify", "end"}   # «hizo algo» (más las preguntas)


def run(agent, st, nlu, text, out, trace):
    """Ejecuta pasos hasta que el flujo termina ("done"), una pregunta o la IA esperan a la persona ("wait"),
    la charla pasa a una persona ("handoff") o un paso falla ("error")."""
    slots = st["slots"]
    for _ in range(MAX_STEPS):
        flow, steps = steps_of(agent, st.get("flow"))
        if st["pc"] >= len(steps):
            if back(agent, st, out):
                continue
            st["flow"] = None
            return "done"
        step = steps[st["pc"]]
        st["pc"] += 1
        ctx = dict(slots, intent=nlu["intent"], confidence=nlu["confidence"], text=text,
                   entities={e["entity"]: e["value"] for e in reversed(nlu["entities"])})
        kind = step.get("type")
        if kind in WORK_STEPS:
            st["worked"] = True
        try:
            if kind == "message":
                out.append(bubble(step, st, ctx))
            elif kind == "ask":
                st["worked"] = True                          # juntó un dato: cuenta para la encuesta (handle)
                if slots.get(step.get("slot")) in (None, ""):
                    out.append(bubble(step, st, ctx))
                    st["waiting"] = step.get("slot") or ""
                    return "wait"
            elif kind == "set":
                mode = step.get("mode") or "text"
                slots[step["slot"]] = (None if mode == "clear" else cel(step.get("expr") or "null", ctx)
                                       if mode == "cel" else render(step.get("text"), ctx))
                trace.append("%s = %s" % (step["slot"], json.dumps(slots[step["slot"]], ensure_ascii=False)))
            elif kind == "http":
                scope = dict(ctx, secret=secrets(agent))       # {{ secret.X }} vale acá, nunca en mensajes
                response = http_step(step, scope)
                trace.append(mask(agent, "%s %s → %s" % (step.get("method") or "GET", render(step.get("url"), scope, url=True), response["status"])))
                for save in step.get("saves") or []:
                    if not save.get("slot"):
                        continue
                    try:
                        slots[save["slot"]] = cel(save.get("expr") or "body", dict(ctx, **response))
                    except ValueError:               # ese dato no vino en la respuesta
                        slots[save["slot"]] = None
                    trace.append(mask(agent, "%s = %s" % (save["slot"], json.dumps(slots[save["slot"]], ensure_ascii=False)[:200])))
            elif kind == "if":
                result = check(step["cond"], slots) if step.get("cond") else cel(step.get("expr") or "false", ctx) is True
                trace.append("condición → %s" % ("se cumple" if result else "no se cumple"))
                if result:
                    jump(agent, st, steps, step["goto"])
            elif kind == "goto":
                jump(agent, st, steps, step.get("goto") or step.get("flow"))
            elif kind == "function":
                fn = next((f for f in agent.get("functions") or [] if f["name"] == step.get("function")), None)
                if not fn:
                    raise ValueError("elegí qué función ejecutar" if not step.get("function") else "no existe la función «%s»" % step["function"])
                res = function_step(agent, fn, step, slots, ctx)
                trace.append(mask(agent, "función «%s» → %s (%d ms)%s" % (fn["name"], "bien" if res["ok"] else "error: " + res["error"], res["ms"],
                                                                       (" · " + res["logs"][:200]) if res.get("logs") else "")))
            elif kind == "classify":
                if not step.get("classification"):
                    raise ValueError("elegí qué clasificación aplicar")
                st.setdefault("classified", []).append(step["classification"])   # la conversación la guarda al final del turno
                trace.append("clasificada como «%s»" % step["classification"])
            elif kind == "call":
                if not any(f["name"] == step.get("flow") for f in agent["flows"]):
                    raise ValueError("elegí qué flujo llamar" if not step.get("flow") else "no existe el flujo «%s»" % step["flow"])
                if len(st.setdefault("stack", [])) >= MAX_DEPTH:
                    raise ValueError("hay más de %d flujos uno dentro de otro" % MAX_DEPTH)
                st["stack"].append({"flow": st["flow"], "pc": st["pc"], "kind": "call", "waiting": None})
                st["flow"], st["pc"] = step["flow"], 0
                trace.append("llama al flujo «%s»" % step["flow"])
            elif kind == "handoff":
                said = localized(step, st)
                out.append(render(said, ctx) if said else localized(system_of(agent)["handoff"], st))
                start_handoff(st, step.get("reason") or "lo pasó el flujo «%s»" % flow["name"])
                trace.append("pasa con una persona")
                return "handoff"
            elif kind == "file":
                sent = files.find(agent.get("id"), step.get("file")) if step.get("file") else None
                if not sent:
                    raise ValueError("no existe el archivo «%s»: subilo de nuevo" % step["file"] if step.get("file") else "elegí qué archivo enviar")
                out.append({"text": render(localized(step, st), ctx).strip() or sent["name"], "buttons": [], "file": sent})
                trace.append("envía el archivo «%s»" % sent["name"])
            elif kind == "agent":
                if agent_step(agent, st, step, text, ctx, out, trace):
                    return "wait"
            elif kind == "remind":          # lo deja en la cola de salida al guardar el turno (collect -> outbound.remind)
                if step.get("flow") and not any(f["name"] == step["flow"] for f in agent["flows"]):
                    raise ValueError("no existe el flujo «%s»" % step["flow"])
                if not step.get("flow") and not str(step.get("text") or "").strip():
                    raise ValueError("elegí qué flujo correr en el recordatorio (o escribí un texto)")
                at = outbound.remind_at(step, ctx, agent)
                if at <= outbound.clock():
                    trace.append("la hora del recordatorio ya pasó: no se programa")
                else:
                    st.setdefault("reminders", []).append({"at": at, "flow": step.get("flow") or None, "template": step.get("template") or None,
                                                           "text": render(localized(step, st), ctx) if step.get("text") else None})
                    trace.append("programa un recordatorio para %s" % time.strftime("%Y-%m-%d %H:%M", time.localtime(at)))
            elif kind == "end":
                if back(agent, st, out):                     # "end" en un subflujo vuelve al que lo llamó
                    continue
                st["flow"], st["finished"] = None, True     # el teléfono corta la llamada (phone.py)
                return "done"
        except Exception as error:  # noqa: BLE001 - un paso mal armado no tira el server: se ve en el chat
            out.append(mask(agent, "⚠ Hay un problema en el flujo «%s», paso «%s»: %s" % (flow["name"], STEP_NAMES.get(kind, kind), error)))
            stop(st)
            return "error"
    out.append("⚠ El flujo dio más de %d pasos seguidos: ¿hay flujos que se llaman entre sí sin parar?" % MAX_STEPS)
    stop(st)
    return "error"


def fallback_reply(agent, st):
    """Qué contesta cuando no entiende. «fallback» puede ser un texto o una lista: elige al azar sin repetir
    la anterior, para que no suene a máquina. Si la charla es en otro idioma usa «fallback_translations»."""
    options = (agent.get("fallback_translations") or {}).get(st.get("lang")) or agent.get("fallback")
    options = [o.strip() for o in (options if isinstance(options, list) else [options]) if isinstance(o, str) and o.strip()]
    if not options:
        return "No entendí."
    fresh = [o for o in options if o != st.get("last_fallback")] or options
    st["last_fallback"] = random.choice(fresh)
    return st["last_fallback"]


def pressed(buttons, text):
    """El valor del botón que la persona tocó (o escribió tal cual, valor o etiqueta), o None."""
    said = text.strip().lower()
    return next((b["value"] for b in buttons or [] if said in (str(b["value"]).lower(), str(b["label"]).lower())), None)


def remember(st, role, text):
    st["recent"] = (st.get("recent") or [])[-11:] + [{"role": role, "text": text}]   # contexto para la IA


def flow_for(agent, nlu, threshold):
    if nlu["intent"] is None or nlu["confidence"] < threshold:
        return None
    return next((f for f in agent["flows"] if f.get("trigger") == nlu["intent"]), None)


def doubt(agent, nlu, threshold):
    """Las dos intenciones (del usuario) más probables si las dos superan el umbral y están muy cerca."""
    conf = system_of(agent)["clarify"]
    ranking = [r for r in nlu.get("ranking") or [] if r[0] not in RESERVED.values()]
    if not conf.get("enabled") or len(ranking) < 2 or ranking[1][1] < threshold:
        return None
    return [ranking[0][0], ranking[1][0]] if ranking[0][1] - ranking[1][1] <= float(conf.get("margin") or 0) else None


FILLER = set("por favor perdón perdon eh che please sorry desculpa desculpe".split())   # cortesía que no cambia el pedido
WORD = re.compile(r"\w+")


def mostly_trigger(text, examples):
    """«¿cómo?» no se lleva «¿cómo puedo pagar?»: el mensaje tiene que ser casi el ejemplo más parecido (el que comparte
    más palabras; empate: el más largo), con a lo sumo una palabra de más sin contar las de cortesía.
    ponytail: por palabras; «¿cómo pago?» todavía pasa (una sola palabra de más)."""
    words = [w for w in WORD.findall(text.lower()) if w not in FILLER]
    shapes = [set(WORD.findall(ANNOT.sub(r"\1", e).lower())) for e in examples if e.strip()]
    if not shapes:
        return True
    closest = max(shapes, key=lambda e: (len(e & set(words)), len(e)))
    return len(words) - len(closest) <= 1


CORRECTION_CUE = re.compile(r"^\s*no\b|\b(mejor|en realidad|cambi\w*|correg\w*|corrij\w*|me equivoqu\w*|quise decir|quería decir|"
                            r"actually|instead|rather|change|i meant|na verdade|melhor|troc\w*|mud\w*|quis dizer)\b", re.I)


def corrections(agent, st, waiting, entities, text=""):
    """Slots que la persona corrige mientras se le pregunta otra cosa ("mejor de fugazza"): solo los que este
    flujo ya preguntó antes de la pregunta actual. Devuelve (índice del primer paso a repetir, nombres) o None.
    Si la pregunta actual es de texto libre, cualquier mensaje es una respuesta posible («Corrientes 1234» a «¿dirección?»
    no cambia la cantidad): ahí corrige solo con una señal explícita («mejor 3», «no, en realidad…»)."""
    spec = next((s for s in agent["slots"] if s["name"] == waiting), {})
    if not spec.get("entity") and not CORRECTION_CUE.search(text or ""):
        return None
    _, steps = steps_of(agent, st.get("flow"))
    here, first, names = st["pc"] - 1, None, []
    for slot in agent["slots"]:
        value, old = entities.get(slot.get("entity")), st["slots"].get(slot["name"])
        if slot["name"] == waiting or value is None or old in (None, "") or str(old).lower() == str(value).lower():
            continue
        index = next((i for i, s in enumerate(steps[:here]) if s.get("type") == "ask" and s.get("slot") == slot["name"]), None)
        if index is not None:
            st["slots"][slot["name"]] = value
            names.append(slot["name"])
            first = index if first is None else min(first, index)
    return (first, names) if names else None


def turn(agent, st, out, nlu, trace, **extra):
    """Arma el resultado del turno con lo que dijo el bot (textos o {"text", "buttons"})."""
    replies = [o if isinstance(o, dict) else {"text": o, "buttons": []} for o in out]
    replies = [r for r in replies if r["text"]]
    if extra.pop("again", False) is False and replies:
        st["last_bot"] = replies                      # para «repetí»
    buttons = replies[-1]["buttons"] if replies else []
    if buttons:
        st["buttons"] = buttons                       # la próxima respuesta puede ser uno de estos
    for r in replies:
        remember(st, "bot", r["text"])
    result = {"messages": [r["text"] for r in replies], "buttons": buttons, "replies": replies, "nlu": nlu,
              "slots": st["slots"], "trace": trace, "answer_to": None, "rejected": False, "fallback": False,
              "handoff": bool((st.get("handoff") or {}).get("active")), "language": st.get("lang") or languages(agent)[0],
              "via": None, "sources": [], "tools": st.pop("tool_log", [])}
    result.update(extra)
    return result


def handle(agent, st, text, parse=parse):
    """Un turno de conversación. `st` es el estado de la sesión y se modifica acá."""
    conf, threshold = system_of(agent), float(agent.get("threshold") or 0)
    slots = st.setdefault("slots", {})
    for slot in agent["slots"]:
        slots.setdefault(slot["name"], None)
    language_of(agent, st, text)
    remember(st, "user", text)
    st.pop("finished", None)
    out, trace = [], []
    empty = {"intent": None, "confidence": 0.0, "ranking": [], "entities": []}
    if (st.get("handoff") or {}).get("active"):         # la charla la tiene una persona: el bot no habla
        return turn(agent, st, out, empty, ["la conversación la atiende una persona"])
    on_reply = st.pop("on_reply", None)                 # contestó a una plantilla de WhatsApp (outbound.py): corre ese flujo
    kept = {k: st[k] for k in ("waiting", "clarify", "csat_waiting", "buttons") if st.get(k) is not None}
    button = pressed(st.pop("buttons", None), text)
    said = button or text
    if st.pop("csat_waiting", None):
        score = re.fullmatch(r"\s*([1-5])(?:\s*/\s*5)?\s*", said)
        if score:
            st["csat"] = int(score.group(1))
            return turn(agent, st, [THANKS.get(st["lang"], THANKS["es"])], empty, ["encuesta: %d" % st["csat"]], csat=st["csat"])
    choices = st.pop("clarify", None)
    nlu = parse(agent, said)
    picked = next((c for c in choices or [] if said.strip().lower() == c.lower()), None)
    if picked:                                          # contestó «¿quisiste decir A o B?»
        nlu = dict(nlu, intent=picked, confidence=1.0)
        trace.append("eligió «%s»" % picked)
    entities = {e["entity"]: e["value"] for e in reversed(nlu["entities"])}
    waiting = st.pop("waiting", None)
    busy = waiting is not None and st.get("flow")
    before = slots.get(waiting) if waiting else None    # si resulta que era otra pregunta, el slot vuelve a esto
    hint = st.pop("hint", None)     # opción que el bot acaba de explicar: un «ah, entonces sí» la elige
    asked = ((st.get("last_bot") or [{}])[-1] or {}).get("text") or ""
    for slot in agent["slots"]:
        # El slot se llena solo con su entidad. Mientras se espera una respuesta, solo el slot preguntado:
        # si no, el número de una dirección terminaría guardado como cantidad.
        if slot.get("entity") in entities and waiting in (None, slot["name"]):
            slots[slot["name"]] = entities[slot["entity"]]
    waited_entity = next((s.get("entity") for s in agent["slots"] if s["name"] == waiting), None) if busy else None
    said_values = {e["value"] for e in nlu["entities"] if waited_entity and e["entity"] == waited_entity}
    if len(said_values) > 1:
        # «hablar DE UNA urgencia, NO PUEDO respirar»: trae un «sí» y un «no». No se elige por la palabra que aparece primero
        slots[waiting] = before
        entities.pop(waited_entity, None)
        trace.append("respuesta ambigua: %s" % " y ".join(sorted(map(str, said_values))))
    if busy and button is not None and waiting:
        slots[waiting] = button                          # tocó un botón de la pregunta
    # Mientras espera una respuesta, "30.123.456" o "Pedro" pueden parecerse a «repetí» o «cancelar»: ahí los comportamientos
    # del sistema (y las interrupciones) piden más seguridad, y no cuentan si el mensaje ya trajo el dato que se pedía.
    strict = max(threshold, 0.75) if busy else threshold
    floor = max(strict, 0.65)        # «repetí», «cancelar»: frases cortas que se parecen a cualquier cosa
    spec_waiting = next((s for s in agent["slots"] if s["name"] == waiting), {}) if busy else {}
    if busy and not spec_waiting.get("entity") and spec_waiting.get("fill") != "ai":
        floor = max(floor, 0.92)     # pregunta de texto libre: «jiménez» es una respuesta, no «repetí»
    answered = busy and waiting and any(s["name"] == waiting and s.get("entity") in entities for s in agent["slots"])
    system = (nlu["intent"] if nlu["intent"] in RESERVED.values() and nlu["confidence"] >= floor and button is None
              and not answered else None)
    if system == "__cancel__":
        stop(st)
        return turn(agent, st, [localized(conf["cancel"], st)], nlu, ["cancela lo que estaba haciendo"])
    if system == "__repeat__" and (not st.get("last_bot") or not mostly_trigger(said, conf["repeat"].get("examples") or [])):
        system = None                                   # nada que repetir, o era una pregunta más larga: sigue normal
    if system == "__repeat__":
        st.update(kept)
        return turn(agent, st, list(st.get("last_bot") or []), nlu, ["repite lo último"], again=True)
    if system == "__handoff__":
        start_handoff(st, "pidió hablar con una persona")
        return turn(agent, st, [localized(conf["handoff"], st)], nlu, ["pasa con una persona"])
    answer_to, rejected, via, sources = waiting, False, None, []
    urgent = flow_for(agent, nlu, strict) if busy and button is None else None
    if urgent and urgent.get("interrupts") == "always" and urgent["name"] != st["flow"]:
        slots[waiting] = before
        st["flow"], st["pc"], st["stack"] = urgent["name"], 0, []    # no vuelve: lo urgente reemplaza lo que se hacía
        trace.append("«%s» corta todo (interrupts: always)" % urgent["name"])
        busy, answer_to = None, None
    if st.get("agent") and st.get("flow"):              # la charla está en un paso de IA: le toca a ella
        answer_to = None
    elif busy:
        # «¿qué es presencial?» a «¿presencial o virtual?»: se contesta (base de conocimiento) y se vuelve a preguntar
        side = hook(brain.side_question, agent, st, text, asked) if button is None else None
        fixed = None if side else corrections(agent, st, waiting, entities, text) if conf["correction"].get("enabled") else None
        if side:
            asked_about = slots.get(waiting)            # «¿qué es presencial?» trajo «presencial»
            slots[waiting] = before
            if asked_about not in (None, ""):
                st["hint"] = {"slot": waiting, "value": asked_about}
            out.append(side["text"])
            st["pc"] -= 1
            trace.append("pregunta otra cosa: la contesta y vuelve a preguntar")
            answer_to, via, sources = None, side.get("via"), side.get("sources") or []
        elif fixed:
            st["pc"] = fixed[0] + 1                     # sigue desde después de esa pregunta: se recalcula lo que sigue
            out.append(localized(conf["correction"], st))
            trace.append("corrige " + ", ".join(fixed[1]))
            answer_to = None
        elif slots.get(waiting) in (None, ""):
            read = None                                 # lo que entendió la IA del turno (si se le preguntó)
            spec = next((s for s in agent["slots"] if s["name"] == waiting), {})
            entity = next((e for e in agent["entities"] if e["name"] == spec.get("entity")), None)
            if spec.get("fill") == "ai":
                value = hook(brain.fill_slot, agent, spec, text, dict(slots, text=text, entities=entities, lang=st["lang"]))
                if value in (None, ""):
                    rejected = True
                else:
                    slots[waiting], via = value, "ia"
            elif entity and (entity.get("regex") or entity.get("values") or entity.get("kind") == "date"):
                # Se esperaba un formato u opción y no vino. En este orden:
                # 1. una contrapropuesta que el paso acepta («also»): «jueves» a «¿te sirve?». El slot queda vacío y el
                #    flujo sigue: los pasos que vienen leen `entities` y deciden (buscar ese día, cambiar de médico…).
                #    Va antes que la IA: la IA leyó «jueves» como «sí» y confirmó una cita.
                # 2. con IA, el turno entero con la charla reciente: contesta (con otras palabras, o «entonces sí»
                #    después de una explicación), pregunta otra cosa, pide otra acción, o nada (saludar o agradecer
                #    con una pregunta pendiente no interrumpe). Sin IA: interrumpe una intención clara, si no «No reconocí».
                _, steps = steps_of(agent, st["flow"])
                ask = steps[st["pc"] - 1] if 0 < st["pc"] <= len(steps) else {}
                also = [e for e in ask.get("also") or [] if e in entities] if ask.get("type") == "ask" else []
                agreed = not also and hint and hint.get("slot") == waiting and brain.affirmative(text)
                # por significado primero (milisegundos); la IA generativa solo si eso no está seguro
                read = None if also or agreed else hook(read_answer, agent, entity, text, st["flow"], st.get("lang") or "es")
                how = "por significado" if read else "la IA"
                if read is None and not (also or agreed):
                    read = hook(brain.understand, agent, st, text, asked, entity, st["flow"])
                if also:
                    trace.append("contestó con otro dato: %s" % ", ".join(also))
                elif agreed:
                    slots[waiting] = hint["value"]
                    trace.append("asintió a la opción que se le explicó: «%s»" % hint["value"])
                elif read and read["tipo"] == "responde" and read["opcion"]:
                    slots[waiting], via = read["opcion"], ("significado" if how == "por significado" else "ia")
                    trace.append("entendió %s «%s» como «%s»%s" % (how, text, read["opcion"],
                                                                 " (parecido a «%s»)" % read["por"] if read.get("por") else ""))
                elif read and read["tipo"] == "pregunta":
                    side = hook(brain.answer, agent, st, text) or {}
                    slots[waiting] = before
                    out.append(side.get("text") or REJECT.get(st["lang"], REJECT["es"]))
                    st["pc"] -= 1
                    trace.append("la IA vio una pregunta: la contesta y vuelve a preguntar")
                    answer_to, via, sources = None, side.get("via"), side.get("sources") or []
                else:
                    rejected = True
                    if read:
                        trace.append("%s lo entendió como «%s»" % (how, read["accion"] or read["tipo"]))
            else:
                slots[waiting] = text
            if rejected and read is not None:   # con IA, interrumpe solo lo que la IA vio como otra acción
                other = next((f for f in agent["flows"] if read.get("accion") and f.get("trigger") == read["accion"]), None)
            else:
                other = flow_for(agent, nlu, strict) if rejected else None
                if other and other.get("interrupts", True) is False:
                    trace.append("«%s» no interrumpe una pregunta" % other["name"])
                    other = None
            if other and other["name"] != st["flow"] and len(st.get("stack") or []) < MAX_DEPTH:
                # ponytail: solo interrumpe una respuesta inválida; una pregunta de texto libre toma cualquier cosa
                st.setdefault("stack", []).append({"flow": st["flow"], "pc": st["pc"] - 1, "kind": "interrupt", "waiting": waiting})
                st["flow"], st["pc"] = other["name"], 0
                trace.append("interrumpe con «%s»; después vuelve a «%s»" % (other["name"], st["stack"][-1]["flow"]))
                answer_to, rejected = None, False
            elif rejected:
                small_talk = read is not None and read.get("tipo") == "nada"
                if not small_talk:                           # a un «gracias» no se le dice «No reconocí ese dato»
                    out.append(REJECT.get(st["lang"], REJECT["es"]))
                st["pc"] -= 1
    else:
        forced = next((f for f in agent["flows"] if on_reply and f["name"] == on_reply), None)
        if forced:
            picked = True
            trace.append("contesta al mensaje que le mandamos: empieza «%s»" % forced["name"])
        unsure = None if picked else doubt(agent, nlu, threshold)
        ai = agent.get("ai") or {}
        if ai.get("enabled") and ai.get("rescue_intents", True) and not picked and (nlu["confidence"] < threshold or unsure):
            better = hook(brain.rescue_intent, agent, said, nlu, st) or nlu
            if better.get("via"):
                nlu, via, unsure = dict(nlu, **better), better["via"], None
                trace.append("la IA eligió «%s»" % nlu["intent"])
        if unsure and button is None:
            st["clarify"] = unsure
            question = localized(conf["clarify"], st).replace("…", " %s o %s" % tuple(unsure))
            return turn(agent, st, [{"text": question, "buttons": [{"label": i, "value": i} for i in unsure]}], nlu, trace)
        flow = forced or flow_for(agent, nlu, threshold)
        if not flow:
            answer = hook(brain.fallback, agent, st, text)
            if answer and answer.get("text"):
                return turn(agent, st, [answer["text"]], nlu, trace, fallback=True, via=answer.get("via") or "ia",
                            sources=answer.get("sources") or [])
            return turn(agent, st, [fallback_reply(agent, st)], nlu, trace, fallback=True, via=via)
        st["flow"], st["pc"], st["stack"] = flow["name"], 0, []
        trace.append("empieza el flujo «%s»" % flow["name"])
    with telemetry.span("flow.run", **{"parla.flow": st.get("flow")}) as sp:
        status = run(agent, st, nlu, text, out, trace)
        sp.set(**{"parla.flow.status": status})
        sp.outcome = "error" if status == "error" else None
    if status == "done":
        # encuesta: solo si el flujo que termina hizo algo (preguntó, consultó, ejecutó, cerró la charla); no tras un saludo
        if conf["csat"].get("enabled") and not st.get("csat_asked") and st.pop("worked", False):
            st["csat_asked"] = st["csat_waiting"] = True
            out.append({"text": localized(conf["csat"], st), "buttons": [{"label": str(n), "value": str(n)} for n in range(1, 6)]})
        elif conf["anything_else"].get("enabled"):
            out.append(localized(conf["anything_else"], st))
    # answer_to: el mensaje se tomó como respuesta a la pregunta por ese slot, no como una intención nueva
    return turn(agent, st, out, nlu, trace, answer_to=answer_to, rejected=rejected, via=via, sources=sources)


START = "__start__"   # trigger de un flujo que corre apenas empieza la conversación


def begin(agent, st, data=None, flow=START):
    """Empieza una conversación: guarda los datos que vienen de afuera (un IVR, un CRM) en los slots que se
    llaman igual y corre el flujo de inicio, si hay. Devuelve el resultado del turno y los datos ignorados.
    «idioma» / «language» / «lang» eligen el idioma de la charla (si el agente lo tiene)."""
    slots = st.setdefault("slots", {})
    for slot in agent["slots"]:
        slots.setdefault(slot["name"], None)
    names = {s["name"] for s in agent["slots"]}
    data = data or {}
    for key, value in data.items():
        if key in names:
            slots[key] = value
    for key in ("idioma", "language", "lang"):
        if str(data.get(key) or "").lower()[:2] in (agent.get("languages") or []):
            st["lang"] = str(data[key]).lower()[:2]
    nlu = {"intent": None, "confidence": 0.0, "ranking": [], "entities": []}
    used = ["%s = %s" % (k, json.dumps(v, ensure_ascii=False)) for k, v in data.items() if k in names]
    out, trace = [], (["datos iniciales: " + ", ".join(used)] if used else [])
    flow = next((f for f in agent["flows"] if (f.get("trigger") == START if flow == START else f["name"] == flow)), None) if flow else None
    if flow:
        st["flow"], st["pc"], st["stack"] = flow["name"], 0, []
        trace.append("empieza el flujo «%s»" % flow["name"])
        run(agent, st, nlu, "", out, trace)
    return turn(agent, st, out, nlu, trace), sorted(k for k in data if k not in names)


# ---------- Agentes en disco + HTTP ----------

DEMO = {
    "name": "Seguimiento de pedidos", "threshold": 0.75, "fallback": "No entendí, ¿me lo decís de otra forma?",
    "intents": [
        {"name": "Saludar", "examples": ["hola", "buen día", "buenas tardes", "qué tal"]},
        {"name": "Consultar pedido", "examples": [
            "quiero saber dónde está mi pedido", "cómo viene el pedido [12](numero_pedido)",
            "estado del pedido [7](numero_pedido)", "necesito rastrear una compra", "cuándo llega mi pedido"]},
    ],
    "entities": [{"name": "numero_pedido", "kind": "number", "regex": r"\b\d+(?:[.,]\d+)?\b", "values": [], "color": 0}],
    "slots": [{"name": "numero_pedido", "entity": "numero_pedido"}, {"name": "codigo_respuesta"},
              {"name": "detalle"}, {"name": "entregado"}],
    "flows": [
        {"name": "Saludo", "trigger": "Saludar", "steps": [
            {"type": "message", "text": "¡Hola! Decime el número de tu pedido y te cuento cómo viene."}]},
        {"name": "Estado del pedido", "trigger": "Consultar pedido", "steps": [
            {"type": "ask", "slot": "numero_pedido", "text": "¿Cuál es el número de pedido? (probá del 1 al 200)"},
            {"type": "http", "method": "GET", "url": "https://jsonplaceholder.typicode.com/todos/{{ numero_pedido }}",
             "headers": [], "body": "", "saves": [
                 {"expr": "status", "slot": "codigo_respuesta"}, {"expr": "body.title", "slot": "detalle"},
                 {"expr": "body.completed", "slot": "entregado"}]},
            {"type": "if", "cond": {"var": "codigo_respuesta", "op": "eq", "value": "200"},
             "then": [
                 {"type": "if", "cond": {"var": "entregado", "op": "eq", "value": "true"},
                  "then": [{"type": "message", "text": "El pedido {{ numero_pedido }} ({{ detalle }}) ya fue entregado."}],
                  "else": [{"type": "message", "text": "El pedido {{ numero_pedido }} ({{ detalle }}) está en camino."}]}],
             "else": [{"type": "message", "text": "No encontré ningún pedido con el número {{ numero_pedido }}."}]},
            {"type": "set", "slot": "numero_pedido", "mode": "clear"}]},
    ],
}
BLANK = {"name": "Nuevo agente", "threshold": 0.75, "fallback": "No entendí, ¿me lo decís de otra forma?",
         "intents": [], "entities": [], "slots": [], "flows": [], "classifications": [], "functions": []}
# functions: [{"name", "description", "language": "python"|"javascript", "inputs": [slot...], "code"}]; el código
# define run(inputs) y devuelve un objeto. Un paso {"type": "function", "function": name, "saves": [...],
# "auto_save": true} la ejecuta (runner.py: proceso aparte con tiempo máximo).
# classifications: [{"name", "color", "description"}]. Un paso {"type": "classify", "classification": name} marca la
# conversación; cada conversación guarda [{"name", "at"}] y con eso salen los reportes.
# Conversaciones: una fila por conversación en DATA/parla.db (db.py), así se pueden revisar después y siguen vivas
# si el servidor se reinicia. retention_days del agente (o PARLA_RETENTION_DAYS) borra las viejas: ver cleanup().
MAX_HISTORY = 500            # mensajes guardados por conversación
SESSION_ID = re.compile(r"[A-Za-z0-9_@+-][A-Za-z0-9_.@+-]{0,99}")


def path(agent_id, ext=".json"):
    if not (isinstance(agent_id, str) and re.fullmatch(r"[0-9a-f]{8}", agent_id)):
        raise ValueError("no existe ese agente")      # ni «../users» ni nada que salga de la carpeta
    return os.path.join(AGENTS, agent_id + ext)


def load(agent_id):
    with open(path(agent_id), encoding="utf-8") as f:
        agent = json.load(f)
    agent["system"] = system_of(agent)       # la interfaz siempre recibe la estructura completa
    return agent


_voiced = {}                 # agente -> hash de las frases que ya se mandaron a pregenerar
_warming = {}                # agente -> (frases, idioma) pendientes, o None: su hilo está trabajando y no hay nada nuevo
_warming_lock = threading.Lock()


def store(agent):
    write_json(path(agent["id"]), agent, indent=2)
    tts = voice.settings(agent)["tts"]
    if voice.ready(tts):                          # con voz (piper o un proveedor): las frases fijas quedan listas para las llamadas
        job = (spoken_texts(agent), languages(agent)[0], tts)
        key = hash((tuple(job[0]), job[1], json.dumps({k: v for k, v in tts.items() if k != "api_key"}, sort_keys=True)))
        with _warming_lock:                       # la interfaz guarda cada ~400 ms: un hilo por agente y solo si cambió algo
            if _voiced.get(agent["id"]) == key:
                return agent
            _voiced[agent["id"]] = key
            start = agent["id"] not in _warming
            _warming[agent["id"]] = job
        if start:
            threading.Thread(target=_prewarm, args=(agent["id"],), daemon=True).start()
    return agent


def _prewarm(agent_id):
    while True:
        with _warming_lock:
            job = _warming[agent_id]
            if job is None:
                del _warming[agent_id]
                return
            _warming[agent_id] = None
        voice.prewarm(*job)


def spoken_texts(agent):
    """Todo lo que el bot puede decir tal cual: mensajes, preguntas, pasar a una persona, el «no entendí» y el
    «No reconocí ese dato». voice.prewarm se saltea las frases con {{ }}."""
    out = [fallback for fallback in ([agent.get("fallback")] if isinstance(agent.get("fallback"), str) else agent.get("fallback") or [])]
    out.append(REJECT.get(languages(agent)[0], REJECT["es"]))
    def walk(steps):
        for s in steps or []:
            if s.get("type") in ("message", "ask", "handoff", "file") and isinstance(s.get("text"), str):
                out.append(s["text"])
            walk(s.get("then")); walk(s.get("else"))
    for flow in agent.get("flows") or []:
        walk(flow.get("steps"))
    return [t for t in out if isinstance(t, str) and t.strip()]


def imported(data):
    """Valida un agente exportado (con o sin el sobre {"parla": 1, "agent": ...}) y lo deja listo para crear."""
    agent = data.get("agent") if isinstance(data.get("agent"), dict) else data
    for key in ("intents", "entities", "slots", "flows", "classifications", "functions", "tests"):
        if not isinstance(agent.get(key, []), list):
            raise ValueError("el archivo no es un agente de Parla: «%s» tiene que ser una lista" % key)
    if not any(agent.get(key) for key in ("intents", "entities", "slots", "flows")):
        raise ValueError("el archivo no es un agente de Parla o está vacío")
    clean = {k: v for k, v in agent.items() if k not in EDITABLE_ONLY}   # se entrena de nuevo al abrirlo; versiones no viajan
    return {**BLANK, **clean, "name": str(agent.get("name") or BLANK["name"]).strip()[:80]}


def all_agents():
    # solo <id>.json: al lado viven <id>.model.json, <id>.secrets.json, etc., que no son agentes
    return [load(name[:-5]) for name in sorted(os.listdir(AGENTS))
            if re.fullmatch(r"[0-9a-f]{8}\.json", name)]


def slug(text):
    """'Pizzería Don Luis' -> 'pizzeria-don-luis': el nombre del bot para usar en una URL."""
    plain = unicodedata.normalize("NFD", text).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", plain.lower()).strip("-")


_names = {}   # archivo -> ((mtime, tamaño), (id del archivo, id, nombre)): find_bot corre hasta 3 veces por pedido del widget


def agent_index():
    """[(id del archivo, id, nombre)] de todos los agentes, sin leer de nuevo los que no cambiaron."""
    out = []
    for name in sorted(os.listdir(AGENTS)):
        if not re.fullmatch(r"[0-9a-f]{8}\.json", name):
            continue
        stat = os.stat(os.path.join(AGENTS, name))
        stamp = (stat.st_mtime_ns, stat.st_size)
        hit = _names.get(os.path.join(AGENTS, name))
        if hit is None or hit[0] != stamp:
            agent = load(name[:-5])
            hit = _names[os.path.join(AGENTS, name)] = (stamp, (name[:-5], agent["id"], agent["name"]))
        out.append(hit[1])
    return out


def find_bot(ref):
    """Un bot por id, por nombre exacto (sin importar mayúsculas) o por slug. None si no existe o es ambiguo."""
    agents = agent_index()
    for test in (lambda a: a[1] == ref, lambda a: a[2].lower() == ref.lower(), lambda a: slug(a[2]) == slug(ref)):
        matches = [a for a in agents if test(a)]
        if len(matches) == 1:
            return load(matches[0][0])
        if matches:
            return None
    return None


def now():
    return time.strftime("%Y-%m-%dT%H:%M:%S")


def settings_of(agent_id):
    """El borrador del agente para leer sus ajustes de guardado (retention_days, pii_redaction); {} si no existe."""
    try:
        return load(agent_id)
    except Exception:  # noqa: BLE001 - agente borrado o corrupto: sin ajustes
        return {}


def load_session(agent_id, sid):
    if not SESSION_ID.fullmatch(sid or ""):
        return None
    rows = db.q("SELECT record FROM sessions WHERE agent_id = ? AND session_id = ?", (agent_id, sid))
    return json.loads(rows[0][0]) if rows else None


def save_session(agent_id, record):
    """Guarda la conversación. Con pii_redaction, lo guardado va con los datos personales tapados; el registro en
    memoria (el turno que está corriendo) no se toca."""
    cats = pii.categories(settings_of(agent_id).get("pii_redaction"))
    stored = pii.record(record, cats) if cats else record
    db.q("INSERT OR REPLACE INTO sessions (agent_id, session_id, channel, started, updated, handoff, record) VALUES (?, ?, ?, ?, ?, ?, ?)",
         (agent_id, record["sessionId"], record.get("channel"), record.get("started"), record.get("updated") or now(),
          int(bool((record.get("handoff") or {}).get("active"))), json.dumps(stored, ensure_ascii=False)))
    bus.publish("session:%s:%s" % (agent_id, record["sessionId"]), {"type": "saved", "record": stored})   # WebSocket/SSE
    if record.get("handoff"):
        bus.publish("inbox:" + agent_id, {"type": "inbox"})


def delete_session(agent_id, sid):
    db.q("DELETE FROM sessions WHERE agent_id = ? AND session_id = ?", (agent_id, sid))


def open_session(agent_id, sid, channel, environment="production"):
    """La conversación con ese sessionId, o una nueva. Si estaba terminada, sigue con la memoria en blanco.
    Una conversación nueva (o que vuelve a empezar) queda atada a la versión que tiene ese entorno ahora."""
    record = load_session(agent_id, sid)
    if record is None or record["ended"]:
        number, _ = target(load(agent_id), environment)
        record = record or {"sessionId": sid, "channel": channel, "started": now(), "history": []}
        record.update(updated=now(), ended=False, state={}, environment=environment, version=number)
        record.pop("handoff", None)
        handoff.emit_by_id(agent_id, "conversation.started", record)
    return record


def session_agent(agent_id, record):
    """La definición del bot con la que sigue esta conversación (su versión, o el borrador)."""
    number = record.get("version")
    if number is None:
        return None, load(agent_id)
    return number, {**load_version(agent_id, number)["agent"], "id": agent_id}


def end_session(agent_id, sid):
    record = load_session(agent_id, sid)
    if record:
        was_open = not record["ended"]
        record.update(ended=True, state={}, updated=now())
        record.pop("handoff", None)
        save_session(agent_id, record)
        if was_open:
            handoff.emit_by_id(agent_id, "conversation.ended", record, resolution=record.get("resolution"))
    return record


def outbound_session(agent_id, sid, channel, data, flow=START, campaign=None, on_reply=None, note=None, text=None):
    """El bot escribe primero (outbound.py): la conversación de producción empieza de nuevo (conserva lo charlado y la
    hora del último mensaje de la persona), con los datos en los slots y el flujo pedido (None = el «Al empezar»; ""
    = ninguno). on_reply: el flujo que corre cuando la persona conteste (después de una plantilla de WhatsApp)."""
    end_session(agent_id, sid)
    record = open_session(agent_id, sid, channel, "production")
    result, ignored = begin(session_agent(agent_id, record)[1], record["state"], data, START if flow is None else flow)
    if text:
        said = render(text, dict(record["state"].get("slots") or {}))
        result["replies"].append({"text": said, "buttons": []})
        result["messages"].append(said)
    if on_reply:
        record["state"]["on_reply"] = on_reply
    if campaign:
        record["campaign"] = record["state"]["campaign"] = campaign
    telemetry.count("parla_conversations_started_total", agent=agent_id, channel=telemetry.channel(channel))
    record["updated"] = now()
    record["history"].append({"from": "event", "text": note or "Mensaje proactivo", "at": record["updated"], "outbound": True,
                              "data": {k: v for k, v in (data or {}).items() if k not in ignored}, **({"campaign": campaign} if campaign else {})})
    record["history"] += bot_entries(result, record["updated"])
    collect(record, agent_id)
    save_session(agent_id, record)
    return record, result


def optout_turn(agent, record, text, reply):
    """Pidió la baja (STOP, BAJA…): se anota, se confirma y el bot no corre."""
    record["updated"] = now()
    record["history"] += [{"from": "user", "text": text, "at": record["updated"], "intent": None, "optout": True},
                          {"from": "event", "text": "Pidió no recibir más mensajes", "at": record["updated"]},
                          {"from": "bot", "text": reply, "at": record["updated"]}]
    save_session(agent["id"], record)
    result = {"messages": [reply], "buttons": [], "replies": [{"text": reply, "buttons": []}], "handoff": False,
              "language": (record["state"].get("lang") or languages(agent)[0]), "via": None, "sources": []}
    return dict(session_info(agent, record), messages=[reply], understood=None, optout=True, **turn_fields(result, record))


def collect(record, agent_id):
    """Pasa a la conversación las clasificaciones que aplicó el flujo en este turno (sin repetir) y deja en la cola
    de salida los recordatorios que programó (paso remind)."""
    marks = record.setdefault("classifications", [])
    for name in record["state"].pop("classified", []):
        if name not in [m["name"] for m in marks]:
            marks.append({"name": name, "at": now()})
            record["history"].append({"from": "event", "text": "Clasificada como «%s»" % name, "at": now(), "classification": name})
    for item in record["state"].pop("reminders", []):           # pasos «remind» de este turno: a la cola de salida
        record["history"].append({"from": "event", "text": outbound.remind(agent_id, record, item), "at": now(), "reminder": True})


def bot_entries(result, at):
    """Lo que dijo el bot, y antes las herramientas que usó la IA (con las claves tapadas; pii_redaction las tapa al guardar)."""
    return [{"from": "event", "text": "La IA usó «%s» → %s" % (t["tool"], "bien" if t["ok"] else "error"), "at": at, "tool": t}
            for t in result.get("tools") or []] + [dict({"from": "bot", "text": r["text"], "at": at}, **({"buttons": r["buttons"]} if r["buttons"] else {}),
                 **({"file": r["file"]} if r.get("file") else {})) for r in result["replies"]]


def sync(record):
    """Copia al registro de la conversación lo que la bandeja y los reportes leen del estado."""
    state = record["state"]
    if state.get("handoff"):
        record["handoff"] = state["handoff"]
    if state.get("csat"):
        record["csat"] = state["csat"]


def active_sessions():
    """Para el gauge parla_active_sessions: conversaciones sin terminar con movimiento en los últimos 30 minutos.
    ponytail: recorre las filas recientes en cada scrape; con millones de charlas, una columna «ended» con índice."""
    rows = db.q("SELECT agent_id, count(*) FROM sessions WHERE updated >= ? AND json_extract(record, '$.ended') = 0 GROUP BY agent_id",
                (ago(30 / 1440),))
    return [({"agent": agent_id}, n) for agent_id, n in rows]


def measure(agent, record, result, text, was_handoff, sp):
    """Métricas y atributos del turno: ids, intención, confianza y estado; el texto solo con PARLA_OTEL_CONTENT=1, tapado."""
    nlu, aid, channel = result["nlu"], agent["id"], telemetry.channel(record.get("channel"))
    outcome = ("fallback" if result["fallback"] else "answer" if result["answer_to"] else
               "system" if str(nlu["intent"] or "").startswith("__") else "matched" if nlu["intent"] else "none")
    telemetry.count("parla_turns_total", agent=aid, channel=channel, environment=record.get("environment", "production"))
    telemetry.count("parla_intent_outcomes_total", agent=aid, outcome=outcome)
    if result["handoff"] and not was_handoff:
        telemetry.count("parla_handoffs_total", agent=aid, channel=channel)
    if result.get("csat"):
        telemetry.observe("parla_csat_score", result["csat"], agent=aid)
    sp.set(**{"parla.intent": nlu["intent"], "parla.confidence": round(nlu["confidence"], 3), "parla.outcome": outcome,
              "parla.flow": record["state"].get("flow"), "parla.via": result["via"], "parla.handoff": result["handoff"]})
    if telemetry.CONTENT and sp is not telemetry.NOOP:
        cover = lambda t: mask(agent, pii.redact(t))
        sp.set(**{"parla.message": cover(text), "parla.reply": cover(" / ".join(result["messages"]))})


def converse(agent_id, record, text):
    """Un turno contra la última versión entrenada. Lo usan el chat de prueba y la API; queda guardado."""
    number, agent = session_agent(agent_id, record)
    snap = trained_for(agent_id, number)
    state = record["state"]
    before = {"flow": state.get("flow"), "waiting": state.get("waiting") if state.get("flow") else None}   # para medir abandono
    was_handoff = bool((state.get("handoff") or {}).get("active"))
    with telemetry.span("parla.turn", **{"parla.agent.id": agent_id, "parla.channel": record.get("channel"),
                                         "parla.environment": record.get("environment"), "parla.version": number}) as sp:
        topic = "session:%s:%s" % (agent_id, record["sessionId"])
        llm.STREAM.sink = (lambda event: bus.publish(topic, event)) if bus.has(topic) else None   # tokens de la IA en vivo
        try:
            result = handle(agent, state, text, parse=lambda a, t: parse(snap["data"], t, snap["tagger"], snap.get("index")))
        finally:
            llm.STREAM.sink = llm.STREAM.last = None
        measure(agent, record, result, text, was_handoff, sp)
    nlu = result["nlu"]
    record["updated"] = now()
    record["history"].append({"from": "user", "text": text, "at": record["updated"], "intent": nlu["intent"],
                              "confidence": round(nlu["confidence"], 3), "answer_to": result["answer_to"],
                              "entities": [{"entity": e["entity"], "value": e["value"]} for e in nlu["entities"]],
                              "fallback": result["fallback"], "via": result["via"], **before})
    record["history"] += bot_entries(result, record["updated"])
    sync(record)
    collect(record, agent_id)
    del record["history"][:-MAX_HISTORY]
    hooks(agent_id, record, result, text, was_handoff)
    save_session(agent_id, record)
    return result


def hooks(agent_id, record, result, text, was_handoff):
    """Después de un turno: completa el handoff que empezó (modo, resumen) y encola los eventos de los webhooks."""
    draft = settings_of(agent_id)
    if result["handoff"] and not was_handoff:
        handoff.started(draft, record)
    if not handoff.webhooks(draft):
        return
    handoff.emit(draft, "message.user", record, text=text)
    for said in result["messages"]:
        handoff.emit(draft, "message.bot", record, text=said)
    if result.get("csat"):
        handoff.emit(draft, "csat.received", record, score=result["csat"])


def bot_info(agent):
    return {"id": agent["id"], "name": agent["name"], "slug": slug(agent["name"]), "online": True,
            "trained_at": (agent.get("trained") or {}).get("at"), "intents": [i["name"] for i in agent["intents"]],
            "environments": {e: (agent.get("environments") or {}).get(e) for e in ENVIRONMENTS}}


def session_info(agent, record):
    state = record["state"]
    return {"bot": {"id": agent["id"], "name": agent["name"]}, "sessionId": record["sessionId"],
            "channel": record["channel"], "started": record["started"], "updated": record["updated"], "ended": record["ended"],
            "slots": dict(state.get("slots", {})), "waiting_for": state.get("waiting") if state.get("flow") else None,
            "flow": state.get("flow"), "classifications": [m["name"] for m in record.get("classifications", [])],
            "environment": record.get("environment", "production"), "version": record.get("version"),
            "handoff": record.get("handoff"), "language": state.get("lang"), "next": len(record["history"])}


def turn_fields(result, record):
    """Lo nuevo de cada turno en la API: botones, persona humana, idioma y quién respondió."""
    return {"buttons": result["buttons"], "replies": result["replies"], "handoff": result["handoff"], "language": result["language"],
            "via": result["via"], "sources": result["sources"], "next": len(record["history"])}


def session_summary(record):
    texts = [h for h in record["history"] if h["from"] == "user"]
    preload = next((h.get("data") for h in record["history"] if h["from"] == "event" and h.get("data")), None)
    return {"sessionId": record["sessionId"], "channel": record["channel"], "started": record["started"],
            "updated": record["updated"], "ended": record["ended"], "messages": len(record["history"]),
            "last_message": record["history"][-1]["text"][:120] if record["history"] else None,
            "first_message": texts[0]["text"][:120] if texts else None, "data": preload,
            "classifications": [m["name"] for m in record.get("classifications", [])],
            "environment": record.get("environment", "production"), "version": record.get("version")}


def sessions_of(agent_id, query):
    """Conversaciones guardadas, la más reciente primero, filtradas por channel, classification ("__none__" = sin
    clasificar), fechas from/to (YYYY-MM-DD, por el día en que empezaron) y handoff (solo las de la Bandeja)."""
    sql, args = "SELECT record FROM sessions WHERE agent_id = ?", [agent_id]
    if query.get("channel"):
        sql, args = sql + " AND channel = ?", args + [query["channel"]]
    if query.get("from"):
        sql, args = sql + " AND substr(started, 1, 10) >= ?", args + [query["from"]]
    if query.get("to"):
        sql, args = sql + " AND substr(started, 1, 10) <= ?", args + [query["to"]]
    if query.get("handoff"):
        sql += " AND handoff = 1"
    if query.get("campaign"):                     # las conversaciones que empezó una campaña (outbound.py)
        sql, args = sql + " AND json_extract(record, '$.campaign') = ?", args + [query["campaign"]]
    # ponytail: lee y decodifica todas las del agente (reportes y analítica las recorren igual); paginar si son cientos de miles
    records = [json.loads(row[0]) for row in db.q(sql + " ORDER BY updated DESC", args)]
    marks = lambda r: [m["name"] for m in r.get("classifications", [])]
    if query.get("classification") == "__none__":
        records = [r for r in records if not marks(r)]
    elif query.get("classification"):
        records = [r for r in records if query["classification"] in marks(r)]
    return records


def report(agent, query):
    """Cuántas conversaciones hubo con cada clasificación, en total y por día."""
    records = sessions_of(agent["id"], {k: v for k, v in query.items() if k != "classification"})
    names = [c["name"] for c in agent.get("classifications", [])]
    totals = dict.fromkeys(names, 0)
    days = {}
    unclassified = 0
    for r in records:
        day = days.setdefault(r["started"][:10], {"date": r["started"][:10], "sessions": 0, "unclassified": 0, "counts": {}})
        day["sessions"] += 1
        found = [m["name"] for m in r.get("classifications", [])]
        if not found:
            unclassified += 1
            day["unclassified"] += 1
        for name in found:
            totals[name] = totals.get(name, 0) + 1          # también las que ya no existen en el agente
            day["counts"][name] = day["counts"].get(name, 0) + 1
    return {"bot": {"id": agent["id"], "name": agent["name"]}, "from": query.get("from"), "to": query.get("to"),
            "channel": query.get("channel"), "sessions": len(records), "unclassified": unclassified,
            "classifications": [{"name": n, "count": c, "configured": n in names} for n, c in totals.items()],
            "by_day": [days[d] for d in sorted(days)]}


def api_v1(method, parts, data, query=None, user=None, public=False):
    """API pública: /api/v1/bots[/{bot}[/events | /sessions[/{sessionId}]]]. Devuelve (status, cuerpo).
    user: quien llama, para listar solo sus bots (auth.guard ya cortó los pedidos a bots que no ve).
    public: el chat del widget sin sesión: solo canal «web», producción, sin datos iniciales ni traza."""
    query = query or {}
    if parts == ["bots"] and method == "GET":
        return 200, {"bots": [bot_info(a) for a in all_agents() if auth.allowed_bot(user, a["id"])]}
    if len(parts) < 2 or parts[0] != "bots":
        return 404, {"error": "no existe. Mirá la documentación en la sección API de Parla"}
    agent = find_bot(urllib.parse.unquote(parts[1]))
    if not agent:
        return 404, {"error": "no hay un bot que se llame «%s» (o hay más de uno con ese nombre: usá su id)" % urllib.parse.unquote(parts[1])}
    rest = parts[2:]
    if not rest and method == "GET":
        return 200, bot_info(agent)
    if rest == ["events"] and method == "POST":
        kind = data.get("type") or ("message" if "text" in data else None)
        sid = data.get("sessionId")
        environment = "production" if public else data.get("environment") or "production"
        channel = "web" if public else str(data.get("channel") or "api")[:30]
        try:
            target(agent, environment)
        except ValueError as error:
            return 400, {"error": str(error)}
        if sid is not None and not (isinstance(sid, str) and SESSION_ID.fullmatch(sid)):
            return 400, {"error": "«sessionId» tiene que ser un texto de hasta 100 letras sin tildes, números o . @ + - _ (sin espacios)"}
        if public and sid and (load_session(agent["id"], sid) or {}).get("channel", "web") != "web":
            return 403, {"error": "esa conversación no es del widget web"}
        if kind in ("start", "online"):
            initial = {} if public else data.get("data") or {}
            if not isinstance(initial, dict):
                return 400, {"error": "«data» tiene que ser un objeto, por ejemplo {\"dni\": \"30123456\"}"}
            flow = None if public else data.get("flow")       # otro flujo en vez del «Al empezar» (llamadas salientes)
            if flow is not None and not isinstance(flow, str):
                return 400, {"error": "«flow» tiene que ser el nombre de un flujo"}
            sid = sid or uuid.uuid4().hex[:16]
            end_session(agent["id"], sid)                 # si ya existía, arranca de cero pero conserva lo charlado
            record = open_session(agent["id"], sid, channel, environment)
            defn = session_agent(agent["id"], record)[1]
            if flow and not any(f["name"] == flow for f in defn["flows"]):
                return 400, {"error": "no existe el flujo «%s»" % flow}
            result, ignored = begin(defn, record["state"], initial, flow or START)
            telemetry.count("parla_conversations_started_total", agent=agent["id"], channel=telemetry.channel(channel))
            record["updated"] = now()
            record["history"].append({"from": "event", "text": "Empezó la conversación", "at": record["updated"],
                                      "data": {k: v for k, v in initial.items() if k not in ignored}})
            record["history"] += bot_entries(result, record["updated"])
            collect(record, agent["id"])
            save_session(agent["id"], record)
            body = dict(session_info(agent, record), messages=result["messages"], understood=None,
                        ignored_data=ignored, trace=result["trace"], **turn_fields(result, record))
            if public:
                body.pop("trace")
            return 200, body
        if kind == "message":
            text = data.get("text")
            if not isinstance(text, str) or not text.strip():
                return 400, {"error": "falta «text» con el mensaje de la persona"}
            sid = sid or uuid.uuid4().hex[:16]
            record = open_session(agent["id"], sid, channel, environment)
            stopped = outbound.inbound(agent, record, text)    # ventana de 24 h, «respondió» y bajas (STOP, BAJA…)
            if stopped:
                return 200, optout_turn(agent, record, text.strip()[:4000], stopped)
            result = converse(agent["id"], record, text.strip()[:4000])
            return 200, dict(session_info(agent, record), messages=result["messages"], understood={
                key: next(h for h in reversed(record["history"]) if h["from"] == "user")[key]
                for key in ("intent", "confidence", "entities", "answer_to")}, **turn_fields(result, record))
        if kind == "end":
            if not sid:
                return 400, {"error": "falta «sessionId» con la conversación a terminar"}
            record = end_session(agent["id"], sid)
            return (200, {"sessionId": sid, "ended": True}) if record else (404, {"error": "no hay una conversación «%s» con este bot" % sid})
        return 400, {"error": "«type» tiene que ser start (u online), message o end"}
    if rest == ["audio"] and method == "POST":
        return audio_event(agent, data, public)
    if rest == ["outbound"] and method == "POST":     # el bot escribe primero (outbound.py); el widget público no
        if public:
            return 403, {"error": "pedido rechazado"}
        return outbound.api_send(agent, data)
    if len(rest) == 3 and rest[0] == "sessions" and rest[2] == "messages" and method == "GET":
        # lo nuevo desde el índice «after»: así el widget recibe lo que escribe la persona de la bandeja
        # ponytail: el historial se recorta a MAX_HISTORY y corre los índices; usar ids si las charlas son muy largas
        record = load_session(agent["id"], urllib.parse.unquote(rest[1]))
        if record is None:
            return 404, {"error": "no hay una conversación «%s» con este bot" % urllib.parse.unquote(rest[1])}
        try:
            after = max(0, int(query.get("after") or 0))
        except ValueError:
            return 400, {"error": "«after» tiene que ser un número"}
        return 200, {"sessionId": record["sessionId"], "messages": record["history"][after:], "next": len(record["history"]),
                     "handoff": bool((record.get("handoff") or {}).get("active")), "ended": record["ended"]}
    if public and (rest == ["lookup"] or len(rest) == 3 and rest[0] == "sessions" and (rest[2] == "handoff" or method == "POST")):
        return 403, {"error": "pedido rechazado"}
    if len(rest) == 3 and rest[0] == "sessions" and rest[2] in ("handoff", "messages") and method == "POST":
        return contact_center(agent, urllib.parse.unquote(rest[1]), rest[2], data, (user or {}).get("name"))
    if rest == ["lookup"] and method == "GET":
        record = lookup(agent["id"], query)
        if record is None:
            return 404, {"error": "no hay una conversación abierta con esa persona"}
        return 200, handoff.context(settings_of(agent["id"]), record)
    if rest == ["sessions"] and method == "GET":
        return 200, {"sessions": [session_summary(r) for r in sessions_of(agent["id"], query)]}
    if rest == ["report"] and method == "GET":
        return 200, report(agent, query)
    if len(rest) == 2 and rest[0] == "sessions":
        sid = urllib.parse.unquote(rest[1])
        record = load_session(agent["id"], sid)
        if record is None:
            return 404, {"error": "no hay una conversación «%s» con este bot" % sid}
        if method == "GET":
            return 200, dict(session_info(agent, record), history=record["history"])
        if method == "DELETE":
            delete_session(agent["id"], sid)
            return 200, {"sessionId": sid, "deleted": True}
    return 405, {"error": "método no permitido acá. Mirá la documentación en la sección API de Parla"}


def vocabulary(agent):
    """Las palabras propias del bot (valores y sinónimos de entidades) como pista para transcribir audios."""
    words = []
    for e in agent.get("entities") or []:
        words += list(e.get("values") or [])
        for others in (e.get("synonyms") or {}).values():
            words += list(others)
    return ", ".join(dict.fromkeys(w for w in words if isinstance(w, str) and w.strip()))[:600] or None


def audio_of(data):
    """data["audio"] en base64, con o sin «data:audio/webm;base64,» adelante (como lo manda el navegador)."""
    try:
        return base64.b64decode(str(data.get("audio") or "").rpartition(",")[2], validate=True)
    except ValueError:
        raise ValueError("«audio» tiene que ser el audio en base64") from None


def audio_event(agent, data, public=False):
    """Un mensaje de voz: se transcribe localmente, se atiende como un mensaje y (si speak) vuelve la respuesta en audio."""
    sid = data.get("sessionId")
    record = load_session(agent["id"], sid) if isinstance(sid, str) else None
    if public and record and record.get("channel") != "web":
        return 403, {"error": "esa conversación no es del widget web"}
    language = ((record or {}).get("state") or {}).get("lang") or languages(agent)[0]
    try:
        audio = audio_of(data)
    except ValueError as error:
        return 400, {"error": str(error)}
    if not audio:
        return 400, {"error": "falta «audio» con la grabación en base64"}
    try:
        conf = voice.settings(agent)
        heard = voice.transcribe(audio, str(data.get("mime") or "audio/webm"), language, vocabulary(agent), conf["asr"])
    except Exception as error:  # noqa: BLE001 - sin modelo de voz, formato raro: que lo vea quien llama
        return 400, {"error": str(error)}
    text = str((heard or {}).get("text") or "").strip()
    if not text:
        return 400, {"error": "no se entendió nada en el audio, probá de nuevo"}
    status, body = api_v1("POST", ["bots", agent["id"], "events"],
                          {k: data[k] for k in ("sessionId", "channel", "environment") if k in data} | {"type": "message", "text": text},
                          public=public)
    if status != 200:
        return status, body
    body["heard"] = text
    if data.get("speak") and body["messages"]:
        try:
            body["audio"] = base64.b64encode(voice.speak(" ".join(body["messages"]), body.get("language") or language, tts=conf["tts"])).decode()
        except Exception as error:  # noqa: BLE001
            return 400, {"error": str(error)}
    return 200, body


def lookup(agent_id, query):
    """La conversación más reciente sin terminar de esa persona (?phone=, ?chat= o ?sid=); primero las que esperan a
    una persona. Para el contact center que recibe la llamada sin el sessionId de Parla."""
    if query.get("sid"):
        record = load_session(agent_id, str(query["sid"]))
        return record if record and not record["ended"] else None
    phone_number = re.sub(r"[\s().+-]", "", str(query.get("phone") or ""))
    chat = str(query.get("chat") or "").strip()
    if not (re.fullmatch(r"\d{6,15}", phone_number) or re.fullmatch(r"-?\d{1,20}", chat)):
        return None
    sids, like = (["wa-" + phone_number], "%" + phone_number + "%") if phone_number else (["tg-" + chat], None)
    rows = db.q("SELECT record FROM sessions WHERE agent_id = ? AND json_extract(record, '$.ended') = 0 AND (session_id = ?%s) "
                "ORDER BY handoff DESC, updated DESC LIMIT 20" % (" OR (channel = 'phone' AND json_extract(record, '$.caller') LIKE ?)" if like else ""),
                (agent_id, sids[0]) + ((like,) if like else ()))
    for (raw,) in rows:
        record = json.loads(raw)
        if record["sessionId"] in sids or re.sub(r"\D", "", str(record.get("caller") or "")) == phone_number:
            return record
    return None


def contact_center(agent, sid, what, data, user_name):
    """POST …/sessions/{sid}/handoff {action: accept|release|close} y …/sessions/{sid}/messages {text, from_name}:
    lo que hace el contact center externo con una conversación. -> (status, cuerpo)."""
    record = load_session(agent["id"], sid)
    if record is None:
        return 404, {"error": "no hay una conversación «%s» con este bot" % sid}
    if record["ended"]:
        return 409, {"error": "esa conversación ya terminó"}
    if what == "messages":
        text = str(data.get("text") or "").strip()[:4000]
        if not text:
            return 400, {"error": "falta «text» con lo que le querés escribir"}
        who = str(data.get("from_name") or user_name or "Contact center").strip()[:60]
        channel = record.get("channel")
        if channel == "phone":
            return 409, {"error": "es una llamada: no se le pueden mandar mensajes de texto"}
        if channel == "whatsapp" and not outbound.in_window(record):
            return 409, {"error": "pasaron más de 24 horas desde el último mensaje de la persona: WhatsApp solo deja escribirle con una plantilla aprobada (POST /outbound)"}
        if channel in channels.CHANNELS:
            try:
                channels.send_now(agent["id"], record, [{"text": text, "buttons": []}])
            except channels.ChannelError as error:
                return 502, {"error": "no se pudo enviar: %s" % error}
        record = human(agent["id"], sid, "reply", text, who, relay=False)
        return 200, dict(session_info(agent, record), delivered=channel in channels.CHANNELS or channel == "web")
    action = data.get("action")
    who = str(data.get("agent_name") or user_name or "Contact center").strip()[:60]
    if action == "accept":
        record = human(agent["id"], sid, "accept", "", who)
    elif action == "release":
        extra, flow = data.get("data"), data.get("flow")
        if extra is not None and not isinstance(extra, dict):
            return 400, {"error": "«data» tiene que ser un objeto, por ejemplo {\"dni\": \"30123456\"}"}
        if flow is not None and (not isinstance(flow, str) or not any(f["name"] == flow for f in session_agent(agent["id"], record)[1]["flows"])):
            return 400, {"error": "no existe el flujo «%s»" % flow}
        record = human(agent["id"], sid, "release", "", who, data=extra, flow=flow)
    elif action == "close":
        record = human(agent["id"], sid, "close", "", who, resolution=str(data.get("resolution") or "")[:200] or None)
    else:
        return 400, {"error": "«action» tiene que ser accept, release o close"}
    return 200, session_info(agent, record)


def inbox(agent_id):
    """Conversaciones que atiende (o espera) una persona, la más reciente primero."""
    return {"sessions": [dict(session_summary(r), handoff=r["handoff"]) for r in sessions_of(agent_id, {"handoff": True})]}


def human(agent_id, sid, action, text, who, data=None, flow=None, resolution=None, relay=True):
    """Una persona toma la charla (take / accept), le escribe (reply), la devuelve al bot (release, con data para los
    slots y flow para seguir) o la cierra (close, con resolution). Lo usan la Bandeja, la API del contact center
    externo y el tiempo máximo del handoff. Devuelve el registro o None."""
    record = load_session(agent_id, sid)
    if record is None:
        return None
    state, at = record["state"], now()
    active = (state.get("handoff") or {}).get("active")
    if action == "close":
        record["resolution"] = resolution
        record["history"].append({"from": "event", "text": "La cerró %s" % who, "at": at, **({"resolution": resolution} if resolution else {})})
        save_session(agent_id, record)
        return end_session(agent_id, sid)
    if action in ("take", "reply", "accept") and not active:      # escribirle también la toma: si no, contestan los dos
        start_handoff(state, "la tomó %s" % who, who)
        state["handoff"]["mode"] = handoff.conf(settings_of(agent_id))["mode"]
        record["history"].append({"from": "event", "text": "La tomó %s" % who, "at": at})
    elif action == "accept":
        state["handoff"]["by"] = who
        record["history"].append({"from": "event", "text": "La tomó %s" % who, "at": at})
    if action == "reply":
        state["handoff"]["by"] = state["handoff"].get("by") or who
        record["history"].append({"from": "human", "text": text, "at": at, "by": who})
        remember(state, "bot", text)
    result = None
    if action == "release":
        stop(state)                                      # lo que estaba a medias ya lo resolvió la persona
        for key in ("waiting", "clarify", "buttons"):
            state.pop(key, None)
        state["handoff"] = dict(state.get("handoff") or {}, active=False, until=at)
        record["history"].append({"from": "event", "text": "Volvió al bot", "at": at})
        if data or flow:                                 # el contact center deja datos y/o pide un flujo
            result, ignored = begin(session_agent(agent_id, record)[1], state, data or {}, flow or "")
            if data:
                record["history"].append({"from": "event", "text": "Datos del contact center", "at": at,
                                          "data": {k: v for k, v in data.items() if k not in ignored}})
            record["history"] += bot_entries(result, at)
    record["updated"] = at
    sync(record)
    collect(record, agent_id)
    del record["history"][:-MAX_HISTORY]
    save_session(agent_id, record)
    if action == "reply" and relay:
        channels.human_reply(agent_id, record, text)     # WhatsApp o Telegram: que le llegue a la persona
    if action == "release":
        handoff.emit_by_id(agent_id, "handoff.released", record, released_by=who)
        if result and result["replies"]:
            channels.human_reply(agent_id, record, None, result["replies"])
    return record


def create(template, **changes):
    return store({**json.loads(json.dumps(template)), **changes, "id": uuid.uuid4().hex[:8]})


def import_rasa(data, user):
    """POST /api/agents/import/rasa con {"zip": base64, "name"} o {"files": {ruta: texto}, "name"} -> (status, {agent, warnings}).
    Crea el agente como «Importar agente» y lo entrena. No crea funciones: no hace falta ser dueño."""
    try:
        if data.get("zip") is not None:
            try:
                raw = base64.b64decode(str(data["zip"]), validate=True)
            except ValueError:
                return 400, {"error": "«zip» tiene que ser el .zip en base64"}
            found, notes = rasa_import.read_zip(raw)
        elif isinstance(data.get("files"), dict):
            found, notes = {str(k): str(v) for k, v in data["files"].items()}, []
        else:
            return 400, {"error": "mandá {\"zip\": base64} o {\"files\": {ruta: texto}} con el proyecto de Rasa"}
        agent, warnings = rasa_import.convert(found, data.get("name"))
        made = create(imported(agent))
    except ValueError as error:
        return 400, {"error": str(error)}
    auth.grant(user, made["id"])
    try:
        train(made["id"])
    except Exception as error:  # noqa: BLE001 - sin modelo igual queda creado: se entrena al abrirlo
        warnings.append("no se pudo entrenar ahora (%s); se entrena al abrirlo" % error)
    return 200, {"agent": load(made["id"]), "warnings": notes + warnings}


CODE_ONLY_OWNER = "Solo el dueño puede crear, cambiar o probar el código de las funciones (corre en esta compu). Pedíselo al dueño o apagá las funciones con PARLA_FUNCTIONS=0."


NOT_JSON = {"error": "mandá el pedido como JSON (Content-Type: application/json)"}


A = r"/api/agents/([0-9a-f]{8})"
AUDIT = (     # (método, ruta, acción): lo que queda en la auditoría cuando sale bien (Handler.audit arma el detalle)
    ("POST", r"/api/auth/login", "login"), ("POST", r"/api/auth/logout", "logout"),
    ("POST", r"/api/users", "user.create"), ("PUT", r"/api/users/([^/]+)", "user.update"), ("DELETE", r"/api/users/([^/]+)", "user.delete"),
    ("POST", r"/api/users/([^/]+)/keys", "key.create"), ("DELETE", r"/api/users/([^/]+)/keys/([^/]+)", "key.revoke"),
    ("POST", r"/api/connect", "key.create"),
    ("POST", r"/api/agents", "agent.create"), ("POST", r"/api/agents/import/rasa", "agent.import"),
    ("PUT", A, "agent.save"), ("DELETE", A, "agent.delete"), ("POST", A + "/train", "agent.train"),
    ("POST", A + "/versions", "agent.publish"), ("POST", A + "/deploy", "agent.deploy"), ("POST", A + r"/versions/(\d+)/restore", "agent.restore"),
    ("PUT", A + "/secrets", "secret.set"), ("DELETE", A + "/secrets", "secret.delete"),
    ("POST", A + "/files", "file.upload"), ("DELETE", A + "/files/([A-Za-z0-9_-]{22})", "file.delete"),
    ("POST", A + "/channels/telegram", "channel.telegram"),
    ("POST", A + r"/sessions/([A-Za-z0-9_.@+-]+)/(take|release|reply)", "/inbox"),
    ("DELETE", r"/api/v1/bots/([^/]+)/sessions/([^/]+)", "session.delete"),
    ("POST", A + "/campaigns", "campaign.create"), ("PUT", A + "/campaigns/([0-9a-f]{12})", "campaign.update"),
    ("DELETE", A + "/campaigns/([0-9a-f]{12})", "campaign.delete"), ("POST", A + "/campaigns/([0-9a-f]{12})/recipients", "campaign.recipients"),
    ("POST", A + "/campaigns/([0-9a-f]{12})/(start|pause|resume|cancel)", "/campaign"),
    ("POST", A + "/optouts", "optout.add"), ("DELETE", A + "/optouts", "optout.remove"),
    ("POST", r"/api/v1/bots/([^/]+)/outbound", "outbound.send"),
    ("POST", r"/api/v1/bots/([^/]+)/sessions/([^/]+)/handoff", "handoff.api"),
    ("POST", r"/api/v1/bots/([^/]+)/sessions/([^/]+)/messages", "handoff.message"),
    ("POST", A + "/webhooks/test", "webhook.test"), ("POST", A + r"/webhooks/deliveries/(\d+)/retry", "webhook.retry"),
)


class Handler(BaseHTTPRequestHandler):
    timeout = 30        # segundos sin datos y se corta la conexión (slowloris)

    def reply(self, data, status=200, ctype="application/json"):
        self.status, self.sent = status, data if isinstance(data, dict) else {}       # para la auditoría (safely)
        if isinstance(data, (dict, list)):              # errores y avisos en el idioma de la interfaz (parla/i18n.py)
            data = i18n.translate(data, i18n.lang_of(self.headers.get("Accept-Language")))
        body = data if isinstance(data, bytes) else json.dumps(data, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        if getattr(self, "cors", None):             # el widget web en un sitio autorizado
            self.send_header("Access-Control-Allow-Origin", self.cors)
            self.send_header("Vary", "Origin")
        for key, value in (getattr(self, "extra_headers", None) or {}).items():
            self.send_header(key, value)
        self.end_headers()
        self.wfile.write(body)

    def route(self, method):
        if method == "GET" and urllib.parse.urlsplit(self.path).path == "/":      # también /?lang=en
            with open(os.path.join(HERE, "index.html"), "rb") as f:
                page = f.read()
            lang = os.environ.get("PARLA_LANG", "").strip().lower()[:2]
            if lang.isalpha():        # PARLA_LANG: el idioma de la interfaz si la persona no eligió otro (static/i18n.js)
                page = page.replace(b'<html lang="es">', b'<html lang="es" data-default-lang="%s">' % lang.encode(), 1)
            return self.reply(page, ctype="text/html; charset=utf-8")
        served = method == "GET" and re.fullmatch(r"/files/([0-9a-f]{8})/([A-Za-z0-9_-]{22})", urllib.parse.urlsplit(self.path).path)
        if served:      # archivos de un paso «Enviar un archivo»: públicos para el widget y la API, el id aleatorio es la llave
            found = files.read(*served.groups())
            if not found:
                return self.reply({"error": "no existe"}, 404)
            self.extra_headers = dict(found[1])
            return self.reply(found[0], ctype=self.extra_headers.pop("Content-Type"))
        static = re.fullmatch(r"/static/([a-z0-9-]+\.js)", urllib.parse.urlsplit(self.path).path)
        if method == "GET" and static and os.path.exists(os.path.join(HERE, "static", static.group(1))):
            with open(os.path.join(HERE, "static", static.group(1)), "rb") as f:
                return self.reply(f.read(), ctype="text/javascript; charset=utf-8")
        if method == "GET" and urllib.parse.urlsplit(self.path).path == "/metrics":    # Prometheus (telemetry.py)
            status = telemetry.allowed(self.headers.get("Authorization"), self.client_address[0], self.headers.get("Host"))
            if status != 200:
                return self.reply({"error": "no existe" if status == 404 else "métricas: falta el token (PARLA_METRICS_TOKEN) o no coincide"}, status)
            telemetry.gauge("parla_active_sessions", active_sessions())
            telemetry.gauge("parla_campaign_recipients", outbound.gauge_rows())
            if "parla.aserver" in sys.modules:
                live = sys.modules["parla.aserver"].gauges()
                telemetry.gauge("parla_connections", live["connections"])
                telemetry.gauge("parla_queue_depth", live["queues"] + [({"queue": "db_write"}, db.pending()), ({"queue": "embed"}, _jobs.qsize()),
                                                       ({"queue": "webhooks"}, handoff.depth())])
            for name, value in (("parla_embed_batches_total", EMBED_STATS["batches"]), ("parla_embed_items_total", EMBED_STATS["items"]),
                                ("parla_db_commits_total", db._stats["commits"]), ("parla_db_statements_total", db._stats["statements"])):
                telemetry.gauge(name, [({}, value)])
            return self.reply(telemetry.render().encode(), ctype="text/plain; version=0.0.4; charset=utf-8")
        raw = self.headers.get("Content-Length") or "0"
        if not (raw.isascii() and raw.isdigit()):
            return self.reply({"error": "Content-Length inválido"}, 400)
        length = int(raw)
        url = urllib.parse.urlsplit(self.path).path
        query = dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(self.path).query))
        as_json = (self.headers.get("Content-Type") or "").startswith("application/json")
        port = self.server.server_address[1]
        ours = {"127.0.0.1:%d" % port, "localhost:%d" % port}
        origin = self.headers.get("Origin")
        self.cors = self.widget_origin(url, origin)
        self.user, self.public = None, False
        # la vuelta del proveedor de SSO es una navegación desde otro sitio: la protegen state, nonce y PKCE (oidc.py)
        if url.startswith("/api/") and url != "/api/auth/oidc/callback" and origin is not None and urllib.parse.urlsplit(origin).netloc.lower() not in ours | set(auth.hosts()) and not self.cors:
            return self.reply({"error": "pedido de otro sitio web rechazado"}, 403)   # cualquier página podría pegarle a localhost
        hooked = re.fullmatch(r"/api/v1/bots/([^/]+)/(whatsapp|telegram)", url)
        if hooked and method in ("GET", "POST"):
            # webhooks de Meta y Telegram: vienen de otro Host y sin sesión; los autentica la firma o el secreto (channels.py)
            status, body, ctype = channels.webhook(self.headers, self.rfile, method, *hooked.groups(), query, length)
            return self.reply(body, status, ctype)
        called = re.fullmatch(r"/api/v1/bots/([^/]+)/phone/(twilio|jambonz)(?:/(gather|status))?", url)
        if called:      # llamadas de Twilio o jambonz: las autentica su firma (phone.py), como los webhooks de arriba
            status, body, ctype = phone.webhook(self.headers, self.rfile, method, called.group(1), called.group(2),
                                                called.group(3) or "", self.path, length)
            return self.reply(body, status, ctype)
        played = re.fullmatch(r"/api/v1/bots/([^/]+)/phone/audio/([A-Za-z0-9_-]+\.[A-Za-z0-9_-]+)\.wav", url)
        if played and method == "GET":      # audio de Parla para la llamada: el token firmado y con vencimiento es la llave
            status, body, ctype = phone.audio(*played.groups())
            return self.reply(body, status, ctype)
        if method == "OPTIONS":
            if not self.cors:
                return self.reply({"error": "pedido de otro sitio web rechazado"}, 403)
            self.extra_headers = {"Access-Control-Allow-Methods": "POST, GET, OPTIONS",
                                  "Access-Control-Allow-Headers": "Content-Type", "Access-Control-Max-Age": "600"}
            return self.reply(b"", 204, "text/plain")
        mine = url.startswith("/api/auth/") or url == "/api/users" or url.startswith("/api/users/")    # rutas de auth.handle
        if url.startswith("/api/") and not mine:
            stop = auth.guard(self, method, url, {})        # antes de leer el cuerpo: sin sesión no se lee nada
            if stop is not None:
                return self.reply(stop[1], stop[0])
        if url.startswith("/api/") and not self.local_host():
            # DNS rebinding: una página que hace apuntar su dominio a 127.0.0.1 no manda Origin en todo, pero sí su Host
            bearer = self.user and (self.headers.get("Authorization") or "").lower().startswith("bearer ")
            widget = auth._public_widget(method, url)
            if not (bearer or widget):
                return self.reply({"error": "pedido rechazado: ese Host no está permitido (sumalo a PARLA_HOSTS)"}, 403)
            self.public = self.public or (widget and not self.user)
        big = re.fullmatch(r"/api/agents(/[0-9a-f]{8}(/files|/knowledge/extract|/voice/transcribe)?|/import/rasa)?|/api/v1/bots/[^/]+/audio", url)
        limit = 2_000_000 if self.public and url.endswith("/audio") else 25_000_000 if big else 1_000_000   # PDFs y audios van en base64
        if length > limit:
            return self.reply({"error": "demasiado grande"}, 413)
        try:
            data = json.loads(self.rfile.read(length) or b"{}") if length else {}
        except ValueError:
            return self.reply({"error": "el cuerpo tiene que ser un JSON válido"}, 400)
        if not isinstance(data, dict):
            return self.reply({"error": "el cuerpo tiene que ser un objeto JSON"}, 400)
        self.body = data
        if mine:
            self.user = auth.current(self)               # para la auditoría: quién maneja usuarios o cierra sesión
        own = oidc.handle(self, method, url, query) or auth.handle(self, method, url, data)   # /api/auth/* y /api/users*
        if own is not None:
            status, body, headers = own
            self.extra_headers = headers
            return self.reply(body, status)
        if url == "/api/audit" and method == "GET":
            if self.user and self.user["role"] != "owner":
                return self.reply({"error": "Solo el dueño puede ver la auditoría."}, 403)
            try:
                limit = min(1000, max(1, int(query.get("limit") or 200)))
            except ValueError:
                return self.reply({"error": "«limit» tiene que ser un número"}, 400)
            return self.reply({"entries": db.audit_list(query.get("agent"), query.get("user"), query.get("since"), limit)})
        if url == "/api/ai/status" and method == "POST" and data.get("agent") and not auth.allowed_bot(self.user, str(data["agent"])):
            return self.reply({"error": "no existe ese agente"}, 404)
        if url == "/api/ai/status" and method == "POST":       # {"ai": config} y/o {"agent": id} (su API key sale del vault)
            ai = data.get("ai") if isinstance(data.get("ai"), dict) else None
            return self.reply(llm.status(llm.settings(load(str(data["agent"])) if data.get("agent") else {}, ai)))
        if url == "/api/ai/pull" and method == "POST":         # descarga un modelo local (Ollama) en segundo plano
            return self.reply(llm.pull(data.get("ai") or {}, str(data.get("model") or "")))
        if url == "/api/ai/progress" and method == "GET":
            return self.reply(llm.pull_progress())
        if url == "/api/voice/status" and method == "GET":
            return self.reply(voice.status())
        if url in ("/api/voice/speak", "/api/voice/voices") and data.get("agent") and not auth.allowed_bot(self.user, str(data["agent"])):
            return self.reply({"error": "no existe ese agente"}, 404)
        if url in ("/api/voice/speak", "/api/voice/voices") and method == "POST":   # {"agent": id} usa su voz; {"voice": config} prueba sin guardar
            owner = load(str(data["agent"])) if data.get("agent") else {}
            tts = voice.settings(owner, data.get("voice") if isinstance(data.get("voice"), dict) else None)["tts"]
            if url == "/api/voice/voices":
                return self.reply({"voices": voice.voices(tts, str(data.get("language") or "es"))})
            audio = voice.speak(str(data.get("text") or "")[:2000], str(data.get("language") or "es"), tts=tts)
            return self.reply(audio, ctype="audio/wav")
        if url in ("/api/connect", "/api/connect/remove"):
            if self.headers.get("Host") not in ours:   # DNS rebinding
                return self.reply({"error": "pedido rechazado"}, 403)
            if method == "GET" and url == "/api/connect":
                return self.reply(connect.clients_status("http://127.0.0.1:%d" % port))
            if method != "POST":
                return self.reply({"error": "método no permitido"}, 405)
            if not as_json:
                return self.reply(NOT_JSON, 415)
            try:
                if url == "/api/connect":
                    user = getattr(self, "user", None)     # con usuarios, el MCP necesita una clave de API propia
                    token = auth.issue_key(user["name"], "Conectar con " + str(data.get("client"))[:30]) if user else None
                    return self.reply(connect.connect(str(data.get("client")), "http://127.0.0.1:%d" % port, token))
                return self.reply(connect.disconnect(str(data.get("client"))))
            except (ValueError, OSError) as error:
                return self.reply({"ok": False, "error": str(error)}, 400)
        if url == "/api/agents/import/rasa":
            if method != "POST":
                return self.reply({"error": "método no permitido"}, 405)
            return self.reply(*reversed(import_rasa(data, self.user)))
        if url.startswith("/api/v1/"):
            return self.reply(*reversed(api_v1(method, [p for p in url[len("/api/v1/"):].split("/") if p], data, query, self.user, self.public)))
        match = re.fullmatch(r"/api/agents(?:/([0-9a-f]{8})(?:/(chat|reset|http|train|tests/run|versions|deploy|diff|versions/\d+|versions/\d+/restore|functions/test"
                             r"|knowledge/extract|knowledge/search|voice/transcribe|mcp/tools|secrets|files|files/[A-Za-z0-9_-]{22}|insights/unrecognized|insights/analytics"
                             r"|inbox|channels|channels/telegram|sessions/[A-Za-z0-9_.@+-]+/(?:reply|release|take)|webhooks/test|webhooks/deliveries(?:/\d+/retry)?"
                             r"|campaigns|campaigns/preview|campaigns/[0-9a-f]{12}(?:/(?:start|pause|resume|cancel|recipients|export))?|optouts))?)?", url)
        if not match:
            return self.reply({"error": "no existe"}, 404)
        agent_id, action = match.groups()
        if agent_id is None:
            if method == "GET":
                return self.reply([{"id": a["id"], "name": a["name"], "intents": len(a["intents"]),
                                    "flows": len(a["flows"])} for a in all_agents() if auth.allowed_bot(self.user, a["id"])])
            if method == "POST" and "import" in data:
                if not isinstance(data["import"], dict):
                    return self.reply({"error": "el archivo no es un agente de Parla"}, 400)
                made = imported(data["import"])
                if self.code_blocked([], made.get("functions")):
                    return self.reply({"error": CODE_ONLY_OWNER}, 403)
                made = create(made)
                auth.grant(self.user, made["id"])
                return self.reply(made)
            if method == "POST":
                name = str(data.get("name") or "").strip()[:80] or BLANK["name"]
                made = create(DEMO if data.get("demo") else BLANK, name=name)
                auth.grant(self.user, made["id"])
                return self.reply(made)
        elif not os.path.exists(path(agent_id)):
            return self.reply({"error": "no existe ese agente"}, 404)
        elif action == "chat" and method == "POST":
            sid = str(data.get("session") or "")
            if not SESSION_ID.fullmatch(sid):
                return self.reply({"error": "sesión inválida"}, 400)
            return self.reply(converse(agent_id, open_session(agent_id, sid, "prueba", str(data.get("environment") or "draft")),
                                       str(data.get("text") or "")[:4000]))
        elif action == "versions" and method == "GET":
            agent = load(agent_id)
            return self.reply({"versions": [version_summary(load_version(agent_id, n), agent) for n in reversed(versions(agent_id))],
                               "environments": {e: (agent.get("environments") or {}).get(e) for e in ENVIRONMENTS},
                               "deployments": list(reversed(agent.get("deployments", [])))[:50]})
        elif action == "versions" and method == "POST":
            # a Producción, con pruebas: primero las pruebas. Si falla alguna, 409 con el detalle (force: true publica igual)
            if data.get("environment") == "production" and data.get("force") is not True and load(agent_id).get("tests"):
                results = bottests.run_suite(agent_id, "draft")
                if not results["passed"]:
                    return self.reply({"error": "No se publicó en Producción: %s. Corregilas o mandá «force»: true para publicar igual."
                                       % bottests.summary(results), "tests": results}, 409)
            return self.reply(publish(agent_id, data.get("note"), data.get("environment")))
        elif action == "tests/run" and method == "POST":           # {"environment"?, "names"?: [...]}: no guarda nada
            names, environment = data.get("names"), data.get("environment")
            if names is not None and not (isinstance(names, list) and all(isinstance(n, str) for n in names)):
                return self.reply({"error": "«names» tiene que ser una lista con los nombres de las pruebas"}, 400)
            if environment is not None:
                target(load(agent_id), environment)       # que exista: si no, 400 con el motivo
            return self.reply(bottests.run_suite(agent_id, environment, names))
        elif action == "deploy" and method == "POST":
            return self.reply(deploy(agent_id, data.get("environment"), data.get("version")))
        elif action == "diff" and method == "GET":
            # ?from=production|staging|<n>&to=draft|<n>: qué cambia, para revisar antes de publicar
            agent = load(agent_id)
            def side(ref):
                if ref in (None, "", "draft"):
                    return definition(agent), None
                number = (agent.get("environments") or {}).get(ref) if ref in ENVIRONMENTS else int(ref)
                return (definition(load_version(agent_id, number)["agent"]), number) if number is not None else ({}, None)
            (old, old_n), (new, new_n) = side(query.get("from", "production")), side(query.get("to", "draft"))
            return self.reply(dict(diff(old, new), **{"from": old_n, "to": new_n}))
        elif action and action.startswith("versions/") and action.endswith("/restore") and method == "POST":
            # volver el borrador a lo que tenía una versión (deshacer cambios sin publicar)
            snapshot = load_version(agent_id, int(action.split("/")[1]))["agent"]
            agent = load(agent_id)
            if self.code_blocked(agent.get("functions"), snapshot.get("functions")):
                return self.reply({"error": CODE_ONLY_OWNER}, 403)
            store({**snapshot, **{k: agent[k] for k in EDITABLE_ONLY if k in agent}})
            return self.reply(load(agent_id))       # con agent["system"] completo, como GET
        elif action and action.startswith("versions/") and method == "GET":
            record = load_version(agent_id, int(action.split("/")[1]))
            return self.reply(dict(version_summary(record, load(agent_id)), agent=record["agent"]))
        elif action == "functions/test" and method == "POST":
            # «Probar» del editor de funciones: corre la definición que manda la interfaz (puede no estar guardada)
            if not as_json:
                return self.reply(NOT_JSON, 415)
            if self.code_blocked([], [True]):
                return self.reply({"error": CODE_ONLY_OWNER}, 403)
            fn, inputs = data.get("function"), data.get("inputs") or {}
            if not isinstance(fn, dict) or not isinstance(inputs, dict):
                return self.reply({"error": "mandá «function» (la definición) e «inputs» (un objeto)"}, 400)
            return self.reply(runner.run_function(fn, inputs))
        elif action == "knowledge/extract" and method == "POST":     # {"kind": text|url|pdf|html, "data"|"url"}
            return self.reply(knowledge.extract(str(data.get("kind") or "text"), data.get("data") if data.get("kind") != "url" else data.get("url")))
        elif action == "knowledge/search" and method == "POST":      # prueba de la base desde la interfaz
            return self.reply({"results": knowledge.search(load(agent_id), str(data.get("query") or ""), int(data.get("k") or 3))})
        elif action == "voice/transcribe" and method == "POST":      # {"audio": base64, "mime", "voice"?: config sin guardar}
            owner = load(agent_id)
            asr = voice.settings(owner, data.get("voice") if isinstance(data.get("voice"), dict) else None)["asr"]
            return self.reply(voice.transcribe(audio_of(data), str(data.get("mime") or "audio/webm"),
                                               str(data.get("language") or "es"), vocabulary(owner), asr))
        elif action == "files" and method == "GET":                  # archivos para el paso «Enviar un archivo»
            return self.reply({"files": files.listing(agent_id)})
        elif action == "files" and method == "POST":                 # {"name": "precios.pdf", "data": base64}
            return self.reply(dict(files.save(agent_id, data.get("name"), data.get("data")), files=files.listing(agent_id)))
        elif action and action.startswith("files/") and method == "DELETE":
            files.delete(agent_id, action[6:])
            return self.reply({"files": files.listing(agent_id)})
        elif action == "secrets" and method == "GET":                # solo los nombres: los valores nunca vuelven
            return self.reply({"secrets": vault.names(agent_id)})
        elif action == "secrets" and method == "PUT":
            if not as_json:
                return self.reply(NOT_JSON, 415)
            vault.put(agent_id, str(data.get("name") or ""), str(data.get("value") or ""))
            return self.reply({"secrets": vault.names(agent_id)})
        elif action == "secrets" and method == "DELETE":
            vault.delete(agent_id, str(data.get("name") or ""))
            return self.reply({"secrets": vault.names(agent_id)})
        elif action == "insights/unrecognized" and method == "GET":
            return self.reply(insights.unrecognized(load(agent_id), sessions_of(agent_id, query)))
        elif action == "insights/analytics" and method == "GET":
            return self.reply(insights.analytics(load(agent_id), sessions_of(agent_id, query)))
        elif action == "train" and method == "POST":
            return self.reply(train(agent_id, data.get("fingerprint")))
        elif action == "reset" and method == "POST":
            end_session(agent_id, str(data.get("session") or ""))
            return self.reply({})
        elif action == "http" and method == "POST":   # "Probar consulta" del armador de flujos
            return self.reply(http_step(data.get("step") or {}, dict(data.get("vars") or {}, secret=secrets({"id": agent_id}))))
        elif action == "mcp/tools" and method == "POST":   # «Ver herramientas»: {"server": nombre | {name, url, headers_secret}}
            server = data.get("server")
            agent = load(agent_id)
            if isinstance(server, dict):        # la config sin guardar de la interfaz
                agent = dict(agent, mcp_servers=[dict(server, name="_")])
                server = "_"
            try:
                url, auth_value = mcp_server(agent, str(server or ""))
                return self.reply({"tools": mcp_client.list_tools(url, auth_value, fresh=True)})
            except ValueError as error:
                return self.reply({"error": str(error)}, 400)
            except mcp_client.MCPError as error:
                return self.reply({"error": mask(agent, str(error))}, 502)
        elif action == "inbox" and method == "GET":
            return self.reply(inbox(agent_id))
        elif action and (action.startswith("campaigns") or action == "optouts"):     # campañas y bajas (outbound.py)
            try:
                out = outbound.admin(method, load(agent_id), action, data, query, self.user)
            except outbound.OutboundError as error:
                return self.reply({"error": str(error)}, error.status)
            if len(out) == 4:                                       # el CSV de resultados
                self.extra_headers = {"Content-Disposition": 'attachment; filename="%s"' % out[3]}
                return self.reply(out[1], out[0], out[2])
            return self.reply(out[1], out[0])
        elif action == "channels" and method == "GET":                # pantalla «Canales»: webhooks, claves que faltan, estado
            return self.reply(dict(channels.info(load(agent_id)), phone=phone.info(load(agent_id))))
        elif action == "channels/telegram" and method == "POST":      # {"connect": true|false}: setWebhook / deleteWebhook
            return self.reply(channels.telegram_webhook(load(agent_id), data.get("connect", True) is not False))
        elif action == "webhooks/deliveries" and method == "GET":    # el registro de entregas de los webhooks (handoff.py)
            try:
                limit = min(200, max(1, int(query.get("limit") or 50)))
            except ValueError:
                return self.reply({"error": "«limit» tiene que ser un número"}, 400)
            return self.reply({"deliveries": handoff.deliveries(agent_id, limit), "pending": handoff.depth()})
        elif action and action.startswith("webhooks/deliveries/") and method == "POST":   # «Reintentar»
            if not handoff.retry(agent_id, int(action.split("/")[2])):
                return self.reply({"error": "no existe esa entrega o ya llegó"}, 404)
            return self.reply({"retried": True})
        elif action == "webhooks/test" and method == "POST":         # «Enviar evento de prueba» a un webhook guardado
            try:
                return self.reply(handoff.test(load(agent_id), str(data.get("url") or "")))
            except ValueError as error:
                return self.reply({"error": str(error)}, 400)
        elif action and action.startswith("sessions/") and method == "POST":   # reply | take | release
            _, sid, what = action.split("/")
            text = str(data.get("text") or "").strip()[:4000]
            if what == "reply" and not text:
                return self.reply({"error": "falta «text» con lo que le querés escribir"}, 400)
            held = ((load_session(agent_id, sid) or {}).get("handoff") or {})
            if what in ("take", "reply") and held.get("active") and held.get("mode") == "external":
                return self.reply({"error": "la atiende el contact center externo: desde la Bandeja solo se puede mirar"}, 409)
            who = (getattr(self, "user", None) or {}).get("name") or "Persona"
            record = human(agent_id, sid, what, text, who)
            if record is None:
                return self.reply({"error": "no existe esa conversación"}, 404)
            return self.reply(dict(session_info(load(agent_id), record), history=record["history"]))
        elif action is None and method == "GET":
            agent = load(agent_id)
            if (self.user or {}).get("role") == "agent":     # atención: solo lo que lee la Bandeja, no la definición del bot
                return self.reply({"id": agent["id"], "name": agent["name"], "environments": agent.get("environments") or {},
                                   "classifications": agent.get("classifications") or [], "languages": languages(agent),
                                   **{k: [] for k in ("intents", "entities", "slots", "flows", "functions", "knowledge")}})
            return self.reply(agent)
        elif action is None and method == "PUT":
            current = load(agent_id)     # la interfaz no maneja versiones: no puede pisar entornos ni el registro
            if self.code_blocked(current.get("functions"), data.get("functions")):
                return self.reply({"error": CODE_ONLY_OWNER}, 403)
            keep = {k: current[k] for k in ("environments", "deployments") if k in current}
            if (current.get("channels") or {}) != (data.get("channels") or {}):
                self.audit_action = "channel.update"     # la configuración de WhatsApp/Telegram vive en el agente
            if (current.get("webhooks") or []) != (data.get("webhooks") or []) or (current.get("handoff") or {}) != (data.get("handoff") or {}):
                self.audit_action = "handoff.update"     # derivación y webhooks (handoff.py)
            return self.reply(store({**BLANK, **data, **keep, "id": agent_id}))
        elif action is None and method == "DELETE":
            for ext in (".json", ".model.json", ".crfsuite", ".secrets.json"):
                if os.path.exists(path(agent_id, ext)):
                    os.remove(path(agent_id, ext))
            db.q("DELETE FROM sessions WHERE agent_id = ?", (agent_id,))
            for table in ("campaign_recipients", "campaigns", "optouts"):
                db.q("DELETE FROM %s WHERE agent_id = ?" % table, (agent_id,))
            shutil.rmtree(os.path.join(AGENTS, agent_id + ".versions"), ignore_errors=True)
            shutil.rmtree(os.path.join(AGENTS, agent_id + ".files"), ignore_errors=True)
            for key in [k for k in MODELS if k.startswith(agent_id + "@")]:
                MODELS.pop(key)
            for file in [f for f in _versions if f.startswith(os.path.join(AGENTS, agent_id + ".versions") + os.sep)]:
                _versions.pop(file)
            MODELS.pop(agent_id, None)
            return self.reply({})
        return self.reply({"error": "método no permitido"}, 405)

    def audit(self, method):
        """Deja en la auditoría las escrituras que salieron bien (y los intentos de login, salgan o no). Ver AUDIT."""
        url = urllib.parse.urlsplit(self.path).path
        found = next(((action, m) for verb, rx, action in AUDIT if verb == method and (m := re.fullmatch(rx, url))), None)
        if not found or (self.status is None or self.status >= 400) and found[0] != "login":
            return
        action, match = found
        data, sent, groups = self.body, self.sent, match.groups()
        agent_id = groups[0] if url.startswith("/api/agents/") and groups else None
        user, role = (self.user or {}).get("name"), (self.user or {}).get("role")
        if action in ("agent.create", "agent.import"):                 # el id nuevo viene en la respuesta
            agent_id = (sent.get("agent") or sent).get("id")
            action = "agent.import" if "import" in data or "rasa" in url else action
        if action == "user.update" and "role" in data:
            action = "user.role"
        action = self.audit_action or action
        if action.startswith("/"):                                  # bandeja: take | release | reply; campaña: start | pause…
            action = ("campaign." if action == "/campaign" else "inbox.") + groups[-1]
        if action == "login":
            user, role = str(data.get("name") or "")[:40], (sent.get("user") or {}).get("role")
            detail = ("ok" if self.status == 200 else "falló (%s)" % self.status) + " desde " + self.client_address[0]
        elif action.startswith(("user.", "key.")) and url.startswith("/api/users"):
            target = urllib.parse.unquote(groups[0]) if groups else str(data.get("name") or "")
            user, role = user or sent.get("name"), role or sent.get("role")      # el primer usuario se crea sin sesión: es él mismo
            changes = ", ".join(("rol: %s" % data["role"]) if k == "role" else k for k in ("role", "bots", "password") if k in data)
            detail = target + (" (%s)" % changes if changes and action in ("user.update", "user.role") else "") + \
                (" · rol %s" % sent.get("role") if action == "user.create" else "") + \
                (" · clave «%s»" % (sent.get("label") or groups[-1]) if action.startswith("key.") else "")
        elif action.startswith("secret."):
            detail = str(data.get("name") or "")[:60]                # el nombre; el valor nunca
        elif action.startswith("campaign."):
            detail = "%s (%s)" % (sent.get("name") or "", sent.get("id") or groups[1] if len(groups) > 1 else sent.get("id"))
            if action == "campaign.create":
                detail += " · %s destinatarios" % ((sent.get("imported") or {}).get("added", 0))
        elif action.startswith("optout.") or action == "outbound.send":     # el teléfono tapado, nunca entero
            detail = (str(data.get("channel") or "whatsapp") + " → " if action == "outbound.send" else "") + outbound.mask(
                re.sub(r"[\s().+-]", "", str(data.get("to") or data.get("address") or "")))
        elif action == "handoff.api":                                # accept | release | close, y la conversación
            action = "handoff." + str(data.get("action"))
            detail = urllib.parse.unquote(groups[1])
        elif action == "webhook.test":
            detail = str(data.get("url") or "")[:200]
        elif action.startswith("inbox.") or action in ("agent.restore", "session.delete", "handoff.message", "webhook.retry"):
            detail = ("versión " if action == "agent.restore" else "") + urllib.parse.unquote(groups[1])     # la conversación o la versión
        else:
            detail = {"agent.publish": "versión %s" % sent.get("version"), "agent.deploy": "%s → versión %s" % (data.get("environment"), data.get("version")),
                      "file.upload": str(data.get("name") or "")[:80], "key.create": "Conectar con %s" % str(data.get("client") or "")[:30],
                      "channel.telegram": "conectar" if data.get("connect", True) is not False else "desconectar"}.get(action, "")
        if url.startswith("/api/v1/bots/"):
            agent_id = (find_bot(urllib.parse.unquote(groups[0])) or {}).get("id") or urllib.parse.unquote(groups[0])
        db.audit(user, role, agent_id, action, detail)

    def code_blocked(self, before, after):
        """Con funciones prendidas, escribir su código es correr código en esta compu: solo el dueño (o sin usuarios).
        Borrar o reordenar sí puede cualquiera que edite; lo que bloquea es una función nueva o cambiada."""
        if not runner.enabled() or (self.user or {}).get("role") in (None, "owner"):
            return False
        return any(f not in (before or []) for f in (after or []))

    def local_host(self):
        """¿El Host del pedido es esta compu (127.0.0.1, localhost, [::1], cualquier puerto) o uno de PARLA_HOSTS?"""
        host = (self.headers.get("Host") or "").lower()
        name = re.sub(r":\d+$", "", host)
        return name in ("127.0.0.1", "localhost", "[::1]") or host in auth.hosts() or name in auth.hosts()

    def widget_origin(self, url, origin):
        """El Origin si es un sitio que el dueño del bot autorizó para su widget (y la ruta es de conversación)."""
        match = origin and re.fullmatch(r"/api/v1/bots/([^/]+)/(events|audio|sessions/[^/]+/messages)", url)
        if not match:
            return None
        agent = find_bot(urllib.parse.unquote(match.group(1)))
        widget = (agent or {}).get("widget") or {}
        allowed = widget.get("origins") or [] if widget.get("enabled") else []
        return origin if origin in allowed or "*" in allowed else None

    def safely(self, method):
        self.status, self.sent, self.body, self.audit_action = None, {}, {}, None
        failed = False
        with telemetry.span("HTTP " + method, kind="server", metric="parla_http_request_duration_seconds",
                            parent=self.headers.get("traceparent") or "", **{"http.request.method": method}) as sp:
            try:
                self.route(method)
            except (ValueError, llm.LLMError) as error:      # mensajes pensados para la persona
                failed = True
                self.reply({"error": str(error)}, 400)
            except Exception:  # noqa: BLE001 - agente corrupto, disco: responder sin mostrar rutas ni detalles internos
                import traceback
                traceback.print_exc(file=sys.stderr)
                failed = True
                self.reply({"error": "Algo falló en el servidor. El detalle quedó en la consola de Parla."}, 500)
            route = telemetry.route_of(self.path)
            sp.name, sp.labels = "%s %s" % (method, route), {"route": route, "method": method}
            sp.set(**{"http.route": route, "http.response.status_code": self.status})
            if (self.status or 500) >= 500:
                sp.outcome = "error"
        telemetry.count("parla_http_requests_total", route=route, method=method, status=self.status)
        telemetry.log_request(method, route, self.status, sp)
        if failed:
            return
        try:
            self.audit(method)
        except Exception:  # noqa: BLE001 - la respuesta ya salió: que la auditoría rota no la tape, solo a la consola
            import traceback
            traceback.print_exc(file=sys.stderr)

    def do_GET(self): self.safely("GET")
    def do_POST(self): self.safely("POST")
    def do_PUT(self): self.safely("PUT")
    def do_DELETE(self): self.safely("DELETE")
    def do_OPTIONS(self): self.safely("OPTIONS")

    def log_message(self, *args):
        pass


def migrate():
    """Instalaciones viejas guardaban todo suelto en la raíz: lo mueve a data/ una vez (nunca borra)."""
    for name in ("agents", "users.json", "models"):
        old, new = os.path.join(ROOT, name), os.path.join(DATA, name)
        if os.path.exists(old) and not os.path.exists(new):
            os.makedirs(DATA, exist_ok=True)
            shutil.move(old, new)
            print("movido %s -> %s" % (old, new), flush=True)


def migrate_sessions():
    """Instalaciones de antes de parla.db: pasa cada agents/<id>.sessions/*.json a la base y deja la carpeta como
    <id>.sessions.migrated (no se borra). Se puede correr de nuevo: lo que ya está en la base no se pisa."""
    for name in sorted(os.listdir(AGENTS)):
        folder = os.path.join(AGENTS, name)
        if not (re.fullmatch(r"[0-9a-f]{8}\.sessions", name) and os.path.isdir(folder)):
            continue
        rows = []
        for file in sorted(os.listdir(folder)):
            try:
                with open(os.path.join(folder, file), encoding="utf-8") as f:
                    record = json.load(f)
                rows.append((name[:8], record["sessionId"], record.get("channel"), record.get("started"), record.get("updated") or now(),
                             int(bool((record.get("handoff") or {}).get("active"))), json.dumps(record, ensure_ascii=False)))
            except (OSError, ValueError, KeyError, TypeError, AttributeError) as error:
                print("no pude migrar %s: %s (queda en la carpeta .migrated)" % (os.path.join(folder, file), error), flush=True)
        with db.connect() as conn:
            conn.executemany("INSERT OR IGNORE INTO sessions (agent_id, session_id, channel, started, updated, handoff, record) "
                             "VALUES (?, ?, ?, ?, ?, ?, ?)", rows)
        done = folder + ".migrated"
        os.replace(folder, done if not os.path.exists(done) else done + "-" + time.strftime("%Y%m%d%H%M%S"))
        print("conversaciones migradas a parla.db: %s (%d)" % (name, len(rows)), flush=True)


def _days(value):
    """Días de retención: un entero >= 0, o None si no está puesto (o no es un número)."""
    try:
        return max(0, int(value)) if value not in (None, "") else None
    except (TypeError, ValueError):
        return None


def ago(days):
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(time.time() - days * 86400))


PII_IDLE_HOURS = 24      # con pii_redaction: una charla quieta tanto tiempo se cierra y su estado (con los datos reales) se borra


def cleanup():
    """Retención, al arrancar y cada hora: conversaciones sin movimiento en retention_days del agente (si no lo
    tiene, PARLA_RETENTION_DAYS; 0 o nada = para siempre), logins vencidos y auditoría de más de PARLA_AUDIT_DAYS (365).
    Los archivos del paso «Enviar un archivo» son del agente, no de cada conversación: no se tocan."""
    default = _days(os.environ.get("PARLA_RETENTION_DAYS"))
    for (agent_id,) in db.q("SELECT DISTINCT agent_id FROM sessions"):
        agent = settings_of(agent_id)
        days = _days(agent.get("retention_days"))
        days = default if days is None else days
        if days:
            db.q("DELETE FROM sessions WHERE agent_id = ? AND updated < ?", (agent_id, ago(days)))
        if pii.categories(agent.get("pii_redaction")):
            idle = db.q("SELECT record FROM sessions WHERE agent_id = ? AND updated < ? AND handoff = 0 AND json_extract(record, '$.ended') = 0",
                        (agent_id, ago(PII_IDLE_HOURS / 24)))
            for (raw,) in idle:
                record = json.loads(raw)
                record.update(ended=True, state={})      # sin tocar «updated»: la retención sigue contando desde la última charla
                save_session(agent_id, record)
    outbound.cleanup(lambda agent_id: (lambda d: default if d is None else d)(_days(settings_of(agent_id).get("retention_days"))))
    handoff.cleanup()           # entregas de webhooks de más de 30 días
    db.q("DELETE FROM logins WHERE expires < ?", (time.time(),))
    db.q("DELETE FROM audit WHERE at < ?", (ago(_days(os.environ.get("PARLA_AUDIT_DAYS")) or 365),))


def _hourly():
    while True:
        time.sleep(3600)
        try:
            cleanup()
        except Exception:  # noqa: BLE001 - que la limpieza no se muera: lo intenta de nuevo en una hora
            import traceback
            traceback.print_exc(file=sys.stderr)


def main():
    migrate()
    os.makedirs(AGENTS, exist_ok=True)
    migrate_sessions()
    if not os.listdir(AGENTS):
        create(DEMO)
    cleanup()
    threading.Thread(target=_hourly, daemon=True).start()
    outbound.start()            # la cola de campañas y recordatorios (sigue lo que quedó en parla.db)
    handoff.start()             # la cola de webhooks y el tiempo máximo de los handoffs externos
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8000
    print("Listo: http://127.0.0.1:%d  (Ctrl+C para salir)" % port, flush=True)
    from . import aserver       # asyncio: keep-alive, WebSocket/SSE, una fila por conversación (aserver.py)
    aserver.serve(os.environ.get("PARLA_HOST", "127.0.0.1"), port)


if __name__ == "__main__":
    main()
