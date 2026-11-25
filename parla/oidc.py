"""Inicio de sesión con OIDC (Keycloak, Entra ID, Google, Okta, Authentik, Auth0…). Solo biblioteca estándar.

Configuración de la instalación (variables de entorno, ver docs/sso.md): PARLA_OIDC_ISSUER, PARLA_OIDC_CLIENT_ID,
PARLA_OIDC_CLIENT_SECRET (o PARLA_OIDC_CLIENT_SECRET_FILE), PARLA_OIDC_SCOPES, PARLA_OIDC_ROLE_CLAIM, PARLA_OIDC_ROLE_MAP,
PARLA_OIDC_DEFAULT_ROLE, PARLA_OIDC_ONLY, PARLA_OIDC_LABEL, PARLA_OIDC_LOGOUT.

Flujo: authorization code + PKCE (S256). GET /api/auth/oidc/start guarda state/nonce/verificador en parla.db (tabla
oidc, con el SHA-256 del state) y deja el state en la cookie parla_oidc (SameSite=Lax: vuelve en la redirección
del proveedor) para atar el login a ese navegador. GET /api/auth/oidc/callback canjea el code en el token endpoint y
valida el ID token: firma RS256/384/512 con la JWKS (verificación RSA PKCS#1 v1.5 en Python puro, abajo), iss, aud/azp,
exp/iat (60 s de margen) y nonce. Después crea o actualiza el usuario (sso: true, sin contraseña) y abre una sesión
normal de Parla (auth._login).
"""
import base64
import hashlib
import hmac
import json
import os
import re
import secrets
import time
import urllib.error
import urllib.parse
import urllib.request

from . import auth, db

LEEWAY = 60           # segundos de margen para exp/iat (relojes desparejos)
PENDING_SECONDS = 600  # cuánto puede tardar la persona en el proveedor
CACHE_SECONDS = 3600
_cache = {}           # url -> (instante, json): discovery y JWKS
DIGEST_INFO = {       # alg -> (hash, prefijo DER de DigestInfo de RFC 8017 §9.2)
    "RS256": (hashlib.sha256, bytes.fromhex("3031300d060960864801650304020105000420")),
    "RS384": (hashlib.sha384, bytes.fromhex("3041300d060960864801650304020205000430")),
    "RS512": (hashlib.sha512, bytes.fromhex("3051300d060960864801650304020305000440")),
}


class SSOFail(Exception):
    """code: lo que ve la persona (la interfaz lo traduce: ?sso_error=code); reason: para la auditoría y la consola."""
    def __init__(self, code, reason):
        super().__init__(reason)
        self.code = code


def env(name, default=""):
    return os.environ.get("PARLA_OIDC_" + name, default).strip()


def enabled():
    return bool(env("ISSUER") and env("CLIENT_ID"))


def only():
    return enabled() and env("ONLY") in ("1", "true", "yes", "on")


def role_map():
    """PARLA_OIDC_ROLE_MAP «grupo:rol,grupo:rol» -> {grupo: rol}. Vacío si no hay PARLA_OIDC_ROLE_CLAIM."""
    if not env("ROLE_CLAIM"):
        return {}
    pairs = (p.rsplit(":", 1) for p in env("ROLE_MAP").split(",") if ":" in p)       # el grupo puede tener «:»
    return {g.strip(): r.strip() for g, r in pairs if g.strip() and r.strip() in auth.ROLES}


def public_config(handler):
    """Lo que necesita la pantalla de entrada (va en /api/auth/me)."""
    return {"enabled": enabled(), "label": env("LABEL") or "SSO", "only": only(), "roles": bool(role_map()),
            "local": not only() or break_glass(handler)}


