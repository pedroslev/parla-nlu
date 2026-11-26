"""El servidor HTTP/1.1 de Parla sobre asyncio (solo biblioteca estándar; uvloop si está instalado).

- Un loop atiende todas las conexiones (keep-alive, miles abiertas a la vez) con los mismos topes que antes:
  64 KB de encabezados, 25 MB de cuerpo, 30 s sin datos y se corta (PARLA_IDLE_TIMEOUT).
- Cada pedido corre el mismo código de siempre (server.Handler: auth, Origin/Host, límites, auditoría, métricas)
  en un pool acotado de hilos (PARLA_THREADS). /static/*.js sale directo del loop, desde memoria.
- Una conversación es serie: los turnos del mismo bot+sessionId esperan en fila (asyncio.Lock FIFO, que se borra
  cuando no queda nadie); conversaciones distintas corren en paralelo.
- Canales de empuje sobre la misma conexión: WebSocket (RFC 6455) en /api/v1/bots/{bot}/ws y SSE en
  /api/v1/bots/{bot}/sessions/{sid}/stream, /api/agents/{id}/inbox/stream y /api/agents/{id}/campaigns/stream.
  Voz en tiempo real (voicestream.py): /api/v1/bots/{bot}/voice/ws y /api/v1/bots/{bot}/phone/{twilio|jambonz}/stream.
  Autorizan corriendo el pedido de polling equivalente por el Handler (las mismas reglas, sin duplicarlas) y
  después escuchan el bus (bus.py). El protocolo está en docs/api.md.
"""
import asyncio
import base64
import concurrent.futures
import contextlib
import hashlib
import http.client
import io
import json
import os
import re
import struct
import sys
import urllib.parse

from . import auth, bus, cluster, db, i18n

MAX_HEADER = 65536
PRELOAD = 1_000_000          # cuerpos hasta 1 MB se leen en el loop; más grandes, el Handler los lee a pedido (después de auth)
BODY_CAP = 25_000_000
IDLE = float(os.environ.get("PARLA_IDLE_TIMEOUT") or 30)
THREADS = int(os.environ.get("PARLA_THREADS") or 64)
WS_MAX = int(os.environ.get("PARLA_WS_MAX_MESSAGE") or 1_000_000)
WS_IDLE, PING, SSE_PING = 120, 30, 15
GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"
POOL = concurrent.futures.ThreadPoolExecutor(THREADS, thread_name_prefix="parla-http")
STATS = {"http": 0, "ws": 0, "sse": 0, "voice": 0, "inflight": 0}
_locks = {}                  # (bot, sessionId) -> [asyncio.Lock, esperando]: la fila de cada conversación activa
_static = {}                 # archivo -> (mtime, bytes)
PORT = [8000]


def _app():
    return sys.modules.get("parla.server") or sys.modules["__main__"]


class _Server:
    @property
    def server_address(self):
        return ("", PORT[0])


class _Body:
    """rfile para cuerpos grandes: el hilo del Handler lee del socket del loop solo si llega a leer."""
    def __init__(self, reader, loop, length):
        self.reader, self.loop, self.left = reader, loop, length

    def read(self, n=-1):
        n = self.left if n is None or n < 0 else min(n, self.left)
        if n <= 0:
            return b""
        data = asyncio.run_coroutine_threadsafe(asyncio.wait_for(self.reader.readexactly(n), IDLE), self.loop).result()
        self.left -= len(data)
        return data


def call(method, target, headers, body=b"", peer=("127.0.0.1", 0), rfile=None):
    """Corre un pedido por server.Handler sin socket (en un hilo del pool) y devuelve la respuesta en bytes."""
    app = _app()
    h = app.Handler.__new__(app.Handler)
    h.command, h.path, h.request_version = method, target, "HTTP/1.1"
    h.protocol_version, h.requestline = "HTTP/1.1", "%s %s HTTP/1.1" % (method, target)
    h.headers, h.rfile, h.wfile = headers, rfile or io.BytesIO(body), io.BytesIO()
    h.client_address, h.server, h.close_connection = peer, _Server(), False
    h.safely(method)
    return h.wfile.getvalue() or b"HTTP/1.1 500 Internal Server Error\r\nContent-Length: 0\r\n\r\n"


