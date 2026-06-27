import asyncio
import json
import sys
from pathlib import Path
from typing import Any

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


PROJECT_ROOT = Path(__file__).resolve().parents[2]
SERVER_PATH = PROJECT_ROOT / "mcp_server" / "server.py"


def print_result(title: str, result: Any) -> None:
    print("\n" + "=" * 80)
    print(title)
    print("=" * 80)
    print(json.dumps(result, indent=2, default=str))


def extract_tool_result(result: Any) -> Any:
    if hasattr(result, "structuredContent") and result.structuredContent:
        return result.structuredContent

    if hasattr(result, "content"):
        return [
            item.text if hasattr(item, "text") else str(item)
            for item in result.content
        ]

    return result


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
            print_result(
                "Available MCP tools",
                [tool.name for tool in tools.tools],
            )

            metrics_result = await session.call_tool(
                "list_metrics",
                arguments={},
            )
            print_result(
                "list_metrics result",
                extract_tool_result(metrics_result),
            )

            dimensions_result = await session.call_tool(
                "list_dimensions",
                arguments={"metric_name": "total_spend"},
            )
            print_result(
                "list_dimensions result",
                extract_tool_result(dimensions_result),
            )

            semantic_result = await session.call_tool(
                "semantic_search",
                arguments={
                    "query": "money by shop",
                    "object_type": "metric",
                    "top_k": 5,
                },
            )
            print_result(
                "semantic_search result",
                extract_tool_result(semantic_result),
            )

            metricflow_result = await session.call_tool(
                "run_metricflow_query",
                arguments={
                    "metrics": ["total_spend"],
                    "group_by": ["order__merchant_name"],
                    "filters": [],
                },
            )
            print_result(
                "run_metricflow_query result",
                extract_tool_result(metricflow_result),
            )


if __name__ == "__main__":
    asyncio.run(main())