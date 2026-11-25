#!/usr/bin/env python3
"""Servidor MCP de Parla: deja que Claude diseñe, cree, entrene y pruebe bots de Parla.

    .venv/bin/python mcp_server.py                 # stdio (Claude Code / Claude Desktop)
    .venv/bin/python mcp_server.py --http --port 8001   # streamable HTTP en /mcp, para hostearlo al lado de Parla

Env: PARLA_URL (default http://127.0.0.1:8000), PARLA_TOKEN (opcional, se manda como Authorization: Bearer),
PARLA_MCP_ALLOWED_HOSTS (opcional, con --http detrás de un proxy: hosts extra aceptados, ej. "bots.midominio.com").
"""
import argparse
import copy
import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
import uuid

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

try:  # celpy viene con Parla; si está, se chequea la sintaxis de las fórmulas CEL
    import celpy
    _CEL = celpy.Environment()
except ImportError:  # pragma: no cover
    _CEL = None

PARLA_URL = os.environ.get("PARLA_URL", "http://127.0.0.1:8000").rstrip("/")
PARLA_TOKEN = os.environ.get("PARLA_TOKEN", "")

# ---------- Lo que acepta el motor (copiado de server.py / web/index.html) ----------

START = "__start__"
STEP_TYPES = {"message", "ask", "set", "http", "if", "goto", "classify", "function", "end", "handoff", "call", "agent", "file"}
SYSTEM_KEYS = ("cancel", "repeat", "clarify", "anything_else", "resume", "correction", "handoff", "csat")   # app.SYSTEM_DEFAULTS
LANG_OK = re.compile(r"[a-z]{2}")
SECRET_REF = re.compile(r"\bsecret\.([A-Za-z_]\w*)")
LANGUAGES = {"python", "javascript"}
OPS = {"eq", "ne", "contains", "gt", "lt", "empty", "filled"}
METHODS = {"GET", "POST", "PUT", "PATCH", "DELETE"}
SET_MODES = {"text", "clear", "cel"}
PRESETS = {  # index.html KINDS: tipo de entidad -> regex que pone la interfaz (None = la escribís vos)
    "examples": "", "list": "",
    "number": r"\b\d+(?:[.,]\d+)?\b",
    "email": r"[\w.+-]+@[\w-]+\.[\w.-]+",
    "phone": r"\+?\d[\d\s().-]{6,}\d",
    "dni": r"\b\d{1,2}\.?\d{3}\.?\d{3}\b",
    "date": "",      # sin regex: el motor entiende fechas en lenguaje natural ("el jueves que viene a las 10")
    "custom": None,
}
RESERVED = {"intent", "confidence", "text", "entities", "status", "body", "true", "false", "null", "in"}
CONTEXT = {"intent", "confidence", "text", "entities"}   # variables que el motor agrega a los slots en {{ }} y CEL
ANNOT = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")
TEMPLATE = re.compile(r"\{\{(.+?)\}\}", re.S)
IDENT_OK = re.compile(r"[a-z_][a-z0-9_]*")
_STRINGS = re.compile(r"""[rRbB]{0,2}("(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*')""")
_NAMES = re.compile(r"(?<![\w.])([A-Za-z_]\w*)(?!\w)(?!\s*\()")   # identificadores sueltos, sin campos (.x) ni funciones f()
DEFINES_RUN = {"python": re.compile(r"^\s*(?:async\s+)?def\s+run\s*\(", re.M),
               "javascript": re.compile(r"\b(?:async\s+)?function\s+run\s*\(|\brun\s*=(?!=)")}
# ponytail: heurística de texto, no ve inputs leídos por otra variable (data = inputs; data["x"])
READS_INPUT = re.compile(r"""\binputs\s*(?:\[\s*["'](\w+)["']\s*\]|\.get\(\s*["'](\w+)["']|\.(\w+)\b(?!\s*\())""")


# ---------- HTTP a Parla ----------

def call(method, path, body=None):
    headers = {"Content-Type": "application/json"}
    if PARLA_TOKEN:
        headers["Authorization"] = "Bearer " + PARLA_TOKEN
    data = json.dumps(body, ensure_ascii=False).encode() if body is not None else None
    request = urllib.request.Request(PARLA_URL + path, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=120) as response:   # entrenar la primera vez baja el modelo
            raw = response.read()
    except urllib.error.HTTPError as error:
        raw = error.read()
        try:
            message = json.loads(raw).get("error") or raw.decode("utf-8", "replace")
        except (ValueError, AttributeError):
            message = raw.decode("utf-8", "replace")[:500]
        raise ToolError("Parla respondió %d en %s %s: %s" % (error.code, method, path, message)) from None
    except urllib.error.URLError as error:
        raise ToolError("No pude conectar con Parla en %s (%s). ¿Está corriendo? Revisá PARLA_URL." % (PARLA_URL, error.reason)) from None
    try:
        return json.loads(raw)
    except ValueError:
        raise ToolError("Parla devolvió algo que no es JSON en %s %s: %s" % (method, path, raw[:300])) from None


def resolve(agent):
    """id, nombre o slug -> id. Usa la misma búsqueda que la API pública."""
    ref = str(agent or "").strip()
    if not ref:
        raise ToolError("falta el agente (id, nombre o slug)")
    return call("GET", "/api/v1/bots/" + urllib.parse.quote(ref, safe=""))["id"]


def as_dict(agent_json):
    if isinstance(agent_json, str):
        try:
            agent_json = json.loads(agent_json)
        except ValueError as error:
            raise ToolError("agent_json no es un JSON válido: %s" % error) from None
    if not isinstance(agent_json, dict):
        raise ToolError("agent_json tiene que ser un objeto JSON con el agente")
    return agent_json


# ---------- Validación local ----------

def normalize(data):
    """Saca el sobre de exportación y completa los campos por defecto que pone la interfaz."""
    agent = copy.deepcopy(data.get("agent") if isinstance(data.get("agent"), dict) else data)
    for key in ("intents", "entities", "slots", "flows", "classifications", "functions"):
        agent.setdefault(key, [])
    for i, e in enumerate(agent["entities"] if isinstance(agent["entities"], list) else []):
        if isinstance(e, dict):
            e.setdefault("values", [])
            e.setdefault("color", i)
            if not e.get("regex"):
                e["regex"] = PRESETS.get(e.get("kind")) or ""
    for s in agent["slots"] if isinstance(agent["slots"], list) else []:
        if isinstance(s, dict):
            s.setdefault("entity", "")
    for doc in agent.get("knowledge") if isinstance(agent.get("knowledge"), list) else []:
        if isinstance(doc, dict):
            doc.setdefault("id", "k" + uuid.uuid4().hex[:6])
            doc.setdefault("source", "url" if doc.get("url") else "texto")
            doc.setdefault("url", "")
    return agent


def names_in(expr):
    return set(_NAMES.findall(_STRINGS.sub('""', expr))) - {"true", "false", "null", "in"}


