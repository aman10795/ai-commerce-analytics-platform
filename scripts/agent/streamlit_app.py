import streamlit as st
import pandas as pd

from analytics.agent import run_analytics_agent
from analytics.mcp_agent import run_mcp_analytics_agent


st.set_page_config(
    page_title="Commerce Analytics AI Assistant",
    layout="wide",
)

st.title("Commerce Analytics AI Assistant")
st.write("Ask questions over your dbt Semantic Layer and MetricFlow metrics.")


if "history" not in st.session_state:
    st.session_state.history = []


example_questions = [
    "How many orders did I have in Berlin with alcohol?",
    "Compare alcohol spend vs grocery spend.",
    "Show total spend by career stage.",
    "Show total spend by residence city.",
    "What was my monthly spend trend?",
]


EXECUTION_PATHS = {
    "Direct Python Agent": (
        "Streamlit → analytics.agent → analytics.ai_metric_query "
        "→ MetricFlow → DuckDB"
    ),
    "MCP Agent": (
        "Streamlit → analytics.mcp_agent → MCP client → MCP server "
        "→ analytics.ai_metric_query → MetricFlow → DuckDB"
    ),
}


with st.sidebar:
    st.subheader("Execution Mode")

    execution_mode = st.radio(
        "Choose how the assistant should execute analytics tools",
        options=[
            "Direct Python Agent",
            "MCP Agent",
        ],
        index=0,
    )

    st.caption(
        "Direct mode calls Python functions directly. "
        "MCP mode calls the same backend through the MCP server."
    )

    st.info(f"Path: {EXECUTION_PATHS[execution_mode]}")

    st.divider()

    st.subheader("Examples")

    for example in example_questions:
        st.caption(f"• {example}")

    st.divider()

    st.subheader("Session Controls")

    if st.button("Clear conversation"):
        st.session_state.history = []
        st.rerun()

    st.caption(f"Questions asked: {len(st.session_state.history)}")


def render_semantic_search_output(output: dict) -> None:
    matches = output.get("matches", [])

    if not matches:
        st.warning("No semantic matches found.")
        st.json(output)
        return

    rows = []

    for rank, match in enumerate(matches, start=1):
        rows.append(
            {
                "rank": rank,
                "type": match.get("type"),
                "name": match.get("name"),
                "metric": match.get("metric"),
                "dimension": match.get("dimension"),
                "score": match.get("score"),
                "available_metrics": ", ".join(match.get("metrics", [])[:5]),
            }
        )

    df = pd.DataFrame(rows)

    st.write(f"Semantic search query: `{output.get('query')}`")
    st.dataframe(df, use_container_width=True)

    if "score" in df.columns:
        chart_df = df.set_index("name")[["score"]]
        st.bar_chart(chart_df)


def render_query_plan(output: dict) -> None:
    plan = output.get("plan")

    if not plan:
        return

    st.markdown("##### Query Plan")
    st.json(plan)


def render_metricflow_command(output: dict) -> None:
    command = output.get("metricflow_command")

    if not command:
        return

    st.markdown("##### MetricFlow Command")
    st.code(command, language="bash")


def render_metricflow_output(output: dict) -> None:
    render_query_plan(output)
    render_metricflow_command(output)

    if output.get("error"):
        st.error("MetricFlow returned an error.")
        st.code(output["error"])
        return

    data = output.get("data", [])
    columns = output.get("columns", [])

    if not data:
        st.warning("No structured data returned.")
        st.json(output)
        return

    df = pd.DataFrame(data)

    st.markdown("##### Result Table")
    st.dataframe(df, use_container_width=True)

    if len(columns) >= 2:
        x_col = columns[0]
        y_cols = columns[1:]

        numeric_cols = [
            col
            for col in y_cols
            if col in df.columns and pd.api.types.is_numeric_dtype(df[col])
        ]

        if numeric_cols:
            chart_df = df.set_index(x_col)[numeric_cols]

            x_name = x_col.lower()

            st.markdown("##### Result Chart")

            if (
                "month" in x_name
                or "week" in x_name
                or "date" in x_name
                or "time" in x_name
            ):
                st.line_chart(chart_df)
            else:
                st.bar_chart(chart_df)


