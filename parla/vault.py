"""Claves secretas por agente: agents/<id>.secrets.json (permisos 600). Nunca viajan en el JSON del agente.

Con PARLA_SECRET_KEY el archivo va cifrado con AES-256-GCM (librería «cryptography»): {"enc": "AES-256-GCM", "nonce",
"ct"}, con el id del agente como dato asociado (un archivo copiado a otro agente no abre). La clave AES sale de
PARLA_SECRET_KEY por HKDF-SHA256 (RFC 5869, con hmac) con su propia etiqueta: no es la misma que firma los audios.
Sin PARLA_SECRET_KEY: JSON plano como siempre (la pantalla Claves avisa). Un archivo plano viejo se lee igual y queda
cifrado la próxima vez que se guarda. PARLA_SECRET_KEY_OLD: la clave anterior, solo para leer mientras se rota.
Rotar:  python -m parla.vault rotate --old VIEJA --new NUEVA   (sin --old/--new: PARLA_SECRET_KEY_OLD / PARLA_SECRET_KEY)"""
import argparse
import base64
import glob
import hashlib
import hmac
import json
import os
import re
import sys
import unicodedata

from . import agents_dir, write_json

_cache = {}     # ruta -> ((mtime_ns, tamaño, inodo, claves), valores): mask() corre en cada respuesta
_warned = set()
ALG = "AES-256-GCM"


class VaultError(ValueError):
    pass


