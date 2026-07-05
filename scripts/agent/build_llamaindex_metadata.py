from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv


PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from analytics.ai_metric_query import (  # noqa: E402
    discover_dimension_source,
    get_available_dimensions,
    get_available_metrics,
    get_dimension_values,
    get_metric_catalog_cached,
    normalize_dimension_label,
)


DBT_MODELS_DIR = PROJECT_ROOT / "commerce_analytics_dbt" / "models"
BUSINESS_RULES_PATH = PROJECT_ROOT / "data" / "business_rules" / "semantic_business_rules.yml"
EVAL_CASES_PATH = PROJECT_ROOT / "evals" / "agent_metricflow_cases.yml"
METADATA_OBJECTS_PATH = PROJECT_ROOT / "artifacts" / "semantic_metadata_objects.jsonl"
INDEX_DIR = PROJECT_ROOT / "artifacts" / "llamaindex_semantic_metadata"

EMBEDDING_MODEL = "text-embedding-3-small"
USEFUL_SAMPLE_DIMENSIONS = [
    "order__residence_city",
    "order_line__residence_city",
    "order__merchant_name",
    "order_line__merchant_name",
    "merchant__merchant_name",
    "order__order_category",
    "order_line__order_category",
    "order_line__item_name",
    "order__payment_method",
    "order__source_platform",
]

SCHEMA_FIELDS = [
    "object_id",
    "object_type",
    "name",
    "title",
    "description",
    "source",
    "metric_name",
    "dimension_name",
    "model_name",
    "column_name",
    "grain",
    "semantic_roles",
    "valid_metrics",
    "valid_dimensions",
    "sample_values",
    "business_terms",
    "synonyms",
    "examples",
    "text_for_embedding",
    "metadata_json",
    "updated_at",
]


load_dotenv(PROJECT_ROOT / ".env")


def readable_name(name: str) -> str:
    return name.replace("__", " ").replace("_", " ")


def load_yaml_file(path: Path) -> dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def load_dbt_yaml_files() -> list[tuple[Path, dict[str, Any]]]:
    yaml_paths = sorted(
        path
        for path in DBT_MODELS_DIR.rglob("*")
        if path.is_file() and path.suffix in {".yml", ".yaml"}
    )

    loaded = []
    for path in yaml_paths:
        try:
            loaded.append((path, load_yaml_file(path)))
        except yaml.YAMLError as exc:
            print(f"Skipping invalid YAML file: {path} | {exc}")

    return loaded


def parse_ref_name(value: Any) -> str | None:
    if not isinstance(value, str):
        return None

    match = re.search(r"ref\(['\"]([^'\"]+)['\"]\)", value)
    if match:
        return match.group(1)

    return value.strip() or None


def get_primary_entity_name(semantic_model: dict[str, Any]) -> str | None:
    for entity in semantic_model.get("entities", []) or []:
        if entity.get("type") == "primary" and entity.get("name"):
            return entity["name"]

    return None


