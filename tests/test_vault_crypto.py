"""Claves cifradas en disco (parla/vault.py): AES-256-GCM con una subclave HKDF de PARLA_SECRET_KEY, detección de
cambios, archivos planos viejos que se cifran al guardar, rotación por la línea de comandos, sin clave = plano como
antes (y la pantalla Claves avisa), y que ningún valor aparezca en disco ni en la consola. Sin red.
Uso: .venv/bin/python tests/test_vault_crypto.py"""
import base64
import contextlib
import hashlib
import io
import json
import os
import stat
import subprocess
import sys
import time
import urllib.request

import support
DATA = support.temp_data()
AGENTS = os.path.join(DATA, "agents")         # vault.py lee AGENTS de __main__ cuando server no está cargado
os.makedirs(AGENTS)
os.environ.pop("PARLA_SECRET_KEY", None)
os.environ.pop("PARLA_SECRET_KEY_OLD", None)
from parla import vault  # noqa: E402

AID, OTHER = "abcd1234", "beef5678"
SECRET = "sk-live-NO-DEBE-VERSE-0123456789"
file = lambda aid=AID: os.path.join(AGENTS, aid + ".secrets.json")
raw = lambda aid=AID: open(file(aid), encoding="utf-8").read()

# HKDF-SHA256: vector de prueba 1 del RFC 5869
okm = vault.hkdf(bytes.fromhex("0b" * 22), bytes.fromhex("f0f1f2f3f4f5f6f7f8f9"), 42, bytes.fromhex("000102030405060708090a0b0c"))
assert okm.hex() == "3cb25f25faacd57a90434f64d0362f2a2d2d0a90cf1a5a4c5db02d56ecc4c5bf34007208d5b887185865", okm.hex()

# sin clave: plano como siempre (0600), y la API avisa que no está cifrado
assert not vault.encrypted()
vault.put(AID, "API_KEY", SECRET)
assert json.loads(raw()) == {"API_KEY": SECRET} and stat.S_IMODE(os.stat(file()).st_mode) == 0o600

# con clave: el archivo plano viejo se lee igual y se cifra en la próxima escritura
os.environ["PARLA_SECRET_KEY"] = "clave-uno"
assert vault.encrypted() and vault.values(AID) == {"API_KEY": SECRET}
vault.put(AID, "TOKEN", "otro-valor-secreto")
blob = json.loads(raw())
assert blob["enc"] == "AES-256-GCM" and set(blob) == {"enc", "nonce", "ct"} and SECRET not in raw() and "TOKEN" not in raw()
assert stat.S_IMODE(os.stat(file()).st_mode) == 0o600
assert vault.values(AID) == {"API_KEY": SECRET, "TOKEN": "otro-valor-secreto"} and vault.names(AID) == ["API_KEY", "TOKEN"]
assert vault.mask("Bearer " + SECRET, AID) == "Bearer ••••"
first = raw()
vault.put(AID, "TOKEN", "otro-valor-secreto")
assert json.loads(raw())["nonce"] != json.loads(first)["nonce"]           # nonce nuevo en cada escritura
# la subclave no es la clave: la de AES sale de HKDF con su propia etiqueta (no la que firma los audios del teléfono)
assert vault.hkdf(b"clave-uno", b"parla-vault-v1") != hashlib.sha256(b"parla-audio\0clave-uno").digest()

# cambiado a mano o copiado a otro agente: no abre (GCM autentica; el id del agente es dato asociado)
for tamper in (lambda b: dict(b, ct=base64.b64encode(bytes([base64.b64decode(b["ct"])[0] ^ 1]) + base64.b64decode(b["ct"])[1:]).decode()),
               lambda b: dict(b, nonce=base64.b64encode(b"\0" * 12).decode())):
    with open(file(), "w") as f:
        json.dump(tamper(json.loads(first)), f)
    try:
        vault._read(AID)
        raise AssertionError("abrió un archivo cambiado")
    except vault.VaultError:
        pass
with open(file(), "w") as f:
    f.write(first)
assert vault.values(AID)["API_KEY"] == SECRET
with open(file(OTHER), "w") as f:
    f.write(first)                                                        # el de AID, intacto, en otro agente
err = io.StringIO()
with contextlib.redirect_stderr(err):
    assert vault.values(OTHER) == {} and vault.values(OTHER) == {}        # el motor sigue (sin claves) y avisa una vez
