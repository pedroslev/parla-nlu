"""SSO con OIDC contra un proveedor de mentira (http.server en un puerto libre: discovery, JWKS, token y logout) con
claves RSA de 2048 bits generadas acá en Python puro. Levanta dos copias del servidor con datos temporales."""
import base64
import hashlib
import http.client
import json
import os
import random
import shutil
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import support

TMP = support.temp_data()
from parla import oidc  # noqa: E402


# ---------- RSA de prueba (solo para firmar acá; Parla solo verifica) ----------
def is_prime(n, rounds=40):
    if n < 2:
        return False
    for p in (2, 3, 5, 7, 11, 13, 17, 19, 23, 29, 31, 37):
        if n % p == 0:
            return n == p
    d, r = n - 1, 0
    while d % 2 == 0:
        d, r = d // 2, r + 1
    for _ in range(rounds):
        x = pow(random.randrange(2, n - 1), d, n)
        if x in (1, n - 1):
            continue
        for _ in range(r - 1):
            x = pow(x, 2, n)
            if x == n - 1:
                break
        else:
            return False
    return True


def prime(bits):
    while True:
        n = random.getrandbits(bits) | (1 << bits - 1) | (1 << bits - 2) | 1
        if is_prime(n):
            return n


def keygen(bits=2048, e=65537):
    while True:
        p, q = prime(bits // 2), prime(bits // 2)
        phi = (p - 1) * (q - 1)
        if p != q and phi % e and (p * q).bit_length() == bits:
            return p * q, e, pow(e, -1, phi)


b64 = lambda raw: base64.urlsafe_b64encode(raw).rstrip(b"=").decode()
as_bytes = lambda i: i.to_bytes((i.bit_length() + 7) // 8, "big")


def sign(key, message, alg="RS256"):
    n, e, d = key
    hash_fn, prefix = oidc.DIGEST_INFO[alg]
    k = (n.bit_length() + 7) // 8
    t = prefix + hash_fn(message).digest()
    em = b"\x00\x01" + b"\xff" * (k - len(t) - 3) + b"\x00" + t
    return pow(int.from_bytes(em, "big"), d, n).to_bytes(k, "big")


def jwt(key, kid, claims, alg="RS256"):
    head = b64(json.dumps({"alg": alg, "kid": kid, "typ": "JWT"}).encode()) + "." + b64(json.dumps(claims).encode())
    return head + "." + b64(sign(key, head.encode(), alg))


K1, K2, K3 = keygen(), keygen(), keygen()
jwk = lambda key, kid: {"kty": "RSA", "kid": kid, "use": "sig", "alg": "RS256", "n": b64(as_bytes(key[0])), "e": b64(as_bytes(key[1]))}

# rsa_verify solo
msg = b"hola.mundo"
assert oidc.rsa_verify(K1[0], K1[1], msg, sign(K1, msg))
assert oidc.rsa_verify(K1[0], K1[1], msg, sign(K1, msg, "RS512"), "RS512")
assert not oidc.rsa_verify(K1[0], K1[1], msg, sign(K1, msg), "RS512")
assert not oidc.rsa_verify(K1[0], K1[1], b"hola.mundO", sign(K1, msg))
assert not oidc.rsa_verify(K2[0], K2[1], msg, sign(K1, msg))
bad = bytearray(sign(K1, msg))
bad[-1] ^= 1
assert not oidc.rsa_verify(K1[0], K1[1], msg, bytes(bad))
assert not oidc.rsa_verify(K1[0], K1[1], msg, sign(K1, msg)[1:])
small = keygen(1024)
assert not oidc.rsa_verify(small[0], small[1], msg, sign(small, msg))       # menos de 2048 bits: no
assert oidc._claim({"realm_access": {"roles": ["a"]}, "https://x.com/roles": ["b"]}, "realm_access.roles") == ["a"]
assert oidc._claim({"https://x.com/roles": ["b"]}, "https://x.com/roles") == ["b"]


# ---------- el proveedor de mentira ----------
class IdP:
    port = support.free_port()
    issuer = "http://127.0.0.1:%d" % port
    keys = {"k1": K1}            # lo que publica la JWKS
    sign_with = ("k1", K1)       # con qué firma el ID token (kid, clave)
    mutate = None                # función(claims) para romper el ID token
    codes = {}                   # code -> lo del /authorize
    claims = {}                  # las de la próxima persona que «entra»
    jwks_hits = 0
    basic = []                   # los Authorization que llegaron al token endpoint


class IdPHandler(BaseHTTPRequestHandler):
    def send(self, status, body=None, headers=None):
        raw = json.dumps(body).encode() if body is not None else b""
        self.send_response(status)
        for k, v in dict({"Content-Type": "application/json"}, **(headers or {})).items():
            self.send_header(k, v)
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):
        url = urllib.parse.urlsplit(self.path)
        q = dict(urllib.parse.parse_qsl(url.query))
        if url.path == "/.well-known/openid-configuration":
            i = IdP.issuer
            return self.send(200, {"issuer": i, "authorization_endpoint": i + "/authorize", "token_endpoint": i + "/token",
                                   "jwks_uri": i + "/jwks", "end_session_endpoint": i + "/logout",
                                   "token_endpoint_auth_methods_supported": ["client_secret_basic", "client_secret_post"]})
        if url.path == "/jwks":
            IdP.jwks_hits += 1
            return self.send(200, {"keys": [jwk(k, kid) for kid, k in IdP.keys.items()]})
        if url.path == "/authorize":       # la persona ya «entró»: vuelve con un code
            assert q["response_type"] == "code" and q["code_challenge_method"] == "S256" and q["client_id"] == "parla"
            assert q["scope"] == "openid email profile"
            code = os.urandom(8).hex()
            IdP.codes[code] = dict(q, claims=dict(IdP.claims))
            return self.send(302, headers={"Location": q["redirect_uri"] + "?" + urllib.parse.urlencode({"code": code, "state": q["state"]})})
        self.send(404, {})

    def do_POST(self):
        form = dict(urllib.parse.parse_qsl(self.rfile.read(int(self.headers["Content-Length"])).decode()))
        IdP.basic.append(self.headers.get("Authorization"))
        if self.headers.get("Authorization") != "Basic " + base64.b64encode(b"parla:s3cr3t").decode():
            return self.send(401, {"error": "invalid_client"})
        got = IdP.codes.pop(form.get("code"), None)
        if not got or form.get("redirect_uri") != got["redirect_uri"]:
            return self.send(400, {"error": "invalid_grant"})
        if b64(hashlib.sha256(form["code_verifier"].encode()).digest()) != got["code_challenge"]:
            return self.send(400, {"error": "invalid_grant", "error_description": "PKCE"})
        now = int(time.time())
        claims = dict({"iss": IdP.issuer, "aud": "parla", "iat": now, "exp": now + 300, "nonce": got["nonce"]}, **got["claims"])
        if IdP.mutate:
            IdP.mutate(claims)
        self.send(200, {"access_token": "AT-secreto", "token_type": "Bearer", "id_token": jwt(IdP.sign_with[1], IdP.sign_with[0], claims)})

    def log_message(self, *args):
        pass


idp = ThreadingHTTPServer(("127.0.0.1", IdP.port), IdPHandler)
threading.Thread(target=idp.serve_forever, daemon=True).start()


# ---------- Parla ----------
def call(port, method, path, body=None, cookie=None, headers=None):
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=30)
    h = dict({"Content-Type": "application/json"}, **(headers or {}))
    if cookie:
        h["Cookie"] = cookie
    conn.request(method, path, json.dumps(body) if body is not None else None, h)
    r = conn.getresponse()
    raw = r.read()
    conn.close()
    try:
        data = json.loads(raw)
    except ValueError:
        data = raw
    return r.status, data, r.getheader("Location"), r.getheader("Set-Cookie")


