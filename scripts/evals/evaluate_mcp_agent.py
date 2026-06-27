import json
from datetime import datetime
from pathlib import Path
from typing import Any

from analytics.mcp_agent import run_mcp_analytics_agent


PROJECT_ROOT = Path(__file__).resolve().parents[2]
EVAL_LOG_DIR = PROJECT_ROOT / "logs" / "evals"
EVAL_LOG_DIR.mkdir(parents=True, exist_ok=True)


EVAL_CASES = [
    {
        "name": "basic_total_spend",
        "question": "How much money did I spend?",
        "expected_tools": ["run_metricflow_query"],
        "expected_metricflow_success": True,
        "expected_metrics": ["total_spend"],
    },
    {
        "name": "spend_by_merchant",
        "question": "Show total spend by merchant.",
        "expected_tools": ["run_metricflow_query"],
        "expected_metricflow_success": True,
        "expected_metrics": ["total_spend"],
        "expected_group_by": ["order__merchant_name"],
    },
    {
        "name": "order_count_berlin_alcohol",
        "question": "How many orders did I have in Berlin with alcohol?",
        "expected_tools": ["run_metricflow_query"],
        "expected_metricflow_success": True,
        "expected_metrics": ["order_count"],
    },
    {
        "name": "monthly_spend_trend",
        "question": "What was my monthly spend trend?",
        "expected_tools": ["run_metricflow_query"],
        "expected_metricflow_success": True,
        "expected_metrics": ["total_spend"],
    },
    {
        "name": "spend_by_career_stage",
        "question": "Show total spend by career stage.",
        "expected_tools": ["run_metricflow_query"],
        "expected_metricflow_success": True,
        "expected_metrics": ["total_spend"],
        "expected_group_by": ["order__career_stage"],
    },
]


def get_tool_names(response: dict[str, Any]) -> list[str]:
    return [
        item.get("tool")
        for item in response.get("tool_results", [])
        if item.get("tool")
    ]


def get_metricflow_outputs(response: dict[str, Any]) -> list[dict[str, Any]]:
    outputs = []

    for item in response.get("tool_results", []):
        if item.get("tool") != "run_metricflow_query":
            continue

        output = item.get("output")

        if isinstance(output, dict):
            outputs.append(output)

    return outputs


def get_metricflow_plans(response: dict[str, Any]) -> list[dict[str, Any]]:
    plans = []

    for output in get_metricflow_outputs(response):
        plan = output.get("plan")

        if isinstance(plan, dict):
            plans.append(plan)

    return plans


def check_expected_tools(
    response: dict[str, Any],
    expected_tools: list[str],
) -> tuple[bool, str]:
    actual_tools = get_tool_names(response)

    missing_tools = [
        tool for tool in expected_tools
        if tool not in actual_tools
    ]

    if missing_tools:
        return False, f"Missing tools: {missing_tools}. Actual tools: {actual_tools}"

    return True, "Expected tools used."


def check_metricflow_success(
    response: dict[str, Any],
    expected_success: bool,
) -> tuple[bool, str]:
    outputs = get_metricflow_outputs(response)

    if not outputs:
        return False, "No run_metricflow_query output found."

    failures = [
        output for output in outputs
        if output.get("success") is not True
    ]

    if expected_success and failures:
        return False, f"MetricFlow failed: {failures}"

    return True, "MetricFlow success status matched expectation."


def check_expected_metrics(
    response: dict[str, Any],
    expected_metrics: list[str],
) -> tuple[bool, str]:
    plans = get_metricflow_plans(response)

    if not plans:
        return False, "No MetricFlow plans found."

    actual_metrics = []

    for plan in plans:
        actual_metrics.extend(plan.get("metrics", []))

    missing_metrics = [
        metric for metric in expected_metrics
        if metric not in actual_metrics
    ]

    if missing_metrics:
        return False, f"Missing expected metrics: {missing_metrics}. Actual metrics: {actual_metrics}"

    return True, "Expected metrics used."


def check_expected_group_by(
    response: dict[str, Any],
    expected_group_by: list[str],
) -> tuple[bool, str]:
    plans = get_metricflow_plans(response)

    if not plans:
        return False, "No MetricFlow plans found."

    actual_group_bys = []

    for plan in plans:
        actual_group_bys.extend(plan.get("group_by", []))

    missing_group_bys = [
        group_by for group_by in expected_group_by
        if group_by not in actual_group_bys
    ]

    if missing_group_bys:
        return (
            False,
            f"Missing expected group_by values: {missing_group_bys}. "
            f"Actual group_by values: {actual_group_bys}",
        )

    return True, "Expected group_by values used."


def run_eval_case(eval_case: dict[str, Any]) -> dict[str, Any]:
    print("\n" + "=" * 80)
    print(f"Running MCP eval: {eval_case['name']}")
    print(f"Question: {eval_case['question']}")
    print("=" * 80)

    response = run_mcp_analytics_agent(eval_case["question"])

    checks = {}

    checks["expected_tools"] = check_expected_tools(
        response=response,
        expected_tools=eval_case.get("expected_tools", []),
    )

    checks["metricflow_success"] = check_metricflow_success(
        response=response,
        expected_success=eval_case.get("expected_metricflow_success", True),
    )

    if eval_case.get("expected_metrics"):
        checks["expected_metrics"] = check_expected_metrics(
            response=response,
            expected_metrics=eval_case["expected_metrics"],
        )

    if eval_case.get("expected_group_by"):
        checks["expected_group_by"] = check_expected_group_by(
            response=response,
            expected_group_by=eval_case["expected_group_by"],
        )

    passed = all(result[0] for result in checks.values())

    if passed:
        print(f"PASS: {eval_case['name']}")
    else:
        print(f"FAIL: {eval_case['name']}")

    for check_name, (check_passed, message) in checks.items():
        icon = "✓" if check_passed else "✗"
        print(f"  {icon} {check_name}: {message}")

    return {
        "name": eval_case["name"],
        "question": eval_case["question"],
        "passed": passed,
        "checks": {
            check_name: {
                "passed": check_result[0],
                "message": check_result[1],
            }
            for check_name, check_result in checks.items()
        },
        "response": response,
    }


def main() -> None:
    started_at = datetime.now().isoformat(timespec="seconds")

    results = []

    for eval_case in EVAL_CASES:
        result = run_eval_case(eval_case)
        results.append(result)

    total = len(results)
    passed = sum(1 for result in results if result["passed"])
    failed = total - passed

    finished_at = datetime.now().isoformat(timespec="seconds")

    summary = {
        "agent_mode": "mcp",
        "started_at": started_at,
        "finished_at": finished_at,
        "total": total,
        "passed": passed,
        "failed": failed,
        "results": results,
    }

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_path = EVAL_LOG_DIR / f"mcp_agent_eval_{timestamp}.json"

    with open(log_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, default=str)

    print("\n" + "=" * 80)
    print("MCP Eval Summary")
    print("=" * 80)
    print(f"Total:  {total}")
    print(f"Passed: {passed}")
    print(f"Failed: {failed}")
    print(f"Log:    {log_path}")

    if failed > 0:
        raise SystemExit(1)


if __name__ == "__main__":
    main()