def break_glass(handler):
    """Con PARLA_OIDC_ONLY, la contraseña sigue sirviendo para el dueño desde esta misma compu: conexión desde el
    loopback, Host local y sin encabezados de proxy (un proxy en la misma compu también llega desde 127.0.0.1)."""
    peer = handler.client_address[0]
    host = re.sub(r":\d+$", "", (handler.headers.get("Host") or "").lower())
    proxied = any(handler.headers.get(h) for h in ("X-Forwarded-For", "X-Forwarded-Host", "X-Real-IP", "Forwarded"))
    return (peer == "::1" or peer.startswith("127.")) and host in ("127.0.0.1", "localhost", "[::1]") and not proxied


# ---------- HTTP con el proveedor ----------
def _check_url(url):
    """https siempre, salvo un proveedor en esta misma compu (pruebas, Keycloak local)."""
    parts = urllib.parse.urlsplit(url)
    if parts.scheme != "https" and not (parts.scheme == "http" and parts.hostname in ("127.0.0.1", "localhost", "::1")):
        raise SSOFail("config", "el proveedor tiene que usar https: %s" % url[:100])
    return url


def _fetch(url, data=None, headers=None):
    request = urllib.request.Request(_check_url(url), data=data, headers=dict(headers or {}, Accept="application/json"))
    try:
        with urllib.request.urlopen(request, timeout=10) as r:
            return json.loads(r.read(1_000_000))
    except urllib.error.HTTPError as error:
        try:
            detail = json.loads(error.read(10_000)).get("error") or ""
        except ValueError:
            detail = ""
        raise SSOFail("failed", "HTTP %s de %s %s" % (error.code, urllib.parse.urlsplit(url).path, str(detail)[:60]))
    except (OSError, ValueError) as error:
        raise SSOFail("failed", "no pude hablar con el proveedor (%s): %s" % (urllib.parse.urlsplit(url).netloc, type(error).__name__))


def _cached(url, fresh=False):
    hit = _cache.get(url)
    if fresh or not hit or hit[0] < time.time() - CACHE_SECONDS:
        hit = _cache[url] = (time.time(), _fetch(url))
    return hit[1]


def discovery():
    issuer = env("ISSUER")
    found = _cached(issuer.rstrip("/") + "/.well-known/openid-configuration")
    if str(found.get("issuer") or "").rstrip("/") != issuer.rstrip("/"):       # que nadie nos mande a otro proveedor
        raise SSOFail("config", "el issuer del discovery (%s) no es PARLA_OIDC_ISSUER" % str(found.get("issuer"))[:100])
    for key in ("authorization_endpoint", "token_endpoint", "jwks_uri"):
        if not isinstance(found.get(key), str):
            raise SSOFail("config", "al discovery le falta %s" % key)
    return found


def client_secret():
    path = env("CLIENT_SECRET_FILE")
    if path:
        with open(path, encoding="utf-8") as f:
            return f.read().strip()
    return env("CLIENT_SECRET")


# ---------- ID token: JWT firmado con RSA ----------
def b64d(text):
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def rsa_verify(n, e, message, signature, alg="RS256"):
    """RSASSA-PKCS1-v1_5 (RFC 8017 §8.2.2): s^e mod n tiene que ser EXACTAMENTE 00 01 FF…FF 00 DigestInfo(hash).
    Se arma el bloque esperado y se compara entero (no se parsea: sin las trampas de Bleichenbacher '06).
    Solo verifica (todo es público): no hace falta tiempo constante ni protección contra canales laterales."""
    hash_fn, prefix = DIGEST_INFO[alg]
    k = (n.bit_length() + 7) // 8
    if n.bit_length() < 2048 or len(signature) != k:
        return False
    s = int.from_bytes(signature, "big")
    if s >= n:
        return False
    t = prefix + hash_fn(message).digest()
    expected = b"\x00\x01" + b"\xff" * (k - len(t) - 3) + b"\x00" + t
    return hmac.compare_digest(pow(s, e, n).to_bytes(k, "big"), expected)


def _jwk(jwks, kid):
    keys = [k for k in jwks.get("keys") or [] if k.get("kty") == "RSA" and k.get("use", "sig") == "sig"]
    if kid is None:
        return keys[0] if len(keys) == 1 else None
    return next((k for k in keys if k.get("kid") == kid), None)


