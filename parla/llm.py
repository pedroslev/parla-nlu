"""Cliente de modelos de lenguaje, solo stdlib: Ollama (/api/chat, local, por defecto) o cualquier servidor
compatible con OpenAI ({url}/chat/completions): vLLM, llama.cpp, LM Studio, LocalAI, OpenAI, Azure OpenAI, Groq,
OpenRouter. La API key sale de las Claves del agente (vault, «api_key_secret»): nunca del JSON del agente."""
import json
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

from . import vault

DEFAULTS = {"enabled": False, "provider": "ollama", "url": "http://127.0.0.1:11434", "model": "qwen2.5:0.5b",
            "temperature": 0.2, "generative_fallback": True, "rescue_intents": True, "use_knowledge": True, "persona": ""}
RECOMMENDED = [{"name": "qwen2.5:0.5b", "size": 400_000_000, "note": "El más liviano. Rápido en cualquier compu."},
               {"name": "qwen3:0.6b", "size": 520_000_000, "note": "Muy liviano, un poco más listo."},
               {"name": "gemma3:1b", "size": 820_000_000, "note": "Liviano, buen español."},
               {"name": "llama3.2:1b", "size": 1_300_000_000, "note": "Liviano, buen seguidor de instrucciones."},
               {"name": "qwen2.5:1.5b", "size": 990_000_000, "note": "Más preciso; necesita algo más de memoria."}]
KEEP_ALIVE = "30m"   # el modelo queda cargado entre mensajes: la primera respuesta tarda más, las demás no
AZURE_API_VERSION = "2024-10-21"
HTTP_HINTS = {401: "la API key no es válida o falta: revisala en «Claves»", 403: "la API key no tiene permiso para esto",
              404: "no existe esa dirección o ese modelo", 429: "demasiados pedidos o se terminó el crédito: esperá un poco"}
_progress, _lock = {}, threading.Lock()
_no_json_mode = set()   # URLs que rechazaron response_format (400): ahí el JSON se pide solo con el prompt


class LLMError(Exception):
    def __init__(self, message, code=None):
        super().__init__(message)
        self.code = code


def settings(agent, ai=None):
    """La config de IA del agente (o `ai`, la que manda la interfaz sin guardar), con la API key sacada del vault."""
    ai = (agent or {}).get("ai") if ai is None else ai
    out = dict(DEFAULTS, **{k: v for k, v in (ai if isinstance(ai, dict) else {}).items() if v is not None})
    out.pop("api_key", None)                    # nunca desde el JSON ni desde la interfaz: solo del vault
    name = str(out.get("api_key_secret") or "")
    if name and (agent or {}).get("id"):
        out["api_key"] = vault.values(agent["id"]).get(vault._normal(name))
    return out


def _cfg(cfg):
    out = dict(DEFAULTS, **{k: v for k, v in (cfg or {}).items() if v is not None})
    out["url"] = str(out["url"] or DEFAULTS["url"]).strip().rstrip("/")
    if out["provider"] == "openai" and not urllib.parse.urlsplit(out["url"]).path:
        out["url"] += "/v1"                     # «http://127.0.0.1:1234» (LM Studio) = «…:1234/v1»
    out["azure"] = bool(out.get("azure")) or ".openai.azure.com" in out["url"]
    return out


def is_local(url):
    """True si la dirección es de esta compu o de la red privada: la charla no sale a un proveedor de afuera."""
    host = urllib.parse.urlsplit(str(url)).hostname or ""
    return host in ("localhost", "host.docker.internal", "::1") or host.endswith(".local") or bool(
        re.fullmatch(r"127\.[\d.]+|10\.[\d.]+|192\.168\.[\d.]+|172\.(1[6-9]|2\d|3[01])\.[\d.]+", host))


def _mask(text, cfg):
    key = (cfg or {}).get("api_key")
    return text.replace(key, "••••") if isinstance(key, str) and len(key) >= 4 else text


def _request(url, body=None, timeout=10, cfg=None):
    headers = {"Content-Type": "application/json"}
    if cfg and cfg["provider"] == "openai":
        if cfg.get("api_key"):
            headers.update({"api-key": cfg["api_key"]} if cfg["azure"] else {"Authorization": "Bearer " + cfg["api_key"]})
        if cfg["azure"]:
            url += ("&" if "?" in url else "?") + "api-version=" + urllib.parse.quote(str(cfg.get("api_version") or AZURE_API_VERSION))
    req = urllib.request.Request(url, data=json.dumps(body).encode() if body is not None else None, headers=headers)
    try:
        return urllib.request.urlopen(req, timeout=timeout)
    except urllib.error.HTTPError as error:
        detail = error.read().decode(errors="replace")[:300]
        try:
            detail = json.loads(detail).get("error") or detail
            if isinstance(detail, dict):
                detail = detail.get("message") or json.dumps(detail)
        except (ValueError, AttributeError):
            pass
        if error.code in (401, 403):
            detail = ""                          # el proveedor suele repetir parte de la clave: no se muestra
        hint = HTTP_HINTS.get(error.code) or ("el servidor falló" if error.code >= 500 else "")
        text = "el servidor respondió %s%s%s" % (error.code, " (" + hint + ")" if hint else "", ": %s" % detail if detail else "")
        raise LLMError(_mask(text, cfg), error.code) from None
    except (urllib.error.URLError, OSError) as error:   # incluye conexión rechazada y timeouts
        reason = getattr(error, "reason", error)
        text = "tardó más de %s s en contestar" % timeout if isinstance(reason, TimeoutError) else str(reason)
        raise LLMError(_mask(text, cfg)) from None


