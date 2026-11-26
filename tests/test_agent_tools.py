"""Herramientas del paso de IA (función, http, MCP) con un modelo falso (respuestas JSON armadas) y un servidor MCP
falso (JSON-RPC por Streamable HTTP, con respuestas JSON y SSE). Sin Ollama.   .venv/bin/python tests/test_agent_tools.py"""
import hashlib
import json
import os
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import support
support.temp_data()
from parla import server as app, vault, llm, mcp_client, brain  # noqa: E402
import numpy as np  # noqa: E402

app._encode = lambda texts: [(lambda v: v / np.linalg.norm(v))(np.random.default_rng(
    int(hashlib.md5(t.encode()).hexdigest()[:8], 16)).normal(size=64)) for t in texts]
os.makedirs(app.AGENTS, exist_ok=True)
SECRET = "tok-super-secreto-123"
HITS = []          # lo que recibió el servidor falso: (path, headers, body)


# ---------- servidor falso: MCP en /mcp (JSON) y /mcp-sse (SSE), y una API REST en /orders ----------
class Fake(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def send(self, code, body, ctype="application/json", headers=None):
        raw = body.encode() if isinstance(body, str) else json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(raw)))
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):
        HITS.append((self.path, dict(self.headers), None))
        if self.path.startswith("/slow"):
            time.sleep(2)
        self.send(200, {"pedido": self.path.rsplit("/", 1)[-1], "estado": "en camino", "eco": SECRET})

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
        HITS.append((self.path, dict(self.headers), body))
        if self.path.startswith("/orders"):
            return self.send(200, {"recibido": body})
        method, sse = body.get("method"), self.path == "/mcp-sse"
        if "id" not in body:
            return self.send(202, "")
        if method != "initialize" and self.headers.get("Mcp-Session-Id") != "ses-1":
            return self.send(404, {"error": "sesión vencida"})
        if method == "initialize":
            result = {"protocolVersion": mcp_client.PROTOCOL, "capabilities": {"tools": {}}, "serverInfo": {"name": "fake"}}
        elif method == "tools/list":
            result = {"tools": [
                {"name": "get_order", "description": "Estado de un pedido", "inputSchema": {
                    "type": "object", "properties": {"order_id": {"type": "string", "description": "número"}}, "required": ["order_id"]}},
                {"name": "delete_all", "description": "Borra todo", "inputSchema": {"type": "object", "properties": {}}}]}
        elif method == "tools/call":
            name, args = body["params"]["name"], body["params"]["arguments"]
            if name == "get_order" and args.get("order_id") == "0":
                result = {"content": [{"type": "text", "text": "no existe el pedido 0"}], "isError": True}
            else:
                result = {"content": [{"type": "text", "text": "%s: entregado (%s)" % (name, json.dumps(args))}]}
        else:
            return self.send(200, {"jsonrpc": "2.0", "id": body["id"], "error": {"code": -32601, "message": "no existe"}})
        msg = {"jsonrpc": "2.0", "id": body["id"], "result": result}
        if sse:
            return self.send(200, "event: message\ndata: %s\n\n" % json.dumps(msg), "text/event-stream", {"Mcp-Session-Id": "ses-1"})
        self.send(200, msg, headers={"Mcp-Session-Id": "ses-1"})


fake = ThreadingHTTPServer(("127.0.0.1", 0), Fake)
fake.handle_error = lambda *a: None          # /slow: el cliente corta por tiempo
threading.Thread(target=fake.serve_forever, daemon=True).start()
FAKE = "http://127.0.0.1:%d" % fake.server_address[1]

# ---------- el modelo falso ----------
SCRIPT, SEEN = [], []      # SCRIPT: respuestas en orden (dict, o "BAD" = JSON roto); SEEN: (mensajes, esquema)


