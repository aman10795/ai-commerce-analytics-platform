import os
import re
import subprocess
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DBT_PROJECT_DIR = PROJECT_ROOT / "commerce_analytics_dbt"


def run_mf_command(command: list[str]) -> str:
    env = os.environ.copy()
    env["DBT_PROFILES_DIR"] = str(Path.home() / ".dbt")

    result = subprocess.run(
        command,
        cwd=DBT_PROJECT_DIR,
        env=env,
        text=True,
        capture_output=True,
    )

    if result.returncode != 0:
        raise RuntimeError(result.stderr)

    return result.stdout


def list_metrics() -> list[str]:
    output = run_mf_command(["mf", "list", "metrics"])

    metrics = []

    for line in output.splitlines():
        line = line.strip()

        match = re.match(r"^•\s*([a-zA-Z0-9_]+):", line)

        if match:
            metrics.append(match.group(1))

    return sorted(set(metrics))


def list_dimensions(metric_name: str) -> list[str]:
    output = run_mf_command(
        ["mf", "list", "dimensions", "--metrics", metric_name]
    )

    dimensions = []

    for line in output.splitlines():
        line = line.strip()

        match = re.match(r"^•\s*([a-zA-Z0-9_]+__[a-zA-Z0-9_]+|metric_time)$", line)

        if match:
            dimensions.append(match.group(1))

    return sorted(set(dimensions))


def get_metric_catalog() -> dict[str, list[str]]:
    catalog = {}

    for metric in list_metrics():
        catalog[metric] = list_dimensions(metric)

    return catalog


if __name__ == "__main__":
    print("Metrics:")
    print(list_metrics())

    print("\nDimensions for total_spend:")
    print(list_dimensions("total_spend"))

    print("\nMetric catalog:")
    print(get_metric_catalog())