def validate(data, files=None):
    """(agente normalizado, errores, advertencias). Errores = el bot no anda o anda distinto de lo que parece.
    files: [{id, name}] subidos a ese agente, para chequear los pasos file (None = no se sabe: solo advierte)."""
    errors, warnings = [], []
    if not isinstance(data, dict):
        return data, ["el agente tiene que ser un objeto JSON"], []
    agent = normalize(data)
    for key in ("intents", "entities", "slots", "flows", "classifications", "functions"):
        if not isinstance(agent[key], list):
            errors.append("«%s» tiene que ser una lista" % key)
    if errors:
        return agent, errors, warnings
    if not any(agent[k] for k in ("intents", "entities", "slots", "flows")):
        errors.append("el agente está vacío: Parla rechaza importar un agente sin intents, entities, slots ni flows")
    if not str(agent.get("name") or "").strip():
        warnings.append("falta «name»: se va a llamar «Nuevo agente»")
    threshold = agent.get("threshold", 0.75)
    if not isinstance(threshold, (int, float)) or isinstance(threshold, bool) or not 0 <= threshold <= 1:
        errors.append("«threshold» tiene que ser un número entre 0 y 1 (la interfaz usa 0.2 a 0.9; 0.75 por defecto)")
    fb = agent.get("fallback")
    if "fallback" in agent and not (isinstance(fb, str) or (isinstance(fb, list) and fb and all(isinstance(x, str) and x.strip() for x in fb))):
        errors.append("«fallback» tiene que ser un texto o una lista de textos no vacíos")

    # idiomas y traducciones
    langs = agent.get("languages") or ["es"]
    if not isinstance(langs, list) or not all(isinstance(l, str) and LANG_OK.fullmatch(l) for l in langs):
        errors.append("«languages» tiene que ser una lista de códigos de 2 letras, el primero es el idioma por defecto: [\"es\", \"pt\"]")
        langs = ["es"]
    others = set(langs[1:])

    def check_translations(where, tr, strings=True):
        """translations = {idioma: texto}; cada idioma tiene que estar en languages (y no ser el por defecto)."""
        if tr in (None, {}):
            return {}
        if not isinstance(tr, dict):
            errors.append("%s: «translations» tiene que ser {idioma: texto}" % where)
            return {}
        for lang, value in tr.items():
            if lang not in others:
                errors.append("%s: la traducción «%s» no es uno de los otros idiomas del agente (languages: %s); "
                              "sumalo a «languages» o sacala" % (where, lang, ", ".join(langs)))
            if strings and not isinstance(value, str):
                errors.append("%s: la traducción «%s» tiene que ser un texto" % (where, lang))
        return tr

    fbt = agent.get("fallback_translations")
    if fbt not in (None, {}):
        if not isinstance(fbt, dict):
            errors.append("«fallback_translations» tiene que ser {idioma: [textos]}")
        else:
            check_translations("fallback_translations", fbt, strings=False)
            for lang, value in fbt.items():
                if not (isinstance(value, str) or (isinstance(value, list) and value and all(isinstance(x, str) and x.strip() for x in value))):
                    errors.append("fallback_translations «%s»: tiene que ser un texto o una lista de textos no vacíos" % lang)
    for lang in sorted(others - set(fbt or {})) if isinstance(fbt, (dict, type(None))) else []:
        warnings.append("no hay «fallback_translations» para «%s»: si no entiende, contesta en %s" % (lang, langs[0]))

    # IA
    ai = agent.get("ai")
    if ai is not None and not isinstance(ai, dict):
        errors.append("«ai» tiene que ser un objeto {enabled, provider, url, model, ...}")
        ai = {}
    ai = ai or {}
    ai_on = ai.get("enabled") is True
    if ai.get("provider") not in (None, "ollama", "openai"):
        errors.append("ai: «provider» tiene que ser ollama u openai (servidor compatible local)")
    temp = ai.get("temperature", 0.2)
    if not isinstance(temp, (int, float)) or isinstance(temp, bool) or not 0 <= temp <= 2:
        errors.append("ai: «temperature» tiene que ser un número de 0 a 2")

    # base de conocimiento
    docs = agent.get("knowledge") or []
    if not isinstance(docs, list):
        errors.append("«knowledge» tiene que ser una lista de documentos [{title, text}]")
        docs = []
    seen_docs = set()
    for n, doc in enumerate(docs, 1):
        if not isinstance(doc, dict):
            errors.append("knowledge #%d no es un objeto" % n)
            continue
        if not isinstance(doc.get("text"), str) or not doc["text"].strip():
            errors.append("knowledge #%d («%s»): falta «text» con el contenido" % (n, doc.get("title") or "sin título"))
        if doc.get("id") in seen_docs:
            errors.append("knowledge #%d: el id «%s» está repetido" % (n, doc.get("id")))
        seen_docs.add(doc.get("id"))
        if not str(doc.get("title") or "").strip():
            warnings.append("knowledge #%d no tiene «title»: el título ayuda a encontrar la respuesta" % n)
    kt = agent.get("knowledge_threshold", 0.75)
    if not isinstance(kt, (int, float)) or isinstance(kt, bool) or not 0 <= kt <= 1:
        errors.append("«knowledge_threshold» tiene que ser un número entre 0 y 1 (0.75 por defecto)")

    # flujos del sistema
    system = agent.get("system")
    if system is not None and not isinstance(system, dict):
        errors.append("«system» tiene que ser {%s: {enabled, text?, examples?, translations?}}" % ", ".join(SYSTEM_KEYS))
        system = {}
    for key, conf in (system or {}).items():
        where = "system «%s»" % key
        if key not in SYSTEM_KEYS:
            errors.append("%s: no existe; los flujos del sistema son %s" % (where, ", ".join(SYSTEM_KEYS)))
            continue
        if not isinstance(conf, dict):
            errors.append("%s: tiene que ser un objeto {enabled, text, ...}" % where)
            continue
        if "enabled" in conf and not isinstance(conf["enabled"], bool):
            errors.append("%s: «enabled» tiene que ser true o false" % where)
        if "examples" in conf and not (isinstance(conf["examples"], list) and all(isinstance(x, str) for x in conf["examples"])):
            errors.append("%s: «examples» tiene que ser una lista de frases" % where)
        if "text" in conf and not isinstance(conf["text"], str):
            errors.append("%s: «text» tiene que ser un texto" % where)
        check_translations(where, conf.get("translations"))
    if any(((system or {}).get(k) or {}).get("enabled") is False for k in ("cancel", "handoff")):
        warnings.append("apagaste system cancel o handoff: la persona no va a poder cortar ni pedir hablar con alguien")

    # widget web
    widget = agent.get("widget")
    if widget is not None:
        if not isinstance(widget, dict):
            errors.append("«widget» tiene que ser {enabled, origins, title, color, greeting, position, voice}")
        else:
            origins = widget.get("origins") or []
            if not isinstance(origins, list) or not all(isinstance(o, str) for o in origins):
                errors.append("widget: «origins» tiene que ser una lista de sitios: [\"https://misitio.com\"]")
                origins = []
            for o in origins:
                if o != "*" and not re.fullmatch(r"https?://[^/\s]+", o):
                    errors.append("widget: el origen «%s» tiene que ser https://dominio (sin / ni ruta al final) o \"*\"" % o)
            if widget.get("enabled") and not origins:
                warnings.append("widget prendido sin «origins»: ningún sitio lo puede usar; poné los dominios de tu web")
            if "*" in origins:
                warnings.append("widget: «*» deja que cualquier sitio use el chat de este bot")
            if widget.get("position") not in (None, "left", "right"):
                errors.append("widget: «position» tiene que ser left o right")

    def unique(kind, items):
        seen = set()
        for i, item in enumerate(items):
            if not isinstance(item, dict):
                errors.append("%s #%d no es un objeto" % (kind, i + 1))
                continue
            name = item.get("name")
            if not isinstance(name, str) or not name.strip():
                errors.append("%s #%d no tiene «name»" % (kind, i + 1))
            elif name in seen:
                errors.append("%s «%s» está repetido" % (kind, name))
            seen.add(name)
        return [x for x in items if isinstance(x, dict) and isinstance(x.get("name"), str)]

    intents = unique("intent", agent["intents"])
    entities = unique("entity", agent["entities"])
    slots = unique("slot", agent["slots"])
    flows = unique("flow", agent["flows"])
    classifications = unique("classification", agent["classifications"])
    classification_names = {c["name"] for c in classifications}
    functions = unique("function", agent["functions"])
    function_names = {f["name"] for f in functions}
    used_functions = set()
    for c in classifications:
        color = c.get("color", 0)
        if not isinstance(color, int) or isinstance(color, bool) or not 0 <= color <= 5:
            errors.append("classification «%s»: «color» tiene que ser un entero de 0 a 5" % c["name"])
        if not isinstance(c.get("description", ""), str):
            errors.append("classification «%s»: «description» tiene que ser un texto" % c["name"])
    used_classifications = set()
    entity_names = {e["name"] for e in entities}
    slot_names = {s["name"] for s in slots}
    flow_names = {f["name"] for f in flows}
    intent_names = {i["name"] for i in intents}

    # entidades
    annotated = set()
    phrases = [(("intent «%s»" % i["name"]), ex) for i in intents for ex in (i.get("examples") or []) if isinstance(ex, str)]
    phrases += [(("entity «%s»" % e["name"]), ex) for e in entities for ex in (e.get("examples") or []) if isinstance(ex, str)]
    for where, phrase in phrases:
        for value, name in ANNOT.findall(phrase):
            annotated.add(name)
            if name not in entity_names:
                errors.append("%s: la frase «%s» marca [%s](%s) pero no existe la entidad «%s»" % (where, phrase, value, name, name))
    for e in entities:
        n, kind, regex, values = e["name"], e.get("kind"), e.get("regex") or "", e.get("values") or []
        if kind not in PRESETS:
            errors.append("entity «%s»: «kind» tiene que ser uno de %s (vino %r)" % (n, ", ".join(PRESETS), kind))
            continue
        if not isinstance(values, list) or not all(isinstance(v, str) for v in values):
            errors.append("entity «%s»: «values» tiene que ser una lista de textos" % n)
            values = []
        if regex:
            try:
                re.compile(regex, re.I)
            except re.error as error:
                errors.append("entity «%s»: la regex %r no es válida (%s); Parla la ignoraría en silencio" % (n, regex, error))
        if kind == "examples":
            if regex or values:
                errors.append("entity «%s»: kind «examples» no lleva regex ni values (si tiene, el motor no la aprende por contexto)" % n)
            if n not in annotated:
                warnings.append("entity «%s» (kind examples) no está marcada en ninguna frase: el bot no puede aprenderla. "
                                "Marcala así: «me llamo [pedro](%s)»" % (n, n))
        elif kind == "list":
            if not values:
                errors.append("entity «%s»: kind «list» necesita «values» con las opciones" % n)
            if regex:
                errors.append("entity «%s»: kind «list» no lleva regex" % n)
        elif kind == "custom":
            if not regex:
                errors.append("entity «%s»: kind «custom» necesita «regex»" % n)
        elif kind == "date":
            if regex or values:
                warnings.append("entity «%s»: kind «date» entiende fechas solas («mañana a las 10», «el jueves»); "
                                "no hace falta regex ni values (si los ponés, también se usan)" % n)
        elif regex != PRESETS[kind]:
            warnings.append("entity «%s»: la regex no es la del tipo «%s» (%s); el motor usa la que pusiste. "
                            "Si querés un formato propio usá kind «custom»" % (n, kind, PRESETS[kind]))
        synonyms = e.get("synonyms") or {}
        if not isinstance(synonyms, dict) or not all(isinstance(v, list) for v in synonyms.values()):
            errors.append("entity «%s»: «synonyms» tiene que ser {valor: [otras formas de decirlo]}" % n)
        else:
            for canonical in synonyms:
                if canonical not in values:
                    warnings.append("entity «%s»: el sinónimo apunta a «%s», que no está en «values»" % (n, canonical))
        if e.get("examples") is not None and not isinstance(e.get("examples"), list):
            errors.append("entity «%s»: «examples» tiene que ser una lista de frases" % n)

    # slots
    for s in slots:
        if not IDENT_OK.fullmatch(s["name"]) or s["name"] in RESERVED:
            errors.append("slot «%s»: el nombre tiene que ser minúsculas, números y _ (sin empezar con número) y no puede ser "
                          "%s; si no, no se puede usar en {{ }} ni en CEL" % (s["name"], ", ".join(sorted(RESERVED))))
        if s.get("entity") and s["entity"] not in entity_names:
            errors.append("slot «%s»: la entidad «%s» no existe" % (s["name"], s["entity"]))
        if "start" in s and not isinstance(s["start"], bool):
            errors.append("slot «%s»: «start» es true o false (true = dato que llega al iniciar la conversación)" % s["name"])
        if s.get("fill") not in (None, "", "ai"):
            errors.append("slot «%s»: «fill» solo puede ser \"ai\" (la IA lo completa leyendo «description»)" % s["name"])
        elif s.get("fill") == "ai":
            if not str(s.get("description") or "").strip():
                warnings.append("slot «%s»: con fill \"ai\" poné «description» (qué dato es y en qué formato): "
                                "es lo único que lee la IA" % s["name"])
            if not ai_on:
                warnings.append("slot «%s»: fill \"ai\" necesita la IA prendida (ai.enabled true); si no, rechaza la respuesta" % s["name"])

    # funciones
    for f in functions:
        w = "function «%s»" % f["name"]
        language = f.get("language") or "python"
        inputs = f.get("inputs") or []
        code = f.get("code") if isinstance(f.get("code"), str) else ""
        if language not in LANGUAGES:
            errors.append("%s: «language» tiene que ser python o javascript (vino %r)" % (w, language))
        if not isinstance(inputs, list) or not all(isinstance(x, str) for x in inputs):
            errors.append("%s: «inputs» tiene que ser una lista de nombres de slots" % w)
            inputs = []
        secret_in = [n for n in inputs if n.startswith("secret.")]
        for name in secret_in:
            if not SECRET_REF.fullmatch(name):
                errors.append("%s: la entrada «%s» tiene que ser secret.NOMBRE (letras, números y _)" % (w, name))
        for name in inputs:
            if name in secret_in:
                continue
            if name not in slot_names:
                errors.append("%s: la entrada «%s» no es un slot (slots: %s)" % (w, name, ", ".join(sorted(slot_names)) or "ninguno"))
        if not code.strip():
            errors.append("%s: falta «code» con una función run(inputs) que devuelva un objeto" % w)
            continue
        if language in LANGUAGES and not DEFINES_RUN[language].search(code):
            errors.append("%s: el código no define run(inputs) (%s)" % (
                w, "def run(inputs): ..." if language == "python" else "function run(inputs) { ... }"))
        if language == "python":
            try:
                compile(code, "funcion.py", "exec")
            except SyntaxError as error:
                errors.append("%s: error de sintaxis en la línea %s: %s" % (w, error.lineno, error.msg))
        read = {n for groups in READS_INPUT.findall(code) for n in groups if n} - {
            "get", "keys", "items", "values", "copy", "pop", "setdefault", "update", "hasOwnProperty", "length"} - (
            {"secret"} if secret_in else set())
        for name in sorted(read - set(inputs)):
            warnings.append("%s: el código lee inputs «%s» pero no está en «inputs»: va a llegar vacío (None/undefined). "
                            "Sumalo a «inputs»%s" % (w, name, "" if name in slot_names else " (y creá ese slot)"))

    # intents
    for f in flows:
        if "interrupts" in f and f["interrupts"] not in (True, False, "always"):
            errors.append("flow «%s»: «interrupts» es true, false (no corta una pregunta pendiente) o \"always\" (la corta "
                          "siempre, aunque el mensaje traiga el dato: urgencias)" % f["name"])
    triggers = [f.get("trigger") for f in flows]
    for i in intents:
        examples = i.get("examples")
        if not isinstance(examples, list) or not all(isinstance(x, str) for x in examples):
            errors.append("intent «%s»: «examples» tiene que ser una lista de frases" % i["name"])
            continue
        if i["name"].startswith("__"):
            errors.append("intent «%s»: los nombres con __ están reservados (%s y los flujos del sistema: usá «system» "
                          "para cancelar, repetir o pasar con una persona)" % (i["name"], START))
        real = [x for x in examples if x.strip()]
        if len(real) < 3:
            warnings.append("intent «%s» tiene %d frase(s): conviene 5 a 10 variadas" % (i["name"], len(real)))
        if len({x.strip().lower() for x in real}) < len(real):
            warnings.append("intent «%s» tiene frases repetidas" % i["name"])
        if i["name"] not in triggers:
            warnings.append("intent «%s» no dispara ningún flujo: el bot va a responder el fallback" % i["name"])

    # flujos
    starts = [f["name"] for f in flows if f.get("trigger") == START]
    if len(starts) > 1:
        errors.append("hay más de un flujo con trigger %s (%s): solo corre el primero" % (START, ", ".join(starts)))
    seen_triggers = {}
    for f in flows:
        t = f.get("trigger") or ""
        if t and t != START and t not in intent_names:
            errors.append("flow «%s»: el trigger «%s» no es el nombre de una intent ni %s" % (f["name"], t, START))
        if t and t != START:
            if t in seen_triggers:
                warnings.append("flow «%s»: la intent «%s» ya dispara «%s»; este flujo nunca arranca por esa intent"
                                % (f["name"], t, seen_triggers[t]))
            seen_triggers.setdefault(t, f["name"])

    gotos = set()

    def check_template(where, value, extra=()):
        if value in (None, ""):
            return
        if not isinstance(value, str):
            errors.append("%s: tiene que ser un texto" % where)
            return
        for expr in TEMPLATE.findall(value):
            check_cel(where, expr.strip(), extra, "{{ %s }}" % expr.strip())

    def check_cel(where, expr, extra=(), shown=None):
        shown = shown or expr
        if _CEL is not None:
            try:
                _CEL.compile(expr)
            except Exception as error:  # noqa: BLE001 - celpy tira varios tipos
                errors.append("%s: la fórmula %s no es CEL válido (%s)" % (where, shown, str(error).splitlines()[0][:160]))
                return
        for name in sorted(names_in(expr) - slot_names - CONTEXT - set(extra)):
            if name == "secret":
                errors.append("%s: %s usa una clave: {{ secret.NOMBRE }} solo vale en url/headers/body de un paso http "
                              "(o como entrada «secret.NOMBRE» de una función), nunca en lo que ve la persona" % (where, shown))
                continue
            errors.append("%s: %s usa «%s», que no es un slot (slots: %s)" % (where, shown, name, ", ".join(sorted(slot_names)) or "ninguno"))

    def bubble(w, step):
        """texto + translations + buttons de un message o ask."""
        check_template(w + " text", step.get("text"))
        for lang, value in check_translations(w, step.get("translations")).items():
            check_template("%s translations.%s" % (w, lang), value)
        buttons = step.get("buttons")
        if buttons in (None, []):
            return
        if not isinstance(buttons, list):
            errors.append("%s: «buttons» tiene que ser [{label, value?, translations?}]" % w)
            return
        if len(buttons) > 10:
            warnings.append("%s: %d botones son muchos; para más de 6 opciones conviene preguntar sin botones" % (w, len(buttons)))
        labels = set()
        for b in buttons:
            if not isinstance(b, dict) or not isinstance(b.get("label"), str) or not b["label"].strip():
                errors.append("%s: cada botón necesita «label» con un texto no vacío (vino %r)" % (w, b))
                continue
            if b["label"].strip().lower() in labels:
                errors.append("%s: el botón «%s» está repetido" % (w, b["label"]))
            labels.add(b["label"].strip().lower())
            if b.get("value") is not None and not (isinstance(b["value"], str) and b["value"].strip()):
                errors.append("%s: el botón «%s»: «value» tiene que ser un texto no vacío (o no ponerlo: vale el label)" % (w, b["label"]))
            check_translations("%s botón «%s»" % (w, b["label"]), b.get("translations"))

    where_flow = [None]

    def need_slot(where, slot):
        if not slot:
            errors.append("%s: falta «slot»" % where)
        elif slot not in slot_names:
            errors.append("%s: el slot «%s» no existe" % (where, slot))

    def steps(where, items):
        if not isinstance(items, list):
            errors.append("%s: los pasos tienen que ser una lista" % where)
            return
        for n, step in enumerate(items, 1):
            w = "%s, paso %d" % (where, n)
            if not isinstance(step, dict):
                errors.append("%s: no es un objeto" % w)
                continue
            kind = step.get("type")
            w += " (%s)" % kind
            if kind not in STEP_TYPES:
                errors.append("%s: tipo de paso desconocido; tiene que ser uno de %s" % (w, ", ".join(sorted(STEP_TYPES))))
            elif kind == "message":
                if not str(step.get("text") or "").strip():
                    warnings.append("%s: mensaje vacío" % w)
                bubble(w, step)
            elif kind == "ask":
                need_slot(w, step.get("slot"))
                if not str(step.get("text") or "").strip():
                    errors.append("%s: falta «text» con la pregunta" % w)
                also = step.get("also")
                if also is not None and (not isinstance(also, list) or any(e not in entity_names for e in also)):
                    errors.append("%s: «also» es una lista de entidades que también cuentan como respuesta (entidades: %s)"
                                  % (w, ", ".join(sorted(entity_names)) or "ninguna"))
                bubble(w, step)
            elif kind == "file":
                ref = str(step.get("file") or "").strip()
                known = {x for f in files or [] for x in (f["id"], f["name"].lower())}
                if not ref:
                    errors.append("%s: falta «file» con el id o el nombre del archivo (list_files los muestra)" % w)
                elif files is None:
                    warnings.append("%s: no puedo comprobar que el archivo «%s» exista: lo sube la persona en Parla "
                                    "(paso «Enviar un archivo») y list_files muestra los que hay" % (w, ref))
                elif ref not in known and ref.lower() not in known:
                    errors.append("%s: el archivo «%s» no está subido a este agente (hay: %s)"
                                  % (w, ref, ", ".join(f["name"] for f in files) or "ninguno"))
                check_template(w + " text", step.get("text"))
                for lang, value in check_translations(w, step.get("translations")).items():
                    check_template("%s translations.%s" % (w, lang), value)
            elif kind == "handoff":
                if step.get("reason") is not None and not isinstance(step.get("reason"), str):
                    errors.append("%s: «reason» tiene que ser un texto (por qué se pasa: «reclamo», «venta grande»)" % w)
                elif not str(step.get("reason") or "").strip():
                    warnings.append("%s: poné «reason» (por qué se pasa): lo ve la persona que atiende en la Bandeja" % w)
                check_template(w + " text", step.get("text"))
                for lang, value in check_translations(w, step.get("translations")).items():
                    check_template("%s translations.%s" % (w, lang), value)
            elif kind == "call":
                target = step.get("flow")
                gotos.add(target)
                if not target:
                    errors.append("%s: falta «flow» con el subflujo a llamar" % w)
                elif target not in flow_names:
                    errors.append("%s: el flujo «%s» no existe" % (w, target))
                elif target == where_flow[0]:
                    errors.append("%s: el flujo se llama a sí mismo: loop" % w)
            elif kind == "agent":
                if not str(step.get("instructions") or "").strip():
                    errors.append("%s: falta «instructions» (qué tiene que lograr la IA y cómo)" % w)
                if not str(step.get("goal") or "").strip():
                    warnings.append("%s: poné «goal» (cuándo terminó, p.ej. «cuando el plan esté elegido»): "
                                    "si no, sigue hasta agotar max_turns" % w)
                fns = step.get("functions") or []
                if not isinstance(fns, list) or not all(isinstance(x, str) for x in fns):
                    errors.append("%s: «functions» tiene que ser una lista de nombres de funciones" % w)
                    fns = []
                for name in fns:
                    used_functions.add(name)
                    if name not in function_names:
                        errors.append("%s: la función «%s» no existe en «functions» (hay: %s)"
                                      % (w, name, ", ".join(sorted(function_names)) or "ninguna"))
                wanted = step.get("slots") or []
                if not isinstance(wanted, list) or not all(isinstance(x, str) for x in wanted):
                    errors.append("%s: «slots» tiene que ser una lista de nombres de slots" % w)
                    wanted = []
                for name in wanted:
                    need_slot(w + " slots", name)
                turns = step.get("max_turns", 8)
                if not isinstance(turns, int) or isinstance(turns, bool) or not 1 <= turns <= 50:
                    errors.append("%s: «max_turns» tiene que ser un entero de 1 a 50" % w)
                if step.get("knowledge") and not docs:
                    warnings.append("%s: knowledge true pero el agente no tiene documentos en «knowledge»" % w)
                if not ai_on:
                    warnings.append("%s: el paso agent necesita la IA prendida (ai.enabled true); si no, contesta «La IA no está configurada» y sigue" % w)
            elif kind == "set":
                need_slot(w, step.get("slot"))
                mode = step.get("mode") or "text"
                if mode not in SET_MODES:
                    errors.append("%s: «mode» tiene que ser text, clear o cel" % w)
                elif mode == "text":
                    check_template(w + " text", step.get("text"))
                elif mode == "cel":
                    if not str(step.get("expr") or "").strip():
                        errors.append("%s: mode cel necesita «expr»" % w)
                    else:
                        check_cel(w + " expr", step["expr"])
            elif kind == "http":
                url = str(step.get("url") or "").strip()
                if not url:
                    errors.append("%s: falta «url»" % w)
                elif not url.startswith(("http://", "https://", "{{")):
                    errors.append("%s: la url tiene que empezar con http:// o https://" % w)
                check_template(w + " url", step.get("url"), ("secret",))
                if (step.get("method") or "GET") not in METHODS:
                    errors.append("%s: «method» tiene que ser %s" % (w, ", ".join(sorted(METHODS))))
                headers = step.get("headers") or []
                if not isinstance(headers, list) or not all(isinstance(h, dict) for h in headers):
                    errors.append("%s: «headers» tiene que ser [{key, value}]" % w)
                else:
                    for h in headers:
                        check_template(w + " header", h.get("key"), ("secret",))
                        check_template(w + " header", h.get("value"), ("secret",))
                        if re.search(r"(?i)authorization|token|api[-_]?key", str(h.get("key") or "")) and \
                                str(h.get("value") or "").strip() and "{{" not in str(h.get("value")):
                            warnings.append("%s: el header «%s» tiene una credencial escrita a mano; guardala en Claves y "
                                            "usá {{ secret.NOMBRE }}" % (w, h.get("key")))
                check_template(w + " body", step.get("body"), ("secret",))
                saves = step.get("saves") or []
                if not isinstance(saves, list) or not all(isinstance(s, dict) for s in saves):
                    errors.append("%s: «saves» tiene que ser [{expr, slot}]" % w)
                else:
                    for s in saves:
                        need_slot(w + " saves", s.get("slot"))
                        check_cel(w + " saves", str(s.get("expr") or "body"), ("status", "body"))
            elif kind == "if":
                cond = step.get("cond")
                if cond:
                    if not isinstance(cond, dict):
                        errors.append("%s: «cond» tiene que ser {var, op, value}" % w)
                    else:
                        var = cond.get("var")
                        if not var:
                            errors.append("%s: la condición no tiene «var»" % w)
                        elif var not in slot_names:
                            errors.append("%s: la condición mira «%s», que no es un slot (cond solo compara slots; "
                                          "para intent/text usá «expr» en CEL)" % (w, var))
                        if cond.get("op") not in OPS:
                            errors.append("%s: «op» tiene que ser uno de %s" % (w, ", ".join(sorted(OPS))))
                        if cond.get("op") in ("gt", "lt"):
                            try:
                                float(str(cond.get("value")).replace(",", "."))
                            except ValueError:
                                errors.append("%s: con gt/lt «value» tiene que ser un número" % w)
                elif str(step.get("expr") or "").strip():
                    check_cel(w + " expr", step["expr"])
                else:
                    errors.append("%s: falta «cond» {var, op, value} o «expr» (sin eso nunca se cumple)" % w)
                steps(w + " → then", step.get("then") or [])
                steps(w + " → else", step.get("else") or [])
            elif kind == "classify":
                name = step.get("classification")
                used_classifications.add(name)
                if not name:
                    errors.append("%s: falta «classification» con el nombre de la clasificación" % w)
                elif name not in classification_names:
                    errors.append("%s: la clasificación «%s» no existe en «classifications» (hay: %s)"
                                  % (w, name, ", ".join(sorted(classification_names)) or "ninguna"))
            elif kind == "function":
                name = step.get("function")
                used_functions.add(name)
                if not name:
                    errors.append("%s: falta «function» con el nombre de la función" % w)
                elif name not in function_names:
                    errors.append("%s: la función «%s» no existe en «functions» (hay: %s)"
                                  % (w, name, ", ".join(sorted(function_names)) or "ninguna"))
                saves = step.get("saves") or []
                if not isinstance(saves, list) or not all(isinstance(s, dict) for s in saves):
                    errors.append("%s: «saves» tiene que ser [{expr, slot}]" % w)
                else:
                    for s in saves:
                        need_slot(w + " saves", s.get("slot"))
                        check_cel(w + " saves", str(s.get("expr") or "result"), ("result", "ok", "error"))
            elif kind == "goto":
                target = step.get("flow") or step.get("goto")
                gotos.add(target)
                if not target:
                    errors.append("%s: falta «flow» con el flujo a seguir" % w)
                elif target not in flow_names:
                    errors.append("%s: el flujo «%s» no existe" % (w, target))

    for f in flows:
        if not f.get("steps"):
            warnings.append("flow «%s» no tiene pasos" % f["name"])
        where_flow[0] = f["name"]
        steps("flow «%s»" % f["name"], f.get("steps") or [])
    for f in flows:
        if not f.get("trigger") and f["name"] not in gotos:
            warnings.append("flow «%s» no tiene trigger y ningún goto/call lo llama: nunca corre" % f["name"])
    for name in sorted(function_names - used_functions):
        warnings.append("function «%s» no la ejecuta ningún paso function ni agent: nunca corre" % name)
    for name in sorted(classification_names - used_classifications):
        warnings.append("classification «%s» no la aplica ningún paso classify: siempre va a dar 0 en el reporte" % name)
    return agent, errors, warnings