def sso(port, claims, state=None, cookie=None, headers=None):
    """Todo el ida y vuelta como lo haría el navegador. -> (Location final de Parla, cookie de sesión o None)."""
    IdP.claims = claims
    status, _, location, set_cookie = call(port, "GET", "/api/auth/oidc/start")
    assert status == 302 and location.startswith(IdP.issuer + "/authorize?"), (status, location)
    assert "SameSite=Lax" in set_cookie and "Path=/api/auth/oidc" in set_cookie and "HttpOnly" in set_cookie
    oidc_cookie = set_cookie.split(";")[0]
    conn = http.client.HTTPConnection("127.0.0.1", IdP.port, timeout=10)
    conn.request("GET", location[len(IdP.issuer):])
    back = conn.getresponse().getheader("Location")
    conn.close()
    url = urllib.parse.urlsplit(back)
    assert url.path == "/api/auth/oidc/callback" and url.netloc == "127.0.0.1:%d" % port, back
    query = dict(urllib.parse.parse_qsl(url.query))
    if state:
        query["state"] = state
    status, _, location, set_cookie = call(port, "GET", url.path + "?" + urllib.parse.urlencode(query),
                                           cookie=oidc_cookie if cookie is None else cookie, headers=headers)
    assert status == 302, status
    session = set_cookie.split(";")[0] if set_cookie and set_cookie.startswith("parla_session=") else None
    return location, session


