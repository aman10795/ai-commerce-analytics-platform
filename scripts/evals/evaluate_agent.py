import json
from datetime import datetime
from pathlib import Path
from typing import Any

from analytics.agent import run_analytics_agent


PROJECT_ROOT = Path(__file__).resolve().parents[2]
EVAL_OUTPUT_DIR = PROJECT_ROOT / "logs" / "eval_runs"
EVAL_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


EVAL_CASES = [
    {
        "id": "basic_total_spend",
        "question": "How much money did I spend?",
        "expected_metrics": ["total_spend"],
        "expected_group_by": [],
        "expected_tools": ["search_semantic_layer", "run_metricflow_query"],
    },
    {
        "id": "spend_by_shop",
        "question": "How much money by shop?",
        "expected_metrics": ["total_spend"],
        "expected_group_by": ["order__merchant_name"],
        "expected_tools": ["search_semantic_layer", "run_metricflow_query"],
    },
    {
        "id": "spend_by_city",
        "question": "Show spend by city.",
        "expected_metrics": ["total_spend"],
        "expected_group_by": ["order__residence_city"],
        "expected_tools": ["search_semantic_layer", "run_metricflow_query"],
    },
    {
        "id": "orders_berlin_alcohol",
        "question": "How many orders did I have in Berlin with alcohol?",
        "expected_metrics": ["order_count"],
        "expected_group_by": [],
        "expected_filters": [
            {"dimension": "order__residence_city", "value": "Berlin"},
            {"dimension": "order__contains_alcohol", "value": True},
        ],
        "expected_tools": ["run_metricflow_query"],
    },
    {
        "id": "grocery_orders",
        "question": "How many orders included grocery?",
        "expected_metrics": ["order_count"],
        "expected_group_by": [],
        "expected_filters": [
            {"dimension": "order__contains_grocery", "value": True},
        ],
        "expected_tools": ["run_metricflow_query"],
    },
    {
        "id": "monthly_spend_trend",
        "question": "What was my monthly spend trend?",
        "expected_metrics": ["total_spend"],
        "expected_group_by_any_of": [
            "metric_time__month",
            "metric_time",
            "order__order_date",
        ],
        "expected_tools": ["run_metricflow_query"],
    },
    {
        "id": "refund_ratio",
        "question": "What is my refund ratio?",
        "expected_metrics": ["refund_ratio"],
        "expected_group_by": [],
        "expected_tools": ["search_semantic_layer", "run_metricflow_query"],
    },
    {
        "id": "discount_ratio_by_city",
        "question": "Show discount ratio by city.",
        "expected_metrics": ["discount_ratio"],
        "expected_group_by": ["order__residence_city"],
        "expected_tools": ["search_semantic_layer", "run_metricflow_query"],
    },
]


def extract_metricflow_steps(response: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        step
        for step in response.get("tool_results", [])
        if step.get("tool") == "run_metricflow_query"
    ]


def extract_used_tools(response: dict[str, Any]) -> list[str]:
    return [step.get("tool") for step in response.get("tool_results", [])]


def extract_plans(response: dict[str, Any]) -> list[dict[str, Any]]:
    plans = []

    for step in extract_metricflow_steps(response):
        output = step.get("output", {})

        if isinstance(output, dict) and output.get("plan"):
            plans.append(output["plan"])

    return plans


def flatten_values(items: list[list[Any]]) -> list[Any]:
    flattened = []

    for item in items:
        flattened.extend(item)

    return flattened


def get_all_metrics(plans: list[dict[str, Any]]) -> list[str]:
    return flatten_values([plan.get("metrics", []) for plan in plans])


def get_all_group_bys(plans: list[dict[str, Any]]) -> list[str]:
    return flatten_values([plan.get("group_by", []) for plan in plans])