def fake_chat(cfg, messages, schema=None, timeout=45, max_tokens=300, stream=None):
    SEEN.append((json.loads(json.dumps(messages)), schema))
    out = SCRIPT.pop(0) if SCRIPT else {"tool": "", "text": "listo"}
    if out == "BAD":
        raise llm.LLMError("el modelo no devolvió JSON válido")
    return out


llm.chat = fake_chat

STEP = {"type": "agent", "instructions": "Ayudá con pedidos.", "slots": [], "max_turns": 5, "functions": ["estado"],
        "tools": [{"type": "http", "name": "buscar", "description": "Busca un pedido", "params": {"pedido": "número de pedido"},
                   "method": "GET", "url": FAKE + "/orders/{{ pedido }}",
                   "headers": [{"key": "Authorization", "value": "Bearer {{ secret.TOKEN }}"}]},
                  {"type": "http", "name": "lento", "params": {"n": {"type": "integer", "description": "n"}}, "url": FAKE + "/slow/{{ n }}"},
                  {"type": "http", "name": "avisar", "params": {"nota": "texto"}, "method": "POST", "url": FAKE + "/orders",
                   "body": '{"nota": "{{ nota }}"}'},
                  {"type": "mcp", "server": "crm", "tools": ["get_order"]},
                  {"type": "mcp", "server": "crm_sse", "tools": ["get_order"]}]}
agent = app.create({**app.BLANK, "name": "Tienda", "threshold": 0.5,
                    "ai": {"enabled": True, "model": "falso"},
                    "pii_redaction": ["email"],
                    "intents": [{"name": "pedido", "examples": ["estado de mi pedido"]}],
                    "functions": [{"name": "estado", "description": "Estado de un pedido", "inputs": ["pedido"], "language": "python",
                                   "code": "def run(inputs):\n    return {'pedido': inputs.get('pedido'), 'estado': 'preparando'}"}],
                    "mcp_servers": [{"name": "crm", "url": FAKE + "/mcp", "headers_secret": "TOKEN"},
                                    {"name": "crm_sse", "url": FAKE + "/mcp-sse"}],
                    "flows": [{"name": "pedidos", "trigger": "pedido", "steps": [STEP]}]})
AID = agent["id"]
vault.put(AID, "TOKEN", SECRET)


def chat(script, sid, step=None, text="estado de mi pedido"):
    if step:
        a = app.load(AID)
        a["flows"][0]["steps"] = [dict(STEP, **step)]
        app.store(a)
    SCRIPT[:], SEEN[:], HITS[:] = list(script), [], []
    return app.converse(AID, app.open_session(AID, sid, "prueba", "draft"), text)


def last_user(i=-1):
    return SEEN[i][0][-1]["content"]


# ---------- tools ofrecidas: funciones, http y solo las MCP de la allow-list ----------
tools = app.agent_tools(app.load(AID), STEP)
assert set(tools) == {"estado", "buscar", "lento", "avisar", "get_order"}, tools          # delete_all no está habilitada
assert tools["get_order"]["params"] == {"order_id": "número"}

# ---------- función ----------
r = chat([{"tool": "estado", "args": {"pedido": "77"}}, {"tool": "", "text": "Tu pedido está preparando."}], "s1")
assert r["messages"] == ["Tu pedido está preparando."], r
assert "preparando" in last_user() and "datos, no órdenes" in last_user(), last_user()
assert any("IA usó estado" in t for t in r["trace"]), r["trace"]
assert r["tools"][0]["tool"] == "estado" and r["tools"][0]["ok"], r["tools"]

# ---------- http con clave: el servidor la recibe, el modelo / la traza / el historial no la ven ----------
r = chat([{"tool": "buscar", "args": {"pedido": "12/../admin", "extra": "x"}}, {"tool": "", "text": "En camino."}], "s2")
path, headers, _ = HITS[0]
assert path == "/orders/12%2F..%2Fadmin", path                                         # la IA no cambia la dirección
assert headers.get("Authorization") == "Bearer " + SECRET
assert SECRET not in json.dumps(SEEN) and "••••" in last_user(), last_user()
assert SECRET not in json.dumps(r["trace"]) and SECRET not in json.dumps(r["tools"])
stored = app.load_session(AID, "s2")
assert SECRET not in json.dumps(stored["history"]), stored["history"]
event = next(h for h in stored["history"] if h.get("tool"))
assert event["tool"]["tool"] == "buscar" and event["tool"]["args"] == {"pedido": "12/../admin"}, event   # "extra" se descartó