def secret_refs(agent):
    """Nombres de claves que usa el agente ({{ secret.X }} en http, entradas secret.X de funciones)."""
    return set(SECRET_REF.findall(json.dumps([agent.get("flows"), agent.get("functions")], ensure_ascii=False)))


def secret_warnings(agent_id, agent):
    """Claves que el agente usa y todavía no tienen valor. El MCP solo ve los nombres, nunca los valores."""
    missing = sorted(secret_refs(agent) - set(call("GET", "/api/agents/%s/secrets" % agent_id).get("secrets") or []))
    return ["faltan cargar las claves %s: pedile a la persona que las cargue en la sección Claves de Parla "
            "(el MCP no puede ver ni escribir valores)" % ", ".join(missing)] if missing else []


def validated(agent_json, files=None):
    agent, errors, warnings = validate(as_dict(agent_json), files)
    if errors:
        raise ToolError("El agente tiene errores, no lo guardé:\n- " + "\n- ".join(errors) +
                        ("\nAdvertencias:\n- " + "\n- ".join(warnings) if warnings else ""))
    return {k: v for k, v in agent.items() if k not in ("id", "trained")}, warnings


# ---------- Guía del formato ----------

DEMO_IVR = {
    "name": "Demo IVR", "threshold": 0.75, "fallback": "No entendí, ¿me lo decís de otra forma?",
    "intents": [
        {"name": "Consultar saldo", "examples": ["quiero saber mi saldo", "cuánta plata tengo", "saldo de mi cuenta", "cuánto me queda"]},
        {"name": "Hablar con alguien", "examples": ["quiero hablar con una persona", "pasame con un operador", "necesito un humano"]}],
    "entities": [{"name": "dni", "kind": "number", "regex": PRESETS["number"], "values": [], "color": 3}],
    "slots": [{"name": "dni", "entity": "dni", "start": True}, {"name": "nombre", "entity": ""}, {"name": "codigo_respuesta", "entity": ""},
              {"name": "email", "entity": ""}],
    "flows": [
        {"name": "Bienvenida", "trigger": "__start__", "steps": [
            {"type": "if", "cond": {"var": "dni", "op": "empty", "value": ""},
             "then": [{"type": "ask", "slot": "dni", "text": "Hola, para empezar decime tu DNI (probá del 1 al 10)."}], "else": []},
            {"type": "http", "method": "GET", "url": "https://jsonplaceholder.typicode.com/users/{{ dni }}", "headers": [], "body": "",
             "saves": [{"expr": "status", "slot": "codigo_respuesta"}, {"expr": "body.name", "slot": "nombre"},
                       {"expr": "body.email", "slot": "email"}]},
            {"type": "if", "cond": {"var": "codigo_respuesta", "op": "eq", "value": "200"},
             "then": [{"type": "message", "text": "¡Hola {{ nombre }}! ¿En qué te puedo ayudar? Puedo decirte tu saldo o pasarte con alguien."}],
             "else": [{"type": "message", "text": "No encontré a nadie con el DNI {{ dni }}. ¿En qué te puedo ayudar igual?"}]}]},
        {"name": "Saldo", "trigger": "Consultar saldo", "steps": [
            {"type": "message", "text": "{{ nombre }}, tu saldo es de $ 152.300. Te lo mandamos también a {{ email }}."}]},
        {"name": "Operador", "trigger": "Hablar con alguien", "steps": [
            {"type": "message", "text": "Te paso con una persona del equipo. Ya tiene tu DNI {{ dni }}, no hace falta que lo repitas."}]}],
}

TOTAL_CODE = """PRECIOS = {"muzzarella": 9500, "napolitana": 10500, "fugazzeta": 11000}

def run(inputs):
    cantidad = int(inputs["cantidad"])          # los slots llegan como texto: "2"
    if cantidad < 1:
        raise ValueError("la cantidad tiene que ser 1 o más")
    total = PRECIOS[inputs["gusto"]] * cantidad
    promo = cantidad >= 3
    if promo:
        total = round(total * 0.9)              # 10% off desde 3 pizzas
    print("total calculado:", total)            # va a logs y a la traza, no al chat
    return {"total": total, "promo": promo}     # mismas claves que los slots: se guardan solas
"""