def _parse(raw):
    """(status, encabezados, JSON o None) de una respuesta del Handler."""
    head, _, body = raw.partition(b"\r\n\r\n")
    line, _, rest = head.partition(b"\r\n")
    headers = http.client.parse_headers(io.BytesIO(rest + b"\r\n"))
    try:
        data = json.loads(body) if body else None
    except ValueError:
        data = None
    return int(line.split()[1]), headers, data


def _headers(original, **extra):
    """Los encabezados del pedido original (cookie, Authorization, Origin, Host…) para un pedido interno."""
    drop = {"content-length", "content-type", "transfer-encoding", "upgrade", "connection", "expect"} | {k.lower() for k in extra}
    lines = ["%s: %s" % (k, v) for k, v in original.items() if k.lower() not in drop and not k.lower().startswith("sec-websocket")]
    lines += ["%s: %s" % (k.replace("_", "-"), v) for k, v in extra.items()]
    return http.client.parse_headers(io.BytesIO(("\r\n".join(lines) + "\r\n\r\n").encode("latin-1", "replace")))


async def run(*args):
    STATS["inflight"] += 1
    try:
        return await asyncio.get_running_loop().run_in_executor(POOL, *args)
    finally:
        STATS["inflight"] -= 1


@contextlib.asynccontextmanager
async def serial(key):
    """Turnos de una misma conversación, de a uno y en el orden en que llegaron. ponytail: la llave es el bot como
    vino en la URL (id, nombre o slug): la misma charla nombrada de dos formas a la vez no queda en la misma fila."""
    if key is None:
        yield
        return
    entry = _locks.get(key) or _locks.setdefault(key, [asyncio.Lock(), 0])
    entry[1] += 1
    try:
        async with entry[0]:
            if not db.PG:
                yield
                return
            name = "turn:%s/%s" % key        # con Postgres, también en fila con las otras réplicas
            held = await run(cluster.acquire, name)
            try:
                yield
            finally:
                await run(cluster.release, held, name)
    finally:
        entry[1] -= 1
        if not entry[1]:
            _locks.pop(key, None)


def _simple(status, text, close=True):
    body = json.dumps({"error": text}).encode()
    return (b"HTTP/1.1 %d %s\r\nContent-Type: application/json\r\nContent-Length: %d\r\n%s\r\n" % (
        status, http.client.responses.get(status, "").encode(), len(body), b"Connection: close\r\n" if close else b"")) + body


def _static_file(name):
    path = os.path.join(_app().HERE, "static", name)
    try:
        mtime = os.stat(path).st_mtime_ns
    except OSError:
        return None
    hit = _static.get(path)
    if not hit or hit[0] != mtime:
        with open(path, "rb") as f:
            hit = _static[path] = (mtime, f.read())
    return b"HTTP/1.1 200 OK\r\nContent-Type: text/javascript; charset=utf-8\r\nContent-Length: %d\r\n\r\n%s" % (len(hit[1]), hit[1])


EVENTS = re.compile(r"/api/v1/bots/([^/]+)/(events|audio)")
WS = re.compile(r"/api/v1/bots/([^/]+)/ws")
VOICE_WS = re.compile(r"/api/v1/bots/([^/]+)/(?:voice/ws|phone/(twilio|jambonz)/stream)")
SSE = re.compile(r"/api/v1/bots/([^/]+)/sessions/([^/]+)/stream|/api/agents/([0-9a-f]{8})/(inbox|campaigns)/stream")


async def client(reader, writer):
    STATS["http"] += 1
    peer = tuple((writer.get_extra_info("peername") or ("?", 0))[:2])
    try:
        while await _one(reader, writer, peer):
            pass
    except (ConnectionError, asyncio.IncompleteReadError, asyncio.TimeoutError, concurrent.futures.TimeoutError):
        pass
    finally:
        STATS["http"] -= 1
        writer.close()


