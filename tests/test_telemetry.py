"""Métricas, trazas y logs (parla/telemetry.py) contra un colector OTLP de mentira:  .venv/bin/python tests/test_telemetry.py"""
import hashlib
import json
import os
import re
import socket
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import support
DATA = support.temp_data()

POSTS, ECHO = [], []          # lotes que recibió el colector; encabezados que recibió el servicio del paso HTTP


class Fake(BaseHTTPRequestHandler):
    def do_POST(self):
        body = self.rfile.read(int(self.headers.get("Content-Length") or 0))
        if self.path == "/v1/traces":
            POSTS.append({"headers": {k.lower(): v for k, v in self.headers.items()}, "body": json.loads(body)})
        else:
            ECHO.append({k.lower(): v for k, v in self.headers.items()})
        out = b'{"ok": true}'
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(out)))
        self.end_headers()
        self.wfile.write(out)

    def log_message(self, *args):
        pass


fake = ThreadingHTTPServer(("127.0.0.1", 0), Fake)
threading.Thread(target=fake.serve_forever, daemon=True).start()
COLLECTOR = "http://127.0.0.1:%d" % fake.server_address[1]
for name in ("PARLA_METRICS", "PARLA_METRICS_TOKEN", "PARLA_OTEL_ENDPOINT", "OTEL_EXPORTER_OTLP_ENDPOINT", "PARLA_OTEL_CONTENT",
             "OTEL_EXPORTER_OTLP_TRACES_ENDPOINT", "PARLA_LOG_FORMAT"):
    os.environ.pop(name, None)
os.environ.update(PARLA_OTEL_INTERVAL="0.1", OTEL_EXPORTER_OTLP_HEADERS="x-honeycomb-team=clave%20de%20prueba", OTEL_SERVICE_NAME="parla-test")

from parla import server as app, telemetry, vault  # noqa: E402
import numpy as np  # noqa: E402

app._encode = lambda texts: [(lambda v: v / np.linalg.norm(v))(np.random.default_rng(
    int(hashlib.md5(t.encode()).hexdigest()[:8], 16)).normal(size=64)) for t in texts]
os.makedirs(app.AGENTS, exist_ok=True)
agent = app.create({**app.BLANK, "name": "Pizzería", "threshold": 0.9,
    "intents": [{"name": "saludar", "examples": ["hola"]}, {"name": "pedir", "examples": ["quiero una pizza"]}],
    "slots": [{"name": "estado"}],
    "flows": [{"name": "saludo", "trigger": "saludar", "steps": [{"type": "message", "text": "¡Hola!"}]},
              {"name": "pedido", "trigger": "pedir", "steps": [
                  {"type": "http", "method": "POST", "url": COLLECTOR + "/pedidos?clave={{ secret.API }}", "body": "{}",
                   "saves": [{"expr": "body.ok", "slot": "estado"}]},
                  {"type": "message", "text": "Listo"}]}],
    "system": {"csat": {"enabled": True}}})
AID = agent["id"]
vault.put(AID, "API", "clave-super-secreta")

srv = ThreadingHTTPServer(("127.0.0.1", 0), app.Handler)
threading.Thread(target=srv.serve_forever, daemon=True).start()
BASE = "http://127.0.0.1:%d" % srv.server_address[1]


def call(method, path, body=None, headers=None):
    req = urllib.request.Request(BASE + path, data=json.dumps(body).encode() if body is not None else None, method=method,
                                 headers={"Content-Type": "application/json", **(headers or {})})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, r.read().decode(), r.headers
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode(), e.headers


def say(text, sid="s1", headers=None):
    status, body, _ = call("POST", "/api/v1/bots/%s/events" % AID, {"sessionId": sid, "text": text}, headers)
    assert status == 200, body
    return json.loads(body)


LINE = re.compile(r'([a-zA-Z_:][a-zA-Z0-9_:]*)(?:\{((?:[a-zA-Z_]\w*="(?:[^"\\]|\\.)*",?)*)\})? ([-+0-9.eE]+|\+Inf|NaN)')


