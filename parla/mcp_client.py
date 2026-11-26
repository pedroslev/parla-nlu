"""Parla como CLIENTE de MCP (Streamable HTTP, JSON-RPC 2.0): initialize -> tools/list -> tools/call.
Solo HTTP: un servidor stdio sería lanzar un proceso desde la config del bot, y eso no se permite.
Lo que devuelve un servidor MCP es dato para la IA, nunca se ejecuta. Solo stdlib. Lanza MCPError."""
import json
import threading
import time
import urllib.error
import urllib.request

PROTOCOL = "2025-06-18"
CACHE_SECONDS = 300          # tools/list y la sesión de cada servidor se reusan unos minutos
MAX_BODY = 1_000_000
_cache, _lock = {}, threading.Lock()   # (url, auth) -> {"at", "session", "tools"}


class MCPError(Exception):
    pass


def _post(url, payload, auth=None, session=None, timeout=10):
    """Un mensaje JSON-RPC. -> (respuesta con ese id o None si es notificación, Mcp-Session-Id)."""
    headers = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream",
               "MCP-Protocol-Version": PROTOCOL}
    if auth:
        headers["Authorization"] = auth if " " in auth else "Bearer " + auth
    if session:
        headers["Mcp-Session-Id"] = session
    req = urllib.request.Request(url, data=json.dumps(payload).encode(), headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            ctype, sid = r.headers.get("Content-Type") or "", r.headers.get("Mcp-Session-Id") or session
            raw = r.read(MAX_BODY).decode("utf-8", "replace")
    except urllib.error.HTTPError as error:
        raise MCPError("el servidor MCP respondió %s" % error.code) from None
    except (urllib.error.URLError, OSError) as error:
        raise MCPError("no pude conectar con el servidor MCP: %s" % getattr(error, "reason", error)) from None
    if "id" not in payload:
        return None, sid
    if "text/event-stream" in ctype:     # SSE: cada evento trae un data: con un mensaje JSON-RPC
        messages, data = [], []
        for line in raw.splitlines() + [""]:
            if line.startswith("data:"):
                data.append(line[5:].lstrip())
            elif not line.strip() and data:
                messages.append("\n".join(data))
                data = []
    else:
        messages = [raw]
    for text in messages:
        try:
            msg = json.loads(text)
        except ValueError:
            continue
        for m in msg if isinstance(msg, list) else [msg]:
            if isinstance(m, dict) and m.get("id") == payload["id"]:
                if m.get("error"):
                    raise MCPError("error del servidor MCP: %s" % str((m["error"] or {}).get("message") or m["error"])[:300])
                return m.get("result") or {}, sid
    raise MCPError("el servidor MCP no devolvió una respuesta válida")


def _session(url, auth, timeout):
    result, sid = _post(url, {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
        "protocolVersion": PROTOCOL, "capabilities": {}, "clientInfo": {"name": "parla", "version": "1"}}}, auth, None, timeout)
    _post(url, {"jsonrpc": "2.0", "method": "notifications/initialized"}, auth, sid, timeout)
    return sid


def _entry(url, auth, timeout, fresh=False):
    key = (url, auth or "")
    with _lock:
        hit = _cache.get(key)
    if hit and not fresh and time.time() - hit["at"] < CACHE_SECONDS:
        return hit
    sid = _session(url, auth, timeout)
    tools, cursor = [], None
    for _ in range(10):                  # paginado (nextCursor), con tope
        result, sid = _post(url, {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {"cursor": cursor} if cursor else {}},
                            auth, sid, timeout)
        tools += [t for t in result.get("tools") or [] if isinstance(t, dict) and isinstance(t.get("name"), str)]
        cursor = result.get("nextCursor")
        if not cursor:
            break
    hit = {"at": time.time(), "session": sid, "tools": tools}
    with _lock:
        _cache[key] = hit
    return hit


def list_tools(url, auth=None, timeout=10, fresh=False):
    """[{name, description, inputSchema}] del servidor (cacheado CACHE_SECONDS)."""
    return [{"name": t["name"], "description": str(t.get("description") or "")[:500],
             "inputSchema": t.get("inputSchema") if isinstance(t.get("inputSchema"), dict) else {}}
            for t in _entry(url, auth, timeout, fresh)["tools"]]


def call_tool(url, name, args, auth=None, timeout=10):
    """-> (ok, texto). ok False si el servidor marcó isError. La sesión vencida se renueva una vez."""
    for attempt in (0, 1):
        hit = _entry(url, auth, timeout, fresh=attempt == 1)
        try:
            result, _ = _post(url, {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": name, "arguments": args}},
                              auth, hit["session"], timeout)
            break
        except MCPError as error:
            if attempt or not hit["session"] or not any(c in str(error) for c in ("404", "400")):
                raise
    parts = [c.get("text") for c in result.get("content") or [] if isinstance(c, dict) and c.get("type") == "text"]
    if not parts and result.get("structuredContent") is not None:
        parts = [json.dumps(result["structuredContent"], ensure_ascii=False)]
    return not result.get("isError"), "\n".join(str(p) for p in parts if p is not None)
