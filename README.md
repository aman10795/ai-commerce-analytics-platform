# AI Commerce Analytics Platform

An AI-native analytics engineering platform for ingesting, extracting, structuring, and modeling transaction documents from food delivery, grocery delivery, and quick-commerce ecosystems.

The platform combines:
- AI-powered semantic document extraction
- warehouse-style analytics engineering
- DuckDB ingestion architecture
- dbt-ready transformation modeling
- operational observability
- lineage and replayability

---

# Project Vision

Traditional invoice extraction systems rely on:
- rigid OCR templates
- regex-heavy pipelines
- provider-specific logic

This platform instead uses:
- AI-assisted semantic extraction
- platform-agnostic ingestion
- warehouse-driven canonicalization
- layered analytics engineering architecture

The goal is to build a scalable analytics platform capable of supporting:
- transaction intelligence
- spending analytics
- pricing and fee analytics
- semantic AI querying
- future machine learning use cases

---

# High-Level Architecture

```text
PDF invoices
    ↓
PDF text extraction
    ↓
transaction text cleaning
    ↓
AI semantic extraction
    ↓
raw AI extraction artifacts
    ↓
DuckDB bronze ingestion layer
    ↓
dbt staging models
    ↓
canonical analytics marts
    ↓
semantic metrics / AI querying
```


---

# Current Capabilities

- Read invoice PDFs from ingestion folders
- Extract transaction-specific text from PDFs
- Remove noisy legal / terms-and-conditions sections
- Use OpenAI APIs for semantic extraction
- Dynamically classify transaction documents
- Extract normalized transaction components
- Persist raw AI extraction artifacts
- Track ingestion lineage and metadata
- Perform content-based idempotent ingestion
- Load raw extraction artifacts into DuckDB
- Generate operational ingestion artifacts

---

# Planned Roadmap
- Near-term roadmap
- - Build dbt project structure
- - Create normalized staging models
- - Add dbt tests and source freshness checks
- - Add schema validation contracts
- - Add reconciliation checks
- - uild canonical order-level marts
- Mid-term roadmap
- - Add orchestration layer
- - Add Dockerized execution
- - Add incremental warehouse ingestion
- - Add semantic AI querying layer
- - Add anomaly detection and forecasting


---

# Technology Stack
- OpenAI API
- PyMuPDF
- DuckDB
- dbt
- Python
- Airflow / Dagster (planned)
- Docker (planned)

---

# Additional Documentation

Detailed architecture and ingestion design documentation:

docs/architecture.md
