"""Observabilidad sin dependencias: métricas Prometheus (GET /metrics), trazas OpenTelemetry (OTLP/HTTP JSON) y logs
de pedidos en JSON. Todo apagado por defecto; ver docs/observability.md.

    with telemetry.span("llm.chat", kind="client", metric="parla_llm_request_duration_seconds", labels={"provider": p}):
        ...
    telemetry.count("parla_turns_total", agent=aid, channel="web")

Privacidad: las métricas y los atributos de los spans llevan ids, nombres de intenciones y flujos, confianza,
duraciones y estados; nunca lo que escribe la persona, los slots ni claves. PARLA_OTEL_CONTENT=1 suma el texto
del turno a los spans, con las claves y los datos personales tapados (lo hace quien llama: server.measure).
"""
import atexit
import contextvars
import hmac
import ipaddress
import json
import os
import queue
import random
import re
import sys
import threading
import time
import urllib.parse
import urllib.request

from . import __version__

LATENCY = (0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30)
DEFS = {    # nombre -> (tipo, ayuda, buckets). La lista completa, con sus etiquetas, está en docs/observability.md
    "parla_http_requests_total": ("counter", "HTTP requests by route template, method and status.", None),
    "parla_http_request_duration_seconds": ("histogram", "HTTP request latency by route template and method.", LATENCY),
    "parla_turns_total": ("counter", "Conversation turns by agent, channel and environment.", None),
    "parla_conversations_started_total": ("counter", "Conversations started by agent and channel.", None),
    "parla_intent_outcomes_total": ("counter", "How each turn was understood (matched, answer, system, fallback, none) by agent.", None),
    "parla_nlu_duration_seconds": ("histogram", "NLU latency by stage (classify, extract).", LATENCY),
    "parla_llm_request_duration_seconds": ("histogram", "LLM calls by provider and outcome.", LATENCY),
    "parla_llm_tokens_total": ("counter", "LLM tokens by provider and type (input, output), when the provider reports them.", None),
    "parla_asr_duration_seconds": ("histogram", "Speech-to-text calls by provider and outcome.", LATENCY),
    "parla_tts_duration_seconds": ("histogram", "Text-to-speech calls by provider and outcome.", LATENCY),
    "parla_http_step_duration_seconds": ("histogram", "HTTP steps and HTTP tools by outcome (ok, http_error, unreachable, error).", LATENCY),
    "parla_function_duration_seconds": ("histogram", "Function runs by language and outcome.", LATENCY),
    "parla_knowledge_search_duration_seconds": ("histogram", "Knowledge base searches by outcome.", LATENCY),
    "parla_handoffs_total": ("counter", "Conversations handed to a person by agent and channel.", None),
    "parla_csat_score": ("histogram", "CSAT survey answers (1 to 5) by agent.", (1, 2, 3, 4, 5)),
    "parla_active_sessions": ("gauge", "Open conversations with activity in the last 30 minutes, by agent.", None),
    "parla_test_runs_total": ("counter", "Conversation test suite runs by agent and outcome.", None),
    "parla_telemetry_dropped_total": ("counter", "Spans or metric series Parla dropped (queue full, export failed, too many series).", None),
}
MAX_SERIES = 5000           # tope de series: una etiqueta descontrolada no se come la memoria
QUEUE_MAX, BATCH = 2048, 512
CHANNELS = {"web", "api", "whatsapp", "telegram", "phone", "prueba"}      # otro canal (texto libre de la API) -> «other»
KINDS = {"internal": 1, "server": 2, "client": 3}
TRACEPARENT = re.compile(r"00-([0-9a-f]{32})-([0-9a-f]{16})-([0-9a-f]{2})")

_lock = threading.Lock()    # ponytail: un lock para todas las métricas; por métrica si el scrape compite con mucho tráfico
_values, _series = {}, [0]
_current = contextvars.ContextVar("parla_span", default=None)
_queue, _wake = queue.Queue(QUEUE_MAX), threading.Event()
_exporter, _last_error = None, [0.0]
STARTED = time.time()


def _on(name):
    return os.environ.get(name, "").strip().lower() in ("1", "true", "yes", "on")


def _pairs(raw):
    """«k1=v1,k2=v2» (OTEL_EXPORTER_OTLP_HEADERS, OTEL_RESOURCE_ATTRIBUTES), con los valores url-encoded."""
    out = {}
    for item in (raw or "").split(","):
        key, _, value = item.partition("=")
        if key.strip() and value.strip():
            out[urllib.parse.unquote(key.strip())] = urllib.parse.unquote(value.strip())
    return out


