import argparse
import json
from pathlib import Path
from typing import Any

import duckdb


PROJECT_ROOT = Path(__file__).resolve().parents[2]

DEFAULT_DB_PATH = PROJECT_ROOT / "data" / "warehouse" / "commerce_analytics.duckdb"
DEFAULT_OUTPUT_PATH = PROJECT_ROOT / "data" / "demo" / "raw_document_extractions_raw.jsonl"


COLUMNS = [
    "document_id",
    "run_id",
    "pdf_hash",
    "json_hash",
    "pdf_file_name",
    "pdf_path",
    "extraction_file_name",
    "extraction_file_path",
    "loaded_at",
    "raw_json",
]


def serialize_value(value: Any) -> Any:
    if value is None:
        return None

    if hasattr(value, "isoformat"):
        return value.isoformat()

    if isinstance(value, (dict, list)):
        return value

    return value


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Export raw.raw_document_extractions from DuckDB to a JSONL fixture."
    )
    parser.add_argument(
        "--db-path",
        default=str(DEFAULT_DB_PATH),
        help="Path to the source DuckDB database.",
    )
    parser.add_argument(
        "--output-path",
        default=str(DEFAULT_OUTPUT_PATH),
        help="Path to write the private raw JSONL fixture.",
    )
    args = parser.parse_args()

    db_path = Path(args.db_path)
    output_path = Path(args.output_path)

    if not db_path.exists():
        raise FileNotFoundError(f"DuckDB database not found: {db_path}")

    output_path.parent.mkdir(parents=True, exist_ok=True)

    con = duckdb.connect(str(db_path))

    try:
        rows = con.execute(
            """
            select
                document_id,
                run_id,
                pdf_hash,
                json_hash,
                pdf_file_name,
                pdf_path,
                extraction_file_name,
                extraction_file_path,
                loaded_at,
                raw_json
            from raw.raw_document_extractions
            order by loaded_at, document_id
            """
        ).fetchall()
    finally:
        con.close()

    with output_path.open("w", encoding="utf-8") as file:
        for row in rows:
            record = {
                column: serialize_value(value)
                for column, value in zip(COLUMNS, row)
            }

            raw_json = record.get("raw_json")

            if isinstance(raw_json, str):
                try:
                    record["raw_json"] = json.loads(raw_json)
                except json.JSONDecodeError:
                    record["raw_json"] = raw_json

            file.write(json.dumps(record, ensure_ascii=False) + "\n")

    print(f"Exported {len(rows)} rows")
    print(f"Private raw fixture written to: {output_path}")


if __name__ == "__main__":
    main()