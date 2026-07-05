from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

OLD_INDEX_PATH = PROJECT_ROOT / "artifacts" / "semantic_index.json"
NEW_INDEX_DIR = PROJECT_ROOT / "artifacts" / "llamaindex_semantic_metadata"
DEFAULT_LOG_DIR = PROJECT_ROOT / "logs" / "retrieval_comparisons"

DEFAULT_QUERIES = [
    {
        "query": "top grocery items by spend",
        "expected_signals": [
            "item_total_spend",
            "order_line__item_name",
            "grocery",
            "top_grocery_items",
            "item_vs_category_grouping",
        ],
    },
    {
        "query": "money by shop",
        "expected_signals": [
            "total_spend",
            "merchant",
            "generic_spend_vs_item_spend",
        ],
    },
    {
        "query": "spend by month",
        "expected_signals": [
            "total_spend",
            "month",
            "calendar_grain_rule",
            "metric_time",
        ],
    },
    {
        "query": "monthly grocery spend in Berlin by merchant",
        "expected_signals": [
            "item_total_spend",
            "grocery",
            "Berlin",
            "merchant",
            "month",
        ],
    },
    {
        "query": "alcohol item spend",
        "expected_signals": [
            "item_total_spend",
            "alcohol",
            "order_line__item_name",
        ],
    },
    {
        "query": "orders in Berlin with alcohol",
        "expected_signals": [
            "order_count",
            "Berlin",
            "alcohol",
            "order__residence_city",
        ],
    },
    {
        "query": "discount ratio by city",
        "expected_signals": [
            "discount_ratio",
            "city",
            "order__residence_city",
        ],
    },
    {
        "query": "spend by career stage",
        "expected_signals": [
            "total_spend",
            "career_stage",
        ],
    },
    {
        "query": "item highest spend in Berlin",
        "expected_signals": [
            "item_total_spend",
            "order_line__item_name",
            "Berlin",
        ],
    },
    {
        "query": "compare alcohol spend vs grocery spend",
        "expected_signals": [
            "item_total_spend",
            "alcohol",
            "grocery",
        ],
    },
]


def compact_preview(value: Any, limit: int = 180) -> str:
    if value is None:
        return ""

    if not isinstance(value, str):
        value = json.dumps(value, default=str, ensure_ascii=False)

    preview = " ".join(value.split())

    if len(preview) <= limit:
        return preview

    return preview[: limit - 3] + "..."


def stringify_for_search(item: dict[str, Any]) -> str:
    searchable_values = [
        item.get("object_type"),
        item.get("name"),
        item.get("metric_name"),
        item.get("dimension_name"),
        item.get("value"),
        item.get("source"),
        item.get("preview"),
    ]

    return " ".join(
        str(value)
        for value in searchable_values
        if value is not None
    ).lower()


def normalize_old_results(raw_result: dict[str, Any], top_k: int) -> list[dict[str, Any]]:
    normalized = []

    for rank, item in enumerate(raw_result.get("matches", [])[:top_k], start=1):
        normalized.append(
            {
                "rank": rank,
                "object_type": item.get("type"),
                "name": item.get("name"),
                "metric_name": item.get("metric"),
                "dimension_name": item.get("dimension"),
                "value": None,
                "score": item.get("score"),
                "source": "artifacts/semantic_index.json",
                "preview": compact_preview(item.get("text")),
                "raw": item,
            }
        )

    return normalized


def normalize_new_results(raw_results: list[dict[str, Any]], top_k: int) -> list[dict[str, Any]]:
    normalized = []

    for rank, item in enumerate(raw_results[:top_k], start=1):
        sample_values = item.get("sample_values") or []
        value = sample_values[0] if sample_values else None
        preview_source = (
            item.get("description")
            or item.get("text_for_embedding")
            or item.get("metadata_json")
        )

        normalized.append(
            {
                "rank": rank,
                "object_type": item.get("object_type"),
                "name": item.get("name"),
                "metric_name": item.get("metric_name"),
                "dimension_name": item.get("dimension_name"),
                "value": value,
                "score": item.get("score"),
                "source": item.get("source"),
                "preview": compact_preview(preview_source),
                "raw": item,
            }
        )

    return normalized


