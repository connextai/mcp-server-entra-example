"""The MCP tools this server exposes.

These are intentionally IDENTICAL to the sibling ``mcp-server-example`` — two
examples:

  1. ``roll_dice``     - a plain, ordinary tool that returns text.
  2. ``greeting_card`` - an "MCP App": a tool that also returns a small HTML UI
                         which the Connext platform renders inline in the chat.

The only difference is *where the caller's identity comes from*: here it is read
from the validated Microsoft Entra ID access token's claims (``name`` /
``preferred_username`` / ...), because this server delegates identity to Entra
rather than running its own login (see auth.py).
"""

from __future__ import annotations

import secrets

from mcp.types import EmbeddedResource, TextContent, TextResourceContents

from fastmcp import FastMCP
from fastmcp.server.dependencies import get_access_token
from fastmcp.tools.tool import ToolResult

# An MCP App is just a tool whose result includes a `ui://` resource carrying
# HTML with this special media type. The platform renders it in a sandboxed
# iframe. (This matches Connext's MCP Apps / SEP-1865 support.)
CARD_URI = "ui://acme/greeting-card"
CARD_MIME = "text/html;profile=mcp-app"


def _current_user() -> str:
    """Return a human-friendly identity from the Entra access token.

    Microsoft Entra access tokens carry the user in their claims. We prefer the
    display ``name``, then ``preferred_username`` (usually the UPN / email), and
    fall back to the token subject (an opaque id) or "guest" for a token without
    a user (e.g. an app-only / client-credentials token).
    """
    token = get_access_token()
    if token is None:
        return "guest"
    claims = getattr(token, "claims", None) or {}
    return (
        claims.get("name")
        or claims.get("preferred_username")
        or claims.get("upn")
        or claims.get("email")
        or token.subject
        or "guest"
    )


def _render_card(username: str, message: str) -> str:
    """Build the self-contained HTML for the greeting card.

    Notes for the iframe sandbox:
      * Everything is inline (no external scripts/styles) so it renders under a
        strict Content-Security-Policy.
      * The ``var(--mcp-color-*, ...)`` fallbacks let the card pick up the
        host's light/dark theme automatically, with sane defaults standalone.
    """
    # Escape the few values we interpolate into HTML.
    safe_user = username.replace("<", "&lt;").replace("&", "&amp;")
    safe_msg = message.replace("<", "&lt;").replace("&", "&amp;")
    return f"""<!doctype html>
<html>
  <head>
    <meta charset="utf-8" />
    <style>
      body {{ font-family: system-ui, sans-serif; margin: 0; }}
      .card {{
        margin: 1rem; padding: 1.25rem 1.5rem; border-radius: 12px;
        border: 1px solid var(--mcp-color-border, #e3e3e8);
        background: var(--mcp-color-surface, #ffffff);
        color: var(--mcp-color-text, #1a1a1a);
      }}
      .label {{ font-size: .7rem; letter-spacing: .05em; text-transform: uppercase; opacity: .55; }}
      .hello {{ font-size: 1.4rem; font-weight: 600; margin: .3rem 0 .1rem; }}
      .msg {{ font-size: 1rem; opacity: .85; }}
    </style>
  </head>
  <body>
    <div class="card">
      <div class="label">Acme greeting</div>
      <div class="hello">Hello, {safe_user}! 👋</div>
      <div class="msg">{safe_msg}</div>
    </div>
  </body>
</html>"""


def register_tools(mcp: FastMCP) -> None:
    """Register all tools and UI resources on the FastMCP app."""

    # --- 1. A plain tool -------------------------------------------------
    @mcp.tool(
        name="roll_dice",
        description="Roll an n-sided dice and return the result.",
    )
    async def roll_dice(sides: int = 6) -> str:
        sides = max(2, sides)
        result = secrets.randbelow(sides) + 1
        return f"{_current_user()} rolled a {result} (1–{sides})."

    # --- 2. A "who am I" tool --------------------------------------------
    # The clearest way to confirm auth works end to end: it echoes back the
    # identity the server read from your *verified* Entra access token. If this
    # returns your name, the whole chain (Entra login -> token -> validation ->
    # tool) is working.
    @mcp.tool(
        name="whoami",
        description="Return the identity of the calling user, read from the verified access token.",
    )
    async def whoami() -> ToolResult:
        token = get_access_token()
        claims = (getattr(token, "claims", None) or {}) if token else {}
        info = {
            "name": claims.get("name"),
            "username": claims.get("preferred_username") or claims.get("upn") or claims.get("email"),
            "object_id": claims.get("oid"),      # the user's stable id in the tenant
            "tenant_id": claims.get("tid"),
            "scopes": claims.get("scp"),
        }
        detail = f" ({info['username']})" if info["username"] else ""
        return ToolResult(
            content=[TextContent(type="text", text=f"You are {_current_user()}{detail}.")],
            structured_content=info,
        )

    # --- 3. An MCP App: a tool that returns an HTML UI -------------------
    # The `meta.ui` block on the tool DEFINITION tells the host this tool has a
    # UI and where its template lives. `visibility` is advisory — the Connext
    # admin still has to allow UI for this server.
    @mcp.tool(
        name="greeting_card",
        description="Greet the signed-in user with a small interactive card.",
        meta={"ui": {"resourceUri": CARD_URI, "visibility": ["model", "app"]}},
    )
    async def greeting_card(message: str = "Welcome to the Acme Entra MCP server.") -> ToolResult:
        user = _current_user()
        html = _render_card(user, message)
        # The result carries BOTH a normal text part (what the model reads) AND
        # an embedded `ui://` resource with the HTML (what the user sees).
        ui_resource = EmbeddedResource(
            type="resource",
            resource=TextResourceContents(uri=CARD_URI, mimeType=CARD_MIME, text=html),
        )
        return ToolResult(
            content=[
                TextContent(type="text", text=f"Showed a greeting card to {user}."),
                ui_resource,
            ],
            # Free-form data a richer UI could read over the host bridge.
            structured_content={"username": user, "message": message},
        )

    # The UI template, also served via resources/read. `meta.ui.csp` lets the
    # host widen the iframe's Content-Security-Policy if your UI needs to reach
    # external domains (none here).
    @mcp.resource(
        CARD_URI,
        name="greeting-card",
        mime_type=CARD_MIME,
        meta={"ui": {"csp": {"connectDomains": [], "resourceDomains": []}, "prefersBorder": True}},
    )
    async def greeting_card_template() -> str:
        return _render_card("there", "This card is filled in when the tool runs.")
