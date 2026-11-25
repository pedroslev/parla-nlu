#!/usr/bin/env python3
"""Corre cada prueba en su propio proceso y resume.   .venv/bin/python tests/run_all.py [nombre ...]
Las de voz e IA dicen «saltado» si faltan los modelos o Ollama (no cuenta como falla)."""
import glob
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
names = sys.argv[1:] or sorted(os.path.basename(f)[5:-3] for f in glob.glob(os.path.join(HERE, "test_*.py")))
failed = 0
for name in names:
    t = time.time()
    r = subprocess.run([sys.executable, os.path.join(HERE, "test_%s.py" % name)], capture_output=True, text=True, cwd=HERE)
    out = r.stdout + r.stderr
    skipped = next((line.strip() for line in out.splitlines() if "saltea" in line or "saltado" in line), "")
    state = "FALLÓ" if r.returncode else ("saltado" if skipped else "ok")
    print("%-8s %-10s %5.1fs  %s" % (state, name, time.time() - t, skipped))
    if r.returncode:
        failed += 1
        tail = out.strip().splitlines()[-15:]
        print("\n".join("    " + line for line in tail))
        if os.environ.get("GITHUB_ACTIONS"):   # anotación visible en GitHub sin abrir el log
            print("::error title=test_%s::%s" % (name, "%0A".join(tail).replace("\r", "")))
print("\n%d de %d pasaron%s" % (len(names) - failed, len(names), "" if not failed else ", %d fallaron" % failed))
sys.exit(1 if failed else 0)
