with source as (select * from {{ source('raw', 'raw_machines') }})

select
    cast(machine_model_id as varchar)   as machine_model_id,
    cast(name as varchar)               as machine_name,
    cast(launch_date as date)           as launch_date,
    cast(discontinue_date as date)      as discontinue_date,
    cast(price as double)               as list_price_eur
from source
