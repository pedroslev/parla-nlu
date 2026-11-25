"""Traducciones: cada t('...') de web/ y cada mensaje del servidor para la interfaz tienen su versión en inglés,
con los mismos {datos} / %s. Sin servidor ni modelos.   .venv/bin/python tests/test_i18n.py"""
import ast
import glob
import json
import os
import re

import support  # noqa: F401  (el repo en sys.path)
from parla import i18n

ROOT = support.ROOT
problems = []

# ---------- web: i18n.js ----------
src = open(os.path.join(ROOT, "web", "static", "i18n.js"), encoding="utf-8").read()
block = re.search(r"// EN-BEGIN.*?\n\s*const EN = \{\n(.*?)\s*\};\s*\n\s*// EN-END", src, re.S)
assert block, "i18n.js: no encontré el bloque EN-BEGIN / EN-END"
EN = json.loads("{" + block.group(1).rstrip().rstrip(",") + "}")   # una entrada por línea; la última coma se tolera

LIT = r"""'((?:[^'\\\n]|\\.)*)'|"((?:[^"\\\n]|\\.)*)"|`((?:[^`\\]|\\.)*)`"""
unescape = lambda s: re.sub(r"\\(.)", lambda m: {"n": "\n", "t": "\t"}.get(m[1], m[1]), s)


def literals_after(code, start, count):
    """Los primeros `count` textos entre comillas desde code[start:] (para t.plural(n, 'uno', 'varios'))."""
    out = []
    for m in re.finditer(LIT, code[start:start + 600]):
        out.append(m)
        if len(out) == count:
            break
    return out


used = {}
for path in [os.path.join(ROOT, "web", "index.html")] + sorted(glob.glob(os.path.join(ROOT, "web", "static", "*.js"))):
    name = os.path.relpath(path, ROOT)
    if name.endswith(("i18n.js", "widget.js")):      # widget.js tiene su propio diccionario (corre en sitios ajenos)
        continue
    code = open(path, encoding="utf-8").read()
    for m in re.finditer(r"(?<![\w.$])t\(\s*(?:" + LIT + ")", code):
        if m.group(3) is not None:
            problems.append("%s: t() con `plantilla`: usá comillas y {datos}: %s" % (name, m.group(3)[:60]))
            continue
        used.setdefault(unescape(m.group(1) if m.group(1) is not None else m.group(2)), name)
    for m in re.finditer(r"\bt\.plural\(", code):
        for lit in literals_after(code, m.end(), 2):
            used.setdefault(unescape(lit.group(1) if lit.group(1) is not None else lit.group(2) or ""), name)

for key, where in sorted(used.items()):
    if key not in EN:
        problems.append("%s: falta en inglés: %s" % (where, json.dumps(key, ensure_ascii=False)))
braces = lambda s: sorted(re.findall(r"\{(\w+)\}", s))
for key, value in EN.items():
    if braces(key) != braces(value):
        problems.append("i18n.js: los {datos} no coinciden: %s -> %s" % (key, value))
    if not value.strip():
        problems.append("i18n.js: traducción vacía: %s" % key)
unused = sorted(set(EN) - set(used))
if unused:
    print("aviso: %d entradas de i18n.js no se usan (¿quedaron de algo que se borró?): %s" % (len(unused), unused[:10]))

# ---------- widget.js: su diccionario chico tiene las mismas claves en cada idioma ----------
widget = open(os.path.join(ROOT, "web", "static", "widget.js"), encoding="utf-8").read()
dicts = re.findall(r"^\s*(\w\w): \{(.*?)\},?$", re.search(r"const TEXTS = \{\n(.*?)\n\s*\};", widget, re.S).group(1), re.M)
keys = {lang: sorted(re.findall(r"(\w+):", body)) for lang, body in dicts}
assert "es" in keys and "en" in keys, keys
for lang, k in keys.items():
    if k != keys["es"]:
        problems.append("widget.js: TEXTS.%s no tiene las mismas claves que TEXTS.es" % lang)

# ---------- servidor: mensajes que van a la interfaz ----------
pct = lambda s: len(re.findall(r"%[sd]", s))
for lang, d in i18n.DICTS.items():
    for key, value in d.items():
        if pct(key) != pct(value) or "%" in value.replace("%s", "").replace("%d", ""):
            problems.append("i18n.py %s: los %%s no coinciden: %s -> %s" % (lang, key, value))
    for key in sorted(set(i18n.EN) ^ set(d)):
        problems.append("i18n.py: %s está en %s pero no en %s" % (json.dumps(key, ensure_ascii=False), *(("en", lang) if key in i18n.EN else (lang, "en"))))

FIELDS = set(i18n.FIELDS)


def message(node):
    """El texto en español de un mensaje: "..." o "..." % (...). None si se arma de otra forma."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Mod) and isinstance(node.left, ast.Constant) and isinstance(node.left.value, str):
        return node.left.value
    return None


def check(node, where):
    if isinstance(node, ast.IfExp):                   # "uno" if n == 1 else "varios": los dos
        check(node.body, where), check(node.orelse, where)
        return
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Mod) and isinstance(node.left, ast.IfExp):
        check(node.left, where)
        return
    if isinstance(node, ast.JoinedStr):
        problems.append("%s: mensaje con f-string (usá \"...%%s\" %% dato para poder traducirlo)" % where)
        return
    text = message(node)
    if text is not None and re.search(r"[a-záéíóúñ]", text) and text not in i18n.EN:
        problems.append("%s: falta en inglés (parla/i18n.py): %s" % (where, json.dumps(text, ensure_ascii=False)))


for path in sorted(glob.glob(os.path.join(ROOT, "parla", "*.py"))):
    name = os.path.relpath(path, ROOT)
    if name.endswith(("mcp_server.py", "i18n.py")):      # el MCP habla con asistentes de IA, no con la interfaz
        continue
    for node in ast.walk(ast.parse(open(path, encoding="utf-8").read())):
        where = "%s:%d" % (name, getattr(node, "lineno", 0))
        if isinstance(node, ast.Dict):
            for k, v in zip(node.keys, node.values):
                if isinstance(k, ast.Constant) and k.value in FIELDS:
                    for item in (v.elts if isinstance(v, (ast.List, ast.Tuple)) else [v]):
                        check(item, where)
        elif isinstance(node, ast.Raise) and isinstance(node.exc, ast.Call) and node.exc.args and \
                getattr(node.exc.func, "id", "").endswith("Error"):
            check(node.exc.args[0], where)
        elif isinstance(node, ast.Call) and node.args and (getattr(node.func, "id", "") == "warn" or (   # rasa_import: warn = warnings.append
                getattr(node.func, "attr", "") == "append" and getattr(node.func.value, "id", "") in ("warnings", "notes", "problems"))):
            check(node.args[0], where)

for p in problems:
    print(p)
assert not problems, "%d problemas de traducción" % len(problems)
print("ok: %d textos de la interfaz y %d mensajes del servidor con su inglés" % (len(used), len(i18n.EN)))
