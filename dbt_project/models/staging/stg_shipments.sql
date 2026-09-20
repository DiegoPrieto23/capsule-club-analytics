with source as (select * from {{ source('raw', 'raw_shipments') }})

select
    cast(shipment_id as varchar)        as shipment_id,
    cast(subscription_id as varchar)    as subscription_id,
    cast(ship_date as date)             as ship_date,
    {{ to_month('ship_date') }}         as ship_month,
    cast(capsule_sku as varchar)        as capsule_sku,
    cast(quantity as integer)           as quantity,
    cast(cost as double)                as shipment_value_eur,
    cast(on_time as boolean)            as is_on_time
from source