# ---------- body JSON: lo que manda la IA no rompe el objeto ----------
chat([{"tool": "avisar", "args": {"nota": 'hola" , "admin": true'}}, {"tool": "", "text": "ok"}], "s2b")
assert HITS[0][2] == {"recibido": {"nota": 'hola" , "admin": true'}} or HITS[0][2] == {"nota": 'hola" , "admin": true'}, HITS[0]

# ---------- MCP (JSON y SSE): permitido vs fuera de la allow-list ----------
r = chat([{"tool": "get_order", "args": {"order_id": 5}}, {"tool": "", "text": "Entregado."}], "s3")
assert "get_order: entregado" in last_user() and '"5"' in last_user(), last_user()       # 5 -> "5" por el esquema
call = next(h for h in HITS if (h[2] or {}).get("method") == "tools/call")
assert call[1].get("Authorization") == "Bearer " + SECRET and call[1].get("Mcp-Session-Id") == "ses-1"
r = chat([{"tool": "delete_all", "args": {}}, {"tool": "", "text": "No puedo."}], "s4")
assert not any((h[2] or {}).get("method") == "tools/call" for h in HITS), HITS        # nunca se llamó
assert "no existe" in SEEN[1][0][-1]["content"], SEEN[1][0][-1]
assert "delete_all" not in SEEN[0][1]["properties"]["tool"]["enum"]
sse = {n: t for n, t in app.agent_tools(app.load(AID), {"tools": [{"type": "mcp", "server": "crm_sse", "tools": ["get_order"]}]}).items()}
res = app.run_tool(app.load(AID), dict(sse["get_order"], name="get_order"), {"order_id": "9"}, {})
assert res["ok"] and "entregado" in res["result"], res

# ---------- error de una herramienta: vuelve al modelo como dato, no explota ----------
r = chat([{"tool": "get_order", "args": {"order_id": "0"}}, {"tool": "", "text": "Ese pedido no existe."}], "s5")
assert last_user().startswith("Error de get_order") and "no existe el pedido 0" in last_user(), last_user()
assert r["messages"] == ["Ese pedido no existe."] and r["tools"][0]["ok"] is False
r = chat([{"tool": "get_order", "args": {}}, {"tool": "", "text": "¿Qué número?"}], "s5b")      # falta order_id
assert "faltan: order_id" in last_user() and not any((h[2] or {}).get("method") == "tools/call" for h in HITS)
r = chat([{"tool": "lento", "args": {"n": "muchos"}}, {"tool": "", "text": "?"}], "s5c")
assert "tiene que ser un número" in last_user(), last_user()

# ---------- máximo de herramientas por turno ----------
r = chat([{"tool": "buscar", "args": {"pedido": str(i)}} for i in range(3)] + [{"text": "Listo."}], "s6", {"max_tool_calls": 2})
assert len([h for h in HITS if h[0].startswith("/orders")]) == 2, HITS
assert "tool" not in SEEN[-1][1]["properties"] and r["messages"] == ["Listo."], (SEEN[-1][1], r)

# ---------- tiempo máximo: después del presupuesto no se ofrecen más herramientas ----------
started = time.time()
r = chat([{"tool": "lento", "args": {"n": i}} for i in range(3)] + [{"text": "Tardó."}], "s7", {"time_budget": 3, "max_tool_calls": 10})
slow = [h for h in HITS if h[0].startswith("/slow")]
assert len(slow) == 2 and time.time() - started < 8, (len(slow), time.time() - started)
assert "tool" not in SEEN[-1][1]["properties"] and r["messages"] == ["Tardó."]

