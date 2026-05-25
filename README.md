# AI Commerce Analytics Platform

An AI-native analytics engineering project for extracting, structuring, and modeling transaction documents from food delivery, grocery delivery, and quick-commerce platforms.

## Project Goal

This project builds a small but scalable analytics platform that can ingest transaction documents such as invoices, receipts, order confirmations, and fee invoices.

The platform starts with PDF invoice extraction and will evolve into a warehouse-style analytics system using dbt.

## Current Scope

Current MVP:

- Read invoice PDFs from a local folder
- Extract transaction-specific text from PDFs
- Remove noisy legal / terms-and-conditions sections
- Use OpenAI API for structured document extraction
- Classify transaction documents in a platform-agnostic way
- Extract components such as:
  - product items
  - modifiers
  - delivery fees
  - service fees
  - discounts
  - tips
  - deposits
  - taxes
- Store output as JSON files

## Architecture

```text
PDF invoices
    ↓
PDF text extraction
    ↓
transaction text cleaning
    ↓
OpenAI structured extraction
    ↓
JSON outputs
    ↓
raw database layer
    ↓
dbt staging models
    ↓
canonical analytics models
```


## Key Design Principles
- Keep extraction flexible and platform-agnostic
- Do not hardcode platform-specific invoice formats
- Preserve raw evidence and confidence scores
- Store missing values as null
- Keep business rules and canonical modeling in dbt, not in the extraction prompt
- Use AI for semantic extraction and classification
- Use dbt for deterministic transformation, testing, and trusted analytics logic


## Next Planned Steps
- Batch process all invoices in the input folder
- Store JSON outputs in a raw database table
- Set up DuckDB as the local warehouse
- Add dbt project structure
- Build staging models:
- - stg_documents
- - stg_components
- - stg_entities
- - stg_tax_breakdown
- Add dbt tests
- Build canonical order-level models
- Add Docker and orchestration later
