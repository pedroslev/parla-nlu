"""Carga contra un Parla de prueba (no es parte de run_all). Conversaciones de 5 turnos con textos únicos, keep-alive.

    .venv/bin/python tests/perf/load.py                          # levanta un servidor temporal y mide conc 1/10/50/200/1000
    .venv/bin/python tests/perf/load.py --conc 20 --seconds 10 --floor 30     # smoke de CI: falla si baja del piso o hay errores
    .venv/bin/python tests/perf/load.py --url http://127.0.0.1:8100 --bot <id> --conc 50
    .venv/bin/python tests/perf/load.py --idle 5000              # 5.000 conexiones SSE + WebSocket quietas: RSS del servidor
    .venv/bin/python tests/perf/load.py --ws --conc 50           # las mismas charlas por WebSocket

Imprime throughput, p50/p95/p99, errores y RSS/CPU del servidor. Usa examples/pizzeria.json en el entorno draft.
"""
import argparse
import asyncio
import base64
import json
import os
import random
import resource
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
GUSTOS = ["muzza", "fugazzeta", "napolitana", "calabresa", "jamón y morrones", "cuatro quesos"]
BARRIOS = ["Palermo", "Belgrano", "Caballito", "Almagro", "Villa Crespo", "Flores", "Boedo"]


def texts():
    return ["hola, buenas %d" % random.randint(1, 999),
            "quiero %d de %s para %s" % (random.randint(1, 5), random.choice(GUSTOS), random.choice(BARRIOS)),
            "me llamo %s %d" % (random.choice(["Ana", "Juan", "Lucía", "Pedro"]), random.randint(1, 99)),
            "Pérez", "Gorriti %d" % random.randint(100, 9999)]


def http(base, method, path, body=None):
    req = urllib.request.Request(base + path, json.dumps(body).encode() if body is not None else None,
                                 {"Content-Type": "application/json", "Origin": base}, method=method)
    with urllib.request.urlopen(req, timeout=600) as r:
        return json.loads(r.read())