def parse(text):
    """Parser mínimo del formato de exposición 0.0.4: {(nombre, ((etiqueta, valor), ...)): número}. Falla si una línea no cumple."""
    out, types = {}, {}
    for line in text.splitlines():
        if line.startswith("# TYPE "):
            _, _, name, kind = line.split(" ")
            assert kind in ("counter", "gauge", "histogram"), line
            types[name] = kind
            continue
        if line.startswith("#") or not line:
            continue
        m = LINE.fullmatch(line)
        assert m, "línea inválida: %r" % line
        name, labels, value = m.groups()
        assert re.sub(r"_(bucket|sum|count)$", "", name) in types or name in types, "sin # TYPE: " + name
        out[(name, tuple(re.findall(r'(\w+)="((?:[^"\\]|\\.)*)"', labels or "")))] = float(value)
    return out, types


def metric(samples, name, **labels):
    return sum(v for (n, ls), v in samples.items() if n == name and all(dict(ls).get(k) == str(v2) for k, v2 in labels.items()))


def scrape(headers=None):
    status, body, hdrs = call("GET", "/metrics", headers=headers)
    assert status == 200, (status, body)
    assert hdrs["Content-Type"].startswith("text/plain; version=0.0.4")
    return parse(body)[0], body


def spans():
    assert telemetry.flush(5)
    time.sleep(0.05)
    out = [s for p in POSTS for rs in p["body"]["resourceSpans"] for ss in rs["scopeSpans"] for s in ss["spans"]]
    POSTS.clear()
    return out


def attrs(s):
    return {a["key"]: next(iter(a["value"].values())) for a in s["attributes"]}


# --- apagado por defecto: /metrics no existe y no se manda ninguna traza
telemetry.configure()
assert not telemetry.METRICS and not telemetry.TRACING
assert call("GET", "/metrics")[0] == 404
say("hola", "apagado")
assert telemetry.span("x") is telemetry.NOOP
assert telemetry.render().count("parla_turns_total{") == 0       # sin métricas no se cuenta nada
time.sleep(0.3)
assert POSTS == []

# --- con PARLA_METRICS=1 y token: sin token o con otro, 401; con el token, el texto
os.environ.update(PARLA_METRICS="1", PARLA_METRICS_TOKEN="tok-123")
telemetry.configure()
assert call("GET", "/metrics")[0] == 401
assert call("GET", "/metrics", headers={"Authorization": "Bearer otro"})[0] == 401
AUTH = {"Authorization": "Bearer tok-123"}
samples, text = scrape(AUTH)
assert metric(samples, "parla_info", version=telemetry.__version__) == 1

# --- sin token: solo desde esta compu (loopback y Host local); otro Host (un proxy) no
os.environ.pop("PARLA_METRICS_TOKEN")
telemetry.configure()
scrape()
assert call("GET", "/metrics", headers={"Host": "bots.example.com"})[0] == 401
assert telemetry.allowed(None, "10.0.0.5", "127.0.0.1:8000") == 401      # otra máquina que dice ser localhost
assert telemetry.allowed(None, "::1", "localhost") == 200

# --- un turno sube los contadores; el texto de la persona nunca aparece
before, _ = scrape()
say("hola")
say("hola soy ana@example.com con dni 30123456")      # fallback (no hay flujo con esa confianza)... o saludo
after, text = scrape()
assert metric(after, "parla_turns_total", agent=AID, channel="api", environment="production") \
    == metric(before, "parla_turns_total", agent=AID, channel="api", environment="production") + 2
outcomes = sum(metric(after, "parla_intent_outcomes_total", agent=AID, outcome=o) for o in ("matched", "fallback", "answer", "system", "none"))
assert outcomes >= 2
assert metric(after, "parla_http_requests_total", route="/api/v1/bots/{bot}/events", method="POST", status=200) >= 2
assert metric(after, "parla_nlu_duration_seconds_count", stage="classify") >= 2
for secret in ("ana@example.com", "30123456", "hola soy", "s1"):
    assert secret not in text, secret
