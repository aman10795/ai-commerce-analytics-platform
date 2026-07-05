with source as (

    select *
    from {{ source('raw', 'raw_document_extractions') }}

),

flattened as (

    select
        s.document_id,
        s.pdf_hash,
        s.json_hash,
        s.raw_json->'transaction_identity'->>'order_id' as order_id,
        s.raw_json->'transaction_identity'->>'merge_key' as merge_key,
        raw_json->'extraction_metadata'->>'source_platform' as source_platform,
        try_cast(c.key as integer) as component_index,
        c.value->>'component_name' as component_name,
        c.value->>'component_type' as component_type,
        c.value->>'component_subtype' as component_subtype,
        try_cast(c.value->>'quantity' as double) as quantity,
        try_cast(c.value->>'unit_price' as double) as unit_price,
        coalesce(
        try_cast(c.value->>'gross_amount' as double),
        Coalesce(try_cast(c.value->>'unit_price' as double),'0') * coalesce(try_cast(c.value->>'quantity' as double), 1)
        ) as gross_amount,        
        try_cast(c.value->>'net_amount' as double) as net_amount,
        try_cast(c.value->>'tax_rate' as double) as tax_rate,
        try_cast(c.value->>'tax_amount' as double) as tax_amount,
        c.value->>'currency' as currency,
        try_cast(c.value->>'is_discount' as boolean) as is_discount,
        try_cast(c.value->>'is_refund' as boolean) as is_refund,
        c.value->>'parent_component' as parent_component,
        c.value->>'source_evidence' as source_evidence,
        try_cast(c.value->>'source_page' as integer) as source_page,
        try_cast(c.value->>'extraction_confidence' as double) as extraction_confidence,
        loaded_at
    from source s,
    json_each(s.raw_json, '$.components') as c

)

select *
from flattened