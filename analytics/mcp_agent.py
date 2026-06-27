import asyncio
import json
import sys
import time
from pathlib import Path
from typing import Any

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from openai import OpenAI

from analytics.ai_metric_query import log_execution_trace, now_iso


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SERVER_PATH = PROJECT_ROOT / "mcp_server" / "server.py"

client = OpenAI()


TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "list_metrics",
            "description": "List available MetricFlow metrics.",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_dimensions",
            "description": "List dimensions available for a selected metric.",
            "parameters": {
                "type": "object",
                "properties": {
                    "metric_name": {
                        "type": "string",
                        "description": "Metric name, for example total_spend or order_count.",
                    },
                },
                "required": ["metric_name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "semantic_search",
            "description": (
                "Search metrics, dimensions, and relationships using natural language. "
                "Use this when the user uses business terms like spend, money, area, city, "
                "shop, merchant, refund, grocery, alcohol, category, or platform."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "object_type": {
                        "type": "string",
                        "description": "Optional filter: metric, dimension, or relationship.",
                    },
                    "metric_name": {
                        "type": "string",
                        "description": "Optional metric filter, for example total_spend.",
                    },
                    "top_k": {"type": "integer"},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "similar_dimensions",
            "description": (
                "Find likely dimensions for vague words like shop, area, city, vendor, "
                "merchant, category, or market."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "user_term": {"type": "string"},
                    "metric_name": {"type": "string"},
                },
                "required": ["user_term"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_dimension_values",
            "description": (
                "Get real warehouse values for a dimension. "
                "Useful for resolving exact city, merchant, category, or platform values."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "dimension_name": {
                        "type": "string",
                        "description": "Dimension name, for example order__merchant_name.",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Maximum number of values to return.",
                    },
                },
                "required": ["dimension_name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "run_metricflow_query",
            "description": "Run a MetricFlow query using metrics, group_by dimensions, and filters.",
            "parameters": {
                "type": "object",
                "properties": {
                    "metrics": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                    "group_by": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                    "filters": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "dimension": {"type": "string"},
                                "operator": {"type": "string"},
                                "value": {},
                            },
                            "required": ["dimension", "operator", "value"],
                        },
                    },
                },
                "required": ["metrics"],
            },
        },
    },
]


def unwrap_mcp_result(value: Any) -> Any:
    """
    MCP/FastMCP sometimes wraps tool returns as:
    {"result": actual_output}

    This unwraps that so Streamlit receives the same shape as the direct agent.
    """
    if isinstance(value, dict) and set(value.keys()) == {"result"}:
        return value["result"]

    return value


def extract_tool_result(result: Any) -> Any:
    """
    Convert MCP tool result into plain Python data.

    MCP can return structuredContent or text content depending on the server/tool.
    This helper normalizes it for the OpenAI agent loop.
    """
    if hasattr(result, "structuredContent") and result.structuredContent:
        return unwrap_mcp_result(result.structuredContent)

    if hasattr(result, "content"):
        values = []

        for item in result.content:
            if hasattr(item, "text"):
                try:
                    parsed = json.loads(item.text)
                    values.append(unwrap_mcp_result(parsed))
                except json.JSONDecodeError:
                    values.append(item.text)
            else:
                values.append(str(item))

        if len(values) == 1:
            return unwrap_mcp_result(values[0])

        return values

    return unwrap_mcp_result(result)


async def call_mcp_tool(
    session: ClientSession,
    tool_name: str,
    tool_args: dict,
) -> Any:
    result = await session.call_tool(
        tool_name,
        arguments=tool_args,
    )

    return extract_tool_result(result)