def make_metadata_object(
    *,
    object_id: str,
    object_type: str,
    name: str,
    updated_at: str,
    title: str | None = None,
    description: str | None = None,
    source: str | None = None,
    metric_name: str | None = None,
    dimension_name: str | None = None,
    model_name: str | None = None,
    column_name: str | None = None,
    grain: str | None = None,
    semantic_roles: list[str] | None = None,
    valid_metrics: list[str] | None = None,
    valid_dimensions: list[str] | None = None,
    sample_values: list[Any] | None = None,
    business_terms: list[str] | None = None,
    synonyms: Any = None,
    examples: list[Any] | None = None,
    text_for_embedding: str | None = None,
    metadata_json: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload = {
        "object_id": object_id,
        "object_type": object_type,
        "name": name,
        "title": title or readable_name(name),
        "description": description or "",
        "source": source or "",
        "metric_name": metric_name,
        "dimension_name": dimension_name,
        "model_name": model_name,
        "column_name": column_name,
        "grain": grain,
        "semantic_roles": semantic_roles or [],
        "valid_metrics": sorted(set(valid_metrics or [])),
        "valid_dimensions": sorted(set(valid_dimensions or [])),
        "sample_values": sample_values or [],
        "business_terms": business_terms or [],
        "synonyms": synonyms or {},
        "examples": examples or [],
        "metadata_json": metadata_json or {},
        "updated_at": updated_at,
    }
    payload["text_for_embedding"] = text_for_embedding or build_embedding_text(payload)

    return {field: payload.get(field) for field in SCHEMA_FIELDS}


def format_examples(examples: list[Any]) -> str:
    rendered = []
    for example in examples:
        if isinstance(example, dict):
            rendered.append(
                " | ".join(f"{key}: {value}" for key, value in example.items())
            )
        else:
            rendered.append(str(example))

    return "; ".join(rendered)


def build_embedding_text(obj: dict[str, Any]) -> str:
    parts = [
        f"Semantic object type: {obj.get('object_type')}",
        f"Name: {obj.get('name')}",
        f"Title: {obj.get('title')}",
        f"Description: {obj.get('description')}",
    ]

    for label, key in [
        ("Metric", "metric_name"),
        ("Dimension", "dimension_name"),
        ("Model", "model_name"),
        ("Column", "column_name"),
        ("Grain", "grain"),
    ]:
        if obj.get(key):
            parts.append(f"{label}: {obj[key]}")

    for label, key in [
        ("Semantic roles", "semantic_roles"),
        ("Valid metrics", "valid_metrics"),
        ("Valid dimensions", "valid_dimensions"),
        ("Sample values", "sample_values"),
        ("Business terms", "business_terms"),
    ]:
        values = obj.get(key) or []
        if values:
            parts.append(f"{label}: {', '.join(str(value) for value in values)}")

    if obj.get("synonyms"):
        parts.append(f"Synonyms: {json.dumps(obj['synonyms'], default=str)}")
    if obj.get("examples"):
        parts.append(f"Examples: {format_examples(obj['examples'])}")

    return "\n".join(part for part in parts if part and not part.endswith(": "))


def collect_semantic_yaml_metadata(
    dbt_yaml_files: list[tuple[Path, dict[str, Any]]],
) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    metric_metadata: dict[str, dict[str, Any]] = {}
    dimension_metadata: dict[str, dict[str, Any]] = {}

    for path, data in dbt_yaml_files:
        source = str(path.relative_to(PROJECT_ROOT))

        for metric in data.get("metrics", []) or []:
            name = metric.get("name")
            if not name:
                continue

            metric_metadata[name] = {
                "title": metric.get("label") or readable_name(name),
                "description": metric.get("description") or "",
                "source": source,
                "metadata": metric,
            }

        for semantic_model in data.get("semantic_models", []) or []:
            semantic_model_name = semantic_model.get("name")
            primary_entity_name = get_primary_entity_name(semantic_model)
            model_name = parse_ref_name(semantic_model.get("model"))

            for dimension in semantic_model.get("dimensions", []) or []:
                dimension_name = dimension.get("name")
                if not semantic_model_name or not dimension_name:
                    continue

                prefixes = [semantic_model_name]
                if primary_entity_name:
                    prefixes.append(primary_entity_name)

                for prefix in prefixes:
                    full_name = f"{prefix}__{dimension_name}"
                    dimension_metadata[full_name] = {
                        "title": readable_name(full_name),
                        "description": dimension.get("description") or "",
                        "source": source,
                        "model_name": model_name,
                        "column_name": dimension.get("expr") or dimension_name,
                        "grain": (
                            (dimension.get("type_params") or {}).get("time_granularity")
                            if dimension.get("type") == "time"
                            else None
                        ),
                        "semantic_roles": [dimension.get("type") or "dimension"],
                        "metadata": {
                            "semantic_model": semantic_model_name,
                            "primary_entity": primary_entity_name,
                            "dimension": dimension,
                        },
                    }

    return metric_metadata, dimension_metadata


def collect_dbt_model_docs(
    dbt_yaml_files: list[tuple[Path, dict[str, Any]]],
) -> tuple[dict[str, dict[str, Any]], dict[tuple[str, str], dict[str, Any]]]:
    models: dict[str, dict[str, Any]] = {}
    columns: dict[tuple[str, str], dict[str, Any]] = {}

    for path, data in dbt_yaml_files:
        source = str(path.relative_to(PROJECT_ROOT))

        for model in data.get("models", []) or []:
            model_name = model.get("name")
            if not model_name:
                continue

            models[model_name] = {
                "description": model.get("description") or "",
                "source": source,
                "metadata": model,
            }

            for column in model.get("columns", []) or []:
                column_name = column.get("name")
                if not column_name:
                    continue

                columns[(model_name, column_name)] = {
                    "description": column.get("description") or "",
                    "source": source,
                    "metadata": column,
                }

    return models, columns


def semantic_dimensions_by_column(
    dimensions: list[str],
    dimension_metadata: dict[str, dict[str, Any]],
) -> dict[str, list[str]]:
    by_column: dict[str, list[str]] = {}

    for dimension in dimensions:
        suffix = dimension.split("__")[-1]
        by_column.setdefault(suffix, []).append(dimension)

        column_name = dimension_metadata.get(dimension, {}).get("column_name")
        if column_name:
            by_column.setdefault(str(column_name), []).append(dimension)

    return {key: sorted(set(value)) for key, value in by_column.items()}


def build_metricflow_objects(
    *,
    metric_catalog: dict[str, list[str]],
    metric_metadata: dict[str, dict[str, Any]],
    dimension_metadata: dict[str, dict[str, Any]],
    updated_at: str,
) -> list[dict[str, Any]]:
    objects = []
    metrics = get_available_metrics()
    dimensions = get_available_dimensions()

    for metric in metrics:
        metadata = metric_metadata.get(metric, {})
        valid_dimensions = metric_catalog.get(metric, [])
        objects.append(
            make_metadata_object(
                object_id=f"metric:{metric}",
                object_type="metric",
                name=metric,
                title=metadata.get("title"),
                description=metadata.get("description"),
                source=metadata.get("source") or "MetricFlow",
                metric_name=metric,
                valid_metrics=[metric],
                valid_dimensions=valid_dimensions,
                semantic_roles=["metric"],
                metadata_json=metadata.get("metadata", {}),
                updated_at=updated_at,
            )
        )

    for dimension in dimensions:
        metadata = dimension_metadata.get(dimension, {})
        valid_metrics = [
            metric
            for metric, metric_dimensions in metric_catalog.items()
            if dimension in metric_dimensions
        ]
        objects.append(
            make_metadata_object(
                object_id=f"dimension:{dimension}",
                object_type="dimension",
                name=dimension,
                title=metadata.get("title") or readable_name(dimension),
                description=metadata.get("description"),
                source=metadata.get("source") or "MetricFlow",
                dimension_name=dimension,
                model_name=metadata.get("model_name"),
                column_name=metadata.get("column_name") or dimension.split("__")[-1],
                grain=metadata.get("grain"),
                semantic_roles=metadata.get("semantic_roles") or ["dimension"],
                valid_metrics=valid_metrics,
                valid_dimensions=[dimension],
                metadata_json=metadata.get("metadata", {}),
                updated_at=updated_at,
            )
        )

    for metric, metric_dimensions in metric_catalog.items():
        metric_info = metric_metadata.get(metric, {})
        for dimension in metric_dimensions:
            dimension_info = dimension_metadata.get(dimension, {})
            description = (
                f"Metric {metric} can be grouped or filtered by dimension {dimension}."
            )
            text = "\n".join(
                [
                    "Semantic object type: relationship",
                    description,
                    f"Readable metric: {readable_name(metric)}",
                    f"Metric description: {metric_info.get('description') or ''}",
                    f"Readable dimension: {normalize_dimension_label(dimension)}",
                    f"Dimension description: {dimension_info.get('description') or ''}",
                ]
            )
            objects.append(
                make_metadata_object(
                    object_id=f"relationship:{metric}::{dimension}",
                    object_type="relationship",
                    name=f"{metric}::{dimension}",
                    title=f"{readable_name(metric)} by {readable_name(dimension)}",
                    description=description,
                    source="MetricFlow",
                    metric_name=metric,
                    dimension_name=dimension,
                    model_name=dimension_info.get("model_name"),
                    column_name=dimension_info.get("column_name") or dimension.split("__")[-1],
                    grain=dimension_info.get("grain"),
                    semantic_roles=["metric_dimension_relationship"],
                    valid_metrics=[metric],
                    valid_dimensions=[dimension],
                    text_for_embedding=text,
                    metadata_json={
                        "metric_description": metric_info.get("description") or "",
                        "dimension_description": dimension_info.get("description") or "",
                    },
                    updated_at=updated_at,
                )
            )

    return objects


def build_dbt_doc_objects(
    *,
    dbt_models: dict[str, dict[str, Any]],
    dbt_columns: dict[tuple[str, str], dict[str, Any]],
    dimensions_by_column: dict[str, list[str]],
    updated_at: str,
) -> list[dict[str, Any]]:
    objects = []

    for model_name, model_info in sorted(dbt_models.items()):
        objects.append(
            make_metadata_object(
                object_id=f"dbt_model:{model_name}",
                object_type="dbt_model",
                name=model_name,
                title=readable_name(model_name),
                description=model_info.get("description"),
                source=model_info.get("source"),
                model_name=model_name,
                semantic_roles=["dbt_model"],
                metadata_json=model_info.get("metadata", {}),
                updated_at=updated_at,
            )
        )

    for (model_name, column_name), column_info in sorted(dbt_columns.items()):
        linked_dimensions = dimensions_by_column.get(column_name, [])
        objects.append(
            make_metadata_object(
                object_id=f"dbt_column:{model_name}.{column_name}",
                object_type="dbt_column",
                name=f"{model_name}.{column_name}",
                title=f"{readable_name(model_name)} {readable_name(column_name)}",
                description=column_info.get("description"),
                source=column_info.get("source"),
                model_name=model_name,
                column_name=column_name,
                semantic_roles=["dbt_column"],
                valid_dimensions=linked_dimensions,
                metadata_json={
                    "column": column_info.get("metadata", {}),
                    "linked_semantic_dimensions": linked_dimensions,
                },
                updated_at=updated_at,
            )
        )

    return objects


def build_dimension_value_objects(
    *,
    metric_catalog: dict[str, list[str]],
    updated_at: str,
    sample_limit: int = 40,
) -> list[dict[str, Any]]:
    objects = []

    for dimension in USEFUL_SAMPLE_DIMENSIONS:
        source = discover_dimension_source(dimension)
        sample_values = get_dimension_values(dimension, limit=sample_limit) if source else []
        valid_metrics = [
            metric
            for metric, dimensions in metric_catalog.items()
            if dimension in dimensions
        ]

        if not source and not valid_metrics:
            continue

        source_text = (
            f"DuckDB marts.{source[0]}.{source[1]}"
            if source
            else "MetricFlow dimension"
        )
        text = "\n".join(
            [
                "Semantic object type: dimension_value",
                f"Dimension: {dimension}",
                f"Readable dimension: {normalize_dimension_label(dimension)}",
                f"Sample values: {', '.join(str(value) for value in sample_values)}",
                f"Use these values to resolve filters for {readable_name(dimension)}.",
            ]
        )

        objects.append(
            make_metadata_object(
                object_id=f"dimension_value:{dimension}",
                object_type="dimension_value",
                name=f"{dimension}:values",
                title=f"{readable_name(dimension)} sample values",
                description=f"Distinct sample values for semantic dimension {dimension}.",
                source=source_text,
                dimension_name=dimension,
                model_name=source[0] if source else None,
                column_name=source[1] if source else dimension.split("__")[-1],
                semantic_roles=["dimension_value", "filter_resolution"],
                valid_metrics=valid_metrics,
                valid_dimensions=[dimension],
                sample_values=sample_values,
                text_for_embedding=text,
                metadata_json={"duckdb_source": source},
                updated_at=updated_at,
            )
        )

    return objects


def build_query_example_objects(updated_at: str) -> list[dict[str, Any]]:
    if not EVAL_CASES_PATH.exists():
        return []

    data = load_yaml_file(EVAL_CASES_PATH)
    cases = data if isinstance(data, list) else data.get("cases", [])
    objects = []

    for case in cases or []:
        case_id = case.get("id")
        question = case.get("question")
        if not case_id or not question:
            continue

        expected = case.get("expected") or {}
        metrics = expected.get("metrics") or []
        valid_dimensions = []
        valid_dimensions.extend(expected.get("group_by") or [])
        for group_options in expected.get("group_by_any_of") or []:
            valid_dimensions.extend(group_options or [])
        for filter_item in expected.get("filters") or []:
            if filter_item.get("dimension"):
                valid_dimensions.append(filter_item["dimension"])
            valid_dimensions.extend(filter_item.get("dimension_any_of") or [])

        text = "\n".join(
            [
                "Semantic object type: query_example",
                f"Example id: {case_id}",
                f"Question: {question}",
                f"Reason: {case.get('reason') or ''}",
                f"Expected metrics: {', '.join(str(metric) for metric in metrics)}",
                f"Expected dimensions: {', '.join(str(dim) for dim in valid_dimensions)}",
                f"Expected plan: {json.dumps(expected, default=str)}",
            ]
        )

        objects.append(
            make_metadata_object(
                object_id=f"query_example:{case_id}",
                object_type="query_example",
                name=case_id,
                title=question,
                description=case.get("reason") or "",
                source=str(EVAL_CASES_PATH.relative_to(PROJECT_ROOT)),
                valid_metrics=metrics,
                valid_dimensions=valid_dimensions,
                examples=[{"question": question, "expected": expected}],
                text_for_embedding=text,
                metadata_json=case,
                updated_at=updated_at,
            )
        )

    return objects


def build_business_rule_objects(updated_at: str) -> list[dict[str, Any]]:
    if not BUSINESS_RULES_PATH.exists():
        return []

    data = load_yaml_file(BUSINESS_RULES_PATH)
    rules = data.get("rules", [])
    objects = []

    for rule in rules or []:
        rule_id = rule.get("id")
        if not rule_id:
            continue

        objects.append(
            make_metadata_object(
                object_id=f"business_rule:{rule_id}",
                object_type="business_rule",
                name=rule_id,
                title=rule.get("title") or readable_name(rule_id),
                description=rule.get("description") or "",
                source=str(BUSINESS_RULES_PATH.relative_to(PROJECT_ROOT)),
                semantic_roles=["business_rule"],
                valid_metrics=rule.get("valid_metrics") or [],
                valid_dimensions=rule.get("valid_dimensions") or [],
                business_terms=rule.get("business_terms") or [],
                synonyms=rule.get("synonyms") or {},
                examples=rule.get("examples") or [],
                metadata_json=rule,
                updated_at=updated_at,
            )
        )

    return objects


def dedupe_objects(objects: list[dict[str, Any]]) -> list[dict[str, Any]]:
    deduped: dict[str, dict[str, Any]] = {}
    for obj in objects:
        deduped[obj["object_id"]] = obj

    return list(deduped.values())


def build_metadata_objects() -> list[dict[str, Any]]:
    updated_at = datetime.now().isoformat(timespec="seconds")
    dbt_yaml_files = load_dbt_yaml_files()
    metric_metadata, dimension_metadata = collect_semantic_yaml_metadata(dbt_yaml_files)
    dbt_models, dbt_columns = collect_dbt_model_docs(dbt_yaml_files)
    metric_catalog = get_metric_catalog_cached()
    dimensions = get_available_dimensions()
    dimensions_by_column = semantic_dimensions_by_column(dimensions, dimension_metadata)

    objects = []
    objects.extend(
        build_metricflow_objects(
            metric_catalog=metric_catalog,
            metric_metadata=metric_metadata,
            dimension_metadata=dimension_metadata,
            updated_at=updated_at,
        )
    )
    objects.extend(
        build_dbt_doc_objects(
            dbt_models=dbt_models,
            dbt_columns=dbt_columns,
            dimensions_by_column=dimensions_by_column,
            updated_at=updated_at,
        )
    )
    objects.extend(
        build_dimension_value_objects(
            metric_catalog=metric_catalog,
            updated_at=updated_at,
        )
    )
    objects.extend(build_query_example_objects(updated_at=updated_at))
    objects.extend(build_business_rule_objects(updated_at=updated_at))

    return dedupe_objects(objects)


def write_metadata_objects(objects: list[dict[str, Any]]) -> None:
    METADATA_OBJECTS_PATH.parent.mkdir(parents=True, exist_ok=True)

    with open(METADATA_OBJECTS_PATH, "w", encoding="utf-8") as f:
        for obj in objects:
            f.write(json.dumps(obj, ensure_ascii=False, default=str) + "\n")


def metadata_for_llamaindex(obj: dict[str, Any]) -> dict[str, Any]:
    metadata = {}
    for key, value in obj.items():
        if key == "text_for_embedding":
            continue
        if isinstance(value, (dict, list)):
            metadata[key] = json.dumps(value, ensure_ascii=False, default=str)
        elif value is None:
            metadata[key] = ""
        else:
            metadata[key] = value

    return metadata


def build_llamaindex(objects: list[dict[str, Any]]) -> None:
    try:
        from llama_index.core import Document, Settings, VectorStoreIndex
        from llama_index.embeddings.openai import OpenAIEmbedding
    except ImportError as exc:  # pragma: no cover - environment guard
        raise SystemExit(
            "LlamaIndex dependencies are missing. Install requirements.txt first."
        ) from exc

    Settings.embed_model = OpenAIEmbedding(model=EMBEDDING_MODEL)

    documents = [
        Document(
            text=obj["text_for_embedding"],
            metadata=metadata_for_llamaindex(obj),
        )
        for obj in objects
    ]
    index = VectorStoreIndex.from_documents(documents)
    index.storage_context.persist(persist_dir=str(INDEX_DIR))


def build_artifacts() -> list[dict[str, Any]]:
    objects = build_metadata_objects()
    write_metadata_objects(objects)
    build_llamaindex(objects)

    print(f"Metadata objects written to: {METADATA_OBJECTS_PATH}")
    print(f"LlamaIndex metadata index written to: {INDEX_DIR}")
    print(f"Object count: {len(objects)}")

    return objects


def print_retrieval_results(
    *,
    query: str,
    object_type: str | None,
    metric_name: str | None,
    top_k: int,
) -> None:
    from analytics.llamaindex_metadata_retriever import retrieve_semantic_objects

    results = retrieve_semantic_objects(
        query=query,
        object_type=object_type,
        metric_name=metric_name,
        top_k=top_k,
    )

    print(f"\nRetrieval results for: {query}")
    for index, result in enumerate(results, start=1):
        print(
            json.dumps(
                {
                    "rank": index,
                    "score": result.get("score"),
                    "object_type": result.get("object_type"),
                    "name": result.get("name"),
                    "metric_name": result.get("metric_name"),
                    "dimension_name": result.get("dimension_name"),
                    "title": result.get("title"),
                    "valid_metrics": result.get("valid_metrics"),
                    "valid_dimensions": result.get("valid_dimensions"),
                    "sample_values": result.get("sample_values"),
                },
                indent=2,
                ensure_ascii=False,
                default=str,
            )
        )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Build structured analytics metadata and a LlamaIndex metadata index. "
            "This does not replace MetricFlow query execution."
        )
    )
    parser.add_argument("--query", help="Optional smoke-test retrieval query.")
    parser.add_argument("--object-type", help="Optional metadata object type filter.")
    parser.add_argument("--metric-name", help="Optional MetricFlow metric filter.")
    parser.add_argument("--top-k", type=int, default=10, help="Number of results to print.")

    return parser.parse_args()


def main() -> None:
    args = parse_args()
    build_artifacts()

    if args.query:
        print_retrieval_results(
            query=args.query,
            object_type=args.object_type,
            metric_name=args.metric_name,
            top_k=args.top_k,
        )


if __name__ == "__main__":
    main()
