with source as (select * from {{ source('raw', 'raw_subscription_events') }})

select
    cast(event_id as varchar)           as event_id,
    cast(subscription_id as varchar)    as subscription_id,
    cast(event_type as varchar)         as event_type,
    cast(event_date as date)            as event_date,
    {{ to_month('event_date') }}        as event_month,
    cast(previous_plan as varchar)      as previous_plan,
    cast(new_plan as varchar)           as new_plan,
    -- Pausar no es cancelar, y un fallo de cobro tampoco: agrupar los eventos
    -- por familia evita que el análisis los cuente todos como churn.
    case
        when event_type in ('paused', 'resumed')                    then 'lifecycle_pause'
        when event_type in ('upgraded', 'downgraded')               then 'plan_change'
        when event_type in ('payment_failed', 'payment_retried_ok') then 'dunning'
        when event_type = 'cancelled'                               then 'churn'
        else 'creation'
    end as event_family
from source
