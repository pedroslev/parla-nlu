"""Parla backup / restore for the Helm chart's CronJob. Runs in the Parla image as uid 10001.

  python backup.py                  -> /backup/parla-<UTC stamp>.tar.gz (keeps the newest $BACKUP_KEEP)
  python backup.py restore <file>   -> extracts it into /data (Parla must be stopped: replicaCount=0)

parla.db is copied with SQLite's online backup API, so the snapshot is consistent while Parla keeps writing.
models/ is left out (it's downloaded again).
"""
import glob
import os
import sqlite3
import sys
import tarfile
import time

DATA, OUT = os.environ.get("PARLA_DATA", "/data"), os.environ.get("BACKUP_DIR", "/backup")
SKIP = {"models", "lost+found", "parla.db", "parla.db-wal", "parla.db-shm", "parla.db.backup"}


def backup():
    os.umask(0o077)          # the snapshot and the archive hold users, keys and conversations: 600
    os.makedirs(OUT, exist_ok=True)
    name = os.path.join(OUT, time.strftime("parla-%Y%m%d-%H%M%S.tar.gz", time.gmtime()))
    snap = "/tmp/parla.db"
    with tarfile.open(name + ".part", "w:gz") as tar:
        if os.path.exists(os.path.join(DATA, "parla.db")):
            src, dst = sqlite3.connect(os.path.join(DATA, "parla.db"), timeout=30), sqlite3.connect(snap)
            src.backup(dst)
            dst.close()
            src.close()
            tar.add(snap, "parla.db")
            os.remove(snap)
        for entry in sorted(os.listdir(DATA)):
            if entry not in SKIP:
                tar.add(os.path.join(DATA, entry), entry)
    os.replace(name + ".part", name)
    keep = max(1, int(os.environ.get("BACKUP_KEEP", "7")))
    old = sorted(glob.glob(os.path.join(OUT, "parla-*.tar.gz")))[:-keep]
    for path in old:
        os.remove(path)
    print("wrote %s (%d bytes); removed %d old" % (name, os.path.getsize(name), len(old)))


def restore(path):
    for stale in ("parla.db-wal", "parla.db-shm"):      # an old WAL would be replayed over the restored database
        if os.path.exists(os.path.join(DATA, stale)):
            os.remove(os.path.join(DATA, stale))
    with tarfile.open(path) as tar:
        tar.extractall(DATA, filter="data")
    print("restored %s into %s" % (path, DATA))


if __name__ == "__main__":
    restore(sys.argv[2]) if sys.argv[1:2] == ["restore"] else backup()