def verify_id_token(token, config, nonce, now=None):
    """Las claims del ID token si pasa todo; si no, SSOFail. config: el discovery."""
    now = time.time() if now is None else now
    try:
        head, body, sig = token.split(".")
        header, claims, signature = json.loads(b64d(head)), json.loads(b64d(body)), b64d(sig)
    except (ValueError, AttributeError):
        raise SSOFail("failed", "el ID token no es un JWT")
    if not isinstance(header, dict) or not isinstance(claims, dict):
        raise SSOFail("failed", "el ID token no es un JWT")
    alg, kid = header.get("alg"), header.get("kid")
    if alg not in DIGEST_INFO:                 # nunca «none» ni HS256 (con la clave pública como secreto)
        raise SSOFail("failed", "algoritmo de firma no soportado: %s" % str(alg)[:20])
    key = _jwk(_cached(config["jwks_uri"]), kid)
    if key is None:                            # el proveedor rotó la clave: traer la JWKS de nuevo
        key = _jwk(_cached(config["jwks_uri"], fresh=True), kid)
    if key is None:
        raise SSOFail("failed", "no hay una clave «%s» en la JWKS" % str(kid)[:40])
    try:
        n, e = int.from_bytes(b64d(key["n"]), "big"), int.from_bytes(b64d(key["e"]), "big")
    except (KeyError, ValueError, TypeError):
        raise SSOFail("failed", "clave inválida en la JWKS")
    if not rsa_verify(n, e, (head + "." + body).encode(), signature, alg):
        raise SSOFail("failed", "firma inválida")
    if claims.get("iss") != config["issuer"]:
        raise SSOFail("failed", "iss no coincide: %s" % str(claims.get("iss"))[:100])
    aud = claims.get("aud")
    auds = aud if isinstance(aud, list) else [aud]
    client = env("CLIENT_ID")
    if client not in auds or (len(auds) > 1 or "azp" in claims) and claims.get("azp", client) != client:
        raise SSOFail("failed", "aud/azp no es este cliente")
    exp, iat = claims.get("exp"), claims.get("iat")
    if not isinstance(exp, (int, float)) or exp < now - LEEWAY:
        raise SSOFail("failed", "el ID token venció")
    if isinstance(iat, (int, float)) and iat > now + LEEWAY:
        raise SSOFail("failed", "el ID token es del futuro (¿reloj desparejo?)")
    if not (isinstance(claims.get("nonce"), str) and hmac.compare_digest(claims["nonce"], nonce)):
        raise SSOFail("failed", "nonce no coincide")
    if not isinstance(claims.get("sub"), str) or not claims["sub"]:
        raise SSOFail("failed", "falta sub")
    return claims


# ---------- claims -> usuario ----------
def _claim(claims, path):
    """La claim tal cual («https://x.com/roles» de Auth0) o por puntos («realm_access.roles» de Keycloak)."""
    if path in claims:
        return claims[path]
    value = claims
    for part in path.split("."):
        value = value.get(part) if isinstance(value, dict) else None
    return value


def role_for(claims):
    """El rol más alto que dan sus grupos (PARLA_OIDC_ROLE_MAP), o PARLA_OIDC_DEFAULT_ROLE, o None (no entra).
    Sin mapa de roles: None = se queda con el que tiene en Parla (si ya existe)."""
    mapping = role_map()
    if mapping:
        values = _claim(claims, env("ROLE_CLAIM"))
        values = values if isinstance(values, list) else [values] if isinstance(values, str) else []
        roles = {mapping[str(v)] for v in values if str(v) in mapping}
        best = next((r for r in auth.ROLES if r in roles), None)         # ROLES va de más a menos permisos
        if best:
            return best
    default = env("DEFAULT_ROLE")
    return default if default in auth.ROLES else None