def configure():
    """Lee las variables de entorno (al importar; las pruebas la vuelven a llamar)."""
    global METRICS, TOKEN, ENDPOINT, TRACING, HEADERS, SERVICE, RESOURCE, CONTENT, JSON_LOGS, INTERVAL, TIMEOUT
    env = os.environ.get
    METRICS = _on("PARLA_METRICS")
    TOKEN = env("PARLA_METRICS_TOKEN", "").strip()
    base = (env("PARLA_OTEL_ENDPOINT") or env("OTEL_EXPORTER_OTLP_ENDPOINT") or "").strip().rstrip("/")
    ENDPOINT = (base + "/v1/traces" if env("PARLA_OTEL_ENDPOINT") else "") or env("OTEL_EXPORTER_OTLP_TRACES_ENDPOINT", "").strip() \
        or (base + "/v1/traces" if base else "")
    TRACING = bool(ENDPOINT) and not _on("OTEL_SDK_DISABLED")
    HEADERS = _pairs(env("OTEL_EXPORTER_OTLP_TRACES_HEADERS") or env("OTEL_EXPORTER_OTLP_HEADERS"))
    SERVICE = env("OTEL_SERVICE_NAME", "").strip() or "parla"
    RESOURCE = dict(_pairs(env("OTEL_RESOURCE_ATTRIBUTES")), **{"service.name": SERVICE, "service.version": __version__})
    CONTENT = _on("PARLA_OTEL_CONTENT")
    JSON_LOGS = env("PARLA_LOG_FORMAT", "").strip().lower() == "json"
    INTERVAL = float(env("PARLA_OTEL_INTERVAL") or 2)                       # segundos entre envíos
    TIMEOUT = float(env("OTEL_EXPORTER_OTLP_TIMEOUT") or 5000) / 1000      # ms, como el estándar


configure()


# ---------- métricas ----------

def _key(labels):
    return tuple(sorted((k, str(v)) for k, v in labels.items()))


def _slot(name, labels, make):
    """La serie (crea si hace falta, salvo que ya haya MAX_SERIES). Con el lock tomado."""
    series = _values.setdefault(name, {})
    key = _key(labels)
    if key not in series:
        if _series[0] >= MAX_SERIES:
            dropped = _values.setdefault("parla_telemetry_dropped_total", {})
            reason = (("reason", "too_many_series"),)
            dropped[reason] = dropped.get(reason, 0) + 1
            return None, None
        _series[0] += 1
        series[key] = make()
    return series, key


def count(name, n=1, **labels):
    if not METRICS:
        return
    with _lock:
        series, key = _slot(name, labels, lambda: 0)
        if series is not None:
            series[key] += n


def observe(name, value, **labels):
    """Un valor en un histograma: [conteo por bucket..., suma, total]."""
    if not METRICS:
        return
    buckets = DEFS[name][2]
    with _lock:
        series, key = _slot(name, labels, lambda: [0] * (len(buckets) + 2))
        if series is None:
            return
        row = series[key]
        for i, edge in enumerate(buckets):
            if value <= edge:
                row[i] += 1
        row[-2] += value
        row[-1] += 1


def gauge(name, rows):
    """Reemplaza todas las series de un gauge: rows = [({etiquetas}, valor)]."""
    with _lock:
        _values[name] = {_key(labels): value for labels, value in rows}


def channel(name):
    return name if name in CHANNELS else "other"


def _num(value):
    return repr(float(value)) if isinstance(value, float) and value != int(value) else str(int(value))


def _labels(key, extra=()):
    pairs = list(key) + list(extra)
    if not pairs:
        return ""
    esc = lambda v: v.replace("\\", "\\\\").replace("\"", "\\\"").replace("\n", "\\n")
    return "{" + ",".join('%s="%s"' % (k, esc(v)) for k, v in pairs) + "}"


def render():
    """El texto de /metrics (formato de exposición 0.0.4)."""
    lines = ["# HELP parla_info Parla version.", "# TYPE parla_info gauge", 'parla_info{version="%s"} 1' % __version__,
             "# HELP process_start_time_seconds Start time of the process since the epoch.", "# TYPE process_start_time_seconds gauge",
             "process_start_time_seconds %d" % STARTED]
    with _lock:
        for name, (kind, text, buckets) in DEFS.items():
            lines += ["# HELP %s %s" % (name, text), "# TYPE %s %s" % (name, kind)]
            for key, value in sorted(_values.get(name, {}).items()):
                if kind != "histogram":
                    lines.append("%s%s %s" % (name, _labels(key), _num(value)))
                    continue
                for edge, hits in zip(list(buckets) + ["+Inf"], value[:-2] + [value[-1]]):
                    lines.append("%s_bucket%s %d" % (name, _labels(key, [("le", str(edge))]), hits))
                lines += ["%s_sum%s %s" % (name, _labels(key), _num(value[-2])), "%s_count%s %d" % (name, _labels(key), value[-1])]
    return "\n".join(lines) + "\n"


