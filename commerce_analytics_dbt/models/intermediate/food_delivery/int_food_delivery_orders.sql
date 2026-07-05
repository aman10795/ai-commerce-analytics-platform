/*
    Model: int_food_delivery_orders

    Purpose:
    Create one interpreted food-delivery order record from one or more
    extracted transaction documents.

    Why this model exists:
    The Silver layer is document-based. One real-world Wolt order can have
    multiple documents, such as:
      - restaurant/item invoice
      - platform fee invoice
      - refund invoice

    This model groups related documents into a single business order using
    merge_key first and order_id as fallback.

    Grain:
    One row per food-delivery order.
*/

with food_delivery_documents as (

    select
        document_id,
        merge_key,
        order_id,

        source_platform,
        document_type,
        document_pattern,
        document_role,

        customer_name,
        order_type,
        order_timestamp,
        delivery_timestamp,
        pickup_timestamp,

        venue_name,
        merchant_legal_name,
        platform_legal_name,
        seller_legal_name,
        delivery_provider,
        payment_method,

        currency,
        country_or_market,

        order_category,
        order_category_confidence,

        document_total_amount,
        items_total_amount,
        fees_total_amount,
        delivery_total_amount,
        tip_total_amount,
        discount_total_amount,
        tax_total_amount,
        deposit_total_amount,
        refund_total_amount,
        amount_paid,
        contains_alcohol,
        contains_grocery,
        contains_restaurant_food,
        contains_pharmacy,
        contains_convenience_items,

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

        loaded_at

    from {{ ref('stg_documents') }}

),



orders as (

    select
        coalesce(merge_key, order_id) as food_delivery_order_key,

        max(order_id) as order_id,
        max(source_platform) as source_platform,

        min(order_timestamp) as order_timestamp,
        max(delivery_timestamp) as delivery_timestamp,
        max(pickup_timestamp) as pickup_timestamp,

        max(customer_name) as customer_name,
        max(order_type) as order_type,

        max(venue_name) as venue_name,
        max(merchant_legal_name) as merchant_legal_name,
        max(platform_legal_name) as platform_legal_name,
        max(seller_legal_name) as seller_legal_name,
        max(delivery_provider) as delivery_provider,
        max(payment_method) as payment_method,

        max(currency) as currency,
        max(country_or_market) as country_or_market,

        max(order_category) as order_category,
        max(order_category_confidence) as order_category_confidence,

        bool_or(contains_food_or_product_items) as contains_food_or_product_items,
        bool_or(contains_platform_fees) as contains_platform_fees,
        bool_or(contains_delivery_charges) as contains_delivery_charges,
        bool_or(contains_tips) as contains_tips,
        bool_or(contains_discounts) as contains_discounts,
        bool_or(contains_taxes) as contains_taxes,
        bool_or(contains_deposits) as contains_deposits,
        bool_or(contains_refunds) as contains_refunds,
        bool_or(contains_subscription_benefits) as contains_subscription_benefits,
        bool_or(contains_payment_information) as contains_payment_information,
        bool_or(contains_alcohol) as contains_alcohol,
        bool_or(contains_grocery) as contains_grocery,
        bool_or(contains_restaurant_food) as contains_restaurant_food,
        bool_or(contains_pharmacy) as contains_pharmacy,
        bool_or(contains_convenience_items) as contains_convenience_items,

        count(*) as source_document_count,
        count(distinct document_id) as distinct_document_count,

        sum(coalesce(items_total_amount, 0)) as items_total_amount,
        sum(coalesce(fees_total_amount, 0)) as fees_total_amount,
        sum(coalesce(delivery_total_amount, 0)) as delivery_total_amount,
        sum(coalesce(tip_total_amount, 0)) as tip_total_amount,
        sum(coalesce(discount_total_amount, 0)) as discount_total_amount,
        sum(coalesce(tax_total_amount, 0)) as tax_total_amount,
        sum(coalesce(deposit_total_amount, 0)) as deposit_total_amount,
        sum(coalesce(refund_total_amount, 0)) as refund_total_amount,
        max(document_total_amount) as document_total_amount,

        max(loaded_at) as latest_loaded_at

    from food_delivery_documents

    where coalesce(merge_key, order_id) is not null

    group by 1

)

select *
from orders