PIZZA_SNIPPET = {
    "intents": [{"name": "Pedir pizza", "examples": [
        "quiero [2](cantidad) pizzas de [muzzarella](gusto)", "mandame una [napo](gusto)", "quiero pedir una pizza",
        "haceme [3](cantidad) de [fugazzeta](gusto)", "me llamo [pedro](nombre) y quiero una pizza", "tienen delivery?"]}],
    "entities": [
        {"name": "gusto", "kind": "list", "regex": "", "values": ["muzzarella", "napolitana", "fugazzeta"],
         "synonyms": {"muzzarella": ["muzza", "mozzarella"], "napolitana": ["napo"]}},
        {"name": "cantidad", "kind": "number", "regex": PRESETS["number"], "values": []},
        {"name": "nombre", "kind": "examples", "regex": "", "values": [], "examples": ["soy [magui](nombre)", "mi nombre es [juan](nombre)"]}],
    "slots": [{"name": "gusto", "entity": "gusto"}, {"name": "cantidad", "entity": "cantidad"},
              {"name": "nombre", "entity": "nombre"}, {"name": "total", "entity": ""}, {"name": "promo", "entity": ""},
              {"name": "total_ok", "entity": ""}, {"name": "total_error", "entity": ""}],
    "functions": [{"name": "calcular_total", "description": "Precio del pedido con 10% off desde 3 pizzas",
                   "language": "python", "inputs": ["gusto", "cantidad"], "code": TOTAL_CODE}],
    "flows": [
        {"name": "Pedido", "trigger": "Pedir pizza", "steps": [
            {"type": "ask", "slot": "nombre", "text": "¿A nombre de quién?"},
            {"type": "ask", "slot": "gusto", "text": "¿De qué gusto? Tenemos muzzarella, napolitana y fugazzeta."},
            {"type": "ask", "slot": "cantidad", "text": "¿Cuántas de {{ gusto }}? Escribilo en números."},
            {"type": "function", "function": "calcular_total", "auto_save": True,
             "saves": [{"expr": "ok", "slot": "total_ok"}, {"expr": "ok ? '' : error", "slot": "total_error"}]},
            {"type": "if", "cond": {"var": "total_ok", "op": "eq", "value": "false"},
             "then": [{"type": "message", "text": "Uy, no pude calcular el total ({{ total_error }}). ¿Me decís la cantidad en números?"},
                      {"type": "set", "slot": "cantidad", "mode": "clear"}, {"type": "end"}],
             "else": []},
            {"type": "if", "expr": "int(cantidad) > 5",
             "then": [{"type": "message", "text": "¡Uh, {{ nombre }}, son muchas! Te llamamos para coordinar."}, {"type": "end"}],
             "else": []},
            {"type": "message", "text": "Listo {{ nombre }}: {{ cantidad }} de {{ gusto }}, total $ {{ total }}{{ promo ? ' (con 10% off)' : '' }}."},
            {"type": "classify", "classification": "Pedido tomado"},
            {"type": "set", "slot": "gusto", "mode": "clear"},
            {"type": "set", "slot": "cantidad", "mode": "clear"},
            {"type": "goto", "flow": "Despedida"}]},
        {"name": "Despedida", "trigger": "", "steps": [{"type": "message", "text": "¡Gracias por elegirnos!"}]}],
    "classifications": [{"name": "Pedido tomado", "color": 1, "description": "Se confirmó un pedido"}],
}

TURNOS_SNIPPET = {
    "name": "Turnos médicos", "threshold": 0.75, "fallback": "No te entendí. Puedo darte un turno o cancelarlo.",
    "classifications": [
        {"name": "Cita agendada", "color": 1, "description": "La persona confirmó un turno"},
        {"name": "Cancelación", "color": 4, "description": "La persona canceló su turno"}],
    "intents": [
        {"name": "Pedir turno", "examples": [
            "quiero sacar un turno", "necesito un turno con [cardiología](especialidad)", "me das turno para [clínica](especialidad)",
            "quería pedir una cita", "turno con el [dermatólogo](especialidad) por favor", "sacame un turno"]},
        {"name": "Cancelar turno", "examples": [
            "quiero cancelar mi turno", "no voy a poder ir, cancelalo", "anulá el turno", "necesito dar de baja la cita",
            "cancelame el turno del martes"]}],
    "entities": [
        {"name": "especialidad", "kind": "list", "regex": "", "values": ["clínica", "cardiología", "dermatología"],
         "synonyms": {"clínica": ["clinica", "clínico", "médico de cabecera"], "cardiología": ["cardiologia", "cardiólogo"],
                      "dermatología": ["dermatologia", "dermatólogo", "dermatologo"]}},
        {"name": "dni", "kind": "dni", "regex": PRESETS["dni"], "values": []}],
    "slots": [{"name": "especialidad", "entity": "especialidad"}, {"name": "dni", "entity": "dni"}],
    "flows": [
        {"name": "Turno", "trigger": "Pedir turno", "steps": [
            {"type": "ask", "slot": "especialidad", "text": "¿Para qué especialidad? Clínica, cardiología o dermatología."},
            {"type": "ask", "slot": "dni", "text": "¿Me pasás tu DNI?"},
            {"type": "message", "text": "Listo, te agendé un turno de {{ especialidad }} para el DNI {{ dni }}."},
            {"type": "classify", "classification": "Cita agendada"},
            {"type": "set", "slot": "especialidad", "mode": "clear"}]},
        {"name": "Cancelar", "trigger": "Cancelar turno", "steps": [
            {"type": "ask", "slot": "dni", "text": "¿Cuál es tu DNI?"},
            {"type": "message", "text": "Cancelé el turno del DNI {{ dni }}."},
            {"type": "classify", "classification": "Cancelación"}]}],
}

COTIZAR_CODE = """PLANES = {"basico": 9900, "plus": 15900, "pro": 24900}

def run(inputs):
    plan = (inputs.get("plan") or "").lower()
    if plan not in PLANES:
        raise ValueError("planes: basico, plus o pro")
    return {"precio": PLANES[plan]}
"""

SOPORTE_SNIPPET = {
    "name": "Soporte Tienda", "threshold": 0.75, "languages": ["es", "pt"],
    "fallback": ["No te entendí bien. ¿Me lo decís de otra forma?",
                 "Perdón, no lo entendí. Puedo ayudarte con tu pedido, una devolución o un reclamo."],
    "fallback_translations": {"pt": ["Não entendi. Pode dizer de outro jeito?"]},
    "ai": {"enabled": True, "provider": "ollama", "url": "http://127.0.0.1:11434", "model": "qwen2.5:0.5b",
           "temperature": 0.2, "generative_fallback": True, "rescue_intents": True, "use_knowledge": True,
           "persona": "Amable y breve, en español rioplatense."},
    "knowledge": [{"id": "kfaq01", "title": "Preguntas frecuentes", "source": "texto", "url": "", "text":
                   "P: ¿Qué días abren?\nR: De lunes a sábado de 9 a 20 h. Los domingos y feriados está cerrado.\n\n"
                   "P: ¿Hacen envíos?\nR: Sí, a todo el país. Llegan en 2 a 5 días hábiles y son gratis desde $ 50.000.\n\n"
                   "P: ¿Cómo puedo pagar?\nR: Con tarjeta de crédito o débito, transferencia o efectivo en el local."}],
    "knowledge_threshold": 0.75,
    "system": {"cancel": {"enabled": True}, "repeat": {"enabled": True}, "clarify": {"enabled": True},
               "resume": {"enabled": True}, "correction": {"enabled": True},
               "handoff": {"enabled": True, "text": "Te paso con una persona del equipo, ya te escriben.",
                           "translations": {"pt": "Vou te passar para uma pessoa da equipe."}},
               "csat": {"enabled": True, "text": "¿Cómo te atendí? Del 1 al 5.", "translations": {"pt": "Como foi o atendimento? De 1 a 5."}},
               "anything_else": {"enabled": False}},
    "widget": {"enabled": True, "origins": ["https://mitienda.com"], "title": "¿Te ayudamos?", "color": "#2f6bff",
               "greeting": "", "position": "right", "voice": False},
    "intents": [
        {"name": "Estado del pedido", "examples": [
            "dónde está mi pedido", "quiero saber cómo viene mi compra", "estado del pedido [48213](pedido)",
            "mi pedido [10293](pedido) no llegó", "rastrear envío", "cuándo me llega la compra", "estado de mi pedido",
            "onde está meu pedido"]},
        {"name": "Devolución", "examples": [
            "quiero devolver un producto", "cómo hago una devolución", "quiero cambiar lo que compré",
            "me llegó fallado y lo quiero devolver", "devolver la compra del [lunes](fecha)", "hacer una devolución",
            "quero devolver um produto", "devoluciones"]},
        {"name": "Reclamo", "examples": [
            "quiero hacer un reclamo", "estoy muy enojado con el servicio", "es la tercera vez que me pasa esto",
            "me cobraron de más", "pésima atención, quiero quejarme", "tengo una queja", "quero fazer uma reclamação",
            "reclamo"]},
        {"name": "Elegir plan", "examples": [
            "qué plan me conviene", "quiero contratar un plan", "cuánto sale el plan plus", "ayudame a elegir un plan",
            "qué diferencia hay entre los planes", "planes y precios", "quero contratar um plano", "planes"]}],
    "entities": [{"name": "pedido", "kind": "number", "regex": PRESETS["number"], "values": []},
                 {"name": "fecha", "kind": "date", "regex": "", "values": []},
                 {"name": "dni", "kind": "dni", "regex": PRESETS["dni"], "values": []}],
    "slots": [{"name": "pedido", "entity": "pedido"}, {"name": "fecha", "entity": "fecha", "description": "Día de la compra"},
              {"name": "motivo", "entity": "", "fill": "ai",
               "description": "Por qué devuelve el producto, en pocas palabras (fallado, talle, no le gustó...)"},
              {"name": "dni", "entity": "dni"}, {"name": "cliente", "entity": ""}, {"name": "codigo", "entity": ""},
              {"name": "plan", "entity": ""}, {"name": "precio", "entity": ""}],
    "functions": [{"name": "cotizar", "description": "Precio mensual de un plan (basico, plus, pro)",
                   "language": "python", "inputs": ["plan"], "code": COTIZAR_CODE}],
    "classifications": [{"name": "Pedido consultado", "color": 1}, {"name": "Devolución iniciada", "color": 2},
                        {"name": "Reclamo derivado", "color": 4}, {"name": "Plan elegido", "color": 3}],
    "flows": [
        {"name": "Bienvenida", "trigger": "__start__", "steps": [
            {"type": "message", "text": "¡Hola! Soy el asistente de la tienda. ¿En qué te ayudo?",
             "translations": {"pt": "Olá! Sou o assistente da loja. Como posso ajudar?"},
             "buttons": [{"label": "Mi pedido", "value": "estado de mi pedido", "translations": {"pt": "Meu pedido"}},
                         {"label": "Devoluciones", "value": "hacer una devolución", "translations": {"pt": "Devoluções"}},
                         {"label": "Planes", "value": "planes y precios", "translations": {"pt": "Planos"}}]}]},
        {"name": "Validar identidad", "trigger": "", "steps": [
            {"type": "ask", "slot": "dni", "text": "Para seguir, ¿me pasás tu DNI?", "translations": {"pt": "Para continuar, qual é o seu documento?"}},
            {"type": "http", "method": "GET", "url": "https://crm.mitienda.com/clientes/{{ dni }}",
             "headers": [{"key": "Authorization", "value": "Bearer {{ secret.CRM_TOKEN }}"}], "body": "",
             "saves": [{"expr": "status", "slot": "codigo"}, {"expr": "body.nombre", "slot": "cliente"}]}]},
        {"name": "Pedido", "trigger": "Estado del pedido", "steps": [
            {"type": "ask", "slot": "pedido", "text": "¿Cuál es el número de pedido?", "translations": {"pt": "Qual é o número do pedido?"}},
            {"type": "message", "text": "El pedido {{ pedido }} está en camino: llega en 48 h.",
             "translations": {"pt": "O pedido {{ pedido }} está a caminho: chega em 48 h."}},
            {"type": "classify", "classification": "Pedido consultado"},
            {"type": "set", "slot": "pedido", "mode": "clear"}]},
        {"name": "Devolver", "trigger": "Devolución", "steps": [
            {"type": "call", "flow": "Validar identidad"},
            {"type": "ask", "slot": "fecha", "text": "¿Qué día hiciste la compra?", "translations": {"pt": "Em que dia você comprou?"}},
            {"type": "ask", "slot": "motivo", "text": "¿Por qué lo querés devolver?",
             "buttons": [{"label": "Llegó fallado", "translations": {"pt": "Chegou com defeito"}},
                         {"label": "No es mi talle", "translations": {"pt": "Não é meu tamanho"}},
                         {"label": "Otro motivo", "value": "otro"}]},
            {"type": "message", "text": "Listo, inicié la devolución de la compra del {{ fecha }} (motivo: {{ motivo }}). Te llega un mail con la etiqueta."},
            {"type": "classify", "classification": "Devolución iniciada"},
            {"type": "set", "slot": "fecha", "mode": "clear"}, {"type": "set", "slot": "motivo", "mode": "clear"}]},
        {"name": "Reclamos", "trigger": "Reclamo", "steps": [
            {"type": "classify", "classification": "Reclamo derivado"},
            {"type": "handoff", "reason": "reclamo", "text": "Lamento lo que pasó. Te paso con una persona del equipo para resolverlo.",
             "translations": {"pt": "Sinto muito. Vou te passar para uma pessoa da equipe."}}]},
        {"name": "Asesor de planes", "trigger": "Elegir plan", "steps": [
            {"type": "agent", "instructions": "Ayudá a elegir entre los planes basico, plus y pro según lo que necesita la "
             "persona. Usá cotizar para dar el precio exacto; no inventes precios.", "functions": ["cotizar"],
             "knowledge": True, "slots": ["plan"], "goal": "cuando la persona eligió un plan", "max_turns": 6},
            {"type": "function", "function": "cotizar", "saves": [{"expr": "ok", "slot": "codigo"}]},
            {"type": "if", "cond": {"var": "codigo", "op": "eq", "value": "false"},
             "then": [{"type": "handoff", "reason": "no se pudo cotizar el plan"}], "else": []},
            {"type": "message", "text": "Perfecto, el plan {{ plan }} sale $ {{ precio }} por mes."},
            {"type": "classify", "classification": "Plan elegido"}]}],
}