async def _one(reader, writer, peer):
    """Un pedido. True si la conexión sigue (keep-alive)."""
    try:
        head = await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), IDLE)
    except asyncio.LimitOverrunError:
        writer.write(_simple(431, "encabezados demasiado grandes"))
        return False
    try:
        line, _, rest = head.partition(b"\r\n")
        method, target, version = line.decode("latin-1").split(" ")
        if not version.startswith("HTTP/1.") or not target.startswith("/"):
            raise ValueError
        headers = http.client.parse_headers(io.BytesIO(rest))      # más de 100 encabezados: HTTPException
    except (ValueError, http.client.HTTPException):
        writer.write(_simple(400, "pedido inválido"))
        return False
    keep = version == "HTTP/1.1" and (headers.get("Connection") or "").lower() != "close"
    if headers.get("Transfer-Encoding"):
        writer.write(_simple(411, "mandá Content-Length (chunked no está soportado)"))
        return False
    raw = headers.get("Content-Length") or "0"
    length = int(raw) if raw.isascii() and raw.isdigit() else 0       # inválido: el Handler contesta 400 y se cierra
    keep = keep and (raw.isascii() and raw.isdigit())
    path = target.split("?", 1)[0]
    if method == "GET" and (headers.get("Upgrade") or "").lower() == "websocket" and WS.fullmatch(path):
        await websocket(reader, writer, headers, peer, WS.fullmatch(path).group(1))
        return False
    if method == "GET" and (headers.get("Upgrade") or "").lower() == "websocket" and VOICE_WS.fullmatch(path):
        from . import voicestream              # voz en tiempo real: navegador, Twilio Media Streams, jambonz listen
        await voicestream.serve(reader, writer, headers, peer, target, *VOICE_WS.fullmatch(path).groups())
        return False
    if method == "GET" and SSE.fullmatch(path):
        await sse(writer, target, headers, peer, SSE.fullmatch(path))
        return False
    static = method == "GET" and re.fullmatch(r"/static/([a-z0-9-]+\.js)", path)
    if static and _static_file(static.group(1)):
        writer.write(_static_file(static.group(1)))
        await writer.drain()
        return keep
    if length > BODY_CAP:
        writer.write(_simple(413, "demasiado grande"))
        return False
    if length and (headers.get("Expect") or "").lower() == "100-continue":
        writer.write(b"HTTP/1.1 100 Continue\r\n\r\n")
    rfile, body, key = None, b"", None
    if length <= PRELOAD:
        body = await asyncio.wait_for(reader.readexactly(length), IDLE) if length else b""
        match = method == "POST" and EVENTS.fullmatch(path)
        if match:
            try:
                sid = json.loads(body).get("sessionId")
                key = (match.group(1), sid) if isinstance(sid, str) else None
            except (ValueError, AttributeError):
                pass
    else:
        rfile = _Body(reader, asyncio.get_running_loop(), length)
    async with serial(key):
        out = await run(call, method, target, headers, body, peer, rfile)
    writer.write(out)
    await writer.drain()
    return keep and not (rfile and rfile.left)       # cuerpo sin leer (lo rechazó antes): no se puede seguir en esta conexión


# ---------- SSE ----------

def _event(name, data):
    return ("event: %s\ndata: %s\n\n" % (name, json.dumps(data, ensure_ascii=False))).encode()


def _since(record, cursor):
    history = record.get("history") or []
    return {"sessionId": record.get("sessionId"), "messages": history[cursor:], "next": len(history),
            "handoff": bool((record.get("handoff") or {}).get("active")), "ended": record.get("ended")}


