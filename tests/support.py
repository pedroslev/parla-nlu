"""Lo común de las pruebas: el repo en sys.path, datos temporales y un servidor de prueba propio."""
import atexit
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


def temp_data():
    """Carpeta de datos descartable: lo que corre en este proceso nunca toca data/."""
    path = tempfile.mkdtemp(prefix="parla-test-")
    atexit.register(shutil.rmtree, path, True)
    os.environ["PARLA_DATA"] = path
    os.environ["PARLA_USERS"] = os.path.join(path, "users.json")
    return path


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def start_server(data, users=None):
    """Levanta app.py con datos temporales en un puerto libre; espera a que conteste. -> (proceso, puerto)."""
    port = free_port()
    env = dict(os.environ, PARLA_DATA=data, PARLA_USERS=users or os.path.join(data, "users.json"))
    proc = subprocess.Popen([sys.executable, os.path.join(ROOT, "app.py"), str(port)], cwd=ROOT, env=env,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(150):
        try:
            urllib.request.urlopen("http://127.0.0.1:%d/api/auth/me" % port, timeout=2).close()
            return proc, port
        except OSError:
            if proc.poll() is not None:
                break
            time.sleep(0.2)
    proc.kill()
    raise RuntimeError("el servidor de prueba no arrancó")