GUIDE = """# Formato de un agente de Parla (JSON)

Un agente es un objeto JSON con: name, threshold, fallback, intents, entities, slots, flows.
Al crear/importar se ignoran "id" y "trained" (los pone Parla). También se acepta el sobre de exportación
{"parla": 1, "agent": {...}}. También: classifications, functions, languages, knowledge, system, ai, widget
(ver abajo). Todo lo nuevo es opcional: un agente sin esos campos anda igual.

## Campos de primer nivel
- name (texto, máx 80): nombre visible. El slug para la API sale de acá ("Pizzería Don Luis" -> "pizzeria-don-luis").
- threshold (número 0..1, default 0.75): similitud mínima para aceptar la intención detectada. Debajo -> fallback.
- fallback (texto o lista de textos): lo que responde cuando no entiende o la intención no tiene flujo. Con una
  lista elige una al azar sin repetir la anterior; conviene 3 o 4 variantes para que suene natural.
- languages (lista de códigos de 2 letras, default ["es"]): el primero es el idioma por defecto. La charla toma el
  idioma que viene en start data {"idioma": "pt"} o el que se adivina del primer mensaje. Las frases de las intents
  pueden mezclar idiomas (los embeddings son multilingües): sumá 1-2 frases por idioma extra en cada intent.
- fallback_translations: {"pt": ["Não entendi..."]}: el fallback en los otros idiomas.
- knowledge_threshold (0..1, default 0.75): puntaje mínimo para contestar con la base de conocimiento.

## intents: [{name, examples: [frases]}]
- La intención se detecta por vecino más cercano con embeddings multilingües sobre las frases (sin las marcas).
- Marcá entidades dentro de las frases con [valor](entidad): "quiero [2](cantidad) de [muzza](gusto)".
  La entidad tiene que existir. Las marcas enseñan al CRF (kind examples) y además agregan ese valor como forma conocida.
- Poné 6 a 12 frases variadas por intención (cantidades parecidas entre intents), en español rioplatense natural (voseo: "quiero", "mandame", "pasame",
  "che, ¿cuánto sale?"), cortas y largas, con y sin datos marcados. Menos de 3 frases = advertencia.
- Una intención sin flujo con ese trigger responde el fallback.
- Los nombres que empiezan con "__" están reservados ("__start__" y las intenciones de los flujos del sistema).

## entities: [{name, kind, regex, values, synonyms?, examples?, color?}]
El motor NO lee "kind": reconoce por "regex" (si hay), por "values"/"synonyms" (si hay) y, si no tiene ni regex ni
values, la aprende el CRF por contexto de las frases marcadas. "kind" lo usa la interfaz y debe ser coherente:
- "examples": sin regex ni values. Se aprende del contexto: "me llamo [pedro](nombre)" -> reconoce "me llamo olivia".
  Necesita varias frases marcadas (en intents o en su propio "examples"). Guarda el valor tal como lo escribió la persona.
- "list": values = opciones canónicas; synonyms = {canónico: [otras formas]}, p.ej. {"muzzarella": ["muzza", "mozza"]}.
  Se guarda siempre el valor canónico. Sin regex.
- Presets (regex exacta que pone la interfaz; si omitís regex, este servidor la completa):
    number: \\b\\d+(?:[.,]\\d+)?\\b
    email:  [\\w.+-]+@[\\w-]+\\.[\\w.-]+
    phone:  \\+?\\d[\\d\\s().-]{6,}\\d
    dni:    \\b\\d{1,2}\\.?\\d{3}\\.?\\d{3}\\b
- "date": SIN regex: entiende fechas y horas en lenguaje natural ("mañana a las 10", "el jueves que viene",
  "12/05") y guarda "AAAA-MM-DD" o "AAAA-MM-DDTHH:MM". No hace falta marcarla en las frases.
- "custom": regex propia (Python re, sin distinguir mayúsculas). Si tiene un grupo (...), se guarda el grupo 1.
- examples (opcional): frases extra con marcas, enseñadas desde el chat; entrenan el CRF igual que las de intents.
- color (opcional): color del resaltado en la interfaz: un índice de la paleta (0-5) o un hex "#rrggbb"
  (el texto se ajusta solo para que se lea).

## slots: [{name, entity, description?, fill?, start?}]
- La memoria de la conversación. name: minúsculas, números y _ (no empieza con número). Reservados: intent,
  confidence, text, entities, status, body, true, false, null, in.
- entity ("" = ninguna): si el mensaje trae esa entidad, el slot se llena solo (en cualquier turno, salvo cuando el bot
  espera la respuesta a otra pregunta: ahí solo se llena el slot preguntado).
- Al responder una pregunta (ask): si el slot tiene entidad con regex o lista y la respuesta no la trae, el bot dice
  "No reconocí ese dato, probemos de nuevo." y vuelve a preguntar. Si la entidad es "examples" o no tiene entidad,
  se guarda el texto completo de la respuesta.
- fill: "ai" + description ("Por qué devuelve el producto, en pocas palabras"): la IA (ai.enabled) saca el dato de la
  respuesta leyendo la descripción; si no lo encuentra, repregunta. Para datos sin formato fijo que una entidad no
  agarra bien. Sin IA prendida, no lo uses.
- start: true marca un dato inicial: llega en start data (IVR, CRM, widget) al empezar. En Parla, «Empezar con
  datos» muestra solo esos slots (si ninguno está marcado, muestra todos). No cambia el motor: start data puede
  precargar cualquier slot. Marcá los que manda el canal (DNI, número de cliente) y no los de trabajo interno.

## flows: [{name, trigger, steps, interrupts?}]
- trigger: nombre exacto de una intent, "__start__" (corre al empezar la conversación; uno solo por agente) o ""
  (solo se llega por goto o call). Si dos flujos tienen el mismo trigger, gana el primero.
- interrupts: false para los flujos de charla (saludar, agradecer, despedirse): nunca cortan una pregunta pendiente
  («ah, entonces sí» no puede terminar en una despedida) y la IA no los ofrece como «otra acción».
  "always" para lo que no puede esperar (urgencias): corta la pregunta aunque el mensaje traiga el dato pedido.
- Mientras una pregunta espera respuesta, el mensaje se toma como respuesta. Si la respuesta no sirve (no trae la
  entidad) y dispara otra intención, el bot atiende eso y después vuelve a la pregunta (interrupción). Los flujos del
  sistema (cancelar, repetir, pasar con una persona) funcionan siempre.
- Pasos (type y campos exactos que lee el motor):
  - {"type": "message", "text": "...", "translations": {"pt": "..."}, "buttons": [...]}   envía un mensaje (con plantillas)
  - {"type": "ask", "slot": "s", "text": "¿...?", "translations": {...}, "buttons": [...]}
       pregunta y espera; SE SALTEA si el slot ya tiene valor
     also (opcional): ["fecha", "cambio"] otras entidades que también cuentan como respuesta. Si la respuesta no trae la
     del slot pero sí una de esas («jueves» a «¿te sirve el lunes?»), el slot queda vacío y el flujo SIGUE: los pasos
     siguientes leen `entities` (if expr "has(entities.fecha)") y deciden. Para contrapropuestas a una oferta.
     Con IA prendida, mientras espera una respuesta: si la persona pregunta otra cosa («¿qué es presencial?») el bot
     contesta con la base de conocimiento (o dice que no sabe) y vuelve a preguntar, sin llenar el slot; y si contesta
     una opción de lista con otras palabras («dale nomás», «por videollamada») la IA elige la opción.
     translations (opcional): {idioma: texto} para cada idioma extra de "languages" (admite plantillas).
     buttons (opcional): [{"label": "Ventas", "value": "ventas", "translations": {"pt": "Vendas"}}] respuestas rápidas
     (value opcional = label). En un ask, tocar el botón guarda su value en el slot. En un message, el value se
     toma como lo que escribió la persona: poné como value una frase que dispare la intención ("estado de mi pedido").
     Usalos para opciones cerradas (2 a 6); escribir el label o el value a mano también vale.
  - {"type": "set", "slot": "s", "mode": "text", "text": "..."} guarda un texto (con plantillas)
    {"type": "set", "slot": "s", "mode": "clear"}               vacía el slot (null)
    {"type": "set", "slot": "s", "mode": "cel", "expr": "int(cantidad) * 9500"}  guarda el resultado de una fórmula CEL
  - {"type": "http", "method": "GET|POST|PUT|PATCH|DELETE", "url": "https://...{{ s }}",
     "headers": [{"key": "Authorization", "value": "Bearer {{ secret.API_TOKEN }}"}], "body": "{\\"dni\\": \\"{{ dni }}\\"}",
     "saves": [{"expr": "status", "slot": "codigo"}, {"expr": "body.name", "slot": "nombre"}]}
     url/headers/body admiten plantillas; con body se agrega Content-Type: application/json. Timeout 10 s.
     Cada save evalúa CEL sobre status (número, 0 = no conectó) y body (JSON parseado o texto) y lo guarda en el slot;
     si el dato no vino, el slot queda null. Un 4xx/5xx no corta el flujo: decidí con un if sobre el status.
  - {"type": "if", "cond": {"var": "slot", "op": "eq", "value": "200"}, "then": [pasos], "else": [pasos]}
     ops: eq, ne, contains (comparan como texto sin distinguir mayúsculas; true/false/números se comparan como texto
     JSON: "true", "200"), gt, lt (numéricos), empty, filled (sin value). cond.var tiene que ser un slot.
     O con fórmula: {"type": "if", "expr": "int(cantidad) > 3 && gusto == 'napolitana'", "then": [...], "else": [...]}
     (la expr tiene que dar true exacto). then/else se pueden anidar.
  - {"type": "goto", "flow": "Otro flujo"}   sigue en otro flujo (desde su primer paso)
  - {"type": "classify", "classification": "Cita agendada"}   marca la conversación con esa clasificación (tiene
     que existir en "classifications"). No dice nada; se puede marcar con varias, cada una cuenta una sola vez.
  - {"type": "function", "function": "calcular_total", "auto_save": true,
     "saves": [{"expr": "ok", "slot": "total_ok"}, {"expr": "result.total * 2", "slot": "doble"}]}
     ejecuta una función del agente (ver "Funciones"). Con auto_save (default true) las claves del objeto devuelto
     que se llaman igual que un slot se guardan solas. saves evalúa CEL sobre result (lo devuelto), ok (true/false)
     y error (texto o null).
  - {"type": "end"}                          termina el flujo acá (dentro de un subflujo, vuelve al que lo llamó)
  - {"type": "call", "flow": "Validar identidad"}   corre ese flujo como subflujo y AL TERMINAR VUELVE al paso
     siguiente (goto, en cambio, no vuelve). Para pasos reutilizables: identificarse, pedir datos de contacto.
  - {"type": "handoff", "reason": "reclamo", "text": "Te paso con una persona", "translations": {...}}
     pasa la charla a una persona (Bandeja de Parla): el bot se calla hasta que la devuelvan. text opcional (si no,
     usa system.handoff.text). reason lo ve quien atiende. Usalo para reclamos, enojo, casos que el bot no resuelve.
  - {"type": "agent", "instructions": "Ayudá a elegir un plan...", "functions": ["cotizar"], "knowledge": true,
     "slots": ["plan"], "goal": "cuando el plan esté elegido", "max_turns": 8}
     una "isla" de IA (necesita ai.enabled): conversa libremente, puede llamar a esas funciones, leer la base de
     conocimiento y completar esos slots; termina al cumplir goal o a los max_turns y sigue con el paso siguiente.
     Usalo poco: para asesorar o negociar, no para pedir datos (para eso: ask).
  - {"type": "file", "file": "Lista de precios.pdf", "text": "Acá tenés la lista, {{ nombre }}", "translations": {...}}
     manda un archivo que la persona subió a este agente (PDF, imagen, Word/Excel/PowerPoint, CSV, TXT o ZIP; hasta
     10 MB). file = id o nombre de list_files (el id no cambia si renombran). text opcional (plantillas; sin text, el
     mensaje es el nombre del archivo). En la API, el mensaje va en messages como siempre y replies[i].file trae
     {id, name, mime, size, url}; url es relativa al servidor de Parla y se abre sin sesión. Los archivos son del
     agente, no de una versión: borrarlo rompe el paso también en lo publicado. Para «pasame la lista de precios».
- Máximo 200 pasos seguidos por turno (corta loops de goto). Un paso que falla muestra "⚠ Hay un problema..." en el chat.

## classifications: [{name, color?, description?}]
- Etiquetas de resultado para reportes: qué pasó en la conversación ("Cita agendada", "Cancelación", "Derivada a
  operador"). color: entero 0-5 (interfaz); description: texto para humanos.
- Se aplican con el paso classify. La sesión guarda [{name, at}], el historial suma un evento
  "Clasificada como «X»", y las respuestas de events/sessions traen "classifications": [nombres].
- get_report cuenta conversaciones por clasificación (total y por día, con filtros de fecha/canal);
  list_sessions filtra por classification ("__none__" = sin clasificar).
- Poné un classify en el punto del flujo donde el objetivo se cumplió (después de confirmar, no antes).
- Ejemplo completo, un bot de turnos médicos que clasifica "Cita agendada" y "Cancelación":
```json
%s
```

## Funciones: functions: [{name, description, language, inputs, code}]
Código propio (Python o JavaScript) que un flujo ejecuta con el paso "function". Sirve para la lógica que ni CEL ni un
paso http resuelven: cuentas con tablas de precios, validar un CUIT/CBU con su dígito verificador, fechas ("¿qué día
cae el próximo martes hábil?"), normalizar textos, armar un resumen.
- name: identificador (único). description: para humanos. language: "python" (default) o "javascript" (necesita
  Node.js instalado en la máquina de Parla). inputs: nombres de slots que recibe (y "secret.NOMBRE" para una clave:
  llega en inputs["secret"]["NOMBRE"]). code: define run(inputs).
- Contrato: run(inputs) (sync o async) recibe {slot: valor} SOLO con los slots declarados en inputs (los valores de
  slots son texto o null: convertí con int()/float()) y devuelve un objeto JSON (dict / object). Cada clave que se
  llama igual que un slot se guarda en ese slot (auto_save). print/console.log van a "logs" y a la traza, no al chat.
  Una excepción (raise / throw) = la función falló, con su mensaje en error.
- Límites: proceso aparte, 5 s máximo, límites de CPU y memoria, carpeta temporal vacía, sin variables de entorno.
  Solo biblioteca estándar (Python) o módulos de Node (require). Corre en la máquina de Parla con sus permisos: no es un
  sandbox de seguridad. Un Parla con PARLA_FUNCTIONS=0 las tiene apagadas (cada ejecución falla con ese aviso).
- ¿Función o http? Para consultar o avisarle a un servicio (CRM, turnero, stock) usá el paso http: es declarativo, se
  ve en la interfaz y no hay código que mantener. Para un cálculo simple alcanza set mode cel. Usá una función cuando
  hay lógica de verdad (tablas, loops, validaciones, fechas) o cuando hay que transformar la respuesta de un http.
- Errores: si la función falla y ningún save mira ok ni error, el flujo se corta con "⚠ Hay un problema...". Para
  manejarlo vos, guardá ok/error y bifurcá: saves [{"expr": "ok", "slot": "total_ok"}, {"expr": "ok ? '' : error",
  "slot": "total_error"}] y después {"type": "if", "cond": {"var": "total_ok", "op": "eq", "value": "false"}, ...}.
- Probala SIEMPRE con test_function (camino feliz + un caso borde: dato vacío, texto en vez de número) antes de
  ponerla en un flujo; después probá el flujo con test_conversation.
- La misma función en JavaScript:
```javascript
const PRECIOS = { muzzarella: 9500, napolitana: 10500, fugazzeta: 11000 };
function run(inputs) {
  const cantidad = parseInt(inputs.cantidad, 10);
  if (!(cantidad >= 1)) throw new Error("la cantidad tiene que ser 1 o más");
  let total = PRECIOS[inputs.gusto] * cantidad;
  const promo = cantidad >= 3;
  if (promo) total = Math.round(total * 0.9);
  return { total, promo };
}
```
- Ejemplo completo en Python: la función calcular_total del fragmento de pizzería (al final de esta guía), con el paso
  function, el manejo de error y el mensaje que usa total y promo.

## Base de conocimiento: knowledge: [{id, title, source, url, text}]
- Documentos (preguntas frecuentes, políticas, horarios, precios). Cuando ninguna intención alcanza el umbral, el bot
  busca el fragmento más parecido; si el puntaje llega a knowledge_threshold, contesta con él (via "knowledge", con
  sources). Funciona sin IA (devuelve el fragmento); con ai.use_knowledge la IA redacta la respuesta solo con eso.
- source: "texto" | "url" | "pdf". Los pares "P: ¿...?\nR: ..." separados por una línea en blanco funcionan mejor.
- Usá add_knowledge (texto o url) y search_knowledge para probar. Regla: preguntas informativas (horarios, envíos,
  medios de pago) -> conocimiento; acciones con datos (sacar un turno, devolver) -> intent + flow.

## Flujos del sistema: system
Reparaciones de la charla que ya vienen hechas; editá textos/ejemplos o apagalas con enabled false. Todas aceptan
"translations": {idioma: texto}.
- cancel {enabled, examples, text}: "cancelar", "olvidalo" -> corta lo que estaba haciendo.
- repeat {enabled, examples}: "¿cómo?" -> repite lo último.
- clarify {enabled, margin, text "¿Quisiste decir…?"}: si dos intenciones quedan muy cerca pregunta cuál, con botones.
- correction {enabled, text}: "mejor de fugazza" mientras pregunta otra cosa -> corrige un dato ya dado.
- resume {enabled, text}: al volver de una interrupción, "Sigamos con lo de antes."
- handoff {enabled, examples, text}: "quiero hablar con una persona" -> pasa a la Bandeja.
- anything_else {enabled false, text}: al terminar un flujo pregunta "¿Te ayudo con algo más?".
- csat {enabled false, text}: al terminar un flujo pide una nota del 1 al 5 (botones); sale en get_analytics.
Dejá prendidas cancel, repeat, clarify, correction, resume y handoff (son lo que espera la gente). No hagas intents
propias para cancelar o pedir un humano: ya están.

## IA local: ai {enabled, provider, url, model, temperature, generative_fallback, rescue_intents, use_knowledge, persona}
- Modelos chicos locales (Ollama "qwen2.5:0.5b" por defecto, o un servidor compatible con OpenAI local). Apagada
  por defecto. rescue_intents: si la detección duda, la IA elige la intención; generative_fallback: repregunta
  natural cuando no entiende; use_knowledge: redacta respuestas de la base. persona: cómo habla el bot.
- La necesitan los pasos agent y los slots fill "ai". Sin IA, el resto del bot anda igual.

## Claves (credenciales): {{ secret.NOMBRE }}
- Tokens y API keys NO van en el JSON: se cargan en la sección «Claves» de Parla (la persona, no vos) y se usan como
  {{ secret.NOMBRE }} SOLO en url/headers/body de un paso http, y como entrada "secret.NOMBRE" de una función (le
  llega como inputs["secret"]["NOMBRE"]). Nunca en mensajes. Se tapan con •••• en trazas y logs.
- list_secret_names muestra qué nombres existen (nunca valores). create/update_agent avisan si falta cargar alguna.

## Widget web: widget {enabled, origins, title, color, greeting, position, voice}
- Chat para pegar en una web. origins: los sitios que lo pueden usar, ["https://mitienda.com"] (sin / al final).
  Con enabled true, las conversaciones del widget no piden clave. position "right" | "left"; voice: micrófono.

## Plantillas {{ }} y CEL
- En textos: {{ slot }} o {{ expresión CEL }}. Un slot vacío se muestra como "". Si la expresión usa algo que no
  existe, el paso falla.
- Variables disponibles: todos los slots + intent, confidence, text (mensaje actual), entities (mapa entidad->valor
  del mensaje actual). En saves de http, además status y body.
- Los valores de slots llenados por entidad o por respuesta son TEXTO: usá int(cantidad) / double(x) para cuentas.
- CEL útil: size(x), x.contains("a"), x.startsWith("a"), x.matches("^\\\\d+$"), cond ? a : b, has(body.campo), int(), string().

## Inicio de conversación y datos precargados
- La API pública arranca con POST /api/v1/bots/{bot}/events {"type": "start", "sessionId": "...", "data": {...}}.
  Cada clave de data que se llame igual que un slot se guarda en ese slot ANTES de correr el flujo "__start__"
  (las demás se ignoran y se informan en ignored_data). Así un IVR/CRM pasa el DNI y el ask se saltea.

## Entrenamiento
- El borrador usa su última versión ENTRENADA de intents y entities; flujos, slots, threshold y fallback se usan en vivo.
  create_agent/update_agent ya entrenan. Si cambiás frases o entidades por otra vía, llamá train_agent antes de probar.

## Borrador, versiones y entornos
- Editar (create_agent, update_agent, restore_version) cambia solo el BORRADOR. Los usuarios reales NO lo ven
  hasta que se publica y se despliega en producción.
- publish_agent congela el borrador como una versión numerada e inmutable (v1, v2…) con su propio modelo entrenado.
- Entornos: "production" (lo que usan las integraciones por defecto) y "staging" ("Pruebas", para que el cliente
  pruebe antes). Cada uno apunta a una versión; deploy_version cambia a cuál (queda registrado en list_versions).
  Si production todavía no tiene versión, responde con el borrador (como antes de que existieran las versiones).
- La API pública elige entorno con "environment": "production" (default) | "staging" | "draft" en el evento.
  Cada conversación queda atada a la versión con la que empezó: publicar o desplegar no cambia las que están en curso.
- Flujo recomendado:
  1. Editá el borrador (create_agent / update_agent).
  2. Probalo con test_conversation (environment="draft", el default).
  3. diff_agent(from_ref="production") para revisar qué cambia, y publish_agent(note=..., environment="staging").
  4. Probá staging con test_conversation(environment="staging") y mostrale el resultado al usuario.
  5. SOLO cuando el usuario lo aprueba: deploy_version(environment="production", version=N, confirm=True).
- Rollback: deploy_version(environment="production", version=<la anterior>, confirm=True). list_versions dice cuál
  estaba antes (deployments[].previous). Para descartar cambios del borrador: restore_version.

## Consejos de diseño
- 6-12 frases variadas por intent (balanceadas entre intents), rioplatenses, incluyendo las formas cortas ("saldo", "operador").
- Pedí los datos con ask: si el slot ya vino en el primer mensaje ("quiero 2 de muzza"), el ask se saltea solo.
- Vaciá con set mode clear al final del flujo los slots que hay que volver a preguntar la próxima vez.
- Si un dato tiene formato (número, email, DNI) o es una opción cerrada, dale una entidad con regex o list y asociala al
  slot: el ask va a volver a preguntar si la respuesta no sirve.
- Para nombres o texto libre, usá kind examples con varias frases marcadas, o un slot sin entidad (guarda el texto).
- Usá un flujo "__start__" para saludar o para usar datos precargados (ver ejemplo); un flujo con trigger "" sirve
  como subflujo reutilizable vía goto.
- Botones para opciones cerradas (menú inicial, sí/no, motivos); texto libre para datos abiertos.
- Preguntas frecuentes en la base de conocimiento (add_knowledge), no como una intent por pregunta.
- Reclamos, enojo o "esto no lo resuelve el bot" -> paso handoff con reason (y un classify antes, para contarlos).
- Dejá prendidos los flujos del sistema; sumá csat si al negocio le importa medir la atención.
- Subflujos con call para lo que se repite (identificarse); goto solo para seguir sin volver.
- Si el bot atiende en varios idiomas: languages + translations en cada message/ask/botón + fallback_translations.
- Credenciales siempre con {{ secret.NOMBRE }}, nunca escritas en el JSON.
- Validá con validate_agent y probá con test_conversation varias conversaciones realistas.
- Después de que lo use gente real: list_unrecognized -> teach_phrases (+ train_agent) o add_knowledge;
  get_analytics para ver contención, abandono por pregunta, fallbacks y CSAT.

## Ejemplo completo: Demo IVR (start flow con datos precargados, consulta HTTP y ramas)
```json
%s
```
Probalo: test_conversation(agent="Demo IVR", start_data={"dni": "3"}, messages=["cuánta plata tengo"]).
Sin start_data, el flujo de inicio pregunta el DNI.

## Fragmento: entidades list/number/examples, sinónimos, función con manejo de error, if expr, end, goto, classify
```json
%s
```

## Ejemplo completo: Soporte Tienda (idiomas, botones, conocimiento, system, call, handoff, agent, date, fill ai, secret, widget)
```json
%s
```
Probalo: test_conversation(agent="Soporte Tienda", messages=["¿hacen envíos?", "Mi pedido", "48213", "quiero hacer un reclamo"]).
Necesita que la persona cargue la clave CRM_TOKEN en Claves para que ande la validación de identidad.
""" % (json.dumps(TURNOS_SNIPPET, ensure_ascii=False, indent=2), json.dumps(DEMO_IVR, ensure_ascii=False, indent=2),
       json.dumps(PIZZA_SNIPPET, ensure_ascii=False, indent=2), json.dumps(SOPORTE_SNIPPET, ensure_ascii=False, indent=2))


