import asyncio
import sys
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SERVER_PATH = PROJECT_ROOT / "mcp_server" / "server.py"

EXPECTED_TOOLS = {
    "list_metrics",
    "list_dimensions",
    "semantic_search",
    "similar_dimensions",
    "get_dimension_values",
    "run_metricflow_query",
}


async def main() -> None:
    server_params = StdioServerParameters(
        command=sys.executable,
        args=[str(SERVER_PATH)],
        cwd=str(PROJECT_ROOT),
    )

    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            tools = await session.list_tools()
            actual_tools = {tool.name for tool in tools.tools}

            missing_tools = EXPECTED_TOOLS - actual_tools

            if missing_tools:
                raise AssertionError(
                    f"Missing expected MCP tools: {sorted(missing_tools)}"
                )

            print("MCP smoke test passed.")
            print(f"Available tools: {sorted(actual_tools)}")


if __name__ == "__main__":
    asyncio.run(main())