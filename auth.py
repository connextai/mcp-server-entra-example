"""Microsoft Entra ID (Azure AD) token verification.

This is the *only* file that differs meaningfully from the sibling
``mcp-server-example``. Where that server is its **own** OAuth provider (its own
login page and user store), this server is a pure OAuth 2.0 **Resource Server**:
it does not log anyone in and issues no tokens of its own. It simply *trusts*
access tokens minted by Microsoft Entra ID and validates every one:

  * signature — against Entra's published JWKS for your tenant,
  * issuer    — ``https://login.microsoftonline.com/<tenant>/v2.0``,
  * audience  — your app's client id / ``api://<client-id>``,
  * scopes    — the ``scp`` claim must contain your required scope(s).

Whoever calls this server must therefore *already hold* a valid Entra access
token for this API (see the README for how a client obtains one). FastMCP's
``AzureJWTVerifier`` derives the JWKS URI, issuer and audience from your app
registration details; ``RemoteAuthProvider`` wraps it so the server advertises
Entra as its authorization server in the OAuth *protected resource metadata*.

Configuration comes from the environment (see .env.example):

    AZURE_CLIENT_ID        Application (client) ID of the App Registration that
                           exposes this API. Required.
    AZURE_TENANT_ID        Directory (tenant) ID — a GUID, or "organizations" /
                           "consumers" / "common" for multi-tenant. Required.
    AZURE_REQUIRED_SCOPES  Comma-separated scope names exactly as defined under
                           "Expose an API" (default: "access_as_user").
    AZURE_IDENTIFIER_URI   Application ID URI, if not the default api://<client-id>.
    PUBLIC_URL             Public base URL of this server; used to build the
                           protected-resource metadata it advertises.
"""

from __future__ import annotations

import os

from pydantic import AnyHttpUrl

from fastmcp.server.auth import RemoteAuthProvider
from fastmcp.server.auth.providers.azure import AzureJWTVerifier


def _split_scopes(raw: str) -> list[str]:
    return [s.strip() for s in raw.split(",") if s.strip()]


def build_auth() -> RemoteAuthProvider:
    """Construct the Entra token-verification auth provider from the environment.

    None of these values is a secret — a token *verifier* only needs your public
    app identity (client id + tenant) to fetch Entra's JWKS and check tokens. So,
    unlike ``mcp-server-example``, there is no client secret and nothing to store
    in a secret manager for auth.
    """
    client_id = os.environ["AZURE_CLIENT_ID"]
    tenant_id = os.environ["AZURE_TENANT_ID"]
    scopes = _split_scopes(os.environ.get("AZURE_REQUIRED_SCOPES", "access_as_user"))
    identifier_uri = os.environ.get("AZURE_IDENTIFIER_URI") or None
    public_url = os.environ.get("PUBLIC_URL", "http://localhost:8000").rstrip("/")

    # Validates Entra-issued JWTs. Auto-derives jwks_uri, issuer and audience
    # (= [client_id, api://client_id]) from the app registration details.
    verifier = AzureJWTVerifier(
        client_id=client_id,
        tenant_id=tenant_id,
        required_scopes=scopes,
        identifier_uri=identifier_uri,
    )

    # Tell MCP clients (via /.well-known/oauth-protected-resource) that tokens for
    # this server are issued by Entra — i.e. go get one from Microsoft, then call
    # back here with it. The v2.0 endpoint is the OIDC issuer for your tenant.
    return RemoteAuthProvider(
        token_verifier=verifier,
        authorization_servers=[
            AnyHttpUrl(f"https://login.microsoftonline.com/{tenant_id}/v2.0")
        ],
        base_url=public_url,
    )