# ---------- Servidor MCP ----------

mcp = MCPServer("parla", instructions=(
    "Parla es un armador de chatbots. get_report y list_sessions muestran cómo les va a los bots en producción. Para armar un bot: leé agent_format_guide, diseñá el JSON del agente, "
    "probá cada función con test_function, validate_agent, create_agent (valida, crea y entrena), y probalo con "
    "test_conversation. Para cambiarlo: "
    "get_agent, editá el JSON completo y update_agent (reemplaza todo y reentrena). Editar cambia solo el BORRADOR: "
    "los usuarios reales no lo ven hasta publicar. Flujo: probar el borrador → publish_agent a staging → probar staging → "
    "con el OK del usuario, deploy_version a production (confirm=True). Rollback = desplegar la versión anterior. "
    "Preguntas frecuentes: add_knowledge / search_knowledge. Para mejorar un bot en uso: list_unrecognized → "
    "teach_phrases → train_agent, y get_analytics. Credenciales: solo {{ secret.NOMBRE }}; list_secret_names ve los "
    "nombres, los valores los carga la persona en Claves (este servidor nunca los ve)."))


@mcp.tool()
def list_agents() -> dict:
    """List all Parla agents (bots): id, name, slug (for URLs), trained_at, intent names and environments
    ({"production": version|null, "staging": version|null})."""
    return call("GET", "/api/v1/bots")


@mcp.tool()
def get_agent(agent: str) -> dict:
    """Get the full JSON definition of an agent. `agent` = id (8 hex chars), exact name or slug.
    Use this before update_agent: edit the returned JSON and pass it back whole."""
    return call("GET", "/api/agents/" + resolve(agent))


@mcp.tool()
def agent_format_guide() -> str:
    """Return the complete guide to Parla's agent JSON format (intents, entities and kinds, slots, flows, every step
    type and its exact fields, templates/CEL, start data, training) with a full worked example. Read it before
    designing or editing an agent."""
    return GUIDE


@mcp.resource("parla://format-guide", name="agent_format_guide", mime_type="text/markdown",
              description="Guía completa del formato JSON de agentes de Parla, con ejemplo.")
