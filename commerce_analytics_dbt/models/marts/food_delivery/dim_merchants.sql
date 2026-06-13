

/*
    Gold dimension: dim_merchants
    Grain: one row per merchant per platform.
*/

with orders as (

    select *
    from {{ ref('fct_orders') }}

)

select
    {{ dbt_utils.generate_surrogate_key([
    'source_platform',
    'merchant_name'
]) }} as merchant_key,
    source_platform,

    merchant_name,
    merchant_legal_name,

    min(order_date) as first_order_date,
    max(order_date) as last_order_date,

    count(distinct order_key) as merchant_order_count,
    sum(calculated_order_total_amount) as lifetime_spend,

    sum(items_total_amount) as lifetime_items_total,
    sum(fees_total_amount) as lifetime_fees_total,
    sum(delivery_total_amount) as lifetime_delivery_total,
    sum(tip_total_amount) as lifetime_tip_total,
    sum(discount_total_amount) as lifetime_discount_total,
    sum(refund_total_amount) as lifetime_refund_total,

    max(latest_loaded_at) as latest_loaded_at

from orders

where merchant_key is not null

group by
    merchant_key,
    source_platform,
    merchant_name,
    merchant_legal_name