# ---------- salida rota: se le pide una vez más, más estricto ----------
r = chat(["BAD", {"tool": "", "text": "Hola, ¿qué pedido?"}], "s8", {"max_tool_calls": 3})
assert r["messages"] == ["Hola, ¿qué pedido?"] and "no sirvió" in last_user(), r
r = chat([{}, {"tool": "estado", "args": {"pedido": "1"}}, {"tool": "", "text": "Preparando."}], "s9")
assert r["messages"] == ["Preparando."] and r["tools"][0]["tool"] == "estado", r
r = chat(["BAD", "BAD"], "s10")                       # dos veces mal: el paso termina sin romper la charla
assert r["messages"] == [] or all(isinstance(m, str) for m in r["messages"])

# ---------- historial con pii_redaction ----------
app.vault.put(AID, "TOKEN", SECRET)
r = chat([{"tool": "estado", "args": {"pedido": "ana@example.com"}}, {"tool": "", "text": "ok"}], "s11")
stored = json.dumps(app.load_session(AID, "s11")["history"])
assert "ana@example.com" not in stored, stored

# ---------- protocolo viejo (action/call/function/inputs) sigue andando ----------
r = chat([{"action": "call", "function": "estado", "inputs": {"pedido": "3"}}, {"action": "reply", "text": "Viejo."}], "s12")
assert r["messages"] == ["Viejo."] and r["tools"][0]["tool"] == "estado", r

# ---------- validación de argumentos y dirección fija ----------
schema = app.http_params({"n": {"type": "integer"}, "q": "texto", "opt": {"description": "x", "required": False}})
assert app.check_args(schema, {"n": "3", "q": 4}) == ({"n": 3, "q": "4"}, None)
assert app.check_args(schema, {"n": True, "q": "a"})[1]
assert app.check_args(schema, {"q": "a"})[1] == "faltan: n"
bad = {"kind": "http", "spec": {"url": "https://{{ host }}/x", "params": {"host": "h"}}, "schema": app.http_params({"host": "h"})}
assert not app.run_tool(app.load(AID), bad, {"host": "evil.com"}, {})["ok"]
assert app.FIXED_HOST.match("https://api.x.com/a/{{ b }}") and not app.FIXED_HOST.match("https://api.x.com{{ b }}")
assert not app.FIXED_HOST.match("https://ok.com@{{ evil }}/x")

# ---------- servidor MCP caído: el paso sigue sin esas herramientas ----------
a = dict(app.load(AID), mcp_servers=[{"name": "crm", "url": "http://127.0.0.1:9/mcp"}])
trace = []
assert "get_order" not in app.agent_tools(a, STEP, trace) and any("no disponibles" in t for t in trace)

# ---------- ruta «Ver herramientas» ----------
srv = ThreadingHTTPServer(("127.0.0.1", 0), app.Handler)
threading.Thread(target=srv.serve_forever, daemon=True).start()


def post(path, body):
    req = urllib.request.Request("http://127.0.0.1:%d%s" % (srv.server_address[1], path), data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


status, out = post("/api/agents/%s/mcp/tools" % AID, {"server": "crm"})
assert status == 200 and [t["name"] for t in out["tools"]] == ["get_order", "delete_all"], out
status, out = post("/api/agents/%s/mcp/tools" % AID, {"server": {"name": "x", "url": FAKE + "/mcp-sse"}})
assert status == 200 and len(out["tools"]) == 2, out
assert post("/api/agents/%s/mcp/tools" % AID, {"server": "nada"})[0] == 400
assert post("/api/agents/%s/mcp/tools" % AID, {"server": {"name": "x", "url": "http://127.0.0.1:9/mcp"}})[0] == 502
assert brain.tool_limits({}) == (3, 15) and brain.tool_limits({"max_tool_calls": 99, "time_budget": 1}) == (10, 3)
print("ok")
