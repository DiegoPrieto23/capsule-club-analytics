with source as (select * from {{ source('raw', 'raw_subscriptions') }})

select
    cast(subscription_id as varchar)        as subscription_id,
    cast(customer_id as varchar)            as customer_id,
    -- OJO: `plan` en crudo es el plan ACTUAL (ya refleja upgrades/downgrades).
    -- El plan histórico mes a mes se reconstruye desde stg_subscription_events.
    cast(plan as varchar)                   as current_plan,
    cast(tier as varchar)                   as tier,
    cast(start_date as date)                as start_date,
    cast(status as varchar)                 as status,
    cast(cancel_date as date)               as cancel_date,
    cast(cancel_reason as varchar)          as cancel_reason,
    cast(had_welcome_discount as boolean)   as had_welcome_discount,
    cast(gifted as boolean)                 as is_gifted,
    {{ to_month('start_date') }}            as cohort_month,
    -- El churn involuntario (fallo de cobro) no es el mismo fenómeno que el
    -- voluntario: se separa aquí para no mezclarlos en la curva de retención.
    coalesce(cancel_reason = 'involuntary_payment_failure', false) as is_involuntary_churn
from source
