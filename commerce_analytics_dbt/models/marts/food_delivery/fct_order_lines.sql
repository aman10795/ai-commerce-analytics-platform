/*
    Gold fact table: fct_order_lines
    Grain: one row per purchased item or modifier.
*/

{{ config(
    materialized='incremental',
    unique_key='order_line_key',
    incremental_strategy='delete+insert'
) }}

with final as (

    select
        {{ dbt_utils.generate_surrogate_key([
            'food_delivery_order_key',
            'document_id',
            'component_index'
        ]) }} as order_line_key,

        {{ dbt_utils.generate_surrogate_key([
            'source_platform',
            'food_delivery_order_key'
        ]) }} as order_key,

        document_id,
        component_index as order_line_index,

        component_name as item_name,
        component_type,
        component_subtype,
        food_delivery_component_group,

        quantity,
        unit_price,
        gross_amount,
        net_amount,
        tax_rate,
        tax_amount,
        currency,

        parent_component,
        extraction_confidence,
        latest_loaded_at

    from {{ ref('int_food_delivery_components') }}

    where is_order_line_component = true

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