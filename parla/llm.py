"""Cliente de modelos de lenguaje: Ollama (/api/chat, local, por defecto), cualquier servidor compatible con OpenAI
({url}/chat/completions: OpenAI, vLLM, llama.cpp, LM Studio, LocalAI, Azure OpenAI, Groq, OpenRouter), Anthropic
(Claude, con el SDK oficial «anthropic», opcional) y Google Gemini (generateContent por REST). Una sola entrada: chat().
La API key sale de las Claves del agente (vault, «api_key_secret»): nunca del JSON del agente, y se tapa en los errores."""
import json
import os
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

from . import telemetry, vault

# Proveedores: ollama (local, por defecto); openai = OpenAI o cualquier servidor compatible con «url» (así venían los
# agentes viejos); openai_compatible = lo mismo con otro nombre; anthropic (Claude, SDK oficial, opcional) y gemini (REST).
PROVIDERS = ("ollama", "openai", "openai_compatible", "anthropic", "gemini")
URLS = {"ollama": "http://127.0.0.1:11434", "openai": "https://api.openai.com/v1", "openai_compatible": "http://127.0.0.1:1234/v1",
        "anthropic": "https://api.anthropic.com", "gemini": "https://generativelanguage.googleapis.com"}
MODELS = {"ollama": "qwen2.5:0.5b", "openai": "gpt-6-luna", "openai_compatible": "", "anthropic": "claude-opus-5-5",
          "gemini": "gemini-3.8-flash"}
SUGGESTED = {"openai": ["gpt-6-luna", "gpt-6.1-terra", "gpt-6.2-sol"],
             "anthropic": ["claude-opus-5-5", "claude-sonnet-5-5", "claude-haiku-5-5"],
             "gemini": ["gemini-3.8-flash", "gemini-3.5-flash-lite", "gemini-3.1-pro-preview"]}
SECRETS = {"openai": "OPENAI_API_KEY", "anthropic": "ANTHROPIC_API_KEY", "gemini": "GEMINI_API_KEY"}   # nombre si no dicen otro
DEFAULTS = {"enabled": False, "provider": "ollama", "temperature": 0.2, "generative_fallback": True, "rescue_intents": True,
            "use_knowledge": True, "persona": ""}
RECOMMENDED = [{"name": "qwen2.5:0.5b", "size": 400_000_000, "note": "El más liviano. Rápido en cualquier compu."},
               {"name": "qwen3:0.6b", "size": 520_000_000, "note": "Muy liviano, un poco más listo."},
               {"name": "gemma3:1b", "size": 820_000_000, "note": "Liviano, buen español."},
               {"name": "llama3.2:1b", "size": 1_300_000_000, "note": "Liviano, buen seguidor de instrucciones."},
               {"name": "qwen2.5:1.5b", "size": 990_000_000, "note": "Más preciso; necesita algo más de memoria."}]
KEEP_ALIVE = "30m"   # el modelo queda cargado entre mensajes: la primera respuesta tarda más, las demás no
AZURE_API_VERSION = "2024-10-21"
HTTP_HINTS = {401: "la API key no es válida o falta: revisala en «Claves»", 403: "la API key no tiene permiso para esto",
              404: "no existe esa dirección o ese modelo", 429: "demasiados pedidos o se terminó el crédito: esperá un poco"}
MIN_TOKENS = 2048    # Claude y Gemini piensan antes de contestar y eso cuenta en max_tokens: con 20 no llegan a responder
_progress, _lock = {}, threading.Lock()
_no_json_mode = set()   # URLs que rechazaron response_format (400): ahí el JSON se pide solo con el prompt


class LLMError(Exception):
    def __init__(self, message, code=None):
        super().__init__(message)
        self.code = code


def base_url(provider):
    """Anthropic y Gemini van siempre a su dirección fija; PARLA_ANTHROPIC_BASE_URL / PARLA_GEMINI_BASE_URL las
    cambian (pruebas con servidores falsos, o un proxy propio)."""
    return (os.environ.get("PARLA_%s_BASE_URL" % provider.upper()) or URLS[provider]).rstrip("/")


