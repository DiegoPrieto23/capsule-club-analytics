with source as (select * from {{ source('raw', 'raw_products') }})

select
    cast(product_sku as varchar)        as product_sku,
    cast(product_type as varchar)       as product_type,
    cast(flavor as varchar)             as flavor,
    cast(launch_date as date)           as launch_date,
    cast(discontinue_date as date)      as discontinue_date,
    cast(replaced_by_sku as varchar)    as replaced_by_sku,
    cast(unit_price as double)          as list_unit_price_eur,
    discontinue_date is not null        as is_discontinued,
    replaced_by_sku is not null         as was_replaced
from source