assert AID in text                                   # el id del agente sí (cardinalidad acotada)

# --- histogramas: buckets acumulativos, +Inf = _count, la suma cuadra
for (name, labels), value in after.items():
    if name.endswith("_bucket"):
        base, rest = name[:-7], tuple(kv for kv in labels if kv[0] != "le")
        if dict(labels)["le"] == "+Inf":
            assert value == after[(base + "_count", rest)], name
buckets = sorted(((float(dict(ls)["le"]) if dict(ls)["le"] != "+Inf" else float("inf")), v)
                 for (n, ls), v in after.items() if n == "parla_nlu_duration_seconds_bucket" and dict(ls)["stage"] == "classify")
assert [v for _, v in buckets] == sorted(v for _, v in buckets), buckets
telemetry.observe("parla_csat_score", 4, agent="prueba")
samples, _ = scrape()
assert metric(samples, "parla_csat_score_bucket", agent="prueba", le="3") == 0
assert metric(samples, "parla_csat_score_bucket", agent="prueba", le="4") == 1
assert metric(samples, "parla_csat_score_bucket", agent="prueba", le="+Inf") == 1 and metric(samples, "parla_csat_score_sum", agent="prueba") == 4

# --- la ruta va como plantilla: ni ids ni sessionId (que puede ser un teléfono)
assert telemetry.route_of("/api/v1/bots/pizzeria/sessions/5491112345678/messages?after=3") == "/api/v1/bots/{bot}/sessions/{session}/messages"
assert telemetry.route_of("/api/agents/%s/versions/3/restore" % AID) == "/api/agents/{id}/versions/{n}/restore"
assert telemetry.route_of("/files/%s/AbCdEfGhIjKlMnOpQrStUv" % AID) == "/files/{id}/{file}"
assert telemetry.route_of("/wp-admin/x.php") == "/wp-admin/{x}"

# --- trazas: OTLP/HTTP JSON al colector, padre/hijo, traceparent entrante y saliente, sin contenido
os.environ["PARLA_OTEL_ENDPOINT"] = COLLECTOR
telemetry.configure()
assert telemetry.TRACING and telemetry.ENDPOINT == COLLECTOR + "/v1/traces"
POSTS.clear()
ECHO.clear()
incoming_trace, incoming_span = "4bf92f3577b34da6a3ce929d0e0e4736", "00f067aa0ba902b7"
say("quiero una pizza", "s2", {"traceparent": "00-%s-%s-01" % (incoming_trace, incoming_span)})
got = spans()
assert POSTS == [] and got
by_name = {s["name"]: s for s in got}
server = by_name["POST /api/v1/bots/{bot}/events"]
assert server["kind"] == 2 and server["traceId"] == incoming_trace and server["parentSpanId"] == incoming_span
assert {s["traceId"] for s in got} == {incoming_trace}
turn = by_name["parla.turn"]
assert turn["parentSpanId"] == server["spanId"]
assert by_name["nlu.classify"]["parentSpanId"] == turn["spanId"] and by_name["nlu.extract"]["parentSpanId"] == turn["spanId"]
flow = by_name["flow.run"]
step = by_name["http.step"]
assert step["parentSpanId"] == flow["spanId"] and step["kind"] == 3
assert attrs(step)["http.response.status_code"] == "200" and attrs(step)["server.address"] == "127.0.0.1"
(echo,) = ECHO
assert echo["traceparent"] == "00-%s-%s-01" % (incoming_trace, step["spanId"])     # el servicio de afuera sigue la traza
assert attrs(turn)["parla.intent"] == "pedir" and attrs(turn)["parla.agent.id"] == AID
dump = json.dumps(got)
for secret in ("quiero una pizza", "clave-super-secreta", "/pedidos", "Listo", "s2"):
    assert secret not in dump, secret
