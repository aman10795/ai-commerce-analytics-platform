import json
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv
from openai import OpenAI

from analytics.semantic_metadata import get_metric_catalog, list_metrics


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DBT_PROJECT_DIR = PROJECT_ROOT / "commerce_analytics_dbt"
MODELS_DIR = DBT_PROJECT_DIR / "models"
INDEX_PATH = PROJECT_ROOT / "artifacts" / "semantic_index.json"

load_dotenv(PROJECT_ROOT / ".env")

client = OpenAI()

EMBEDDING_MODEL = "text-embedding-3-small"


def get_embedding(text: str) -> list[float]:
    response = client.embeddings.create(
        model=EMBEDDING_MODEL,
        input=text,
    )
    return response.data[0].embedding


def readable_name(name: str) -> str:
    return name.replace("__", " ").replace("_", " ")


def load_yaml_files() -> list[dict[str, Any]]:
    yaml_files = [
        path
        for path in MODELS_DIR.rglob("*")
        if path.is_file() and path.suffix in {".yml", ".yaml"}
    ]

    parsed_files = []

    for file_path in yaml_files:
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f)

            if data:
                parsed_files.append(data)

        except yaml.YAMLError as exc:
            print(f"Skipping invalid YAML file: {file_path} | {exc}")

    return parsed_files


def extract_metric_descriptions() -> dict[str, str]:
    descriptions = {}

    for data in load_yaml_files():
        for metric in data.get("metrics", []):
            name = metric.get("name")
            description = metric.get("description", "")

            if name:
                descriptions[name] = description or ""

    return descriptions


def extract_dimension_descriptions() -> dict[str, str]:
    descriptions = {}

    for data in load_yaml_files():
        for semantic_model in data.get("semantic_models", []):
            semantic_model_name = semantic_model.get("name")

            for dimension in semantic_model.get("dimensions", []):
                dimension_name = dimension.get("name")
                description = dimension.get("description", "")

                if not semantic_model_name or not dimension_name:
                    continue

                full_dimension_name = f"{semantic_model_name}__{dimension_name}"
                descriptions[full_dimension_name] = description or ""

    return descriptions


def build_semantic_documents() -> list[dict]:
    metric_catalog = get_metric_catalog()
    metric_descriptions = extract_metric_descriptions()
    dimension_descriptions = extract_dimension_descriptions()

    documents = []

    for metric in list_metrics():
        description = metric_descriptions.get(metric, "")

        text = f"""
Semantic object type: metric
Metric name: {metric}
Readable name: {readable_name(metric)}
Description: {description}
Use this metric when the user asks about {readable_name(metric)}.
"""

        documents.append(
            {
                "type": "metric",
                "name": metric,
                "metrics": [metric],
                "description": description,
                "text": text.strip(),
            }
        )

    unique_dimensions = {}

    for metric, dimensions in metric_catalog.items():
        for dimension in dimensions:
            if dimension not in unique_dimensions:
                description = dimension_descriptions.get(dimension, "")

                unique_dimensions[dimension] = {
                    "type": "dimension",
                    "name": dimension,
                    "metrics": [],
                    "description": description,
                    "text": f"""
Semantic object type: dimension
Dimension name: {dimension}
Readable name: {readable_name(dimension)}
Description: {description}
Use this dimension when the user asks about {readable_name(dimension)}.
""".strip(),
                }

            unique_dimensions[dimension]["metrics"].append(metric)

    documents.extend(unique_dimensions.values())

    for metric, dimensions in metric_catalog.items():
        metric_description = metric_descriptions.get(metric, "")

        for dimension in dimensions:
            dimension_description = dimension_descriptions.get(dimension, "")

            text = f"""
Semantic object type: relationship
Metric {metric} can be grouped or filtered by dimension {dimension}.
Readable metric: {readable_name(metric)}
Metric description: {metric_description}
Readable dimension: {readable_name(dimension)}
Dimension description: {dimension_description}
"""

            documents.append(
                {
                    "type": "relationship",
                    "name": f"{metric}::{dimension}",
                    "metric": metric,
                    "dimension": dimension,
                    "metrics": [metric],
                    "metric_description": metric_description,
                    "dimension_description": dimension_description,
                    "text": text.strip(),
                }
            )

    return documents


def build_index() -> None:
    INDEX_PATH.parent.mkdir(parents=True, exist_ok=True)

    documents = build_semantic_documents()
    indexed_documents = []

    for doc in documents:
        embedding = get_embedding(doc["text"])

        indexed_documents.append(
            {
                **doc,
                "embedding": embedding,
            }
        )

        print(f"Embedded: {doc['type']} - {doc['name']}")

    with open(INDEX_PATH, "w", encoding="utf-8") as f:
        json.dump(indexed_documents, f, indent=2)

    print(f"\nSemantic index written to: {INDEX_PATH}")


if __name__ == "__main__":
    build_index()