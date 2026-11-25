"""Proveedor compatible con OpenAI contra un servidor falso local (http.server): forma del pedido, API key desde el
vault, modo JSON y su caída a prompt, errores (401 sin la key, 429, timeout), /models y funciones del bot.
Nunca llama a una API real. Uso: .venv/bin/python tests/test_llm_openai.py"""
import json
import os
import re
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import support
data = support.temp_data()
os.makedirs(os.path.join(data, "agents"), exist_ok=True)
from parla import brain, llm, vault  # noqa: E402

KEY = "sk-test-1234567890abcdef"
seen = []                     # (path, headers, body) de cada pedido
mode = {"models": 200, "chat": 200, "json_mode": True, "sleep": 0, "answer": lambda prompt: "hola"}


class Fake(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def send(self, code, body):
        raw = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):
        seen.append((self.path, dict(self.headers), None))
        if mode["models"] != 200:
            return self.send(mode["models"], {"error": "not found"})
        self.send(200, {"object": "list", "data": [{"id": "gpt-test"}, {"id": "otro"}]})

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        seen.append((self.path, dict(self.headers), body))
        time.sleep(mode["sleep"])
        if mode["chat"] != 200:
            return self.send(mode["chat"], {"error": {"message": "Incorrect API key provided: %s" % KEY}})
        if "response_format" in body and not mode["json_mode"]:
            return self.send(400, {"error": {"message": "response_format is not supported"}})
        prompt = body["messages"][-1]["content"]
        content = mode["answer"](prompt)
        self.send(200, {"choices": [{"message": {"role": "assistant", "content": content}}]})


server = ThreadingHTTPServer(("127.0.0.1", 0), Fake)
threading.Thread(target=server.serve_forever, daemon=True).start()
URL = "http://127.0.0.1:%d/v1" % server.server_address[1]

AGENT_ID = "abcd1234"
vault.put(AGENT_ID, "OPENAI_KEY", KEY)
AI = {"enabled": True, "provider": "openai", "url": URL, "model": "gpt-test", "api_key_secret": "OPENAI_KEY", "temperature": 0}
AGENT = {"id": AGENT_ID, "ai": AI, "threshold": 0.7, "entities": [], "functions": [], "intents": [
    {"name": "pedir_turno", "examples": ["quiero un turno"]}, {"name": "cancelar_turno", "examples": ["cancelá mi turno"]}]}

# ---------- la key sale del vault; nunca del JSON ----------
cfg = llm.settings(AGENT)
assert cfg["api_key"] == KEY
assert "api_key" not in llm.settings({"ai": dict(AI, api_key="robada")})          # sin id ni vault: sin key
assert llm.settings({"id": AGENT_ID, "ai": dict(AI, api_key="x")})["api_key"] == KEY

# ---------- forma del pedido ----------
assert llm.chat(cfg, [{"role": "user", "content": "hola"}], max_tokens=50) == "hola"
path, headers, body = seen[-1]
assert path == "/v1/chat/completions", path
assert headers["Authorization"] == "Bearer " + KEY, headers
assert body["model"] == "gpt-test" and body["messages"] == [{"role": "user", "content": "hola"}], body
assert body["max_tokens"] == 50 and body["temperature"] == 0 and body["stream"] is False and "response_format" not in body
# dirección sin /v1 (LM Studio «http://127.0.0.1:1234»): se agrega
llm.chat(dict(cfg, url=URL[:-3]), [{"role": "user", "content": "x"}])
assert seen[-1][0] == "/v1/chat/completions"

# ---------- modo JSON ----------
SCHEMA = {"type": "object", "properties": {"r": {"type": "string"}}, "required": ["r"]}
mode["answer"] = lambda p: '{"r": "ok"}'
assert llm.chat(cfg, [{"role": "user", "content": "x"}], schema=SCHEMA) == {"r": "ok"}
body = seen[-1][2]
assert body["response_format"] == {"type": "json_object"} and "JSON" in body["messages"][0]["content"], body
# el servidor rechaza response_format (400): reintenta sin él, lo recuerda y saca el JSON de ```json …```
mode.update(json_mode=False, answer=lambda p: 'Claro:\n```json\n{"r": "sin modo"}\n```')
cfg2 = dict(cfg, url=URL + "/")                                                   # misma URL normalizada
n = len(seen)
assert llm.chat(cfg2, [{"role": "user", "content": "x"}], schema=SCHEMA) == {"r": "sin modo"}
assert len(seen) == n + 2 and "response_format" not in seen[-1][2]
assert llm.chat(cfg, [{"role": "user", "content": "x"}], schema=SCHEMA) == {"r": "sin modo"}
assert len(seen) == n + 3                                                          # ya no prueba con response_format
mode["json_mode"] = True

