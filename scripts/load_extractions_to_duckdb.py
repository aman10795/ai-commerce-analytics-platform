import json
import uuid
import hashlib
from pathlib import Path
from datetime import datetime, timezone

import duckdb


PROJECT_ROOT = Path(__file__).resolve().parent.parent

RAW_JSON_DIR = PROJECT_ROOT / "data" / "raw_json" / "ai_extractions"

DB_DIR = PROJECT_ROOT / "data" / "warehouse"
DB_DIR.mkdir(parents=True, exist_ok=True)

DB_PATH = DB_DIR / "commerce_analytics.duckdb"

DUCKDB_ARTIFACTS_DIR = PROJECT_ROOT / "artifacts" / "duckdb_load"
LOAD_LOG_DIR = DUCKDB_ARTIFACTS_DIR / "logs"
FAILED_DIR = DUCKDB_ARTIFACTS_DIR / "failed"
VALIDATION_DIR = DUCKDB_ARTIFACTS_DIR / "validation"
DEBUG_DIR = DUCKDB_ARTIFACTS_DIR / "debug"


def now_utc():
    return datetime.now(timezone.utc)


def now_utc_iso():
    return datetime.now(timezone.utc).isoformat()


def json_hash(raw_data):
    canonical_json = json.dumps(raw_data, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()


def save_json(data, output_path):
    with open(output_path, "w", encoding="utf-8") as file:
        json.dump(data, file, indent=2, ensure_ascii=False, default=str)


def create_artifact_folders():
    LOAD_LOG_DIR.mkdir(parents=True, exist_ok=True)
    FAILED_DIR.mkdir(parents=True, exist_ok=True)
    VALIDATION_DIR.mkdir(parents=True, exist_ok=True)
    DEBUG_DIR.mkdir(parents=True, exist_ok=True)


def create_raw_tables(conn):
    conn.execute("CREATE SCHEMA IF NOT EXISTS raw;")

    conn.execute("""
        CREATE TABLE IF NOT EXISTS raw.raw_file_registry (
            pdf_hash VARCHAR PRIMARY KEY,
            current_json_hash VARCHAR,
            pdf_file_name VARCHAR,
            pdf_path VARCHAR,
            extraction_file_name VARCHAR,
            extraction_file_path VARCHAR,
            model_name VARCHAR,
            prompt_path VARCHAR,
            first_seen_at TIMESTAMP,
            last_loaded_at TIMESTAMP,
            load_count INTEGER
        );
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS raw.raw_ingestion_log (
            run_id VARCHAR,
            pdf_hash VARCHAR,
            json_hash VARCHAR,
            pdf_file_name VARCHAR,
            extraction_file_name VARCHAR,
            ingestion_status VARCHAR,
            error_message VARCHAR,
            loaded_at TIMESTAMP
        );
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS raw.raw_document_extractions (
            document_id VARCHAR PRIMARY KEY,
            run_id VARCHAR,
            pdf_hash VARCHAR,
            json_hash VARCHAR,
            pdf_file_name VARCHAR,
            pdf_path VARCHAR,
            extraction_file_name VARCHAR,
            extraction_file_path VARCHAR,
            loaded_at TIMESTAMP,
            raw_json JSON
        );
    """)


def load_extraction_json(file_path):
    with open(file_path, "r", encoding="utf-8") as file:
        raw_data = json.load(file)

    pipeline_metadata = raw_data.get("_pipeline_metadata", {})
    pdf_hash = pipeline_metadata.get("pdf_hash")

    if not pdf_hash:
        raise ValueError(f"Missing _pipeline_metadata.pdf_hash in {file_path.name}")

    current_json_hash = json_hash(raw_data)

    return raw_data, pipeline_metadata, pdf_hash, current_json_hash


def get_existing_registry_record(conn, pdf_hash):
    return conn.execute("""
        SELECT current_json_hash
        FROM raw.raw_file_registry
        WHERE pdf_hash = ?
    """, [pdf_hash]).fetchone()


def register_new_file(conn, file_path, pipeline_metadata, pdf_hash, current_json_hash, loaded_at):
    conn.execute("""
        INSERT INTO raw.raw_file_registry
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, [
        pdf_hash,
        current_json_hash,
        pipeline_metadata.get("pdf_file_name"),
        pipeline_metadata.get("pdf_path"),
        file_path.name,
        str(file_path),
        pipeline_metadata.get("model_name"),
        pipeline_metadata.get("prompt_path"),
        loaded_at,
        loaded_at,
        1,
    ])


def update_existing_file_registry(conn, file_path, pipeline_metadata, pdf_hash, current_json_hash, loaded_at):
    conn.execute("""
        UPDATE raw.raw_file_registry
        SET
            current_json_hash = ?,
            pdf_file_name = ?,
            pdf_path = ?,
            extraction_file_name = ?,
            extraction_file_path = ?,
            model_name = ?,
            prompt_path = ?,
            last_loaded_at = ?,
            load_count = load_count + 1
        WHERE pdf_hash = ?
    """, [
        current_json_hash,
        pipeline_metadata.get("pdf_file_name"),
        pipeline_metadata.get("pdf_path"),
        file_path.name,
        str(file_path),
        pipeline_metadata.get("model_name"),
        pipeline_metadata.get("prompt_path"),
        loaded_at,
        pdf_hash,
    ])


def log_ingestion(
    conn,
    run_id,
    pdf_hash,
    current_json_hash,
    pdf_file_name,
    extraction_file_name,
    status,
    error_message,
    loaded_at,
):
    conn.execute("""
        INSERT INTO raw.raw_ingestion_log
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, [
        run_id,
        pdf_hash,
        current_json_hash,
        pdf_file_name,
        extraction_file_name,
        status,
        error_message,
        loaded_at,
    ])


def upsert_raw_document_extraction(
    conn,
    run_id,
    file_path,
    raw_data,
    pipeline_metadata,
    pdf_hash,
    current_json_hash,
    loaded_at,
):
    document_id = pdf_hash[:16]

    conn.execute("""
        DELETE FROM raw.raw_document_extractions
        WHERE pdf_hash = ?
    """, [pdf_hash])

    conn.execute("""
        INSERT INTO raw.raw_document_extractions
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, [
        document_id,
        run_id,
        pdf_hash,
        current_json_hash,
        pipeline_metadata.get("pdf_file_name"),
        pipeline_metadata.get("pdf_path"),
        file_path.name,
        str(file_path),
        loaded_at,
        json.dumps(raw_data),
    ])


def create_failure_artifact(file_path, error, run_id, loaded_at):
    failed_payload = {
        "run_id": run_id,
        "extraction_file_name": file_path.name,
        "extraction_file_path": str(file_path),
        "status": "failed",
        "error_type": type(error).__name__,
        "error_message": str(error),
        "failed_at": loaded_at,
    }

    failed_path = FAILED_DIR / f"{file_path.stem}_failed.json"
    save_json(failed_payload, failed_path)

    return failed_path


def create_debug_artifact(file_path, error, run_id):
    debug_payload = {
        "run_id": run_id,
        "extraction_file_name": file_path.name,
        "extraction_file_path": str(file_path),
        "error_type": type(error).__name__,
        "error_message": str(error),
        "debug_created_at": now_utc_iso(),
        "debug_note": "This file failed during DuckDB raw ingestion. Check whether JSON is valid and contains _pipeline_metadata.pdf_hash.",
    }

    debug_path = DEBUG_DIR / f"{file_path.stem}_debug.json"
    save_json(debug_payload, debug_path)

    return debug_path


def load_json_file(conn, file_path, run_id):
    loaded_at = now_utc()

    result = {
        "run_id": run_id,
        "extraction_file_name": file_path.name,
        "extraction_file_path": str(file_path),
        "pdf_hash": None,
        "json_hash": None,
        "pdf_file_name": None,
        "status": None,
        "error_message": None,
        "loaded_at": loaded_at,
    }

    try:
        raw_data, pipeline_metadata, pdf_hash, current_json_hash = load_extraction_json(file_path)

        result["pdf_hash"] = pdf_hash
        result["json_hash"] = current_json_hash
        result["pdf_file_name"] = pipeline_metadata.get("pdf_file_name")

        existing_record = get_existing_registry_record(conn, pdf_hash)

        if existing_record and existing_record[0] == current_json_hash:
            status = "skipped_unchanged"

            log_ingestion(
                conn=conn,
                run_id=run_id,
                pdf_hash=pdf_hash,
                current_json_hash=current_json_hash,
                pdf_file_name=pipeline_metadata.get("pdf_file_name"),
                extraction_file_name=file_path.name,
                status=status,
                error_message=None,
                loaded_at=loaded_at,
            )

            result["status"] = status
            print(f"{status}: {file_path.name}", flush=True)
            return result

        if existing_record and existing_record[0] != current_json_hash:
            update_existing_file_registry(
                conn=conn,
                file_path=file_path,
                pipeline_metadata=pipeline_metadata,
                pdf_hash=pdf_hash,
                current_json_hash=current_json_hash,
                loaded_at=loaded_at,
            )

            upsert_raw_document_extraction(
                conn=conn,
                run_id=run_id,
                file_path=file_path,
                raw_data=raw_data,
                pipeline_metadata=pipeline_metadata,
                pdf_hash=pdf_hash,
                current_json_hash=current_json_hash,
                loaded_at=loaded_at,
            )

            status = "replaced_changed_extraction"

        else:
            register_new_file(
                conn=conn,
                file_path=file_path,
                pipeline_metadata=pipeline_metadata,
                pdf_hash=pdf_hash,
                current_json_hash=current_json_hash,
                loaded_at=loaded_at,
            )

            upsert_raw_document_extraction(
                conn=conn,
                run_id=run_id,
                file_path=file_path,
                raw_data=raw_data,
                pipeline_metadata=pipeline_metadata,
                pdf_hash=pdf_hash,
                current_json_hash=current_json_hash,
                loaded_at=loaded_at,
            )

            status = "inserted_new_document"

        log_ingestion(
            conn=conn,
            run_id=run_id,
            pdf_hash=pdf_hash,
            current_json_hash=current_json_hash,
            pdf_file_name=pipeline_metadata.get("pdf_file_name"),
            extraction_file_name=file_path.name,
            status=status,
            error_message=None,
            loaded_at=loaded_at,
        )

        result["status"] = status
        print(f"{status}: {file_path.name}", flush=True)
        return result

    except Exception as error:
        status = "failed"
        error_message = str(error)

        log_ingestion(
            conn=conn,
            run_id=run_id,
            pdf_hash=result.get("pdf_hash"),
            current_json_hash=result.get("json_hash"),
            pdf_file_name=result.get("pdf_file_name"),
            extraction_file_name=file_path.name,
            status=status,
            error_message=error_message,
            loaded_at=loaded_at,
        )

        failed_path = create_failure_artifact(file_path, error, run_id, loaded_at)
        debug_path = create_debug_artifact(file_path, error, run_id)

        result["status"] = status
        result["error_message"] = error_message
        result["failed_artifact_path"] = str(failed_path)
        result["debug_artifact_path"] = str(debug_path)

        print(f"Failed to load: {file_path.name}", flush=True)
        print(f"Error: {error}", flush=True)
        print(f"Failure artifact: {failed_path}", flush=True)
        print(f"Debug artifact: {debug_path}", flush=True)

        return result


def create_validation_report(conn, run_id, json_files, run_log):
    total_raw_records = conn.execute("""
        SELECT COUNT(*)
        FROM raw.raw_document_extractions
    """).fetchone()[0]

    missing_pdf_hash_count = conn.execute("""
        SELECT COUNT(*)
        FROM raw.raw_document_extractions
        WHERE pdf_hash IS NULL OR pdf_hash = ''
    """).fetchone()[0]

    missing_json_hash_count = conn.execute("""
        SELECT COUNT(*)
        FROM raw.raw_document_extractions
        WHERE json_hash IS NULL OR json_hash = ''
    """).fetchone()[0]

    duplicate_pdf_hash_count = conn.execute("""
        SELECT COUNT(*)
        FROM (
            SELECT pdf_hash
            FROM raw.raw_document_extractions
            GROUP BY pdf_hash
            HAVING COUNT(*) > 1
        )
    """).fetchone()[0]

    failed_count = sum(1 for row in run_log if row.get("status") == "failed")

    validation_report = {
        "run_id": run_id,
        "validated_at": now_utc_iso(),
        "source_file_count": len(json_files),
        "run_file_count": len(run_log),
        "warehouse_total_raw_records": total_raw_records,
        "missing_pdf_hash_count": missing_pdf_hash_count,
        "missing_json_hash_count": missing_json_hash_count,
        "duplicate_pdf_hash_count": duplicate_pdf_hash_count,
        "failed_count": failed_count,
        "validation_status": "passed"
    }

    if (
        missing_pdf_hash_count > 0
        or missing_json_hash_count > 0
        or duplicate_pdf_hash_count > 0
        or failed_count > 0
    ):
        validation_report["validation_status"] = "warning"

    return validation_report


def main():
    run_id = str(uuid.uuid4())

    print("Starting DuckDB raw ingestion pipeline...", flush=True)
    print(f"Run ID: {run_id}", flush=True)

    create_artifact_folders()

    conn = duckdb.connect(str(DB_PATH))

    print(f"Connected to DuckDB database: {DB_PATH}", flush=True)

    create_raw_tables(conn)

    json_files = sorted(RAW_JSON_DIR.glob("*.json"))

    print(f"Found {len(json_files)} raw AI extraction files.", flush=True)

    run_log = []

    for file_path in json_files:
        result = load_json_file(conn, file_path, run_id)
        run_log.append(result)

    summary = conn.execute("""
        SELECT ingestion_status, COUNT(*)
        FROM raw.raw_ingestion_log
        WHERE run_id = ?
        GROUP BY ingestion_status
        ORDER BY ingestion_status
    """, [run_id]).fetchall()

    total_records = conn.execute("""
        SELECT COUNT(*)
        FROM raw.raw_document_extractions
    """).fetchone()[0]

    validation_report = create_validation_report(
        conn=conn,
        run_id=run_id,
        json_files=json_files,
        run_log=run_log,
    )

    log_path = LOAD_LOG_DIR / f"duckdb_load_run_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    validation_path = VALIDATION_DIR / f"duckdb_load_validation_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"

    save_json(run_log, log_path)
    save_json(validation_report, validation_path)

    print("\nIngestion summary:", flush=True)

    for status, count in summary:
        print(f"{status}: {count}", flush=True)

    print(f"\nTotal records in raw_document_extractions: {total_records}", flush=True)
    print(f"Run log artifact saved to: {log_path}", flush=True)
    print(f"Validation artifact saved to: {validation_path}", flush=True)

    conn.close()

    print("DuckDB raw ingestion completed.", flush=True)


if __name__ == "__main__":
    main()