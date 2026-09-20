{#
    Comprador de máquina con cápsulas de regalo -> suscriptor semanas después.

    Grano: una fila por pedido de máquina con trial de un cliente identificado.

    Dos trampas que este modelo resuelve a propósito:
      1. La conversión no ocurre el día de la compra, sino entre 2 y 11 semanas
         después: un join por fecha exacta no encuentra ninguna.
      2. El cliente puede haberse re-registrado con otro email entre la compra
         y el alta, así que el join va por customer_key (identidad resuelta),
         no por el customer_id de origen.
#}

{% set window_days = var('machine_trial_conversion_window_days') %}

with identity as (

    select customer_id, customer_key from {{ ref('int_customer_identity') }}

),

trial_orders as (

    select
        o.machine_order_id,
        i.customer_key,
        o.order_date,
        o.channel,
        o.store_id,
        o.machine_model_id,
        o.price_paid_eur
    from {{ ref('stg_machine_orders') }} o
    join identity i on i.customer_id = o.customer_id
    where o.has_bundled_capsules_trial

),

subscriptions as (

    select
        i.customer_key,
        s.subscription_id,
        s.start_date
    from {{ ref('stg_subscriptions') }} s
    join identity i on i.customer_id = s.customer_id

),

-- Quien ya era suscriptor antes de comprar la máquina no "convierte".
prior_subscribers as (

    select t.machine_order_id
    from trial_orders t
    join subscriptions s
        on  s.customer_key = t.customer_key
        and s.start_date  <= t.order_date
    group by 1

),

candidates as (

    select
        t.machine_order_id,
        s.subscription_id,
        s.start_date                                        as subscription_start_date,
        date_diff('day', t.order_date, s.start_date)        as conversion_lag_days,
        row_number() over (
            partition by t.machine_order_id order by s.start_date
        ) as rn
    from trial_orders t
    join subscriptions s
        on  s.customer_key = t.customer_key
        and date_diff('day', t.order_date, s.start_date) between 1 and {{ window_days }}
    -- Quien ya estaba suscrito no convierte: sólo amplía su relación.
    where t.machine_order_id not in (select machine_order_id from prior_subscribers)

),

-- Contraste explícito: cuántas encontraría un join ingenuo por fecha exacta.
naive_same_day as (

    select t.machine_order_id
    from trial_orders t
    join subscriptions s
        on  s.customer_key = t.customer_key
        and s.start_date   = t.order_date
    group by 1

)

select
    t.machine_order_id,
    t.customer_key,
    t.order_date,
    t.channel,
    t.store_id,
    t.machine_model_id,
    t.price_paid_eur,
    c.subscription_id,
    c.subscription_start_date,
    c.conversion_lag_days,
    c.subscription_id is not null   as is_trial_conversion,
    n.machine_order_id is not null  as would_match_naive_same_day_join,
    p.machine_order_id is not null  as was_already_subscriber
from trial_orders t
left join candidates c
    on c.machine_order_id = t.machine_order_id and c.rn = 1
left join naive_same_day n on n.machine_order_id = t.machine_order_id
left join prior_subscribers p on p.machine_order_id = t.machine_order_id
