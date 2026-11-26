#!/usr/bin/env python3
"""Importa un proyecto de Rasa 3.x (YAML) a un agente de Parla.

    .venv/bin/python -m parla.rasa_import <carpeta_del_proyecto> [-o agente.json]

convert({ruta relativa: texto}) -> (agente, avisos). Función pura: sirve igual desde un zip, una carpeta o la API.
Lee nlu.yml (intents, sinónimos, regex, lookups), domain.yml o domain/ (intents, entities, slots, responses, forms,
actions), rules.yml y stories.yml (clásico), flows de CALM y config.yml (language). Lo que no se puede traducir
queda en los avisos: nunca se descarta en silencio.
"""
import json
import re

import yaml

ANNOT = re.compile(r"\[([^\]]+)\](?:\(([^)]+)\)|\{([^}]*)\})")    # [texto](entidad) · [texto](entidad:valor) · [texto]{"entity": ...}
SLOT_REF = re.compile(r"(?<!\{)\{(\w+)\}(?!\})")                  # «Hola {name}» de Rasa -> «Hola {{ name }}»
RESERVED = {"intent", "confidence", "text", "entities", "status", "body", "true", "false", "null", "in"}   # mcp_server.RESERVED
PRESET_NAMES = {"email": "email", "number": "number", "phone": "phone", "phone_number": "phone", "date": "date", "time": "date"}
PRESET_REGEX = {"number": r"\b\d+(?:[.,]\d+)?\b", "email": r"[\w.+-]+@[\w-]+\.[\w.-]+", "phone": r"\+?\d[\d\s().-]{6,}\d"}
SILENT_ACTIONS = {"action_listen", "action_deactivate_loop", "action_unlikely_intent"}
TOP_KEYS = {"version", "nlu", "rules", "stories", "flows", "intents", "entities", "slots", "responses", "forms", "actions",
            "language", "pipeline", "policies", "recipe", "assistant_id", "session_config", "config", "e2e_actions"}
WEBHOOK = "http://localhost:5055/webhook"        # el servidor de acciones de Rasa (rasa run actions)
FALLBACKS = {"en": "Sorry, I didn't get that. Could you rephrase?", "pt": "Não entendi, pode dizer de outro jeito?"}
SYSTEM_EN = {"cancel": {"examples": ["cancel", "stop", "forget it", "never mind"], "text": "Ok, let's stop here. Anything else I can help with?"},
             "repeat": {"examples": ["repeat", "what?", "say that again"]},
             "clarify": {"text": "Did you mean…?"}, "anything_else": {"text": "Anything else I can help with?"},
             "resume": {"text": "Let's continue where we were."}, "correction": {"text": "Done, I changed it."},
             "handoff": {"examples": ["I want to talk to a human", "connect me to an agent"], "text": "I'm passing you to a person, they'll write to you shortly."},
             "csat": {"text": "How did I do? From 1 to 5."}}
YES_NO = {"true": ["yes", "yeah", "yep", "sure", "sí", "si", "dale", "claro", "sim"], "false": ["no", "nope", "não", "nao"]}


def examples_of(item):
    """Rasa guarda los ejemplos como un bloque «- frase» por línea (o, a veces, como lista)."""
    raw = item.get("examples") or []
    if isinstance(raw, str):
        return [line.strip()[2:].strip() for line in raw.splitlines() if line.strip().startswith("- ")]
    return [str(x.get("text") if isinstance(x, dict) else x).strip() for x in raw if x]


def merge(parts):
    """Junta todos los YAML: las listas se suman y los diccionarios se combinan (domain/ partido en varios archivos)."""
    out = {}
    for data in parts:
        for key, value in data.items():
            if isinstance(value, list):
                out.setdefault(key, []).extend(value)
            elif isinstance(value, dict) and isinstance(out.get(key), dict):
                out[key].update(value)
            else:
                out.setdefault(key, value)
    return out


