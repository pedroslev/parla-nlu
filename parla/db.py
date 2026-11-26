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
"""
import concurrent.futures
import contextlib
import os
import queue
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
    conn = _conn()
    if getattr(_local, "tx", False) or sql.lstrip()[:6].upper() == "SELECT":
        return conn.execute(sql, args).fetchall()
    future = concurrent.futures.Future()
    _writes.put((path(), sql, args, future))
    return future.result()


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
