"""Cliente de modelos de lenguaje LOCALES, solo stdlib: Ollama (/api/chat) o un servidor compatible con OpenAI
que corra en esta compu (llama.cpp server, LM Studio: /v1/chat/completions). Nada de nubes."""
import json
import threading
import time
import urllib.error
import urllib.request

DEFAULTS = {"enabled": False, "provider": "ollama", "url": "http://127.0.0.1:11434", "model": "qwen2.5:0.5b",
            "temperature": 0.2, "generative_fallback": True, "rescue_intents": True, "use_knowledge": True, "persona": ""}
RECOMMENDED = [{"name": "qwen2.5:0.5b", "size": 400_000_000, "note": "El más liviano. Rápido en cualquier compu."},
               {"name": "qwen3:0.6b", "size": 520_000_000, "note": "Muy liviano, un poco más listo."},
               {"name": "gemma3:1b", "size": 820_000_000, "note": "Liviano, buen español."},
               {"name": "llama3.2:1b", "size": 1_300_000_000, "note": "Liviano, buen seguidor de instrucciones."},
               {"name": "qwen2.5:1.5b", "size": 990_000_000, "note": "Más preciso; necesita algo más de memoria."}]
KEEP_ALIVE = "30m"   # el modelo queda cargado entre mensajes: la primera respuesta tarda más, las demás no
_progress, _lock = {}, threading.Lock()


class LLMError(Exception):
    pass


def settings(agent):
    ai = (agent or {}).get("ai")
    return dict(DEFAULTS, **{k: v for k, v in (ai if isinstance(ai, dict) else {}).items() if v is not None})


def _cfg(cfg):
    out = dict(DEFAULTS, **{k: v for k, v in (cfg or {}).items() if v is not None})
    out["url"] = str(out["url"] or DEFAULTS["url"]).strip().rstrip("/")
    if out["provider"] == "openai" and out["url"].endswith("/v1"):
        out["url"] = out["url"][:-3]
    return out


def _request(url, body=None, timeout=10):
    req = urllib.request.Request(url, data=json.dumps(body).encode() if body is not None else None,
                                 headers={"Content-Type": "application/json"})
    try:
        return urllib.request.urlopen(req, timeout=timeout)
    except urllib.error.HTTPError as error:
        detail = error.read().decode(errors="replace")[:300]
        try:
            detail = json.loads(detail).get("error") or detail
        except ValueError:
            pass
        raise LLMError("el servidor respondió %s: %s" % (error.code, detail if isinstance(detail, str) else json.dumps(detail)))
    except (urllib.error.URLError, OSError) as error:   # incluye conexión rechazada y timeouts
        raise LLMError(str(getattr(error, "reason", error)))


def _json(url, body=None, timeout=10):
    with _request(url, body, timeout) as r:
        return json.loads(r.read().decode())


def _hint(cfg, error):
    if cfg["provider"] == "ollama":
        if "refused" in error.lower() or "rechaz" in error.lower():
            return ("No encuentro Ollama en esta compu. Si no lo tenés, instalalo desde ollama.com (es gratis y corre "
                    "todo acá, sin internet). Si ya lo tenés, abrilo y probá de nuevo.")
        return "Ollama no respondió. Revisá que esté abierto y que la dirección sea " + DEFAULTS["url"] + "."
    return "No pude hablar con el servidor de " + cfg["url"] + ". Revisá que esté prendido (LM Studio o llama.cpp) y la dirección."


