"""Archivos que sube quien arma el bot (lista de precios, catálogo, fotos) para mandarlos con el paso «Enviar un archivo».
agents/<id>.files/<fileId> (el contenido) y <fileId>.json (nombre, tipo, tamaño). Son del agente, no de una versión:
una versión publicada manda el archivo que hay hoy con ese id (si lo borran, el paso da error).
Se sirven sin sesión en /files/<agente>/<fileId>: el fileId es aleatorio (128 bits) y hace de llave.
Lo que manda la persona por WhatsApp o Telegram (store) va en la misma carpeta con «session» en el .json: no sale en la
lista, se sirve solo a quien ve el agente (server.py) y se borra con la conversación (forget / prune)."""
import base64
import json
import os
import re
import secrets
import time
import urllib.parse

from . import agents_dir, write_json

MAX_BYTES = 10 * 1024 * 1024
# el tipo sale de la extensión, nunca de lo que diga el navegador: nada de HTML ni SVG (correrían en este sitio)
TYPES = {"pdf": "application/pdf", "png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg", "gif": "image/gif",
         "webp": "image/webp", "txt": "text/plain; charset=utf-8", "csv": "text/csv; charset=utf-8",
         "doc": "application/msword", "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
         "xls": "application/vnd.ms-excel", "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
         "ppt": "application/vnd.ms-powerpoint", "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
         "zip": "application/zip"}
INLINE = ("application/pdf", "image/", "text/plain", "audio/", "video/")       # se abren en el navegador; el resto se descarga
# lo que se acepta de un cliente por WhatsApp/Telegram: tipo (sin parámetros) -> extensión. Nada que corra en el navegador
INBOUND = {"image/jpeg": "jpg", "image/png": "png", "image/webp": "webp", "image/gif": "gif",
           "audio/ogg": "ogg", "audio/opus": "opus", "audio/mpeg": "mp3", "audio/mp4": "m4a", "audio/aac": "aac", "audio/amr": "amr",
           "audio/wav": "wav", "audio/webm": "webm", "video/mp4": "mp4", "video/3gpp": "3gp", "application/pdf": "pdf",
           "text/plain": "txt", "text/csv": "csv", "application/msword": "doc", "application/vnd.ms-excel": "xls",
           "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "docx",
           "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": "xlsx", "application/zip": "zip"}
MAX_INBOUND = 16 * 1024 * 1024
AGENT_ID = re.compile(r"[0-9a-f]{8}")
FILE_ID = re.compile(r"[A-Za-z0-9_-]{22}")


def folder(agent_id):
    if not AGENT_ID.fullmatch(str(agent_id)):
        raise ValueError("agente inválido")
    return os.path.join(agents_dir(), agent_id + ".files")


def public(agent_id, meta):
    """Lo que viaja en la respuesta del bot y en la lista: sin rutas del disco."""
    return {"id": meta["id"], "name": meta["name"], "mime": meta["mime"].split(";")[0], "size": meta["size"],
            "url": "/files/%s/%s" % (agent_id, meta["id"])}


