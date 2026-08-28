"""COELHO Search MCP — FastMCP server. Registers all domain tools and exposes the Streamable-HTTP ASGI app."""
import logging
import os

logging.basicConfig(level = logging.INFO)


from fastmcp import FastMCP
from starlette.requests import Request
from starlette.responses import JSONResponse

from domains.search import server as search

mcp = FastMCP("coelho-search-mcp-fastmcp")

search.register(mcp)


@mcp.tool
def ping() -> dict[str, str]:
    """Liveness probe — confirms the MCP server is up and tools are callable."""
    return {"status": "ok", "server": "coelho-search-mcp-fastmcp"}


@mcp.custom_route("/health", methods = ["GET"])
async def health(request: Request) -> JSONResponse:
    return JSONResponse({"status": "ok", "server": "coelho-search-mcp-fastmcp"})


http_app = mcp.http_app


if __name__ == "__main__":
    mcp.run(
        transport = "streamable-http",
        host = os.getenv("MCP_HOST", "0.0.0.0"),
        port = int(os.getenv("MCP_PORT", "8000")),
    )