async def run_mcp_analytics_agent_async(
    question: str,
    conversation_history: list[dict] | None = None,
) -> dict:
    history_text = json.dumps(conversation_history or [], indent=2, default=str)

    run_started_at = now_iso()
    trace_steps = []
    tool_results = []

    server_params = StdioServerParameters(
        command=sys.executable,
        args=[str(SERVER_PATH)],
        cwd=str(PROJECT_ROOT),
    )

    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            messages = [
                {
                    "role": "system",
                    "content": f"""
You are an autonomous commerce analytics agent.

You answer user questions using MCP tools exposed by the commerce analytics MCP server.

Important rules:
- You must use tools to get actual numeric results.
- Do not invent metrics, dimensions, or values.
- Use list_metrics when you need to understand available metrics.
- Use list_dimensions to understand valid dimensions for a metric.
- Use semantic_search when the user uses business terms like spend, money, shop, merchant, grocery, alcohol, city, refund, or category.
- Use similar_dimensions for vague dimension words like shop, store, vendor, area, market, city, or category.
- Use get_dimension_values when you need exact real values such as merchant names or cities.
- Use run_metricflow_query to get final numeric results.
- If a query fails, inspect the error and retry with corrected metric/dimension names.
- Final answer should be short, clear, and business-friendly.
- Mention the result and briefly explain how it was grouped or filtered.
- Do not expose unnecessary internal JSON unless the user asks.

Recent conversation history:
{history_text}

Use this only to resolve follow-up questions like:
- What about Munich?
- Now show that by city.
- Only Berlin.
""",
                },
                {"role": "user", "content": question},
            ]

            for _ in range(10):
                response = client.chat.completions.create(
                    model="gpt-4.1-mini",
                    messages=messages,
                    tools=TOOLS,
                    tool_choice="auto",
                    temperature=0,
                )

                message = response.choices[0].message
                messages.append(message)

                if not message.tool_calls:
                    final_answer = message.content or ""

                    execution_trace = {
                        "started_at": run_started_at,
                        "finished_at": now_iso(),
                        "question": question,
                        "conversation_history_used": conversation_history or [],
                        "final_answer": final_answer,
                        "steps": trace_steps,
                        "status": "success",
                        "error": None,
                        "agent_mode": "mcp",
                    }

                    log_execution_trace(execution_trace)

                    return {
                        "question": question,
                        "answer": final_answer,
                        "tool_results": tool_results,
                        "execution_trace": execution_trace,
                    }

                for tool_call in message.tool_calls:
                    tool_name = tool_call.function.name
                    tool_args = json.loads(tool_call.function.arguments or "{}")

                    step_start = time.perf_counter()

                    try:
                        output = await call_mcp_tool(
                            session=session,
                            tool_name=tool_name,
                            tool_args=tool_args,
                        )
                    except Exception as exc:
                        output = {"error": str(exc)}

                    duration_ms = (time.perf_counter() - step_start) * 1000

                    trace_step = {
                        "step_number": len(trace_steps) + 1,
                        "tool_name": tool_name,
                        "arguments": tool_args,
                        "output": output,
                        "duration_ms": round(duration_ms, 2),
                        "called_via": "mcp",
                    }

                    trace_steps.append(trace_step)

                    tool_results.append(
                        {
                            "tool": tool_name,
                            "arguments": tool_args,
                            "output": output,
                            "called_via": "mcp",
                        }
                    )

                    messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": tool_call.id,
                            "name": tool_name,
                            "content": json.dumps(output, default=str),
                        }
                    )

    fallback_answer = "The MCP agent could not complete the query."

    execution_trace = {
        "started_at": run_started_at,
        "finished_at": now_iso(),
        "question": question,
        "conversation_history_used": conversation_history or [],
        "final_answer": fallback_answer,
        "steps": trace_steps,
        "status": "failed",
        "error": "MCP session ended unexpectedly",
        "agent_mode": "mcp",
    }

    log_execution_trace(execution_trace)

    return {
        "question": question,
        "answer": fallback_answer,
        "tool_results": tool_results,
        "execution_trace": execution_trace,
    }


def run_mcp_analytics_agent(
    question: str,
    conversation_history: list[dict] | None = None,
) -> dict:
    """
    Synchronous wrapper so Streamlit / scripts can call the async MCP agent easily.
    """
    return asyncio.run(
        run_mcp_analytics_agent_async(
            question=question,
            conversation_history=conversation_history,
        )
    )