def allowed(authorization, peer, host):
    """¿Puede leer /metrics? -> 200, 401 (falta el token o no coincide) o 404 (apagado). Sin PARLA_METRICS_TOKEN, solo
    desde esta misma máquina: conexión desde loopback y Host 127.0.0.1 / localhost (un proxy de PARLA_HOSTS no alcanza:
    reenviaría el pedido de cualquiera)."""
    if not METRICS:
        return 404
    if TOKEN:
        return 200 if hmac.compare_digest((authorization or "").encode(), ("Bearer " + TOKEN).encode()) else 401
    try:
        loopback = ipaddress.ip_address(peer).is_loopback
    except ValueError:
        loopback = False
    name = re.sub(r":\d+$", "", (host or "").lower())
    return 200 if loopback and name in ("127.0.0.1", "localhost", "[::1]") else 401


_SEGMENT = re.compile(r"[a-z][a-z0-9_-]{0,30}")
_PLACEHOLDER = {"bots": "{bot}", "sessions": "{session}", "files": "{file}", "users": "{user}", "keys": "{key}",
                "versions": "{n}", "audio": "{audio}", "static": "{file}"}


def route_of(path):
    """La plantilla de la ruta (/api/agents/{id}/sessions/{session}/reply), nunca la ruta cruda: ids, nombres de bots y
    sessionId (que puede ser un teléfono) no llegan a las etiquetas."""
    parts, out = [p for p in urllib.parse.urlsplit(path).path.split("/") if p][:7], []
    if parts[:1] == ["files"]:
        return "/files/{id}/{file}"
    for i, part in enumerate(parts):
        before = parts[i - 1] if i else ""
        if before in _PLACEHOLDER:
            out.append(_PLACEHOLDER[before])
        elif re.fullmatch(r"[0-9a-f]{8}", part):
            out.append("{id}")
        elif part.isdigit():
            out.append("{n}")
        else:
            out.append(part if _SEGMENT.fullmatch(part) else "{x}")
    return "/" + "/".join(out)


# ---------- trazas ----------

class _Remote:
    """El span que mandó el que llama (traceparent): solo da los ids para continuar la traza."""
    def __init__(self, trace_id, span_id, sampled):
        self.trace_id, self.span_id, self.sampled = trace_id, span_id, sampled


class Span:
    def __init__(self, name, kind, metric, labels, parent, attrs):
        self.name, self.kind, self.metric, self.labels, self.attrs = name, kind, metric, dict(labels or {}), attrs
        self.outcome = self.seconds = None
        up = _incoming(parent) if parent is not None else _current.get()
        self.trace_id = up.trace_id if up else "%032x" % random.getrandbits(128)
        self.parent_id = up.span_id if up else None
        self.sampled = up.sampled if up else True
        self.span_id = "%016x" % random.getrandbits(64)

    def set(self, **attrs):
        self.attrs.update(attrs)
        return self

    def traceparent(self):
        return "00-%s-%s-%s" % (self.trace_id, self.span_id, "01" if self.sampled else "00")

    def __enter__(self):
        self.start = time.time_ns()
        self._t0 = time.perf_counter()
        self._token = _current.set(self)
        return self

    def __exit__(self, kind, error, tb):
        self.seconds = time.perf_counter() - self._t0
        _current.reset(self._token)
        if kind is not None:
            self.outcome = "error"
            self.attrs.setdefault("error.type", kind.__name__)       # el tipo; el mensaje puede traer datos de la persona
        self.outcome = self.outcome or "ok"
        if self.metric:
            observe(self.metric, self.seconds, **dict(self.labels, outcome=self.outcome))
        if TRACING and self.sampled:
            _enqueue(self)
        return False


class _Noop:
    """Lo que devuelve span() con todo apagado: no mide ni guarda nada."""
    outcome = seconds = None
    labels, attrs = {}, {}
    def set(self, **attrs): return self
    def traceparent(self): return None
    def __enter__(self): return self
    def __exit__(self, *exc): return False
    def __setattr__(self, name, value): pass


NOOP = _Noop()


def _incoming(header):
    """traceparent W3C -> _Remote, o None si no vino o es inválido (empieza una traza nueva)."""
    m = TRACEPARENT.fullmatch((header or "").strip().lower())
    if not m or set(m.group(1)) == {"0"} or set(m.group(2)) == {"0"}:
        return None
    return _Remote(m.group(1), m.group(2), int(m.group(3), 16) & 1 == 1)


def span(name, kind="internal", metric=None, labels=None, parent=None, **attrs):
    """Context manager de un span. parent: el encabezado traceparent de un pedido entrante (si no, el span actual).
    Con metric, al cerrar observa la duración en ese histograma con labels + outcome («ok», «error» si hubo una
    excepción, o lo que se haya puesto en .outcome). Con trazas y métricas apagadas no hace nada."""
    if not (TRACING or (METRICS and metric) or (JSON_LOGS and kind == "server")):
        return NOOP
    return Span(name, kind, metric, labels, parent, attrs)


