from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError as exc:  # pragma: no cover - environment guard
    raise SystemExit(
        "PyYAML is required for YAML eval cases. Install it with:\n"
        "  pip install pyyaml\n"
        "or add `pyyaml` to requirements.txt."
    ) from exc

from analytics.mcp_agent import run_mcp_analytics_agent


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CASES_PATH = PROJECT_ROOT / "evals" / "agent_metricflow_cases.yml"
EVAL_LOG_DIR = PROJECT_ROOT / "logs" / "evals"
EVAL_LOG_DIR.mkdir(parents=True, exist_ok=True)


CheckResult = tuple[bool, str]


def normalize_scalar(value: Any) -> Any:
    """Normalize common scalar representations for stable comparisons."""
    if isinstance(value, str):
        stripped = value.strip()
        lowered = stripped.lower()

        if lowered == "true":
            return True
        if lowered == "false":
            return False
        if lowered in {"null", "none"}:
            return None

        return stripped

    return value


def normalize_operator(operator: Any) -> str | None:
    if operator is None:
        return None

    op = str(operator).strip().lower()

    aliases = {
        "==": "=",
        "eq": "=",
        "equals": "=",
        "is": "=",
        "in": "in",
        "not in": "not in",
        "!=": "!=",
        "neq": "!=",
        "not_equals": "!=",
        ">": ">",
        "<": "<",
        ">=": ">=",
        "<=": "<=",
    }

    return aliases.get(op, op)


