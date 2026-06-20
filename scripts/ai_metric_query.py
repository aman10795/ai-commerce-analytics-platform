import difflib
import json
import os
import io
import pandas as pd
import subprocess
from pathlib import Path
from typing import Any

import duckdb
from dotenv import load_dotenv
from openai import OpenAI

from semantic_metadata import get_metric_catalog


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DBT_PROJECT_DIR = PROJECT_ROOT / "commerce_analytics_dbt"
DUCKDB_PATH = PROJECT_ROOT / "data" / "warehouse" / "commerce_analytics.duckdb"

load_dotenv(PROJECT_ROOT / ".env")

client = OpenAI()

print("\nLoading MetricFlow semantic metadata...")
METRIC_CATALOG = get_metric_catalog()

AVAILABLE_METRICS = sorted(METRIC_CATALOG.keys())

AVAILABLE_DIMENSIONS = sorted(
    {
        dimension
        for dimensions in METRIC_CATALOG.values()
        for dimension in dimensions
    }
)

DIMENSION_ALIASES = {
    "area": ["order__residence_city", "order__country_or_market"],
    "city": ["order__residence_city"],
    "country": ["order__country_or_market"],
    "market": ["order__country_or_market"],
    "merchant": ["order__merchant_name", "merchant__merchant_name"],
    "restaurant": ["order__merchant_name"],
    "store": ["order__merchant_name"],
    "category": ["order__order_category"],
    "payment": ["order__payment_method"],
    "platform": ["order__source_platform"],
}

def find_similar_dimensions(
    user_term: str,
    metric_name: str | None = None,
) -> dict:
    term = user_term.strip().lower()

    if metric_name:
        candidate_dimensions = METRIC_CATALOG.get(metric_name, [])
    else:
        candidate_dimensions = AVAILABLE_DIMENSIONS

    alias_matches = [
        dim for dim in DIMENSION_ALIASES.get(term, [])
        if dim in candidate_dimensions
    ]

    if alias_matches:
        return {
            "user_term": user_term,
            "matches": alias_matches,
            "method": "alias",
        }

    fuzzy_matches = difflib.get_close_matches(
        term,
        candidate_dimensions,
        n=5,
        cutoff=0.4,
    )

    return {
        "user_term": user_term,
        "matches": fuzzy_matches,
        "method": "fuzzy",
    }

def discover_dimension_column(dimension_name: str) -> str | None:
    column_guess = dimension_name.split("__")[-1]

    query = """
        select column_name
        from information_schema.columns
        where table_schema = 'marts'
          and table_name = 'fct_orders'
    """

    with duckdb.connect(str(DUCKDB_PATH)) as conn:
        rows = conn.execute(query).fetchall()

    available_columns = [row[0] for row in rows]

    if column_guess in available_columns:
        return column_guess

    return None


def get_dimension_values(dimension_name: str, limit: int = 100) -> list[Any]:
    column_name = discover_dimension_column(dimension_name)

    if not column_name:
        return []

    query = f"""
        select distinct {column_name} as value
        from marts.fct_orders
        where {column_name} is not null
        order by 1
        limit ?
    """

    with duckdb.connect(str(DUCKDB_PATH)) as conn:
        rows = conn.execute(query, [limit]).fetchall()

    return [row[0] for row in rows]


def resolve_dimension_value(dimension_name: str, value: Any) -> Any:
    if isinstance(value, bool):
        return value

    values = get_dimension_values(dimension_name)

    if not values:
        return value

    value_str = str(value).strip().lower()

    for existing_value in values:
        if str(existing_value).strip().lower() == value_str:
            return existing_value

    possible_matches = [str(v).strip().lower() for v in values]

    fuzzy_match = difflib.get_close_matches(
        value_str,
        possible_matches,
        n=1,
        cutoff=0.7,
    )

    if fuzzy_match:
        matched_value = fuzzy_match[0]

        for existing_value in values:
            if str(existing_value).strip().lower() == matched_value:
                return existing_value

    return value


def validate_plan(plan: dict) -> None:
    selected_metrics = plan.get("metrics", [])

    if not selected_metrics:
        raise ValueError("At least one metric is required.")

    for metric in selected_metrics:
        if metric not in AVAILABLE_METRICS:
            raise ValueError(f"Invalid metric: {metric}")

    valid_dimensions = set()

    for metric in selected_metrics:
        valid_dimensions.update(METRIC_CATALOG.get(metric, []))

    for group_by in plan.get("group_by", []):
        if group_by not in valid_dimensions:
            raise ValueError(
                f"Invalid group_by '{group_by}' for metrics {selected_metrics}"
            )

    for filter_item in plan.get("filters", []):
        dimension = filter_item.get("dimension")
        operator = filter_item.get("operator")

        if dimension not in valid_dimensions:
            raise ValueError(
                f"Invalid filter dimension '{dimension}' for metrics {selected_metrics}"
            )

        if operator not in ["=", "!=", ">", ">=", "<", "<="]:
            raise ValueError(f"Invalid filter operator: {operator}")