def _fill(out):
    """Completa url, modelo y nombre de la clave según el proveedor (sin pisar lo que ya trae)."""
    provider = out["provider"] if out.get("provider") in PROVIDERS else "ollama"
    out["provider"] = provider
    out["url"] = base_url(provider) if provider in ("anthropic", "gemini") else str(out.get("url") or URLS[provider]).strip().rstrip("/")
    out["model"] = str(out.get("model") or MODELS[provider]).strip()
    if not out.get("api_key_secret") and provider in SECRETS and (provider != "openai" or out["url"] == URLS["openai"]):
        out["api_key_secret"] = SECRETS[provider]
    return out


def settings(agent, ai=None):
    """La config de IA del agente (o `ai`, la que manda la interfaz sin guardar), con la API key sacada del vault."""
    ai = (agent or {}).get("ai") if ai is None else ai
    out = _fill(dict(DEFAULTS, **{k: v for k, v in (ai if isinstance(ai, dict) else {}).items() if v is not None}))
    out.pop("api_key", None)                    # nunca desde el JSON ni desde la interfaz: solo del vault
    name = str(out.get("api_key_secret") or "")
    if name and (agent or {}).get("id"):
        out["api_key"] = vault.values(agent["id"]).get(vault._normal(name))
    return out


def _cfg(cfg):
    out = _fill(dict(DEFAULTS, **{k: v for k, v in (cfg or {}).items() if v is not None}))
    if out["provider"] in ("openai", "openai_compatible") and not urllib.parse.urlsplit(out["url"]).path:
        out["url"] += "/v1"                     # «http://127.0.0.1:1234» (LM Studio) = «…:1234/v1»
    out["azure"] = bool(out.get("azure")) or ".openai.azure.com" in out["url"]
    out["compatible"] = out["provider"] in ("openai", "openai_compatible")
    return out


def is_local(url):
    """True si la dirección es de esta compu o de la red privada: la charla no sale a un proveedor de afuera."""
    host = urllib.parse.urlsplit(str(url)).hostname or ""
    return host in ("localhost", "host.docker.internal", "::1") or host.endswith(".local") or bool(
        re.fullmatch(r"127\.[\d.]+|10\.[\d.]+|192\.168\.[\d.]+|172\.(1[6-9]|2\d|3[01])\.[\d.]+", host))


def mask(text, *secrets):
    """Tapa cada clave (y su versión en URL) en un texto: algunos proveedores repiten la key en el error."""
    text = str(text)
    for key in secrets:
        if isinstance(key, str) and len(key) >= 4:
            text = text.replace(key, "••••").replace(urllib.parse.quote(key, safe=""), "••••")
    return text


def _mask(text, cfg):
    return mask(text, (cfg or {}).get("api_key"))


def fetch(url, data=None, headers=None, timeout=10, secret=None, method=None):
    """Un pedido HTTP con el error ya armado para la persona (LLMError con el código): lo usan la IA y la voz.
    `secret` es la clave que se tapa en cualquier mensaje. Devuelve la respuesta abierta (usar con `with`)."""
    req = urllib.request.Request(url, data=data, headers=headers or {}, method=method)
    try:
        return urllib.request.urlopen(req, timeout=timeout)
    except urllib.error.HTTPError as error:
        detail = error.read().decode(errors="replace")[:300]
        try:
            detail = json.loads(detail)
            detail = detail.get("error") or detail.get("detail") or detail.get("err_msg") or detail
            if isinstance(detail, dict):
                detail = detail.get("message") or json.dumps(detail)
        except (ValueError, AttributeError):
            pass
        if error.code in (401, 403):
            detail = ""                          # el proveedor suele repetir parte de la clave: no se muestra
        hint = HTTP_HINTS.get(error.code) or ("el servidor falló" if error.code >= 500 else "")
        text = "el servidor respondió %s%s%s" % (error.code, " (" + hint + ")" if hint else "", ": %s" % detail if detail else "")
        raise LLMError(mask(text, secret), error.code) from None
    except (urllib.error.URLError, OSError) as error:   # incluye conexión rechazada y timeouts
        reason = getattr(error, "reason", error)
        text = "tardó más de %s s en contestar" % timeout if isinstance(reason, TimeoutError) else str(reason)
        raise LLMError(mask(text, secret)) from None


