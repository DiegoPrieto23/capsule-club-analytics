{#
    Estado real de cada suscripción, mes a mes.

    Grano: (subscription_id, month_start), desde el mes de alta hasta el mes de
    baja (o hasta el final del histórico si sigue viva).

    Por qué existe: `status` en origen es sólo la foto final, y contar activos
    como "sin cancel_date" da una serie que crece de forma monótona y esconde
    la estacionalidad real. Las pausas de verano/Navidad no son churn, pero un
    suscriptor pausado no factura ni recibe envío: hay que poder contar las dos
    definiciones por separado y decidir cuál se forecastea.
#}

with subs as (

    select * from {{ ref('stg_subscriptions') }}

),

events as (

    select * from {{ ref('stg_subscription_events') }}

),

-- El horizonte se deduce de los datos, no se fija a mano.
horizon as (

    select
        (select cast(date_trunc('month', min(start_date)) as date) from subs) as first_month,
        (select cast(date_trunc('month', max(d)) as date) from (
            select max(start_date)                    as d from subs
            union all select max(cancel_date)              from subs
            union all select max(event_date)               from events
            union all select max(ship_date)                from {{ ref('stg_shipments') }}
            union all select max(payment_date)             from {{ ref('stg_payments') }}
        )) as last_month

),

spine as (

    select unnest(generate_series(first_month, last_month, interval 1 month))::date as month_start
    from horizon

),

subscription_months as (

    select
        s.subscription_id,
        s.customer_id,
        s.tier,
        s.cohort_month,
        s.had_welcome_discount,
        s.is_gifted,
        s.cancel_date,
        s.cancel_reason,
        s.is_involuntary_churn,
        sp.month_start,
        cast(last_day(sp.month_start) as date)                  as month_end,
        date_diff('month', s.cohort_month, sp.month_start)      as months_since_start
    from subs s
    cross join spine sp
    where sp.month_start >= s.cohort_month
      and (
            s.cancel_date is null
            or sp.month_start <= cast(date_trunc('month', s.cancel_date) as date)
          )

),

pause_events as (

    select subscription_id, event_date, event_type
    from events
    where event_type in ('paused', 'resumed')

),

plan_events as (

    -- 'created' lleva el plan de alta; upgraded/downgraded, el plan resultante.
    select subscription_id, event_date, new_plan
    from events
    where event_type in ('created', 'upgraded', 'downgraded')

),

-- ASOF JOIN = "el último evento en o antes del cierre de mes", sin subconsulta
-- correlacionada por fila.
with_pause_state as (

    select
        m.*,
        pe.event_type as last_pause_event
    from subscription_months m
    asof left join pause_events pe
        on m.subscription_id = pe.subscription_id
       and m.month_end >= pe.event_date

),

with_plan_state as (

    select
        w.*,
        pl.new_plan as plan_at_month
    from with_pause_state w
    asof left join plan_events pl
        on w.subscription_id = pl.subscription_id
       and w.month_end >= pl.event_date

),

monthly_events as (

    select
        subscription_id,
        event_month,
        count(*) filter (where event_type = 'payment_failed')     as payment_failed_events,
        count(*) filter (where event_type = 'payment_retried_ok') as payment_recovered_events,
        count(*) filter (where event_type = 'paused')             as pause_events,
        count(*) filter (where event_type = 'resumed')            as resume_events,
        count(*) filter (where event_type = 'downgraded')         as downgrade_events,
        count(*) filter (where event_type = 'upgraded')           as upgrade_events
    from events
    group by 1, 2

)

select
    w.subscription_id,
    w.customer_id,
    w.month_start,
    w.month_end,
    w.cohort_month,
    w.months_since_start,
    w.tier,
    w.plan_at_month,
    w.had_welcome_discount,
    w.is_gifted,
    w.cancel_date,
    w.cancel_reason,
    w.is_involuntary_churn,

    -- Tres definiciones de "activo", deliberadamente separadas:
    --   live        -> la suscripción existe este mes (definición ingenua)
    --   active_eom  -> sigue viva al cierre de mes (excluye el mes de baja)
    --   active_net  -> además no está pausada: es la que factura y envía
    true                                                        as is_live,
    (w.cancel_date is null or w.cancel_date > w.month_end)      as is_active_eom,
    coalesce(w.last_pause_event = 'paused', false)              as is_paused,
    (w.cancel_date is null or w.cancel_date > w.month_end)
        and not coalesce(w.last_pause_event = 'paused', false)  as is_active_net_of_pauses,

    (w.cancel_date is not null
        and cast(date_trunc('month', w.cancel_date) as date) = w.month_start) as is_churn_month,

    coalesce(e.payment_failed_events, 0)                        as payment_failed_events,
    coalesce(e.payment_recovered_events, 0)                     as payment_recovered_events,
    coalesce(e.pause_events, 0)                                 as pause_events,
    coalesce(e.resume_events, 0)                                as resume_events,
    coalesce(e.downgrade_events, 0)                             as downgrade_events,
    coalesce(e.upgrade_events, 0)                               as upgrade_events,
    -- Mes de dunning: el suscriptor "desaparece" de las métricas de cobro sin
    -- haber cancelado. Ruido en la serie diaria que no es churn.
    coalesce(e.payment_failed_events, 0) > 0                    as is_dunning_month
from with_plan_state w
left join monthly_events e
    on  e.subscription_id = w.subscription_id
    and e.event_month     = w.month_start