def normalize_dimension_candidates(
    raw_results: list[dict[str, Any]],
    start_rank: int,
    top_k: int,
) -> list[dict[str, Any]]:
    normalized = []

    for offset, item in enumerate(raw_results[:top_k], start=0):
        sample_values = item.get("sample_values") or []
        value = sample_values[0] if sample_values else None
        normalized.append(
            {
                "rank": start_rank + offset,
                "object_type": f"dimension_candidate:{item.get('object_type')}",
                "name": item.get("name"),
                "metric_name": item.get("metric_name"),
                "dimension_name": item.get("dimension_name"),
                "value": value,
                "score": item.get("score"),
                "source": item.get("source"),
                "preview": compact_preview(
                    item.get("description") or item.get("text_for_embedding")
                ),
                "raw": item,
            }
        )

    return normalized


def signal_hits(
    expected_signals: list[str],
    results: list[dict[str, Any]],
) -> tuple[list[str], list[str]]:
    combined_text = "\n".join(stringify_for_search(item) for item in results)
    hits = []
    missing = []

    for signal in expected_signals:
        if signal.lower() in combined_text:
            hits.append(signal)
        else:
            missing.append(signal)

    return hits, missing


def run_old_retrieval(query: str, top_k: int) -> tuple[list[dict[str, Any]], str | None]:
    if not OLD_INDEX_PATH.exists():
        return [], "Old semantic index unavailable: artifacts/semantic_index.json is missing."

    from analytics.ai_metric_query import search_semantic_layer

    try:
        raw_result = search_semantic_layer(query=query, top_k=top_k)
    except Exception as exc:  # Keep comparison running when one retriever fails.
        return [], f"Old retrieval failed: {exc}"

    if raw_result.get("error"):
        return [], raw_result["error"]

    return normalize_old_results(raw_result, top_k), None


def run_new_retrieval(
    query: str,
    top_k: int,
    include_dimension_candidates: bool,
) -> tuple[list[dict[str, Any]], str | None]:
    if not NEW_INDEX_DIR.exists():
        return [], (
            "LlamaIndex semantic metadata index unavailable. Run: "
            "python scripts/agent/build_llamaindex_metadata.py"
        )

    from analytics.llamaindex_metadata_retriever import (
        retrieve_dimension_candidates,
        retrieve_semantic_objects,
    )

    try:
        raw_results = retrieve_semantic_objects(query=query, top_k=top_k)
        normalized = normalize_new_results(raw_results, top_k)

        if include_dimension_candidates:
            dimension_results = retrieve_dimension_candidates(
                user_term=query,
                top_k=top_k,
            )
            normalized.extend(
                normalize_dimension_candidates(
                    dimension_results,
                    start_rank=len(normalized) + 1,
                    top_k=top_k,
                )
            )

        return normalized, None
    except Exception as exc:
        return [], f"New retrieval failed: {exc}"


def winner_for_counts(old_hit_count: int, new_hit_count: int) -> str:
    if old_hit_count > new_hit_count:
        return "old"
    if new_hit_count > old_hit_count:
        return "new"
    return "tie"


def compare_query(
    query: str,
    expected_signals: list[str],
    top_k: int,
    include_dimension_candidates: bool,
) -> dict[str, Any]:
    old_results, old_error = run_old_retrieval(query=query, top_k=top_k)
    new_results, new_error = run_new_retrieval(
        query=query,
        top_k=top_k,
        include_dimension_candidates=include_dimension_candidates,
    )

    old_hits, old_missing = signal_hits(expected_signals, old_results)
    new_hits, new_missing = signal_hits(expected_signals, new_results)
    winner = winner_for_counts(len(old_hits), len(new_hits))

    return {
        "query": query,
        "expected_signals": expected_signals,
        "old_error": old_error,
        "new_error": new_error,
        "old_hits": old_hits,
        "new_hits": new_hits,
        "old_missing": old_missing,
        "new_missing": new_missing,
        "old_hit_count": len(old_hits),
        "new_hit_count": len(new_hits),
        "winner": winner,
        "old_results": old_results,
        "new_results": new_results,
    }