def _meta(agent_id, file_id):
    if not FILE_ID.fullmatch(str(file_id or "")):
        return None
    try:
        with open(os.path.join(folder(agent_id), file_id + ".json"), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def listing(agent_id):
    try:
        names = os.listdir(folder(agent_id))
    except (OSError, ValueError):
        return []
    metas = [_meta(agent_id, n[:-5]) for n in names if n.endswith(".json")]
    return [public(agent_id, m) for m in sorted(filter(None, metas), key=lambda m: m["uploaded"]) if not m.get("session")]


def _metas(agent_id):
    try:
        return [m for m in (_meta(agent_id, n[:-5]) for n in os.listdir(folder(agent_id)) if n.endswith(".json")) if m]
    except (OSError, ValueError):
        return []


def store(agent_id, session, name, mime, body):
    """Un archivo que mandó la persona (foto, audio, documento) en esa conversación. ValueError si no se acepta."""
    mime = str(mime or "").split(";")[0].strip().lower()
    if mime not in INBOUND:
        raise ValueError("ese tipo de archivo no se acepta (%s)" % (mime or "sin tipo"))
    if not body:
        raise ValueError("el archivo está vacío")
    if len(body) > MAX_INBOUND:
        raise ValueError("el archivo es muy grande (máximo %d MB)" % (MAX_INBOUND // 1024 // 1024))
    base = re.sub(r"[\x00-\x1f\x7f/\\]", "", os.path.basename(str(name or "").replace("\\", "/"))).strip()[:100]
    name = base if base.lower().endswith("." + INBOUND[mime]) else (base.rpartition(".")[0] or base or mime.split("/")[0]) + "." + INBOUND[mime]
    file_id = secrets.token_urlsafe(16)
    meta = {"id": file_id, "name": name, "mime": mime, "size": len(body), "uploaded": time.strftime("%Y-%m-%dT%H:%M:%S"), "session": session}
    os.makedirs(folder(agent_id), exist_ok=True)
    with open(os.path.join(folder(agent_id), file_id), "wb") as f:
        f.write(body)
    write_json(os.path.join(folder(agent_id), file_id + ".json"), meta)
    return public(agent_id, meta)


def session_of(agent_id, file_id):
    """La conversación de un archivo que mandó una persona; None si es del bot (o no existe)."""
    return ((_meta(agent_id, file_id) if AGENT_ID.fullmatch(str(agent_id)) else None) or {}).get("session")


def prune(agent_id, keep=None, session=None):
    """Borra los archivos de las personas: los de `session`, o los de conversaciones que ya no están en `keep`."""
    for m in _metas(agent_id):
        if m.get("session") and (m["session"] == session if session else m["session"] not in keep):
            delete(agent_id, m["id"])


def find(agent_id, ref):
    """Un archivo por id o, si no, por nombre (sin importar mayúsculas; con nombres repetidos, el último subido)."""
    meta = _meta(agent_id, ref)
    if meta:
        return public(agent_id, meta)
    named = [f for f in listing(agent_id) if f["name"].lower() == str(ref or "").strip().lower()]
    return named[-1] if named else None


def save(agent_id, name, data):
    """data en base64 (o «data:...;base64,...», como lo manda la interfaz)."""
    name = re.sub(r"[\x00-\x1f\x7f/\\]", "", os.path.basename(str(name or "").replace("\\", "/"))).strip()[:120]
    ext = name.rpartition(".")[2].lower() if "." in name else ""
    if ext not in TYPES:
        raise ValueError("ese tipo de archivo no se puede enviar. Sirven: %s" % ", ".join(sorted(TYPES)))
    try:
        body = base64.b64decode(str(data or "").rpartition(",")[2], validate=True)
    except ValueError:
        raise ValueError("«data» tiene que ser el archivo en base64") from None
    if not body:
        raise ValueError("el archivo está vacío")
    if len(body) > MAX_BYTES:
        raise ValueError("el archivo es muy grande (máximo %d MB)" % (MAX_BYTES // 1024 // 1024))
    file_id = secrets.token_urlsafe(16)
    meta = {"id": file_id, "name": name, "mime": TYPES[ext], "size": len(body), "uploaded": time.strftime("%Y-%m-%dT%H:%M:%S")}
    os.makedirs(folder(agent_id), exist_ok=True)
    with open(os.path.join(folder(agent_id), file_id), "wb") as f:
        f.write(body)
    write_json(os.path.join(folder(agent_id), file_id + ".json"), meta)
    return public(agent_id, meta)


def delete(agent_id, file_id):
    if _meta(agent_id, file_id):
        for name in (file_id, file_id + ".json"):
            try:
                os.remove(os.path.join(folder(agent_id), name))
            except OSError:
                pass


def read(agent_id, file_id):
    """(contenido, headers) para servirlo, o None. Solo ids con el formato exacto: no hay forma de salir de la carpeta."""
    meta = _meta(agent_id, file_id) if AGENT_ID.fullmatch(str(agent_id)) else None
    if not meta:
        return None
    try:
        with open(os.path.join(folder(agent_id), file_id), "rb") as f:
            body = f.read()
    except OSError:
        return None
    plain = re.sub(r'[^A-Za-z0-9._ -]', "_", meta["name"])
    how = "inline" if meta["mime"].startswith(INLINE) else "attachment"
    return body, {"Content-Type": meta["mime"], "X-Content-Type-Options": "nosniff", "Cache-Control": "private, max-age=300",
                  "Content-Disposition": "%s; filename=\"%s\"; filename*=UTF-8''%s" % (how, plain, urllib.parse.quote(meta["name"]))}