assert int(server["endTimeUnixNano"]) >= int(server["startTimeUnixNano"])
assert all(s["status"]["code"] == 1 for s in got)

# encabezados y recurso estándar (OTEL_EXPORTER_OTLP_HEADERS, OTEL_SERVICE_NAME)
say("hola", "s3")
telemetry.flush(5)
time.sleep(0.05)
post = POSTS[-1]
assert post["headers"].get("x-honeycomb-team") == "clave de prueba"
resource = {a["key"]: a["value"]["stringValue"] for a in post["body"]["resourceSpans"][0]["resource"]["attributes"]}
assert resource["service.name"] == "parla-test" and resource["service.version"] == telemetry.__version__
POSTS.clear()

# traceparent inválido o sin muestrear
say("hola", "s4", {"traceparent": "basura"})
assert len({s["traceId"] for s in spans()}) == 1
say("hola", "s4", {"traceparent": "00-%s-%s-00" % (incoming_trace, incoming_span)})
assert spans() == []                                  # el que llama dijo «no muestrear»

# --- PARLA_OTEL_CONTENT=1: el texto va, con datos personales y claves tapados
os.environ["PARLA_OTEL_CONTENT"] = "1"
telemetry.configure()
say("mi mail es ana@example.com y mi clave clave-super-secreta", "s5")
turn = next(s for s in spans() if s["name"] == "parla.turn")
message = attrs(turn)["parla.message"]
assert "[email]" in message and "••••" in message, message
assert "ana@example.com" not in message and "clave-super-secreta" not in message
os.environ.pop("PARLA_OTEL_CONTENT")
telemetry.configure()

# --- logs JSON: una línea por pedido con trace_id y span_id
import io, sys  # noqa: E401,E402
os.environ["PARLA_LOG_FORMAT"] = "json"
telemetry.configure()
err, sys.stderr = sys.stderr, io.StringIO()
try:
    say("hola", "s6")
    for _ in range(40):   # la línea se escribe después de mandar la respuesta: esperarla (si no, falla de vez en cuando)
        lines = [json.loads(line) for line in sys.stderr.getvalue().splitlines() if line.startswith("{")]
        if any(line["msg"] == "request" for line in lines):
            break
        time.sleep(0.05)
finally:
    sys.stderr = err
(log,) = [line for line in lines if line["msg"] == "request"]
assert log["route"] == "/api/v1/bots/{bot}/events" and log["status"] == 200 and len(log["trace_id"]) == 32 and len(log["span_id"]) == 16
assert "s6" not in json.dumps(log)
os.environ.pop("PARLA_LOG_FORMAT")
spans()

# --- el colector colgado (acepta la conexión y no contesta) nunca frena un pedido; la cola llena descarta
hung = socket.socket()
hung.bind(("127.0.0.1", 0))
hung.listen(1)
os.environ.update(PARLA_OTEL_ENDPOINT="http://127.0.0.1:%d" % hung.getsockname()[1], OTEL_EXPORTER_OTLP_TIMEOUT="300")
telemetry.configure()
started = time.perf_counter()
for i in range(20):
    say("hola", "lento")
per_turn = (time.perf_counter() - started) / 20
assert per_turn < 0.25, per_turn
started = time.perf_counter()
for i in range(telemetry.QUEUE_MAX + 500):
    with telemetry.span("relleno"):
        pass
assert time.perf_counter() - started < 2
samples, _ = scrape()
assert metric(samples, "parla_telemetry_dropped_total", reason="queue_full") > 0
# y tampoco con el colector apagado (conexión rechazada)
hung.close()
for i in range(5):
    say("hola", "lento")
telemetry.flush(3)
samples, _ = scrape()
assert metric(samples, "parla_telemetry_dropped_total", reason="export_failed") > 0
print("ok: métricas, trazas OTLP, traceparent, privacidad, logs JSON y exportador que no bloquea")
