"""Claves secretas por agente: agents/<id>.secrets.json (permisos 600). Nunca viajan en el JSON del agente."""
import json
import os
import re
import sys
import unicodedata

from . import DATA

AGENTS = os.path.join(DATA, "agents")


def _path(agent_id):
    if not re.fullmatch(r"[0-9a-f]{8}", str(agent_id)):
        raise ValueError("agente inválido")
    main = sys.modules.get("parla.server") or sys.modules.get("__main__")      # sigue a app.AGENTS (los tests lo cambian)
    return os.path.join(getattr(main, "AGENTS", None) or AGENTS, agent_id + ".secrets.json")


def _normal(name):
    """'api key de Mercado Pago' -> 'API_KEY_DE_MERCADO_PAGO'."""
    plain = unicodedata.normalize("NFD", str(name)).encode("ascii", "ignore").decode()
    return re.sub(r"[^A-Z0-9]+", "_", plain.upper()).strip("_")


def values(agent_id):
    """{NOMBRE: valor} para el motor ({{ secret.NOMBRE }}). Vacío si no hay."""
    try:
        with open(_path(agent_id), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def names(agent_id):
    return sorted(values(agent_id))


def _save(agent_id, data):
    path = _path(agent_id)
    if not data:
        if os.path.exists(path):
            os.remove(path)
        return
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.chmod(path, 0o600)       # por si el archivo ya existía con otros permisos


def put(agent_id, name, value):
    key = _normal(name)
    if not key:
        raise ValueError("ponele un nombre a la clave, por ejemplo API_KEY")
    if len(key) > 64:
        raise ValueError("el nombre de la clave es muy largo (hasta 64 letras)")
    if not isinstance(value, str) or not value:
        raise ValueError("falta el valor de la clave")
    if len(value) > 10000:
        raise ValueError("el valor es muy largo (hasta 10.000 caracteres)")
    data = values(agent_id)
    data[key] = value
    _save(agent_id, data)
    return key


def delete(agent_id, name):
    data = values(agent_id)
    data.pop(_normal(name), None)
    _save(agent_id, data)


def mask(text, agent_id):
    """Tapa con •••• cualquier valor secreto (de 4 o más caracteres) que aparezca en el texto."""
    if not isinstance(text, str):
        return text
    for value in sorted(values(agent_id).values(), key=len, reverse=True):
        if isinstance(value, str) and len(value) >= 4:
            text = text.replace(value, "••••")
    return text
