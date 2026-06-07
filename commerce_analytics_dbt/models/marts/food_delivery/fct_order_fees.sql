/*
    Gold fact table: fct_order_fees
    Grain: one row per fee, tip, discount, deposit, refund, or tax component.
*/
{{ config(
    materialized='incremental',
    unique_key='order_fee_key',
    incremental_strategy='delete+insert'
) }}


select
    {{ dbt_utils.generate_surrogate_key([
    'source_platform',
    'food_delivery_order_key'
]) }} as order_key,

    {{ dbt_utils.generate_surrogate_key([
    'food_delivery_order_key',
    'document_id',
    'component_index'
]) }} as order_fee_key,

    document_id,
    component_index as fee_index,

    component_name as fee_name,
    component_type,
    component_subtype,
    food_delivery_component_group,

    gross_amount,
    net_amount,
    tax_rate,
    tax_amount,
    currency,

    is_discount,
    is_refund,
    extraction_confidence,
    latest_loaded_at

from {{ ref('int_food_delivery_components') }}

where (is_fee_component = true
   or food_delivery_component_group in (
        'discount',
        'deposit',
        'refund',
        'tax',
        'other_fee'
   )
)
{% if is_incremental() %}
and latest_loaded_at > (
    select coalesce(max(latest_loaded_at), timestamp '1900-01-01')
    from {{ this }}
)
{% endif %}