def convert(files, name=None):
    warnings = []
    warn = warnings.append
    parts = []
    for p, text in sorted(files.items()):
        low = p.replace("\\", "/").lower()
        if not low.endswith((".yml", ".yaml")):
            continue
        if low.split("/")[-1] in ("endpoints.yml", "credentials.yml", "endpoints.yaml", "credentials.yaml"):
            warn("%s: no se importa (conexiones y canales de Rasa; en Parla se configuran desde Publicar)" % p)
            continue
        if {"tests", "e2e_tests"} & set(low.split("/")[:-1]):
            warn("%s: es una prueba de Rasa, no se importa" % p)
            continue
        try:
            data = yaml.safe_load(text)
        except yaml.YAMLError as error:
            warn("%s: no es un YAML válido (%s), lo salteo" % (p, str(error).splitlines()[0]))
            continue
        if isinstance(data, dict):
            for key in sorted(set(data) - TOP_KEYS):
                warn("%s: la sección «%s» no la conozco, la salteo" % (p, key))
            parts.append({k: v for k, v in data.items() if k in TOP_KEYS})
    d = merge(parts)
    if d.get("pipeline") or d.get("policies"):
        warn("config.yml: el pipeline y las policies de Rasa no se usan; Parla tiene su propio NLU (embeddings + CRF) y sus flujos")
    if isinstance(d.get("session_config"), dict):
        warn("domain: «session_config» no se importa (Parla guarda cada conversación por sessionId)")

    # ---------- idioma ----------
    lang = str(d.get("language") or "").lower().split("_")[0].split("-")[0]
    if lang and not re.fullmatch(r"[a-z]{2}", lang):
        warn("config.yml: no entiendo el idioma «%s», quedó en español" % d.get("language"))
        lang = ""
    lang = lang or "es"
    agent = {"name": str(name or "").strip()[:80] or "Bot importado de Rasa", "threshold": 0.75, "languages": [lang],
             "fallback": FALLBACKS.get(lang, "No entendí, ¿me lo decís de otra forma?"),
             "intents": [], "entities": [], "slots": [], "flows": [], "classifications": [], "functions": []}
    if lang == "en":
        agent["system"] = json.loads(json.dumps(SYSTEM_EN))
    elif lang not in ("es",):
        warn("idioma «%s»: los textos de los flujos del sistema (cancelar, repetir, pasar con una persona) quedan en español; "
             "traducilos en Flujos del sistema" % lang)

    # ---------- NLU ----------
    intents = {}             # nombre -> [frases]
    entity_names = []        # en orden de aparición
    synonyms = {}            # entidad -> {valor: [formas]}
    regexes, lookups, nlu_synonyms = {}, {}, {}
    groups_seen, roles_seen = [], []

    def entity(n):
        if n not in entity_names:
            entity_names.append(n)
        return n

    def annotate(phrase, where):
        def one(m):
            text, simple, meta = m.group(1), m.group(2), m.group(3)
            if simple is not None:
                ent, _, value = simple.partition(":")
                role = None
            else:
                try:
                    info = json.loads("{%s}" % meta)
                except ValueError:
                    warn("%s: no entiendo la marca «%s», queda como texto" % (where, m.group(0)))
                    return text
                ent, value, role = str(info.get("entity") or ""), str(info.get("value") or ""), info.get("role")
                if info.get("group") is not None:
                    groups_seen.append(ent)
            ent = ent.strip()
            if not ent:
                return text
            if role:
                ent = "%s_%s" % (ent, role)
                roles_seen.append(ent)
            entity(ent)
            if value and value != text:
                forms = synonyms.setdefault(ent, {}).setdefault(value, [])
                if text not in forms:
                    forms.append(text)
            return "[%s](%s)" % (text, ent)
        return ANNOT.sub(one, phrase)

    for item in d.get("nlu") or []:
        if not isinstance(item, dict):
            continue
        if "intent" in item:
            n = str(item["intent"])
            bucket = intents.setdefault(n, [])
            for ex in examples_of(item):
                ex = annotate(ex, "intent «%s»" % n)
                if ex and ex not in bucket:
                    bucket.append(ex)
        elif "synonym" in item:
            nlu_synonyms.setdefault(str(item["synonym"]), []).extend(examples_of(item))
        elif "regex" in item:
            regexes.setdefault(str(item["regex"]), []).extend(examples_of(item))
        elif "lookup" in item:
            lookups.setdefault(str(item["lookup"]), []).extend(examples_of(item))
        else:
            warn("nlu: no entiendo el bloque %s, lo salteo" % json.dumps(item, ensure_ascii=False)[:80])
    if groups_seen:
        warn("nlu: Parla no tiene grupos de entidades; se ignoraron los «group» de %s" % ", ".join(sorted(set(groups_seen))))
    for item in d.get("intents") or []:
        n = str(next(iter(item)) if isinstance(item, dict) else item)
        intents.setdefault(n, [])
    for item in d.get("entities") or []:
        n = str(next(iter(item)) if isinstance(item, dict) else item)
        roles = (item[n].get("roles") or []) if isinstance(item, dict) and isinstance(item[n], dict) else []
        for role in roles:
            roles_seen.append(entity("%s_%s" % (n, role)))
        if not roles:
            entity(n)          # con roles, la entidad sola no se usa: cada rol es la suya
    if roles_seen:
        warn("entidades con «role»: Parla no tiene roles, cada rol quedó como una entidad aparte (ciudad + role origen -> «ciudad_origen»)")

    # sinónimos de nlu.yml: van a la entidad que usa ese valor (o la que lo tiene en su lookup)
    for value, forms in nlu_synonyms.items():
        owners = [e for e in entity_names if value in synonyms.get(e, {}) or value in lookups.get(e, [])]
        if not owners:
            warn("sinónimo «%s»: ninguna entidad usa ese valor ([texto]{\"entity\": \"x\", \"value\": \"%s\"}), lo salteo" % (value, value))
        for e in owners:
            known = synonyms.setdefault(e, {}).setdefault(value, [])
            known += [f for f in forms if f not in known]

    entities = []
    for n in entity_names:
        e = {"name": n, "kind": "examples", "values": [], "regex": "", "color": len(entities) % 6}
        if n in lookups:
            e.update(kind="list", values=list(dict.fromkeys(lookups[n] + list(synonyms.get(n, {})))))
        elif n in regexes:
            pattern = "|".join("(?:%s)" % r for r in regexes[n]) if len(regexes[n]) > 1 else regexes[n][0]
            try:
                re.compile(pattern)
                e.update(kind="custom", regex=pattern)
            except re.error as error:
                warn("regex «%s»: no es válida en Python (%s), la entidad queda aprendida por ejemplos" % (n, error))
        elif n in PRESET_NAMES and not any("](%s)" % n in ex for exs in intents.values() for ex in exs):
            kind = PRESET_NAMES[n]
            e.update(kind=kind, regex=PRESET_REGEX.get(kind, ""))
            warn("entidad «%s»: no está marcada en ninguna frase (en Rasa seguro venía de Duckling o spaCy); quedó como tipo «%s»" % (n, kind))
        if synonyms.get(n):
            e["synonyms"] = synonyms[n]
            if e["kind"] == "examples":
                warn("entidad «%s»: tiene sinónimos pero se aprende por ejemplos; Parla guarda el valor como lo escribió la persona. "
                     "Si las opciones son fijas, pasala a «De una lista de opciones»" % n)
        entities.append(e)
    for n in sorted(set(regexes) - set(entity_names)):
        warn("regex «%s»: en Rasa es una pista para el clasificador; Parla no la necesita, la salteo "
             "(si es un dato, creá una entidad «Un formato propio» con esa regex)" % n)
    for n in sorted(set(lookups) - set(entity_names)):
        warn("lookup «%s»: no hay una entidad con ese nombre, la salteo" % n)
    by_entity = {e["name"]: e for e in entities}

    # ---------- slots ----------
    slot_map, slot_types, slots = {}, {}, []
    free_llm, no_mapping = [], []

    def ident(n):
        s = re.sub(r"[^a-z0-9_]", "_", str(n).lower())
        s = ("s_" + s) if not s or s[0].isdigit() else s
        return s + "_slot" if s in RESERVED else s

    raw_slots = d.get("slots") if isinstance(d.get("slots"), dict) else {}
    for rname, spec in raw_slots.items():
        if rname == "requested_slot":
            continue
        spec = spec if isinstance(spec, dict) else {}
        n = ident(rname)
        slot_map[str(rname)] = n
        slot_types[n] = spec.get("type") or "text"
        slot = {"name": n, "entity": ""}
        for mapping in spec.get("mappings") or []:
            kind = mapping.get("type")
            if kind == "from_entity" and not slot["entity"]:
                ent = str(mapping.get("entity") or "")
                if mapping.get("role"):
                    ent = "%s_%s" % (ent, mapping["role"])
                if ent and ent not in by_entity:
                    by_entity[ent] = {"name": ent, "kind": "examples", "values": [], "regex": "", "color": len(entities) % 6}
                    entities.append(by_entity[ent])
                slot["entity"] = ent
                if mapping.get("intent") or mapping.get("not_intent") or mapping.get("conditions") or mapping.get("group"):
                    warn("slot «%s»: las condiciones de su mapping (intent, not_intent, conditions, group) no se importan" % rname)
            elif kind in ("from_llm", "from_text", "controlled") or kind is None:
                if kind == "from_llm":
                    free_llm.append(n)
            elif kind == "from_entity":
                warn("slot «%s»: tiene más de un mapping from_entity; quedó solo el primero (%s)" % (rname, slot["entity"]))
            else:
                warn("slot «%s»: el mapping «%s» no existe en Parla (se llena sola con una entidad o al preguntar); "
                     "para un valor fijo usá un paso «Guardar un valor» en el flujo" % (rname, kind))
        if not spec.get("mappings") and spec.get("type"):
            no_mapping.append(str(rname))
        values = [str(v).lower() if isinstance(v, bool) else str(v) for v in spec.get("values") or []]
        if not slot["entity"] and slot_types[n] == "categorical" and values:
            ent = n if n not in by_entity else n + "_opcion"
            by_entity[ent] = {"name": ent, "kind": "list", "values": values, "regex": "", "color": len(entities) % 6}
            entities.append(by_entity[ent])
            slot["entity"] = ent
        elif not slot["entity"] and slot_types[n] == "bool":
            ent = n if n not in by_entity else n + "_si_no"
            by_entity[ent] = {"name": ent, "kind": "list", "values": ["true", "false"], "synonyms": YES_NO, "regex": "", "color": len(entities) % 6}
            entities.append(by_entity[ent])
            slot["entity"] = ent
        if spec.get("initial_value") is not None:
            warn("slot «%s»: «initial_value» (%s) no se importa; poné un paso «Guardar un valor» al principio del flujo que lo use"
                 % (rname, spec["initial_value"]))
        slots.append(slot)
    free_llm = [n for n in free_llm if not next(x for x in slots if x["name"] == n)["entity"]]
    if free_llm:
        warn("slots que en Rasa llena el LLM (%s): en Parla guardan la respuesta entera cuando se preguntan. "
             "Para que la IA saque el dato, prendé la IA y elegí «Lo completa la IA» en el slot" % ", ".join(free_llm))

    # ---------- respuestas ----------
    responses = d.get("responses") if isinstance(d.get("responses"), dict) else {}
    used, multi = set(), []

    def template(text):
        return SLOT_REF.sub(lambda m: "{{ %s }}" % slot_map[m.group(1)] if m.group(1) in slot_map else m.group(0), str(text))

    def bubble(utter, kind="message", slot=None):
        """Un utter_* de Rasa -> un paso message o ask (o None si no existe esa respuesta)."""
        options = responses.get(utter)
        if not isinstance(options, list) or not options:
            return None
        used.add(utter)
        plain = [o for o in options if isinstance(o, dict) and not o.get("condition") and not o.get("channel")]
        chosen = (plain or [o for o in options if isinstance(o, dict)] or [{}])[0]
        if len(options) > 1:
            multi.append(utter)
        step = {"type": kind, "text": template(chosen.get("text") or "")}
        if slot:
            step["slot"] = slot
        buttons = []
        for b in chosen.get("buttons") or []:
            title, payload = str(b.get("title") or "").strip(), str(b.get("payload") or "").strip()
            if not title:
                continue
            value = payload or title
            if payload.startswith("/"):        # «/inform{"x": "y"}»: en Parla tocar un botón es escribir su value
                target = re.match(r"/([^{\s]+)", payload)
                sample = intents.get(target.group(1) if target else "", [])
                value = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", sample[0]) if sample else title
                if "{" in payload:
                    warn("%s: el botón «%s» manda entidades en el payload (%s); en Parla manda «%s»" % (utter, title, payload, value))
            if title.lower() not in {x["label"].lower() for x in buttons}:
                buttons.append({"label": template(title), "value": value})
        if buttons:
            step["buttons"] = buttons
        for key in sorted(set(chosen) - {"text", "buttons", "condition", "channel", "metadata"}):
            warn("%s: «%s» no se importa (Parla manda texto y botones%s)" % (
                utter, key, "; para imágenes o archivos usá un paso «Enviar un archivo»" if key in ("image", "attachment") else ""))
        if not step["text"].strip():
            step["text"] = chosen.get("title") or utter
            warn("%s: no tiene texto; quedó «%s»" % (utter, step["text"]))
        return step

    if bubble("utter_default"):
        agent["fallback"] = bubble("utter_default")["text"]

    # ---------- acciones ----------
    forms = d.get("forms") if isinstance(d.get("forms"), dict) else {}
    form_after, custom_used = {}, []
    retrieval = {n.split("/")[0] for n in intents if "/" in n}

    def placeholder(action):
        if action not in custom_used:
            custom_used.append(action)
        return {"type": "http", "method": "POST", "url": WEBHOOK, "headers": [],
                "body": json.dumps({"next_action": action, "sender_id": "parla"}), "saves": [],
                "note": "TODO: acción personalizada de Rasa «%s». Reemplazá este paso por la consulta real o una función." % action}

    def ask_slot(rslot, form=None):
        n = slot_map.get(str(rslot)) or ident(rslot)
        if n not in slot_types:
            slot_map[str(rslot)], slot_types[n] = n, "text"
            slots.append({"name": n, "entity": ""})
            warn("slot «%s»: se pregunta pero no está en el domain; lo creé sin entidad (guarda la respuesta entera)" % rslot)
        step = (form and bubble("utter_ask_%s_%s" % (form, rslot), "ask", n)) or bubble("utter_ask_%s" % rslot, "ask", n)
        if not step:
            step = {"type": "ask", "slot": n, "text": "¿%s?" % str(rslot).replace("_", " ")}
            custom = "action_ask_%s" % rslot
            warn("slot «%s»: no hay respuesta utter_ask_%s%s; la pregunta quedó «%s», cambiala" % (
                rslot, rslot, " (la pregunta la hacía la acción %s, que no se importa)" % custom
                if custom in (d.get("actions") or []) else "", step["text"]))
        return step

    def action_steps(action, rest=()):
        action = str(action)
        if action in SILENT_ACTIONS:
            return []
        if action in forms:
            spec = forms[action] if isinstance(forms[action], dict) else {}
            required = spec.get("required_slots") or []
            out = [ask_slot(s, action) for s in (list(required) if isinstance(required, (list, dict)) else [])]
            if "validate_%s" % action in (d.get("actions") or []):
                warn("form «%s»: la validación validate_%s es código de Rasa y no se importa; en Parla validá con "
                     "entidades de formato o de lista (rechazan lo que no coincide)" % (action, action))
            for key in sorted(set(spec) - {"required_slots", "ignored_intents"}):
                warn("form «%s»: «%s» no se importa" % (action, key))
            if not rest and form_after.get(action):
                for a in form_after[action]:
                    out += action_steps(a)
            return out
        if action.startswith("utter_") and action[6:] in retrieval:
            return []                          # FAQ de Rasa: cada pregunta (faq/xxx) es su propia intención en Parla
        step = bubble(action)
        if step:
            return [step]
        if action.startswith("utter_"):
            warn("%s: no está en las respuestas del domain; quedó un mensaje con su nombre" % action)
            return [{"type": "message", "text": action}]
        if action == "action_restart":
            warn("action_restart: Parla no reinicia la conversación desde un flujo; borrá los slots con pasos «Guardar un valor» si hace falta")
            return []
        return [placeholder(action)]

    # ---------- reglas e historias (Rasa clásico) ----------
    segments = {}            # intención -> (acciones, de dónde)

    def walk(kind, item):
        title = "%s «%s»" % ("regla" if kind == "rule" else "historia", item.get(kind) or "sin nombre")
        cond_forms = [c.get("active_loop") for c in item.get("condition") or [] if isinstance(c, dict) and c.get("active_loop")]
        for key in sorted(set(item) - {kind, "steps", "condition", "wait_for_user_input", "conversation_start", "metadata"}):
            warn("%s: «%s» no se importa" % (title, key))
        if item.get("conversation_start"):
            warn("%s: «conversation_start» no se importa (para algo al empezar, usá un flujo con trigger __start__)" % title)
        current, orphan, noted, segs = None, [], set(), []
        for step in item.get("steps") or []:
            if not isinstance(step, dict):
                continue
            if "intent" in step or "or" in step:
                names = [step["intent"]] if "intent" in step else [s["intent"] for s in step["or"] if isinstance(s, dict) and "intent" in s]
                current = {"triggers": [str(n) for n in names], "actions": []}
                segs.append(current)
            elif "action" in step or "bot" in step:
                act = step.get("action") or {"bot": step["bot"]}
                (current["actions"] if current else orphan).append(act)
            elif "user" in step:
                if "user" not in noted:
                    warn("%s: los pasos «user» (texto de punta a punta) no se importan" % title)
                noted.add("user")
                current = None
            elif "slot_was_set" in step:
                keys = {k for s in (step["slot_was_set"] or []) for k in (s if isinstance(s, dict) else {s: None})}
                if keys - {"requested_slot"} and "slot" not in noted:
                    warn("%s: «slot_was_set» (%s) no se importa; si la historia depende de un slot, poné un paso «Tomar un camino»"
                         % (title, ", ".join(sorted(keys))))
                    noted.add("slot")
            elif "checkpoint" in step:
                if "checkpoint" not in noted:
                    warn("%s: los checkpoints no se importan; cada intención queda con su propio flujo" % title)
                noted.add("checkpoint")
            elif "active_loop" in step:
                pass                               # el form ya arrancó con su action; active_loop: null es el final del form
            else:
                warn("%s: no entiendo el paso %s" % (title, json.dumps(step, ensure_ascii=False)[:80]))
        if orphan:
            first = orphan[0] if isinstance(orphan[0], str) else None
            if first in forms or (cond_forms and first in cond_forms):
                form_after.setdefault(first, [a for a in orphan[1:] if a != first])
            else:
                warn("%s: empieza sin una intención; sus acciones no se importan" % title)
        for seg in segs_of(segs, cond_forms):
            for trig in seg["triggers"]:
                if trig in segments:
                    if segments[trig][0] != seg["actions"]:
                        warn("intención «%s»: %s responde distinto que %s (depende del contexto); quedó la primera" % (trig, title, segments[trig][1]))
                    continue
                segments[trig] = (seg["actions"], title)

    def segs_of(found, cond_forms):
        for seg in found:
            if cond_forms:   # una interrupción dentro de un form: Parla vuelve sola a la pregunta pendiente
                seg["actions"] = [a for a in seg["actions"] if a not in cond_forms]
            if seg["actions"]:
                yield seg

    for kind, key in (("rule", "rules"), ("story", "stories")):
        for item in d.get(key) or []:
            if isinstance(item, dict):
                walk(kind, item)

    flows, names = [], set()

    def flow_name(base):
        n, k = base, 2
        while n in names:
            n, k = "%s (%d)" % (base, k), k + 1
        names.add(n)
        return n

    for trig, (actions, _) in segments.items():
        steps = []
        for i, a in enumerate(actions):
            if isinstance(a, dict):           # paso «bot: texto»
                steps.append({"type": "message", "text": template(a["bot"])})
            else:
                steps += action_steps(a, actions[i + 1:])
        if trig == "nlu_fallback":
            said = [s["text"] for s in steps if s["type"] == "message"]
            if said:
                agent["fallback"] = said[0]
            continue
        intents.setdefault(trig, [])
        if steps:
            flows.append({"name": flow_name(trig), "trigger": trig, "steps": steps})
    for n in intents:
        if "/" in n and not any(f["trigger"] == n for f in flows):
            step = bubble("utter_" + n)
            if step:
                flows.append({"name": flow_name(n), "trigger": n, "steps": [step]})

    # ---------- flows de CALM ----------
    calm = d.get("flows") if isinstance(d.get("flows"), dict) else {}
    no_examples, moved = [], set()
    for fid in calm:
        if str(fid).startswith("pattern_"):
            warn("flow «%s»: es un patrón de conversación de CALM; Parla tiene los suyos en Flujos del sistema, no se importa" % fid)
    real = {str(k): v for k, v in calm.items() if not str(k).startswith("pattern_") and isinstance(v, dict)}
    calm_names = {fid: flow_name(fid) for fid in real}
    for fid, spec in real.items():
        compile_flow(fid, spec, calm_names, flows, flow_name, slot_map, slot_types, ask_slot, action_steps, warn)
        triggers = []
        for t in spec.get("nlu_trigger") or []:
            t = t.get("intent") if isinstance(t, dict) else t
            t = t.get("name") if isinstance(t, dict) else t
            if t:
                triggers.append(str(t))
        examples = [ex for t in triggers for ex in intents.get(t, [])]
        moved |= set(triggers)
        description = str(spec.get("description") or "").strip()
        if not examples and description:
            examples = [description]
            no_examples.append(fid)
        if examples:
            intents[fid] = list(dict.fromkeys(intents.get(fid, []) + examples))
            next(f for f in flows if f["name"] == calm_names[fid])["trigger"] = fid
        for key in sorted(set(spec) - {"description", "name", "steps", "nlu_trigger", "persisted_slots", "run_pattern_completed"}):
            warn("flow «%s»: «%s» no se importa%s" % (fid, key, " (para arrancarlo solo en algún caso, poné un paso «Tomar un camino» al principio)"
                                                       if key == "if" else ""))
    for t in moved:
        if t in intents and not any(f.get("trigger") == t for f in flows):
            del intents[t]                     # sus frases pasaron a la intención del flujo que disparaban
    if no_examples:
        warn("CALM elige el flujo con un LLM leyendo la descripción; Parla necesita frases de ejemplo. Los flujos %s quedaron "
             "con una intención que tiene solo la descripción como frase: sumale 5 a 10 frases reales a cada una"
             % ", ".join(no_examples))

    # ---------- avisos de lo que quedó afuera ----------
    if multi:
        warn("respuestas con variaciones (o por canal o condición): quedó la primera de %s" % ", ".join(sorted(set(multi))))
    unused = sorted(set(responses) - used - {"utter_" + n for n in intents if "/" in n})
    if unused:
        warn("respuestas que no usa ninguna regla, historia ni flow, no se importaron: %s" % ", ".join(unused))
    for a in custom_used:
        warn("acción personalizada «%s»: es código de Rasa; quedó un paso «Consultar un servicio» a %s (el servidor de acciones) "
             "como marcador. Reemplazalo por la consulta real o por una función" % (a, WEBHOOK))
    declared = [str(a) for a in d.get("actions") or [] if not str(a).startswith("utter_")]
    skipped = [a for a in declared if a not in custom_used and not a.startswith("validate_") and a not in forms]
    if skipped:
        warn("acciones del domain que no usa ninguna regla, historia ni flow, no se importaron: %s" % ", ".join(skipped))
    if no_mapping:
        warn("slots sin mappings (%s): quedaron sin entidad, guardan la respuesta entera cuando se preguntan" % ", ".join(no_mapping))
    agent["intents"] = [{"name": n, "examples": exs} for n, exs in intents.items()]
    agent["entities"], agent["slots"], agent["flows"] = entities, slots, flows
    empty = [n for n, exs in intents.items() if not exs]
    if empty:
        warn("intenciones sin frases de ejemplo (%s): sumales frases o el bot no las va a reconocer" % ", ".join(empty))
    if not any(agent[k] for k in ("intents", "entities", "slots", "flows")):
        raise ValueError("no encontré nada de Rasa para importar: mandá los .yml del proyecto (data/, domain.yml, config.yml)")
    return agent, warnings


