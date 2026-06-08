from __future__ import annotations

import os
import subprocess
from datetime import datetime

from airflow import DAG
from airflow.operators.python import PythonOperator


PROJECT_ROOT = "/Users/amansingh/Desktop/ai_commerce_analytics"
DBT_PROJECT_DIR = f"{PROJECT_ROOT}/commerce_analytics_dbt"
PROJECT_VENV_PYTHON = f"{PROJECT_ROOT}/venvwolt/bin/python"
PROJECT_VENV_DBT = f"{PROJECT_ROOT}/venvwolt/bin/dbt"


def run_command(command: list[str], cwd: str) -> None:
    result = subprocess.run(
        command,
        cwd=cwd,
        text=True,
        capture_output=True,
        check=False,
    )

    print(result.stdout)

    if result.returncode != 0:
        print(result.stderr)
        raise RuntimeError(f"Command failed: {' '.join(command)}")


def extract_invoices() -> None:
    run_command(
        [PROJECT_VENV_PYTHON, "scripts/extract_invoice.py"],
        cwd=PROJECT_ROOT,
    )


def load_to_duckdb() -> None:
    run_command(
        [PROJECT_VENV_PYTHON, "scripts/load_extractions_to_duckdb.py"],
        cwd=PROJECT_ROOT,
    )


def dbt_source_freshness() -> None:
    run_command(
        [PROJECT_VENV_DBT, "source", "freshness"],
        cwd=DBT_PROJECT_DIR,
    )


def dbt_run() -> None:
    run_command(
        [PROJECT_VENV_DBT, "run"],
        cwd=DBT_PROJECT_DIR,
    )


def dbt_test() -> None:
    run_command(
        [PROJECT_VENV_DBT, "test"],
        cwd=DBT_PROJECT_DIR,
    )


with DAG(
    dag_id="commerce_analytics_pipeline",
    description="End-to-end AI commerce analytics pipeline: extraction, loading, dbt transformations, and tests.",
    start_date=datetime(2026, 1, 1),
    schedule=None,
    catchup=False,
    tags=["commerce-analytics", "dbt", "duckdb", "ai-extraction"],
) as dag:

    extract_invoices_task = PythonOperator(
        task_id="extract_invoices",
        python_callable=extract_invoices,
    )

    load_to_duckdb_task = PythonOperator(
        task_id="load_to_duckdb",
        python_callable=load_to_duckdb,
    )

    dbt_source_freshness_task = PythonOperator(
        task_id="dbt_source_freshness",
        python_callable=dbt_source_freshness,
    )

    dbt_run_task = PythonOperator(
        task_id="dbt_run",
        python_callable=dbt_run,
    )

    dbt_test_task = PythonOperator(
        task_id="dbt_test",
        python_callable=dbt_test,
    )

    (
        extract_invoices_task
        >> load_to_duckdb_task
        >> dbt_source_freshness_task
        >> dbt_run_task
        >> dbt_test_task
    )