"""La base SQLite (DATA/parla.db): conversaciones, sesiones de login y auditoría. Agentes, versiones y usuarios
siguen en JSON (chicos y editables a mano). Solo biblioteca estándar.

sessions(agent_id, session_id, channel, started, updated, handoff, record)   record = el JSON de la conversación
logins(token, name, expires)        token = SHA-256 del valor de la cookie (el valor no se guarda)
audit(id, at, user, role, agent_id, action, detail)
oidc(state, nonce, verifier, expires)   logins de SSO a medio camino (oidc.py); state = su SHA-256, de un solo uso
"""
import contextlib
import os
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
"""
# ponytail: una conexión y un lock para todo el proceso (ThreadingHTTPServer); alcanza para un servidor.
# Con mucho tráfico: una conexión por hilo (WAL ya deja leer mientras otro escribe)
LOCK = threading.RLock()
_conn = None


def path():
    return os.path.join(DATA, "parla.db")


@contextlib.contextmanager
def connect():
    """La conexión, con el lock tomado y dentro de una transacción (commit al salir, rollback si falla)."""
    global _conn
    with LOCK:
        if _conn is None:
            os.makedirs(DATA, exist_ok=True)
            os.close(os.open(path(), os.O_CREAT | os.O_WRONLY, 0o600))     # conversaciones y logins: solo el dueño del proceso
            conn = sqlite3.connect(path(), check_same_thread=False, timeout=10)
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA busy_timeout=10000")
            conn.executescript(SCHEMA)
            _conn = conn
        with _conn:
            yield _conn


def q(sql, args=()):
    """Una consulta: devuelve las filas (lista vacía si no es un SELECT)."""
    with connect() as conn:
        return conn.execute(sql, args).fetchall()


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
