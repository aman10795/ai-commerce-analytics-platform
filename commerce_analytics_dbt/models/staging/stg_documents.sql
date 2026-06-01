with source as (

    select *
    from {{ source('raw', 'raw_document_extractions') }}

)

select
    document_id,
    run_id,
    pdf_hash,
    json_hash,
    pdf_file_name,
    pdf_path,
    extraction_file_name,
    extraction_file_path,
    loaded_at,

    raw_json->'extraction_metadata'->>'source_platform' as source_platform,
    raw_json->'extraction_metadata'->>'document_type' as document_type,
    raw_json->'extraction_metadata'->>'document_pattern' as document_pattern,
    try_cast(raw_json->'extraction_metadata'->>'document_type_confidence' as double) as document_type_confidence,
    raw_json->'extraction_metadata'->>'document_language' as document_language,
    raw_json->'extraction_metadata'->>'country_or_market' as country_or_market,
    raw_json->'extraction_metadata'->>'currency' as currency,

    raw_json->'document_identity'->>'document_number' as document_number,
    raw_json->'document_identity'->>'document_label' as document_label,
    try_cast(raw_json->'document_identity'->>'document_date' as timestamp) as document_date,
    raw_json->'document_identity'->>'document_role' as document_role,

    raw_json->'transaction_identity'->>'order_id' as order_id,
    raw_json->'transaction_identity'->>'transaction_id' as transaction_id,
    raw_json->'transaction_identity'->>'payment_id' as payment_id,
    raw_json->'transaction_identity'->>'external_reference_id' as external_reference_id,
    raw_json->'transaction_identity'->>'merge_key' as merge_key,

    raw_json->'transaction_context'->>'customer_name' as customer_name,
    raw_json->'transaction_context'->>'order_type' as order_type,
    try_cast(raw_json->'transaction_context'->>'order_timestamp' as timestamp) as order_timestamp,
    try_cast(raw_json->'transaction_context'->>'delivery_timestamp' as timestamp) as delivery_timestamp,
    try_cast(raw_json->'transaction_context'->>'pickup_timestamp' as timestamp) as pickup_timestamp,
    raw_json->'transaction_context'->>'venue_name' as venue_name,
    raw_json->'transaction_context'->>'merchant_legal_name' as merchant_legal_name,
    raw_json->'transaction_context'->>'platform_legal_name' as platform_legal_name,
    raw_json->'transaction_context'->>'seller_legal_name' as seller_legal_name,
    raw_json->'transaction_context'->>'delivery_provider' as delivery_provider,
    raw_json->'transaction_context'->>'payment_method' as payment_method,

    raw_json->'order_classification'->>'order_category' as order_category,
    try_cast(raw_json->'order_classification'->>'order_category_confidence' as double) as order_category_confidence,

    try_cast(raw_json->'amount_summary'->>'document_total_amount' as double) as document_total_amount,
    try_cast(raw_json->'amount_summary'->>'items_total_amount' as double) as items_total_amount,
    try_cast(raw_json->'amount_summary'->>'fees_total_amount' as double) as fees_total_amount,
    try_cast(raw_json->'amount_summary'->>'delivery_total_amount' as double) as delivery_total_amount,
    try_cast(raw_json->'amount_summary'->>'tip_total_amount' as double) as tip_total_amount,
    try_cast(raw_json->'amount_summary'->>'discount_total_amount' as double) as discount_total_amount,
    try_cast(raw_json->'amount_summary'->>'tax_total_amount' as double) as tax_total_amount,
    try_cast(raw_json->'amount_summary'->>'deposit_total_amount' as double) as deposit_total_amount,
    try_cast(raw_json->'amount_summary'->>'refund_total_amount' as double) as refund_total_amount,
    try_cast(raw_json->'amount_summary'->>'amount_paid' as double) as amount_paid,

    try_cast(raw_json->'document_content_flags'->>'contains_food_or_product_items' as boolean) as contains_food_or_product_items,
    try_cast(raw_json->'document_content_flags'->>'contains_platform_fees' as boolean) as contains_platform_fees,
    try_cast(raw_json->'document_content_flags'->>'contains_delivery_charges' as boolean) as contains_delivery_charges,
    try_cast(raw_json->'document_content_flags'->>'contains_tips' as boolean) as contains_tips,
    try_cast(raw_json->'document_content_flags'->>'contains_discounts' as boolean) as contains_discounts,
    try_cast(raw_json->'document_content_flags'->>'contains_taxes' as boolean) as contains_taxes,
    try_cast(raw_json->'document_content_flags'->>'contains_deposits' as boolean) as contains_deposits,
    try_cast(raw_json->'document_content_flags'->>'contains_refunds' as boolean) as contains_refunds,
    try_cast(raw_json->'document_content_flags'->>'contains_subscription_benefits' as boolean) as contains_subscription_benefits,
    try_cast(raw_json->'document_content_flags'->>'contains_payment_information' as boolean) as contains_payment_information,

    try_cast(raw_json->'data_quality'->>'requires_merge_with_other_documents' as boolean) as requires_merge_with_other_documents,
    raw_json->'data_quality'->>'merge_reason' as merge_reason

from source