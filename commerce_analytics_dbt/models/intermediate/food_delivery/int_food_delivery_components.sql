/*
    Model: int_food_delivery_components

    Purpose:
    Interpret generic extracted transaction components as food-delivery
    business components.

    Why this model exists:
    The Silver model stg_components is source/extraction-oriented.
    It stores whatever the AI extracted from the document.

    This Intermediate model adds food-delivery business meaning:
      - item
      - modifier
      - delivery_fee
      - service_fee
      - tip
      - discount
      - deposit
      - refund
      - tax
      - other_fee
      - unknown

    Grain:
    One row per extracted food-delivery component.
*/

with components as (

    select
        document_id,
        order_id,
        merge_key,

        coalesce(merge_key, order_id) as food_delivery_order_key,
        source_platform,
        component_index,
        component_name,
        component_type,
        component_subtype,

        quantity,
        unit_price,
        gross_amount,
        net_amount,
        tax_rate,
        tax_amount,
        currency,

        is_discount,
        is_refund,
        parent_component,

        source_evidence,
        source_page,
        extraction_confidence

    from {{ ref('stg_components') }}

),
max_loaddate as (

    select document_id, max(loaded_at) as latest_loaded_at
    from {{ ref('stg_components') }}
    group by document_id
),

classified as (

    select
        *,

        /*
            Normalize extracted component types into food-delivery business groups.

            This is intentionally handled in Intermediate, not Silver:
            - Silver preserves the extraction contract.
            - Intermediate applies business interpretation.
        */
        case
            when component_type in ('product_item', 'food_item', 'item') then 'item'

            when component_type in ('modifier', 'addon', 'add_on', 'customization') then 'modifier'

            when component_type in ('delivery_fee', 'delivery_charge') then 'delivery_fee'

            when component_type in ('service_fee', 'platform_fee', 'small_order_fee') then 'service_fee'

            when component_type in ('tip', 'courier_tip') then 'tip'

            when component_type in ('discount', 'promotion', 'voucher', 'coupon') 
                 or is_discount = true
                then 'discount'

            when component_type in ('deposit', 'bottle_deposit', 'packaging_deposit') then 'deposit'

            when component_type in ('refund', 'refund_adjustment')
                 or is_refund = true
                then 'refund'

            when component_type in ('tax', 'vat', 'sales_tax') then 'tax'

            when component_type in ('fee', 'other_fee') then 'other_fee'

            else 'unknown'
        end as food_delivery_component_group,

        case
            when component_type in ('product_item', 'food_item', 'item', 'modifier', 'addon', 'add_on', 'customization')
                then true
            else false
        end as is_order_line_component,

        case
            when component_type in (
                'delivery_fee',
                'delivery_charge',
                'service_fee',
                'platform_fee',
                'small_order_fee',
                'tip',
                'courier_tip',
                'fee',
                'other_fee'
            )
                then true
            else false
        end as is_fee_component

    from components

)

select c.*,m.latest_loaded_at
from classified c
left join max_loaddate m using (document_id)