"""Varias réplicas de Parla sobre la misma Postgres (PARLA_DATABASE_URL). Sin Postgres nada de esto hace algo:
una sola réplica, como siempre (locks en memoria, el bus del proceso, esta réplica es la líder).

- lock(nombre): advisory lock de Postgres (pg_advisory_lock(hashtext(nombre))) en una conexión propia, con
  PARLA_LOCK_TIMEOUT (30 s). Los turnos de una conversación, entrenar y publicar un agente, arrancar.
- Líder: una réplica tiene el advisory lock «parla:leader» en una conexión abierta; corre lo que tiene que correr
  una sola vez (retención, tiempo máximo de los handoffs, el ritmo de las campañas, filas trabadas). Si se muere,
  Postgres suelta el lock al cerrarse la conexión y otra lo toma en LEADER_CHECK segundos.
- Bus entre réplicas: LISTEN/NOTIFY en el canal «parla». El payload de NOTIFY tiene un tope (8000 bytes): una
  conversación guardada viaja como su tema y la réplica que la recibe la lee de la base.
- kv: contadores y valores con vencimiento compartidos (límites de intentos y de envíos, ids de mensajes ya
  atendidos, silencios y planes de las llamadas).
"""
import contextlib
import json
import os
import queue
import secrets
import socket
import sys
import threading
import time

from . import bus, db

NODE = "%s-%d-%s" % (socket.gethostname(), os.getpid(), secrets.token_hex(3))
LOCK_TIMEOUT = float(os.environ.get("PARLA_LOCK_TIMEOUT") or 30)
LEADER_CHECK = float(os.environ.get("PARLA_LEADER_CHECK") or 2)
NOTIFY_MAX = 7000
STATE = {"leader": not db.PG, "since": time.time() if not db.PG else None, "sent": 0, "received": 0, "started": False}
locks = db.Pool(int(os.environ.get("PARLA_DB_LOCKS") or 32)) if db.PG else None     # aparte: un lock no le saca conexiones a las consultas
_out = queue.Queue()


def is_leader():
    """¿Corre esta réplica las tareas de una sola vez? Sin start() (un proceso suelto, las pruebas) no hay elección: sí."""
    return STATE["leader"] or not STATE["started"]


# ---------- locks ----------

def acquire(name):
    """Espera el lock (como mucho LOCK_TIMEOUT; si no, TimeoutError). -> la conexión que lo tiene, o None sin Postgres."""
    if not db.PG:
        return None
    conn = locks.get()
    try:
        conn.execute("SELECT set_config('lock_timeout', %s, false)", ("%dms" % (LOCK_TIMEOUT * 1000),))
        conn.execute("SELECT pg_advisory_lock(hashtext(%s))", (name,))
    except Exception as error:
        locks.put(conn, broken=True)
        raise TimeoutError("no pude tomar el lock %s: %s" % (name, error)) from error
    return conn


def release(conn, name):
    if conn is None:
        return
    try:
        conn.execute("SELECT pg_advisory_unlock(hashtext(%s))", (name,))
        locks.put(conn)
    except Exception:  # noqa: BLE001 - la conexión murió: el lock se soltó con ella
        locks.put(conn, broken=True)


@contextlib.contextmanager
def lock(name):
    conn = acquire(name)
    try:
        yield
    finally:
        release(conn, name)


@contextlib.contextmanager
def both(local, name):
    """El lock del proceso y, con Postgres, el de todas las réplicas."""
    with local, lock(name):
        yield


# ---------- kv ----------

def hit(key, ttl):
    """Suma 1 al contador (la ventana empieza con el primero y dura ttl segundos). -> cuántos van."""
    now = time.time()
    return db.q("INSERT INTO kv (k, n, expires) VALUES (?, 1, ?) ON CONFLICT (k) DO UPDATE SET "
                "n = CASE WHEN kv.expires < ? THEN 1 ELSE kv.n + 1 END, "
                "expires = CASE WHEN kv.expires < ? THEN EXCLUDED.expires ELSE kv.expires END RETURNING n",
                (key, now + ttl, now, now))[0][0]


def count(key):
    rows = db.q("SELECT n FROM kv WHERE k = ? AND expires >= ?", (key, time.time()))
    return rows[0][0] if rows else 0


def forget(key):
    db.q("DELETE FROM kv WHERE k = ?", (key,))


def first(key, ttl):
    """¿Es la primera vez que vemos esta llave (en ttl segundos)? Atómico entre réplicas."""
    now = time.time()
    return bool(db.q("INSERT INTO kv (k, n, expires) VALUES (?, 1, ?) ON CONFLICT (k) DO UPDATE SET n = 1, "
                     "expires = EXCLUDED.expires WHERE kv.expires < ? RETURNING n", (key, now + ttl, now)))