async def sse(writer, target, headers, peer, match):
    query = dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(target).query))
    ref, sid, aid, what = match.groups()
    if ref:
        agent = await run(_app().find_bot, urllib.parse.unquote(ref))
        topic = "session:%s:%s" % ((agent or {}).get("id"), urllib.parse.unquote(sid))
        probe = lambda after: "/api/v1/bots/%s/sessions/%s/messages?after=%s" % (ref, sid, after)
    else:
        topic = ("inbox:" if what == "inbox" else "campaign:") + aid
        probe = lambda after: "/api/agents/%s/%s" % (aid, what)
    try:
        cursor = max(0, int(query.get("after") or 0))
    except ValueError:
        cursor = 0
    STATS["sse"] += 1
    try:
        with bus.subscribe(topic) as queue:          # antes del primer estado: no se pierde nada en el medio
            raw = await run(call, "GET", probe(cursor), headers, b"", peer)
            status, out, data = _parse(raw)
            if status != 200:
                writer.write(raw)
                return
            cors = out.get("Access-Control-Allow-Origin")
            writer.write(b"HTTP/1.1 200 OK\r\nContent-Type: text/event-stream; charset=utf-8\r\nCache-Control: no-cache\r\n"
                         b"X-Accel-Buffering: no\r\n" + (b"Access-Control-Allow-Origin: %s\r\nVary: Origin\r\n" % cors.encode() if cors else b"")
                         + b"\r\n" + b"retry: 3000\n\n" + _event("messages" if ref else what, data))
            await writer.drain()
            cursor, last = (data or {}).get("next", cursor), data
            while True:
                try:
                    event = await asyncio.wait_for(queue.get(), SSE_PING)
                except asyncio.TimeoutError:
                    writer.write(b": ping\n\n")
                    await writer.drain()
                    continue
                if ref and event["type"] in ("delta", "replace"):
                    writer.write(_event(event["type"], event))
                elif ref and event["type"] == "saved":
                    if len(event["record"].get("history") or []) != cursor:
                        update = _since(event["record"], cursor)
                        cursor = update["next"]
                        writer.write(_event("messages", update))
                else:                                # bandeja, campañas o overflow: se vuelve a pedir (con auth) y se manda si cambió
                    await asyncio.sleep(0.3)         # junta ráfagas
                    while not queue.empty():
                        queue.get_nowait()
                    status, _, data = _parse(await run(call, "GET", probe(cursor), headers, b"", peer))
                    if status != 200:
                        return
                    if data != last:
                        writer.write(_event("messages" if ref else what, data))
                        cursor, last = (data or {}).get("next", cursor), data
                await writer.drain()
    finally:
        STATS["sse"] -= 1


# ---------- WebSocket (RFC 6455) ----------

class Closed(Exception):
    def __init__(self, code, reason=""):
        super().__init__(reason)
        self.code, self.reason = code, reason


def frame(op, payload=b""):
    n = len(payload)
    size = bytes([n]) if n < 126 else b"\x7e" + struct.pack("!H", n) if n < 65536 else b"\x7f" + struct.pack("!Q", n)
    return bytes([0x80 | op]) + size + payload