def hkdf(secret, info, length=32, salt=b""):
    """HKDF-SHA256 (RFC 5869): extract + expand con hmac."""
    prk = hmac.new(salt or b"\0" * 32, secret, hashlib.sha256).digest()
    out, block = b"", b""
    for i in range((length + 31) // 32):
        block = hmac.new(prk, block + info + bytes([i + 1]), hashlib.sha256).digest()
        out += block
    return out[:length]


def _keys():
    """(clave para escribir o None, [claves para leer])."""
    new, old = os.environ.get("PARLA_SECRET_KEY") or None, os.environ.get("PARLA_SECRET_KEY_OLD") or None
    return new, [k for k in (new, old) if k]


def encrypted():
    """True si lo que se guarde queda cifrado (hay PARLA_SECRET_KEY)."""
    return bool(_keys()[0])


def _aes(key):
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    return AESGCM(hkdf(key.encode(), b"parla-vault-v1"))


def seal(agent_id, data, key):
    nonce = os.urandom(12)
    ct = _aes(key).encrypt(nonce, json.dumps(data, ensure_ascii=False).encode(), agent_id.encode())
    return {"enc": ALG, "nonce": base64.b64encode(nonce).decode(), "ct": base64.b64encode(ct).decode()}


def unseal(agent_id, blob, keys):
    """El dict de claves de un archivo (cifrado o plano viejo). VaultError si está cifrado y ninguna clave lo abre."""
    if not (isinstance(blob, dict) and "enc" in blob):
        return blob                     # plano (sin clave, o de antes de cifrar): los nombres son MAYÚSCULAS, «enc» no choca
    if blob["enc"] != ALG:
        raise VaultError("las claves están cifradas con un formato desconocido")
    from cryptography.exceptions import InvalidTag
    for key in keys:
        try:
            return json.loads(_aes(key).decrypt(base64.b64decode(blob["nonce"]), base64.b64decode(blob["ct"]), agent_id.encode()))
        except (InvalidTag, ValueError, TypeError):
            continue
    raise VaultError("no se pueden leer las claves: falta PARLA_SECRET_KEY, no es la misma con la que se guardaron o el archivo se modificó")


def _path(agent_id):
    if not re.fullmatch(r"[0-9a-f]{8}", str(agent_id)):
        raise ValueError("agente inválido")
    return os.path.join(agents_dir(), agent_id + ".secrets.json")


def _normal(name):
    """'api key de Mercado Pago' -> 'API_KEY_DE_MERCADO_PAGO'."""
    plain = unicodedata.normalize("NFD", str(name)).encode("ascii", "ignore").decode()
    return re.sub(r"[^A-Z0-9]+", "_", plain.upper()).strip("_")


def _read(agent_id):
    """{NOMBRE: valor}; {} si no hay archivo. VaultError si está cifrado y no se puede abrir."""
    path = _path(agent_id)
    try:
        st = os.stat(path)
    except OSError:
        return {}
    keys = _keys()[1]
    stamp = (st.st_mtime_ns, st.st_size, st.st_ino, tuple(hashlib.sha256(k.encode()).digest() for k in keys))   # os.replace cambia el inodo
    if path in _cache and _cache[path][0] == stamp:
        return dict(_cache[path][1])
    try:
        with open(path, encoding="utf-8") as f:
            blob = json.load(f)
    except (OSError, ValueError):
        return {}
    data = unseal(agent_id, blob, keys)
    _cache[path] = (stamp, data)
    return dict(data)


def values(agent_id):
    """{NOMBRE: valor} para el motor ({{ secret.NOMBRE }}). Vacío si no hay, o si no se pueden descifrar (avisa una vez)."""
    try:
        return _read(agent_id)
    except VaultError as error:
        if agent_id not in _warned:
            _warned.add(agent_id)
            print("vault: agente %s: %s" % (agent_id, error), file=sys.stderr)     # nunca un valor
        return {}
    except ValueError:
        return {}


def names(agent_id):
    return sorted(values(agent_id))


def _save(agent_id, data):
    path = _path(agent_id)
    if not data:
        if os.path.exists(path):
            os.remove(path)
        return
    key = _keys()[0]
    if key:
        write_json(path, seal(agent_id, data, key), 0o600)
    else:
        write_json(path, data, 0o600, indent=2)


def put(agent_id, name, value):
    key = _normal(name)
    if not key:
        raise ValueError("ponele un nombre a la clave, por ejemplo API_KEY")
    if len(key) > 64:
        raise ValueError("el nombre de la clave es muy largo (hasta 64 letras)")
    if not isinstance(value, str) or not value:
        raise ValueError("falta el valor de la clave")
    if len(value) > 10000:
        raise ValueError("el valor es muy largo (hasta 10.000 caracteres)")
    data = _read(agent_id)            # si no se puede descifrar: VaultError, y no se pisan las otras claves
    data[key] = value
    _save(agent_id, data)
    return key


def delete(agent_id, name):
    data = _read(agent_id)
    data.pop(_normal(name), None)
    _save(agent_id, data)


def mask(text, agent_id):
    """Tapa con •••• cualquier valor secreto (de 4 o más caracteres) que aparezca en el texto."""
    if not isinstance(text, str):
        return text
    for value in sorted(values(agent_id).values(), key=len, reverse=True):
        if isinstance(value, str) and len(value) >= 4:
            text = text.replace(value, "••••")
    return text


def rotate(old, new):
    """Vuelve a cifrar todos los archivos de claves con «new» (también los planos). -> cuántos. Si alguno no abre con
    «old» (o «new»), no toca ninguno."""
    if not new:
        raise VaultError("falta la clave nueva")
    opened = []
    for path in sorted(glob.glob(os.path.join(agents_dir(), "*.secrets.json"))):
        agent_id = os.path.basename(path).split(".")[0]
        with open(path, encoding="utf-8") as f:
            opened.append((path, agent_id, unseal(agent_id, json.load(f), [k for k in (old, new) if k])))
    for path, agent_id, data in opened:
        write_json(path, seal(agent_id, data, new), 0o600)
    _cache.clear()
    return len(opened)


def main(argv=None):
    p = argparse.ArgumentParser(prog="python -m parla.vault", description="Parla: per-agent secrets encrypted at rest")
    sub = p.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("rotate", help="re-encrypt every secrets file with a new PARLA_SECRET_KEY (also encrypts plaintext files)")
    r.add_argument("--old", default=os.environ.get("PARLA_SECRET_KEY_OLD"), help="previous key (default PARLA_SECRET_KEY_OLD; empty = plaintext files)")
    r.add_argument("--new", default=os.environ.get("PARLA_SECRET_KEY"), help="new key (default PARLA_SECRET_KEY)")
    args = p.parse_args(argv)
    try:
        n = rotate(args.old, args.new)
    except VaultError as error:
        print("error: %s" % error, file=sys.stderr)
        return 1
    print("ok: %d secrets files encrypted with the new key. Restart Parla (every replica) with the new PARLA_SECRET_KEY." % n)
    return 0


if __name__ == "__main__":
    sys.exit(main())
