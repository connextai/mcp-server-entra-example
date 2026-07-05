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

## Set up the Azure App Registration

A token verifier needs an App Registration that **exposes an API**:

1. **Azure Portal → App registrations → New registration.** Note the
   **Application (client) ID** and **Directory (tenant) ID**.
2. **Expose an API → Set** the Application ID URI (defaults to `api://<client-id>`).
3. **Expose an API → Add a scope**, e.g. `access_as_user`. This is the value you
   put in `AZURE_REQUIRED_SCOPES`.
4. In the app **Manifest**, set `"requestedAccessTokenVersion": 2` (v2 tokens).

That's it — **no client secret** is required to *verify* tokens. (A secret is
only needed if a server has to *obtain* tokens itself; this one doesn't.)

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
  --scope api://$AZURE_CLIENT_ID/.default --query accessToken -o tsv)
python examples/connect_with_client.py
```

Tools run **as the Entra user**: `roll_dice` and `greeting_card` read the
caller's name from the token's claims (see `_current_user()` in `tools.py`).

---

## Connecting it to Connext — read this first

Because this server only *verifies* tokens (it is not an authorization server),
connecting it to Connext is **not** the same one-click OAuth flow as
`mcp-server-example`. Connext registers MCP clients dynamically (RFC 7591 DCR),
but **Entra does not support DCR**, so Connext cannot self-register with Entra
automatically. In practice you use this pattern when the caller can already
present an Entra token — for example a **pre-registered confidential client**,
a gateway that attaches the token, or service-to-service calls.

> If what you want is the full "user clicks Connect → signs in with Microsoft"
> experience *through Connext*, use FastMCP's `AzureProvider` instead (the OAuth
> **proxy** pattern): it presents a DCR-capable OAuth server to Connext while
> proxying the actual login to Entra. This repo intentionally shows the simpler,
> secret-free **verification** half of the story.

The server still advertises Entra correctly in its protected-resource metadata
(`/.well-known/oauth-protected-resource/mcp`), so any client that speaks
RFC 9728 will discover where to get a token.

---

## The files

| File | What it does |
| ---- | ------------ |
| `server.py` | Entry point. Builds the FastMCP server with Entra auth, registers tools, adds `/health`, runs it. |
| `auth.py` | **The only real difference from `mcp-server-example`.** Builds an `AzureJWTVerifier` + `RemoteAuthProvider` from env config. No login page, no user store, no secret. |
| `tools.py` | The two example tools + the `ui://` MCP App resource. Identical to `mcp-server-example` except identity is read from Entra token claims. |
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
- **Clock/JWKS:** FastMCP caches Entra's JWKS and honours token expiry; no state
  of your own to persist, so this scales horizontally with no shared store.
