# AI Commerce Analytics Platform

An end-to-end analytics engineering and AI project that transforms raw food-delivery invoices and transaction data into a semantic analytics platform with natural language querying.

## Project Overview

This project demonstrates a modern analytics stack combining:

* Python data extraction and transformation
* DuckDB warehouse
* dbt data modeling
* SCD Type 2 historical tracking
* Airflow orchestration
* dbt Semantic Layer + MetricFlow
* AI-powered analytics assistant
* Streamlit user interface

The goal is to allow users to ask business questions in natural language and receive governed answers directly from a semantic layer rather than generated SQL.

Example:

**User Question**

> How many orders did I have in Berlin with alcohol?

**AI Query Plan**

```json
{
  "metrics": ["order_count"],
  "filters": [
    {
      "dimension": "order__residence_city",
      "value": "Berlin"
    },
    {
      "dimension": "order__contains_alcohol",
      "value": true
    }
  ]
}
```

The AI converts the question into approved metrics and dimensions, executes the query through MetricFlow, and returns a business-friendly explanation.

---

## Architecture

Raw Documents (PDFs / JSON / CSV)
↓
Python Extraction Layer
↓
DuckDB Warehouse
↓
dbt Bronze → Silver → Gold Models
↓
Snapshots (SCD Type 2)
↓
Semantic Layer (MetricFlow)
↓
AI Query Planner
↓
MetricFlow Execution
↓
Natural Language Answers

---

## Key Features

### Data Engineering

* Multi-source ingestion
* DuckDB warehouse
* Incremental dbt models
* Data quality tests
* Historical snapshots

### Analytics Engineering

* Fact and dimension modeling
* Semantic metrics
* MetricFlow governed queries
* Time-based and behavioral analytics

### AI Analytics Assistant

* Natural language querying
* Query decomposition
* Semantic query planning
* Dynamic dimension value discovery
* Fuzzy matching and value normalization
* AI-generated business explanations

### Orchestration

* Airflow DAG
* Automated ingestion
* Automated dbt runs

---

## Example Business Questions

* How many orders did I have in Berlin with alcohol?
* Show total spend by career stage.
* Show total spend by residence city.
* What was my monthly spend trend?
* What was my average order value?
* Which merchants generated the highest spend?

---

## Technology Stack

* Python
* DuckDB
* dbt
* MetricFlow
* Airflow
* OpenAI API
* Streamlit
* Pandas

---

## Roadmap

### Completed

* Data ingestion pipeline
* Warehouse layer
* dbt modeling
* Snapshots
* Semantic layer
* AI analytics assistant
* Streamlit interface

### Planned

* Forecasting layer
* Marketing analytics
* Merchant analytics
* Automated chart generation
* Production deployment
* Dockerized platform
* Streamlit Cloud hosting
