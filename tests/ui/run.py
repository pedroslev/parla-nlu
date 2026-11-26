#!/usr/bin/env python3
"""Barrido de la interfaz en Chrome sin ventana: cada rol x idioma x agente x sección que el rol ve.

    .venv/bin/python tests/ui/run.py            # make ui-test; CHROME=/ruta/a/chrome si no está en el lugar de siempre

Levanta un Parla propio (datos temporales, puerto libre), crea dueño, editor, analista y atención, importa los dos
ejemplos, entrena, arma unas charlas (una pasa a una persona) y corre tests/ui/sweep.mjs, un proceso por rol en paralelo.
Necesita Node 22+ (WebSocket global) y Chrome. Sale con 1 si encontró algún problema.
"""
import http.cookiejar
import json
import os
import subprocess
import sys
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
import support  # noqa: E402

ROOT = support.ROOT
PASSWORD = "ui-sweep-123"
ROLES = {"owner": "duena", "editor": "edita", "analyst": "mira", "agent": "atiende"}


def client():
    jar = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))

    def call(method, path, body=None):
        req = urllib.request.Request(BASE + path, method=method, data=json.dumps(body).encode() if body is not None else None,
                                     headers={"Content-Type": "application/json"})
        with jar.open(req, timeout=120) as r:
            return json.loads(r.read() or b"null")
    return call


def chrome_path():
    if os.environ.get("CHROME"):
        return os.environ["CHROME"]
    mac = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
    return mac if os.path.exists(mac) else "google-chrome"


data = support.temp_data()
proc, port = support.start_server(data)
BASE = "http://127.0.0.1:%d" % port
started = time.time()
try:
    api = client()
    api("POST", "/api/users", {"name": ROLES["owner"], "password": PASSWORD})          # el primero queda dueño
    for role, name in ROLES.items():
        if role != "owner":
            api("POST", "/api/users", {"name": name, "password": PASSWORD, "role": role})
    agents = []
    for example in ("pizzeria.json", "turnos-clinica.json"):
        with open(os.path.join(ROOT, "examples", example), encoding="utf-8") as f:
            agents.append(api("POST", "/api/agents", {"import": json.load(f)})["id"])
    for aid in agents:
        api("POST", "/api/agents/%s/train" % aid, {})
    talk = lambda aid, sid, texts: [api("POST", "/api/v1/bots/%s/events" % aid, {"sessionId": sid, "text": t}) for t in texts]
    talk(agents[0], "ui-pedido", ["hola", "Juan", "Pérez", "Corrientes 1234", "napo", "2"])
    talk(agents[0], "ui-reclamo", ["me llegó fría", "hola?"])                                # pasa a una persona: Bandeja
    talk(agents[0], "ui-raro", ["asdf qwerty", "¿aceptan bitcoin?"])                          # para «Para enseñar»
    talk(agents[1], "ui-turno", ["hola", "quiero un turno"])
    print("datos listos en %.1fs (%s)" % (time.time() - started, BASE), flush=True)

    env = dict(os.environ, BASE=BASE, AGENTS=",".join(agents), PASSWORD=PASSWORD, CHROME=chrome_path())
    runs = [subprocess.Popen(["node", os.path.join(HERE, "sweep.mjs"), role, name], env=env, cwd=ROOT)   # cada línea dice su [rol]
            for role, name in ROLES.items()]
    failed = sum(run.wait() != 0 for run in runs)
    print("\nbarrido de la interfaz: %s en %.0fs" % ("FALLÓ (%d roles)" % failed if failed else "ok", time.time() - started))
    sys.exit(1 if failed else 0)
finally:
    proc.terminate()
    proc.wait(10)
