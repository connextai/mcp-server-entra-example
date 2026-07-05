"""Call the running server with a Microsoft Entra access token.

Unlike ``mcp-server-example`` (whose client runs a full browser OAuth login),
this server only *verifies* tokens — so the client must already hold a valid
Entra access token for this API and present it as a bearer token.

1. Run the server first (`python server.py`) with AZURE_CLIENT_ID / AZURE_TENANT_ID set.

2. Get an access token for your API from Entra. Easiest with the Azure CLI
   (the scope is your Application ID URI + "/.default"):

       az login
       export MCP_ACCESS_TOKEN=$(az account get-access-token \
         --scope api://$AZURE_CLIENT_ID/.default \
         --query accessToken -o tsv)

   (Any method that yields a token with the right audience + scope works:
   MSAL device-code flow, a confidential client, etc.)

3. Run this client:

       python examples/connect_with_client.py
"""

import asyncio
import os

from fastmcp import Client
from fastmcp.client.auth import BearerAuth

SERVER_URL = os.environ.get("PUBLIC_URL", "http://localhost:8000").rstrip("/") + "/mcp/"
TOKEN = os.environ.get("MCP_ACCESS_TOKEN")


async def main() -> None:
    if not TOKEN:
        raise SystemExit("Set MCP_ACCESS_TOKEN to an Entra access token (see the module docstring).")

    async with Client(SERVER_URL, auth=BearerAuth(TOKEN)) as client:
        tools = await client.list_tools()
        print("Tools:", [t.name for t in tools])

        dice = await client.call_tool("roll_dice", {"sides": 20})
        print("roll_dice ->", dice.data)

        card = await client.call_tool("greeting_card", {"message": "Hello from Entra!"})
        print("greeting_card structured ->", card.structured_content)


if __name__ == "__main__":
    asyncio.run(main())
