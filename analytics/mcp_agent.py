import asyncio
import json
import sys
import time
from pathlib import Path
from typing import Any, Literal

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from openai import OpenAI

from analytics.ai_metric_query import log_execution_trace, now_iso


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SERVER_PATH = PROJECT_ROOT / "mcp_server" / "server.py"

DEFAULT_MODEL = "gpt-4.1-mini"
MAX_AGENT_STEPS = 10

client: OpenAI | None = None


IntentType = Literal[
    "metric_query",
    "metadata_question",
    "clarification_needed",
    "unsupported",
]

TimeGrainType = Literal["day", "week", "month", "quarter", "year"]
VALID_TIME_GRAINS = {"day", "week", "month", "quarter", "year"}



TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "list_metrics",
            "description": (
                "List available MetricFlow metrics. This is a metadata discovery tool only; "
                "it does not answer numeric analytics questions by itself."
            ),
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
                "shop, merchant, refund, grocery, alcohol, category, item, product, or platform."
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
                "merchant, category, market, platform, item, or product."
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
            "name": "discover_dimension_candidates",
            "description": (
                "Discover candidate semantic dimensions for a user term by checking both "
                "semantic dimension names and real values present inside dimension columns. "
                "Use this for group_by dimensions, filters, categories, locations, merchants, "
                "items, products, statuses, payment methods, and any other dimension term. "
                "For filters, prefer candidates with match_type='dimension_value'."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "user_term": {
                        "type": "string",
                        "description": (
                            "The user phrase to resolve, such as city, item, alcohol, "
                            "Berlin, merchant, category, grocery, card, KFC, Wolt."
                        ),
                    },
                    "metric_name": {
                        "type": "string",
                        "description": (
                            "The selected metric name, such as item_total_spend, "
                            "total_spend, order_count, or average_order_value."
                        ),
                    },
                    "role": {
                        "type": "string",
                        "enum": ["any", "group_by", "filter", "partition_by", "order_by"],
                        "description": "How the dimension will be used in the query plan.",
                    },
                    "limit_per_dimension": {
                        "type": "integer",
                        "description": "Number of warehouse values to sample per dimension.",
                    },
                },
                "required": ["user_term", "metric_name", "role"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_dimension_values",
            "description": (
                "Get real warehouse values for a dimension. "
                "Useful for resolving exact city, merchant, category, item, or platform values."
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
            "description": (
                "Run a MetricFlow query to get final numeric analytics results. "
                "Use this for any answerable metric question. "
                "For simple totals, pass metrics only and leave group_by, filters, and time_granularity empty. "
                "For time-grain questions such as by day, week, month, quarter, or year, "
                "pass time_granularity instead of inventing date-derived group_by names."
            ),
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
                    "order_by": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "field": {
                                    "type": "string",
                                    "description": "Metric or returned group_by field to sort by, for example item_total_spend.",
                                },
                                "direction": {
                                    "type": "string",
                                    "enum": ["asc", "desc"],
                                },
                            },
                            "required": ["field", "direction"],
                        },
                        "description": (
                            "Optional result ordering. Use for top, highest, most, lowest, or ranking questions. "
                            "For top/highest/most spend, sort by the selected spend metric descending."
                        ),
                    },
                    "limit": {
                        "type": "integer",
                        "description": (
                            "Optional maximum number of result rows. Use 1 for 'which item/merchant had the highest' "
                            "and a reasonable small number such as 10 for 'top' lists when not specified."
                        ),
                    },
                    "time_granularity": {
                        "type": "string",
                        "enum": ["day", "week", "month", "quarter", "year"],
                        "description": (
                            "Optional calendar grain for metric_time aggregation. "
                            "Use this for phrases like by month, monthly, by week, yearly. "
                            "Do not encode time grain as group_by values like metric_time__month "
                            "or order__order_date__month."
                        ),
                    },
                },
                "required": ["metrics"],
            },
        },
    },
]


def get_openai_client() -> OpenAI:
    global client

    if client is None:
        client = OpenAI()

    return client


def safe_json_loads(raw_value: str, fallback: Any) -> Any:
    try:
        return json.loads(raw_value)
    except json.JSONDecodeError:
        return fallback


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


def tool_was_called(tool_results: list[dict], tool_name: str) -> bool:
    return any(step.get("tool") == tool_name for step in tool_results)