def format_guide_resource() -> str:
    return GUIDE


@mcp.tool()
def validate_agent(agent_json: dict | str) -> dict:
    """Validate an agent definition locally (nothing is saved). Returns {ok, errors, warnings}. Errors mean the bot
    would break or behave differently than intended (unknown step types, unknown slots in steps/{{ }}/conditions,
    bad triggers, goto to missing flows, unknown entities in [x](entity) marks, bad regex, inconsistent entity kinds,
    duplicates; functions: unknown function in a step, bad language, inputs that aren't slots, no run(), Python syntax
    errors). Warnings are quality issues (few examples, intent without flow, unused function, input read in code but
    not declared, ...). Fix all errors before creating."""
    agent, errors, warnings = validate(as_dict(agent_json))
    return {"ok": not errors, "errors": errors, "warnings": warnings}


@mcp.tool()
def create_agent(agent_json: dict | str) -> dict:
    """Create a NEW agent from a full definition (see agent_format_guide): validates, imports and trains it.
    It only has a DRAFT: test it with test_conversation, then publish_agent / deploy_version to go live.
    Fails with the list of errors if it doesn't validate. Returns {id, name, slug, trained, warnings}.
    Preset entity kinds (number/email/phone/dni/date) get their regex filled in if omitted."""
    agent, warnings = validated(agent_json)
    created = call("POST", "/api/agents", {"import": agent})
    trained = call("POST", "/api/agents/%s/train" % created["id"], {})
    warnings += secret_warnings(created["id"], agent)
    info = call("GET", "/api/v1/bots/" + created["id"])
    return {"id": created["id"], "name": info["name"], "slug": info["slug"], "trained": trained, "warnings": warnings}


@mcp.tool()
def update_agent(agent: str, agent_json: dict | str) -> dict:
    """Replace an existing agent's WHOLE definition (same id; anything you omit is reset to defaults/empty), then
    retrain. `agent` = id, name or slug. Get the current JSON with get_agent, edit it, and pass it entire.
    Validates first; fails with the errors list if invalid. Returns {id, name, slug, trained, warnings}.
    This edits the DRAFT only: production/staging keep answering with their published version (real users and
    conversations in progress are NOT affected) until you publish_agent and deploy_version."""
    agent_id = resolve(agent)
    data, warnings = validated(agent_json, call("GET", "/api/agents/%s/files" % agent_id)["files"])
    call("PUT", "/api/agents/" + agent_id, data)
    trained = call("POST", "/api/agents/%s/train" % agent_id, {})
    warnings += secret_warnings(agent_id, data)
    info = call("GET", "/api/v1/bots/" + agent_id)
    return {"id": agent_id, "name": info["name"], "slug": info["slug"], "trained": trained, "warnings": warnings}


@mcp.tool()
def train_agent(agent: str) -> dict:
    """Retrain an agent's DRAFT so it uses its current intents and entities. create_agent/update_agent already do it.
    Published versions have their own frozen model and are not affected."""
    return call("POST", "/api/agents/%s/train" % resolve(agent), {})


@mcp.tool()
def test_conversation(agent: str, messages: list[str], start_data: dict | None = None, keep: bool = False,
                      environment: str = "draft") -> dict:
    """Simulate a conversation through the public API: starts a session (channel "mcp") with `start_data`
    (keys matching slot names preload those slots and the __start__ flow runs), then sends each message in order.
    Returns the transcript: per user turn what the bot understood (intent, confidence, entities, answer_to = the slot
    this message answered, or null if it was taken as a new intent), the bot replies, the flow/slot it waits for, and
    the final slots, plus the classifications applied so far (per turn and final). Replies starting with "⚠" are
    flow errors. Each turn also has language, handoff (true = a person took over: the bot stays silent) and, when
    present, buttons [{label, value}] (send a button's value or label as the next message to "press" it), via
    ("ia" | "knowledge" = who answered), sources (knowledge documents used) and files (names of files sent). The session is deleted afterwards
    unless keep=True. To start in another language pass start_data={"idioma": "pt"}.
    `environment`: "draft" (default: your unpublished edits, with the last TRAINED intents/entities), "staging" or
    "production" (what real users get: their published version). Returns the environment and version used
    (version null = draft)."""
    bot = resolve(agent)
    sid = "mcp-" + uuid.uuid4().hex[:12]
    events = "/api/v1/bots/%s/events" % bot
    transcript, problems, last = [], [], {}
    try:
        start = call("POST", events, {"type": "start", "sessionId": sid, "channel": "mcp", "data": start_data or {},
                                      "environment": environment})
        transcript.append({"event": "start", "data": start_data or {}, "bot": start["messages"], "trace": start["trace"],
                           "ignored_data": start["ignored_data"], "waiting_for": start["waiting_for"],
                           "classifications": start.get("classifications", []), **extras(start)})
        last = start
        for text in messages:
            last = call("POST", events, {"type": "message", "sessionId": sid, "channel": "mcp", "text": text})
            u = last["understood"]
            transcript.append({"user": text, "intent": u["intent"], "confidence": u["confidence"], "entities": u["entities"],
                               "answer_to": u["answer_to"], "bot": last["messages"], "flow": last["flow"],
                               "waiting_for": last["waiting_for"], "classifications": last.get("classifications", []),
                               **extras(last)})
        problems = [m for turn in transcript for m in turn["bot"] if m.startswith("⚠")]
    finally:
        if not keep:
            try:
                call("DELETE", "/api/v1/bots/%s/sessions/%s" % (bot, sid))
            except ToolError:
                pass
    return {"sessionId": sid if keep else None, "environment": last.get("environment"), "version": last.get("version"),
            "transcript": transcript, "final_slots": last.get("slots", {}),
            "waiting_for": last.get("waiting_for"), "classifications": last.get("classifications", []),
            "handoff": last.get("handoff"), "language": last.get("language"), "problems": problems}


def extras(turn):
    """Lo nuevo de cada turno, solo si aporta: botones, idioma, quién respondió (ia/knowledge) y fuentes."""
    out = {"language": turn.get("language"), "handoff": bool(turn.get("handoff"))}
    for key in ("buttons", "via", "sources"):
        if turn.get(key):
            out[key] = turn[key]
    sent = [r["file"]["name"] for r in turn.get("replies") or [] if r.get("file")]
    if sent:
        out["files"] = sent
    return out


@mcp.tool()
def test_function(agent: str, function: dict | str, inputs: dict | None = None) -> dict:
    """Run one of an agent's functions (custom Python/JavaScript code) on the Parla machine, without a conversation.
    `function` = a full definition {name, language, inputs, code} (to try it BEFORE saving it in the agent) or the
    name of a function already in the agent's DRAFT. `inputs` = {slot: value}; like in a flow, the function only
    receives the slots listed in its "inputs" (missing ones arrive as null; slot values are usually text, e.g. "2").
    Returns {ok, result | error, traceback?, logs (prints), ms, sent (the inputs it got), ignored_inputs}.
    Test the happy path and an edge case (empty / invalid value) before wiring it into a flow step."""
    agent_id = resolve(agent)
    if isinstance(function, str) and function.strip().startswith("{"):
        function = as_dict(function)
    if isinstance(function, str):
        found = [f for f in call("GET", "/api/agents/" + agent_id).get("functions") or [] if f.get("name") == function]
        if not found:
            raise ToolError("el borrador de «%s» no tiene una función «%s»: pasá la definición completa o creala primero"
                            % (agent, function))
        function = found[0]
    if not isinstance(function, dict) or not isinstance(inputs or {}, dict):
        raise ToolError("«function» tiene que ser una definición {name, language, inputs, code} o un nombre, e «inputs» un objeto")
    declared = function.get("inputs") or []
    sent = {name: (inputs or {}).get(name) for name in declared}
    result = call("POST", "/api/agents/%s/functions/test" % agent_id, {"function": function, "inputs": sent})
    return dict(result, sent=sent, ignored_inputs=sorted(set(inputs or {}) - set(declared)))


@mcp.tool()
def delete_agent(agent: str, confirm: bool = False) -> dict:
    """PERMANENTLY delete an agent with its model and all its conversations. Irreversible: pass confirm=True only
    when the user explicitly asked to delete this agent."""
    agent_id = resolve(agent)
    if confirm is not True:
        raise ToolError("Borrar «%s» es irreversible: volvé a llamar con confirm=True si el usuario lo pidió." % agent)
    call("DELETE", "/api/agents/" + agent_id)
    return {"deleted": agent_id}


ENVIRONMENTS = ("production", "staging")


def environment_of(environment):
    if environment not in ENVIRONMENTS:
        raise ToolError("«environment» tiene que ser production o staging (vino %r)" % (environment,))
    return environment


def needs_confirm(agent, environment, confirm):
    if environment == "production" and confirm is not True:
        raise ToolError("Esto cambia lo que contesta «%s» a los usuarios reales (production). Hacelo solo si el usuario "
                        "lo aprobó: volvé a llamar con confirm=True." % agent)


@mcp.tool()
def publish_agent(agent: str, note: str, environment: str | None = None, confirm: bool = False) -> dict:
    """Publish the current DRAFT as a new immutable numbered version (v1, v2…) with its own trained model.
    `note` = what changed, for humans. `environment` = None (just create the version), "staging" (recommended: for
    the user/client to test) or "production" (goes live right away: requires confirm=True, only with the user's OK).
    Returns {version, created, note, stats, environments}."""
    if environment is not None:
        needs_confirm(agent, environment_of(environment), confirm)
    return call("POST", "/api/agents/%s/versions" % resolve(agent), {"note": note, "environment": environment})


@mcp.tool()
def deploy_version(agent: str, environment: str, version: int | None, confirm: bool = False) -> dict:
    """Point an environment ("production" or "staging") to a published version (version=None empties it; an empty
    production answers with the draft). Deploying to production changes what real users get: pass confirm=True
    only when the user approved it. Rollback = deploy the previous version. New conversations use the new version;
    conversations in progress keep the one they started with. Returns {environment, version, previous}."""
    needs_confirm(agent, environment_of(environment), confirm)
    return call("POST", "/api/agents/%s/deploy" % resolve(agent), {"environment": environment, "version": version})


@mcp.tool()
def list_versions(agent: str) -> dict:
    """List an agent's published versions (newest first: version, created, note, stats, environments it is in),
    which version each environment has ({"production": n|null, "staging": n|null}) and the deployment log
    (newest first: {environment, version, previous, at}; `previous` is what to deploy to roll back)."""
    return call("GET", "/api/agents/%s/versions" % resolve(agent))


@mcp.tool()
def diff_agent(agent: str, from_ref: str = "production", to_ref: str = "draft") -> dict:
    """What changes between two definitions, by name: intents (added/removed phrases), entities, slots, flows,
    classifications and settings (name/threshold/fallback). Refs: "production", "staging", "draft" or a version
    number. Default = what publishing the draft would change in production. Returns {changes (total), settings,
    intents: {added, removed, changed}, …, from, to (version numbers, null = draft/empty)}."""
    query = query_string(**{"from": str(from_ref), "to": str(to_ref)})
    return call("GET", "/api/agents/%s/diff%s" % (resolve(agent), query))


@mcp.tool()
def restore_version(agent: str, version: int, confirm: bool = False) -> dict:
    """Replace the DRAFT with a published version's definition (discards unpublished edits; environments and
    versions are untouched) and retrain the draft. Pass confirm=True only if the user agreed to lose the draft's
    unpublished changes (check them first with diff_agent(from_ref=str(version), to_ref="draft"))."""
    agent_id = resolve(agent)
    if confirm is not True:
        raise ToolError("Esto pisa el borrador de «%s» con la v%s y se pierden los cambios sin publicar: volvé a llamar "
                        "con confirm=True si el usuario lo pidió." % (agent, version))
    restored = call("POST", "/api/agents/%s/versions/%d/restore" % (agent_id, int(version)), {})
    return {"id": agent_id, "restored": int(version), "name": restored["name"],
            "trained": call("POST", "/api/agents/%s/train" % agent_id, {})}


def query_string(**params):
    params = {k: v for k, v in params.items() if v}
    return "?" + urllib.parse.urlencode(params) if params else ""


@mcp.tool()
def list_sessions(agent: str, channel: str | None = None, classification: str | None = None,
                  date_from: str | None = None, date_to: str | None = None) -> dict:
    """List an agent's conversations (newest first): sessionId, channel, dates, ended, message count, first/last
    message, preloaded data, classifications. Optional filters: `channel` (e.g. "api", "prueba" = the UI test chat,
    "mcp"), `classification` (a classification name, or "__none__" for unclassified), `date_from`/`date_to`
    (YYYY-MM-DD, inclusive, by the day the conversation started)."""
    query = query_string(channel=channel, classification=classification, **{"from": date_from, "to": date_to})
    return call("GET", "/api/v1/bots/%s/sessions%s" % (resolve(agent), query))


@mcp.tool()
def get_report(agent: str, date_from: str | None = None, date_to: str | None = None, channel: str | None = None) -> dict:
    """Classification report: how many conversations got each classification, total and per day.
    Returns {sessions, unclassified, classifications: [{name, count, configured}], by_day: [{date, sessions,
    unclassified, counts: {name: n}}]}. configured=false means the name was applied but no longer exists in the agent.
    Optional filters: `date_from`/`date_to` (YYYY-MM-DD, by start day) and `channel`."""
    query = query_string(channel=channel, **{"from": date_from, "to": date_to})
    return call("GET", "/api/v1/bots/%s/report%s" % (resolve(agent), query))


@mcp.tool()
def get_session(agent: str, session_id: str) -> dict:
    """Get one conversation with its full history (user messages with intent/confidence/entities/answer_to, bot
    replies, start events with data), current slots, flow and the slot it is waiting for."""
    return call("GET", "/api/v1/bots/%s/sessions/%s" % (resolve(agent), urllib.parse.quote(session_id, safe="")))


