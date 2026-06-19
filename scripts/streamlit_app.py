import json
import pandas as pd
import streamlit as st

from ai_metric_query import (
    build_query_plan,
    validate_plan,
    run_metricflow,
    explain_result,
)

st.set_page_config(
    page_title="Commerce Analytics AI Assistant",
    layout="wide",
)

st.title("Commerce Analytics AI Assistant")
st.write("Ask questions over your dbt Semantic Layer and MetricFlow metrics.")

example_questions = [
    "How many orders did I have in Berlin with alcohol?",
    "Show total spend by career stage.",
    "Show total spend by residence city.",
    "What was my monthly spend trend?",
    "What was my average order value?",
]

question = st.text_input(
    "Ask a question",
    placeholder="Example: Show total spend by career stage",
)

st.caption("Try: " + " | ".join(example_questions[:3]))

if st.button("Run query") and question:
    with st.spinner("Planning query..."):
        plan = build_query_plan(question)

    st.subheader("AI Query Plan")
    st.json(plan)

    validate_plan(plan)

    with st.spinner("Running MetricFlow..."):
        result = run_metricflow(plan)

    st.subheader("MetricFlow Result")
    st.text(result)

    with st.spinner("Generating explanation..."):
        explanation = explain_result(question, plan, result)

    st.subheader("AI Explanation")
    st.write(explanation)