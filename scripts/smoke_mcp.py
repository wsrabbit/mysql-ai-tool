"""Exercise actual MCP framing against a source or frozen server."""

import argparse
import asyncio
import json
import os
import sys

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


async def check(command, args):
    parameters = StdioServerParameters(command=command, args=args, env=dict(os.environ))
    async with stdio_client(parameters) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = await session.list_tools()
            result = await session.call_tool("list_connections", {})
            assert len(tools.tools) == 7 and not result.isError
            print(json.dumps({"ok": True, "tools": [tool.name for tool in tools.tools]}, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--executable")
    arguments = parser.parse_args()
    command = arguments.executable or sys.executable
    args = ["serve"] if arguments.executable else ["-m", "mysql_ai", "serve"]
    asyncio.run(asyncio.wait_for(check(command, args), timeout=30))