def read_json(response, timeout=10):
    with response as r:
        try:
            return json.loads(r.read().decode())
        except OSError:                          # se cortó o tardó demasiado a mitad de la respuesta
            raise LLMError("tardó más de %s s en contestar" % timeout) from None
        except ValueError:
            raise LLMError("el servidor no devolvió JSON") from None


def _request(url, body=None, timeout=10, cfg=None):
    headers = {"Content-Type": "application/json"}
    if cfg and cfg["provider"] == "gemini":
        headers["x-goog-api-key"] = cfg.get("api_key") or ""
    elif cfg and cfg.get("compatible"):
        if cfg.get("api_key"):
            headers.update({"api-key": cfg["api_key"]} if cfg["azure"] else {"Authorization": "Bearer " + cfg["api_key"]})
        if cfg["azure"]:
            url += ("&" if "?" in url else "?") + "api-version=" + urllib.parse.quote(str(cfg.get("api_version") or AZURE_API_VERSION))
    return fetch(url, json.dumps(body).encode() if body is not None else None, headers, timeout, (cfg or {}).get("api_key"))


def _json(url, body=None, timeout=10, cfg=None):
    return read_json(_request(url, body, timeout, cfg), timeout)


def _hint(cfg, error):
    if cfg["provider"] == "ollama":
        if "refused" in error.lower() or "rechaz" in error.lower():
            return ("No encuentro Ollama en esta compu. Si no lo tenés, instalalo desde ollama.com (es gratis y corre "
                    "todo acá, sin internet). Si ya lo tenés, abrilo y probá de nuevo.")
        return "Ollama no respondió. Revisá que esté abierto y que la dirección sea %s." % URLS["ollama"]
    if cfg["provider"] in ("anthropic", "gemini"):
        return "No pude hablar con %s. Revisá la API key en «Claves» (%s) y la conexión a internet." % (
            "Anthropic" if cfg["provider"] == "anthropic" else "Google Gemini", cfg.get("api_key_secret") or "")
    return "No pude hablar con %s. Revisá la dirección, la API key y que el servidor esté prendido." % cfg["url"]


def _models(cfg):
    """[{name, size}] que ofrece el proveedor (lanza LLMError)."""
    if cfg["provider"] == "anthropic":
        client = _claude(cfg, 4)
        try:
            return [{"name": m.id, "size": None} for m in client.models.list(limit=100).data]
        except Exception as error:  # noqa: BLE001 - los errores del SDK pasan a LLMError con la key tapada
            raise _claude_error(error, cfg, 4) from None
    if cfg["provider"] == "gemini":
        data = _json(cfg["url"] + "/v1beta/models?pageSize=1000", timeout=4, cfg=cfg).get("models") or []
        return [{"name": str(m.get("name") or "").removeprefix("models/"), "size": None} for m in data if isinstance(m, dict)]
    if cfg["compatible"]:
        data = _json(cfg["url"] + "/models", timeout=4, cfg=cfg).get("data") or []
        return [{"name": m.get("id"), "size": None} for m in data if isinstance(m, dict)]
    return [{"name": m.get("name"), "size": m.get("size")} for m in _json(cfg["url"] + "/api/tags", timeout=4).get("models") or []]


