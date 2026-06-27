import json
import time

from openai import OpenAI

from analytics.ai_metric_query import (
    find_similar_dimensions,
    get_available_metrics,
    log_execution_trace,
    now_iso,
    search_semantic_layer,
    tool_get_dimension_values,
    tool_list_dimensions,
    tool_list_metrics,
    tool_run_metricflow_query,
)


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
            "name": "get_dimension_values",
            "description": (
                "Get real warehouse values for a dimension. "
                "Useful for resolving casing and spelling."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "dimension_name": {
                        "type": "string",
                        "description": "Dimension name, for example order__residence_city.",
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
    {
        "type": "function",
        "function": {
            "name": "find_similar_dimensions",
            "description": (
                "Find likely MetricFlow dimensions for vague user terms like area, city, "
                "merchant, category, shop, vendor, or platform."
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
            "name": "search_semantic_layer",
            "description": (
                "Search the semantic layer using natural language. Use this to find relevant "
                "metrics, dimensions, or metric-dimension relationships when the user uses "
                "business terms like spend, money, area, city, shop, merchant, refund, order, "
                "grocery, alcohol, or category."
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
]


TOOL_MAPPING = {
    "list_metrics": tool_list_metrics,
    "list_dimensions": tool_list_dimensions,
    "get_dimension_values": tool_get_dimension_values,
    "run_metricflow_query": tool_run_metricflow_query,
    "find_similar_dimensions": find_similar_dimensions,
    "search_semantic_layer": search_semantic_layer,
}


def run_analytics_agent(
    question: str,
    conversation_history: list[dict] | None = None,
) -> dict:
    history_text = json.dumps(conversation_history or [], indent=2, default=str)

    run_started_at = now_iso()
    trace_steps = []
    tool_results = []

    known_metrics = get_available_metrics()

    messages = [
        {
            "role": "system",
            "content": f"""
You are an autonomous commerce analytics agent.

You answer user questions using the available tools.

Available high-level context:
- Metrics are managed by MetricFlow.
- Dimensions are metric-dependent.
- You must use tools to get actual numeric results.
- Do not invent metrics, dimensions, or values.
- For comparisons, call run_metricflow_query multiple times if needed.
- For breakdowns or trends, use group_by.
- For exact filter values such as city or merchant names, use get_dimension_values when needed.
- Final answer should be short, clear, and business-friendly.
- If a tool returns success=false or an error, inspect the valid metrics/dimensions and retry with a corrected query.
- If the user uses business terms that may not exactly match MetricFlow names, call search_semantic_layer before choosing metrics or dimensions.
- Use search_semantic_layer for vague terms like spend, money, area, city, shop, merchant, refund, order, grocery, alcohol, category, market, or platform.
- If the user uses vague terms like area, region, category, shop, store, vendor, or merchant, call find_similar_dimensions before asking for clarification.

Recent conversation history:
{history_text}

Use this only to resolve follow-up questions like:
- What about Munich?
- Now show that by city.
- Only Berlin.

Known metrics:
{known_metrics}
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

            tool_function = TOOL_MAPPING.get(tool_name)

            step_start = time.perf_counter()

            if not tool_function:
                output = {"error": f"Unknown tool: {tool_name}"}
            else:
                try:
                    output = tool_function(**tool_args)
                except Exception as exc:
                    output = {"error": str(exc)}

            duration_ms = (time.perf_counter() - step_start) * 1000

            trace_step = {
                "step_number": len(trace_steps) + 1,
                "tool_name": tool_name,
                "arguments": tool_args,
                "output": output,
                "duration_ms": round(duration_ms, 2),
            }

            trace_steps.append(trace_step)

            tool_results.append(
                {
                    "tool": tool_name,
                    "arguments": tool_args,
                    "output": output,
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

    fallback_answer = "The agent could not complete the query within the tool-call limit."

    execution_trace = {
        "started_at": run_started_at,
        "finished_at": now_iso(),
        "question": question,
        "conversation_history_used": conversation_history or [],
        "final_answer": fallback_answer,
        "steps": trace_steps,
        "status": "failed",
        "error": "Tool-call limit reached",
    }

    log_execution_trace(execution_trace)

    return {
        "question": question,
        "answer": fallback_answer,
        "tool_results": tool_results,
        "execution_trace": execution_trace,
    }