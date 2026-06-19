import difflib
import json
import os
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

AVAILABLE_GROUP_BYS = sorted(
    {
        dimension
        for dimensions in METRIC_CATALOG.values()
        for dimension in dimensions
    }
)

AVAILABLE_FILTERS = AVAILABLE_GROUP_BYS



def discover_dimension_column(dimension_name: str) -> str | None:
    """
    Converts a MetricFlow dimension like order__residence_city
    into a physical column like residence_city, if it exists in marts.fct_orders.
    """
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

def build_query_plan(question: str) -> dict:
    prompt = f"""
You are an analytics semantic-layer planner.

Convert the user question into a structured MetricFlow query plan.

Available metrics:
{AVAILABLE_METRICS}

Available dimensions:
{AVAILABLE_GROUP_BYS}

Metric catalog:
{json.dumps(METRIC_CATALOG, indent=2)}

Return ONLY valid JSON with this structure:
{{
  "metrics": ["metric_name"],
  "group_by": ["dimension_name"],
  "filters": [
    {{
      "dimension": "dimension_name",
      "operator": "=",
      "value": "filter value"
    }}
  ]
}}

Rules:
- Use only available metrics and dimensions.
- A group_by or filter dimension must be valid for the selected metric.
- Do not invent columns.
- Do not write SQL.
- Do not write MetricFlow Dimension syntax.
- Put filter values exactly as understood from the user question.
- Boolean values must be true/false, not strings.
- If there are no groupings, return "group_by": [].
- If there are no filters, return "filters": [].

Examples:

User: How many orders did I have in Berlin with alcohol?
Return:
{{
  "metrics": ["order_count"],
  "group_by": [],
  "filters": [
    {{
      "dimension": "order__residence_city",
      "operator": "=",
      "value": "berlin"
    }},
    {{
      "dimension": "order__contains_alcohol",
      "operator": "=",
      "value": true
    }}
  ]
}}

User: Show total spend by career stage
Return:
{{
  "metrics": ["total_spend"],
  "group_by": ["order__career_stage"],
  "filters": []
}}

User question:
{question}
"""

    response = client.chat.completions.create(
        model="gpt-4.1-mini",
        messages=[{"role": "user", "content": prompt}],
        temperature=0,
        response_format={"type": "json_object"},
    )

    content = response.choices[0].message.content

    if not content:
        raise ValueError("OpenAI returned an empty response.")

    print("\nRaw AI response:")
    print(content)

    return json.loads(content)

def decompose_question(user_input: str) -> list[str]:
    prompt = f"""
You are an analytics query decomposer.

Break the user input into one or more independent analytics questions.

Return ONLY valid JSON with this structure:
{{
  "questions": ["question 1", "question 2"]
}}

Rules:
- If the user asks one question, return one question.
- If the user separates questions with "|" or asks multiple things, split them.
- Do not answer the questions.
- Do not add new questions.

User input:
{user_input}
"""

    response = client.chat.completions.create(
        model="gpt-4.1-mini",
        messages=[{"role": "user", "content": prompt}],
        temperature=0,
        response_format={"type": "json_object"},
    )

    content = response.choices[0].message.content

    if not content:
        raise ValueError("OpenAI returned an empty decomposition response.")

    parsed = json.loads(content)
    return parsed.get("questions", [user_input])

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
        values = conn.execute(query, [limit]).fetchall()

    return [row[0] for row in values]


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

    for metric in selected_metrics:
        if metric not in AVAILABLE_METRICS:
            raise ValueError(f"Invalid metric: {metric}")

    valid_dimensions_for_selected_metrics = set()

    for metric in selected_metrics:
        valid_dimensions_for_selected_metrics.update(
            METRIC_CATALOG.get(metric, [])
        )

    for group_by in plan.get("group_by", []):
        if group_by not in valid_dimensions_for_selected_metrics:
            raise ValueError(
                f"Invalid group_by '{group_by}' for metrics {selected_metrics}"
            )

    for filter_item in plan.get("filters", []):
        dimension = filter_item.get("dimension")
        operator = filter_item.get("operator")

        if dimension not in valid_dimensions_for_selected_metrics:
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

        print(
            f"Resolved filter: {dimension} {operator} "
            f"{raw_value!r} -> {resolved_value!r}"
        )

        clause = (
            f"{{{{ Dimension('{dimension}') }}}} "
            f"{operator} "
            f"{format_value_for_where(resolved_value)}"
        )

        clauses.append(clause)

    return " and ".join(clauses)


def run_metricflow(plan: dict) -> str:
    command = ["mf", "query"]

    for metric in plan["metrics"]:
        command.extend(["--metrics", metric])

    for group_by in plan.get("group_by", []):
        command.extend(["--group-by", group_by])

    where_clause = build_where_clause(plan)

    if where_clause:
        command.extend(["--where", where_clause])

    print("\nMetricFlow command:")
    print(" ".join(command))

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
        print(result.stderr)
        raise RuntimeError("MetricFlow query failed.")

    return result.stdout


def explain_result(question: str, plan: dict, result: str) -> str:
    prompt = f"""
You are an analytics assistant.

User question:
{question}

Query plan:
{json.dumps(plan, indent=2)}

Result:
{result}

Write a short, clear business answer.
Do not mention SQL or MetricFlow.
If the result is empty, say no matching data was found.
"""

    response = client.chat.completions.create(
        model="gpt-4.1-mini",
        messages=[{"role": "user", "content": prompt}],
        temperature=0,
    )

    return response.choices[0].message.content or ""

def answer_question(question: str) -> dict:
    print(f"\nQuestion: {question}")

    print("\nPlanning query...")
    plan = build_query_plan(question)

    print("\nQuery plan:")
    print(json.dumps(plan, indent=2))

    validate_plan(plan)

    print("\nRunning MetricFlow...")
    result = run_metricflow(plan)

    print("\nResult:")
    print(result)

    explanation = explain_result(question, plan, result)

    print("\nAI Explanation:")
    print(explanation)

    return {
        "question": question,
        "plan": plan,
        "result": result,
        "explanation": explanation,
    }

def main() -> None:
    user_input = input(
        "Ask one or more commerce analytics questions: "
    )

    print("\nDecomposing input...")
    questions = decompose_question(user_input)

    print("\nDetected questions:")

    for i, question in enumerate(questions, start=1):
        print(f"{i}. {question}")

    all_answers = []

    for question in questions:
        answer = answer_question(question)
        all_answers.append(answer)

    print("\nFinal Summary:")

    for i, answer in enumerate(all_answers, start=1):
        print(f"\n{i}. {answer['question']}")
        print(answer["explanation"])


if __name__ == "__main__":
    main()