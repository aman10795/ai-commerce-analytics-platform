/*
    Gold dimension table: dim_merchants
    Grain: one row per merchant name.
*/

select
    {{ dbt_utils.generate_surrogate_key([
    'source_platform',
    'merchant_name'
]) }} as merchant_key,

    merchant_name,
    max(merchant_legal_name) as merchant_legal_name,
    max(source_platform) as source_platform,
    max(country_or_market) as country_or_market,
    count(distinct order_key) as order_count,
    max(latest_loaded_at) as latest_loaded_at

from {{ ref('fct_orders') }}

where merchant_name is not null

group by 1, 2