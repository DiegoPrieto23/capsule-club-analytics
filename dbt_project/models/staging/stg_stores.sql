with source as (select * from {{ source('raw', 'raw_stores') }})

select
    cast(store_id as varchar)   as store_id,
    cast(city as varchar)       as city,
    cast(opening_date as date)  as opening_date
from source
