import difflib
import io
import json
import os
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any

import duckdb
import numpy as np
import pandas as pd
from dotenv import load_dotenv
from openai import OpenAI

from analytics.semantic_metadata import get_metric_catalog


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DBT_PROJECT_DIR = PROJECT_ROOT / "commerce_analytics_dbt"
DUCKDB_PATH = PROJECT_ROOT / "data" / "warehouse" / "commerce_analytics.duckdb"

SEMANTIC_INDEX_PATH = PROJECT_ROOT / "artifacts" / "semantic_index.json"
EMBEDDING_MODEL = "text-embedding-3-small"
SUPPORTED_TIME_GRANULARITIES = {"day", "week", "month", "quarter", "year"}


AGENT_LOG_DIR = PROJECT_ROOT / "logs" / "agent_runs"
AGENT_LOG_DIR.mkdir(parents=True, exist_ok=True)

load_dotenv(PROJECT_ROOT / ".env")

client: OpenAI | None = None


def get_openai_client() -> OpenAI:
    global client

    if client is None:
        client = OpenAI()

    return client


# -------------------------------------------------------------------
# Lazy-loaded MetricFlow metadata
# -------------------------------------------------------------------
# Important:
# Do NOT call get_metric_catalog() at import time.
# MCP Inspector connects through stdio and can timeout if this file does heavy work
# before the MCP server finishes initialization.

METRIC_CATALOG: dict[str, list[str]] | None = None
AVAILABLE_METRICS: list[str] | None = None
AVAILABLE_DIMENSIONS: list[str] | None = None


DIMENSION_ALIASES = {
    "area": ["order__residence_city", "order__country_or_market"],
    "city": ["order__residence_city"],
    "country": ["order__country_or_market"],
    "market": ["order__country_or_market"],
    "merchant": ["order__merchant_name", "merchant__merchant_name"],
    "restaurant": ["order__merchant_name"],
    "store": ["order__merchant_name"],
    "shop": ["order__merchant_name", "merchant__merchant_name"],
    "vendor": ["merchant__merchant_name", "order__merchant_name"],
    "category": ["order__order_category"],
    "payment": ["order__payment_method"],
    "platform": ["order__source_platform"],
}


def load_metricflow_metadata() -> None:
    """
    Lazy-load MetricFlow semantic metadata.

    This prevents MCP Inspector from timing out during connection.
    Metadata is loaded only when a tool or agent call actually needs it.
    """
    global METRIC_CATALOG, AVAILABLE_METRICS, AVAILABLE_DIMENSIONS

    if METRIC_CATALOG is not None:
        return

    METRIC_CATALOG = get_metric_catalog()

    AVAILABLE_METRICS = sorted(METRIC_CATALOG.keys())

    AVAILABLE_DIMENSIONS = sorted(
        {
            dimension
            for dimensions in METRIC_CATALOG.values()
            for dimension in dimensions
        }
    )


def get_metric_catalog_cached() -> dict[str, list[str]]:
    load_metricflow_metadata()
    return METRIC_CATALOG or {}


def get_available_metrics() -> list[str]:
    load_metricflow_metadata()
    return AVAILABLE_METRICS or []


def get_available_dimensions() -> list[str]:
    load_metricflow_metadata()
    return AVAILABLE_DIMENSIONS or []


# -------------------------------------------------------------------
# Utility functions
# -------------------------------------------------------------------

def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def log_execution_trace(trace: dict) -> None:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_path = AGENT_LOG_DIR / f"agent_trace_{timestamp}.json"

    with open(log_path, "w", encoding="utf-8") as f:
        json.dump(trace, f, indent=2, default=str)

    print(f"\nExecution trace logged to: {log_path}")


def cosine_similarity(a: list[float], b: list[float]) -> float:
    a_arr = np.array(a)
    b_arr = np.array(b)

    denominator = np.linalg.norm(a_arr) * np.linalg.norm(b_arr)

    if denominator == 0:
        return 0.0

    return float(np.dot(a_arr, b_arr) / denominator)