def render_tool_output(output, tool_name: str | None = None) -> None:
    if not isinstance(output, dict):
        st.json(output)
        return

    if tool_name in ["search_semantic_layer", "semantic_search"]:
        render_semantic_search_output(output)
        return

    if tool_name == "run_metricflow_query" or output.get("data"):
        render_metricflow_output(output)
        return

    st.json(output)


def run_selected_agent(
    question: str,
    recent_history: list[dict],
    execution_mode: str,
) -> dict:
    if execution_mode == "Direct Python Agent":
        return run_analytics_agent(
            question=question,
            conversation_history=recent_history,
        )

    return run_mcp_analytics_agent(
        question=question,
        conversation_history=recent_history,
    )


def get_primary_metricflow_steps(tool_results: list[dict]) -> list[dict]:
    return [
        step
        for step in tool_results
        if step.get("tool") == "run_metricflow_query"
        and isinstance(step.get("output"), dict)
    ]


def render_primary_results(tool_results: list[dict]) -> None:
    metricflow_steps = get_primary_metricflow_steps(tool_results)

    if not metricflow_steps:
        return

    st.markdown("#### Query Result")

    for i, step in enumerate(metricflow_steps, start=1):
        output = step["output"]

        if len(metricflow_steps) > 1:
            st.markdown(f"##### MetricFlow Query {i}")

        render_metricflow_output(output)


def render_response_card(item: dict, index: int) -> None:
    question = item["question"]
    answer = item["answer"]
    tool_results = item.get("tool_results", [])
    mode = item.get("execution_mode", "Unknown")
    execution_path = item.get("execution_path", EXECUTION_PATHS.get(mode, "Unknown"))

    with st.container(border=True):
        st.markdown(f"### Question {index}")
        st.markdown(f"**User:** {question}")

        st.markdown("#### AI Answer")
        st.write(answer)

        col1, col2 = st.columns([1, 3])

        with col1:
            st.caption(f"Mode: {mode}")

        with col2:
            st.caption(f"Execution path: {execution_path}")

        render_primary_results(tool_results)

        execution_trace = item.get("execution_trace", {})

        if execution_trace:
            with st.expander("Execution Trace Summary"):
                st.json(
                    {
                        "status": execution_trace.get("status"),
                        "agent_mode": execution_trace.get("agent_mode", "direct"),
                        "started_at": execution_trace.get("started_at"),
                        "finished_at": execution_trace.get("finished_at"),
                        "error": execution_trace.get("error"),
                        "steps_count": len(execution_trace.get("steps", [])),
                    }
                )

        if tool_results:
            with st.expander("All Agent Tool Calls", expanded=False):
                for i, step in enumerate(tool_results, start=1):
                    label = f"Step {i}: {step['tool']}"

                    if mode == "MCP Agent":
                        label += " via MCP"

                    with st.expander(label):
                        st.write("Arguments")
                        st.json(step["arguments"])

                        st.write("Output")
                        render_tool_output(
                            output=step["output"],
                            tool_name=step["tool"],
                        )


st.caption("Try: " + " | ".join(example_questions[:3]))

st.divider()

st.subheader("Conversation")

if not st.session_state.history:
    st.info("Ask your first question below.")

for index, item in enumerate(st.session_state.history, start=1):
    render_response_card(item=item, index=index)


question = st.chat_input("Ask a commerce analytics question")


if question:
    recent_history = st.session_state.history[-5:]

    with st.spinner(f"Agent is working using {execution_mode}..."):
        response = run_selected_agent(
            question=question,
            recent_history=recent_history,
            execution_mode=execution_mode,
        )

    st.session_state.history.append(
        {
            "question": question,
            "answer": response["answer"],
            "tool_results": response["tool_results"],
            "execution_trace": response.get("execution_trace", {}),
            "execution_mode": execution_mode,
            "execution_path": EXECUTION_PATHS[execution_mode],
        }
    )

    st.rerun()