def wait(port):
    for _ in range(100):
        try:
            if call(port, "GET", "/api/auth/me")[0] == 200:
                return
        except OSError:
            time.sleep(0.2)


def audit(port, owner):
    return call(port, "GET", "/api/audit", cookie=owner)[1]["entries"]


XFF = {"X-Forwarded-For": "203.0.113.9"}
base_env = {"PARLA_OIDC_ISSUER": IdP.issuer, "PARLA_OIDC_CLIENT_ID": "parla", "PARLA_OIDC_CLIENT_SECRET_FILE": os.path.join(TMP, "secret")}
with open(base_env["PARLA_OIDC_CLIENT_SECRET_FILE"], "w") as f:
    f.write("s3cr3t\n")
servers = []
try:
    # ===== A: mapa de roles, sin rol por defecto, solo SSO =====
    os.environ.update(base_env, PARLA_OIDC_ROLE_CLAIM="groups", PARLA_OIDC_LABEL="Keycloak", PARLA_OIDC_ONLY="1",
                      PARLA_OIDC_ROLE_MAP="parla-owners:owner,parla-editors:editor,parla-analysts:analyst,support:agent")
    server, A = support.start_server(os.path.join(TMP, "a"))
    servers.append(server)
    wait(A)
    me = call(A, "GET", "/api/auth/me")[1]
    assert me == {"enabled": True, "user": None, "oidc": {"enabled": True, "label": "Keycloak", "only": True, "roles": True, "local": True}}, me
    assert call(A, "GET", "/api/auth/me", headers=XFF)[1]["oidc"]["local"] is False
    assert call(A, "GET", "/api/agents")[0] == 401                 # con SSO configurado y sin usuarios: igual pide entrar
    # break-glass: el dueño local solo desde esta compu
    assert call(A, "POST", "/api/users", {"name": "admin", "password": "secreta123"}, headers=XFF)[0] == 403
    status, _, _, sc = call(A, "POST", "/api/users", {"name": "admin", "password": "secreta123"})
    assert status == 200
    owner = sc.split(";")[0]

    # camino feliz
    loc, ana = sso(A, {"sub": "u-ana", "preferred_username": "ana", "email": "ana@example.com", "groups": ["otros", "parla-editors"]})
    assert loc == "/" and ana, loc
    assert IdP.basic[-1].startswith("Basic ")                      # client_secret_basic, el secreto salió del archivo
    assert call(A, "GET", "/api/auth/me", cookie=ana)[1]["user"] == {"name": "ana", "role": "editor", "bots": None}
    status, agent, _, _ = call(A, "POST", "/api/agents", {"name": "tmp test_oidc"}, cookie=ana)
    assert status == 200
    users = json.load(open(os.path.join(TMP, "a", "users.json")))["users"]
    rec = next(u for u in users if u["name"] == "ana")
    assert rec["sso"] is True and rec["sub"] == "u-ana" and "hash" not in rec and rec["email"] == "ana@example.com"
    entry = next(e for e in audit(A, owner) if e["action"] == "login.sso")
    assert entry["user"] == "ana" and entry["role"] == "editor" and entry["detail"].startswith("ok"), entry
    assert "AT-secreto" not in json.dumps(audit(A, owner))

    # el dueño la limita a un agente; el rol lo maneja el proveedor, la contraseña no existe
    assert call(A, "PUT", "/api/users/ana", {"bots": [agent["id"]]}, cookie=owner)[0] == 200
    status, data, _, _ = call(A, "PUT", "/api/users/ana", {"role": "owner"}, cookie=owner)
    assert status == 400 and "proveedor" in data["error"], data
    assert call(A, "PUT", "/api/users/ana", {"password": "otra12345"}, cookie=owner)[0] == 400
    assert next(u for u in call(A, "GET", "/api/users", cookie=owner)[1]["users"] if u["name"] == "ana")["sso"] is True

    # el rol cambia en el proveedor: se aplica en el próximo login y «bots» se mantiene
    loc, ana = sso(A, {"sub": "u-ana", "preferred_username": "ana", "groups": ["parla-analysts"]})
    assert call(A, "GET", "/api/auth/me", cookie=ana)[1]["user"] == {"name": "ana", "role": "analyst", "bots": [agent["id"]]}

    # sin un grupo mapeado (y sin PARLA_OIDC_DEFAULT_ROLE): no entra
    loc, session = sso(A, {"sub": "u-pepe", "preferred_username": "pepe", "groups": ["otros"]})
    assert loc == "/?sso_error=denied" and session is None
    entry = audit(A, owner)[0]
    assert entry["action"] == "login.sso" and entry["detail"].startswith("falló: sin un rol"), entry

    # nunca pisa a un usuario local con el mismo nombre
    loc, admin2 = sso(A, {"sub": "u-otro", "preferred_username": "admin", "groups": "support"})
    me = call(A, "GET", "/api/auth/me", cookie=admin2)[1]["user"]
    assert me["name"].startswith("admin-") and me["role"] == "agent", me
    assert call(A, "POST", "/api/auth/login", {"name": "admin", "password": "secreta123"})[0] == 200    # el local sigue

    # contraseñas con PARLA_OIDC_ONLY: solo el dueño, solo desde acá
    assert call(A, "POST", "/api/auth/login", {"name": "admin", "password": "secreta123"}, headers=XFF)[0] == 403
    assert call(A, "POST", "/api/auth/login", {"name": "admin", "password": "secreta123"}, headers={"Host": "parla.example.com"})[0] == 403
    assert call(A, "POST", "/api/users", {"name": "edu", "role": "editor", "password": "secreta123"}, cookie=owner)[0] == 200
    assert call(A, "POST", "/api/auth/login", {"name": "edu", "password": "secreta123"})[0] == 403
    assert call(A, "POST", "/api/auth/login", {"name": "ana", "password": ""})[0] == 401          # los de SSO no tienen contraseña

    # state: de otro navegador, cambiado o reusado
    assert sso(A, {"sub": "u-ana", "groups": ["parla-editors"]}, cookie="parla_oidc=otro")[0] == "/?sso_error=state"
    assert sso(A, {"sub": "u-ana", "groups": ["parla-editors"]}, state="x", cookie="parla_oidc=x")[0] == "/?sso_error=state"
    IdP.claims = {"sub": "u-ana", "groups": ["parla-editors"]}
    _, _, location, sc = call(A, "GET", "/api/auth/oidc/start")
    conn = http.client.HTTPConnection("127.0.0.1", IdP.port)
    conn.request("GET", location[len(IdP.issuer):])
    back = urllib.parse.urlsplit(conn.getresponse().getheader("Location"))
    conn.close()
    path = back.path + "?" + back.query
    first = call(A, "GET", path, cookie=sc.split(";")[0], headers={"Origin": IdP.issuer})    # sin el chequeo de Origin
    assert first[2] == "/" and first[3].startswith("parla_session="), first[:3]
    assert call(A, "GET", path, cookie=sc.split(";")[0])[2] == "/?sso_error=state"      # de un solo uso
    status, _, location, _ = call(A, "GET", "/api/auth/oidc/callback?error=access_denied&state=x")
    assert location == "/?sso_error=idp"

    # ID tokens rotos
    def broken(change):
        IdP.mutate = change
        try:
            return sso(A, {"sub": "u-ana", "groups": ["parla-editors"]})
        finally:
            IdP.mutate = None
    assert broken(lambda c: c.update(nonce="otro")) == ("/?sso_error=failed", None)
    assert broken(lambda c: c.update(exp=time.time() - 3600)) == ("/?sso_error=failed", None)
    assert broken(lambda c: c.update(iat=time.time() + 3600)) == ("/?sso_error=failed", None)
    assert broken(lambda c: c.update(aud="otra-app")) == ("/?sso_error=failed", None)
    assert broken(lambda c: c.update(aud=["parla", "otra-app"], azp="otra-app")) == ("/?sso_error=failed", None)
    assert broken(lambda c: c.update(iss="https://evil.example.com")) == ("/?sso_error=failed", None)
    assert broken(lambda c: c.update(exp=time.time() - 30))[1]                           # dentro del margen: sí
    IdP.sign_with = ("k1", K3)                                                         # firma con otra clave
    assert sso(A, {"sub": "u-ana", "groups": ["parla-editors"]}) == ("/?sso_error=failed", None)
    details = [e["detail"] for e in audit(A, owner)[:10] if e["action"] == "login.sso"]
    assert any("firma inválida" in d for d in details) and any("nonce" in d for d in details) and any("venció" in d for d in details), details
    # clave nueva (kid desconocido): Parla vuelve a pedir la JWKS
    IdP.keys["k2"], IdP.sign_with = K2, ("k2", K2)
    hits = IdP.jwks_hits
    loc, session = sso(A, {"sub": "u-ana", "groups": ["parla-editors"]})
    assert loc == "/" and session and IdP.jwks_hits == hits + 1
    IdP.sign_with = ("k9", K2)                                                         # kid que no está ni después de refrescar
    assert sso(A, {"sub": "u-ana", "groups": ["parla-editors"]})[0] == "/?sso_error=failed"
    IdP.sign_with = ("k2", K2)

    # cerrar sesión: también en el proveedor
    status, data, _, sc = call(A, "POST", "/api/auth/logout", cookie=session)
    assert status == 200 and "Max-Age=0" in sc and data["logout_url"].startswith(IdP.issuer + "/logout?client_id=parla"), data
    assert call(A, "GET", "/api/agents", cookie=session)[0] == 401
    assert "logout_url" not in call(A, "POST", "/api/auth/logout", cookie=owner)[1]       # el dueño local no

    # ===== B: sin mapa de roles, rol por defecto, contraseñas prendidas =====
    for k in ("PARLA_OIDC_ROLE_CLAIM", "PARLA_OIDC_ROLE_MAP", "PARLA_OIDC_ONLY", "PARLA_OIDC_LABEL"):
        os.environ.pop(k)
    os.environ["PARLA_OIDC_DEFAULT_ROLE"] = "analyst"
    server, B = support.start_server(os.path.join(TMP, "b"))
    servers.append(server)
    wait(B)
    assert call(B, "GET", "/api/auth/me", headers=XFF)[1]["oidc"] == {"enabled": True, "label": "SSO", "only": False, "roles": False, "local": True}
    owner = call(B, "POST", "/api/users", {"name": "admin", "password": "secreta123"})[3].split(";")[0]
    loc, leo = sso(B, {"sub": "u-leo", "email": "leo@example.com", "groups": ["parla-owners"]})
    assert call(B, "GET", "/api/auth/me", cookie=leo)[1]["user"]["role"] == "analyst"        # sin mapa: el rol por defecto
    assert call(B, "GET", "/api/auth/me", cookie=leo)[1]["user"]["name"] == "leo@example.com"
    assert call(B, "PUT", "/api/users/leo@example.com", {"role": "editor"}, cookie=owner)[0] == 200   # el dueño lo cambia en Parla
    loc, leo = sso(B, {"sub": "u-leo", "email": "leo@example.com"})
    assert call(B, "GET", "/api/auth/me", cookie=leo)[1]["user"]["role"] == "editor"          # y se mantiene
    assert call(B, "POST", "/api/auth/login", {"name": "admin", "password": "secreta123"}, headers=XFF)[0] == 200
finally:
    for server in servers:
        server.terminate()
        server.wait()
    idp.shutdown()
    shutil.rmtree(TMP, ignore_errors=True)
print("ok")
