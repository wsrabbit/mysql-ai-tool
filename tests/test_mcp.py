import asyncio
import os
import sys

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


def test_real_stdio_handshake_and_tools(tmp_path):
    async def scenario():
        env = dict(os.environ, MYSQL_AI_HOME=str(tmp_path))
        parameters = StdioServerParameters(
            command=sys.executable, args=["-m", "mysql_ai", "serve"], env=env
        )
        async with stdio_client(parameters) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                tools = await session.list_tools()
                assert len(tools.tools) == 7
                result = await session.call_tool("list_connections", {})
                assert not result.isError
                assert result.structuredContent["connections"] == []
                missing = await session.call_tool(
                    "query", {"connection": "missing", "database": "shop", "sql": "SELECT 1"}
                )
                assert missing.structuredContent["error"]["code"] == "CONNECTION_UNKNOWN"

    asyncio.run(asyncio.wait_for(scenario(), 20))
