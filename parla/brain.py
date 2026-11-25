"""IA generativa encima del motor, pensada para modelos chicos y locales (qwen2.5:0.5b en CPU).
La IA propone y el motor decide: solo se acepta una intención de la lista, un valor que está en el texto, una
función permitida por el paso. Si la IA está apagada o no responde, todo vuelve al comportamiento de siempre.
Ninguna función lanza."""
import json
import re

from . import dates, knowledge, llm

LANGS = {"es": "español rioplatense", "pt": "portugués", "en": "inglés"}
MAX_CALLS = 4


def _on(agent, flag=None):
    try:
        cfg = llm.settings(agent)
    except Exception:
        return None
    return cfg if cfg.get("enabled") and (flag is None or cfg.get(flag)) else None


def _lang(st):
    return LANGS.get((st or {}).get("lang") or "es", (st or {}).get("lang") or "español")


def _recent(st, n=6):
    lines = ["%s: %s" % ("Usuario" if r.get("role") == "user" else "Bot", r.get("text", ""))
             for r in ((st or {}).get("recent") or [])[-n:] if isinstance(r, dict)]
    return "\n".join(lines)


def _system(cfg, extra):
    persona = (cfg.get("persona") or "").strip()
    return {"role": "system", "content": (("Tu personalidad: " + persona + "\n") if persona else "") + extra}


def _plain(s):
    return dates._plain(str(s or "")).strip()