def get_all_filters(plans: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return flatten_values([plan.get("filters", []) for plan in plans])


def values_match(actual: Any, expected: Any) -> bool:
    if isinstance(expected, bool):
        return actual is expected

    if actual is None:
        return False

    return str(actual).strip().lower() == str(expected).strip().lower()


def check_expected_metrics(case: dict[str, Any], plans: list[dict[str, Any]]) -> tuple[bool, str]:
    expected = case.get("expected_metrics", [])
    actual = get_all_metrics(plans)

    missing = [metric for metric in expected if metric not in actual]

    if missing:
        return False, f"Missing expected metrics: {missing}. Actual: {actual}"

    return True, "Expected metrics found."


def check_expected_group_by(case: dict[str, Any], plans: list[dict[str, Any]]) -> tuple[bool, str]:
    actual = get_all_group_bys(plans)

    if "expected_group_by" in case:
        expected = case.get("expected_group_by", [])
        missing = [group_by for group_by in expected if group_by not in actual]

        if missing:
            return False, f"Missing expected group_by: {missing}. Actual: {actual}"

        return True, "Expected group_by found."

    if "expected_group_by_any_of" in case:
        expected_any = case.get("expected_group_by_any_of", [])

        if not any(group_by in actual for group_by in expected_any):
            return False, f"None of expected group_by options found: {expected_any}. Actual: {actual}"

        return True, "At least one expected group_by option found."

    return True, "No group_by expectation."


def check_expected_filters(case: dict[str, Any], plans: list[dict[str, Any]]) -> tuple[bool, str]:
    expected_filters = case.get("expected_filters", [])

    if not expected_filters:
        return True, "No filter expectation."

    actual_filters = get_all_filters(plans)

    for expected in expected_filters:
        expected_dimension = expected.get("dimension")
        expected_value = expected.get("value")

        matching_dimension_filters = [
            actual
            for actual in actual_filters
            if actual.get("dimension") == expected_dimension
        ]

        if not matching_dimension_filters:
            return False, f"Missing filter dimension: {expected_dimension}. Actual filters: {actual_filters}"

        if not any(
            values_match(actual.get("value"), expected_value)
            for actual in matching_dimension_filters
        ):
            return False, (
                f"Filter value mismatch for {expected_dimension}. "
                f"Expected: {expected_value}. Actual filters: {matching_dimension_filters}"
            )

    return True, "Expected filters found."


def check_expected_tools(case: dict[str, Any], response: dict[str, Any]) -> tuple[bool, str]:
    expected_tools = case.get("expected_tools", [])
    used_tools = extract_used_tools(response)

    missing = [tool for tool in expected_tools if tool not in used_tools]

    if missing:
        return False, f"Missing expected tools: {missing}. Used tools: {used_tools}"

    return True, "Expected tools used."


def check_metricflow_success(response: dict[str, Any]) -> tuple[bool, str]:
    metricflow_steps = extract_metricflow_steps(response)

    if not metricflow_steps:
        return False, "No MetricFlow query was executed."

    failed_steps = []

    for step in metricflow_steps:
        output = step.get("output", {})

        if isinstance(output, dict) and output.get("success") is False:
            failed_steps.append(output.get("error") or output)

    if failed_steps:
        return False, f"MetricFlow failed: {failed_steps}"

    return True, "MetricFlow succeeded."


def evaluate_case(case: dict[str, Any]) -> dict[str, Any]:
    print(f"\nRunning eval: {case['id']}")
    print(f"Question: {case['question']}")

    response = run_analytics_agent(case["question"])
    plans = extract_plans(response)

    checks = []

    for check_name, check_function in [
        ("expected_tools", check_expected_tools),
        ("metricflow_success", check_metricflow_success),
    ]:
        passed, message = check_function(case, response) if check_name == "expected_tools" else check_function(response)
        checks.append(
            {
                "check": check_name,
                "passed": passed,
                "message": message,
            }
        )

    for check_name, check_function in [
        ("expected_metrics", check_expected_metrics),
        ("expected_group_by", check_expected_group_by),
        ("expected_filters", check_expected_filters),
    ]:
        passed, message = check_function(case, plans)
        checks.append(
            {
                "check": check_name,
                "passed": passed,
                "message": message,
            }
        )

    passed = all(check["passed"] for check in checks)

    return {
        "id": case["id"],
        "question": case["question"],
        "passed": passed,
        "checks": checks,
        "answer": response.get("answer"),
        "plans": plans,
        "tool_results": response.get("tool_results", []),
        "execution_trace": response.get("execution_trace"),
    }


def main() -> None:
    started_at = datetime.now().isoformat(timespec="seconds")

    results = []

    for case in EVAL_CASES:
        result = evaluate_case(case)
        results.append(result)

        status = "PASS" if result["passed"] else "FAIL"
        print(f"{status}: {case['id']}")

        for check in result["checks"]:
            check_status = "✓" if check["passed"] else "✗"
            print(f"  {check_status} {check['check']}: {check['message']}")

    total = len(results)
    passed_count = sum(1 for result in results if result["passed"])

    summary = {
        "started_at": started_at,
        "finished_at": datetime.now().isoformat(timespec="seconds"),
        "total_cases": total,
        "passed_cases": passed_count,
        "failed_cases": total - passed_count,
        "pass_rate": round(passed_count / total, 4) if total else 0,
        "results": results,
    }

    output_path = EVAL_OUTPUT_DIR / f"eval_run_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, default=str)

    print("\nEvaluation complete")
    print(f"Passed: {passed_count}/{total}")
    print(f"Pass rate: {summary['pass_rate'] * 100:.1f}%")
    print(f"Saved to: {output_path}")


if __name__ == "__main__":
    main()