async def read_frame(reader):
    """(fin, opcode, datos) de un frame del cliente: enmascarado, sin RSV, control <= 125 y sin fragmentar."""
    b1, b2 = await reader.readexactly(2)
    fin, op, n = bool(b1 & 0x80), b1 & 0x0F, b2 & 0x7F
    if b1 & 0x70 or not b2 & 0x80:
        raise Closed(1002, "frame inválido")
    if n == 126:
        n = struct.unpack("!H", await reader.readexactly(2))[0]
    elif n == 127:
        n = struct.unpack("!Q", await reader.readexactly(8))[0]
    if op >= 8 and (n > 125 or not fin):
        raise Closed(1002, "frame de control inválido")
    if n > WS_MAX:
        raise Closed(1009, "mensaje demasiado grande")
    mask = await reader.readexactly(4)
    data = await reader.readexactly(n)
    if n:
        data = (int.from_bytes(data, "big") ^ int.from_bytes((mask * (n // 4 + 1))[:n], "big")).to_bytes(n, "big")
    return fin, op, data


async def messages(reader, binary=False):
    """Los mensajes de texto del cliente ya armados (fragmentos juntos); contesta ping y cierra con el código que va.
    binary: también los binarios (audio de voicestream.py), como ("binary", bytes)."""
    buf, kind = None, 1
    while True:
        fin, op, data = await asyncio.wait_for(read_frame(reader), WS_IDLE)
        if op == 8:
            code = struct.unpack("!H", data[:2])[0] if len(data) >= 2 else 1000
            raise Closed(code if 1000 <= code < 5000 and code not in (1004, 1005, 1006, 1015) else 1002)
        if op == 9:
            yield ("ping", data)
            continue
        if op == 10:
            continue
        if op == 0:
            if buf is None:
                raise Closed(1002, "continuación sin mensaje")
            buf += data
        elif op in (1, 2):
            if buf is not None:
                raise Closed(1002, "mensaje nuevo a mitad de otro")
            if op == 2 and not binary:
                raise Closed(1003, "solo mensajes de texto (JSON)")
            buf, kind = data, op
        else:
            raise Closed(1002, "opcode desconocido")
        if len(buf) > WS_MAX:
            raise Closed(1009, "mensaje demasiado grande")
        if fin and kind == 2:
            buf, data = None, buf
            yield ("binary", data)
        elif fin:
            try:
                text = buf.decode("utf-8")
            except UnicodeDecodeError:
                raise Closed(1007, "texto que no es UTF-8") from None
            buf = None
            yield ("text", text)


def _ours(headers, origin):
    host = urllib.parse.urlsplit(origin).netloc.lower()
    return host in {"127.0.0.1:%d" % PORT[0], "localhost:%d" % PORT[0]} | set(auth.hosts())


def handshake_ok(headers):
    key = headers.get("Sec-WebSocket-Key") or ""
    try:
        return headers.get("Sec-WebSocket-Version") == "13" and "upgrade" in (headers.get("Connection") or "").lower() and len(base64.b64decode(key + "==")[:16]) == 16
    except ValueError:
        return False


def upgrade(writer, headers):
    accept = base64.b64encode(hashlib.sha1(((headers.get("Sec-WebSocket-Key") or "") + GUID).encode()).digest())
    writer.write(b"HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Accept: %s\r\n\r\n" % accept)


async def authorize(writer, headers, peer, ref):
    """¿Puede abrir un WebSocket de este bot? Las reglas de siempre: Origin propio o del widget, y sesión, API key o el
    widget público. Si no, ya contestó el error."""
    if not handshake_ok(headers):
        writer.write(_simple(400, "handshake de WebSocket inválido"))
        return False
    origin, app = headers.get("Origin"), _app()
    if origin and not _ours(headers, origin) and not await run(app.Handler.widget_origin, None, "/api/v1/bots/%s/events" % ref, origin):
        writer.write(_simple(403, "pedido de otro sitio web rechazado"))       # Cross-Site WebSocket Hijacking
        return False
    raw = await run(call, "GET", "/api/v1/bots/%s" % ref, headers, b"", peer)  # quién es: sesión, API key o el widget público
    status = _parse(raw)[0]
    if status != 200:
        agent = await run(app.find_bot, urllib.parse.unquote(ref))
        if status not in (401, 403) or not ((agent or {}).get("widget") or {}).get("enabled"):
            writer.write(raw)
            return False
    return True


async def websocket(reader, writer, headers, peer, ref):
    if not await authorize(writer, headers, peer, ref):
        return
    upgrade(writer, headers)
    STATS["ws"] += 1
    sock = _Socket(writer, headers, peer, ref)
    pinger = asyncio.create_task(sock.pinger())
    code = 1000
    try:
        async for kind, data in messages(reader):
            if kind == "ping":
                writer.write(frame(10, data))
            else:
                sock.tasks.add(asyncio.create_task(sock.handle(data)))      # en orden: sock.turn es FIFO
            await writer.drain()
    except Closed as closed:
        code = closed.code
    except (asyncio.TimeoutError, asyncio.IncompleteReadError, ConnectionError):
        code = 1001
    finally:
        STATS["ws"] -= 1
        pinger.cancel()
        sock.stop()
        for task in list(sock.tasks):
            task.cancel()
        with contextlib.suppress(Exception):
            writer.write(frame(8, struct.pack("!H", code)))
            await writer.drain()


class _Socket:
    """Una conexión WebSocket: los turnos van por el Handler (mismas reglas que POST /events) y lo que publica el bus
    de su conversación (personas de la bandeja, deltas de la IA) sale por el mismo socket."""

    def __init__(self, writer, headers, peer, ref):
        self.writer, self.headers, self.peer, self.ref = writer, headers, peer, ref
        self.turn, self.tasks, self.sid, self.cursor, self.follower = asyncio.Lock(), set(), None, 0, None

    def send(self, data):
        self.writer.write(frame(1, json.dumps(data, ensure_ascii=False).encode()))

    async def pinger(self):
        while True:
            await asyncio.sleep(PING)
            self.writer.write(frame(9, b"parla"))

    def stop(self):
        if self.follower:
            self.follower.cancel()

    async def handle(self, text):
        try:
            data = json.loads(text)
            if not isinstance(data, dict):
                raise ValueError
        except ValueError:
            return self.send(i18n.translate({"type": "error", "error": "cada mensaje tiene que ser un objeto JSON"}, i18n.lang_of(self.headers.get("Accept-Language"))))
        ref, mid = self.ref, data.pop("id", None)
        async with self.turn:
            if data.get("type") == "follow":            # escuchar una charla sin mandar nada (retomar el widget)
                path = "/api/v1/bots/%s/sessions/%s/messages?after=%s" % (ref, urllib.parse.quote(str(data.get("sessionId") or ""), safe=""),
                                                                           int(data.get("after") or 0) if str(data.get("after") or 0).isdigit() else 0)
                status, _, body = _parse(await run(call, "GET", path, self.headers, b"", self.peer))
                self.send({"type": "messages" if status == 200 else "error", "id": mid, "status": status, **(body or {})})
                if status == 200:
                    await self.follow(body["sessionId"], body["next"])
                return
            payload = json.dumps(data).encode()
            headers = _headers(self.headers, Content_Type="application/json", Content_Length=str(len(payload)))
            sid = data.get("sessionId") if isinstance(data.get("sessionId"), str) else None
            async with serial((ref, sid) if sid else None):
                status, _, body = _parse(await run(call, "POST", "/api/v1/bots/%s/events" % ref, headers, payload, self.peer))
            self.send({"type": "reply", "id": mid, "status": status, "body": body})
            if status == 200 and isinstance(body, dict) and body.get("sessionId") and isinstance(body.get("next"), int):
                await self.follow(body["sessionId"], body["next"])
        await self.writer.drain()

    async def follow(self, sid, cursor):
        self.cursor = cursor
        if sid == self.sid:
            return
        self.stop()
        self.sid = sid
        agent = await run(_app().find_bot, urllib.parse.unquote(self.ref))
        ready = asyncio.Event()
        self.follower = asyncio.create_task(self._listen("session:%s:%s" % ((agent or {}).get("id"), sid), ready))
        await ready.wait()

    async def _listen(self, topic, ready):
        with bus.subscribe(topic) as queue:
            ready.set()
            while True:
                event = await queue.get()
                if event["type"] in ("delta", "replace"):
                    self.send(event)                    # en vivo, aunque el turno siga corriendo
                elif event["type"] == "saved":
                    async with self.turn:               # lo de un turno propio ya salió en su «reply»
                        if len(event["record"].get("history") or []) > self.cursor:
                            update = _since(event["record"], self.cursor)
                            self.cursor = update["next"]
                            self.send(dict(update, type="messages"))
                elif event["type"] == "overflow":
                    self.send({"type": "overflow"})     # el cliente pide el historial de nuevo (follow)
                await self.writer.drain()


# ---------- arranque ----------

def _nofile():
    """Miles de conexiones necesitan miles de descriptores: sube el límite blando hasta el duro."""
    try:
        import resource
        soft, hard = resource.getrlimit(resource.RLIMIT_NOFILE)
        want = hard if hard != resource.RLIM_INFINITY else 65536
        if soft < want:
            resource.setrlimit(resource.RLIMIT_NOFILE, (min(want, 65536), hard))
    except (ImportError, ValueError, OSError):
        pass


async def _serve(host, port, ready=None):
    server = await asyncio.start_server(client, host, port, limit=MAX_HEADER, backlog=4096)
    PORT[0] = server.sockets[0].getsockname()[1]
    if ready:
        ready(PORT[0])
    async with server:
        await server.serve_forever()


def serve(host, port, ready=None):
    _nofile()
    PORT[0] = port
    try:
        import uvloop
        return uvloop.run(_serve(host, port, ready))
    except ImportError:
        return asyncio.run(_serve(host, port, ready))


def gauges():
    """Para /metrics."""
    return {"connections": [({"kind": k}, STATS[k]) for k in ("http", "ws", "sse", "voice")],
            "queues": [({"queue": "executor"}, POOL._work_queue.qsize()), ({"queue": "inflight"}, STATS["inflight"]),
                       ({"queue": "sessions"}, len(_locks)), ({"queue": "bus_subscribers"}, bus.subscribers())]}