def put(key, value, ttl):
    db.q("INSERT INTO kv (k, v, expires) VALUES (?, ?, ?) ON CONFLICT (k) DO UPDATE SET v = EXCLUDED.v, expires = EXCLUDED.expires",
         (key, json.dumps(value, ensure_ascii=False), time.time() + ttl))


def take(key):
    """El valor guardado con put (y lo borra), o None."""
    rows = db.q("DELETE FROM kv WHERE k = ? AND expires >= ? RETURNING v", (key, time.time()))
    return json.loads(rows[0][0]) if rows and rows[0][0] is not None else None


# ---------- líder ----------

def _elect(conn):
    """Una vuelta: si no es líder, intenta serlo; si ya lo es, comprueba que su conexión (y el lock) sigue viva."""
    try:
        conn = conn or db._new_connection()
        if not STATE["leader"]:
            if conn.execute("SELECT pg_try_advisory_lock(hashtext('parla:leader'))").fetchone()[0]:
                STATE.update(leader=True, since=time.time())
                print("cluster: %s es la réplica líder" % NODE, flush=True)
        else:
            conn.execute("SELECT 1")
            db.q("DELETE FROM kv WHERE expires < ?", (time.time() - 60,))
        return conn
    except Exception as error:  # noqa: BLE001 - sin base: deja de ser líder (otra lo toma) y reintenta
        if STATE["leader"]:
            print("cluster: %s deja de ser líder: %s" % (NODE, error), file=sys.stderr, flush=True)
        STATE.update(leader=False, since=None)
        try:
            conn and conn.close()
        except Exception:  # noqa: BLE001
            pass
        return None


def _lead(conn):
    while True:
        time.sleep(LEADER_CHECK)
        conn = _elect(conn)


# ---------- bus entre réplicas ----------

def _send(topic, event):
    _out.put((topic, event))


def _notifier():
    conn = None
    while True:
        topic, event = _out.get()
        payload = json.dumps({"n": NODE, "t": topic, "e": event}, ensure_ascii=False)
        if len(payload.encode()) > NOTIFY_MAX:
            payload = json.dumps({"n": NODE, "t": topic})          # «saved»: el que lo recibe lee la conversación
        try:
            conn = conn or db._new_connection()
            conn.execute("SELECT pg_notify('parla', %s)", (payload,))
            STATE["sent"] += 1
        except Exception as error:  # noqa: BLE001 - se pierde ese evento (el cliente se pone al día en el próximo)
            print("cluster: NOTIFY falló: %s" % error, file=sys.stderr, flush=True)
            conn = None


def deliver(payload):
    """Un NOTIFY de otra réplica -> los suscriptores de esta."""
    data = json.loads(payload)
    topic = data.get("t") or ""
    if data.get("n") == NODE or not bus.has(topic):
        return
    event = data.get("e")
    if event is None and topic.startswith("session:"):
        _, agent_id, sid = topic.split(":", 2)
        rows = db.q("SELECT record FROM sessions WHERE agent_id = ? AND session_id = ?", (agent_id, sid))
        if not rows:
            return
        event = {"type": "saved", "record": json.loads(rows[0][0])}
    if event is not None:
        STATE["received"] += 1
        bus.local(topic, event)


def _listen():
    while True:
        try:
            conn = db._new_connection()
            conn.execute("LISTEN parla")
            for note in conn.notifies():
                try:
                    deliver(note.payload)
                except Exception as error:  # noqa: BLE001 - un evento raro no corta la escucha
                    print("cluster: evento descartado: %s" % error, file=sys.stderr, flush=True)
        except Exception as error:  # noqa: BLE001 - se cortó la base: reconecta (lo que pasó mientras, se pierde)
            print("cluster: LISTEN se cortó: %s" % error, file=sys.stderr, flush=True)
            time.sleep(1)


def start():
    """Al arrancar (server.main): líder, bus entre réplicas. Sin Postgres no hace nada."""
    if not db.PG or STATE["started"]:
        return
    STATE["started"] = True
    if not os.environ.get("PARLA_SECRET_KEY"):
        print("cluster: falta PARLA_SECRET_KEY: las direcciones firmadas de audio de una réplica no valen en otra",
              file=sys.stderr, flush=True)
    bus.remote = _send
    conn = _elect(None)          # la primera elección, antes de las tareas de arranque (limpieza solo en la líder)
    threading.Thread(target=_lead, args=(conn,), daemon=True, name="parla-leader").start()
    for target, name in ((_notifier, "parla-notify"), (_listen, "parla-listen")):
        threading.Thread(target=target, daemon=True, name=name).start()


def gauges():
    out = [("parla_cluster_leader", [({}, int(STATE["leader"]))]),
           ("parla_cluster_events_total", [({"direction": "sent"}, STATE["sent"]), ({"direction": "received"}, STATE["received"])])]
    if db.PG:
        out.append(("parla_db_pool_connections", [({"pool": name, "state": state}, p.stats()[state])
                                                  for name, p in (("queries", db.pool), ("locks", locks)) for state in ("open", "idle")]))
    return out
