import streamlit as st
import pandas as pd

from analytics.ai_metric_query import run_analytics_agent


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

question = st.text_input(
    "Ask a question",
    placeholder="Example: What about only Berlin?",
)

st.caption("Try: " + " | ".join(example_questions[:3]))


with st.sidebar:
    st.subheader("Session History")

    if st.button("Clear history"):
        st.session_state.history = []

    if not st.session_state.history:
        st.caption("No questions asked yet.")
    else:
        for i, item in enumerate(reversed(st.session_state.history), start=1):
            with st.expander(f"{i}. {item['question']}"):
                st.write(item["answer"])

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


def render_tool_output(output: dict, tool_name: str | None = None) -> None:
    if tool_name == "search_semantic_layer":
        render_semantic_search_output(output)
        return

    if isinstance(output, dict) and output.get("data"):
        data = output["data"]
        columns = output.get("columns", [])

        df = pd.DataFrame(data)

        st.dataframe(df, use_container_width=True)

        if len(columns) >= 2:
            x_col = columns[0]
            y_cols = columns[1:]

            numeric_cols = [
                col for col in y_cols
                if col in df.columns and pd.api.types.is_numeric_dtype(df[col])
            ]

            if numeric_cols:
                chart_df = df.set_index(x_col)[numeric_cols]

                x_name = x_col.lower()

                if (
                    "month" in x_name
                    or "week" in x_name
                    or "date" in x_name
                    or "time" in x_name
                ):
                    st.line_chart(chart_df)
                else:
                    st.bar_chart(chart_df)

    else:
        st.json(output)


if st.button("Run query") and question:
    recent_history = st.session_state.history[-5:]

    with st.spinner("Agent is working..."):
        response = run_analytics_agent(
            question=question,
            conversation_history=recent_history,
        )

    st.session_state.history.append(
        {
            "question": question,
            "answer": response["answer"],
            "tool_results": response["tool_results"],
        }
    )

    st.subheader("AI Answer")
    st.write(response["answer"])

    st.subheader("Agent Tool Calls")

    for i, step in enumerate(response["tool_results"], start=1):
        with st.expander(f"Step {i}: {step['tool']}"):
            st.write("Arguments")
            st.json(step["arguments"])

            st.write("Output")
            render_tool_output(
                output=step["output"],
                tool_name=step["tool"],
            )