# ---------- errores ----------
def error_of():
    try:
        llm.chat(cfg, [{"role": "user", "content": "x"}], timeout=5)
    except llm.LLMError as e:
        return e
    raise AssertionError("no falló")


mode["chat"] = 401
e = error_of()
assert e.code == 401 and "401" in str(e) and "API key" in str(e) and KEY not in str(e) and KEY[:10] not in str(e), e
mode["chat"] = 429
e = error_of()
assert e.code == 429 and "demasiados pedidos" in str(e) and KEY not in str(e), e    # el detalle se muestra, sin la key
mode["chat"] = 503
assert "falló" in str(error_of())
mode.update(chat=200, sleep=1.5)
try:
    llm.chat(cfg, [{"role": "user", "content": "x"}], timeout=0.5)
    raise AssertionError("no cortó")
except llm.LLMError as e:
    assert "tardó" in str(e), e
mode["sleep"] = 0
time.sleep(1.2)                                                                    # que termine el pedido colgado

# ---------- estado: /models, sin /models, prueba ----------
s = llm.status(cfg)
assert s["ok"] and s["model_ready"] and [m["name"] for m in s["models"]] == ["gpt-test", "otro"] and s["local"], s
assert seen[-1][0] == "/v1/models" and seen[-1][1]["Authorization"] == "Bearer " + KEY
s = llm.status(dict(cfg, model="no-existe"))
assert s["ok"] and not s["model_ready"] and "no-existe" in s["hint"], s
mode["models"] = 404
s = llm.status(dict(cfg, prompt="hola"))
assert s["ok"] and s["models_unknown"] and s["model_ready"] and s["reply"] and isinstance(s["ms"], int), s
mode["models"] = 401
s = llm.status(cfg)
assert not s["ok"] and KEY not in json.dumps(s), s
mode["models"] = 200
assert not llm.is_local("https://api.openai.com/v1") and llm.is_local("http://192.168.1.10:8000/v1") and llm.is_local(URL)
assert llm.pull(cfg, "x")["ok"] is False                                           # descargar: solo Ollama

# ---------- Azure: api-key y api-version ----------
llm.chat(dict(cfg, azure=True), [{"role": "user", "content": "x"}])
path, headers, _ = seen[-1]
assert path == "/v1/chat/completions?api-version=" + llm.AZURE_API_VERSION, path
assert headers.get("Api-Key") == KEY and "Authorization" not in headers, headers

# ---------- funciones del bot a través del proveedor ----------
def letter_of(word):
    def answer(prompt):
        found = re.search(r"^([A-Z])\) [^\n]*%s" % word, prompt, re.M)
        return json.dumps({"opcion": found.group(1), "letra": found.group(1)}) if found else '{"opcion": "Z", "letra": "Z"}'
    return answer


mode["answer"] = letter_of("cancelar")
nlu = {"intent": "pedir_turno", "confidence": 0.5, "entities": [], "ranking": [("pedir_turno", 0.5), ("cancelar_turno", 0.45)]}
r = brain.rescue_intent(AGENT, "al final no puedo ir", nlu)
assert r["intent"] == "cancelar_turno" and r["via"] == "ia", r
mode["answer"] = letter_of("no, rechaza")
r = brain.understand(AGENT, {}, "mejor no", "¿Te confirmo el turno?", {"name": "si_no", "values": ["si", "no"]})
assert r == {"tipo": "responde", "opcion": "no", "accion": None}, r
mode["answer"] = lambda p: json.dumps({"valor": "Juan Pérez", "respuesta": "si"})   # extrae y después verifica
assert brain.fill_slot(AGENT, {"name": "nombre", "description": "Nombre"}, "soy Juan Pérez", {}) == "Juan Pérez"
mode["chat"] = 500                                                                 # proveedor caído: el bot sigue igual
assert brain.rescue_intent(AGENT, "al final no puedo ir", nlu) is nlu
mode["chat"] = 200
server.shutdown()
print("ok")
