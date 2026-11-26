"""La base SQLite (DATA/parla.db): conversaciones, sesiones de login y auditoría. Agentes, versiones y usuarios
siguen en JSON (chicos y editables a mano). Solo biblioteca estándar.

sessions(agent_id, session_id, channel, started, updated, handoff, record)   record = el JSON de la conversación
logins(token, name, expires)        token = SHA-256 del valor de la cookie (el valor no se guarda)
audit(id, at, user, role, agent_id, action, detail)
oidc(state, nonce, verifier, expires)   logins de SSO a medio camino (oidc.py); state = su SHA-256, de un solo uso
campaigns(id, agent_id, name, channel, status, config, created, updated, created_by)        envíos salientes (outbound.py)
campaign_recipients(id, campaign_id, agent_id, address, spec, status, error, attempts, next_at, ...)   la cola de envíos:
    destinatarios de campañas, envíos de la API (campaign_id NULL, kind «api») y recordatorios (kind «remind»)
optouts(agent_id, address, channel, keyword, at)    quien pidió que no le escriban más (por agente)
webhook_deliveries(id, agent_id, url, event, event_id, session_id, body, status, attempts, next_at, code, error, ...)
    la cola de webhooks salientes (handoff.py)
usage(agent_id, session_id, day, channel, provider, model, kind, qty)   uso medido (costs.py): tokens, minutos, caracteres…
    sumado por día y conversación; el costo se calcula al leer, con los precios de ahora

Con PARLA_DATABASE_URL=postgresql://… (alta disponibilidad, varias réplicas) las mismas funciones van a Postgres
(psycopg 3, requirements-postgres.txt): el SQL de los módulos sigue escrito para SQLite y _pg() lo traduce
(placeholders, INSERT OR …, json_extract, IS). Además: kv (contadores y valores con vencimiento compartidos entre
réplicas, cluster.py) y schema_version (migraciones, con un advisory lock al arrancar).
"""
import concurrent.futures
import functools
import contextlib
import os
import queue
import re
import sqlite3
import threading
import time

from . import DATA

SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (agent_id TEXT NOT NULL, session_id TEXT NOT NULL, channel TEXT, started TEXT,
    updated TEXT NOT NULL, handoff INTEGER NOT NULL DEFAULT 0, record TEXT NOT NULL, PRIMARY KEY (agent_id, session_id));
CREATE INDEX IF NOT EXISTS sessions_updated ON sessions (agent_id, updated);
CREATE TABLE IF NOT EXISTS logins (token TEXT PRIMARY KEY, name TEXT NOT NULL, expires REAL NOT NULL);
CREATE TABLE IF NOT EXISTS audit (id INTEGER PRIMARY KEY, at TEXT NOT NULL, user TEXT, role TEXT, agent_id TEXT,
    action TEXT NOT NULL, detail TEXT);
CREATE INDEX IF NOT EXISTS audit_at ON audit (at);
CREATE TABLE IF NOT EXISTS oidc (state TEXT PRIMARY KEY, nonce TEXT NOT NULL, verifier TEXT NOT NULL, expires REAL NOT NULL);
CREATE TABLE IF NOT EXISTS campaigns (id TEXT PRIMARY KEY, agent_id TEXT NOT NULL, name TEXT NOT NULL, channel TEXT NOT NULL,
    status TEXT NOT NULL, config TEXT NOT NULL, created TEXT NOT NULL, updated TEXT NOT NULL, created_by TEXT);
CREATE INDEX IF NOT EXISTS campaigns_agent ON campaigns (agent_id, created);
CREATE TABLE IF NOT EXISTS campaign_recipients (id INTEGER PRIMARY KEY, campaign_id TEXT, agent_id TEXT NOT NULL,
    kind TEXT NOT NULL DEFAULT 'campaign', channel TEXT NOT NULL, address TEXT NOT NULL, spec TEXT NOT NULL,
    status TEXT NOT NULL, error TEXT, attempts INTEGER NOT NULL DEFAULT 0, next_at REAL NOT NULL DEFAULT 0,
    session_id TEXT, message_id TEXT, token TEXT, created TEXT NOT NULL, updated TEXT NOT NULL, sent_at TEXT,
    UNIQUE (campaign_id, address));