def listify(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def normalize_string_list(values: Any) -> list[str]:
    return [str(item) for item in listify(values) if item is not None]


def values_match(actual: Any, expected: Any) -> bool:
    actual_norm = normalize_scalar(actual)
    expected_norm = normalize_scalar(expected)

    if isinstance(actual_norm, list):
        return any(values_match(item, expected_norm) for item in actual_norm)

    if isinstance(expected_norm, list):
        return any(values_match(actual_norm, item) for item in expected_norm)

    return actual_norm == expected_norm


def load_cases(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        raise FileNotFoundError(f"Eval case file not found: {path}")

    with open(path, "r", encoding="utf-8") as f:
        loaded = yaml.safe_load(f) or {}

    if isinstance(loaded, list):
        cases = loaded
    else:
        cases = loaded.get("cases", [])

    if not isinstance(cases, list):
        raise ValueError("Eval YAML must contain a top-level `cases:` list.")

    for index, case in enumerate(cases, start=1):
        if not case.get("id"):
            raise ValueError(f"Eval case #{index} is missing `id`.")
        if not case.get("question"):
            raise ValueError(f"Eval case {case.get('id')} is missing `question`.")
        if not isinstance(case.get("expected", {}), dict):
            raise ValueError(f"Eval case {case.get('id')} has invalid `expected` block.")

    return cases


def get_execution_trace(response: dict[str, Any]) -> dict[str, Any]:
    trace = response.get("execution_trace")
    return trace if isinstance(trace, dict) else {}


def get_query_plan(response: dict[str, Any]) -> dict[str, Any]:
    trace = get_execution_trace(response)
    plan = trace.get("query_plan")
    return plan if isinstance(plan, dict) else {}


def extract_tool_steps(response: dict[str, Any]) -> list[dict[str, Any]]:
    """
    Normalize tool calls from response.tool_results and execution_trace.steps.

    Newer MCP agent responses expose tool_results like:
      {"tool": "run_metricflow_query", "arguments": {...}, "output": {...}}

    Execution traces expose steps like:
      {"tool_name": "run_metricflow_query", "arguments": {...}, "output": {...}}
    """
    normalized: list[dict[str, Any]] = []

    for item in response.get("tool_results", []) or []:
        if not isinstance(item, dict):
            continue
        tool_name = item.get("tool") or item.get("tool_name")
        if not tool_name:
            continue
        normalized.append(
            {
                "tool": tool_name,
                "arguments": item.get("arguments") or {},
                "output": item.get("output") or {},
                "source": "tool_results",
            }
        )

    if normalized:
        return normalized

    trace = get_execution_trace(response)
    for step in trace.get("steps", []) or []:
        if not isinstance(step, dict):
            continue
        tool_name = step.get("tool") or step.get("tool_name")
        if not tool_name:
            continue
        normalized.append(
            {
                "tool": tool_name,
                "arguments": step.get("arguments") or {},
                "output": step.get("output") or {},
                "source": "execution_trace.steps",
            }
        )

    return normalized


def extract_used_tools(response: dict[str, Any]) -> list[str]:
    return [step["tool"] for step in extract_tool_steps(response)]


def extract_metricflow_steps(response: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        step
        for step in extract_tool_steps(response)
        if step.get("tool") == "run_metricflow_query"
    ]


def metricflow_step_succeeded(step: dict[str, Any]) -> bool:
    output = step.get("output")
    return isinstance(output, dict) and output.get("success") is True


def extract_metricflow_plan(step: dict[str, Any]) -> dict[str, Any]:
    """
    Prefer the validated plan returned by the MetricFlow tool.
    Fall back to the tool arguments if a plan is not present.
    """
    output = step.get("output")
    arguments = step.get("arguments") if isinstance(step.get("arguments"), dict) else {}

    if isinstance(output, dict) and isinstance(output.get("plan"), dict):
        plan = dict(output["plan"])
    else:
        plan = dict(arguments or {})

    # Preserve time_granularity from arguments if the returned plan omitted it.
    if "time_granularity" not in plan and "time_granularity" in arguments:
        plan["time_granularity"] = arguments.get("time_granularity")

    return plan


def extract_successful_metricflow_plans(response: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        extract_metricflow_plan(step)
        for step in extract_metricflow_steps(response)
        if metricflow_step_succeeded(step)
    ]


def filters_match(actual_filters: list[dict[str, Any]], expected_filters: list[dict[str, Any]]) -> bool:
    for expected in expected_filters:
        expected_dimension = expected.get("dimension")
        expected_dimensions = expected.get("dimension_any_of")
        if expected_dimensions is None:
            expected_dimensions = [expected_dimension]
        expected_dimensions = [dim for dim in listify(expected_dimensions) if dim is not None]

        expected_operator = normalize_operator(expected.get("operator"))
        expected_value = expected.get("value")

        matching_dimensions = [
            actual
            for actual in actual_filters
            if isinstance(actual, dict)
            and actual.get("dimension") in expected_dimensions
        ]

        if not matching_dimensions:
            return False

        found_value_match = False

        for actual in matching_dimensions:
            actual_operator = normalize_operator(actual.get("operator"))
            actual_value = actual.get("value")

            operator_ok = (
                expected_operator is None
                or actual_operator is None
                or actual_operator == expected_operator
            )

            if operator_ok and values_match(actual_value, expected_value):
                found_value_match = True
                break

        if not found_value_match:
            return False

    return True


def plan_satisfies_expected(plan: dict[str, Any], expected: dict[str, Any]) -> tuple[bool, list[str]]:
    reasons: list[str] = []

    expected_metrics = normalize_string_list(expected.get("metrics"))
    actual_metrics = normalize_string_list(plan.get("metrics"))
    if expected_metrics:
        missing_metrics = [metric for metric in expected_metrics if metric not in actual_metrics]
        if missing_metrics:
            reasons.append(f"missing metrics {missing_metrics}; actual metrics={actual_metrics}")

    # group_by can be exact via group_by or flexible via group_by_any_of.
    actual_group_by = normalize_string_list(plan.get("group_by"))

    if "group_by_any_of" in expected:
        acceptable_groups = expected.get("group_by_any_of") or []
        acceptable_groups = [normalize_string_list(group) for group in acceptable_groups]
        if actual_group_by not in acceptable_groups:
            reasons.append(
                f"group_by {actual_group_by} not in acceptable options {acceptable_groups}"
            )
    elif "group_by" in expected:
        expected_group_by = normalize_string_list(expected.get("group_by"))
        if actual_group_by != expected_group_by:
            reasons.append(
                f"group_by mismatch; expected={expected_group_by}, actual={actual_group_by}"
            )

    if "time_granularity" in expected:
        expected_time = expected.get("time_granularity")
        actual_time = plan.get("time_granularity")
        if actual_time != expected_time:
            reasons.append(
                f"time_granularity mismatch; expected={expected_time}, actual={actual_time}"
            )

    if "order_by" in expected:
        expected_order_by = expected.get("order_by") or []
        actual_order_by = plan.get("order_by") or []
        if actual_order_by != expected_order_by:
            reasons.append(
                f"order_by mismatch; expected={expected_order_by}, actual={actual_order_by}"
            )

    if "limit" in expected:
        expected_limit = expected.get("limit")
        actual_limit = plan.get("limit")
        if actual_limit != expected_limit:
            reasons.append(
                f"limit mismatch; expected={expected_limit}, actual={actual_limit}"
            )

    if "filters" in expected:
        expected_filters = expected.get("filters") or []
        actual_filters = plan.get("filters") or []

        if expected_filters:
            if not filters_match(actual_filters, expected_filters):
                reasons.append(
                    f"filters mismatch; expected={expected_filters}, actual={actual_filters}"
                )
        else:
            if actual_filters:
                reasons.append(f"expected no filters, actual filters={actual_filters}")

    return (len(reasons) == 0, reasons)


def check_intent(case: dict[str, Any], response: dict[str, Any]) -> CheckResult:
    expected_intent = case.get("expected", {}).get("intent")
    if not expected_intent:
        return True, "No intent expectation."

    plan = get_query_plan(response)
    actual_intent = plan.get("intent")

    if actual_intent != expected_intent:
        return False, f"Expected intent={expected_intent}, actual intent={actual_intent}"

    return True, f"Intent matched: {actual_intent}"


def check_planner_time_grain(case: dict[str, Any], response: dict[str, Any]) -> CheckResult:
    expected = case.get("expected", {})

    if "time_granularity" not in expected:
        return True, "No planner time-grain expectation."

    expected_time = expected.get("time_granularity")
    plan = get_query_plan(response)
    actual_time = plan.get("time_grain")

    if actual_time != expected_time:
        return False, f"Expected planner time_grain={expected_time}, actual={actual_time}"

    return True, f"Planner time_grain matched: {actual_time}"


def check_expected_tools(case: dict[str, Any], response: dict[str, Any]) -> CheckResult:
    expected_tools = case.get("expected", {}).get("tools", ["run_metricflow_query"])
    used_tools = extract_used_tools(response)
    missing = [tool for tool in expected_tools if tool not in used_tools]

    if missing:
        return False, f"Missing expected tools: {missing}. Used tools: {used_tools}"

    return True, f"Expected tools used: {expected_tools}"


def check_metricflow_success(case: dict[str, Any], response: dict[str, Any]) -> CheckResult:
    expected_success = case.get("expected", {}).get("metricflow_success", True)
    steps = extract_metricflow_steps(response)

    if not steps:
        return False, "No run_metricflow_query call found."

    successes = [step for step in steps if metricflow_step_succeeded(step)]
    failures = [step for step in steps if not metricflow_step_succeeded(step)]

    if expected_success and not successes:
        failure_outputs = [step.get("output") for step in failures]
        return False, f"No successful MetricFlow call. Failures={failure_outputs}"

    if expected_success is False and successes:
        return False, "MetricFlow succeeded, but expected failure."

    return True, f"MetricFlow success matched. successful_calls={len(successes)}, total_calls={len(steps)}"


def check_metricflow_call_count(case: dict[str, Any], response: dict[str, Any]) -> CheckResult:
    expected = case.get("expected", {})
    steps = extract_metricflow_steps(response)
    successful_steps = [step for step in steps if metricflow_step_succeeded(step)]

    if "expected_metricflow_calls" in expected:
        expected_count = int(expected["expected_metricflow_calls"])
        actual_count = len(successful_steps)
        if actual_count != expected_count:
            return False, f"Expected exactly {expected_count} successful MetricFlow calls, actual={actual_count}"
        return True, f"Successful MetricFlow call count matched: {actual_count}"

    if "expected_metricflow_calls_min" in expected:
        expected_min = int(expected["expected_metricflow_calls_min"])
        actual_count = len(successful_steps)
        if actual_count < expected_min:
            return False, f"Expected at least {expected_min} successful MetricFlow calls, actual={actual_count}"
        return True, f"Successful MetricFlow call count >= {expected_min}: {actual_count}"

    return True, "No MetricFlow call-count expectation."


def check_expected_metricflow_plan(case: dict[str, Any], response: dict[str, Any]) -> CheckResult:
    expected = case.get("expected", {})
    plans = extract_successful_metricflow_plans(response)

    if not plans:
        return False, "No successful MetricFlow plans found."

    best_failure_reasons: list[str] = []

    for plan in plans:
        ok, reasons = plan_satisfies_expected(plan, expected)
        if ok:
            return True, f"Found matching MetricFlow plan: {plan}"
        if not best_failure_reasons or len(reasons) < len(best_failure_reasons):
            best_failure_reasons = reasons

    return False, (
        "No successful MetricFlow plan matched expected contract. "
        f"Best mismatch: {best_failure_reasons}. Actual plans={plans}"
    )


def check_filters_any_call(case: dict[str, Any], response: dict[str, Any]) -> CheckResult:
    expected_filters = case.get("expected", {}).get("filters_any_call")
    if not expected_filters:
        return True, "No filters_any_call expectation."

    plans = extract_successful_metricflow_plans(response)
    all_filters = []
    for plan in plans:
        all_filters.extend(plan.get("filters") or [])

    missing = []
    for expected_filter in expected_filters:
        if not filters_match(all_filters, [expected_filter]):
            missing.append(expected_filter)

    if missing:
        return False, f"Missing filters across successful calls: {missing}. Actual filters={all_filters}"

    return True, "Expected filters found across successful MetricFlow calls."


def evaluate_case(case: dict[str, Any]) -> dict[str, Any]:
    case_id = case["id"]
    question = case["question"]

    print("\n" + "=" * 100)
    print(f"Running MCP eval: {case_id}")
    print(f"Question: {question}")
    if case.get("reason"):
        print(f"Reason:   {case['reason']}")
    print("=" * 100)

    try:
        response = run_mcp_analytics_agent(question)
    except Exception as exc:  # keep eval log useful when the agent crashes
        response = {
            "question": question,
            "answer": "",
            "tool_results": [],
            "execution_trace": {
                "status": "failed",
                "error": f"Agent raised exception: {exc}",
                "query_plan": {},
                "steps": [],
            },
        }

    checks: dict[str, CheckResult] = {
        "intent": check_intent(case, response),
        "planner_time_grain": check_planner_time_grain(case, response),
        "expected_tools": check_expected_tools(case, response),
        "metricflow_success": check_metricflow_success(case, response),
        "metricflow_call_count": check_metricflow_call_count(case, response),
        "expected_metricflow_plan": check_expected_metricflow_plan(case, response),
        "filters_any_call": check_filters_any_call(case, response),
    }

    passed = all(result[0] for result in checks.values())

    print(f"{'PASS' if passed else 'FAIL'}: {case_id}")
    for check_name, (check_passed, message) in checks.items():
        icon = "✓" if check_passed else "✗"
        print(f"  {icon} {check_name}: {message}")

    return {
        "id": case_id,
        "question": question,
        "reason": case.get("reason"),
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


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Evaluate the MCP analytics agent.")
    parser.add_argument(
        "--cases",
        type=Path,
        default=DEFAULT_CASES_PATH,
        help=f"Path to YAML eval cases. Default: {DEFAULT_CASES_PATH}",
    )
    parser.add_argument(
        "--case",
        action="append",
        dest="case_ids",
        default=[],
        help="Run only this case id. Can be passed multiple times.",
    )
    parser.add_argument(
        "--max-cases",
        type=int,
        default=None,
        help="Run only the first N selected cases.",
    )
    parser.add_argument(
        "--no-exit-code",
        action="store_true",
        help="Do not exit with status 1 when evals fail.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    started_at = datetime.now().isoformat(timespec="seconds")

    cases = load_cases(args.cases)

    if args.case_ids:
        selected = set(args.case_ids)
        cases = [case for case in cases if case["id"] in selected]
        missing_ids = sorted(selected - {case["id"] for case in cases})
        if missing_ids:
            raise ValueError(f"Requested case ids not found in YAML: {missing_ids}")

    if args.max_cases is not None:
        cases = cases[: args.max_cases]

    results = [evaluate_case(case) for case in cases]

    total = len(results)
    passed = sum(1 for result in results if result["passed"])
    failed = total - passed
    finished_at = datetime.now().isoformat(timespec="seconds")

    summary = {
        "agent_mode": "mcp",
        "cases_file": str(args.cases),
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

    print("\n" + "=" * 100)
    print("MCP Eval Summary")
    print("=" * 100)
    print(f"Cases file: {args.cases}")
    print(f"Total:      {total}")
    print(f"Passed:     {passed}")
    print(f"Failed:     {failed}")
    print(f"Log:        {log_path}")

    if failed > 0 and not args.no_exit_code:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
