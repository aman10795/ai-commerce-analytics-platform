with source as (

    select *
    from {{ source('raw', 'raw_document_extractions') }}

)

select
    s.document_id,
    s.pdf_hash,
    s.json_hash,
    s.raw_json->'transaction_identity'->>'order_id' as order_id,
    s.raw_json->'transaction_identity'->>'merge_key' as merge_key,

    try_cast(e.key as integer) as entity_index,
    e.value->>'entity_name' as entity_name,
    e.value->>'entity_type' as entity_type,
    e.value->>'legal_identifier' as legal_identifier,
    e.value->>'vat_id' as vat_id,
    e.value->>'business_id' as business_id,
    e.value->>'address' as address,
    e.value->>'source_evidence' as source_evidence,
    try_cast(e.value->>'source_page' as integer) as source_page,
    try_cast(e.value->>'extraction_confidence' as double) as extraction_confidence

from source s,
json_each(s.raw_json, '$.entities') as e