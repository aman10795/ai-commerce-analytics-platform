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
    contains_food_or_product_items,
        contains_platform_fees,
        contains_delivery_charges,
        contains_tips,
        contains_discounts,
        contains_taxes,
        contains_deposits,
        contains_refunds,
        contains_subscription_benefits,
        contains_payment_information,
        contains_alcohol,
        contains_grocery,
        contains_restaurant_food,
        contains_pharmacy,
        contains_convenience_items,
        order_category,
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

Select o.*,
-- time context
cast(o.order_timestamp as date) as order_date,
d.year,
d.month,
d.week_of_year,
d.week_of_month,
d.day_of_month,

-- residence context
a.address_id as residence_address_id,
a.city as residence_city,
a.postcode as residence_postcode,

-- career context
c.career_stage

 from orders o
left join {{ ref('dim_date') }} d
    on cast(o.order_timestamp as date) = d.date_day

left join {{ ref('wolt_addresses') }} a
    on cast(o.order_timestamp as date)
       between cast(a.valid_from as date)
       and coalesce(cast(a.valid_to as date), date '9999-12-31')

left join {{ ref('career_trajectory') }} c
    on cast(o.order_timestamp as date)
       between cast(c.valid_from as date)
       and coalesce(cast(c.valid_to as date), date '9999-12-31')