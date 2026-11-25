"""Ejecuta las "funciones" de un agente (código Python o JavaScript) en un proceso aparte.

Cada función define run(inputs) y devuelve un objeto. Corre con tiempo máximo, límites de CPU y memoria,
una carpeta temporal vacía y variables de entorno limpias: si se cuelga o explota, el bot sigue andando.
NO es un sandbox de seguridad: es código del dueño del agente (o de su IA) corriendo en su máquina.
Para un Parla expuesto a otros, apagalas con PARLA_FUNCTIONS=0.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import uuid

TIMEOUT = 5                 # segundos por ejecución
MEMORY = 512 * 1024 * 1024  # bytes (donde el sistema lo respeta)
MAX_OUTPUT = 200_000        # caracteres de salida que se leen
LANGUAGES = {"python": "Python", "javascript": "JavaScript"}

PYTHON = r'''
import asyncio, inspect, json, sys, traceback
mark = sys.argv[1]
payload = json.loads(sys.stdin.read())
scope = {"__name__": "funcion"}
try:
    exec(compile(payload["code"], "funcion.py", "exec"), scope)
    if not callable(scope.get("run")):
        raise NameError("definí una función run(inputs) que devuelva un objeto")
    result = scope["run"](payload["inputs"])
    if inspect.isawaitable(result):
        result = asyncio.run(result)
    out = {"ok": True, "result": result}
except Exception as error:
    out = {"ok": False, "error": "%s: %s" % (type(error).__name__, error), "traceback": traceback.format_exc(limit=4)}
sys.stdout.write("\n" + mark + json.dumps(out, default=str, ensure_ascii=False))
'''

JAVASCRIPT = r'''
const mark = process.argv[1];
let raw = "";
process.stdin.on("data", (c) => raw += c).on("end", async () => {
  let out;
  try {
    const payload = JSON.parse(raw);
    const run = new Function("require", "module", "exports", payload.code + "\n;return typeof run === 'function' ? run : (module.exports && module.exports.run);")(require, { exports: {} }, {});
    if (typeof run !== "function") throw new Error("definí una función run(inputs) que devuelva un objeto");
    out = { ok: true, result: await run(payload.inputs) };
  } catch (error) {
    out = { ok: false, error: (error && error.name ? error.name + ": " : "") + (error && error.message || String(error)), traceback: String(error && error.stack || "").split("\n").slice(0, 5).join("\n") };
  }
  process.stdout.write("\n" + mark + JSON.stringify(out, (k, v) => typeof v === "bigint" ? String(v) : v));
});
'''


def enabled():
    return os.environ.get("PARLA_FUNCTIONS", "1") not in ("0", "false", "no", "off")


def _limits():
    try:
        import resource
        resource.setrlimit(resource.RLIMIT_CPU, (TIMEOUT + 1, TIMEOUT + 1))
        try:
            resource.setrlimit(resource.RLIMIT_AS, (MEMORY, MEMORY))
        except (ValueError, OSError):
            pass        # macOS no deja limitar la memoria así; el tiempo máximo sigue valiendo
    except ImportError:
        pass            # Windows: queda el tiempo máximo


def run_function(function, inputs):
    """{"ok", "result" | "error", "logs", "ms"}. Nunca lanza: cualquier problema vuelve como ok=False."""
    import time
    started = time.perf_counter()
    done = lambda out: dict(out, ms=round((time.perf_counter() - started) * 1000))
    if not enabled():
        return done({"ok": False, "error": "Las funciones están apagadas en este Parla (PARLA_FUNCTIONS=0).", "logs": ""})
    language = function.get("language") or "python"
    if language not in LANGUAGES:
        return done({"ok": False, "error": "el lenguaje tiene que ser python o javascript", "logs": ""})
    mark = "@@PARLA-%s@@" % uuid.uuid4().hex
    if language == "python":
        command = [sys.executable, "-I", "-c", PYTHON, mark]
    else:
        node = shutil.which("node")
        if not node:
            return done({"ok": False, "error": "Para funciones en JavaScript hace falta tener Node.js instalado.", "logs": ""})
        command = [node, "-e", JAVASCRIPT, mark]
    payload = json.dumps({"code": function.get("code") or "", "inputs": inputs}, default=str)
    env = {"PATH": os.environ.get("PATH", ""), "LANG": "C.UTF-8", "PYTHONIOENCODING": "utf-8", "PYTHONDONTWRITEBYTECODE": "1"}
    with tempfile.TemporaryDirectory(prefix="parla-fn-") as folder:
        try:
            proc = subprocess.run(command, input=payload, capture_output=True, text=True, timeout=TIMEOUT, cwd=folder,
                                  env=env, preexec_fn=_limits if os.name == "posix" else None)
        except subprocess.TimeoutExpired:
            return done({"ok": False, "error": "La función tardó más de %d segundos y se cortó." % TIMEOUT, "logs": ""})
        except OSError as error:
            return done({"ok": False, "error": "No se pudo ejecutar la función: %s" % error, "logs": ""})
    stdout, stderr = proc.stdout[:MAX_OUTPUT], proc.stderr[:MAX_OUTPUT]
    logs, _, tail = stdout.rpartition(mark) if mark in stdout else (stdout, "", "")
    logs = (logs.rstrip("\n") + ("\n" + stderr if stderr else "")).strip()[-4000:]
    if not tail:
        why = "se quedó sin memoria o la cortó el sistema" if proc.returncode and proc.returncode < 0 else "terminó sin devolver nada"
        return done({"ok": False, "error": "La función %s." % why, "logs": logs})
    try:
        out = json.loads(tail)
    except ValueError:
        return done({"ok": False, "error": "La función devolvió algo que no se puede guardar.", "logs": logs})
    return done(dict(out, logs=logs))