def upsert_user(claims):
    """Crea o actualiza el usuario de SSO (por sub). El rol se pisa en cada login si hay mapa de roles; «bots» nunca."""
    with auth.LOCK:
        users = auth._load()
        user = next((u for u in users if u.get("sso") and u.get("sub") == claims["sub"]), None)
        role = role_for(claims)
        if role_map() or not user:
            if not role:
                raise SSOFail("denied", "sin un rol de Parla (grupos: %s)" % str(_claim(claims, env("ROLE_CLAIM") or "groups"))[:120])
        if not user:
            name = re.sub(r"[^\w.@+ -]", "", str(claims.get("preferred_username") or claims.get("email") or claims["sub"]))[:40].strip() or "sso"
            if auth._find(users, name):            # un usuario local (u otro de SSO) ya se llama así: nunca lo pisa
                name = name[:33] + "-" + hashlib.sha256(claims["sub"].encode()).hexdigest()[:6]
            user = {"name": name, "role": role, "sso": True, "sub": claims["sub"], "keys": []}
            users.append(user)
        if role_map() and role != user["role"]:
            user["role"] = role
        if user["role"] == "owner":
            user.pop("bots", None)
        if claims.get("email"):
            user["email"] = str(claims["email"])[:200]
        auth._save(users)
        return {"name": user["name"], "role": user["role"]}


# ---------- rutas ----------
def redirect_uri(handler):
    """Desde PARLA_PUBLIC_URL; si no, el Host del pedido solo si es local o de PARLA_HOSTS (nunca un Host cualquiera)."""
    base = os.environ.get("PARLA_PUBLIC_URL", "").strip().rstrip("/")
    if not base:
        host = (handler.headers.get("Host") or "").lower()
        name = re.sub(r":\d+$", "", host)
        if not (name in ("127.0.0.1", "localhost", "[::1]") or host in auth.hosts() or name in auth.hosts()):
            raise SSOFail("config", "falta PARLA_PUBLIC_URL (el Host %s no es local ni de PARLA_HOSTS)" % host[:80])
        base = ("https" if auth._secure(handler) else "http") + "://" + host
    return base + "/api/auth/oidc/callback"


def _home():
    return (os.environ.get("PARLA_PUBLIC_URL", "").strip().rstrip("/") or "") + "/"


def _state_cookie(handler, value, age):
    secure = "; Secure" if auth._secure(handler) else ""
    return "parla_oidc=%s; HttpOnly; SameSite=Lax; Path=/api/auth/oidc; Max-Age=%d%s" % (value, age, secure)


def _audit(handler, user, role, detail):
    db.audit(user, role, None, "login.sso", detail + " desde " + handler.client_address[0])


def start(handler):
    config = discovery()
    state, nonce, verifier = secrets.token_urlsafe(32), secrets.token_urlsafe(32), secrets.token_urlsafe(48)
    db.q("DELETE FROM oidc WHERE expires < ?", (time.time(),))
    db.q("INSERT INTO oidc (state, nonce, verifier, expires) VALUES (?, ?, ?, ?)",
         (auth._digest(state), nonce, verifier, time.time() + PENDING_SECONDS))
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    query = urllib.parse.urlencode({"response_type": "code", "client_id": env("CLIENT_ID"), "redirect_uri": redirect_uri(handler),
                                    "scope": env("SCOPES") or "openid email profile", "state": state, "nonce": nonce,
                                    "code_challenge": challenge, "code_challenge_method": "S256"})
    sep = "&" if "?" in config["authorization_endpoint"] else "?"
    return 302, b"", {"Location": config["authorization_endpoint"] + sep + query, "Set-Cookie": _state_cookie(handler, state, PENDING_SECONDS)}


