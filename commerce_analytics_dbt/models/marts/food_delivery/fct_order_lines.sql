/*
    Gold fact table: fct_order_lines
    Grain: one row per purchased item or modifier.

    This fact is item/product-level, but it deliberately carries the
    foreign order and merchant entities so MetricFlow can join item metrics
    to order-level and merchant-level dimensions.
*/

{{ config(
    materialized='incremental',
    unique_key='order_line_key',
    incremental_strategy='delete+insert'
) }}

with order_lines as (

    select
        {{ dbt_utils.generate_surrogate_key([
            'c.food_delivery_order_key',
            'c.document_id',
            'c.component_index'
        ]) }} as order_line_key,

        {{ dbt_utils.generate_surrogate_key([
            'c.source_platform',
            'c.food_delivery_order_key'
        ]) }} as order_key,

        c.document_id,
        c.component_index as order_line_index,

        c.component_name as item_name,
        c.component_type,
        c.component_subtype,
        c.food_delivery_component_group,

        c.quantity,
        c.unit_price,
        c.gross_amount,
        c.net_amount,
        c.tax_rate,
        c.tax_amount,
        c.currency,

        c.parent_component,
        c.extraction_confidence,
        c.latest_loaded_at

    from {{ ref('int_food_delivery_components') }} c

    where c.is_order_line_component = true

),

orders as (

    select
        order_key,
        merchant_key,
        natural_order_key,
        order_id,
        source_platform,
        order_timestamp,
        order_date,
        merchant_name,
        country_or_market,
        order_category,
        contains_alcohol,
        contains_grocery,
        contains_restaurant_food,
        contains_pharmacy,
        contains_convenience_items,
        residence_city,
        career_stage

    from {{ ref('fct_orders') }}

),

final as (

    select
        l.order_line_key,
        l.order_key,
        o.merchant_key,

        l.document_id,
        l.order_line_index,

        o.natural_order_key,
        o.order_id,
        o.source_platform,
        o.order_timestamp,
        o.order_date,

        o.merchant_name,
        o.country_or_market,
        o.order_category,
        o.contains_alcohol,
        o.contains_grocery,
        o.contains_restaurant_food,
        o.contains_pharmacy,
        o.contains_convenience_items,
        o.residence_city,
        o.career_stage,

        l.item_name,
        l.component_type,
        l.component_subtype,
        l.food_delivery_component_group,

        coalesce(l.quantity, 1) as quantity,
        l.unit_price,
        l.gross_amount,
        l.net_amount,
        l.tax_rate,
        l.tax_amount,
        l.currency,

        l.parent_component,
        l.extraction_confidence,
        l.latest_loaded_at

    from order_lines l
    left join orders o
        on l.order_key = o.order_key

),

filtered as (

    select *
    from final

    {% if is_incremental() %}
        where latest_loaded_at > (
            select coalesce(max(latest_loaded_at), timestamp '1900-01-01')
            from {{ this }}
        )
    {% endif %}

)

select *
from filtered
