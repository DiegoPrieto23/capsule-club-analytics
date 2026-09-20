with source as (select * from {{ source('raw', 'raw_payments') }})

select
    cast(payment_id as varchar)         as payment_id,
    cast(subscription_id as varchar)    as subscription_id,
    cast(payment_date as date)          as payment_date,
    {{ to_month('payment_date') }}      as payment_month,
    cast(amount as double)              as amount_eur,
    cast(status as varchar)             as status,
    -- retried_success sí entró en caja; failed no.
    status in ('success', 'retried_success') as is_collected
from source