def callback(handler, query):
    config = discovery()
    if query.get("error"):                     # la persona canceló o el proveedor no la dejó
        raise SSOFail("idp", "el proveedor respondió %s" % str(query["error"])[:60])
    state = query.get("state") or ""
    cookie = auth.cookie_value(handler, "parla_oidc") or ""
    if not state or not hmac.compare_digest(state, cookie):     # otro navegador (CSRF de login) o la cookie venció
        raise SSOFail("state", "state no coincide con la cookie de este navegador")
    with db.connect() as conn:                 # de un solo uso
        row = conn.execute("SELECT nonce, verifier, expires FROM oidc WHERE state = ?", (auth._digest(state),)).fetchone()
        conn.execute("DELETE FROM oidc WHERE state = ?", (auth._digest(state),))
    if not row or row[2] < time.time():
        raise SSOFail("state", "state desconocido o vencido")
    nonce, verifier = row[0], row[1]
    form = {"grant_type": "authorization_code", "code": query.get("code") or "", "redirect_uri": redirect_uri(handler),
            "code_verifier": verifier, "client_id": env("CLIENT_ID")}
    headers, secret = {"Content-Type": "application/x-www-form-urlencoded"}, client_secret()
    methods = config.get("token_endpoint_auth_methods_supported") or ["client_secret_basic"]    # el default de OIDC
    if secret and "client_secret_basic" in methods:
        pair = urllib.parse.quote(env("CLIENT_ID"), safe="") + ":" + urllib.parse.quote(secret, safe="")
        headers["Authorization"] = "Basic " + base64.b64encode(pair.encode()).decode()
    elif secret:
        form["client_secret"] = secret
    tokens = _fetch(config["token_endpoint"], urllib.parse.urlencode(form).encode(), headers)
    if not isinstance(tokens, dict) or not isinstance(tokens.get("id_token"), str):
        raise SSOFail("failed", "el token endpoint no devolvió id_token")
    claims = verify_id_token(tokens["id_token"], config, nonce)
    who = str(claims.get("email") or claims.get("preferred_username") or claims["sub"])[:60]
    try:
        user = upsert_user(claims)
    except SSOFail as fail:
        fail.who = who
        raise
    return user


def handle(handler, method, url, query):
    """/api/auth/oidc/(start|callback): (status, body, headers), o None si no es una de esas rutas."""
    if url not in ("/api/auth/oidc/start", "/api/auth/oidc/callback"):
        return None
    if method != "GET":
        return 405, {"error": "método no permitido"}, {}
    if not enabled():
        return 404, {"error": "El inicio de sesión con SSO no está configurado (PARLA_OIDC_ISSUER y PARLA_OIDC_CLIENT_ID)."}, {}
    try:
        if url.endswith("/start"):
            return start(handler)
        user = callback(handler, query)
    except SSOFail as fail:
        print("SSO: %s" % fail, flush=True)
        _audit(handler, getattr(fail, "who", None), None, "falló: %s" % fail)
        return 302, b"", {"Location": _home() + "?sso_error=" + fail.code}
    except OSError as error:                   # PARLA_OIDC_CLIENT_SECRET_FILE ilegible, la base…
        print("SSO: %s" % error, flush=True)
        _audit(handler, None, None, "falló: %s" % type(error).__name__)
        return 302, b"", {"Location": _home() + "?sso_error=failed"}
    _audit(handler, user["name"], user["role"], "ok")
    return 302, b"", {"Location": _home(), "Set-Cookie": auth._login(handler, user["name"])["Set-Cookie"]}


def logout_url(user_record):
    """RP-initiated logout si el proveedor lo tiene (y PARLA_OIDC_LOGOUT no es 0). Sin id_token_hint: no se guardan tokens."""
    if not (enabled() and (user_record or {}).get("sso")) or env("LOGOUT") in ("0", "false", "no", "off"):
        return None
    try:
        end = discovery().get("end_session_endpoint")
    except SSOFail:
        return None
    if not isinstance(end, str):
        return None
    query = {"client_id": env("CLIENT_ID")}
    if os.environ.get("PARLA_PUBLIC_URL"):
        query["post_logout_redirect_uri"] = _home()
    return end + ("&" if "?" in end else "?") + urllib.parse.urlencode(query)
