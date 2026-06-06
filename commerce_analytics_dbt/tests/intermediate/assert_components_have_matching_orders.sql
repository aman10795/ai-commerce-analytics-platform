select c.*
from {{ ref('int_food_delivery_components') }} c
left join {{ ref('int_food_delivery_orders') }} o
    on c.food_delivery_order_key = o.food_delivery_order_key
where o.food_delivery_order_key is null