def get_embedding(text: str) -> list[float]:
    client = get_openai_client()
    response = client.embeddings.create(
        model=EMBEDDING_MODEL,
        input=text,
    )

    return response.data[0].embedding


def load_semantic_index() -> list[dict]:
    if not SEMANTIC_INDEX_PATH.exists():
        return []

    with open(SEMANTIC_INDEX_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


# -------------------------------------------------------------------
# Semantic search / dimension matching
# -------------------------------------------------------------------

def search_semantic_layer(
    query: str,
    object_type: str | None = None,
    metric_name: str | None = None,
    top_k: int = 8,
) -> dict:
    index = load_semantic_index()

    if not index:
        return {
            "query": query,
            "matches": [],
            "error": "Semantic index not found. Run scripts/build_semantic_index.py first.",
        }

    query_embedding = get_embedding(query)

    scored = []

    for item in index:
        if object_type and item.get("type") != object_type:
            continue

        if metric_name and metric_name not in item.get("metrics", []):
            continue

        score = cosine_similarity(query_embedding, item["embedding"])

        scored.append(
            {
                "type": item.get("type"),
                "name": item.get("name"),
                "metric": item.get("metric"),
                "dimension": item.get("dimension"),
                "metrics": item.get("metrics", []),
                "score": round(score, 4),
                "text": item.get("text"),
            }
        )

    scored = sorted(scored, key=lambda x: x["score"], reverse=True)

    return {
        "query": query,
        "object_type": object_type,
        "metric_name": metric_name,
        "matches": scored[:top_k],
    }


def find_similar_dimensions(
    user_term: str,
    metric_name: str | None = None,
) -> dict:
    term = user_term.strip().lower()
    metric_catalog = get_metric_catalog_cached()

    if metric_name:
        candidate_dimensions = metric_catalog.get(metric_name, [])
    else:
        candidate_dimensions = get_available_dimensions()

    alias_matches = [
        dim
        for dim in DIMENSION_ALIASES.get(term, [])
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


def normalize_dimension_label(dimension_name: str) -> str:
    """Convert semantic dimension names into searchable words."""
    return (
        dimension_name.replace("__", " ")
        .replace("_", " ")
        .strip()
        .lower()
    )


def get_candidate_dimensions_for_metric(metric_name: str | None = None) -> list[str]:
    metric_catalog = get_metric_catalog_cached()

    if metric_name:
        return list(metric_catalog.get(metric_name, []))

    return get_available_dimensions()


def score_dimension_name(user_term: str, dimension_name: str) -> float:
    """Lightweight lexical scoring for dimension-name matching."""
    term = user_term.strip().lower()
    label = normalize_dimension_label(dimension_name)

    if not term or not label:
        return 0.0

    if term == label or term == dimension_name.lower():
        return 1.0

    if term in label:
        return 0.9

    alias_matches = DIMENSION_ALIASES.get(term, [])
    if dimension_name in alias_matches:
        return 0.88

    ratio = difflib.SequenceMatcher(None, term, label).ratio()
    return round(ratio, 4)


def score_dimension_value(user_term: str, value: Any) -> float:
    term = user_term.strip().lower()
    value_text = str(value).strip().lower()

    if not term or not value_text:
        return 0.0

    if term == value_text:
        return 1.0

    if term in value_text or value_text in term:
        return 0.85

    return round(difflib.SequenceMatcher(None, term, value_text).ratio(), 4)


def discover_dimension_candidates(
    user_term: str,
    metric_name: str | None = None,
    role: str = "any",
    limit_per_dimension: int = 20,
) -> dict[str, Any]:
    """Resolve a user phrase to candidate semantic dimensions.

    This intentionally combines several weak signals rather than hardcoding one
    mapping table: alias/fuzzy name matching, semantic index retrieval, and real
    warehouse value matching where available.
    """
    candidate_dimensions = get_candidate_dimensions_for_metric(metric_name)
    candidates: dict[str, dict[str, Any]] = {}

    def upsert_candidate(
        dimension: str,
        *,
        score: float,
        match_type: str,
        matched_value: Any = None,
        value_matches: list[dict[str, Any]] | None = None,
        text: str | None = None,
    ) -> None:
        if dimension not in candidate_dimensions:
            return

        existing = candidates.get(dimension)
        payload = {
            "dimension": dimension,
            "role": role,
            "match_type": match_type,
            "matched_value": matched_value,
            "score": round(float(score), 4),
            "value_matches": value_matches or [],
            "sample_values": get_dimension_values(dimension, limit=10),
            "text": text,
        }

        if existing is None or payload["score"] > existing.get("score", 0):
            candidates[dimension] = payload

    # 1) Alias/fuzzy/name scoring.
    for dimension in candidate_dimensions:
        score = score_dimension_name(user_term, dimension)
        if score >= 0.45:
            upsert_candidate(
                dimension,
                score=score,
                match_type="dimension_name",
            )

    # 2) Semantic retrieval from the vector index.
    try:
        semantic_results = search_semantic_layer(
            query=user_term,
            object_type=None,
            metric_name=metric_name,
            top_k=15,
        )
        for match in semantic_results.get("matches", []):
            dimension = match.get("dimension") or match.get("name")
            if not dimension:
                continue
            if match.get("type") == "relationship":
                dimension = match.get("dimension")
            if dimension in candidate_dimensions:
                upsert_candidate(
                    dimension,
                    score=float(match.get("score") or 0),
                    match_type="semantic_search",
                    text=match.get("text"),
                )
    except Exception:
        # Retrieval is helpful but not required for deterministic execution.
        pass

    # 3) Actual value matching for filters such as Berlin, KFC, grocery values, etc.
    # Keep this bounded; it is a discovery tool, not a full scan.
    for dimension in candidate_dimensions:
        values = get_dimension_values(dimension, limit=limit_per_dimension)
        value_matches = []
        for value in values:
            value_score = score_dimension_value(user_term, value)
            if value_score >= 0.72:
                value_matches.append(
                    {
                        "value": value,
                        "score": round(value_score, 4),
                    }
                )

        if value_matches:
            value_matches = sorted(
                value_matches,
                key=lambda item: item["score"],
                reverse=True,
            )[:5]
            upsert_candidate(
                dimension,
                score=max(item["score"] for item in value_matches),
                match_type="dimension_value",
                matched_value=value_matches[0]["value"],
                value_matches=value_matches,
            )

    sorted_candidates = sorted(
        candidates.values(),
        key=lambda item: item.get("score", 0),
        reverse=True,
    )

    return {
        "user_term": user_term,
        "metric_name": metric_name,
        "role": role,
        "candidates": sorted_candidates,
    }


# -------------------------------------------------------------------
# Dimension value resolution
# -------------------------------------------------------------------

def discover_dimension_source(dimension_name: str) -> tuple[str, str] | None:
    """Find the mart table/column backing a semantic dimension.

    MetricFlow dimensions are semantic names such as order__residence_city or
    order_line__item_name. The backing warehouse column is usually the suffix,
    but the mart table depends on the semantic entity/grain. This function keeps
    the value-discovery logic generic while supporting order, order_line,
    merchant, and fee contexts.
    """
    column_guess = dimension_name.split("__")[-1]

    table_priority = []
    if dimension_name.startswith("order_line__"):
        table_priority = ["fct_order_lines", "fct_orders", "dim_merchants", "fct_order_fees"]
    elif dimension_name.startswith("merchant__"):
        table_priority = ["dim_merchants", "fct_orders", "fct_order_lines", "fct_order_fees"]
    elif dimension_name.startswith("fee__"):
        table_priority = ["fct_order_fees", "fct_orders", "fct_order_lines", "dim_merchants"]
    else:
        table_priority = ["fct_orders", "fct_order_lines", "dim_merchants", "fct_order_fees"]

    placeholders = ", ".join(["?"] * len(table_priority))
    query = f"""
        select table_name, column_name
        from information_schema.columns
        where table_schema = 'marts'
          and table_name in ({placeholders})
    """

    with duckdb.connect(str(DUCKDB_PATH)) as conn:
        rows = conn.execute(query, table_priority).fetchall()

    available = {(row[0], row[1]) for row in rows}

    for table_name in table_priority:
        if (table_name, column_guess) in available:
            return table_name, column_guess

    return None


def discover_dimension_column(dimension_name: str) -> str | None:
    source = discover_dimension_source(dimension_name)
    return source[1] if source else None


def get_dimension_values(dimension_name: str, limit: int = 100) -> list[Any]:
    source = discover_dimension_source(dimension_name)

    if not source:
        return []

    table_name, column_name = source

    query = f"""
        select distinct {column_name} as value
        from marts.{table_name}
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


# -------------------------------------------------------------------
# MetricFlow validation and execution
# -------------------------------------------------------------------

def normalize_time_granularity(value: Any) -> str | None:
    if value is None:
        return None

    normalized = str(value).strip().lower()

    if normalized in SUPPORTED_TIME_GRANULARITIES:
        return normalized

    raise ValueError(
        f"Invalid time_granularity '{value}'. "
        f"Supported values are {sorted(SUPPORTED_TIME_GRANULARITIES)}."
    )


def metric_supports_metric_time(selected_metrics: list[str]) -> bool:
    metric_catalog = get_metric_catalog_cached()

    return all(
        "metric_time" in set(metric_catalog.get(metric, []))
        for metric in selected_metrics
    )


def metricflow_time_group_by(time_granularity: str) -> str:
    return f"metric_time__{time_granularity}"



def normalize_order_by(order_by: Any) -> list[dict[str, str]]:
    if not order_by:
        return []

    normalized_items = []
    for item in order_by:
        if isinstance(item, str):
            normalized_items.append({"field": item, "direction": "desc"})
            continue

        if not isinstance(item, dict):
            raise ValueError(f"Invalid order_by item: {item}")

        field = str(item.get("field") or item.get("metric") or item.get("dimension") or "").strip()
        direction = str(item.get("direction") or "desc").strip().lower()

        if not field:
            raise ValueError(f"Invalid order_by field: {item}")
        if direction not in {"asc", "desc"}:
            raise ValueError(f"Invalid order_by direction: {direction}")

        normalized_items.append({"field": field, "direction": direction})

    return normalized_items


def validate_order_by(plan: dict) -> None:
    order_by = normalize_order_by(plan.get("order_by"))
    plan["order_by"] = order_by

    if not order_by:
        return

    allowed_fields = set(plan.get("metrics") or [])
    allowed_fields.update(plan.get("group_by") or [])

    if plan.get("time_granularity"):
        allowed_fields.add(metricflow_time_group_by(plan["time_granularity"]))

    for item in order_by:
        if item["field"] not in allowed_fields:
            raise ValueError(
                f"Invalid order_by field '{item['field']}'. "
                f"Allowed fields are {sorted(allowed_fields)}."
            )


def validate_limit(plan: dict) -> None:
    limit = plan.get("limit")

    if limit is None:
        plan["limit"] = None
        return

    try:
        normalized_limit = int(limit)
    except (TypeError, ValueError):
        raise ValueError(f"Invalid limit: {limit}")

    if normalized_limit <= 0:
        raise ValueError(f"Invalid limit: {limit}")

    plan["limit"] = normalized_limit

def validate_plan(plan: dict) -> None:
    selected_metrics = plan.get("metrics", [])
    available_metrics = get_available_metrics()
    metric_catalog = get_metric_catalog_cached()

    if not selected_metrics:
        raise ValueError("At least one metric is required.")

    for metric in selected_metrics:
        if metric not in available_metrics:
            raise ValueError(f"Invalid metric: {metric}")

    valid_dimensions = set()

    for metric in selected_metrics:
        valid_dimensions.update(metric_catalog.get(metric, []))

    time_granularity = normalize_time_granularity(plan.get("time_granularity"))

    if time_granularity and not metric_supports_metric_time(selected_metrics):
        raise ValueError(
            "time_granularity was requested, but metric_time is not available "
            f"for metrics {selected_metrics}."
        )

    plan["time_granularity"] = time_granularity

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

        if operator not in ["=", "!=", ">", ">=", "<", "<=", "in", "not in"]:
            raise ValueError(f"Invalid filter operator: {operator}")

    validate_order_by(plan)
    validate_limit(plan)


def build_validation_error_context(
    error_message: str,
    plan: dict,
) -> dict:
    selected_metrics = plan.get("metrics", [])
    metric_catalog = get_metric_catalog_cached()

    valid_dimensions = set()

    for metric in selected_metrics:
        valid_dimensions.update(metric_catalog.get(metric, []))

    return {
        "error": error_message,
        "failed_plan": plan,
        "valid_metrics": get_available_metrics(),
        "valid_dimensions_for_selected_metrics": sorted(valid_dimensions),
        "supported_time_granularities": sorted(SUPPORTED_TIME_GRANULARITIES),
        "instruction": (
            "Correct the failed query by using only valid metrics and dimensions. "
            "For calendar aggregation requests such as by month, by week, or by year, "
            "use the separate time_granularity argument instead of inventing date-derived "
            "group_by values such as metric_time__month or order__order_date__month. "
            "If the user asked for an unavailable dimension, choose the closest valid dimension "
            "or explain that it is unavailable."
        ),
    }


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

        if operator in {"in", "not in"}:
            values = resolved_value if isinstance(resolved_value, list) else [resolved_value]
            formatted_values = ", ".join(format_value_for_where(value) for value in values)
            clause = (
                f"{{{{ Dimension('{dimension}') }}}} "
                f"{operator} "
                f"({formatted_values})"
            )
        else:
            clause = (
                f"{{{{ Dimension('{dimension}') }}}} "
                f"{operator} "
                f"{format_value_for_where(resolved_value)}"
            )

        clauses.append(clause)

    return " and ".join(clauses)


def run_metricflow(plan: dict) -> dict:
    validate_plan(plan)

    command = ["mf", "query"]

    for metric in plan["metrics"]:
        command.extend(["--metrics", metric])

    for group_by in plan.get("group_by", []):
        command.extend(["--group-by", group_by])

    time_granularity = plan.get("time_granularity")
    if time_granularity:
        command.extend(["--group-by", metricflow_time_group_by(time_granularity)])

    where_clause = build_where_clause(plan)

    if where_clause:
        command.extend(["--where", where_clause])

    metricflow_command = " ".join(command)

    env = os.environ.copy()
    env["DBT_PROFILES_DIR"] = str(Path.home() / ".dbt")

    result = subprocess.run(
        command,
        cwd=DBT_PROJECT_DIR,
        env=env,
        text=True,
        capture_output=True,
    )

    return {
        "metricflow_command": metricflow_command,
        "raw_result": result.stdout,
        "error": None if result.returncode == 0 else result.stderr or result.stdout,
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



def coerce_sort_series(series: pd.Series) -> pd.Series:
    """Return a safe sort key for a MetricFlow result column.

    MetricFlow CLI output is parsed from fixed-width text, so numeric metric
    columns can arrive as strings. In newer pandas versions,
    pd.to_numeric(..., errors="ignore") is no longer a safe option and can raise
    "invalid error value specified". We therefore use errors="coerce" for the
    sort key only, while preserving the original result values returned to the
    caller.
    """
    numeric_series = pd.to_numeric(series, errors="coerce")

    # If at least one value converted to a number, use numeric sorting. NaNs are
    # pushed last by sort_values below.
    if numeric_series.notna().any():
        return numeric_series

    # Otherwise fall back to case-insensitive text sorting.
    return series.astype(str).str.lower()


def apply_result_post_processing(df: pd.DataFrame, plan: dict) -> pd.DataFrame:
    """Apply ranking/limit locally after MetricFlow returns tabular data.

    MetricFlow is still the source of truth for the metric calculation. Sorting
    and limiting are presentation/query-shape operations, and keeping them here
    avoids making the LLM know provider-specific CLI syntax for top-N queries.
    """
    if df.empty:
        return df

    processed = df.copy()

    # Apply lower-priority sorts first so earlier order_by entries win because
    # mergesort is stable.
    for sort_index, item in enumerate(reversed(plan.get("order_by") or [])):
        field = item.get("field")
        direction = str(item.get("direction", "desc")).lower()

        if field not in processed.columns:
            continue

        sort_key = f"__sort_key_{sort_index}_{field}"
        processed[sort_key] = coerce_sort_series(processed[field])
        processed = processed.sort_values(
            by=sort_key,
            ascending=(direction == "asc"),
            kind="mergesort",
            na_position="last",
        ).drop(columns=[sort_key])

    if plan.get("limit") is not None:
        processed = processed.head(int(plan["limit"]))

    return processed.reset_index(drop=True)


def dataframe_to_text(df: pd.DataFrame) -> str:
    if df.empty:
        return ""

    return df.to_string(index=False)

# -------------------------------------------------------------------
# Tool functions
# -------------------------------------------------------------------

def tool_list_metrics() -> list[str]:
    return get_available_metrics()


def tool_list_dimensions(metric_name: str) -> list[str]:
    return get_metric_catalog_cached().get(metric_name, [])


def tool_get_dimension_values(
    dimension_name: str,
    limit: int = 100,
) -> list[Any]:
    return get_dimension_values(dimension_name, limit)


def tool_discover_dimension_candidates(
    user_term: str,
    metric_name: str | None = None,
    role: str = "any",
    limit_per_dimension: int = 20,
) -> dict[str, Any]:
    return discover_dimension_candidates(
        user_term=user_term,
        metric_name=metric_name,
        role=role,
        limit_per_dimension=limit_per_dimension,
    )


def tool_run_metricflow_query(
    metrics: list[str],
    group_by: list[str] | None = None,
    filters: list[dict] | None = None,
    time_granularity: str | None = None,
    order_by: list[dict] | None = None,
    limit: int | None = None,
) -> dict:
    plan = {
        "metrics": metrics,
        "group_by": group_by or [],
        "filters": filters or [],
        "time_granularity": time_granularity,
        "order_by": order_by or [],
        "limit": limit,
    }

    try:
        validate_plan(plan)

        metricflow_response = run_metricflow(plan)
        raw_result = metricflow_response.get("raw_result", "")
        metricflow_error = metricflow_response.get("error")

        # Do not try to parse/sort failed MetricFlow output as if it were a
        # result table. Return the real MetricFlow error instead.
        if metricflow_error is not None:
            return {
                "success": False,
                "plan": plan,
                "metricflow_command": metricflow_response.get("metricflow_command"),
                "result": raw_result,
                "raw_result": raw_result,
                "error": metricflow_error,
                "data": [],
                "columns": [],
                "row_count": 0,
            }

        df = parse_metricflow_result_to_dataframe(raw_result)

        try:
            processed_df = apply_result_post_processing(df, plan)
            post_processing_error = None
        except Exception as postprocess_exc:
            # Ranking is a local presentation step. A post-processing failure
            # should not be misreported as a MetricFlow semantic/execution
            # failure. Fall back to the raw parsed table and expose a warning.
            processed_df = df
            post_processing_error = str(postprocess_exc)

        processed_result = dataframe_to_text(processed_df)

        return {
            "success": True,
            "plan": plan,
            "metricflow_command": metricflow_response.get("metricflow_command"),
            "result": processed_result or raw_result,
            "raw_result": raw_result,
            "error": None,
            "post_processing_error": post_processing_error,
            "data": processed_df.to_dict(orient="records"),
            "columns": processed_df.columns.tolist(),
            "row_count": len(processed_df),
        }

    except Exception as exc:
        return {
            "success": False,
            **build_validation_error_context(
                error_message=str(exc),
                plan=plan,
            ),
        }