def status(cfg):
    """{ok, models: [{name, size}], recommended, suggested, model_ready, local, error, hint}. Con cfg["prompt"] además
    prueba el modelo: {reply, ms}. Si un servidor compatible con OpenAI no lista modelos: models_unknown (hay que probar)."""
    cfg = _cfg(cfg)
    out = {"ok": False, "models": [], "recommended": RECOMMENDED, "suggested": SUGGESTED.get(cfg["provider"], []),
           "provider": cfg["provider"], "model": cfg["model"], "model_ready": False,
           "local": cfg["provider"] not in ("anthropic", "gemini") and is_local(cfg["url"]), "error": None, "hint": None}
    remote = cfg["provider"] != "ollama"
    if cfg["provider"] in ("anthropic", "gemini") and not cfg.get("api_key"):
        out.update(error="falta la API key: guardala en «Claves» como %s" % cfg.get("api_key_secret"), hint=_hint(cfg, ""))
        return out
    try:
        out["models"] = _models(cfg)
    except LLMError as error:
        if not (cfg["compatible"] and error.code in (404, 405, 501)):
            out.update(error=str(error), hint=_hint(cfg, str(error)))
            return out
        out["models_unknown"] = True             # no implementa /models: no se sabe hasta probar
    names = {m["name"] for m in out["models"]}
    out["ok"] = True
    out["model_ready"] = cfg["model"] in names or cfg["model"] + ":latest" in names or (remote and not names)
    if not out["model_ready"]:
        out["hint"] = ("El servidor no ofrece «%s». Elegí uno de los que ofrece." if remote else
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


def _schema_prompt(schema):
    return {"role": "system", "content": "Respondé solo con un objeto JSON que cumpla este esquema: " + json.dumps(schema, ensure_ascii=False)}


def _first_json(text):
    """Sin modo JSON, algunos modelos lo envuelven en ```json … ``` o le ponen texto alrededor."""
    found = re.search(r"\{.*\}", text, re.S)
    return found.group(0) if found else text


def _openai(cfg, messages, schema, timeout, max_tokens, temperature, sink=None):
    if schema:      # json_object + el esquema en el prompt: lo aceptan casi todos (json_schema strict es más exigente)
        messages = [_schema_prompt(schema)] + list(messages)
    body = {"model": cfg["model"], "messages": messages, "temperature": temperature, "max_tokens": max_tokens, "stream": False}
    url = cfg["url"] + "/chat/completions"
    if sink:        # streaming (SSE): data: {"choices": [{"delta": {"content": "..."}}]} … data: [DONE]
        text = ""
        with _request(url, dict(body, stream=True), timeout, cfg) as r:
            for data in _sse(r, timeout):
                piece = ((data.get("choices") or [{}])[0].get("delta") or {}).get("content") or ""
                text += piece
                sink(piece)
                usage = data.get("usage") or {}
                if usage:
                    telemetry.tokens(usage.get("prompt_tokens"), usage.get("completion_tokens"))
        return _first_json(text) if schema else text
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
    usage = data.get("usage") or {}
    telemetry.tokens(usage.get("prompt_tokens"), usage.get("completion_tokens"))
    text = ((data.get("choices") or [{}])[0].get("message") or {}).get("content") or ""
    return _first_json(text) if schema else text


# ---------- Anthropic (Claude): SDK oficial, opcional (requirements-providers.txt) ----------

FALLBACK_MODELS = ("claude-opus-5-5", "claude-sonnet-5-5", "claude-fable-5-2", "claude-fable-5-1", "claude-opus-5")
FALLBACK_BETA = "server-side-fallback-2026-07-01"


def _claude(cfg, timeout):
    try:
        import anthropic
    except ImportError:
        raise LLMError("Para usar Claude falta instalar el SDK de Anthropic: pip install -r requirements-providers.txt") from None
    if not cfg.get("api_key"):
        raise LLMError("falta la API key: guardala en «Claves» como %s" % cfg.get("api_key_secret"), 401)
    # ponytail: un reintento del SDK (429/5xx/red): en el peor caso tarda 2 × timeout; 0 si el teléfono necesita menos
    return anthropic.Anthropic(api_key=cfg["api_key"], base_url=cfg["url"], max_retries=1).with_options(timeout=timeout)


def _claude_error(error, cfg, timeout):
    """Las excepciones del SDK (de la más específica a la más general) -> LLMError con el mismo texto que el resto."""
    import anthropic
    if isinstance(error, LLMError):
        return error
    if isinstance(error, anthropic.APITimeoutError):
        return LLMError("tardó más de %s s en contestar" % timeout)
    if isinstance(error, anthropic.APIConnectionError):
        return LLMError(_mask("no pude conectar con Anthropic: %s" % error, cfg))
    if isinstance(error, anthropic.APIStatusError):
        code = error.status_code
        if isinstance(error, (anthropic.AuthenticationError, anthropic.PermissionDeniedError)):
            detail = ""
        else:
            detail = str(getattr(error, "message", "") or "")[:300]
        if isinstance(error, (anthropic.NotFoundError, anthropic.RateLimitError)) or code < 500:
            hint = HTTP_HINTS.get(code, "")
        else:
            hint = "el servidor falló"
        text = "el servidor respondió %s%s%s" % (code, " (" + hint + ")" if hint else "", ": %s" % detail if detail else "")
        return LLMError(_mask(text, cfg), code)
    return LLMError(_mask(str(error), cfg))


def _strict(schema):
    """El esquema como lo piden las salidas estructuradas de Claude (additionalProperties: false en cada objeto), o
    None si tiene objetos libres ({"type": "object"} sin propiedades, como los slots del paso de IA)."""
    if isinstance(schema, dict):
        if schema.get("type") == "object":
            if not schema.get("properties"):
                return None
            props = {k: _strict(v) for k, v in schema["properties"].items()}
            if any(v is None for v in props.values()):
                return None
            return dict(schema, properties=props, additionalProperties=False)
        return dict(schema)
    return schema


def _anthropic(cfg, messages, schema, timeout, max_tokens, sink=None):
    client = _claude(cfg, timeout)
    system = "\n\n".join(m["content"] for m in messages if m.get("role") == "system")
    turns = [{"role": m["role"], "content": m["content"]} for m in messages if m.get("role") in ("user", "assistant")]
    strict = _strict(schema) if schema else None
    if schema and not strict:
        system = (system + "\n\n" if system else "") + _schema_prompt(schema)["content"]
    # Opus 5.5 siempre piensa (thinking no se apaga): effort low = rápido para charlar. Los modelos viejos no lo aceptan.
    output = {} if re.match(r"claude-(3|haiku-4|sonnet-4-5|opus-4-[01])", cfg["model"]) else {"effort": "low"}
    if strict:
        output["format"] = {"type": "json_schema", "schema": strict}
    args = {"model": cfg["model"], "max_tokens": max(max_tokens, MIN_TOKENS), "messages": turns or [{"role": "user", "content": "."}],
            **({"output_config": output} if output else {})}
    if system:
        args["system"] = system
    try:
        if cfg["model"] in FALLBACK_MODELS:      # si un clasificador de seguridad rechaza, el servidor reintenta con otro modelo
            api, args = client.beta.messages, dict(args, betas=[FALLBACK_BETA], fallbacks="default")
        else:
            api = client.messages
        if sink:                                  # tokens a medida que llegan (WebSocket/SSE); el mensaje final igual que sin stream
            with api.stream(**args) as stream:
                for piece in stream.text_stream:
                    sink(piece)
                response = stream.get_final_message()
        else:
            response = api.create(**args)
    except Exception as error:  # noqa: BLE001
        raise _claude_error(error, cfg, timeout) from None
    usage = getattr(response, "usage", None)
    telemetry.tokens(getattr(usage, "input_tokens", None), getattr(usage, "output_tokens", None))
    if response.stop_reason == "refusal":
        raise LLMError("el modelo no quiso contestar eso (lo frenó un filtro de seguridad del proveedor)")
    if response.stop_reason == "max_tokens":
        raise LLMError("la respuesta se cortó: el modelo llegó al máximo de tokens")
    text = "".join(block.text for block in response.content if block.type == "text")
    return _first_json(text) if schema and not strict else text


# ---------- Google Gemini: generateContent por REST ----------

GEMINI_BLOCKED = ("SAFETY", "PROHIBITED_CONTENT", "BLOCKLIST", "SPII", "RECITATION")
_gemini_plain = set()   # modelos que rechazaron responseJsonSchema (400): ahí el JSON se pide solo con el prompt


def _gemini(cfg, messages, schema, timeout, max_tokens, sink=None):
    if not cfg.get("api_key"):
        raise LLMError("falta la API key: guardala en «Claves» como %s" % cfg.get("api_key_secret"), 401)
    system = "\n\n".join(m["content"] for m in messages if m.get("role") == "system")
    contents = [{"role": "model" if m["role"] == "assistant" else "user", "parts": [{"text": m["content"]}]}
                for m in messages if m.get("role") in ("user", "assistant")]
    url = "%s/v1beta/models/%s:generateContent" % (cfg["url"], urllib.parse.quote(cfg["model"], safe=".-_"))
    plain = schema and cfg["model"] in _gemini_plain
    if plain:
        system = (system + "\n\n" if system else "") + _schema_prompt(schema)["content"]
    body = {"contents": contents or [{"role": "user", "parts": [{"text": "."}]}],
            "generationConfig": {"maxOutputTokens": max(max_tokens, MIN_TOKENS)}}
    if system:
        body["systemInstruction"] = {"parts": [{"text": system}]}
    if schema and not plain:
        body["generationConfig"].update(responseMimeType="application/json", responseJsonSchema=schema)
    try:
        if sink:    # streamGenerateContent?alt=sse: cada evento es una respuesta parcial; se juntan como una sola
            data, parts = {}, []
            with _request(url.replace(":generateContent", ":streamGenerateContent") + "?alt=sse", body, timeout, cfg) as r:
                for chunk in _sse(r, timeout):
                    candidate = (chunk.get("candidates") or [{}])[0]
                    for p in (candidate.get("content") or {}).get("parts") or []:
                        if p.get("text") and not p.get("thought"):
                            parts.append({"text": p["text"]})
                            sink(p["text"])
                    data = dict(chunk, candidates=[dict(candidate, content={"parts": parts})])
        else:
            data = _json(url, body, timeout, cfg)
    except LLMError as error:
        if not (error.code == 400 and schema and not plain):
            raise
        _gemini_plain.add(cfg["model"])
        return _gemini(cfg, messages, schema, timeout, max_tokens, sink)
    usage = data.get("usageMetadata") or {}
    telemetry.tokens(usage.get("promptTokenCount"), usage.get("candidatesTokenCount"))
    if (data.get("promptFeedback") or {}).get("blockReason"):
        raise LLMError("el modelo no quiso contestar eso (lo frenó un filtro de seguridad del proveedor)")
    candidate = (data.get("candidates") or [{}])[0]
    if candidate.get("finishReason") in GEMINI_BLOCKED:
        raise LLMError("el modelo no quiso contestar eso (lo frenó un filtro de seguridad del proveedor)")
    text = "".join(p.get("text") or "" for p in (candidate.get("content") or {}).get("parts") or [] if not p.get("thought"))
    if candidate.get("finishReason") == "MAX_TOKENS" and not text:
        raise LLMError("la respuesta se cortó: el modelo llegó al máximo de tokens")
    return _first_json(text) if schema else text


def chat(cfg, messages, schema=None, timeout=45, max_tokens=300, stream=None):
    """Texto de la respuesta; con `schema` (JSON schema) pide salida estructurada y devuelve el dict. Un solo punto de
    entrada para todos los proveedores. Lanza LLMError si el servidor no está, tarda más de `timeout` segundos o
    devuelve algo inválido (los mensajes nunca muestran la API key).
    stream: True (texto) o el nombre del campo del JSON que ve la persona: si el turno tiene alguien escuchando por
    WebSocket/SSE (STREAM.sink), los tokens salen como eventos «delta» mientras llegan; el valor devuelto es el mismo."""
    cfg = _cfg(cfg)
    temperature = float(cfg.get("temperature") or 0)
    provider = cfg["provider"] if cfg["provider"] in PROVIDERS else "other"
    system = {"anthropic": "anthropic", "gemini": "gcp.gemini", "ollama": "ollama"}.get(provider, "openai")   # gen_ai semconv
    # sin los mensajes ni la respuesta: solo proveedor, modelo, límites y tokens
    with telemetry.span("chat " + str(cfg.get("model") or ""), kind="client", metric="parla_llm_request_duration_seconds",
                        labels={"provider": provider}, **{"gen_ai.operation.name": "chat", "gen_ai.system": system,
                        "gen_ai.provider.name": system, "gen_ai.request.model": cfg.get("model"),
                        "gen_ai.request.max_tokens": max_tokens, "gen_ai.request.temperature": temperature}):
        return _chat(cfg, messages, schema, timeout, max_tokens, temperature, _streamer(stream))


def _chat(cfg, messages, schema, timeout, max_tokens, temperature, sink=None):
    if cfg["provider"] == "anthropic":
        text = _anthropic(cfg, messages, schema, timeout, max_tokens, sink)
    elif cfg["provider"] == "gemini":
        text = _gemini(cfg, messages, schema, timeout, max_tokens, sink)
    elif cfg["compatible"]:
        text = _openai(cfg, messages, schema, timeout, max_tokens, temperature, sink)
    else:
        body = {"model": cfg["model"], "messages": messages, "stream": bool(sink), "keep_alive": KEEP_ALIVE,
                "options": {"temperature": temperature, "num_predict": max_tokens, "num_ctx": 4096}}
        if schema:
            body["format"] = schema
        if sink:        # Ollama: una línea JSON por pedazo, la última con done y los tokens
            text = ""
            with _request(cfg["url"] + "/api/chat", body, timeout) as r:
                for line in _lines(r, timeout):
                    data = json.loads(line)
                    piece = (data.get("message") or {}).get("content") or ""
                    text += piece
                    sink(piece)
                    if data.get("done"):
                        telemetry.tokens(data.get("prompt_eval_count"), data.get("eval_count"))
        else:
            data = _json(cfg["url"] + "/api/chat", body, timeout)
            telemetry.tokens(data.get("prompt_eval_count"), data.get("eval_count"))
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


# ---------- streaming: tokens a la persona mientras el modelo escribe ----------

STREAM = threading.local()      # .sink = función(evento) del turno en curso (server.converse la pone si alguien escucha)
_streams = [0]


def _lines(response, timeout):
    try:
        for raw in response:
            line = raw.decode("utf-8", "replace").strip()
            if line:
                yield line
    except OSError:
        raise LLMError("tardó más de %s s en contestar" % timeout) from None


def _sse(response, timeout):
    """Los «data:» de una respuesta text/event-stream, ya como JSON (sin el [DONE] final)."""
    for line in _lines(response, timeout):
        if line.startswith("data:") and line[5:].strip() != "[DONE]":
            try:
                yield json.loads(line[5:])
            except ValueError:
                continue


def visible(raw, field):
    """Lo que ya se puede mostrar de una salida a medio llegar: todo el texto (field None) o el valor del campo
    `field` de un JSON incompleto («{"text": "Hola, qu» -> «Hola, qu»)."""
    if field is None:
        return raw
    found = re.search(r'"%s"\s*:\s*"' % re.escape(field), raw)
    if not found:
        return ""
    out, s, i = [], raw[found.end():], 0
    while i < len(s) and s[i] != '"':
        if s[i] == "\\":
            if s[i + 1:i + 2] == "u":
                if i + 6 > len(s):
                    break
                try:
                    out.append(chr(int(s[i + 2:i + 6], 16)))
                except ValueError:
                    pass
                i += 6
                continue
            if i + 1 >= len(s):
                break
            out.append({"n": "\n", "t": "\t", "r": "", "b": "", "f": ""}.get(s[i + 1], s[i + 1]))
            i += 2
            continue
        out.append(s[i])
        i += 1
    return "".join(out)


def _streamer(stream):
    """El sink para el proveedor: junta lo crudo y manda {"type": "delta", "stream": n, "text"} con lo nuevo visible."""
    emit = getattr(STREAM, "sink", None)
    if not stream or not emit:
        return None
    _streams[0] += 1
    sid, field, state = _streams[0], None if stream is True else stream, {"raw": "", "shown": ""}
    STREAM.last = state
    state["id"] = sid

    def sink(piece):
        state["raw"] += piece or ""
        now = visible(state["raw"], field)
        if len(now) > len(state["shown"]) and now.startswith(state["shown"]):
            emit({"type": "delta", "stream": sid, "text": now[len(state["shown"]):]})
            state["shown"] = now
    return sink


def settle(final):
    """Después de los guardrails (que necesitan el texto entero): si lo que se mostró en vivo no es lo que queda,
    un evento «replace» con el texto final ("" = no mostrar nada). Así el leak-regex y la regla del «?» siguen valiendo."""
    state, emit = getattr(STREAM, "last", None), getattr(STREAM, "sink", None)
    STREAM.last = None
    if state and emit and state["shown"] and state["shown"].strip() != (final or "").strip():
        emit({"type": "replace", "stream": state["id"], "text": final or ""})
