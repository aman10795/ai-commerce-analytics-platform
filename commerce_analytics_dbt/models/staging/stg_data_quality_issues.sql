with source as (

    select *
    from {{ source('raw', 'raw_document_extractions') }}

),

missing_fields as (

    select
        s.document_id,
        s.pdf_hash,
        s.json_hash,
        s.raw_json->'transaction_identity'->>'order_id' as order_id,
        'missing_critical_field' as issue_type,
        CAST(m.value AS VARCHAR) as issue_value

    from source s,
    json_each(s.raw_json, '$.data_quality.missing_critical_fields') as m

),

ambiguous_fields as (

    select
        s.document_id,
        s.pdf_hash,
        s.json_hash,
        s.raw_json->'transaction_identity'->>'order_id' as order_id,
        'ambiguous_field' as issue_type,
        CAST(a.value AS VARCHAR) as issue_value

    from source s,
    json_each(s.raw_json, '$.data_quality.ambiguous_fields') as a

),

parsing_issues as (

    select
        s.document_id,
        s.pdf_hash,
        s.json_hash,
        s.raw_json->'transaction_identity'->>'order_id' as order_id,
        'possible_parsing_issue' as issue_type,
        CAST(p.value AS VARCHAR) as issue_value

    from source s,
    json_each(s.raw_json, '$.data_quality.possible_parsing_issues') as p

)

select * from missing_fields
union all
select * from ambiguous_fields
union all
select * from parsing_issues