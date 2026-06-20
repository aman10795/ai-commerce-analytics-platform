# Architecture Overview

## Architectural Philosophy

The platform is intentionally designed as an AI-native analytics engineering system rather than a simple invoice extraction pipeline.

The architecture separates:

* semantic extraction
* deterministic business logic
* warehouse modeling
* operational observability
* semantic governance
* AI analytics consumption
* lineage and replayability

This prevents:

* prompt bloat
* business logic leakage into AI prompts
* brittle extraction systems
* provider-specific hardcoding
* metric definition duplication
* uncontrolled AI-generated SQL

---

# End-to-End Architecture

```text
PDF invoices / JSON exports / CSV exports
                    ↓
            PDF Text Extraction
                    ↓
          Transaction Text Cleaning
                    ↓
          AI Semantic Extraction
                    ↓
      Raw Extraction Artifacts (Bronze)
                    ↓
           DuckDB Ingestion Layer
                    ↓
         dbt Staging Models (Silver)
                    ↓
       dbt Analytics Marts (Gold)
                    ↓
          dbt Semantic Layer
                    ↓
               MetricFlow
                    ↓
          AI Query Planner
                    ↓
       AI Analytics Assistant
                    ↓
             Streamlit UI
```

---

# AI Extraction Layer

The extraction layer uses AI-assisted semantic extraction rather than rigid template-based OCR systems.

The extraction system:

* classifies document types dynamically
* extracts semantic transaction components
* identifies entities and relationships
* infers component categories
* preserves evidence and confidence information
* remains resilient to document-layout drift

The extraction layer intentionally avoids:

* provider-specific regex-only extraction
* brittle invoice templates
* rigid schema assumptions

---

# Platform-Agnostic Ingestion

Instead of building separate pipelines for:

* Wolt
* Uber Eats
* Flink
* DoorDash

the system extracts normalized semantic concepts such as:

* products
* modifiers
* taxes
* delivery fees
* platform fees
* discounts
* refunds
* deposits

This allows the warehouse layer to absorb:

* schema drift
* provider changes
* layout changes
* future platforms

without major extraction redesign.

---

# DuckDB Raw Ingestion Layer

The DuckDB ingestion layer acts as the warehouse's bronze ingestion system.

Responsibilities include:

* raw artifact ingestion
* lineage tracking
* idempotent loading
* extraction version detection
* ingestion auditing
* operational logging

The warehouse stores:

* source PDF hashes
* extraction JSON hashes
* ingestion timestamps
* processing metadata
* raw extraction payloads

---

# Content-Based Idempotency

The ingestion pipeline uses SHA256 hashes of source PDFs as stable document identifiers.

This prevents:

* duplicate processing
* duplicate warehouse records
* repeated LLM inference costs

The platform separately tracks extraction JSON hashes to detect:

* prompt changes
* extraction changes
* model-version changes

---

# Medallion-Style Warehouse Design

The platform follows a layered warehouse architecture.

## Bronze Layer

Contains:

* raw PDFs
* raw AI extraction artifacts
* raw ingestion metadata

## Silver Layer

Contains:

* normalized staging models
* flattened extraction structures
* cleaned component models
* canonical entity mappings

Implemented using dbt staging and intermediate models.

## Gold Layer

Contains:

* canonical analytics marts
* reporting-ready datasets
* business entities
* reusable analytical dimensions
* ML-ready feature structures

Examples:

* fct_orders
* fct_order_lines
* fct_order_fees
* dim_merchants
* dim_date

---

# Semantic Analytics Layer

The Gold layer is exposed through the dbt Semantic Layer and MetricFlow.

Rather than querying warehouse tables directly, analytics consumers interact with governed business metrics.

The semantic layer defines:

* entities
* dimensions
* measures
* metrics
* time semantics

Examples include:

* order_count
* total_spend
* average_order_value
* merchant_count
* merchant_lifetime_spend
* merchant_average_order_value
* delivery_fee_ratio
* discount_ratio
* refund_ratio

Benefits:

* centralized metric definitions
* reusable business logic
* consistent KPI calculations
* semantic governance
* dashboard consistency
* AI-ready analytical interfaces

The semantic layer becomes the contract between warehouse models and downstream analytical applications.

---

# AI Analytics Assistant

The platform includes an AI-powered analytics assistant built on top of the semantic layer.

Instead of generating SQL directly, the assistant:

1. interprets natural language questions
2. decomposes complex requests
3. converts questions into semantic query plans
4. validates metrics and dimensions
5. discovers valid dimension values dynamically
6. normalizes user inputs
7. executes MetricFlow queries
8. generates business-friendly explanations

Example:

User:

> How many orders did I have in Berlin with alcohol?

AI Query Plan:

* metric: order_count
* filters:

  * residence_city = Berlin
  * contains_alcohol = true

MetricFlow then executes the query against governed semantic definitions.

This architecture provides:

* governed analytics
* semantic consistency
* explainable query generation
* reduced hallucinations
* reusable business logic
* AI-safe metric access

Current capabilities include:

* natural language querying
* semantic query planning
* MetricFlow execution
* dynamic dimension discovery
* fuzzy value resolution
* multi-question decomposition
* AI-generated explanations

---

# Orchestration Layer

The platform uses Apache Airflow to orchestrate ingestion and transformation workflows.

Current orchestration responsibilities include:

* extraction execution
* warehouse loading
* dbt seed execution
* snapshot execution
* model builds
* data quality testing

The orchestration layer remains separate from the AI analytics assistant.

Airflow produces trusted analytical datasets while the AI assistant consumes them.

---

# Separation of AI and Business Logic

The AI layer is responsible for:

* semantic extraction
* entity detection
* schema discovery
* flexible classification
* natural language understanding

The dbt layer is responsible for:

* deterministic transformations
* business rules
* metric definitions
* trusted analytics logic
* testing and validation

MetricFlow is responsible for:

* semantic query generation
* metric governance
* reusable analytical definitions

This separation ensures that business logic remains version-controlled, testable, and explainable rather than becoming embedded inside prompts.

---

# Technology Stack

## Data Platform

* Python
* DuckDB
* dbt
* Apache Airflow

## AI Layer

* OpenAI API
* Semantic Query Planner
* Natural Language Analytics Assistant

## Analytics Layer

* dbt Semantic Layer
* MetricFlow

## Application Layer

* Streamlit

## Data Processing

* Pandas
* PyMuPDF
* JSON-based extraction framework

---

# Future Roadmap

## Completed

* AI semantic extraction
* DuckDB warehouse
* dbt staging models
* dbt intermediate models
* dbt marts
* snapshots (SCD Type 2)
* Airflow orchestration
* semantic layer
* MetricFlow metrics
* AI analytics assistant
* Streamlit interface

## Planned

* forecasting layer
* merchant intelligence
* marketing analytics
* automatic chart generation
* AI dashboard generation
* Docker deployment
* Streamlit Cloud deployment
* production monitoring
* multi-agent analytics workflows
* AI-powered insight generation
