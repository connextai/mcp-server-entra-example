# mcp-server-entra-example

A **minimal, well-commented MCP server** that authenticates its callers with
**Microsoft Entra ID (Azure AD)**.

This is the **token-verifier variant** of
[`mcp-server-example`](../mcp-server-example). The two are deliberately almost
identical — the tools, the MCP App, the health check and the deployment are the
same — so you can diff them and see that **the only thing that really changes is
`auth.py`**:

| | `mcp-server-example` | **`mcp-server-entra-example`** (this repo) |
| --- | --- | --- |
| Who logs the user in? | This server (its own login page + user store) | **Microsoft Entra ID** |
| Who issues the token? | This server | **Microsoft Entra ID** |
| What this server does with auth | Is a full OAuth **authorization server** | Is a pure OAuth **resource server** — it only **verifies** Entra tokens |
| Secrets needed | Hashed user passwords | **None** (a verifier needs only your *public* client id + tenant id) |

It is built on [FastMCP](https://gofastmcp.com), whose `AzureJWTVerifier` +
`RemoteAuthProvider` do all the token plumbing, so the only code specific to
*your* application is your tools and the ~30 lines of `auth.py`.

---

## How it works

This server never logs anyone in. It trusts access tokens minted by Entra and
validates each one (signature via Entra's JWKS, issuer, audience, and required
scope). The **caller** is responsible for obtaining a token from Entra first:

```
  Caller (MCP client)                     Microsoft Entra ID        This MCP server
  ───────────────────                     ──────────────────        ───────────────
  1. discover ───────────────────────────────────────────────────▶ GET /.well-known/oauth-protected-resource/mcp
                                                                    └▶ "tokens come from Entra: <tenant>/v2.0"
  2. get a token ────────────────────────▶ /authorize, /token
                                            └▶ returns an access token
  3. call tools (Authorization: Bearer) ─────────────────────────▶ POST /mcp
                                                                    └▶ verifies the token, runs your tools
```

You write only step 3's tools. FastMCP verifies the token; Entra does 1–2.

---

## Getting your Azure values (step by step)

A token verifier needs an App Registration that **exposes an API**. You end up
with three values — `AZURE_CLIENT_ID`, `AZURE_TENANT_ID`, `AZURE_REQUIRED_SCOPES`
— and **no client secret** (a secret is only needed to *obtain* tokens, which
this server never does).

Do everything in the **Microsoft Entra admin center** ([entra.microsoft.com](https://entra.microsoft.com))
or the Azure Portal ([portal.azure.com](https://portal.azure.com) → *Microsoft Entra ID*).

### 1. Create the app registration
- **Identity → Applications → App registrations → New registration.**
  > ⚠️ It must be **App registrations**, not **Enterprise applications** — only
  > App registrations have the "Expose an API" page you need in step 3.
- Give it a name (e.g. `mcp-server-entra-example`) → **Register**.

### 2. Copy the two IDs → `AZURE_CLIENT_ID` and `AZURE_TENANT_ID`
On the app's **Overview** page:
- **Application (client) ID** → this is `AZURE_CLIENT_ID`
- **Directory (tenant) ID** → this is `AZURE_TENANT_ID`

Both are plain GUIDs and are **not secret**. (The tenant ID is the same across
your whole Entra directory — if you already use Microsoft 365 / Entra SSO, it's
the GUID in your SAML issuer `https://sts.windows.net/<tenant-id>/`.)

### 3. Expose an API → add a scope → `AZURE_REQUIRED_SCOPES`
In the app's left menu, **Manage → Expose an API**:
- If **Application ID URI** isn't set yet, click **Add** / **Set** and accept the
  default `api://<client-id>` → **Save**.
- **+ Add a scope**:
  - **Scope name:** `access_as_user`  ← this is your `AZURE_REQUIRED_SCOPES`
  - **Who can consent:** *Admins and users*
  - Fill the admin consent display name/description (anything) → **State: Enabled**
  - **Add scope**

The full scope is now `api://<client-id>/access_as_user`. (Any leftover default
scope like `user_impersonation` is harmless — the server only checks for the
name in `AZURE_REQUIRED_SCOPES`.)

### 4. Force v2 tokens
**Manage → Manifest** → set `"requestedAccessTokenVersion": 2` → **Save**. This
makes Entra issue **v2** access tokens, whose issuer is
`https://login.microsoftonline.com/<tenant-id>/v2.0` — which is what this server
validates against.

### 5. (Only if you'll test with the Azure CLI) authorize the CLI
To let `az` mint a token for your custom API, either consent when prompted, or
pre-authorize it: **Expose an API → Authorized client applications → Add a
client application** → Azure CLI id `04b07795-8ddb-461a-bbee-02f9e1bf7b46` →
tick your `access_as_user` scope.

### Recap — how the values map
| App registration field | Env var |
| --- | --- |
| Application (client) ID | `AZURE_CLIENT_ID` |
| Directory (tenant) ID | `AZURE_TENANT_ID` |
| Expose an API → scope name | `AZURE_REQUIRED_SCOPES` (e.g. `access_as_user`) |
| *(nothing — no secret needed)* | — |

> These three values are all the **server** needs. To connect it **through
> Connext**, you'll add a **client secret** and a **redirect URI** to this same
> app registration — those are used by Connext (the OAuth client), not by this
> server. See [Connecting it to Connext](#connecting-it-to-connext).

---

## Quick start

Requires Python 3.11+.

```bash
# 1. install
python -m venv .venv && source .venv/bin/activate
pip install -e .

# 2. configure and run (values from your app registration)
export AZURE_CLIENT_ID=<application-client-id>
export AZURE_TENANT_ID=<directory-tenant-id>
export AZURE_REQUIRED_SCOPES=access_as_user
python server.py
# -> serving on http://localhost:8000  (MCP endpoint: http://localhost:8000/mcp/)

# 3. in another terminal, get a token and call the server as a client would
az login
export MCP_ACCESS_TOKEN=$(az account get-access-token \
  --scope api://$AZURE_CLIENT_ID/access_as_user --query accessToken -o tsv)
python examples/connect_with_client.py
```

Tools run **as the Entra user**: `whoami`, `roll_dice` and `greeting_card` read
the caller's identity from the token's claims (see `_current_user()` in
`tools.py`). The quickest way to confirm the whole flow works is to call
**`whoami`** — it just returns your name back to you.

---

## Connecting it to Connext

Connext connects to this server over OAuth and lets users **sign in with
Microsoft**. Because the server delegates identity to **Entra** — which does
**not** support RFC 7591 dynamic client registration — you register Connext as a
client of Entra by hand: you supply a **client id + client secret** when adding
the server. (Contrast the self-hosted [`mcp-server-example`](../mcp-server-example),
where you leave those blank and Connext self-registers via DCR.)

> **Platform requirement.** Connext has to speak Entra's enterprise OAuth dialect:
> fall back to **OpenID Connect discovery** (Entra publishes no RFC 8414 doc),
> request the **resource's** scope (`api://<client-id>/access_as_user`, per RFC
> 9728 — not the AS's generic OIDC scopes), and **omit** the RFC 8707 `resource`
> indicator for Entra. Recent connext-core does all three. On an older build the
> connect fails with *"Could not connect to the MCP server URL"* (discovery) or
> `AADSTS9010010: The resource parameter … doesn't match with the requested
> scopes`.

### Extra Entra app-registration steps (for the Connext OAuth flow)

These are what **Connext-as-OAuth-client** needs — all on the **same** app
registration you set up above:

1. **Client secret** — **Manage → Certificates & secrets → New client secret** →
   copy the **Value**. Connext uses it to exchange the auth code; it's stored
   encrypted **in Connext**, not in this server. (The server itself still needs
   no secret — it only verifies tokens.)
2. **Redirect URI (reply URL)** — **Manage → Authentication → Add a platform →
   Web → Redirect URIs** → add Connext's MCP OAuth callback, e.g.
   `https://<your-connext-host>/api/v1/oauth/mcp/callback` → **Save**.
   - Must be a **Web** platform (Connext is a confidential client), an **exact**
     match, no trailing slash. If sign-in returns `AADSTS500113: No reply address
     is registered for the application`, this step is missing or the URL differs.
     The exact value is the `redirect_uri` in the failing `/authorize` URL.
3. *(Optional)* **API permissions → Grant admin consent** for `access_as_user`,
   so users don't see a one-time consent screen on first connect.

### Register in Connext

**Admin → MCP Servers → Add:**
- **URL:** your public MCP endpoint (e.g. `https://mcp.example.com/mcp`)
- **Auth:** OAuth · **Client id:** your `AZURE_CLIENT_ID` · **Client secret:** step 1's value

Then each user clicks **Connect** **once** and signs in with Microsoft — a silent
SSO redirect if they're already signed into Connext via Entra (no password). The
server requests `offline_access`, so Connext keeps a refresh token and the
connection **persists** (no reconnecting).

### Alternative: `AzureProvider` (server-side OAuth proxy)

If your MCP platform *doesn't* bridge enterprise IdPs, FastMCP's `AzureProvider`
moves the bridge into the **server**: it presents a DCR-capable OAuth server to
the client and proxies the login to Entra (the client then connects with blank
creds), at the cost of a client secret + redirect URI on the *server* side. This
repo shows the simpler token-verifier; reach for `AzureProvider` when the server
must be self-contained.

---

## The files

| File | What it does |
| ---- | ------------ |
| `server.py` | Entry point. Builds the FastMCP server with Entra auth, registers tools, adds `/health`, runs it. |
| `auth.py` | **The only real difference from `mcp-server-example`.** Builds an `AzureJWTVerifier` + `RemoteAuthProvider` from env config. No login page, no user store, no secret. |
| `tools.py` | The example tools (`whoami`, `roll_dice`, `greeting_card`) + the `ui://` MCP App resource. Identity is read from Entra token claims. |
| `examples/connect_with_client.py` | A client that calls the server with a bearer token you obtained from Entra. |
| `.env.example` | Configuration (`AZURE_*`, `PUBLIC_URL`, `HOST`, `PORT`). |

---

## Taking it to production

- **Tenant scoping:** use your specific tenant GUID (single-tenant) for the
  tightest validation, or `organizations` / `common` for multi-tenant (issuer
  validation is then skipped and the audience is what protects you — make sure
  your `AZURE_CLIENT_ID`/audience is correct).
- **Scopes/roles:** enforce least privilege with `AZURE_REQUIRED_SCOPES`, and add
  app-role or group checks in your tools if needed (both are in the token claims).
- **HTTPS:** terminate TLS in front and set `PUBLIC_URL` to the `https://` URL so
  the advertised metadata is correct.
- **Clock/JWKS:** FastMCP caches Entra's JWKS and honours token expiry — there is
  no *auth* state to persist (no secret, no stored tokens).
- **Scaling / replicas:** note that while auth is stateless, the MCP
  streamable-HTTP transport keeps **per-session** state in memory (`initialize`
  → `Mcp-Session-Id` → follow-up calls). To run more than one replica you need
  session stickiness or a shared session store, otherwise a client's follow-up
  request can land on another pod and get *"Session not found"*. This example
  runs a single replica for simplicity.
