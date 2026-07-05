from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from dotenv import load_dotenv


PROJECT_ROOT = Path(__file__).resolve().parents[1]
INDEX_DIR = PROJECT_ROOT / "artifacts" / "llamaindex_semantic_metadata"
METADATA_OBJECTS_PATH = PROJECT_ROOT / "artifacts" / "semantic_metadata_objects.jsonl"

load_dotenv(PROJECT_ROOT / ".env")

_METADATA_INDEX: Any | None = None
_METADATA_OBJECTS: list[dict[str, Any]] | None = None


def _import_llamaindex() -> tuple[Any, Any]:
    try:
        from llama_index.core import StorageContext, load_index_from_storage
    except ImportError as exc:  # pragma: no cover - environment guard
        raise RuntimeError(
            "LlamaIndex is required for semantic metadata retrieval. "
            "Install project dependencies from requirements.txt."
        ) from exc

    return StorageContext, load_index_from_storage


def load_metadata_index() -> Any:
    """Load the persisted metadata index lazily.

    LlamaIndex is the metadata retrieval layer only. It does not execute
    analytics queries; MetricFlow remains the query execution layer.
    """
    global _METADATA_INDEX

    if _METADATA_INDEX is not None:
        return _METADATA_INDEX

    if not INDEX_DIR.exists():
        raise FileNotFoundError(
            "LlamaIndex semantic metadata index not found. Run "
            "python scripts/agent/build_llamaindex_metadata.py first."
        )

    StorageContext, load_index_from_storage = _import_llamaindex()
    storage_context = StorageContext.from_defaults(persist_dir=str(INDEX_DIR))
    _METADATA_INDEX = load_index_from_storage(storage_context)

    return _METADATA_INDEX


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def _load_metadata_objects() -> list[dict[str, Any]]:
    global _METADATA_OBJECTS

    if _METADATA_OBJECTS is not None:
        return _METADATA_OBJECTS

    if not METADATA_OBJECTS_PATH.exists():
        _METADATA_OBJECTS = []
        return _METADATA_OBJECTS

    objects = []
    with open(METADATA_OBJECTS_PATH, "r", encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            objects.append(json.loads(line))

    _METADATA_OBJECTS = objects
    return _METADATA_OBJECTS


def _metadata_value(metadata: dict[str, Any], key: str, default: Any = None) -> Any:
    value = metadata.get(key, default)

    if isinstance(value, str) and value[:1] in {"[", "{"}:
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return value

    return value


def _result_from_node(node_with_score: Any) -> dict[str, Any]:
    node = node_with_score.node
    metadata = dict(getattr(node, "metadata", {}) or {})
    metadata_json = _metadata_value(metadata, "metadata_json", {})

    if not isinstance(metadata_json, dict):
        metadata_json = {}

    result = {
        "score": getattr(node_with_score, "score", None),
        "text_for_embedding": getattr(node, "text", "") or "",
        "metadata_json": metadata_json,
    }

    for key, value in metadata.items():
        result[key] = _metadata_value(metadata, key, value)

    return result


def _matches_object_type(result: dict[str, Any], object_type: str | None) -> bool:
    if not object_type:
        return True

    return result.get("object_type") == object_type


def _matches_metric_name(result: dict[str, Any], metric_name: str | None) -> bool:
    if not metric_name:
        return True

    valid_metrics = set(str(item) for item in _as_list(result.get("valid_metrics")))
    metric_value = result.get("metric_name")

    return metric_value == metric_name or metric_name in valid_metrics


def _searchable_text(result: dict[str, Any]) -> str:
    values = [
        result.get("object_id"),
        result.get("object_type"),
        result.get("name"),
        result.get("title"),
        result.get("description"),
        result.get("metric_name"),
        result.get("dimension_name"),
        result.get("model_name"),
        result.get("column_name"),
        result.get("text_for_embedding"),
        " ".join(str(item) for item in _as_list(result.get("business_terms"))),
        " ".join(str(item) for item in _as_list(result.get("sample_values"))),
        json.dumps(result.get("synonyms") or {}, default=str),
        json.dumps(result.get("examples") or [], default=str),
    ]

    return " ".join(str(value) for value in values if value).lower()


def _rerank_score(query: str, result: dict[str, Any]) -> float:
    base_score = result.get("score")
    try:
        score = float(base_score or 0)
    except (TypeError, ValueError):
        score = 0.0

    normalized_query = query.strip().lower()
    query_tokens = {
        token
        for token in re.split(r"[^a-z0-9_]+", normalized_query)
        if len(token) >= 3
    }
    searchable = _searchable_text(result)

    if normalized_query and normalized_query in searchable:
        score += 0.35

    token_hits = sum(1 for token in query_tokens if token in searchable)
    score += min(token_hits * 0.025, 0.2)

    object_type = result.get("object_type")
    metric_name = str(result.get("metric_name") or result.get("name") or "")
    dimension_name = str(result.get("dimension_name") or result.get("name") or "")

    item_terms = {"item", "items", "product", "products"}
    merchant_terms = {"shop", "store", "vendor", "merchant", "restaurant"}
    spend_terms = {"spend", "money", "paid", "expenses", "cost"}

    if query_tokens & item_terms:
        if metric_name == "item_total_spend":
            score += 0.15
        if dimension_name.endswith("__item_name"):
            score += 0.2
        if object_type == "business_rule" and "item" in searchable:
            score += 0.12

    if query_tokens & merchant_terms and "merchant_name" in dimension_name:
        score += 0.18

    if query_tokens & spend_terms:
        if metric_name == "total_spend" and not (query_tokens & item_terms):
            score += 0.12
            if object_type == "metric":
                score += 0.4
        if metric_name == "item_total_spend" and query_tokens & item_terms:
            score += 0.12

    if "grocery" in query_tokens and "grocery" in searchable:
        score += 0.08
        if object_type == "dimension_value":
            score += 1.2

    if object_type == "query_example":
        score += 0.08
    if object_type == "business_rule":
        score += 0.08

    return score


def retrieve_semantic_objects(
    query: str,
    object_type: str | None = None,
    metric_name: str | None = None,
    top_k: int = 10,
) -> list[dict[str, Any]]:
    """Retrieve analytics metadata objects from the persisted LlamaIndex index."""
    index = load_metadata_index()
    retriever = index.as_retriever(similarity_top_k=max(top_k * 12, top_k))
    raw_results = retriever.retrieve(query)

    filtered_results: list[dict[str, Any]] = []
    seen_object_ids: set[str] = set()
    for raw_result in raw_results:
        result = _result_from_node(raw_result)
        if not _matches_object_type(result, object_type):
            continue
        if not _matches_metric_name(result, metric_name):
            continue
        result["rerank_score"] = _rerank_score(query, result)
        filtered_results.append(result)
        if result.get("object_id"):
            seen_object_ids.add(str(result["object_id"]))

    query_tokens = {
        token
        for token in re.split(r"[^a-z0-9_]+", query.strip().lower())
        if len(token) >= 3
    }
    for result in _load_metadata_objects():
        object_id = str(result.get("object_id") or "")
        if object_id in seen_object_ids:
            continue
        if not _matches_object_type(result, object_type):
            continue
        if not _matches_metric_name(result, metric_name):
            continue

        searchable = _searchable_text(result)
        if not any(token in searchable for token in query_tokens):
            continue

        result = dict(result)
        result["score"] = result.get("score")
        result["rerank_score"] = _rerank_score(query, result)
        filtered_results.append(result)
        seen_object_ids.add(object_id)

    return sorted(
        filtered_results,
        key=lambda item: item.get("rerank_score") or item.get("score") or 0,
        reverse=True,
    )[:top_k]


def retrieve_dimension_candidates(
    user_term: str,
    metric_name: str | None = None,
    role: str | None = None,
    top_k: int = 10,
) -> list[dict[str, Any]]:
    """Retrieve likely dimension metadata for a user term.

    This is metadata discovery only. The caller must still validate dimensions
    with MetricFlow before executing a query.
    """
    query_parts = [user_term, role or "", metric_name or ""]
    query = " ".join(part for part in query_parts if part)
    allowed_types = {"dimension", "relationship", "dimension_value", "business_rule"}

    candidates = []
    for result in retrieve_semantic_objects(
        query=query,
        metric_name=metric_name,
        top_k=max(top_k * 4, top_k),
    ):
        if result.get("object_type") not in allowed_types:
            continue
        candidates.append(result)

        if len(candidates) >= top_k:
            break

    return candidates


def retrieve_query_examples(question: str, top_k: int = 3) -> list[dict[str, Any]]:
    """Retrieve similar eval/query examples from the metadata index."""
    return retrieve_semantic_objects(
        query=question,
        object_type="query_example",
        top_k=top_k,
    )