def _json(url, body=None, timeout=10, cfg=None):
    with _request(url, body, timeout, cfg) as r:
        try:
            return json.loads(r.read().decode())
        except OSError:                          # se cortó o tardó demasiado a mitad de la respuesta
            raise LLMError("tardó más de %s s en contestar" % timeout) from None
        except ValueError:
            raise LLMError("el servidor no devolvió JSON") from None


def _hint(cfg, error):
    if cfg["provider"] == "ollama":
        if "refused" in error.lower() or "rechaz" in error.lower():
            return ("No encuentro Ollama en esta compu. Si no lo tenés, instalalo desde ollama.com (es gratis y corre "
                    "todo acá, sin internet). Si ya lo tenés, abrilo y probá de nuevo.")
        return "Ollama no respondió. Revisá que esté abierto y que la dirección sea %s." % DEFAULTS["url"]
    return "No pude hablar con %s. Revisá la dirección, la API key y que el servidor esté prendido." % cfg["url"]


def status(cfg):
    """{ok, models: [{name, size}], recommended, model_ready, local, error, hint}. Con cfg["prompt"] además prueba
    el modelo: {reply, ms}. Si un servidor compatible con OpenAI no lista modelos: models_unknown (hay que probar)."""
    cfg = _cfg(cfg)
    out = {"ok": False, "models": [], "recommended": RECOMMENDED, "provider": cfg["provider"], "model": cfg["model"],
           "model_ready": False, "local": is_local(cfg["url"]), "error": None, "hint": None}
    try:
        if cfg["provider"] == "openai":
            data = _json(cfg["url"] + "/models", timeout=4, cfg=cfg).get("data") or []
            out["models"] = [{"name": m.get("id"), "size": None} for m in data if isinstance(m, dict)]
        else:
            out["models"] = [{"name": m.get("name"), "size": m.get("size")} for m in _json(cfg["url"] + "/api/tags", timeout=4).get("models") or []]
    except LLMError as error:
        if not (cfg["provider"] == "openai" and error.code in (404, 405, 501)):
            out.update(error=str(error), hint=_hint(cfg, str(error)))
            return out
        out["models_unknown"] = True             # no implementa /models: no se sabe hasta probar
    names = {m["name"] for m in out["models"]}
    out["ok"] = True
    out["model_ready"] = cfg["model"] in names or cfg["model"] + ":latest" in names or (cfg["provider"] == "openai" and not names)
    if not out["model_ready"]:
        out["hint"] = ("El servidor no ofrece «%s». Elegí uno de los que ofrece." if cfg["provider"] == "openai" else
                       "El modelo «%s» todavía no está en esta compu. Tocá «Descargar».") % cfg["model"]
    elif cfg.get("prompt"):
        started = time.time()
        try:
            out["reply"] = chat(cfg, [{"role": "user", "content": str(cfg["prompt"])[:500]}], max_tokens=120)
        except LLMError as error:
            out.update(ok=False, error=str(error), hint="El modelo no pudo contestar: %s" % error)
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
        return {"ok": False, "error": "La descarga automática es solo para Ollama. En los otros servidores el modelo se carga ahí."}
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


def _openai(cfg, messages, schema, timeout, max_tokens, temperature):
    if schema:      # json_object + el esquema en el prompt: lo aceptan casi todos (json_schema strict es más exigente)
        messages = [{"role": "system", "content": "Respondé solo con un objeto JSON que cumpla este esquema: " +
                     json.dumps(schema, ensure_ascii=False)}] + list(messages)
    body = {"model": cfg["model"], "messages": messages, "temperature": temperature, "max_tokens": max_tokens, "stream": False}
    url = cfg["url"] + "/chat/completions"
    if schema and url not in _no_json_mode:
        try:
            data = _json(url, dict(body, response_format={"type": "json_object"}), timeout, cfg)
        except LLMError as error:
            if error.code != 400:
                raise
            data = _json(url, body, timeout, cfg)     # no acepta response_format: JSON solo con el prompt
            _no_json_mode.add(url)
    else:
        data = _json(url, body, timeout, cfg)
    text = ((data.get("choices") or [{}])[0].get("message") or {}).get("content") or ""
    if schema:                                        # sin modo JSON, algunos lo envuelven en ```json … ```
        found = re.search(r"\{.*\}", text, re.S)
        text = found.group(0) if found else text
    return text


def chat(cfg, messages, schema=None, timeout=45, max_tokens=300):
    """Texto de la respuesta; con `schema` (JSON schema) pide salida estructurada y devuelve el dict.
    Lanza LLMError si el servidor no está, tarda más de `timeout` segundos o devuelve algo inválido."""
    cfg = _cfg(cfg)
    temperature = float(cfg.get("temperature") or 0)
    if cfg["provider"] == "openai":
        text = _openai(cfg, messages, schema, timeout, max_tokens, temperature)
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
