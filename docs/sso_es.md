# Inicio de sesión único (OIDC)

[English](sso.md) · **Español**

Parla puede hacer entrar a la gente con tu proveedor de identidad por OpenID Connect: Keycloak, Microsoft Entra ID,
Google Workspace, Okta, Authentik, Auth0 o cualquier otro proveedor OIDC que firme los ID tokens con RSA. Los roles
pueden salir de los grupos o roles del proveedor. Es opcional: sin estas variables, el login anda como siempre
(usuarios locales y contraseñas). Cómo se protege y sus límites: [security_es.md](security_es.md#inicio-de-sesión-único-oidc).

## Qué necesitás

1. Parla en una dirección con HTTPS, p. ej. `https://bots.example.com`, con la interfaz completa publicada (`/` y
   `/api/`), no solo `/api/v1/` (ver [deployment_es.md](deployment_es.md#detrás-de-un-proxy-con-https)).
2. Un **dueño local** creado antes (desde la misma máquina, ver
   [deployment_es.md](deployment_es.md#primer-ingreso-y-usuarios)). Es tu forma de entrar si el proveedor falla o
   te baja el rol.
3. En tu proveedor, un cliente **confidencial** (con secreto) con el flujo **authorization code** y PKCE `S256`
   permitido:
   - **Redirect URI:** `https://<tu host>/api/auth/oidc/callback`
   - **Redirect después de salir:** `https://<tu host>/`
   - Scopes: `openid email profile`.

Parla se autentica en el token endpoint con `client_secret_basic` si el proveedor lo anuncia, y si no con
`client_secret_post`.

## Variables

| Variable | Por defecto | Para qué |
|---|---|---|
| `PARLA_OIDC_ISSUER` | | La URL del issuer del proveedor, tal cual aparece en su `/.well-known/openid-configuration`. Prende el SSO (junto con el client id). |
| `PARLA_OIDC_CLIENT_ID` | | El client id. |
| `PARLA_OIDC_CLIENT_SECRET` | | El secreto del cliente. |
| `PARLA_OIDC_CLIENT_SECRET_FILE` | | Un archivo con el secreto (secrets de Docker / Kubernetes). Gana sobre `PARLA_OIDC_CLIENT_SECRET`. |
| `PARLA_OIDC_SCOPES` | `openid email profile` | Los scopes que se piden. |
| `PARLA_OIDC_ROLE_CLAIM` | | La claim con los grupos o roles. Primero se busca como clave exacta (`https://parla.example/roles` de Auth0) y después como ruta con puntos (`realm_access.roles` de Keycloak). Texto o lista. |
| `PARLA_OIDC_ROLE_MAP` | | `grupo:rol,grupo:rol`. Roles: `owner`, `editor`, `analyst`, `agent`. Si coinciden varios, gana el más alto. Se corta en el último `:`, así que los grupos pueden tener dos puntos. Solo se usa junto con `PARLA_OIDC_ROLE_CLAIM`. |
| `PARLA_OIDC_DEFAULT_ROLE` | | El rol para quien no tiene un grupo mapeado. Sin definir: no entra. |
| `PARLA_OIDC_ONLY` | | `1`: login con contraseña apagado, salvo para un dueño desde la misma máquina (emergencia, ver [security_es.md](security_es.md#inicio-de-sesión-único-oidc)). |
| `PARLA_OIDC_LABEL` | `SSO` | El texto del botón: **Entrar con {label}**. |
| `PARLA_OIDC_LOGOUT` | prendido | `0`: al salir, no mandar el navegador a la página de salida del proveedor. |
| `PARLA_PUBLIC_URL` | | Tu dirección pública (`https://bots.example.com`). Se usa para la redirect URI y para volver después de salir. |
| `PARLA_HOSTS` | | Tu host público (`bots.example.com`). Hace falta para la interfaz y la vuelta del proveedor detrás de un proxy. |

Una configuración mínima:

```sh
PARLA_PUBLIC_URL=https://bots.example.com
PARLA_HOSTS=bots.example.com
PARLA_SECURE_COOKIE=1
PARLA_OIDC_ISSUER=https://kc.example.com/realms/acme
PARLA_OIDC_CLIENT_ID=parla
PARLA_OIDC_CLIENT_SECRET_FILE=/run/secrets/parla-oidc
PARLA_OIDC_ROLE_CLAIM=groups
PARLA_OIDC_ROLE_MAP=parla-owners:owner,parla-editors:editor,parla-analysts:analyst,support:agent
PARLA_OIDC_LABEL=Acme
```

### Cómo se decide el rol

- **Con mapa de roles** (`PARLA_OIDC_ROLE_CLAIM` + `PARLA_OIDC_ROLE_MAP`): en cada login el rol es el más alto que
  le dan sus grupos, o `PARLA_OIDC_DEFAULT_ROLE`. Si ninguno le da uno, no entra. El rol no se puede cambiar en
  Parla: lo maneja el proveedor.
- **Sin mapa de roles:** un usuario nuevo recibe `PARLA_OIDC_DEFAULT_ROLE` (sin definir: no entra). De ahí en más
  se queda con el rol que tiene en Parla, y el dueño lo puede cambiar en **Usuarios**.
- En los dos casos, qué bots ve cada usuario se elige en Parla y se mantiene entre logins. Los dueños ven todos.

## Keycloak

1. **Clients → Create client**: tipo OpenID Connect, Client ID `parla`.
2. **Client authentication: On**. Authentication flow: solo **Standard flow**.
3. **Valid redirect URIs:** `https://bots.example.com/api/auth/oidc/callback`. **Valid post logout redirect URIs:**
   `https://bots.example.com/`.
4. Pestaña **Credentials**: copiá el client secret.
5. Roles desde grupos: **Client scopes → parla-dedicated → Add mapper → By configuration → Group Membership**, token
   claim name `groups`, **Full group path: Off** (si lo dejás prendido, mapeá `/parla-owners` en vez de
   `parla-owners`), add to ID token: On.

```sh
PARLA_OIDC_ISSUER=https://kc.example.com/realms/<realm>
PARLA_OIDC_ROLE_CLAIM=groups
PARLA_OIDC_ROLE_MAP=parla-owners:owner,parla-editors:editor
```

O con roles del realm, sin mapper: `PARLA_OIDC_ROLE_CLAIM=realm_access.roles`.

## Microsoft Entra ID

1. **App registrations → New registration**. Plataforma **Web**, redirect URI
   `https://bots.example.com/api/auth/oidc/callback`. Sumá también `https://bots.example.com/` en
   **Authentication → Redirect URIs** para volver a Parla después de salir.
2. **Certificates & secrets → New client secret**: copiá el valor (no el id).
3. **Token configuration → Add optional claim → ID → `email`**.
4. Roles, una de dos:
   - **Grupos:** **Token configuration → Add groups claim** (security groups). La claim es `groups` y trae los
     **Object IDs** de los grupos, así que mapeá los GUID: `PARLA_OIDC_ROLE_MAP=3f2c…-…:owner,9a71…-…:editor`.
   - **App roles** (recomendado): **App roles → Create app role** (p. ej. valor `parla.owner`) y asignalos en
     **Enterprise applications → la app → Users and groups**. Llegan en la claim `roles`.
5. El issuer es el **del tenant**, con `v2.0`. El issuer multi-tenant `common` no anda.

```sh
PARLA_OIDC_ISSUER=https://login.microsoftonline.com/<tenant-id>/v2.0
PARLA_OIDC_ROLE_CLAIM=roles
PARLA_OIDC_ROLE_MAP=parla.owner:owner,parla.editor:editor,parla.analyst:analyst
```

Con más de 200 grupos Entra ID saca la claim `groups` (overage) y nadie coincidiría: usá app roles.

## Google Workspace

1. Consola de Google Cloud → **APIs & Services → OAuth consent screen**: **User type: Internal**. Es obligatorio:
   con External puede entrar cualquier cuenta de Google.
2. **Credentials → Create credentials → OAuth client ID**, tipo **Web application**, authorized redirect URI
   `https://bots.example.com/api/auth/oidc/callback`.
3. Google no manda grupos. Dales a todos un rol de entrada y subí a quien haga falta a mano en **Usuarios**, sin
   mapa de roles:

```sh
PARLA_OIDC_ISSUER=https://accounts.google.com
PARLA_OIDC_DEFAULT_ROLE=analyst
PARLA_OIDC_LABEL=Google
```

## Okta

1. **Applications → Create App Integration → OIDC - OpenID Connect → Web Application**.
2. Grant type **Authorization Code**. Sign-in redirect URI `https://bots.example.com/api/auth/oidc/callback`,
   sign-out redirect URI `https://bots.example.com/`. Asigná las personas o grupos.
3. Grupos: **Security → API → Authorization Servers → default → Claims → Add Claim**: nombre `groups`, incluida en
   el **ID Token**, value type **Groups**, filtro p. ej. **Starts with** `parla-`.
4. La salida de Okta exige `id_token_hint`, que Parla no guarda: apagá la salida del proveedor.

```sh
PARLA_OIDC_ISSUER=https://<org>.okta.com/oauth2/default
PARLA_OIDC_ROLE_CLAIM=groups
PARLA_OIDC_ROLE_MAP=parla-owners:owner,parla-editors:editor
PARLA_OIDC_LOGOUT=0
```

## Authentik

1. **Applications → Providers → Create → OAuth2/OpenID Provider**. Client type **Confidential**, redirect URI
   `https://bots.example.com/api/auth/oidc/callback`, signing key: un certificado (RSA).
2. **Applications → Create**, slug p. ej. `parla`, con ese provider.
3. Los grupos llegan en la claim `groups` con el scope `profile` (ya está en los scopes por defecto).

```sh
PARLA_OIDC_ISSUER=https://authentik.example.com/application/o/<slug>/
PARLA_OIDC_ROLE_CLAIM=groups
PARLA_OIDC_ROLE_MAP=parla-owners:owner,parla-editors:editor
```

## Auth0

1. **Applications → Create Application → Regular Web Application**.
2. **Allowed Callback URLs:** `https://bots.example.com/api/auth/oidc/callback`. **Allowed Logout URLs:**
   `https://bots.example.com/`.
3. Roles: crealos en **User Management → Roles** y después una **Action** post-login que los agregue como claim
   con namespace:

```js
exports.onExecutePostLogin = async (event, api) => {
  api.idToken.setCustomClaim('https://parla.example/roles', event.authorization?.roles || []);
};
```

```sh
PARLA_OIDC_ISSUER=https://<tenant>.auth0.com/
PARLA_OIDC_ROLE_CLAIM=https://parla.example/roles
PARLA_OIDC_ROLE_MAP=parla-owner:owner,parla-editor:editor
```

## Probarlo

1. Reiniciá Parla con las variables. La pantalla de entrada muestra **Entrar con {label}**.
2. Entrá. La primera vez el usuario se crea en **Usuarios** con el rol que da el mapa (o el de por defecto).
3. Mirá **Auditoría**: una entrada `login.sso` con `ok`.
4. Salí: Parla cierra la sesión y, salvo con `PARLA_OIDC_LOGOUT=0`, te manda a la salida del proveedor.
5. Cuando ande, pensá en `PARLA_OIDC_ONLY=1`.

## Si algo falla

La pantalla de entrada muestra un mensaje según `?sso_error=`, y el motivo queda en **Auditoría** (`login.sso`,
`falló: …`) y en la consola de Parla:

| `sso_error` | Qué quiere decir |
|---|---|
| `state` | El login no volvió al mismo navegador, tardó más de 10 minutos o se repitió. Empezá de nuevo. |
| `denied` | El proveedor la dejó entrar pero no le toca ningún rol: revisá los grupos, `PARLA_OIDC_ROLE_CLAIM` y `PARLA_OIDC_ROLE_MAP`, o definí `PARLA_OIDC_DEFAULT_ROLE`. |
| `idp` | El proveedor devolvió un error (la persona canceló, no está asignada a la app…). |
| `config` | La configuración de Parla: el issuer no coincide con el discovery, una URL sin HTTPS, o falta `PARLA_PUBLIC_URL` y el `Host` no es local ni de `PARLA_HOSTS`. |
| `failed` | Cualquier otra cosa: error del token endpoint (secreto equivocado), firma, `aud`, token vencido. |

Casos comunes:

- **403 «ese Host no está permitido»** en la vuelta o en la interfaz: sumá tu host a `PARLA_HOSTS`.
- **`redirect_uri` no coincide** en el proveedor: la URI registrada ahí tiene que ser exactamente
  `PARLA_PUBLIC_URL` + `/api/auth/oidc/callback` (esquema, host, puerto, sin barra al final).
- **Issuer que no coincide** («el issuer del discovery … no es PARLA_OIDC_ISSUER»): copiá `issuer` de
  `<issuer>/.well-known/openid-configuration` tal cual (Authentik y Auth0 lo terminan con `/`).
- **«el ID token es del futuro»** o **«venció»**: el reloj del servidor está corrido más de 60 s. Sincronizalo
  (NTP).

## Usuarios de SSO en la página Usuarios

- Tienen una etiqueta **SSO** y no tienen contraseña (no se les puede poner).
- Con mapa de roles, su rol dice «lo maneja tu proveedor de identidad» y no se puede cambiar en Parla.
- Qué bots ven se edita como para cualquier usuario y se mantiene entre logins.
- Borrar uno cierra sus sesiones, pero puede volver a entrar mientras el proveedor lo deje. Para sacarle el acceso
  del todo, sacalo en el proveedor (o de los grupos mapeados).
- Se les pueden crear claves de API como a cualquier usuario.
