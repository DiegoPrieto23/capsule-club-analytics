with source as (select * from {{ source('raw', 'raw_machine_orders') }})

select
    cast(order_id as varchar)                   as machine_order_id,
    cast(customer_id as varchar)                as customer_id,
    cast(machine_model_id as varchar)           as machine_model_id,
    cast(order_date as date)                    as order_date,
    {{ to_month('order_date') }}                as order_month,
    {{ normalize_sales_channel('channel') }}    as channel,
    cast(store_id as varchar)                   as store_id,
    cast(price_paid as double)                  as price_paid_eur,
    cast(bundled_capsules_trial as boolean)     as has_bundled_capsules_trial,
    customer_id is not null                     as is_identified_customer
from source