def build_planner_prompt(
    question: str,
    conversation_history: list[dict] | None,
) -> str:
    history_text = json.dumps(conversation_history or [], indent=2, default=str)

    return f"""
You are the planning layer for a production-style commerce analytics agent.

Your job is to classify the user's request and produce a strict JSON plan.

Do not answer the user.
Do not invent final metrics, dimensions, filters, or numbers.
Do not rely on keyword matching.
Reason from the meaning of the user's question and the recent conversation context.

Intent types:
- metric_query:
  The user is asking for a numeric analytics result, comparison, aggregation, ranking,
  breakdown, trend, total, count, average, ratio, or filtered business answer.
- metadata_question:
  The user is asking what metrics, dimensions, fields, tools, or data are available.
- clarification_needed:
  The user request is too ambiguous to execute safely.
- unsupported:
  The request is outside the analytics agent's capabilities.

Return only valid JSON with this schema:
{{
  "intent": "metric_query | metadata_question | clarification_needed | unsupported",
  "requires_metricflow_execution": true,
  "user_question_rewritten": "clear standalone version of the user question",
  "metric_terms": ["business metric phrases from the user"],
  "dimension_terms": ["grouping, breakdown, or comparison terms"],
  "filter_terms": ["filter values or conditions from the user"],
  "time_terms": ["date, month, week, period, or relative time terms"],
  "time_grain": "day | week | month | quarter | year | null",
  "ranking_terms": ["top, highest, most, lowest, least, rank, sort terms"],
  "order_direction": "asc | desc | null",
  "limit": 1,
  "needs_value_aware_dimension_discovery": true,
  "clarification_question": null,
  "reason": "brief explanation"
}}

Rules:
- If the user asks for a numeric answer, requires_metricflow_execution must be true.
- If the user asks only what is available, requires_metricflow_execution must be false.
- If the user asks a simple metric-only question, such as a total or count with no filters,
  needs_value_aware_dimension_discovery should be false.
- If the user mentions a city, merchant, item, category, platform, payment method, grocery,
  alcohol, product, status, or any value that may live inside a dimension column,
  needs_value_aware_dimension_discovery should be true.
- If the user asks for a calendar aggregation such as by day, by week, weekly, by month,
  monthly, quarterly, or yearly, set time_grain to the corresponding grain.
- A calendar grain is not the same thing as a semantic dimension. Do not put pure
  calendar-grain words such as month or week into dimension_terms unless the user
  is asking for a business dimension like week_of_month.
- If the user asks for top, highest, most, biggest, largest, ranked, or "spend the most",
  set order_direction to "desc" and include the wording in ranking_terms.
- If the user asks for lowest, least, smallest, or cheapest, set order_direction to "asc".
- If the user asks "which item/merchant/category ... most/highest", set limit to 1.
- If the user asks for "top" without an explicit number, set limit to 10.
- For generic money/spend/cost by shop, merchant, city, career stage, or order type,
  use metric_terms that point to overall spend, not item-only spend.
- Use item/product/item-level metric terms only when the user explicitly mentions
  item, product, grocery item, alcohol item, or top item analysis.
- For follow-up questions, use conversation history to rewrite the question as standalone.
- When the user asks for top items, products, grocery items, alcohol items, or item-level rankings, group by the most specific item-name dimension available.

    Prefer:
    - order_line__item_name

    Do not use:
    - order_line__component_subtype
    - order_line__component_type
    - order_line__food_delivery_component_group

    unless the user explicitly asks for category, type, subtype, component group, or product category.

Recent conversation history:
{history_text}

Current user question:
{question}
""".strip()


def create_query_plan(
    question: str,
    conversation_history: list[dict] | None = None,
) -> dict:
    """
    LLM planning layer.

    This replaces hardcoded keyword intent detection. The planner decides whether
    the request is a metric query, metadata question, unsupported request, or needs
    clarification.

    The execution layer still validates the plan deterministically.
    """
    openai_client = get_openai_client()

    response = openai_client.chat.completions.create(
        model=DEFAULT_MODEL,
        messages=[
            {
                "role": "system",
                "content": "Return only valid JSON. No markdown. No prose.",
            },
            {
                "role": "user",
                "content": build_planner_prompt(
                    question=question,
                    conversation_history=conversation_history,
                ),
            },
        ],
        temperature=0,
        response_format={"type": "json_object"},
    )

    raw_plan = response.choices[0].message.content or "{}"
    plan = safe_json_loads(raw_plan, fallback={})

    return normalize_query_plan(plan, question)