# ---------- Conocimiento, para enseñar, métricas y claves ----------

@mcp.tool()
def add_knowledge(agent: str, title: str = "", text: str | None = None, url: str | None = None) -> dict:
    """Add a document to the agent's knowledge base (FAQs, policies, hours, prices): pass `text` (plain text; FAQ
    pairs as "P: ¿...?\\nR: ..." work best) OR `url` (Parla downloads the page and extracts its text). A document
    with the same title is replaced. When no intent matches, the bot answers from these documents if a fragment
    scores >= knowledge_threshold (0.75 default), with or without AI. Edits the DRAFT; no retraining needed.
    Check it with search_knowledge. Returns {id, title, source, chars, preview, documents}."""
    if bool(text and text.strip()) == bool(url and url.strip()):
        raise ToolError("pasá «text» o «url» (uno de los dos)")
    agent_id = resolve(agent)
    if url:
        url = url.strip() if re.match(r"(?i)https?://", url.strip()) else "https://" + url.strip()
        got = call("POST", "/api/agents/%s/knowledge/extract" % agent_id, {"kind": "url", "url": url})
    else:
        got = call("POST", "/api/agents/%s/knowledge/extract" % agent_id, {"kind": "text", "data": text})
    data = call("GET", "/api/agents/" + agent_id)
    docs = [d for d in data.get("knowledge") or [] if isinstance(d, dict)]
    title = (title or got.get("title") or "Documento").strip()[:120]
    old = next((d for d in docs if d.get("title") == title), None)
    doc = {"id": (old or {}).get("id") or "k" + uuid.uuid4().hex[:6], "title": title,
           "source": "url" if url else "texto", "url": url or "", "text": got["text"]}
    data["knowledge"] = [doc if d is old else d for d in docs] + ([] if old else [doc])
    call("PUT", "/api/agents/" + agent_id, data)
    return {"id": doc["id"], "title": title, "source": doc["source"], "replaced": bool(old), "chars": len(doc["text"]),
            "preview": doc["text"][:300], "documents": len(data["knowledge"])}


@mcp.tool()
def search_knowledge(agent: str, query: str, k: int = 3) -> dict:
    """Search the agent's knowledge base (DRAFT) like the bot does when no intent matches. Returns
    {results: [{text, title, doc, score}], threshold, answers}: answers=true if the best score reaches
    knowledge_threshold (the bot would answer with that fragment). Use it to check FAQs before testing."""
    agent_id = resolve(agent)
    results = call("POST", "/api/agents/%s/knowledge/search" % agent_id, {"query": query, "k": k}).get("results") or []
    threshold = float(call("GET", "/api/agents/" + agent_id).get("knowledge_threshold", 0.75))
    return {"results": results, "threshold": threshold, "answers": bool(results) and results[0]["score"] >= threshold}


@mcp.tool()
def list_unrecognized(agent: str, date_from: str | None = None, date_to: str | None = None) -> dict:
    """What real users wrote that the bot did NOT understand (fallbacks), grouped by similar meaning, most frequent
    first: {groups: [{label, count, texts, examples: [{text, sessionId, at}], suggested_intent}]}. Use it to
    improve the bot: add the good phrases to an intent with teach_phrases, answer FAQs with add_knowledge, or
    create a new intent+flow with update_agent. Optional `date_from`/`date_to` (YYYY-MM-DD)."""
    query = query_string(**{"from": date_from, "to": date_to})
    return call("GET", "/api/agents/%s/insights/unrecognized%s" % (resolve(agent), query))


@mcp.tool()
def teach_phrases(agent: str, intent: str, phrases: list[str]) -> dict:
    """Add example phrases to an EXISTING intent of the DRAFT (e.g. from list_unrecognized). Phrases already there
    are skipped; [value](entity) marks must use existing entities. Does NOT retrain: call train_agent afterwards,
    then check with test_conversation. Returns {intent, added, skipped, total}."""
    agent_id = resolve(agent)
    data = call("GET", "/api/agents/" + agent_id)
    target = next((i for i in data.get("intents") or [] if i.get("name") == intent), None)
    if not target:
        raise ToolError("no existe la intent «%s» (hay: %s). Para una nueva usá get_agent + update_agent"
                        % (intent, ", ".join(i["name"] for i in data.get("intents") or []) or "ninguna"))
    entities = {e.get("name") for e in data.get("entities") or []}
    known = {p.strip().lower() for p in target.get("examples") or []}
    added, skipped = [], []
    for phrase in phrases:
        phrase = str(phrase or "").strip()
        bad = [name for _, name in ANNOT.findall(phrase) if name not in entities]
        if bad:
            raise ToolError("la frase «%s» marca la entidad «%s», que no existe" % (phrase, bad[0]))
        if not phrase or phrase.lower() in known:
            skipped.append(phrase)
            continue
        known.add(phrase.lower())
        added.append(phrase)
    target["examples"] = list(target.get("examples") or []) + added
    if added:
        call("PUT", "/api/agents/" + agent_id, data)
    return {"intent": intent, "added": added, "skipped": skipped, "total": len(target["examples"]),
            "next": "Llamá train_agent para que el bot las aprenda y probá con test_conversation (es el borrador: "
                    "publicá para que llegue a producción)." if added else "No había frases nuevas."}


@mcp.tool()
def get_analytics(agent: str, date_from: str | None = None, date_to: str | None = None) -> dict:
    """How the bot is doing with real conversations: sessions, contained (solved without a person) vs handoff and
    their rates, user_messages, fallbacks and fallback_rate, csat {average, answered, distribution}, abandoned
    and drop_off [{flow, question, count}] (where people leave), per-flow started/dropped and by_day.
    Optional `date_from`/`date_to` (YYYY-MM-DD, by start day)."""
    query = query_string(**{"from": date_from, "to": date_to})
    return call("GET", "/api/agents/%s/insights/analytics%s" % (resolve(agent), query))


@mcp.tool()
def list_files(agent: str) -> dict:
    """Files the person uploaded to this agent (price lists, catalogs, photos) that a {"type": "file"} step can send.
    Returns {files: [{id, name, mime, size}]}; reference one in a step by id (stable) or by name. This server can't
    upload: if the file is missing, ask the person to upload it in Parla (step «Enviar un archivo» in Flujos)."""
    return {"files": [{k: f[k] for k in ("id", "name", "mime", "size")}
                      for f in call("GET", "/api/agents/%s/files" % resolve(agent))["files"]]}


@mcp.tool()
def list_secret_names(agent: str) -> dict:
    """NAMES of the credentials (API keys, tokens) stored for this agent — never their values. Use them as
    {{ secret.NAME }} in http url/headers/body or as function input "secret.NAME". This server cannot read or set
    values: if one is missing, ask the person to add it in Parla's «Claves» section. Returns {secrets, used, missing}."""
    agent_id = resolve(agent)
    names = call("GET", "/api/agents/%s/secrets" % agent_id).get("secrets") or []
    used = secret_refs(call("GET", "/api/agents/" + agent_id))
    return {"secrets": names, "used": sorted(used), "missing": sorted(used - set(names)),
            "note": "Los valores los carga la persona en la sección Claves de Parla; el MCP nunca los ve."}


@mcp.prompt()
def build_bot(description: str) -> str:
    """Armar un bot completo de Parla a partir de una descripción."""
    return """Armá un bot de Parla que haga esto: %s

Construí el bot ENTERO (intents, entidades, slots, funciones, flujos, clasificaciones) con las herramientas de Parla:
1. Leé agent_format_guide completo (formato exacto, tipos de paso, entidades, funciones, consejos).
2. Intents con frases balanceadas y variadas:
   - 6 a 12 frases por intent y cantidades parecidas entre intents (una con 12 y otra con 4 sesga la detección).
   - Español rioplatense natural (voseo: "quiero", "pasame", "che, ¿cuánto sale?"), con estructuras y largos distintos:
     formas cortas ("saldo", "un turno"), preguntas, pedidos indirectos ("quería ver si..."), con y sin datos.
   - Marcá las entidades con [valor](entidad) repartidas entre varias frases, con valores distintos y en distintas
     posiciones; dejá también frases sin marcas. Evitá frases casi iguales entre intents distintas.
3. Entidades según el dato: list + synonyms para opciones cerradas (gustos, especialidades, sucursales); presets
   number/email/phone/dni para formatos conocidos; date (sin regex) para fechas y horas en lenguaje natural; custom
   con regex para otros formatos; examples (aprendida) para nombres o texto libre, con al menos 3 frases marcadas en
   contextos distintos. Asociá cada slot a su entidad. Si hay IA prendida y el dato es abierto, slot con
   fill "ai" + description.
4. Funciones para la lógica que un paso http o una fórmula CEL no resuelven (tablas de precios, dígitos
   verificadores, fechas, transformar respuestas). Para cada una: escribí run(inputs) devolviendo claves que se
   llamen igual que los slots, y probala con test_function ANTES de usarla en un flujo: camino feliz + un caso borde
   (dato vacío o inválido). Corregí hasta que ok/result sean los esperados. En el paso function guardá ok/error y
   bifurcá con un if para que un error no corte la conversación con "⚠".
5. Flows: ask para cada dato, http para consultar servicios, function para la lógica, if para las ramas, set clear al
   final para lo que se vuelve a pedir, y un flujo __start__ si conviene saludar o usar datos precargados. Poné un
   fallback (3-4 variantes) y threshold razonables. Prácticas equilibradas:
   - buttons en message/ask para opciones cerradas (menú inicial con value = una frase que dispare la intent;
     sí/no; motivos), texto libre para lo abierto. No más de 6 botones.
   - Preguntas informativas (horarios, envíos, pagos, políticas) en la base de conocimiento con add_knowledge
     después de crear el agente (o en "knowledge"), no una intent por pregunta. Probalas con search_knowledge.
   - Reclamos, enojo o lo que el bot no resuelve: paso handoff con reason (y classify antes para contarlos).
   - Dejá prendidos los flujos del sistema (cancel, repeat, clarify, correction, resume, handoff): no hagas intents
     propias para cancelar o pedir un humano. csat si interesa medir la atención.
   - call para subflujos reutilizables (identificarse) que vuelven; goto solo para seguir sin volver.
   - Paso agent (IA con funciones) solo si hay IA prendida y la tarea es abierta (asesorar); para datos, ask.
   - Varios idiomas: languages + translations en cada message/ask/botón/handoff + fallback_translations + 1-2
     frases por idioma en cada intent.
   - Credenciales: NUNCA en el JSON. Usá {{ secret.NOMBRE }} en http (o entrada "secret.NOMBRE" de una función);
     list_secret_names muestra qué hay; si falta, pedile a la persona que la cargue en la sección Claves. Definí classifications con los resultados que al negocio le
   importa contar y marcá cada uno con un paso classify donde se cumple (p. ej. turnos médicos: "Cita agendada" al
   confirmar, "Cancelación" al cancelar, "Derivada a operador" al pasar con una persona).
6. validate_agent y corregí todos los errores (y las advertencias que importen).
7. create_agent (valida, crea y entrena). Si el usuario quería cambiar uno existente: get_agent + update_agent.
   Las dos cambian solo el BORRADOR: los usuarios reales no ven nada hasta que se publica.
8. Revisá el entrenamiento: create/update_agent devuelven trained.log (también en get_agent → trained.log).
   trained.log.self_check.mistakes lista frases que el bot mandaría a otra intent: reescribí o mové esas frases,
   o sumá frases que marquen la diferencia; mirá también trained.log.warnings. Repetí hasta que no queden confusiones
   importantes.
9. Probá el borrador con test_conversation (environment="draft", el default) en 3-4 conversaciones realistas: el
   camino feliz, un dato inválido, todo dado en el primer mensaje, tocar un botón (mandá su value), una pregunta
   frecuente (via "knowledge"), un reclamo (handoff true), una función que falla (si hay) y algo fuera de tema
   (fallback). Si tiene varios idiomas, una charla con start_data={"idioma": "pt"}. Revisá intent/confidence,
   entities, answer_to, slots, buttons, via, handoff, classifications y mensajes "⚠".
10. Si algo falla (intención mal detectada, slot vacío, flujo cortado), corregí con update_agent y volvé a probar.
11. Revisá con diff_agent qué cambia respecto de producción y publicá a Pruebas:
    publish_agent(note="qué cambió", environment="staging"). Probá staging con test_conversation(environment="staging").
12. Reportá: qué hace el bot, sus intents/flujos/funciones, cómo se ven las conversaciones de prueba, la versión en
    staging y su id/slug para usarlo por la API (/api/v1/bots/<slug>/events). Preguntá si lo pasás a producción.
13. SOLO si el usuario lo aprueba: deploy_version(environment="production", version=N, confirm=True). Si después algo
    anda mal, rollback: deploy_version a production con la versión anterior (list_versions la muestra).
14. Con el bot en uso: list_unrecognized para ver lo que no entendió → teach_phrases a la intent correcta (y
    train_agent) o add_knowledge si era una pregunta frecuente; get_analytics para contención, abandono y CSAT.""" % description


def main():
    parser = argparse.ArgumentParser(description="Servidor MCP de Parla")
    parser.add_argument("--http", action="store_true", help="streamable HTTP en /mcp en vez de stdio")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8001)
    args = parser.parse_args()
    if not args.http:
        mcp.run()
        return
    extra = [h.strip() for h in os.environ.get("PARLA_MCP_ALLOWED_HOSTS", "").split(",") if h.strip()]
    security = None
    if extra:
        from mcp.server.transport_security import TransportSecuritySettings
        hosts = extra + ["127.0.0.1:*", "localhost:*"]
        security = TransportSecuritySettings(allowed_hosts=hosts, allowed_origins=["https://" + h for h in extra] +
                                             ["http://127.0.0.1:*", "http://localhost:*"])
    mcp.run("streamable-http", host=args.host, port=args.port, transport_security=security)


if __name__ == "__main__":
    main()
