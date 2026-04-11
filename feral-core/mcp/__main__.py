"""
Run FERAL as an MCP stdio server.

Usage (Claude Desktop config):
  { "mcpServers": { "feral": { "command": "python", "args": ["-m", "mcp.server"], "cwd": "/path/to/feral-core" } } }

Or via HTTP:
  POST http://localhost:9090/mcp
"""
import asyncio
import sys

from mcp.server import FeralMCPServer


def main():
    server = FeralMCPServer()
    try:
        asyncio.run(server.run_stdio())
    except KeyboardInterrupt:
        pass
    except BrokenPipeError:
        pass


if __name__ == "__main__":
    main()