def normalize_query_plan(plan: dict, question: str) -> dict:
    """
    Defensive normalization so the rest of the agent can rely on stable keys.
    """
    valid_intents = {
        "metric_query",
        "metadata_question",
        "clarification_needed",
        "unsupported",
    }

    intent = plan.get("intent")
    if intent not in valid_intents:
        intent = "clarification_needed"

    requires_metricflow_execution = bool(
        plan.get("requires_metricflow_execution", False)
    )

    if intent != "metric_query":
        requires_metricflow_execution = False

    time_grain = plan.get("time_grain")
    if time_grain not in VALID_TIME_GRAINS:
        time_grain = None

    order_direction = plan.get("order_direction")
    if order_direction not in {"asc", "desc"}:
        order_direction = None

    raw_limit = plan.get("limit")
    try:
        limit = int(raw_limit) if raw_limit is not None else None
    except (TypeError, ValueError):
        limit = None
    if limit is not None and limit <= 0:
        limit = None

    normalized = {
        "intent": intent,
        "requires_metricflow_execution": requires_metricflow_execution,
        "user_question_rewritten": plan.get("user_question_rewritten") or question,
        "metric_terms": plan.get("metric_terms") or [],
        "dimension_terms": plan.get("dimension_terms") or [],
        "filter_terms": plan.get("filter_terms") or [],
        "time_terms": plan.get("time_terms") or [],
        "time_grain": time_grain,
        "ranking_terms": plan.get("ranking_terms") or [],
        "order_direction": order_direction,
        "limit": limit,
        "needs_value_aware_dimension_discovery": bool(
            plan.get("needs_value_aware_dimension_discovery", False)
        ),
        "clarification_question": plan.get("clarification_question"),
        "reason": plan.get("reason") or "",
    }

    return normalized


def plan_requires_metricflow_execution(plan: dict) -> bool:
    return (
        plan.get("intent") == "metric_query"
        and bool(plan.get("requires_metricflow_execution"))
    )


def append_force_execution_message(messages: list[Any], plan: dict) -> None:
    """
    Add a corrective instruction when the model tries to stop too early.

    The decision to force execution comes from the planner/control layer,
    not from a hardcoded keyword list.
    """
    metric_terms = plan.get("metric_terms", [])
    dimension_terms = plan.get("dimension_terms", [])
    filter_terms = plan.get("filter_terms", [])
    ranking_terms = plan.get("ranking_terms", [])
    order_direction = plan.get("order_direction")
    limit = plan.get("limit")
    needs_value_discovery = plan.get("needs_value_aware_dimension_discovery", False)
    time_grain = plan.get("time_grain")

    messages.append(
        {
            "role": "user",
            "content": (
                "You attempted to answer before calling run_metricflow_query. "
                "The planning layer classified this as an executable metric query, "
                "so you must call run_metricflow_query before giving the final answer.\n\n"
                f"Metric terms: {json.dumps(metric_terms, default=str)}\n"
                f"Dimension terms: {json.dumps(dimension_terms, default=str)}\n"
                f"Filter terms: {json.dumps(filter_terms, default=str)}\n"
                f"Time grain: {json.dumps(time_grain, default=str)}\n"
                f"Ranking terms: {json.dumps(ranking_terms, default=str)}\n"
                f"Order direction: {json.dumps(order_direction, default=str)}\n"
                f"Limit: {json.dumps(limit, default=str)}\n"
                f"Needs value-aware dimension discovery: {needs_value_discovery}\n\n"
                "If there are filter or grouping terms, use discover_dimension_candidates "
                "to resolve them before run_metricflow_query. "
                "If time_grain is not null, pass it as run_metricflow_query.time_granularity; "
                "do not resolve the grain itself as a dimension. "
                "If order_direction is not null, pass order_by using the selected metric as the sort field; "
                "if limit is not null, pass it to run_metricflow_query. "
                "If this is a simple metric-only question, call run_metricflow_query "
                "with metrics only and no group_by, filters, or time_granularity."
            ),
        }
    )