CREATE INDEX IF NOT EXISTS recipients_due ON campaign_recipients (status, next_at);
CREATE INDEX IF NOT EXISTS recipients_message ON campaign_recipients (message_id);
CREATE INDEX IF NOT EXISTS recipients_session ON campaign_recipients (agent_id, session_id);
CREATE TABLE IF NOT EXISTS optouts (agent_id TEXT NOT NULL, address TEXT NOT NULL, channel TEXT, keyword TEXT, at TEXT NOT NULL,
    PRIMARY KEY (agent_id, address));
CREATE TABLE IF NOT EXISTS webhook_deliveries (id INTEGER PRIMARY KEY, agent_id TEXT NOT NULL, url TEXT NOT NULL,
    event TEXT NOT NULL, event_id TEXT NOT NULL, session_id TEXT, body TEXT NOT NULL, status TEXT NOT NULL,
    attempts INTEGER NOT NULL DEFAULT 0, next_at REAL NOT NULL DEFAULT 0, code INTEGER, error TEXT, latency_ms INTEGER,
    created TEXT NOT NULL, updated TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS webhook_due ON webhook_deliveries (status, next_at);
CREATE INDEX IF NOT EXISTS webhook_order ON webhook_deliveries (agent_id, url, session_id, status);
CREATE TABLE IF NOT EXISTS usage (agent_id TEXT NOT NULL, session_id TEXT NOT NULL DEFAULT '', day TEXT NOT NULL,
    channel TEXT NOT NULL DEFAULT '', provider TEXT NOT NULL, model TEXT NOT NULL DEFAULT '', kind TEXT NOT NULL, qty REAL NOT NULL,
    PRIMARY KEY (agent_id, day, session_id, channel, provider, model, kind));
CREATE INDEX IF NOT EXISTS usage_session ON usage (agent_id, session_id);
"""
# Lecturas: una conexión por hilo, sin lock (WAL deja leer mientras otro escribe). Escrituras: un solo hilo escritor
# con una cola y group commit (todo lo que se juntó va en una transacción). q() de escritura vuelve recién después del
# COMMIT: lo que devolvió OK está en el WAL (synchronous=NORMAL: sobrevive a que se caiga el proceso; un corte de luz
# puede perder las últimas transacciones). Si el proceso muere con escrituras en la cola, esas se pierden y sus pedidos
# nunca recibieron respuesta. connect() (transacciones de varias sentencias) toma WRITE, el mismo lock del escritor.
WRITE = threading.Lock()
BATCH = 512                 # sentencias por group commit, como mucho
_local = threading.local()
_writes = queue.Queue()
_ready = [False]
_stats = {"commits": 0, "statements": 0}     # para /metrics: tamaño de los group commits


def path():
    return os.path.join(DATA, "parla.db")


URL = os.environ.get("PARLA_DATABASE_URL") or ""
PG = URL.startswith(("postgresql://", "postgres://"))


def _open():
    if not _ready[0]:
        with WRITE:
            if not _ready[0]:
                os.makedirs(DATA, exist_ok=True)
                os.close(os.open(path(), os.O_CREAT | os.O_WRONLY, 0o600))     # conversaciones y logins: solo el dueño del proceso
                conn = sqlite3.connect(path(), timeout=10)
                conn.execute("PRAGMA journal_mode=WAL")
                conn.executescript(SCHEMA)
                conn.close()
                threading.Thread(target=_writer, daemon=True, name="parla-db-writer").start()
                _ready[0] = True
    conn = sqlite3.connect(path(), check_same_thread=False, timeout=10, isolation_level=None)   # autocommit: sin snapshot viejo
    conn.execute("PRAGMA busy_timeout=10000")
    conn.execute("PRAGMA synchronous=NORMAL")
    return conn


def _conn():
    conn = getattr(_local, "conn", None)
    if conn is None:
        conn = _local.conn = _open()
    return conn


def _writer():
    conn = None
    while True:
        batch = [_writes.get()]
        while len(batch) < BATCH:
            try:
                batch.append(_writes.get_nowait())
            except queue.Empty:
                break
        try:
            if conn is None:
                conn = sqlite3.connect(batch[0][0], timeout=10, isolation_level=None)
                conn.execute("PRAGMA busy_timeout=10000")
                conn.execute("PRAGMA synchronous=NORMAL")
            results = []
            with WRITE:
                conn.execute("BEGIN IMMEDIATE")
                for where, sql, args, future in batch:
                    try:        # un error (p. ej. UNIQUE) deshace solo esa sentencia: la transacción sigue
                        results.append((future, conn.execute(sql, args).fetchall(), None))
                    except Exception as error:  # noqa: BLE001 - se le devuelve al que la pidió
                        results.append((future, None, error))
                conn.execute("COMMIT")
            _stats["commits"] += 1
            _stats["statements"] += len(batch)
        except Exception as error:  # noqa: BLE001 - el COMMIT falló (disco lleno): nadie quedó guardado
            try:
                conn.execute("ROLLBACK")
            except Exception:  # noqa: BLE001
                pass
            results = [(job[3], None, error) for job in batch]
        for future, rows, error in results:
            future.set_exception(error) if error else future.set_result(rows)


@contextlib.contextmanager
def connect():
    """Una conexión de este hilo dentro de una transacción de escritura (commit al salir, rollback si falla)."""
    if PG:
        yield from _pg_connect()
        return
    conn = _conn()
    if getattr(_local, "tx", False):        # anidada: ya estamos adentro
        yield conn
        return
    with WRITE:
        _local.tx = True
        conn.execute("BEGIN IMMEDIATE")
        try:
            yield conn
            conn.execute("COMMIT")
        except BaseException:
            conn.execute("ROLLBACK")
            raise
        finally:
            _local.tx = False


def q(sql, args=()):
    """Una consulta: devuelve las filas. SELECT lee en la conexión del hilo; lo demás va por el escritor."""
    if PG:
        return _pg_q(sql, args)
    conn = _conn()
    if getattr(_local, "tx", False) or sql.lstrip()[:6].upper() == "SELECT":
        return conn.execute(sql, args).fetchall()
    future = concurrent.futures.Future()
    _writes.put((path(), sql, args, future))
    return future.result()


def later(sql, args=()):
    """Una escritura sin esperar el COMMIT (va en el próximo group commit; si falla, se pierde en silencio). Para lo
    que no puede frenar un turno: la contabilidad de uso (costs.py)."""
    if PG:
        _pg_start_writer()
        with _later:
            _later.queued += 1
            _writes.put((None, sql, args, concurrent.futures.Future()))
        return
    _conn()
    _writes.put((path(), sql, args, concurrent.futures.Future()))


def pending():
    """Escrituras esperando al escritor (gauge parla_db_write_queue)."""
    return _writes.qsize()


def audit(user, role, agent_id, action, detail=""):
    """Una entrada de auditoría. «agent.save» llega cada ~400 ms mientras se edita: se junta con la anterior del mismo
    usuario y agente si fue hace menos de 5 minutos (solo se corre la hora)."""
    at = time.strftime("%Y-%m-%dT%H:%M:%S")
    with connect() as conn:
        if action == "agent.save":
            last = conn.execute("SELECT id, at FROM audit WHERE action = 'agent.save' AND user IS ? AND agent_id IS ? ORDER BY id DESC LIMIT 1",
                                (user, agent_id)).fetchone()
            since = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(time.time() - 300))
            if last and last[1] >= since and conn.execute("SELECT max(id) FROM audit").fetchone()[0] == last[0]:
                conn.execute("UPDATE audit SET at = ? WHERE id = ?", (at, last[0]))
                return
        conn.execute("INSERT INTO audit (at, user, role, agent_id, action, detail) VALUES (?, ?, ?, ?, ?, ?)",
                     (at, user, role, agent_id, action, str(detail or "")[:300]))


def audit_list(agent=None, user=None, since=None, limit=200):
    """Las entradas más nuevas primero, filtradas por agente, usuario y desde (YYYY-MM-DD o con hora)."""
    sql, args = "SELECT at, user, role, agent_id, action, detail FROM audit WHERE 1 = 1", []
    for column, value in (("agent_id", agent), ("user", user)):
        if value:
            sql, args = sql + " AND %s = ?" % column, args + [value]
    if since:
        sql, args = sql + " AND at >= ?", args + [since]
    rows = q(sql + " ORDER BY id DESC LIMIT ?", args + [limit])
    return [dict(zip(("at", "user", "role", "agent_id", "action", "detail"), row)) for row in rows]


# ---------- Postgres (PARLA_DATABASE_URL) ----------

# Migraciones versionadas: cada una corre una sola vez (schema_version), en orden, bajo un advisory lock (varias
# réplicas arrancando a la vez no las corren dos veces). Agregar al final; nunca cambiar una que ya salió.
MIGRATIONS = [(1, """
CREATE TABLE IF NOT EXISTS sessions (agent_id TEXT NOT NULL, session_id TEXT NOT NULL, channel TEXT, started TEXT,
    updated TEXT NOT NULL, handoff INTEGER NOT NULL DEFAULT 0, record JSONB NOT NULL, PRIMARY KEY (agent_id, session_id));
CREATE INDEX IF NOT EXISTS sessions_updated ON sessions (agent_id, updated);
CREATE TABLE IF NOT EXISTS logins (token TEXT PRIMARY KEY, name TEXT NOT NULL, expires DOUBLE PRECISION NOT NULL);
CREATE TABLE IF NOT EXISTS audit (id BIGSERIAL PRIMARY KEY, at TEXT NOT NULL, "user" TEXT, role TEXT, agent_id TEXT,
    action TEXT NOT NULL, detail TEXT);
CREATE INDEX IF NOT EXISTS audit_at ON audit (at);
CREATE TABLE IF NOT EXISTS oidc (state TEXT PRIMARY KEY, nonce TEXT NOT NULL, verifier TEXT NOT NULL, expires DOUBLE PRECISION NOT NULL);
CREATE TABLE IF NOT EXISTS campaigns (id TEXT PRIMARY KEY, agent_id TEXT NOT NULL, name TEXT NOT NULL, channel TEXT NOT NULL,
    status TEXT NOT NULL, config JSONB NOT NULL, created TEXT NOT NULL, updated TEXT NOT NULL, created_by TEXT);
CREATE INDEX IF NOT EXISTS campaigns_agent ON campaigns (agent_id, created);
CREATE TABLE IF NOT EXISTS campaign_recipients (id BIGSERIAL PRIMARY KEY, campaign_id TEXT, agent_id TEXT NOT NULL,
    kind TEXT NOT NULL DEFAULT 'campaign', channel TEXT NOT NULL, address TEXT NOT NULL, spec JSONB NOT NULL,
    status TEXT NOT NULL, error TEXT, attempts INTEGER NOT NULL DEFAULT 0, next_at DOUBLE PRECISION NOT NULL DEFAULT 0,
    session_id TEXT, message_id TEXT, token TEXT, created TEXT NOT NULL, updated TEXT NOT NULL, sent_at TEXT,
    UNIQUE (campaign_id, address));
CREATE INDEX IF NOT EXISTS recipients_due ON campaign_recipients (status, next_at);
CREATE INDEX IF NOT EXISTS recipients_message ON campaign_recipients (message_id);
CREATE INDEX IF NOT EXISTS recipients_session ON campaign_recipients (agent_id, session_id);
CREATE TABLE IF NOT EXISTS optouts (agent_id TEXT NOT NULL, address TEXT NOT NULL, channel TEXT, keyword TEXT, at TEXT NOT NULL,
    PRIMARY KEY (agent_id, address));
CREATE TABLE IF NOT EXISTS webhook_deliveries (id BIGSERIAL PRIMARY KEY, agent_id TEXT NOT NULL, url TEXT NOT NULL,
    event TEXT NOT NULL, event_id TEXT NOT NULL, session_id TEXT, body TEXT NOT NULL, status TEXT NOT NULL,
    attempts INTEGER NOT NULL DEFAULT 0, next_at DOUBLE PRECISION NOT NULL DEFAULT 0, code INTEGER, error TEXT, latency_ms INTEGER,
    created TEXT NOT NULL, updated TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS webhook_due ON webhook_deliveries (status, next_at);
CREATE INDEX IF NOT EXISTS webhook_order ON webhook_deliveries (agent_id, url, session_id, status);
CREATE TABLE IF NOT EXISTS usage (agent_id TEXT NOT NULL, session_id TEXT NOT NULL DEFAULT '', day TEXT NOT NULL,
    channel TEXT NOT NULL DEFAULT '', provider TEXT NOT NULL, model TEXT NOT NULL DEFAULT '', kind TEXT NOT NULL,
    qty DOUBLE PRECISION NOT NULL, PRIMARY KEY (agent_id, day, session_id, channel, provider, model, kind));
CREATE INDEX IF NOT EXISTS usage_session ON usage (agent_id, session_id);
CREATE TABLE IF NOT EXISTS kv (k TEXT PRIMARY KEY, v TEXT, n BIGINT NOT NULL DEFAULT 0, expires DOUBLE PRECISION NOT NULL);
CREATE INDEX IF NOT EXISTS kv_expires ON kv (expires);
""")]
TABLES = ("sessions", "logins", "audit", "oidc", "campaigns", "campaign_recipients", "optouts", "webhook_deliveries", "usage")
KEYS = {"sessions": "agent_id, session_id", "optouts": "agent_id, address", "logins": "token", "oidc": "state", "campaigns": "id",
        "usage": "agent_id, day, session_id, channel, provider, model, kind"}
SERIAL = {"audit", "campaign_recipients", "webhook_deliveries"}      # id BIGSERIAL: INSERT … RETURNING id (lastrowid)
POOL_SIZE = int(os.environ.get("PARLA_DB_POOL") or 20)
SCHEMA_NAME = os.environ.get("PARLA_DATABASE_SCHEMA") or ""      # vacío = el search_path del usuario (public)
_EXTRACT = re.compile(r"json_extract\(([\w.]+), '\$\.(\w+)'\)")


@functools.lru_cache(maxsize=512)
def _pg(sql):
    """El SQL de SQLite que usan los módulos, en el de Postgres. -> (sql, ¿agregué RETURNING id?)."""
    head = re.match(r"\s*INSERT OR (IGNORE|REPLACE) INTO (\w+)\s*\(([^)]*)\)", sql)
    if head:
        sql = sql.replace("INSERT OR %s INTO" % head.group(1), "INSERT INTO", 1)
        if head.group(1) == "IGNORE":
            sql += " ON CONFLICT DO NOTHING"
        else:
            keys = KEYS[head.group(2)]
            cols = [c.strip() for c in head.group(3).split(",") if c.strip() not in keys.split(", ")]
            sql += " ON CONFLICT (%s) DO UPDATE SET %s" % (keys, ", ".join("%s = EXCLUDED.%s" % (c, c) for c in cols))
    table = re.match(r"\s*INSERT INTO (\w+)", sql)
    if table and "DO UPDATE SET" in sql:      # «qty = qty + excluded.qty»: en Postgres la columna va con la tabla
        sql = re.sub(r"DO UPDATE SET (\w+) = \1\b", r"DO UPDATE SET \1 = %s.\1" % table.group(1), sql)
    sql = _EXTRACT.sub(r"(\1->>'\2')", sql)
    sql = re.sub(r"(\(\w+->>'\w+'\)) = 0\b", r"\1 IN ('0', 'false')", sql)
    sql = re.sub(r"\bWHERE ([01])\b(?!\s*[=<>!])", lambda m: "WHERE " + ("true" if m.group(1) == "1" else "false"), sql)
    sql = re.sub(r"\bIS NOT (?!NULL\b)", "IS DISTINCT FROM ", sql)
    sql = re.sub(r"\bIS (?!NULL\b|NOT\b|DISTINCT\b)", "IS NOT DISTINCT FROM ", sql)
    sql = re.sub(r"(?<![\w.'\"])user(?![\w'\"])", '"user"', sql)
    returning = bool(table and table.group(1) in SERIAL and "RETURNING" not in sql.upper())
    if returning:
        sql += " RETURNING id"
    return sql.replace("%", "%%").replace("?", "%s"), returning


class _Cursor:
    def __init__(self, rows, rowcount, lastrowid=None):
        self.rows, self.rowcount, self.lastrowid = rows, rowcount, lastrowid

    def fetchall(self):
        return self.rows

    def fetchone(self):
        return self.rows[0] if self.rows else None

    def __iter__(self):
        return iter(self.rows)


class _Conn:
    """Una conexión de psycopg con la cara de sqlite3 (execute/executemany con SQL de SQLite)."""
    def __init__(self, raw):
        self.raw = raw

    def execute(self, sql, args=()):
        text, returning = _pg(sql)
        cur = self.raw.execute(text, [int(a) if isinstance(a, bool) else a for a in args])
        rows = cur.fetchall() if cur.description else []
        if returning:
            return _Cursor([], cur.rowcount, rows[0][0] if rows else None)
        return _Cursor(rows, cur.rowcount)

    def executemany(self, sql, seq):
        for args in seq:
            self.execute(sql, args)


class Pool:
    """Pool simple y seguro entre hilos: hasta `size` conexiones; get() espera (30 s) si están todas ocupadas."""
    def __init__(self, size):
        self.size, self.idle, self.open = size, [], 0
        self.cond = threading.Condition()

    def get(self):
        with self.cond:
            if not self.cond.wait_for(lambda: self.idle or self.open < self.size, 30):
                raise TimeoutError("Postgres: no hay conexiones libres en el pool (PARLA_DB_POOL=%d)" % self.size)
            if self.idle:
                return self.idle.pop()
            self.open += 1
        try:
            return _new_connection()
        except BaseException:
            with self.cond:
                self.open -= 1
                self.cond.notify()
            raise

    def put(self, conn, broken=False):
        with self.cond:
            if broken or conn.closed or conn.info.transaction_status != 0:      # 0 = IDLE: nada a medio hacer
                self.open -= 1
                try:
                    conn.close()
                except Exception:  # noqa: BLE001
                    pass
            else:
                self.idle.append(conn)
            self.cond.notify()

    @contextlib.contextmanager
    def conn(self):
        conn, broken = self.get(), False
        try:
            yield conn
        except Exception as error:
            import psycopg
            broken = isinstance(error, (psycopg.OperationalError, psycopg.InterfaceError))
            raise
        finally:
            self.put(conn, broken)

    def stats(self):
        return {"size": self.size, "open": self.open, "idle": len(self.idle)}


def _new_connection():
    import psycopg
    from psycopg.types.string import TextLoader
    options = "-c search_path=%s" % SCHEMA_NAME if SCHEMA_NAME else None
    conn = psycopg.connect(URL, autocommit=True, connect_timeout=10, application_name="parla", options=options)
    for name in ("json", "jsonb"):          # el JSON vuelve como texto, igual que en SQLite (los módulos hacen json.loads)
        conn.adapters.register_loader(name, TextLoader)
    if not _ready[0]:
        _migrate(conn)
    return conn


def _migrate(conn):
    with WRITE:
        if _ready[0]:
            return
        if SCHEMA_NAME:
            conn.execute('CREATE SCHEMA IF NOT EXISTS "%s"' % SCHEMA_NAME)
        conn.execute("SELECT pg_advisory_lock(hashtext('parla:migrate'))")
        try:
            conn.execute("CREATE TABLE IF NOT EXISTS schema_version (version INTEGER PRIMARY KEY, at TEXT NOT NULL)")
            done = {v for (v,) in conn.execute("SELECT version FROM schema_version").fetchall()}
            for version, ddl in MIGRATIONS:
                if version not in done:
                    with conn.transaction():
                        conn.execute(ddl)
                        conn.execute("INSERT INTO schema_version (version, at) VALUES (%s, %s)", (version, time.strftime("%Y-%m-%dT%H:%M:%S")))
        finally:
            conn.execute("SELECT pg_advisory_unlock(hashtext('parla:migrate'))")
        _ready[0] = True


pool = Pool(POOL_SIZE) if PG else None


def _pg_q(sql, args):
    if _later.done < _later.queued and sql.lstrip()[:6].upper() != "SELECT":
        with _later:            # como en SQLite: una escritura que espera va después de las de later() que ya estaban encoladas
            ticket = _later.queued
            _later.wait_for(lambda: _later.done >= ticket, 30)
    conn = getattr(_local, "pg", None)
    if conn is not None:            # adentro de connect(): la misma transacción
        return conn.execute(sql, args).fetchall()
    with pool.conn() as raw:
        return _Conn(raw).execute(sql, args).fetchall()


def _pg_connect():
    if getattr(_local, "pg", None) is not None:
        yield _local.pg
        return
    with pool.conn() as raw:
        with raw.transaction():
            _local.pg = _Conn(raw)
            try:
                yield _local.pg
            finally:
                _local.pg = None
    _stats["commits"] += 1


def _pg_writer():
    while True:
        batch = [_writes.get()]
        while len(batch) < BATCH:
            try:
                batch.append(_writes.get_nowait())
            except queue.Empty:
                break
        try:
            with connect() as conn:
                for _, sql, args, _ in batch:
                    conn.execute(sql, args)
            _stats["statements"] += len(batch)
        except Exception:  # noqa: BLE001 - de a una: la que falla se pierde (como en SQLite), las demás no
            for _, sql, args, _ in batch:
                try:
                    with pool.conn() as raw:
                        _Conn(raw).execute(sql, args)
                except Exception:  # noqa: BLE001
                    pass
        with _later:
            _later.done += len(batch)
            _later.notify_all()


def _pg_start_writer():
    if not _writer_started[0]:
        with WRITE:
            if not _writer_started[0]:
                threading.Thread(target=_pg_writer, daemon=True, name="parla-db-writer").start()
                _writer_started[0] = True


_writer_started = [False]
_later = threading.Condition()
_later.queued = _later.done = 0     # escrituras de later() encoladas y hechas (en orden: la cola es FIFO)


def ping():
    """¿Contesta la base? Para /readyz."""
    try:
        q("SELECT 1")
        return True
    except Exception:  # noqa: BLE001
        return False