def query_specs_for_args(query: str | None) -> list[dict[str, Any]]:
    if not query:
        return DEFAULT_QUERIES

    for item in DEFAULT_QUERIES:
        if item["query"].lower() == query.lower():
            return [item]

    return [
        {
            "query": query,
            "expected_signals": [],
        }
    ]


def print_results_table(title: str, results: list[dict[str, Any]]) -> None:
    print(title)
    if not results:
        print("  (no results)")
        return

    for item in results:
        score = item.get("score")
        score_text = f"{score:.4f}" if isinstance(score, (int, float)) else str(score)
        print(
            "  "
            f"{item['rank']:>2}. "
            f"type={item.get('object_type') or ''} | "
            f"name={item.get('name') or ''} | "
            f"metric={item.get('metric_name') or ''} | "
            f"dimension={item.get('dimension_name') or ''} | "
            f"value={item.get('value') or ''} | "
            f"score={score_text} | "
            f"source={item.get('source') or ''}"
        )
        if item.get("preview"):
            print(f"      {item['preview']}")


def print_terminal_report(report: dict[str, Any]) -> None:
    for item in report["comparisons"]:
        print("=" * 100)
        print(f"Query: {item['query']}")
        print(f"Expected signals: {', '.join(item['expected_signals']) or '(none for custom query)'}")

        if item.get("old_error"):
            print(f"Old retrieval: {item['old_error']}")
        print(
            f"Old hits ({item['old_hit_count']}): "
            f"{', '.join(item['old_hits']) or '(none)'}"
        )
        print(f"Old missing: {', '.join(item['old_missing']) or '(none)'}")

        if item.get("new_error"):
            print(f"New retrieval: {item['new_error']}")
        print(
            f"New hits ({item['new_hit_count']}): "
            f"{', '.join(item['new_hits']) or '(none)'}"
        )
        print(f"New missing: {', '.join(item['new_missing']) or '(none)'}")
        print(f"Winner: {item['winner']}")
        print()

        print_results_table("Top old results:", item["old_results"])
        print()
        print_results_table("Top new results:", item["new_results"])
        print()


def make_json_safe(value: Any) -> Any:
    try:
        json.dumps(value, default=str)
        return value
    except TypeError:
        return str(value)


def write_json_report(report: dict[str, Any], output_path: Path | None) -> Path:
    if output_path is None:
        DEFAULT_LOG_DIR.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_path = (
            DEFAULT_LOG_DIR
            / f"metadata_retrieval_comparison_{timestamp}.json"
        )
    else:
        output_path.parent.mkdir(parents=True, exist_ok=True)

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False, default=make_json_safe)

    return output_path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Compare old custom semantic retrieval with new LlamaIndex metadata retrieval."
    )
    parser.add_argument("--query", help="Compare only this query.")
    parser.add_argument("--top-k", type=int, default=10, help="Number of results per retriever.")
    parser.add_argument("--json-only", action="store_true", help="Only write JSON; do not print full terminal report.")
    parser.add_argument(
        "--include-dimension-candidates",
        action="store_true",
        help="Also include retrieve_dimension_candidates results in the new result set.",
    )
    parser.add_argument("--output-path", type=Path, help="Optional JSON report path.")

    return parser.parse_args()


def main() -> None:
    args = parse_args()
    query_specs = query_specs_for_args(args.query)

    comparisons = [
        compare_query(
            query=item["query"],
            expected_signals=item["expected_signals"],
            top_k=args.top_k,
            include_dimension_candidates=args.include_dimension_candidates,
        )
        for item in query_specs
    ]
    report = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "top_k": args.top_k,
        "include_dimension_candidates": args.include_dimension_candidates,
        "old_index_path": str(OLD_INDEX_PATH),
        "new_index_dir": str(NEW_INDEX_DIR),
        "comparisons": comparisons,
    }

    output_path = write_json_report(report, args.output_path)

    if args.json_only:
        print(output_path)
    else:
        print_terminal_report(report)
        print(f"JSON report written to: {output_path}")


if __name__ == "__main__":
    main()