def spawn(workers_env=None):
    """Servidor temporal en un puerto libre con datos descartables y el bot de la pizzería entrenado."""
    import socket
    data = tempfile.mkdtemp(prefix="parla-perf-")
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    env = dict(os.environ, PARLA_DATA=data, PARLA_USERS=os.path.join(data, "users.json"), **(workers_env or {}))
    env.setdefault("PARLA_EMBED_CACHE", os.path.join(ROOT, "data", "models", "embeddings"))
    proc = subprocess.Popen([sys.executable, os.path.join(ROOT, "app.py"), str(port)], cwd=ROOT, env=env,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    base = "http://127.0.0.1:%d" % port
    for _ in range(300):
        try:
            http(base, "GET", "/api/auth/me")
            break
        except OSError:
            time.sleep(0.2)
    with open(os.path.join(ROOT, "examples", "pizzeria.json"), encoding="utf-8") as f:
        agent = http(base, "POST", "/api/agents", {"import": json.load(f)})
    agent = agent.get("agent", agent)
    http(base, "POST", "/api/agents/%s/train" % agent["id"], {})
    return proc, base, agent["id"], data


def server_usage(pid):
    try:
        out = subprocess.run(["ps", "-o", "rss=,time=", "-p", str(pid)], capture_output=True, text=True).stdout.split()
        parts = [float(x) for x in out[1].replace("-", ":").split(":")]
        return int(out[0]) // 1024, sum(v * 60 ** i for i, v in enumerate(reversed(parts)))      # MB, segundos de CPU
    except (IndexError, ValueError):
        return 0, 0.0


class Conn:
    """Una conexión HTTP/1.1 keep-alive mínima (lo justo para medir sin que el cliente sea el cuello de botella)."""
    def __init__(self, host, port):
        self.host, self.port, self.r, self.w = host, port, None, None

    async def post(self, path, body):
        if self.w is None:
            self.r, self.w = await asyncio.open_connection(self.host, self.port, limit=1 << 22)
        data = json.dumps(body).encode()
        origin = "http://%s:%d" % (self.host, self.port)
        self.w.write(("POST %s HTTP/1.1\r\nHost: %s:%d\r\nOrigin: %s\r\nContent-Type: application/json\r\nContent-Length: %d\r\n\r\n"
                      % (path, self.host, self.port, origin, len(data))).encode() + data)
        head = await self.r.readuntil(b"\r\n\r\n")
        status = int(head.split(b" ", 2)[1])
        length = next(int(l.split(b":")[1]) for l in head.split(b"\r\n") if l.lower().startswith(b"content-length:"))
        payload = await self.r.readexactly(length)
        if status != 200:
            raise RuntimeError("HTTP %d %s" % (status, payload[:200]))
        return json.loads(payload)

    def close(self):
        if self.w:
            self.w.close()
            self.w = None


async def ws_connect(host, port, path):
    r, w = await asyncio.open_connection(host, port, limit=1 << 22)
    key = base64.b64encode(os.urandom(16)).decode()
    w.write(("GET %s HTTP/1.1\r\nHost: %s:%d\r\nOrigin: http://%s:%d\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n"
             "Sec-WebSocket-Key: %s\r\nSec-WebSocket-Version: 13\r\n\r\n" % (path, host, port, host, port, key)).encode())
    head = await r.readuntil(b"\r\n\r\n")
    if b" 101 " not in head.split(b"\r\n")[0]:
        raise RuntimeError(head[:200])
    return r, w


def ws_frame(text, op=1):
    data, mask = text.encode() if isinstance(text, str) else text, os.urandom(4)
    n = len(data)
    size = bytes([0x80 | n]) if n < 126 else bytes([0x80 | 126]) + n.to_bytes(2, "big") if n < 65536 else bytes([0x80 | 127]) + n.to_bytes(8, "big")
    return bytes([0x80 | op]) + size + mask + bytes(b ^ mask[i % 4] for i, b in enumerate(data))


async def ws_read(r):
    b1, b2 = await r.readexactly(2)
    n = b2 & 0x7F
    if n == 126:
        n = int.from_bytes(await r.readexactly(2), "big")
    elif n == 127:
        n = int.from_bytes(await r.readexactly(8), "big")
    return b1 & 0x0F, await r.readexactly(n)


async def ws_reply(r):
    while True:
        op, data = await ws_read(r)
        if op == 1:
            msg = json.loads(data)
            if msg.get("type") == "reply":
                return msg


async def load(base, bot, conc, seconds, use_ws=False):
    host, port = base.split("//")[1].split(":")
    port = int(port)
    lat, errors, stop = [], [0], time.monotonic() + seconds
    path = "/api/v1/bots/%s/events" % bot

    async def user(i):
        conn, n = Conn(host, port), 0
        ws = None
        while time.monotonic() < stop:
            sid = "load-%d-%d-%d" % (i, n, random.randint(0, 1 << 30))
            n += 1
            try:
                if use_ws and ws is None:
                    ws = await ws_connect(host, port, "/api/v1/bots/%s/ws" % bot)
                async def send(body):
                    if ws:
                        ws[1].write(ws_frame(json.dumps(body)))
                        reply = await ws_reply(ws[0])
                        if reply["status"] != 200:
                            raise RuntimeError(reply)
                        return reply["body"]
                    return await conn.post(path, body)
                await send({"type": "start", "sessionId": sid, "environment": "draft"})
                for text in texts():
                    if time.monotonic() >= stop:
                        break
                    t = time.perf_counter()
                    await send({"type": "message", "sessionId": sid, "text": text, "environment": "draft"})
                    lat.append(time.perf_counter() - t)
            except Exception:  # noqa: BLE001 - se cuenta y se sigue con otra conexión
                errors[0] += 1
                conn.close()
                if ws:
                    ws[1].close()
                    ws = None
        conn.close()
        if ws:
            ws[1].close()

    t0 = time.monotonic()
    await asyncio.gather(*(user(i) for i in range(conc)))
    took = time.monotonic() - t0
    lat.sort()
    q = lambda p: lat[min(len(lat) - 1, int(p * len(lat)))] * 1000 if lat else 0
    return {"conc": conc, "turns": len(lat), "throughput": len(lat) / took, "p50": q(.5), "p95": q(.95), "p99": q(.99), "errors": errors[0]}


async def idle(base, bot, n):
    """n/2 SSE y n/2 WebSocket abiertos y quietos: ¿cuántos quedan vivos y cuánta memoria usa el servidor?"""
    host, port = base.split("//")[1].split(":")
    port = int(port)
    first = http(base, "POST", "/api/v1/bots/%s/events" % bot, {"type": "start", "sessionId": "idle-0", "environment": "draft"})
    socks, failed = [], [0]

    async def sse(i):
        try:
            r, w = await asyncio.open_connection(host, port)
            w.write(("GET /api/v1/bots/%s/sessions/idle-0/stream?after=%d HTTP/1.1\r\nHost: %s:%d\r\n\r\n" % (bot, first["next"], host, port)).encode())
            head = await r.readuntil(b"\r\n\r\n")
            assert b" 200 " in head.split(b"\r\n")[0], head[:100]
            await r.readuntil(b"\n\n")
            await r.readuntil(b"\n\n")       # el estado inicial
            socks.append((r, w))
        except Exception:  # noqa: BLE001
            failed[0] += 1

    async def ws(i):
        try:
            r, w = await ws_connect(host, port, "/api/v1/bots/%s/ws" % bot)
            w.write(ws_frame(json.dumps({"type": "follow", "sessionId": "idle-0"})))
            op, data = await ws_read(r)
            assert json.loads(data)["type"] == "messages"
            socks.append((r, w))
        except Exception:  # noqa: BLE001
            failed[0] += 1

    t0 = time.monotonic()
    for start in range(0, n, 200):              # de a 200 para no desbordar el backlog
        await asyncio.gather(*((sse if i % 2 else ws)(i) for i in range(start, min(n, start + 200))))
    opened = time.monotonic() - t0
    # un mensaje a esa charla tiene que llegarles a todos por el bus
    http(base, "POST", "/api/v1/bots/%s/events" % bot, {"type": "message", "sessionId": "idle-0", "text": "hola", "environment": "draft"})
    got = [0]

    async def wait(rw):
        try:
            await asyncio.wait_for(rw[0].read(1), 30)
            got[0] += 1
        except Exception:  # noqa: BLE001
            pass
    t1 = time.monotonic()
    await asyncio.gather(*(wait(s) for s in socks))
    fanout = time.monotonic() - t1
    return {"open": len(socks), "failed": failed[0], "open_s": opened, "delivered": got[0], "fanout_s": fanout, "socks": socks}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url")
    ap.add_argument("--bot")
    ap.add_argument("--pid", type=int)
    ap.add_argument("--conc", type=int, nargs="*", default=[1, 10, 50, 200, 1000])
    ap.add_argument("--seconds", type=float, default=15)
    ap.add_argument("--floor", type=float, help="turnos/s mínimos (CI); con errores también falla")
    ap.add_argument("--idle", type=int)
    ap.add_argument("--ws", action="store_true")
    args = ap.parse_args()
    soft, hard = resource.getrlimit(resource.RLIMIT_NOFILE)
    resource.setrlimit(resource.RLIMIT_NOFILE, (min(hard, 65536) if hard != resource.RLIM_INFINITY else 65536, hard))
    proc = data = None
    if args.url:
        base, bot, pid = args.url.rstrip("/"), args.bot, args.pid
    else:
        proc, base, bot, data = spawn()
        pid = proc.pid
    try:
        if args.idle:
            out = asyncio.run(idle(base, bot, args.idle))
            rss, cpu = server_usage(pid) if pid else (0, 0)
            print("idle connections: open=%d failed=%d (%.1fs to open) delivered=%d in %.2fs server_rss=%dMB" % (
                out["open"], out["failed"], out["open_s"], out["delivered"], out["fanout_s"], rss))
            ok = out["failed"] == 0 and out["delivered"] == out["open"]
        else:
            print("| conc | turns/s | p50 ms | p95 ms | p99 ms | errors | server RSS MB | server CPU % |")
            print("|---:|---:|---:|---:|---:|---:|---:|---:|")
            ok = True
            for conc in args.conc:
                before, t0 = server_usage(pid)[1] if pid else 0, time.monotonic()
                r = asyncio.run(load(base, bot, conc, args.seconds, args.ws))
                rss, cpu = server_usage(pid) if pid else (0, 0)
                cpu = (cpu - before) / (time.monotonic() - t0) * 100
                print("| %d | %.0f | %.0f | %.0f | %.0f | %d | %d | %.0f |" % (conc, r["throughput"], r["p50"], r["p95"], r["p99"], r["errors"], rss, cpu), flush=True)
                if args.floor is not None and (r["throughput"] < args.floor or r["errors"]):
                    ok = False
        sys.exit(0 if ok else 1)
    finally:
        if proc:
            proc.terminate()
            proc.wait(10)
            shutil.rmtree(data, True)


if __name__ == "__main__":
    main()
