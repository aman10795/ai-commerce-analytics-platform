

```markdown
# Architecture Overview

## Architectural Philosophy

The platform is intentionally designed as an AI-native analytics engineering system rather than a simple invoice extraction pipeline.

The architecture separates:
- semantic extraction
- deterministic business logic
- warehouse modeling
- operational observability
- lineage and replayability

This prevents:
- prompt bloat
- business logic leakage into AI prompts
- brittle extraction systems
- provider-specific hardcoding

---

# Core Architecture

```text
PDF invoices
    ↓
PDF text extraction
    ↓
transaction text cleaning
    ↓
AI semantic extraction
    ↓
raw AI extraction artifacts (Bronze)
    ↓
DuckDB raw ingestion layer
    ↓
dbt staging models (Silver)
    ↓
canonical analytics marts (Gold)
    ↓
semantic metrics / AI querying


```



# AI Extraction Layer

The extraction layer uses AI-assisted semantic extraction rather than rigid template-based OCR systems.

The extraction system:

- classifies document types dynamically
- extracts semantic transaction components
- identifies entities and relationships
- infers component categories
- preserves evidence and confidence information
- remains resilient to document-layout drift

The extraction layer intentionally avoids:

- provider-specific regex-only extraction
- brittle invoice templates
- rigid schema assumptions


# Platform-Agnostic Ingestion

Instead of building separate pipelines for:
- Wolt
- Uber Eats
- Flink
- DoorDash

the system extracts normalized semantic concepts such as:
- products
- modifiers
- taxes
- delivery fees
- platform fees
- discounts
- refunds
- deposits

This allows the warehouse layer to absorb:
- schema drift
- provider changes
- layout changes
- future platforms

without major extraction redesign.


# DuckDB Raw Ingestion Layer

The DuckDB ingestion layer acts as the warehouse's bronze ingestion system.

Responsibilities include:
- raw artifact ingestion
- lineage tracking
- idempotent loading
- extraction version detection
- ingestion auditing
- operational logging

The warehouse stores:
- source PDF hashes
- extraction JSON hashes
- ingestion timestamps
- processing metadata
- raw extraction payloads
- Content-Based Idempotency

The ingestion pipeline uses SHA256 hashes of source PDFs as stable document identifiers.

This prevents:
- duplicate processing
- duplicate warehouse records
- repeated LLM inference costs

The platform separately tracks extraction JSON hashes to detect:
- prompt changes
- extraction changes
- model-version changes


# Medallion-Style Warehouse Design

The platform follows a layered warehouse architecture.

# Bronze Layer

Contains:
- raw PDFs
- raw AI extraction artifacts
- raw ingestion metadata

# Silver Layer

Contains:
- normalized staging models
- flattened extraction structures
- cleaned component models
- canonical entity mappings

Implemented using dbt staging models.

# Gold Layer

Contains:
- canonical analytics marts
- -semantic business metrics
- reporting-ready datasets
- future ML-ready feature structures


# Separation of AI and Business Logic

The AI layer is responsible for:

- semantic extraction
- entity detection
- schema discovery
- flexible classification

The dbt layer is responsible for:

- deterministic transformations
- business rules
- metric definitions
- trusted analytics logic
- testing and validation

This prevents business logic from becoming embedded inside prompts.