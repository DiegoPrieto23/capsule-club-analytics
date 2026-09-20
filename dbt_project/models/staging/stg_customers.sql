with source as (select * from {{ source('raw', 'raw_customers') }})

select
    cast(customer_id as varchar)                        as customer_id,
    cast(signup_date as date)                           as signup_date,
    -- El canal NULL es una imperfección real (touchpoint de origen no
    -- atribuible): se etiqueta como direct_unknown, pero se conserva la marca
    -- para poder cuantificar el attribution gap más adelante.
    {{ normalize_marketing_channel('acquisition_channel') }} as acquisition_channel,
    acquisition_channel is null                         as has_unknown_acquisition_channel,
    cast(home_store_id as varchar)                      as home_store_id,
    lower(trim(cast(email_raw as varchar)))             as email_clean,
    cast(email_raw as varchar)                          as email_raw
from source
