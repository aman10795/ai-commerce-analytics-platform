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

    try_cast(t.key as integer) as tax_index,
    t.value->>'tax_type' as tax_type,
    try_cast(t.value->>'tax_rate' as double) as tax_rate,
    try_cast(t.value->>'taxable_net_amount' as double) as taxable_net_amount,
    try_cast(t.value->>'tax_amount' as double) as tax_amount,
    try_cast(t.value->>'gross_amount' as double) as gross_amount,
    t.value->>'source_evidence' as source_evidence,
    try_cast(t.value->>'source_page' as integer) as source_page,
    try_cast(t.value->>'extraction_confidence' as double) as extraction_confidence

from source s,
json_each(s.raw_json, '$.tax_breakdown') as t