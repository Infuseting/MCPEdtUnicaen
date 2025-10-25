from fastmcp import FastMCP, Context
import math
import json
import os
import urllib.request
import urllib.parse
import datetime
import re
import asyncio
from uuid import UUID
from typing import Optional
from starlette.requests import Request
from starlette.responses import Response as StarletteResponse
from utils import *
from mcp.server.sse import SseServerTransport
from mcp.shared.message import ServerMessageMetadata, SessionMessage
import mcp.types as mcp_types
from tools import *

_MCP_HOST = os.getenv("MCP_HOST", "127.0.0.1")
_MCP_PORT = int(os.getenv("MCP_PORT", "8000"))
_MCP_MOUNT = os.getenv("MCP_MOUNT", "/mcp")
_MCP_SSE_PATH = os.getenv("MCP_SSE_PATH", "/sse")
_MCP_MESSAGE_PATH = os.getenv("MCP_MESSAGE_PATH", "/messages/")

# Optional fallback: name to use when no EDT name is provided to tools.
# Expected format: "FIRSTNAME LASTNAME" (set via environment variable MY_EDT)
_MY_EDT = os.getenv("MY_EDT", "").strip() or None




mcp = FastMCP("EDT Unicaen MCP Server")

# Create SSE transport helper (used internally by FastMCP when serving SSE)
sse_transport = SseServerTransport(_MCP_MESSAGE_PATH)


# small health endpoint to validate the HTTP/SSE server is reachable
@mcp.custom_route(path="/health", methods=["GET"])
async def _health(request):
    from starlette.responses import JSONResponse

    return JSONResponse({"ok": True, "server": mcp.name, "mount": _MCP_MOUNT, "sse_path": _MCP_SSE_PATH})


# Root route: return 200 to satisfy probes from connectors (some clients/bridges
# probe `/` and treat a 404 as an error). See FastMCP/OpenAI connector notes.
@mcp.custom_route(path="/", methods=["GET"])
async def _root(request):
    # Return plain text/HTML to avoid confusing probes that expect non-JSON content
    from starlette.responses import PlainTextResponse

    txt = f"{mcp.name} — SSE endpoint available at { _MCP_SSE_PATH } (MCP mount: { _MCP_MOUNT })"
    return PlainTextResponse(txt)

# execute and return the stdio output
if __name__ == "__main__":
    print("Starting MCP server (SSE transport)...")
    # Run the FastMCP server using the SSE transport so clients can connect via HTTP/SSE
    # The `FastMCP` instance was configured with `sse_path` and `message_path` above.
    mcp.run(transport="sse", host=_MCP_HOST, port=_MCP_PORT)
    print("MCP server stopped.")