def compile_flow(fid, spec, calm_names, flows, flow_name, slot_map, slot_types, ask_slot, action_steps, warn):
    """Un flow de CALM -> uno o más flujos de Parla. Los saltos a un paso con id («next: pedir_monto») van a un flujo
    aparte «<flow> · <id>» con goto: así no se duplican pasos y los loops quedan bien."""
    persisted = {str(s) for s in spec.get("persisted_slots") or []}
    ids, targets, resets = {}, set(), []

    def index(steps):
        for i, s in enumerate(steps if isinstance(steps, list) else []):
            if not isinstance(s, dict):
                continue
            if s.get("id"):
                ids[str(s["id"])] = (steps, i)
            if s.get("collect") and s.get("reset_after_flow_ends", True) and str(s["collect"]) not in persisted:
                n = slot_map.get(str(s["collect"]), str(s["collect"]))
                if n not in resets:
                    resets.append(n)
            nxt = s.get("next")
            if isinstance(nxt, str) and nxt != "END":
                targets.add(nxt)
            for branch in nxt if isinstance(nxt, list) else []:
                then = branch.get("then", branch.get("else")) if isinstance(branch, dict) else None
                if isinstance(then, str) and then != "END":
                    targets.add(then)
                index(then)
    index(spec.get("steps"))
    resets = [n for n in resets if n in slot_types]
    finish = lambda: [{"type": "set", "slot": n, "mode": "clear"} for n in resets]   # noqa: E731 - CALM borra lo preguntado al terminar
    label = lambda t: "%s · %s" % (calm_names[fid], t)                              # noqa: E731

    def jump(target):
        if target == "END":
            return finish()
        if target not in ids:
            warn("flow «%s»: «next: %s» apunta a un paso que no existe; ahí termina" % (fid, target))
            return finish()
        return [{"type": "goto", "goto": label(target)}]

    def seq(steps, start):
        out = []
        for i in range(start, len(steps)):
            s = steps[i]
            if not isinstance(s, dict):
                continue
            if i > start and s.get("id") in targets:
                return out + [{"type": "goto", "goto": label(s["id"])}]
            out += one(s)
            if s.get("link") and s["link"] in calm_names:
                return out                         # link termina este flow y arranca el otro
            nxt = s.get("next")
            if nxt is None:
                continue
            if isinstance(nxt, str):
                return out + jump(nxt)
            return out + branches(nxt)
        return out + finish()

    def branch_steps(then):
        if isinstance(then, str):
            return jump(then)
        return seq(then, 0) if isinstance(then, list) else finish()

    def branches(items):
        items = [b for b in items if isinstance(b, dict)]
        if not items:
            return finish()
        first = items[0]
        if "if" not in first:
            return branch_steps(first.get("else", first.get("then")))
        step = condition(first["if"])
        step["then"] = branch_steps(first.get("then"))
        step["else"] = branches(items[1:])
        return [step]

    def condition(text):
        found = translate(text, slot_map, slot_types)
        if found:
            return dict(found, type="if")
        warn("flow «%s»: no pude traducir la condición «%s»; quedó como «no se cumple» (siempre va por el otro camino), "
             "arreglala en el paso «Tomar un camino»" % (fid, text))
        return {"type": "if", "expr": "false", "note": "Condición de Rasa sin traducir: %s" % text}

    def one(s):
        known = {"id", "next", "collect", "utter", "ask_before_filling", "reset_after_flow_ends", "description", "rejections",
                 "action", "set_slots", "link", "call", "noop", "force_slot_filling"}
        for key in sorted(set(s) - known):
            warn("flow «%s»: el paso %s tiene «%s», que no se importa" % (fid, s.get("id") or "", key))
        if s.get("collect"):
            rslot = str(s["collect"])
            ask = ask_slot(rslot)
            if s.get("utter"):
                from_utter = action_steps(s["utter"])
                if from_utter and from_utter[0]["type"] == "message":
                    ask = dict(from_utter[0], type="ask", slot=ask["slot"])
            if s.get("rejections"):
                warn("flow «%s»: las «rejections» de %s no se importan; usá una entidad de lista o de formato para rechazar respuestas" % (fid, rslot))
            return ([{"type": "set", "slot": ask["slot"], "mode": "clear"}] if s.get("ask_before_filling") else []) + [ask]
        if s.get("action"):
            return action_steps(s["action"])
        if "set_slots" in s:
            out = []
            items = s["set_slots"] if isinstance(s["set_slots"], list) else [s["set_slots"]]
            for pair in items:
                for k, v in (pair.items() if isinstance(pair, dict) else []):
                    n = slot_map.get(str(k))
                    if not n:
                        warn("flow «%s»: set_slots usa «%s», que no está en los slots del domain" % (fid, k))
                        continue
                    out.append({"type": "set", "slot": n, "mode": "clear"} if v is None else
                               {"type": "set", "slot": n, "mode": "text", "text": str(v).lower() if isinstance(v, bool) else str(v)})
            return out
        if s.get("link") or s.get("call"):
            target = str(s.get("link") or s.get("call"))
            if target not in calm_names:
                warn("flow «%s»: %s «%s» apunta a un flow que no existe o no se importa" % (fid, "link" if s.get("link") else "call", target))
                return []
            if s.get("link"):
                return finish() + [{"type": "goto", "goto": calm_names[target]}]
            return [{"type": "call", "flow": calm_names[target]}]
        return []                                  # noop: solo vale su next

    steps = spec.get("steps") if isinstance(spec.get("steps"), list) else []
    if not steps:
        warn("flow «%s»: no tiene pasos" % fid)
    flows.append({"name": calm_names[fid], "trigger": "", "steps": seq(steps, 0), "description": str(spec.get("description") or "")})
    for t in sorted(targets):
        if t in ids:
            flows.append({"name": flow_name(label(t)), "trigger": "", "steps": seq(*ids[t])})


