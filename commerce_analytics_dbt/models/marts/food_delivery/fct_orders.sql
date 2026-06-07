/*
    Gold fact table: fct_orders
    Grain: one row per food-delivery order.
*/

{{ config(
    materialized='incremental',
    unique_key='order_key',
    incremental_strategy='delete+insert'
) }}

with orders as (
select
    {{ dbt_utils.generate_surrogate_key([
    'source_platform',
    'food_delivery_order_key'
]) }} as order_key,

    {{ dbt_utils.generate_surrogate_key([
    'source_platform',
    'venue_name'
]) }} as merchant_key,

    
    food_delivery_order_key as natural_order_key,
    order_id,
    source_platform,
    order_timestamp,
    delivery_timestamp,
    venue_name as merchant_name,
    merchant_legal_name,
    payment_method,
    currency,
    country_or_market,

    items_total_amount,
    fees_total_amount,
    delivery_total_amount,
    tip_total_amount,
    discount_total_amount,
    tax_total_amount,
    deposit_total_amount,
    refund_total_amount,

    (
        items_total_amount
        + fees_total_amount
        + delivery_total_amount
        + tip_total_amount
        + tax_total_amount
        + deposit_total_amount
        + refund_total_amount
        + discount_total_amount
    ) as calculated_order_total_amount,

    source_document_count,
    latest_loaded_at

from {{ ref('int_food_delivery_orders') }}
{% if is_incremental() %}

        where latest_loaded_at > (
            select coalesce(max(latest_loaded_at), timestamp '1900-01-01')
            from {{ this }}
        )

    {% endif %}

)

Select * from orders