# ---------- rescatar intención ----------
def rescue_intent(agent, text, nlu, st=None):
    """Elige entre las 5 mejores intenciones del NLU (o ninguna). Solo acepta un nombre de la lista.
    Los modelos chicos casi nunca dicen «ninguna» y prefieren la primera opción: por eso se descartan candidatas
    lejanas y se pregunta dos veces con el orden invertido; solo vale si las dos respuestas coinciden."""
    try:
        cfg = _on(agent, "rescue_intents")
        threshold = float(agent.get("threshold") or 0)
        scores = {}
        for r in (nlu or {}).get("ranking") or []:
            name, score = (r[0], r[1]) if isinstance(r, (list, tuple)) else (r.get("intent"), r.get("confidence", 0))
            if name and float(score) >= max(0.25, threshold - 0.3):   # algo parecido tiene que haber
                scores[name] = float(score)
        ranking = list(scores)[:5]
        if not cfg or not ranking or not str(text or "").strip():
            return nlu
        intents = {i["name"]: i for i in agent.get("intents") or []}
        context = ("Conversación previa:\n" + _recent(st, 4) + "\n\n") if _recent(st, 4) else ""

        def ask(names):
            letters = "ABCDE"[:len(names)]
            options = "\n".join('%s) %s. Ejemplos: %s' % (l, n.replace("_", " "), "; ".join(
                re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", e) for e in ((intents.get(n) or {}).get("examples") or [])[:3] if e.strip()) or "-")
                for l, n in zip(letters, names))
            prompt = ('%sMensaje: "%s"\n\nOpciones:\n%s\nZ) ninguna de las anteriores\n\n¿Qué opción describe mejor el '
                      'mensaje? Respondé con la letra.' % (context, text, options))
            out = llm.chat(cfg, [{"role": "user", "content": prompt}], timeout=20, max_tokens=20, schema={
                "type": "object", "properties": {"opcion": {"type": "string", "enum": list(letters) + ["Z"]}}, "required": ["opcion"]})
            return names[letters.index(out["opcion"])] if out.get("opcion") in letters else None

        choice = ask(ranking)
        if choice is None or (len(ranking) > 1 and ask(ranking[::-1]) != choice):
            return nlu
        # la IA ya eligió: queda al menos en el umbral del agente para que el motor la acepte
        return dict(nlu, intent=choice, confidence=round(max(scores[choice], threshold), 3), via="ia")
    except Exception:
        return nlu


# ---------- completar un slot ----------
def _is_date(agent, slot):
    entity = next((e for e in agent.get("entities") or [] if e.get("name") == slot.get("entity")), {})
    return entity.get("kind") == "date" or bool(re.search(r"\b(fecha|dia|hora|horario|cuando|turno)\b", _plain(
        "%s %s" % (slot.get("name"), slot.get("description")))))


def fill_slot(agent, slot, text, ctx=None):
    """Valor del slot leído del texto según su descripción, o None. La IA no puede inventar: el valor tiene que
    estar en el mensaje (las fechas se normalizan con dates.extract, sin modelo)."""
    try:
        cfg = _on(agent)
        if not cfg or not str(text or "").strip():
            return None
        if _is_date(agent, slot):
            found = dates.extract(text)
            if found:
                return found[0]["value"]
        desc = slot.get("description") or slot.get("name")
        # los modelos chicos extraen bien con un ejemplo, pero devuelven algo aunque no esté: se verifica aparte
        prompt = ('Del mensaje, extraé el dato pedido. Si no aparece, dejalo en "".\nDato: valor = %s\n\n'
                  'Ejemplo: "me llamo Pedro Ruiz" con dato "nombre" -> {"valor": "Pedro Ruiz"}\n'
                  'Ejemplo: "quiero info" -> {"valor": ""}\n\nMensaje: "%s"' % (desc, text))
        out = llm.chat(cfg, [{"role": "user", "content": prompt}], timeout=20, max_tokens=60,
                       schema={"type": "object", "properties": {"valor": {"type": "string"}}, "required": ["valor"]})
        value = str(out.get("valor") or "").strip().strip("\"'.,")
        if not value:
            return None
        words = re.findall(r"\w+", _plain(value))
        # ponytail: control por palabras; un valor normalizado por la IA («dos» -> «2») se descarta
        if not words or not all(re.search(r"(?<!\w)" + re.escape(w) + r"(?!\w)", _plain(text)) for w in words):
            return None
        check = llm.chat(cfg, [{"role": "user", "content": 'Mensaje: "%s"\n¿"%s" es un dato del tipo "%s"? Respondé si o no.' % (text, value, desc)}],
                         timeout=20, max_tokens=15, schema={"type": "object", "properties": {"respuesta": {"type": "string", "enum": ["si", "no"]}}, "required": ["respuesta"]})
        return value if check.get("respuesta") == "si" else None
    except Exception:
        return None


# ---------- una pregunta en medio de una pregunta ----------
# «¿qué es presencial?» mientras el bot pregunta «¿presencial o virtual?»: trae el valor, pero no es una respuesta.
# «que sea más tarde» o «que quede en Bogotá» contestan: «que» solo cuenta en «qué es», «qué significa», etc.
QUESTION = re.compile(r"\?|^\s*(que\s+(es|son|significa|quiere\s+decir|incluye|pasa|tengo|necesito|debo|hago|llevo)"
                      r"|cual|cuales|como|donde|cuando|cuanto|cuantos|cuanta|por\s*que|para\s*que|quien|quienes"
                      r"|tienen|se\s+puede|necesito\s+saber)\b")
# «sí» corto y claro, para tomar la opción que el bot acaba de explicar («¿qué es presencial?» … «ah, entonces sí»):
# todas las palabras son de asentir o de relleno, y al menos una asiente.
YES_WORDS = {"si", "sii", "siii", "sip", "dale", "claro", "ok", "okey", "listo", "perfecto", "vale", "una", "sim", "yes", "bueno"}
FILLERS = {"ah", "ahh", "aa", "ahi", "entonces", "pues", "ya", "de", "esa", "ese", "eso", "porfa", "por", "favor", "gracias", "que"}


def affirmative(text):
    words = re.findall(r"\w+", _plain(text))
    return bool(words) and len(words) <= 6 and all(w in YES_WORDS | FILLERS for w in words) and any(w in YES_WORDS for w in words)


DONT_KNOW = {"es": "Esa consulta no la puedo responder por acá.", "pt": "Essa dúvida eu não consigo responder por aqui.",
             "en": "I can't answer that here."}   # neutro: lo dice cualquier bot, de cualquier país


def answer(agent, st, text):
    """Respuesta a una consulta suelta: la base de conocimiento, o un «no lo sé» honesto (nunca inventa)."""
    return _from_knowledge(agent, st, text) or {"text": DONT_KNOW.get((st or {}).get("lang") or "es", DONT_KNOW["es"]),
                                                "sources": [], "via": "ia"}


def side_question(agent, st, text, asked):
    """Si la persona, en vez de contestar `asked`, hace otra pregunta: {"text", "sources", "via"} con la respuesta
    (de la base de conocimiento; sin datos, un «no lo sé» honesto). None si el mensaje parece una respuesta.
    Sin IA solo cuenta como pregunta lo que la base de conocimiento sabe contestar."""
    try:
        if not QUESTION.search(_plain(text)):
            return None
        found = _from_knowledge(agent, st, text)
        if found:
            return found
        cfg = _on(agent)
        if not cfg:
            return None
        out = llm.chat(cfg, [
            {"role": "system", "content": (
                'Clasificás mensajes de clientes de un chat. El bot hizo una pregunta y el cliente escribió algo.\n'
                '"contesta": el cliente responde o elige, aunque lo haga con signos de pregunta, con dudas, proponiendo otra '
                'opción, un día, una hora, un lugar, o pidiendo algo distinto a lo ofrecido.\n'
                '"pregunta": el cliente pide información que no responde la pregunta del bot (qué significa algo, cuánto '
                'cuesta, dónde queda, qué tiene que llevar, cómo funciona).\n'
                'Ejemplos:\nBot: "¿Te sirve el lunes a las 9?" Cliente: "¿y el jueves hay algo?" -> contesta\n'
                'Bot: "¿Te sirve el lunes a las 9?" Cliente: "¿no tenés más tarde?" -> contesta\n'
                'Bot: "¿Presencial o virtual?" Cliente: "¿qué es virtual?" -> pregunta\n'
                'Bot: "¿En qué ciudad?" Cliente: "¿puede ser en Cali?" -> contesta\n'
                'Bot: "¿En qué ciudad?" Cliente: "¿cuánto sale la consulta?" -> pregunta')},
            {"role": "user", "content": 'Bot: "%s" Cliente: "%s" ->' % (asked, text)}], timeout=20, max_tokens=15,
            schema={"type": "object", "properties": {"tipo": {"type": "string", "enum": ["contesta", "pregunta"]}}, "required": ["tipo"]})
        if out.get("tipo") != "pregunta":
            return None
        return {"text": DONT_KNOW.get((st or {}).get("lang") or "es", DONT_KNOW["es"]), "sources": [], "via": "ia"}
    except Exception:
        return None


# ---------- entender un turno mientras el bot espera una respuesta ----------
def _actions(agent, current_flow):
    """Lo que la persona puede pedir en cualquier momento: intenciones con flujo, menos la del flujo en curso."""
    flows = {f.get("trigger"): f for f in agent.get("flows") or [] if f.get("trigger")}
    current = next((f.get("trigger") for f in agent.get("flows") or [] if f.get("name") == current_flow), None)
    # los flujos con "interrupts": false (saludar, agradecer) no cortan una pregunta pendiente: no son acciones
    return [i for i in agent.get("intents") or [] if i.get("name") in flows and i.get("name") != current
            and flows[i["name"]].get("interrupts", True) is not False]


def understand(agent, st, text, asked, entity=None, current_flow=None):
    """Qué hizo la persona con la pregunta `asked`, mirando la charla reciente (no solo el último mensaje):
    {"tipo": "responde" | "pregunta" | "accion" | "nada", "opcion": valor de la lista o None, "accion": intención o None}.
    None sin IA o si el modelo no es consistente (se pregunta dos veces, con las listas al revés: una mala lectura
    puede confirmar una cita). Los saludos y agradecimientos con una pregunta pendiente no son acciones."""
    try:
        cfg = _on(agent)
        if not cfg or not str(text or "").strip():
            return None
        values = [v for v in (entity or {}).get("values") or [] if isinstance(v, str)]
        yes_no = "si" in values and "no" in values
        # una sola lista plana de elecciones con letra: es lo que mejor siguen los modelos chicos
        choices = ([("responde", v, 'contesta "%s"' % ({"si": "sí, acepta", "no": "no, rechaza o pone una objeción"}.get(v, v)
                                                         if yes_no else v)) for v in values]
                   or [("responde", None, "contesta la pregunta")])
        choices += [("pregunta", None, "pregunta algo (pide información en vez de contestar)")]
        choices += [("accion", a["name"], "quiere otra cosa: %s" % a["name"].lower()) for a in _actions(agent, current_flow)]

        def ask(order):
            letters = "ABCDEFGHIJKLMNOPQRSTUVWXY"[:len(order)]
            menu = "\n".join("%s) %s" % (l, c[2]) for l, c in zip(letters, order))
            out = llm.chat(cfg, [{"role": "user", "content": (
                'Conversación de un chat de atención:\n%s\n\nEl bot espera respuesta a: "%s"\nEl cliente escribió: "%s"\n\n'
                '¿Qué hizo el cliente? "sí", "esa", "dale", "entonces sí" se refieren a lo último que el bot explicó u ofreció. '
                'Saludar o agradecer no es contestar ni pedir otra cosa: eso es Z.\n%s\nZ) nada de eso (saluda, agradece o no se entiende)\n'
                'Respondé con la letra.' % (_recent(st, 4), asked, text, menu))}],
                timeout=25, max_tokens=10,
                schema={"type": "object", "properties": {"letra": {"type": "string", "enum": list(letters) + ["Z"]}}, "required": ["letra"]})
            letter = out.get("letra")
            kind, value, _ = order[letters.index(letter)] if letter in letters else ("nada", None, "")
            return {"tipo": kind, "opcion": value if kind == "responde" else None, "accion": value if kind == "accion" else None}

        first = ask(choices)
        risky = first["tipo"] == "accion" or first["opcion"] == "si"   # interrumpe o confirma: se pregunta de nuevo
        return first if not risky or ask(choices[::-1]) == first else None
    except Exception:
        return None


# ---------- antes del «no entendí» ----------
def _snippet(text, limit=600):
    text = re.sub(r"^(p|pregunta|q)\s*[:.)-]\s*[^\n]*\?\s*\n", "", str(text).strip(), flags=re.I)   # sin repetir la pregunta
    text = re.sub(r"^(r|respuesta|a)\s*[:.)-]\s*", "", text.strip(), flags=re.I)
    if len(text) <= limit:
        return text
    cut = max(text.rfind(". ", 0, limit), text.rfind("\n", 0, limit))
    return text[:cut + 1 if cut > limit // 3 else limit].strip() + ("" if cut > limit // 3 else "…")


NEGATIONS = {"no", "nunca", "ni", "tampoco", "sin", "jamas", "not", "never", "nao"}


def _supported(answer, context, question):
    """¿La respuesta sale del texto? Controles baratos que atrapan lo que inventan los modelos chicos: números que
    no están, una negación que el texto no tiene, o muchas palabras nuevas. Si no pasa, se muestra el texto tal cual."""
    ans, ctx = _plain(answer), _plain(context)
    if set(re.findall(r"\d+", ans)) - set(re.findall(r"\d+", ctx)):
        return False
    words, known = re.findall(r"\w+", ans), set(re.findall(r"\w+", ctx + " " + _plain(question)))
    if any(w in NEGATIONS and w not in known for w in words):
        return False
    stems = {w[:5] for w in known if len(w) >= 4}
    content = [w for w in words if len(w) >= 4]
    return sum(w[:5] not in stems for w in content) <= max(1, 0.3 * len(content))   # alguna palabra propia, no muchas


def _capabilities(agent):
    return [i["name"].replace("_", " ") for i in agent.get("intents") or [] if i.get("name")][:8]


def _from_knowledge(agent, st, text):
    """Respuesta de la base de conocimiento ({"text", "sources", "via"}) o None si nada pasa el umbral.
    Sin IA devuelve el fragmento; con IA (use_knowledge) lo redacta, y si la redacción no se sostiene, el fragmento."""
    try:
        hits = knowledge.search(agent, text, 3) or []
    except Exception:
        hits = []
    threshold = float(agent.get("knowledge_threshold", 0.75))
    good = [h for h in hits if float(h.get("score") or 0) >= threshold]
    if not good:
        return None
    sources = [{"title": h.get("title"), "doc": h.get("doc"), "score": round(float(h.get("score") or 0), 3)} for h in good]
    cfg = _on(agent, "use_knowledge")
    if cfg:
        try:
            context = "\n\n".join(h["text"] for h in good[:2])
            persona = (cfg.get("persona") or "").strip()
            answer = llm.chat(cfg, [{"role": "user", "content": (
                '%sTexto:\n"""\n%s\n"""\n\nPregunta del cliente: %s\n\nRespondé la pregunta en una o dos oraciones '
                'completas, en %s, usando solo datos del texto.' % (("Así habla el bot: " + persona + "\n") if persona else "",
                                                                  context, text, _lang(st)))}], timeout=40, max_tokens=140)
            answer = re.sub(r"^\s*¿[^?]{3,120}\?\s*", "", answer or "")      # sin repetir la pregunta («¿Qué es…? Es…»)
            leaked = re.search(r"(?im)^\s*(p|r|pregunta|respuesta|texto)\s*:|pregunta del cliente|\"\"\"", answer or "")
            if answer and not leaked and len(answer) <= 400 and _supported(answer, context, text):
                return {"text": answer, "sources": sources, "via": "knowledge"}
        except Exception:
            pass
    return {"text": _snippet(good[0]["text"]), "sources": sources[:1], "via": "knowledge"}


def fallback(agent, st, text):
    """{"text", "sources", "via"} o None. Base de conocimiento primero (funciona sin IA, de forma extractiva);
    si no hay nada, con IA una repregunta corta que dice qué sabe hacer el bot."""
    try:
        if not str(text or "").strip():
            return None
        found = _from_knowledge(agent, st, text)
        if found:
            return found
        cfg = _on(agent, "generative_fallback")
        if not cfg:
            return None
        can = _capabilities(agent)
        persona = (cfg.get("persona") or "").strip()
        prompt = ('%sUn cliente le escribió al bot: "%s"\nEl bot NO entendió el mensaje y no tiene esa información.\n'
                  'Escribí lo que contesta el bot, en %s: una sola oración corta y amable que pida decirlo de otra forma. '
                  'Sin responder la pregunta y sin dar datos.\nEjemplos: "Perdón, no te entendí bien. ¿Me lo contás de otra '
                  'forma?" / "Uy, no estoy seguro de qué necesitás, ¿me lo explicás con otras palabras?"'
                  % (("Así habla el bot: " + persona + "\n") if persona else "", text, _lang(st)))
        try:
            out = llm.chat(cfg, [{"role": "user", "content": prompt}], timeout=30, max_tokens=60,
                           schema={"type": "object", "properties": {"respuesta": {"type": "string"}}, "required": ["respuesta"]})
        except llm.LLMError:
            if not llm.status(cfg).get("ok"):
                return None                     # sin modelo: el «no entendí» de siempre
            out = {}                            # el modelo respondió mal: frase fija + lo que sabe hacer
        out = out if isinstance(out, dict) else {}
        reply = " ".join(re.split(r"(?<=[.!?])\s+", str(out.get("respuesta") or "").strip())[:2])[:220]
        if not reply or "?" not in reply or re.search(r"[\d$@]|https?:", reply):   # tiene que repreguntar   # un número o un link en una repregunta es un dato inventado
            reply = {"en": "Sorry, I didn't get that. Could you say it another way?",
                     "pt": "Desculpa, não entendi. Pode dizer de outro jeito?"}.get((st or {}).get("lang"), "Perdón, no te entendí bien. ¿Me lo decís de otra forma?")
        if can:   # lo que sabe hacer lo pone el motor, no el modelo: así no inventa
            reply += " " + {"en": "I can help with: ", "pt": "Posso ajudar com: "}.get((st or {}).get("lang"), "Puedo ayudarte con: ") + ", ".join(can) + "."
        return {"text": reply, "sources": [], "via": "ia"}
    except Exception:
        return None


# ---------- paso «agent»: una isla de IA con herramientas ----------
def _functions(agent, step):
    allowed = step.get("functions") or []
    return {f["name"]: f for f in agent.get("functions") or [] if f.get("name") in allowed}


def agent_turn(agent, step, st, text, ctx, call_function):
    """Bucle de acciones JSON (sirve para modelos chicos): cada llamada al modelo devuelve
    {"action": "call", "function", "inputs"} o {"action": "reply", "text", "slots", "done"}. El motor ejecuta."""
    stub = {"messages": ["(La IA no está configurada para este agente.)"], "done": True, "slots": {}, "trace": []}
    try:
        cfg = _on(agent)
        if not cfg:
            return stub
        st = st if isinstance(st, dict) else {}
        mem = st.setdefault("agent", {}) if isinstance(st.get("agent", {}), dict) else {}
        mem["turns"] = int(mem.get("turns") or 0) + 1
        max_turns = int(step.get("max_turns") or 8)
        fns = _functions(agent, step)
        slot_names = [s for s in step.get("slots") or []]
        known = {k: v for k, v in (ctx or {}).items() if k in slot_names and v not in (None, "")}
        trace, calls, seen = [], 0, {}
        parts = ["Instrucciones: " + (step.get("instructions") or "Ayudá a la persona."),
                 "Respondé en %s, corto (1 o 2 oraciones)." % _lang(st)]
        if step.get("goal"):
            parts.append("Terminaste (done=true) " + step["goal"] + ".")
        if fns:
            parts.append("Funciones que podés usar: " + "; ".join(
                "%s(%s)%s" % (n, ", ".join(f.get("inputs") or []), (" - " + f["description"]) if f.get("description") else "") for n, f in fns.items()))
        if slot_names:
            parts.append("Datos a conseguir (slots): %s. Ya sabemos: %s." % (", ".join(slot_names), json.dumps(known, ensure_ascii=False) if known else "nada"))
        if mem.get("facts"):
            parts.append("Resultados de funciones que ya usaste: " + "; ".join(mem["facts"]))
        if step.get("knowledge"):
            try:
                hits = [h for h in knowledge.search(agent, text, 3) or [] if float(h.get("score") or 0) >= float(agent.get("knowledge_threshold", 0.75)) * 0.8]
            except Exception:
                hits = []
            if hits:
                parts.append("Información confiable (usá solo esto para datos):\n" + "\n".join("- " + h["text"][:500] for h in hits))
        parts.append('Respondé SOLO JSON. Para usar una función: {"action":"call","function":"nombre","inputs":{...}}. '
                     'Para contestar: {"action":"reply","text":"...","slots":{...},"done":false}. No inventes datos.')
        messages = [_system(cfg, "\n".join(parts))]
        if _recent(st):
            messages.append({"role": "user", "content": "Conversación hasta ahora:\n" + _recent(st)})
        messages.append({"role": "user", "content": text or "(empieza la conversación)"})
        while True:
            actions = ["call", "reply"] if fns and calls < MAX_CALLS else ["reply"]
            schema = {"type": "object", "properties": {
                "action": {"type": "string", "enum": actions},
                "function": {"type": "string", "enum": list(fns) or [""]}, "inputs": {"type": "object"},
                "text": {"type": "string"}, "slots": {"type": "object"}, "done": {"type": "boolean"}},
                "required": ["action"]}
            out = llm.chat(cfg, messages, schema=schema, timeout=45, max_tokens=250)
            if out.get("action") == "call" and "call" in actions:
                name, inputs = out.get("function"), out.get("inputs") if isinstance(out.get("inputs"), dict) else {}
                calls += 1
                if name not in fns:
                    trace.append("IA pidió una función no permitida: %s" % name)
                    messages.append({"role": "user", "content": "La función «%s» no existe. Usá una de: %s." % (name, ", ".join(fns))})
                    continue
                inputs = {k: inputs.get(k, (ctx or {}).get(k)) for k in fns[name].get("inputs") or inputs.keys()}
                key = name + json.dumps(inputs, sort_keys=True, default=str)
                if key in seen:   # los modelos chicos repiten la misma llamada: se le recuerda el resultado y que conteste
                    calls = MAX_CALLS
                    messages.append({"role": "user", "content": "Ya tenés ese resultado: %s. Ahora contestá al usuario." % seen[key]})
                    continue
                try:
                    res = call_function(name, inputs)
                except Exception as error:
                    res = {"ok": False, "error": str(error)}
                trace.append("IA llamó %s(%s) -> %s" % (name, json.dumps(inputs, ensure_ascii=False), "ok" if (res or {}).get("ok") else "error"))
                messages.append({"role": "assistant", "content": json.dumps({"action": "call", "function": name, "inputs": inputs}, ensure_ascii=False)})
                seen[key] = json.dumps((res or {}).get("result") if (res or {}).get("ok") else {"error": (res or {}).get("error")},
                                       ensure_ascii=False, default=str)[:1500]
                mem["facts"] = (mem.get("facts") or [])[-4:] + ["%s(%s) = %s" % (name, json.dumps(inputs, ensure_ascii=False, default=str), seen[key][:300])]
                messages.append({"role": "user", "content": "Resultado de %s: %s" % (name, seen[key])})
                continue
            reply = str(out.get("text") or "").strip()[:400]
            slots = {k: v for k, v in (out.get("slots") or {}).items() if k in slot_names and v not in (None, "")} if isinstance(out.get("slots"), dict) else {}
            done = bool(out.get("done")) or mem["turns"] >= max_turns
            if done:
                st.pop("agent", None)
            trace.append("IA respondió%s" % (" y terminó" if done else ""))
            return {"messages": [reply] if reply else [], "done": done, "slots": slots, "trace": trace}
    except Exception as error:
        return {"messages": [], "done": True, "slots": {}, "trace": ["IA no disponible: %s" % error]}
