"""Entry point: build the FastMCP server, wire up Entra auth + tools, and run it.

    python server.py

This is the Microsoft Entra ID (Azure AD) *token-verifier* variant of
``mcp-server-example``. The tools are identical — only the auth differs: this
server trusts access tokens issued by Entra rather than issuing its own. See
auth.py for the details and .env.example for configuration.

Configuration (from the environment):

    AZURE_CLIENT_ID / AZURE_TENANT_ID / AZURE_REQUIRED_SCOPES   see auth.py
    PUBLIC_URL   the public URL the platform uses to reach this server; the
                 OAuth protected-resource metadata is built from it.
    HOST / PORT  the address uvicorn binds to (default 127.0.0.1:8000).
"""

from __future__ import annotations

import os

from starlette.requests import Request
from starlette.responses import PlainTextResponse

from fastmcp import FastMCP

from auth import build_auth
from tools import register_tools

HOST = os.environ.get("HOST", "127.0.0.1")
PORT = int(os.environ.get("PORT", "8000"))

# The Entra token-verifier auth provider (see auth.py). Passing `auth=...` makes
# FastMCP require a valid Entra bearer token on the /mcp endpoint and serve the
# OAuth protected-resource metadata that points MCP clients at Microsoft Entra.
auth = build_auth()

mcp = FastMCP("Acme Entra MCP Example", auth=auth)

# Register the same example tools as mcp-server-example.
register_tools(mcp)


# An unauthenticated liveness/readiness probe. The GKE Ingress BackendConfig and
# the Kubernetes probes hit GET /health; it must NOT require a bearer token, so
# it is a plain custom route outside the MCP auth surface.
@mcp.custom_route("/health", methods=["GET"])
async def health(_request: Request) -> PlainTextResponse:
    return PlainTextResponse("ok")


if __name__ == "__main__":
    # Streamable-HTTP transport; the MCP endpoint is served at <PUBLIC_URL>/mcp/
    mcp.run(transport="http", host=HOST, port=PORT)
