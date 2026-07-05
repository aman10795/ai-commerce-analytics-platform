from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP

from analytics.ai_metric_query import (
    find_similar_dimensions,
    get_available_metrics,
    get_metric_catalog_cached,
    search_semantic_layer,
    tool_discover_dimension_candidates,
    tool_get_dimension_values,
    tool_run_metricflow_query,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]

mcp = FastMCP("commerce-analytics")


@mcp.tool()
def list_metrics() -> list[str]:
    """List all available MetricFlow metrics."""
    return get_available_metrics()


@mcp.tool()
def list_dimensions(metric_name: str) -> list[str]:
    """List dimensions available for a selected metric."""
    return get_metric_catalog_cached().get(metric_name, [])


@mcp.tool()
def semantic_search(
    query: str,
    object_type: str | None = None,
    metric_name: str | None = None,
    top_k: int = 8,
) -> dict[str, Any]:
    """Search metrics, dimensions, and relationships using natural language."""
    return search_semantic_layer(
        query=query,
        object_type=object_type,
        metric_name=metric_name,
        top_k=top_k,
    )


@mcp.tool()
def similar_dimensions(
    user_term: str,
    metric_name: str | None = None,
) -> dict[str, Any]:
    """Find likely dimensions for vague words like shop, area, city, vendor, or market."""
    return find_similar_dimensions(
        user_term=user_term,
        metric_name=metric_name,
    )




@mcp.tool()
def discover_dimension_candidates(
    user_term: str,
    metric_name: str | None = None,
    role: str = "any",
    limit_per_dimension: int = 20,
) -> dict[str, Any]:
    """Discover candidate semantic dimensions for a user term using names, semantic metadata, and values."""
    return tool_discover_dimension_candidates(
        user_term=user_term,
        metric_name=metric_name,
        role=role,
        limit_per_dimension=limit_per_dimension,
    )

@mcp.tool()
def get_dimension_values(
    dimension_name: str,
    limit: int = 100,
) -> list[Any]:
    """Return real warehouse values for a dimension."""
    return tool_get_dimension_values(
        dimension_name=dimension_name,
        limit=limit,
    )


@mcp.tool()
def run_metricflow_query(
    metrics: list[str],
    group_by: list[str] | None = None,
    filters: list[dict[str, Any]] | None = None,
    time_granularity: str | None = None,
    order_by: list[dict[str, Any]] | None = None,
    limit: int | None = None,
) -> dict[str, Any]:
    """Run a MetricFlow query using metrics, dimensions, filters, optional time grain, ordering, and limit."""
    return tool_run_metricflow_query(
        metrics=metrics,
        group_by=group_by or [],
        filters=filters or [],
        time_granularity=time_granularity,
        order_by=order_by or [],
        limit=limit,
    )


if __name__ == "__main__":
    mcp.run()