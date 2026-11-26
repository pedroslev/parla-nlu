"""Pasar una instalación de SQLite a Postgres:

    PARLA_DATABASE_URL=postgresql://usuario:clave@host/base python -m parla.migrate sqlite-to-postgres [ruta/parla.db]

Copia todas las tablas de parla.db (por defecto la de PARLA_DATA) a la base de PARLA_DATABASE_URL, que se crea con
las migraciones de db.py si está vacía. Se puede correr de nuevo: las filas que ya están (misma clave) no se pisan.
Conviene con Parla apagado (o en solo lectura), para no perder lo que se escriba mientras copia.
"""
import os
import sqlite3
import sys

from . import db


def copy(source, out=print):
    if not db.PG:
        raise SystemExit("falta PARLA_DATABASE_URL=postgresql://… (la base de destino)")
    if not os.path.exists(source):
        raise SystemExit("no existe %s" % source)
    src = sqlite3.connect("file:%s?mode=ro" % source, uri=True)
    have = {name for (name,) in src.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    total = 0
    with db.pool.conn() as raw:
        for table in db.TABLES:
            if table not in have:
                continue
            cur = src.execute("SELECT * FROM %s" % table)
            cols = [d[0] for d in cur.description]
            sql = 'INSERT INTO %s (%s) VALUES (%s) ON CONFLICT DO NOTHING' % (
                table, ", ".join('"%s"' % c for c in cols), ", ".join(["%s"] * len(cols)))
            n = read = 0
            with raw.transaction():
                while True:
                    rows = cur.fetchmany(1000)
                    if not rows:
                        break
                    with raw.cursor() as c:
                        c.executemany(sql, rows)
                        n += max(0, c.rowcount)
                    read += len(rows)
                if table in db.SERIAL:      # que los ids nuevos sigan después de los copiados
                    raw.execute("SELECT setval(pg_get_serial_sequence(%s, 'id'), GREATEST((SELECT max(id) FROM " + table + "), 1))", (table,))
            out("%-20s %d filas nuevas de %d" % (table, n, read))
            total += n
    out("listo: %d filas nuevas copiadas de %s" % (total, source))
    return total


def main(argv):
    if not argv or argv[0] != "sqlite-to-postgres":
        raise SystemExit(__doc__)
    copy(argv[1] if len(argv) > 1 else db.path())


if __name__ == "__main__":
    main(sys.argv[1:])