async def get_semantic_planning_context(
    session: ClientSession,
    plan: dict,
) -> Any:
    """
    Lightweight semantic metadata retrieval.

    This is not full metadata preloading. It keeps the lazy-loading design but gives
    the agent relevant semantic candidates before the tool loop starts.

    The agent can still call semantic_search, list_metrics, list_dimensions, and
    discover_dimension_candidates later if it needs more information.
    """
    if plan.get("intent") not in {"metric_query", "metadata_question"}:
        return None

    search_query_parts = [
        plan.get("user_question_rewritten") or "",
        *plan.get("metric_terms", []),
        *plan.get("dimension_terms", []),
        *plan.get("filter_terms", []),
        *plan.get("time_terms", []),
        plan.get("time_grain") or "",
        *plan.get("ranking_terms", []),
        plan.get("order_direction") or "",
    ]

    search_query = " ".join(
        str(part).strip()
        for part in search_query_parts
        if str(part).strip()
    )

    if not search_query:
        return None

    try:
        return await call_mcp_tool(
            session=session,
            tool_name="semantic_search",
            tool_args={
                "query": search_query,
                "top_k": 10,
            },
        )
    except Exception as exc:
        return {"error": str(exc)}


def build_system_prompt(
    *,
    conversation_history: list[dict] | None,
    query_plan: dict,
    semantic_context: Any,
) -> str:
    history_text = json.dumps(conversation_history or [], indent=2, default=str)
    query_plan_text = json.dumps(query_plan, indent=2, default=str)
    semantic_context_text = json.dumps(semantic_context, indent=2, default=str)

    return f"""
You are an autonomous commerce analytics agent.

You answer user questions using MCP tools exposed by the commerce analytics MCP server.

Core production rules:
- The planning layer classifies whether the user request is an executable metric query.
- If query_plan.requires_metricflow_execution is true, you must call run_metricflow_query before giving the final answer.
- list_metrics, list_dimensions, semantic_search, similar_dimensions, get_dimension_values, and discover_dimension_candidates are discovery tools only.
- Discovery tools are not final answers for numeric analytics questions.
- Do not invent metrics, dimensions, values, filters, or numeric results.
- Use run_metricflow_query to get final numeric results.

Metric query rules:
- For a simple metric-only question, call run_metricflow_query with metrics only and no group_by or filters.
- Do not ask "how would you like to see it" for a complete metric-only question.
- Ask a clarification question only when the planning layer says clarification_needed, or when no safe metric/dimension mapping can be found after discovery.

Time grain rules:
- If query_plan.time_grain is day, week, month, quarter, or year, pass it to run_metricflow_query as time_granularity.
- Calendar grains such as month, monthly, week, weekly, quarter, and year are time grains, not ordinary semantic dimensions.
- Do not call discover_dimension_candidates only to resolve a pure calendar grain.
- Do not invent date-derived group_by names such as metric_time__month or order__order_date__month. The run_metricflow_query tool handles time_granularity.
- If the user asks for a time grain plus another breakdown, put the non-time breakdowns in group_by and the calendar grain in time_granularity.

Metric grain rules:
- For generic money, spend, cost, total spend, expenses, or amount spent, prefer total_spend.
- Use item_total_spend only when the user explicitly asks about item spend, product spend, grocery items, alcohol items, top items, or item/product-level analysis.
- Do not choose item_total_spend merely because the user says shop, merchant, city, or money.

Ranking rules:
- If query_plan.order_direction is desc or the user asks for top, highest, most, biggest, largest, or spend the most, pass order_by with the selected metric as field and direction "desc".
- If query_plan.order_direction is asc or the user asks for lowest, least, smallest, or cheapest, pass order_by with the selected metric as field and direction "asc".
- If query_plan.limit is not null, pass limit to run_metricflow_query.
- For "which item/merchant/category had the highest/most" questions, use limit 1.
- For "top" lists without a requested number, use limit 10.

Dimension and filter discovery rules:
- Keep the system lazy-loaded. Do not list all metadata unless needed.
- Use semantic_search for broad semantic matching.
- Use list_metrics only when you need to understand available metrics.
- Use list_dimensions to understand valid dimensions for a selected metric.
- Use discover_dimension_candidates when the user mentions a filter, grouping, merchant, city, item, category, platform, payment method, product, grocery, alcohol, or any phrase that may be a value inside a dimension column.
- Prefer discover_dimension_candidates over guessing dimension names.
- For filters, prefer candidates with match_type='dimension_value'.
- Use get_dimension_values when an exact dimension value still needs confirmation.

Execution rules:
- If a tool call fails, inspect the error and retry with corrected metric, dimension, or filter names.
- When run_metricflow_query returns structured data, use the returned data/columns as the source for final answers; if order_by or limit was used, those rows are already post-processed.
- Final answer should be short, clear, and business-friendly.
- Mention the result and briefly explain how it was grouped, sorted, limited, or filtered.
- Do not expose unnecessary internal JSON unless the user asks.

Query plan:
{query_plan_text}

Relevant semantic metadata context:
{semantic_context_text}

Recent conversation history:
{history_text}

Use conversation history only to resolve follow-up questions like:
- What about Munich?
- Now show that by city.
- Only Berlin.
""".strip()