def format_value_for_where(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"

    if isinstance(value, (int, float)):
        return str(value)

    escaped_value = str(value).replace("'", "''")
    return f"'{escaped_value}'"


def build_where_clause(plan: dict) -> str | None:
    filters = plan.get("filters", [])

    if not filters:
        return None

    clauses = []

    for filter_item in filters:
        dimension = filter_item["dimension"]
        operator = filter_item["operator"]
        raw_value = filter_item["value"]

        resolved_value = resolve_dimension_value(
            dimension_name=dimension,
            value=raw_value,
        )

        clause = (
            f"{{{{ Dimension('{dimension}') }}}} "
            f"{operator} "
            f"{format_value_for_where(resolved_value)}"
        )

        clauses.append(clause)

    return " and ".join(clauses)


def run_metricflow(plan: dict) -> str:
    validate_plan(plan)

    command = ["mf", "query"]

    for metric in plan["metrics"]:
        command.extend(["--metrics", metric])

    for group_by in plan.get("group_by", []):
        command.extend(["--group-by", group_by])

    where_clause = build_where_clause(plan)

    if where_clause:
        command.extend(["--where", where_clause])

    env = os.environ.copy()
    env["DBT_PROFILES_DIR"] = str(Path.home() / ".dbt")

    result = subprocess.run(
        command,
        cwd=DBT_PROJECT_DIR,
        env=env,
        text=True,
        capture_output=True,
    )

    if result.returncode != 0:
        return f"MetricFlow error:\n{result.stderr or result.stdout}"

    return result.stdout


def tool_list_metrics() -> list[str]:
    return AVAILABLE_METRICS


def tool_list_dimensions(metric_name: str) -> list[str]:
    return METRIC_CATALOG.get(metric_name, [])


def tool_get_dimension_values(
    dimension_name: str,
    limit: int = 100,
) -> list[Any]:
    return get_dimension_values(dimension_name, limit)


def tool_run_metricflow_query(
    metrics: list[str],
    group_by: list[str] | None = None,
    filters: list[dict] | None = None,
) -> dict:
    plan = {
        "metrics": metrics,
        "group_by": group_by or [],
        "filters": filters or [],
    }

    try:
        validate_plan(plan)
        result = run_metricflow(plan)
        df = parse_metricflow_result_to_dataframe(result)

        return {
            "success": True,
            "plan": plan,
            "result": result,
            "data": df.to_dict(orient="records"),
            "columns": df.columns.tolist(),
        }

    except Exception as exc:
        return {
            "success": False,
            **build_validation_error_context(
                error_message=str(exc),
                plan=plan,
            ),
        }


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
            "description": "Get real warehouse values for a dimension. Useful for resolving casing and spelling.",
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
        "description": "Find likely MetricFlow dimensions for vague user terms like area, city, merchant, category, or platform.",
        "parameters": {
            "type": "object",
            "properties": {
                "user_term": {"type": "string"},
                "metric_name": {"type": "string"},
            },
            "required": ["user_term"],
        },
    },
}
]


TOOL_MAPPING = {
    "list_metrics": tool_list_metrics,
    "list_dimensions": tool_list_dimensions,
    "get_dimension_values": tool_get_dimension_values,
    "run_metricflow_query": tool_run_metricflow_query,
    "find_similar_dimensions": find_similar_dimensions,
}


def run_analytics_agent(question: str,conversation_history: list[dict] | None = None,) -> dict:
    history_text = json.dumps(conversation_history or [], indent=2, default=str)
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

- If the user uses vague terms like area, region, category, shop, store, vendor, or merchant, call find_similar_dimensions before asking for clarification.
Recent conversation history:
{history_text}

Use this only to resolve follow-up questions like:
- What about Munich?
- Now show that by city.
- Only Berlin.

Known metrics:
{AVAILABLE_METRICS}
""",
        },
        {"role": "user", "content": question},
    ]

    tool_results = []

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
            return {
                "question": question,
                "answer": message.content or "",
                "tool_results": tool_results,
            }

        for tool_call in message.tool_calls:
            tool_name = tool_call.function.name
            tool_args = json.loads(tool_call.function.arguments or "{}")

            tool_function = TOOL_MAPPING.get(tool_name)

            if not tool_function:
                output = {"error": f"Unknown tool: {tool_name}"}
            else:
                try:
                    output = tool_function(**tool_args)
                except Exception as exc:
                    output = {"error": str(exc)}

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

    return {
        "question": question,
        "answer": "The agent could not complete the query within the tool-call limit.",
        "tool_results": tool_results,
    }

def parse_metricflow_result_to_dataframe(result: str) -> pd.DataFrame:
    lines = result.splitlines()

    table_lines = []

    for line in lines:
        stripped = line.strip()

        if not stripped:
            continue

        if stripped.startswith(("⠋", "⠙", "✔", "🌱")):
            continue

        if set(stripped) <= {"-", " "}:
            continue

        table_lines.append(line)

    if len(table_lines) < 2:
        return pd.DataFrame()

    table_text = "\n".join(table_lines)

    try:
        df = pd.read_fwf(io.StringIO(table_text))
        df = df.dropna(how="all")
        return df
    except Exception:
        return pd.DataFrame()

def build_validation_error_context(
    error_message: str,
    plan: dict,
) -> dict:
    selected_metrics = plan.get("metrics", [])

    valid_dimensions = set()

    for metric in selected_metrics:
        valid_dimensions.update(METRIC_CATALOG.get(metric, []))

    return {
        "error": error_message,
        "failed_plan": plan,
        "valid_metrics": AVAILABLE_METRICS,
        "valid_dimensions_for_selected_metrics": sorted(valid_dimensions),
        "instruction": (
            "Correct the failed query by using only valid metrics and dimensions. "
            "If the user asked for an unavailable dimension, choose the closest valid dimension or explain that it is unavailable."
        ),
    }

def main() -> None:
    question = input("Ask a commerce analytics question: ")
    response = run_analytics_agent(question)

    print("\nFinal Answer:")
    print(response["answer"])

    print("\nTool Calls:")
    print(json.dumps(response["tool_results"], indent=2, default=str))


if __name__ == "__main__":
    main()