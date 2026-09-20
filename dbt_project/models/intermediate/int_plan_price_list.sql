{#
    Tarifa mensual efectiva por (tier, plan), derivada de los cobros reales.

    Se deduce de los datos en vez de hardcodear una lista de precios: así el
    MRR contratado no depende de constantes copiadas del generador.

    Se excluye el primer ciclo de las suscripciones con descuento de bienvenida,
    que se cobra a mitad de precio: si se incluyera, la tarifa quedaría sesgada
    a la baja y el pico de cancelación del mes 2 parecería una caída de precio.
#}

with payments as (

    select * from {{ ref('stg_payments') }} where is_collected

),

state as (

    select
        subscription_id,
        month_start,
        tier,
        plan_at_month,
        had_welcome_discount,
        months_since_start
    from {{ ref('int_subscription_monthly_state') }}

),

payments_with_plan as (

    select
        p.amount_eur,
        s.tier,
        s.plan_at_month as plan,
        case s.plan_at_month
            when 'monthly'   then 1
            when 'quarterly' then 3
            when 'annual'    then 12
        end as plan_months
    from payments p
    join state s
        on  s.subscription_id = p.subscription_id
        and s.month_start     = p.payment_month
    where not (s.had_welcome_discount and s.months_since_start = 0)

)

select
    tier,
    plan,
    plan_months,
    count(*)                                        as payments_observed,
    round(median(amount_eur), 2)                    as cycle_price_eur,
    round(median(amount_eur) / plan_months, 2)      as monthly_price_eur
from payments_with_plan
group by 1, 2, 3
