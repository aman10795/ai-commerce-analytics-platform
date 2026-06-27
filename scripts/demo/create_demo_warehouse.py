import argparse
import json
from pathlib import Path
from typing import Any

import duckdb


PROJECT_ROOT = Path(__file__).resolve().parents[2]

DEFAULT_DB_PATH = PROJECT_ROOT / "data" / "warehouse" / "commerce_analytics_demo.duckdb"
DEFAULT_FIXTURE_PATH = PROJECT_ROOT / "data" / "demo" / "raw_document_extractions_demo.jsonl"


def normalize_raw_json(value: Any) -> str:
    if value is None:
        return "{}"

    if isinstance(value, str):
        try:
            json.loads(value)
            return value
        except json.JSONDecodeError:
            return json.dumps({"raw_text": value}, ensure_ascii=False)

    return json.dumps(value, ensure_ascii=False)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Create a fresh DuckDB demo warehouse from anonymized raw extraction fixture."
    )
    parser.add_argument(
        "--db-path",
        default=str(DEFAULT_DB_PATH),
        help="Path where the demo DuckDB database should be created.",
    )
    parser.add_argument(
        "--fixture-path",
        default=str(DEFAULT_FIXTURE_PATH),
        help="Path to the anonymized demo fixture JSONL.",
    )
    parser.add_argument(
        "--reset",
        action="store_true",
        help="Delete the existing DuckDB file before creating the demo warehouse.",
    )
    args = parser.parse_args()

    db_path = Path(args.db_path)
    fixture_path = Path(args.fixture_path)

    if not fixture_path.exists():
        raise FileNotFoundError(
            f"Demo fixture not found: {fixture_path}. "
            "Run scripts/export_raw_fixture.py and scripts/anonymize_raw_fixture.py first."
        )

    db_path.parent.mkdir(parents=True, exist_ok=True)

    if args.reset and db_path.exists():
        db_path.unlink()

    con = duckdb.connect(str(db_path))

    try:
        con.execute("create schema if not exists raw")

            
        con.execute("drop table if exists raw.raw_ingestion_log")
        con.execute("drop table if exists raw.raw_file_registry")
        con.execute("drop table if exists raw.raw_document_extractions")

        con.execute(
            """
            create table raw.raw_document_extractions (
                document_id varchar primary key,
                run_id varchar,
                pdf_hash varchar,
                json_hash varchar,
                pdf_file_name varchar,
                pdf_path varchar,
                extraction_file_name varchar,
                extraction_file_path varchar,
                loaded_at timestamp,
                raw_json json
            )
            """
        )

        con.execute(
            """
            create table raw.raw_file_registry (
                pdf_hash varchar primary key,
                pdf_file_name varchar,
                pdf_path varchar,
                current_json_hash varchar,
                first_seen_at timestamp,
                last_loaded_at timestamp
            )
            """
        )

        con.execute(
            """
            create table raw.raw_ingestion_log (
                run_id varchar,
                document_id varchar,
                pdf_hash varchar,
                json_hash varchar,
                pdf_file_name varchar,
                ingestion_status varchar,
                loaded_at timestamp
            )
            """
        )

        inserted_rows = 0

        with fixture_path.open("r", encoding="utf-8") as file:
            for line in file:
                if not line.strip():
                    continue

                record = json.loads(line)
                raw_json = normalize_raw_json(record.get("raw_json"))

                con.execute(
                    """
                    insert into raw.raw_document_extractions (
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
                    )
                    values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?::json)
                    """,
                    [
                        record.get("document_id"),
                        record.get("run_id"),
                        record.get("pdf_hash"),
                        record.get("json_hash"),
                        record.get("pdf_file_name"),
                        record.get("pdf_path"),
                        record.get("extraction_file_name"),
                        record.get("extraction_file_path"),
                        record.get("loaded_at"),
                        raw_json,
                    ],
                )
                con.execute(
                    """
                    insert or replace into raw.raw_file_registry (
                        pdf_hash,
                        pdf_file_name,
                        pdf_path,
                        current_json_hash,
                        first_seen_at,
                        last_loaded_at
                    )
                    values (?, ?, ?, ?, ?, ?)
                    """,
                    [
                        record.get("pdf_hash"),
                        record.get("pdf_file_name"),
                        record.get("pdf_path"),
                        record.get("json_hash"),
                        record.get("loaded_at"),
                        record.get("loaded_at"),
                    ],
                )

                con.execute(
                    """
                    insert into raw.raw_ingestion_log (
                        run_id,
                        document_id,
                        pdf_hash,
                        json_hash,
                        pdf_file_name,
                        ingestion_status,
                        loaded_at
                    )
                    values (?, ?, ?, ?, ?, ?, ?)
                    """,
                    [
                        record.get("run_id"),
                        record.get("document_id"),
                        record.get("pdf_hash"),
                        record.get("json_hash"),
                        record.get("pdf_file_name"),
                        "inserted_new_document",
                        record.get("loaded_at"),
                    ],
                )    
                

                inserted_rows += 1

        row_count = con.execute(
            "select count(*) from raw.raw_document_extractions"
        ).fetchone()[0]

    finally:
        con.close()

    print(f"Created demo warehouse at: {db_path}")
    print(f"Inserted fixture rows: {inserted_rows}")
    print(f"Rows in raw.raw_document_extractions: {row_count}")


if __name__ == "__main__":
    main()