def build_execution_trace(
    *,
    run_started_at: str,
    question: str,
    conversation_history: list[dict] | None,
    query_plan: dict | None,
    semantic_context: Any,
    final_answer: str,
    trace_steps: list[dict],
    status: str,
    error: str | None,
) -> dict:
    return {
        "started_at": run_started_at,
        "finished_at": now_iso(),
        "question": question,
        "conversation_history_used": conversation_history or [],
        "query_plan": query_plan or {},
        "semantic_context": semantic_context,
        "final_answer": final_answer,
        "steps": trace_steps,
        "status": status,
        "error": error,
        "agent_mode": "mcp",
    }


def is_time_like_group_by(group_by: str) -> bool:
    """Return true for group_by names that represent time/date grains.

    This is a generic structural check, not a business-dimension alias table.
    It prevents the LLM from encoding calendar grain requests as fake dimensions
    when the planner has already identified an explicit time_grain.
    """
    normalized = group_by.strip().lower()
    return (
        normalized == "metric_time"
        or normalized.startswith("metric_time__")
        or "__date" in normalized
        or "__time" in normalized
        or normalized.endswith("_date")
        or normalized.endswith("_time")
    )


def normalize_metricflow_tool_args(tool_args: dict, query_plan: dict) -> dict:
    """Apply deterministic planner constraints before calling MetricFlow.

    The LLM still selects metrics, business dimensions, and filters. The control
    layer only prevents a known class of invalid plans: treating calendar grain
    as an ordinary group_by dimension.
    """
    normalized_args = dict(tool_args or {})
    time_grain = query_plan.get("time_grain")

    if time_grain in VALID_TIME_GRAINS:
        normalized_args["time_granularity"] = time_grain

        original_group_by = normalized_args.get("group_by") or []
        normalized_args["group_by"] = [
            dimension
            for dimension in original_group_by
            if not is_time_like_group_by(str(dimension))
        ]

    order_direction = query_plan.get("order_direction")
    metrics = normalized_args.get("metrics") or []
    if order_direction in {"asc", "desc"} and metrics and not normalized_args.get("order_by"):
        normalized_args["order_by"] = [
            {
                "field": metrics[0],
                "direction": order_direction,
            }
        ]

    if query_plan.get("limit") is not None and normalized_args.get("limit") is None:
        normalized_args["limit"] = query_plan.get("limit")

    return normalized_args


def metricflow_query_succeeded(tool_results: list[dict]) -> bool:
    return any(
        step.get("tool") == "run_metricflow_query"
        and isinstance(step.get("output"), dict)
        and bool(step["output"].get("success"))
        for step in tool_results
    )


def latest_successful_metricflow_result(tool_results: list[dict]) -> dict | None:
    for step in reversed(tool_results):
        if (
            step.get("tool") == "run_metricflow_query"
            and isinstance(step.get("output"), dict)
            and bool(step["output"].get("success"))
        ):
            return step

    return None


def build_metricflow_result_fallback_answer(tool_result: dict) -> str:
    output = tool_result.get("output", {})
    plan = output.get("plan") or tool_result.get("arguments", {})
    rows = output.get("data") or []
    columns = output.get("columns") or []

    if not rows:
        return "The query ran successfully, but it returned no rows."

    preview_rows = rows[:10]

    return (
        "The query ran successfully, but the agent could not complete the final wording. "
        f"Plan used: {json.dumps(plan, default=str)}. "
        f"Columns: {json.dumps(columns, default=str)}. "
        f"First rows: {json.dumps(preview_rows, default=str)}"
    )


