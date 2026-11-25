# Single sign-on (OIDC)

**English** · [Español](sso_es.md)

Parla can sign people in with your identity provider over OpenID Connect: Keycloak, Microsoft Entra ID, Google
Workspace, Okta, Authentik, Auth0 or any other OIDC provider that signs ID tokens with RSA. Roles can come from
the provider's groups or roles. It's optional: without these variables, login works as always (local users and
passwords). How it's protected and its limits: [security.md](security.md#single-sign-on-oidc).

## What you need

1. Parla reachable at an HTTPS address, e.g. `https://bots.example.com`, with the whole interface published (`/` and
   `/api/`), not only `/api/v1/` (see [deployment.md](deployment.md#behind-an-https-proxy)).
2. A **local owner** created beforehand (from the machine itself, see
   [deployment.md](deployment.md#first-login-and-users)). It's your way in if the provider fails or demotes you.
3. In your provider, a **confidential** client (it has a secret) using the **authorization code** flow, with PKCE
   `S256` allowed:
   - **Redirect URI:** `https://<your host>/api/auth/oidc/callback`
   - **Post-logout redirect URI:** `https://<your host>/`
   - Scopes: `openid email profile`.

Parla authenticates to the token endpoint with `client_secret_basic` if the provider advertises it, otherwise with
`client_secret_post`.

## Variables

| Variable | Default | What for |
|---|---|---|
| `PARLA_OIDC_ISSUER` | | The provider's issuer URL, exactly as it appears in its `/.well-known/openid-configuration`. Turns SSO on (with the client id). |
| `PARLA_OIDC_CLIENT_ID` | | The client id. |
| `PARLA_OIDC_CLIENT_SECRET` | | The client secret. |
| `PARLA_OIDC_CLIENT_SECRET_FILE` | | A file with the secret (Docker / Kubernetes secrets). Wins over `PARLA_OIDC_CLIENT_SECRET`. |
| `PARLA_OIDC_SCOPES` | `openid email profile` | Scopes to request. |
| `PARLA_OIDC_ROLE_CLAIM` | | The claim with the groups or roles. First looked up as an exact key (Auth0's `https://parla.example/roles`), then as a dotted path (Keycloak's `realm_access.roles`). String or list. |
| `PARLA_OIDC_ROLE_MAP` | | `group:role,group:role`. Roles: `owner`, `editor`, `analyst`, `agent`. If several match, the highest wins. Split on the last `:`, so groups can contain colons. Only used together with `PARLA_OIDC_ROLE_CLAIM`. |
| `PARLA_OIDC_DEFAULT_ROLE` | | Role for anyone without a mapped group. Unset: they're denied. |
| `PARLA_OIDC_ONLY` | | `1`: password login off, except for an owner on the machine itself (break-glass, see [security.md](security.md#single-sign-on-oidc)). |
| `PARLA_OIDC_LABEL` | `SSO` | Button text: **Sign in with {label}**. |
| `PARLA_OIDC_LOGOUT` | on | `0`: on logout, don't send the browser to the provider's logout page. |
| `PARLA_PUBLIC_URL` | | Your public address (`https://bots.example.com`). Used for the redirect URI and the post-logout redirect. |
| `PARLA_HOSTS` | | Your public host (`bots.example.com`). Needed for the interface and the callback behind a proxy. |

A minimal setup:

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

### How roles are decided

- **With a role map** (`PARLA_OIDC_ROLE_CLAIM` + `PARLA_OIDC_ROLE_MAP`): on every login the role is the highest one
  given by the person's groups, or `PARLA_OIDC_DEFAULT_ROLE`. If neither gives one, they're denied. The role can't
  be changed in Parla: the provider manages it.
- **Without a role map:** a new user gets `PARLA_OIDC_DEFAULT_ROLE` (unset: denied). From then on they keep the
  role set in Parla, and the owner can change it in **Users**.
- Either way, which bots each user sees is set in Parla and kept across logins. Owners always see all.

## Keycloak

1. **Clients → Create client**: type OpenID Connect, Client ID `parla`.
2. **Client authentication: On**. Authentication flow: **Standard flow** only.
3. **Valid redirect URIs:** `https://bots.example.com/api/auth/oidc/callback`. **Valid post logout redirect URIs:**
   `https://bots.example.com/`.
4. **Credentials** tab: copy the client secret.
5. Roles from groups: **Client scopes → parla-dedicated → Add mapper → By configuration → Group Membership**, token
   claim name `groups`, **Full group path: Off** (with it on, map `/parla-owners` instead of `parla-owners`), add to
   ID token: On.

```sh
PARLA_OIDC_ISSUER=https://kc.example.com/realms/<realm>
PARLA_OIDC_ROLE_CLAIM=groups
PARLA_OIDC_ROLE_MAP=parla-owners:owner,parla-editors:editor
```

Or with realm roles, without a mapper: `PARLA_OIDC_ROLE_CLAIM=realm_access.roles`.

## Microsoft Entra ID

1. **App registrations → New registration**. Platform **Web**, redirect URI
   `https://bots.example.com/api/auth/oidc/callback`. Also add `https://bots.example.com/` under
   **Authentication → Redirect URIs** to come back to Parla after logout.
2. **Certificates & secrets → New client secret**: copy the value (not the id).
3. **Token configuration → Add optional claim → ID → `email`**.
4. Roles, one of two:
   - **Groups:** **Token configuration → Add groups claim** (security groups). The claim is `groups` and has the
     groups' **Object IDs**, so map the GUIDs: `PARLA_OIDC_ROLE_MAP=3f2c…-…:owner,9a71…-…:editor`.
   - **App roles** (recommended): **App roles → Create app role** (e.g. value `parla.owner`), assign them under
     **Enterprise applications → the app → Users and groups**. They come in the `roles` claim.
5. The issuer is the **tenant's**, with `v2.0`. The multi-tenant `common` issuer doesn't work.

```sh
PARLA_OIDC_ISSUER=https://login.microsoftonline.com/<tenant-id>/v2.0
PARLA_OIDC_ROLE_CLAIM=roles
PARLA_OIDC_ROLE_MAP=parla.owner:owner,parla.editor:editor,parla.analyst:analyst
```

With more than 200 groups Entra ID leaves the `groups` claim out (overage) and nobody would match: use app roles.

## Google Workspace

1. Google Cloud console → **APIs & Services → OAuth consent screen**: **User type: Internal**. This is mandatory:
   with External, any Google account can sign in.
2. **Credentials → Create credentials → OAuth client ID**, type **Web application**, authorized redirect URI
   `https://bots.example.com/api/auth/oidc/callback`.
3. Google doesn't send groups. Give everyone a starting role and promote people by hand in **Users**, with no role
   map:

```sh
PARLA_OIDC_ISSUER=https://accounts.google.com
PARLA_OIDC_DEFAULT_ROLE=analyst
PARLA_OIDC_LABEL=Google
```

## Okta

1. **Applications → Create App Integration → OIDC - OpenID Connect → Web Application**.
2. Grant type **Authorization Code**. Sign-in redirect URI `https://bots.example.com/api/auth/oidc/callback`,
   sign-out redirect URI `https://bots.example.com/`. Assign the people or groups.
3. Groups: **Security → API → Authorization Servers → default → Claims → Add Claim**: name `groups`, include in
   **ID Token**, value type **Groups**, filter e.g. **Starts with** `parla-`.
4. Okta's logout requires `id_token_hint`, which Parla doesn't keep: turn provider logout off.

```sh
PARLA_OIDC_ISSUER=https://<org>.okta.com/oauth2/default
PARLA_OIDC_ROLE_CLAIM=groups
PARLA_OIDC_ROLE_MAP=parla-owners:owner,parla-editors:editor
PARLA_OIDC_LOGOUT=0
```

## Authentik

1. **Applications → Providers → Create → OAuth2/OpenID Provider**. Client type **Confidential**, redirect URI
   `https://bots.example.com/api/auth/oidc/callback`, signing key: a certificate (RSA).
2. **Applications → Create**, slug e.g. `parla`, with that provider.
3. Groups come in the `groups` claim with the `profile` scope (already in the default scopes).

```sh
PARLA_OIDC_ISSUER=https://authentik.example.com/application/o/<slug>/
PARLA_OIDC_ROLE_CLAIM=groups
PARLA_OIDC_ROLE_MAP=parla-owners:owner,parla-editors:editor
```

## Auth0

1. **Applications → Create Application → Regular Web Application**.
2. **Allowed Callback URLs:** `https://bots.example.com/api/auth/oidc/callback`. **Allowed Logout URLs:**
   `https://bots.example.com/`.
3. Roles: create them under **User Management → Roles**, then a post-login **Action** that adds them as a
   namespaced claim:

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

## Trying it

1. Restart Parla with the variables. The login screen shows **Sign in with {label}**.
2. Sign in. The first time, the user is created in **Users** with the role the map (or the default) gives.
3. Check **Audit log**: a `login.sso` entry with `ok`.
4. Sign out: Parla ends the session and, unless `PARLA_OIDC_LOGOUT=0`, sends you to the provider's logout.
5. When it works, consider `PARLA_OIDC_ONLY=1`.

## Troubleshooting

When something fails, the login screen shows a message from `?sso_error=`, and the reason is in **Audit log**
(`login.sso`, `falló: …`) and in Parla's console:

| `sso_error` | Means |
|---|---|
| `state` | The login didn't come back to the same browser, took more than 10 minutes, or was replayed. Start again. |
| `denied` | The provider let them in but no role applies: check the groups, `PARLA_OIDC_ROLE_CLAIM` and `PARLA_OIDC_ROLE_MAP`, or set `PARLA_OIDC_DEFAULT_ROLE`. |
| `idp` | The provider returned an error (the person cancelled, isn't assigned to the app…). |
| `config` | Parla's configuration: issuer doesn't match the discovery document, a non-HTTPS URL, or no `PARLA_PUBLIC_URL` and the `Host` isn't local or in `PARLA_HOSTS`. |
| `failed` | Anything else: token endpoint error (wrong secret), signature, `aud`, expired token. |

Common cases:

- **403 "ese Host no está permitido"** (Host not allowed) on the callback or the interface: add your host to
  `PARLA_HOSTS`.
- **`redirect_uri` mismatch** at the provider: the URI registered there must be exactly
  `PARLA_PUBLIC_URL` + `/api/auth/oidc/callback` (scheme, host, port, no trailing slash).
- **Issuer mismatch** ("el issuer del discovery … no es PARLA_OIDC_ISSUER"): copy `issuer` from
  `<issuer>/.well-known/openid-configuration` as is (Authentik and Auth0 end it with `/`).
- **"el ID token es del futuro"** or **"venció"**: the server's clock is off by more than 60 s. Sync it (NTP).

## SSO users in the Users page

- They show an **SSO** badge and have no password (they can't get one).
- With a role map, their role reads "managed by your identity provider" and can't be changed in Parla.
- Which bots they see is editable as for any user, and kept across logins.
- Deleting one ends their sessions, but they can sign in again while the provider allows it. To remove access for
  good, remove them in the provider (or from the mapped groups).
- API keys can be created for them as for any user.
