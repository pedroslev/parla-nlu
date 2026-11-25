"""Parla: armá bots que entienden. Paquete del servidor, el motor y sus módulos."""
import json
import os
import sys

__version__ = "0.9.0"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))          # la carpeta del repo
DATA = os.path.abspath(os.environ.get("PARLA_DATA") or os.path.join(ROOT, "data"))   # agentes, usuarios y modelos


def agents_dir():
    """La carpeta de agentes. Sigue a app.AGENTS (los tests lo cambian): server cargado o, si no, __main__."""
    main = sys.modules.get("parla.server") or sys.modules.get("__main__")
    return getattr(main, "AGENTS", None) or os.path.join(DATA, "agents")


def write_json(path, obj, mode=None, **dump):
    """Escribe JSON de forma atómica: a un .tmp en la misma carpeta y os.replace (nunca queda a medio escribir).
    mode=0o600 para archivos con secretos."""
    tmp = path + ".tmp"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, mode if mode is not None else 0o644)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, **dump)
    if mode is not None:
        os.chmod(tmp, mode)     # por si el .tmp ya existía con otros permisos
    os.replace(tmp, path)