assert err.getvalue().count("vault:") == 1 and SECRET not in err.getvalue()
try:
    vault.put(OTHER, "X", "y")                                            # no pisa claves que no pudo leer
    raise AssertionError("pisó")
except ValueError as error:
    assert "PARLA_SECRET_KEY" in str(error)
os.remove(file(OTHER))

# clave equivocada: no abre; PARLA_SECRET_KEY_OLD sirve para leer mientras se rota
os.environ["PARLA_SECRET_KEY"] = "clave-dos"
try:
    vault._read(AID)
    raise AssertionError("abrió con otra clave")
except vault.VaultError:
    pass
os.environ["PARLA_SECRET_KEY_OLD"] = "clave-uno"
assert vault.values(AID)["API_KEY"] == SECRET
del os.environ["PARLA_SECRET_KEY_OLD"]

# rotación por la línea de comandos: todos los archivos (cifrados y planos) quedan con la nueva
with open(file(OTHER), "w") as f:
    json.dump({"PLANO": "valor-plano-secreto"}, f)
before = raw()
env = dict(os.environ, PARLA_DATA=DATA)
env.pop("PARLA_SECRET_KEY", None)
bad = subprocess.run([sys.executable, "-m", "parla.vault", "rotate", "--old", "mala", "--new", "clave-dos"], cwd=support.ROOT, env=env, capture_output=True, text=True)
assert bad.returncode == 1 and raw() == before, bad.stdout + bad.stderr       # una no abre: no toca ninguna
assert json.loads(raw(OTHER)) == {"PLANO": "valor-plano-secreto"}
ok = subprocess.run([sys.executable, "-m", "parla.vault", "rotate", "--old", "clave-uno", "--new", "clave-dos"], cwd=support.ROOT, env=env, capture_output=True, text=True)
assert ok.returncode == 0 and "2 secrets files" in ok.stdout, ok.stdout + ok.stderr
assert SECRET not in ok.stdout + ok.stderr + bad.stdout + bad.stderr and "valor-plano" not in raw(OTHER)
assert vault.values(AID)["API_KEY"] == SECRET and vault.values(OTHER) == {"PLANO": "valor-plano-secreto"}
os.environ["PARLA_SECRET_KEY"] = "clave-uno"
try:
    vault._read(AID)
    raise AssertionError("la vieja ya no abre")
except vault.VaultError:
    pass
os.environ["PARLA_SECRET_KEY"] = "clave-dos"

# por HTTP: la pantalla Claves sabe si está cifrado; el valor nunca vuelve ni sale en la consola del servidor
for key in ("clave-dos", ""):
    log = os.path.join(DATA, "server-%s.log" % (key or "plain"))
    env = dict(os.environ, PARLA_DATA=os.path.join(DATA, key or "plain"), PARLA_SECRET_KEY=key)
    port = support.free_port()
    with open(log, "w") as out:
        proc = subprocess.Popen([sys.executable, os.path.join(support.ROOT, "app.py"), str(port)], cwd=support.ROOT, env=env, stdout=out, stderr=out)
    try:
        for _ in range(150):
            try:
                urllib.request.urlopen("http://127.0.0.1:%d/api/auth/me" % port, timeout=2).close()
                break
            except OSError:
                time.sleep(0.2)

        def call(method, path, body=None):
            req = urllib.request.Request("http://127.0.0.1:%d/api%s" % (port, path), method=method, data=json.dumps(body).encode() if body is not None else None,
                                         headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.loads(r.read())
        aid = call("POST", "/agents", {"name": "cripto"})["id"]
        assert call("PUT", "/agents/%s/secrets" % aid, {"name": "API_KEY", "value": SECRET}) == {"secrets": ["API_KEY"]}
        got = call("GET", "/agents/%s/secrets" % aid)
        assert got == {"secrets": ["API_KEY"], "encrypted": bool(key)}, got
        on_disk = open(os.path.join(DATA, key or "plain", "agents", aid + ".secrets.json")).read()
        assert (SECRET in on_disk) == (not key)
    finally:
        proc.kill()
        proc.wait()
    assert SECRET not in open(log).read()
print("ok: claves cifradas en disco (AES-256-GCM, HKDF, rotación, planos viejos)")