def current():
    return _current.get()


def annotate(**attrs):
    """Suma atributos al span actual (p. ej. los tokens que devolvió el proveedor)."""
    s = _current.get()
    if s is not None:
        s.attrs.update(attrs)


def tokens(prompt=None, completion=None):
    """Uso de tokens de la llamada al modelo en curso: atributos gen_ai.usage.* y parla_llm_tokens_total."""
    s = _current.get()
    if s is None:
        return
    provider = s.labels.get("provider", "other")
    for kind, n in (("input", prompt), ("output", completion)):
        if isinstance(n, int) and n >= 0:
            s.attrs["gen_ai.usage.%s_tokens" % kind] = n
            count("parla_llm_tokens_total", n, provider=provider, type=kind)


def traceparent():
    """Para propagar la traza en los pedidos que salen (pasos HTTP). None si no hay trazas."""
    s = _current.get()
    return s.traceparent() if TRACING and s is not None else None


def _value(v):
    if isinstance(v, bool):
        return {"boolValue": v}
    if isinstance(v, int):
        return {"intValue": str(v)}
    if isinstance(v, float):
        return {"doubleValue": v}
    return {"stringValue": str(v)}


def _attrs(d):
    return [{"key": k, "value": _value(v)} for k, v in d.items() if v is not None]


def _enqueue(s):
    item = {"traceId": s.trace_id, "spanId": s.span_id, "name": s.name, "kind": KINDS.get(s.kind, 1),
            "startTimeUnixNano": str(s.start), "endTimeUnixNano": str(s.start + int(s.seconds * 1e9)),
            "attributes": _attrs(s.attrs), "status": {"code": 2 if s.outcome != "ok" else 1}}
    if s.parent_id:
        item["parentSpanId"] = s.parent_id
    if s.outcome != "ok":
        item["status"]["message"] = s.outcome
    _start()
    try:
        _queue.put_nowait(item)         # nunca espera: si el colector no da abasto, se pierde el span, no el pedido
    except queue.Full:
        count("parla_telemetry_dropped_total", reason="queue_full")
    if _queue.qsize() >= BATCH:
        _wake.set()


def _start():
    global _exporter
    if _exporter is None:
        with _lock:
            if _exporter is None:
                _exporter = threading.Thread(target=_loop, name="parla-otlp", daemon=True)
                _exporter.start()


def payload(spans):
    return {"resourceSpans": [{"resource": {"attributes": _attrs(RESOURCE)},
                               "scopeSpans": [{"scope": {"name": "parla", "version": __version__}, "spans": spans}]}]}


def _send(spans):
    body = json.dumps(payload(spans)).encode()
    request = urllib.request.Request(ENDPOINT, data=body, method="POST",
                                     headers=dict(HEADERS, **{"Content-Type": "application/json"}))
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
            response.read()
    except Exception as error:  # noqa: BLE001 - el colector caído no puede afectar a Parla: se pierde el lote
        count("parla_telemetry_dropped_total", len(spans), reason="export_failed")
        if time.time() - _last_error[0] > 60:      # un aviso por minuto, no uno por lote
            _last_error[0] = time.time()
            print("trazas: no pude mandar %d spans a %s: %s" % (len(spans), ENDPOINT, error), file=sys.stderr, flush=True)


def _loop():
    while True:
        _wake.wait(INTERVAL)
        _wake.clear()
        while True:
            batch = []
            while len(batch) < BATCH:
                try:
                    batch.append(_queue.get_nowait())
                except queue.Empty:
                    break
            if not batch:
                break
            _send(batch)
            for _ in batch:
                _queue.task_done()


def flush(timeout=5):
    """Manda lo que haya en la cola ya (al salir y en las pruebas). True si se vació a tiempo."""
    if _exporter is None:
        return True
    _wake.set()
    deadline = time.time() + timeout
    while _queue.unfinished_tasks and time.time() < deadline:
        time.sleep(0.02)
    return not _queue.unfinished_tasks


atexit.register(flush, 2)


# ---------- logs ----------

def log_request(method, route, status, s):
    """PARLA_LOG_FORMAT=json: una línea JSON por pedido en stderr, con trace_id y span_id para cruzar con las trazas."""
    if not JSON_LOGS:
        return
    line = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "level": "error" if (status or 0) >= 500 else "info", "msg": "request",
            "method": method, "route": route, "status": status, "duration_ms": round((s.seconds or 0) * 1000, 1),
            "trace_id": getattr(s, "trace_id", None), "span_id": getattr(s, "span_id", None)}
    print(json.dumps(line), file=sys.stderr, flush=True)
