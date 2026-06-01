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

    try_cast(f.key as integer) as detected_field_index,
    f.value->>'field_label' as field_label,
    f.value->>'field_value' as field_value,
    f.value->>'field_category' as field_category,
    f.value->>'normalized_candidate_name' as normalized_candidate_name,
    f.value->>'source_evidence' as source_evidence,
    try_cast(f.value->>'source_page' as integer) as source_page,
    try_cast(f.value->>'extraction_confidence' as double) as extraction_confidence

from source s,
json_each(s.raw_json, '$.raw_detected_fields') as f