def status(cfg):
    """{ok, models: [{name, size}], recommended, model_ready, error, hint}. Con cfg["prompt"] además prueba el
    modelo: {reply, ms}."""
    cfg = _cfg(cfg)
    out = {"ok": False, "models": [], "recommended": RECOMMENDED, "provider": cfg["provider"], "model": cfg["model"],
           "model_ready": False, "error": None, "hint": None}
    try:
        if cfg["provider"] == "openai":
            out["models"] = [{"name": m.get("id"), "size": None} for m in _json(cfg["url"] + "/v1/models", timeout=4).get("data") or []]
        else:
            out["models"] = [{"name": m.get("name"), "size": m.get("size")} for m in _json(cfg["url"] + "/api/tags", timeout=4).get("models") or []]
    except LLMError as error:
        out.update(error=str(error), hint=_hint(cfg, str(error)))
        return out
    names = {m["name"] for m in out["models"]}
    out["ok"] = True
    out["model_ready"] = cfg["model"] in names or cfg["model"] + ":latest" in names or cfg["provider"] == "openai"
    if not out["model_ready"]:
        out["hint"] = "El modelo «%s» todavía no está en esta compu. Tocá «Descargar»." % cfg["model"]
    elif cfg.get("prompt"):
        started = time.time()
        try:
            out["reply"] = chat(cfg, [{"role": "user", "content": str(cfg["prompt"])[:500]}], max_tokens=120)
        except LLMError as error:
            out.update(ok=False, error=str(error), hint="El modelo no pudo contestar: " + str(error))
        out["ms"] = int((time.time() - started) * 1000)
    return out


def _pull(cfg, model):
    state = _progress[model]
    try:
        with _request(cfg["url"] + "/api/pull", {"model": model, "stream": True}, timeout=60) as r:
            for line in r:
                if not line.strip():
                    continue
                event = json.loads(line)
                with _lock:
                    if event.get("error"):
                        state["error"] = event["error"]
                    state["status"] = event.get("status") or state["status"]
                    if event.get("total"):
                        state["total"], state["completed"] = event["total"], event.get("completed") or 0
        with _lock:
            state["status"] = "error" if state["error"] else "listo"
    except (LLMError, ValueError, OSError) as error:
        with _lock:
            state.update(error=str(error), status="error")
    finally:
        with _lock:
            state["done"] = True


def pull(cfg, model):
    """Descarga un modelo de Ollama en segundo plano; el avance se lee con pull_progress()."""
    cfg = _cfg(cfg)
    model = (model or cfg["model"]).strip()
    if cfg["provider"] != "ollama":
        return {"ok": False, "error": "La descarga automática es solo para Ollama. En LM Studio bajá el modelo desde su ventana."}
    if not model:
        return {"ok": False, "error": "Falta el nombre del modelo."}
    with _lock:
        if model in _progress and not _progress[model]["done"]:
            return {"ok": True, "started": False, "model": model}
        _progress[model] = {"status": "empezando", "completed": 0, "total": 0, "done": False, "error": None}
    threading.Thread(target=_pull, args=(cfg, model), daemon=True).start()
    return {"ok": True, "started": True, "model": model}


def pull_progress():
    with _lock:
        return {k: dict(v) for k, v in _progress.items()}


def chat(cfg, messages, schema=None, timeout=45, max_tokens=300):
    """Texto de la respuesta; con `schema` (JSON schema) pide salida estructurada y devuelve el dict.
    Lanza LLMError si el servidor no está, tarda más de `timeout` segundos o devuelve algo inválido."""
    cfg = _cfg(cfg)
    temperature = float(cfg.get("temperature") or 0)
    if cfg["provider"] == "openai":
        body = {"model": cfg["model"], "messages": messages, "temperature": temperature, "max_tokens": max_tokens, "stream": False}
        if schema:
            body["response_format"] = {"type": "json_schema", "json_schema": {"name": "respuesta", "schema": schema, "strict": True}}
        data = _json(cfg["url"] + "/v1/chat/completions", body, timeout)
        text = ((data.get("choices") or [{}])[0].get("message") or {}).get("content") or ""
    else:
        body = {"model": cfg["model"], "messages": messages, "stream": False, "keep_alive": KEEP_ALIVE,
                "options": {"temperature": temperature, "num_predict": max_tokens, "num_ctx": 4096}}
        if schema:
            body["format"] = schema
        data = _json(cfg["url"] + "/api/chat", body, timeout)
        text = (data.get("message") or {}).get("content") or ""
    if not schema:
        return text.strip()
    try:
        out = json.loads(text)
    except ValueError:
        raise LLMError("el modelo no devolvió JSON válido")
    if not isinstance(out, dict):
        raise LLMError("el modelo no devolvió un objeto")
    return out