def translate(text, slot_map, slot_types):
    """Condición de CALM (pypred) -> {"cond": {var, op, value}} o {"expr": CEL}, o None si no se puede."""
    s = str(text).strip()
    if s.lower() in ("true", "false"):
        return {"expr": s.lower()}
    name = lambda n: slot_map.get(n)    # noqa: E731
    m = re.fullmatch(r"(not\s+)?(?:slots\.)?(\w+)", s)
    if m and name(m.group(2)):
        n = name(m.group(2))
        if slot_types.get(n) == "bool":
            return {"cond": {"var": n, "op": "ne" if m.group(1) else "eq", "value": "true"}}
        return {"cond": {"var": n, "op": "empty" if m.group(1) else "filled", "value": ""}}
    m = re.fullmatch(r"(?:slots\.)?(\w+)\s*(==|=|!=|is\s+not|is|>|<)\s*(.+)", s)
    if m and name(m.group(1)) and not re.search(r"\b(and|or|not)\b|&&|\|\|", m.group(3)):
        n, op, value = name(m.group(1)), re.sub(r"\s+", " ", m.group(2)), m.group(3).strip().strip("'\"")
        if value.lower() in ("null", "none"):
            return {"cond": {"var": n, "op": "filled" if op in ("!=", "is not") else "empty", "value": ""}}
        op = {"==": "eq", "=": "eq", "is": "eq", "!=": "ne", "is not": "ne", ">": "gt", "<": "lt"}[op]
        if op in ("gt", "lt"):
            try:
                float(value)
            except ValueError:
                return None
        return {"cond": {"var": n, "op": op, "value": value.lower() if value.lower() in ("true", "false") else value}}
    def truthy(x):  # «slots.a and slots.b»: un slot suelto es «tiene valor» (en CEL «a && b» con textos falla)
        n = name(x.group(2))
        if not n:
            return x.group(0)
        test = '%s == "true"' % n if slot_types.get(n) == "bool" else '%s != null && %s != ""' % (n, n)
        return ("!(%s)" if x.group(1) else "(%s)") % test
    s = re.sub(r"(?:^|(?<=\band )|(?<=\bor )|(?<=\())(not\s+)?slots\.(\w+)(?=\s*$|\s*\)|\s+and\b|\s+or\b)", truthy, s)

    def var(x):     # los slots son texto: un float se compara con double(x)
        n = slot_map.get(x.group(1), "slots_" + x.group(1))
        return "double(%s)" % n if slot_types.get(n) == "float" else n
    expr = re.sub(r"\bslots\.(\w+)", var, s)
    for a, b in ((r"\bis\s+not\b", "!="), (r"\bis\b", "=="), (r"(?<![=!<>])=(?!=)", "=="), (r"\band\b", "&&"),
                 (r"\bor\b", "||"), (r"\bnot\s+", "!"), (r"\bNone\b", "null"), (r"\bTrue\b", "true"), (r"\bFalse\b", "false")):
        expr = re.sub(a, b, expr)
    words = set(re.findall(r"(?<![\w.\"'])([A-Za-z_]\w*)", re.sub(r"\"[^\"]*\"|'[^']*'", "", expr))) - {"true", "false", "null", "in", "size", "double"}
    if words - set(slot_map.values()):
        return None
    try:
        import celpy
        celpy.Environment().compile(expr)
    except Exception:  # noqa: BLE001 - celpy tira varios tipos
        return None
    return {"expr": expr}


