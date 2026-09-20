with source as (select * from {{ source('raw', 'raw_shop_orders') }})

select
    cast(order_id as varchar)               as order_id,
    cast(customer_id as varchar)            as customer_id,
    cast(order_date as date)                as order_date,
    {{ to_month('order_date') }}            as order_month,
    {{ normalize_sales_channel('channel') }} as channel,
    cast(store_id as varchar)               as store_id,
    -- Venta en boutique sin fidelización: no es atribuible a ningún cliente
    -- ni a ningún canal de marketing. Se marca en vez de descartarse.
    customer_id is not null                 as is_identified_customer
from source