async def run_mcp_analytics_agent_async(
    question: str,
    conversation_history: list[dict] | None = None,
) -> dict:
    run_started_at = now_iso()
    trace_steps: list[dict] = []
    tool_results: list[dict] = []
    semantic_context: Any = None

    try:
        query_plan = create_query_plan(
            question=question,
            conversation_history=conversation_history,
        )
    except Exception as exc:
        query_plan = {
            "intent": "clarification_needed",
            "requires_metricflow_execution": False,
            "user_question_rewritten": question,
            "metric_terms": [],
            "dimension_terms": [],
            "filter_terms": [],
            "time_terms": [],
            "time_grain": None,
            "ranking_terms": [],
            "order_direction": None,
            "limit": None,
            "needs_value_aware_dimension_discovery": False,
            "clarification_question": (
                "I could not safely understand the analytics request. "
                "Can you rephrase it?"
            ),
            "reason": f"Planner failed: {exc}",
        }

    if query_plan.get("intent") == "unsupported":
        final_answer = (
            "I cannot answer that with the commerce analytics MCP tools. "
            "Try asking about spend, orders, merchants, items, categories, fees, "
            "discounts, refunds, or trends."
        )

        execution_trace = build_execution_trace(
            run_started_at=run_started_at,
            question=question,
            conversation_history=conversation_history,
            query_plan=query_plan,
            semantic_context=semantic_context,
            final_answer=final_answer,
            trace_steps=trace_steps,
            status="success",
            error=None,
        )

        log_execution_trace(execution_trace)

        return {
            "question": question,
            "answer": final_answer,
            "tool_results": tool_results,
            "execution_trace": execution_trace,
        }

    if query_plan.get("intent") == "clarification_needed":
        final_answer = (
            query_plan.get("clarification_question")
            or "Can you clarify what metric or breakdown you want?"
        )

        execution_trace = build_execution_trace(
            run_started_at=run_started_at,
            question=question,
            conversation_history=conversation_history,
            query_plan=query_plan,
            semantic_context=semantic_context,
            final_answer=final_answer,
            trace_steps=trace_steps,
            status="success",
            error=None,
        )

        log_execution_trace(execution_trace)

        return {
            "question": question,
            "answer": final_answer,
            "tool_results": tool_results,
            "execution_trace": execution_trace,
        }

    server_params = StdioServerParameters(
        command=sys.executable,
        args=[str(SERVER_PATH)],
        cwd=str(PROJECT_ROOT),
    )

    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            semantic_context = await get_semantic_planning_context(
                session=session,
                plan=query_plan,
            )

            messages: list[Any] = [
                {
                    "role": "system",
                    "content": build_system_prompt(
                        conversation_history=conversation_history,
                        query_plan=query_plan,
                        semantic_context=semantic_context,
                    ),
                },
                {
                    "role": "user",
                    "content": query_plan.get("user_question_rewritten") or question,
                },
            ]

            for _ in range(MAX_AGENT_STEPS):
                openai_client = get_openai_client()

                response = openai_client.chat.completions.create(
                    model=DEFAULT_MODEL,
                    messages=messages,
                    tools=TOOLS,
                    tool_choice="auto",
                    temperature=0,
                )

                message = response.choices[0].message
                messages.append(message)

                if not message.tool_calls:
                    final_answer = message.content or ""

                    if (
                        plan_requires_metricflow_execution(query_plan)
                        and not metricflow_query_succeeded(tool_results)
                    ):
                        append_force_execution_message(
                            messages=messages,
                            plan=query_plan,
                        )
                        continue

                    execution_trace = build_execution_trace(
                        run_started_at=run_started_at,
                        question=question,
                        conversation_history=conversation_history,
                        query_plan=query_plan,
                        semantic_context=semantic_context,
                        final_answer=final_answer,
                        trace_steps=trace_steps,
                        status="success",
                        error=None,
                    )

                    log_execution_trace(execution_trace)

                    return {
                        "question": question,
                        "answer": final_answer,
                        "tool_results": tool_results,
                        "execution_trace": execution_trace,
                    }

                for tool_call in message.tool_calls:
                    tool_name = tool_call.function.name
                    tool_args = safe_json_loads(
                        tool_call.function.arguments or "{}",
                        fallback={},
                    )

                    if tool_name == "run_metricflow_query":
                        tool_args = normalize_metricflow_tool_args(
                            tool_args=tool_args,
                            query_plan=query_plan,
                        )

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

    successful_metricflow_result = latest_successful_metricflow_result(tool_results)

    if successful_metricflow_result:
        fallback_answer = build_metricflow_result_fallback_answer(successful_metricflow_result)
        fallback_status = "success"
        fallback_error = None
    else:
        fallback_answer = "The MCP agent could not complete the query."
        fallback_status = "failed"
        fallback_error = "MCP session ended unexpectedly"

    execution_trace = build_execution_trace(
        run_started_at=run_started_at,
        question=question,
        conversation_history=conversation_history,
        query_plan=query_plan,
        semantic_context=semantic_context,
        final_answer=fallback_answer,
        trace_steps=trace_steps,
        status=fallback_status,
        error=fallback_error,
    )

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