MAX_FILES, MAX_TOTAL = 500, 20_000_000      # un proyecto de Rasa real tiene decenas de .yml y pocos MB


def read_zip(raw):
    """Los .yml/.yaml de un zip -> ({ruta: texto}, avisos). Sin rutas absolutas ni «..», y con tope de cantidad y tamaño
    (descomprimido) para que un zip bomba no tumbe el servidor."""
    import io
    import zipfile
    files, warnings, total = {}, [], 0
    try:
        z = zipfile.ZipFile(io.BytesIO(raw))
    except zipfile.BadZipFile:
        raise ValueError("el archivo no es un .zip válido") from None
    for info in z.infolist():
        name = info.filename.replace("\\", "/")
        if info.is_dir() or not name.lower().endswith((".yml", ".yaml")):
            continue
        if name.startswith("/") or re.match(r"[A-Za-z]:", name) or ".." in name.split("/"):
            warnings.append("%s: ruta insegura dentro del zip, la salteo" % name)
            continue
        if any(part.startswith(".") or part in ("models", "__MACOSX") for part in name.split("/")[:-1]):
            continue
        total += info.file_size
        if len(files) >= MAX_FILES or total > MAX_TOTAL:
            raise ValueError("el zip es demasiado grande: hasta %d archivos .yml y %d MB descomprimidos" % (MAX_FILES, MAX_TOTAL // 1_000_000))
        with z.open(info) as f:
            data = f.read(MAX_TOTAL + 1)
        if len(data) > info.file_size:
            raise ValueError("el zip es demasiado grande o está dañado")
        files[name] = data.decode("utf-8", "replace")
    return files, warnings


def read_folder(root):
    """Los .yml/.yaml de una carpeta de proyecto Rasa -> {ruta relativa: texto} (sin .venv, models ni ocultas)."""
    import os
    out = {}
    for base, dirs, names in os.walk(root):
        dirs[:] = [x for x in dirs if not x.startswith(".") and x not in ("models", "node_modules", "venv", "__pycache__", "results")]
        for n in names:
            if n.lower().endswith((".yml", ".yaml")):
                full = os.path.join(base, n)
                if os.path.getsize(full) <= 5_000_000:
                    with open(full, encoding="utf-8", errors="replace") as f:
                        out[os.path.relpath(full, root).replace(os.sep, "/")] = f.read()
    return out


def main():
    import argparse
    import os
    import sys
    parser = argparse.ArgumentParser(description="Convierte un proyecto de Rasa en un agente de Parla (JSON para «Importar agente»).")
    parser.add_argument("project", help="carpeta del proyecto Rasa (la que tiene domain.yml y data/)")
    parser.add_argument("-o", "--output", help="dónde guardar el agente (por defecto, lo imprime)")
    parser.add_argument("--name", help="nombre del agente (por defecto, el de la carpeta)")
    args = parser.parse_args()
    try:
        agent, warnings = convert(read_folder(args.project), args.name or os.path.basename(os.path.abspath(args.project)))
    except ValueError as error:
        sys.exit("error: %s" % error)
    text = json.dumps({"parla": 1, "agent": agent}, ensure_ascii=False, indent=2)
    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(text + "\n")
    else:
        print(text)
    print("\n%d intenciones, %d entidades, %d slots, %d flujos. %d avisos%s" % (
        len(agent["intents"]), len(agent["entities"]), len(agent["slots"]), len(agent["flows"]), len(warnings),
        ":" if warnings else "."), file=sys.stderr)
    for w in warnings:
        print("  - " + w, file=sys.stderr)


if __name__ == "__main__":
    main()
