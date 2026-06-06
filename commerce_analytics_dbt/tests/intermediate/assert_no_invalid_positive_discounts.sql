select *
from {{ ref('int_food_delivery_components') }}
where food_delivery_component_group = 'discount'
  and gross_amount > 0