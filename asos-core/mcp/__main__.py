"""
Run THEORA as an MCP stdio server.

Usage (Claude Desktop config):
  { "mcpServers": { "theora": { "command": "python", "args": ["-m", "mcp.server"], "cwd": "/path/to/asos-core" } } }

Or via HTTP:
  POST http://localhost:9090/mcp
"""
import asyncio
import sys

from mcp.server import TheoraMCPServer


def main():
    server = TheoraMCPServer()
    try:
        asyncio.run(server.run_stdio())
    except KeyboardInterrupt:
        pass
    except BrokenPipeError:
        pass


if __name__ == "__main__":
    main()
