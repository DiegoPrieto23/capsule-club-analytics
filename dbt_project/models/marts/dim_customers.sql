{#
    Dimensión de cliente. Grano: customer_key (el humano, no el registro de alta).

    Ojo al consumirla: las ventas de boutique sin fidelización no tienen cliente
    y por tanto NO están aquí. Esa diferencia entre "ingresos totales" e
    "ingresos atribuibles a un cliente" es real y hay que declararla en el
    informe, no cuadrarla por la fuerza.

    Lleva agregados de vida del cliente (ingreso por suscripción, tienda y
    máquina) porque son el insumo directo del LTV por canal de la página de
    cierre, y recalcularlos en cada notebook invitaría a que cada uno usara una
    definición distinta.
#}

with identity as (

    select * from {{ ref('int_customer_identity') }}

),

-- Atributos del registro que sobrevive a la deduplicación.
surviving_record as (

    select
        customer_key,
        acquisition_channel,
        has_unknown_acquisition_channel,
        home_store_id
    from identity
    where customer_id = customer_key

),

identity_rollup as (

    select
        customer_key,
        min(first_signup_date)              as first_signup_date,
        count(*)                            as source_records,
        max(is_duplicate_identity::int) = 1 as has_duplicate_identity
    from identity
    group by 1

),

subscriptions as (

    select
        i.customer_key,
        count(*)                                            as subscriptions_total,
        min(s.start_date)                                   as first_subscription_date,
        cast(date_trunc('month', min(s.start_date)) as date) as subscription_cohort_month,
        max((s.status = 'active')::int) = 1                 as has_active_subscription,
        max(s.had_welcome_discount::int) = 1                as had_welcome_discount_ever,
        max(s.is_gifted::int) = 1                           as has_gifted_subscription,
        max(s.is_involuntary_churn::int) = 1                as had_involuntary_churn
    from {{ ref('stg_subscriptions') }} s
    join identity i on i.customer_id = s.customer_id
    group by 1

),

subscription_revenue as (

    select
        customer_key,
        round(sum(collected_eur), 2)                        as subscription_collected_eur,
        round(sum(recognized_revenue_eur), 2)               as subscription_recognized_eur,
        sum(is_active_net_of_pauses::int)                   as active_months,
        sum(is_paused::int)                                 as paused_months
    from {{ ref('fct_subscriptions_monthly') }}
    where customer_key is not null
    group by 1

),

machine_orders as (

    select
        i.customer_key,
        count(*)                                    as machine_orders_total,
        round(sum(o.price_paid_eur), 2)             as machine_revenue_eur,
        min(o.order_date)                           as first_machine_order_date,
        max(o.has_bundled_capsules_trial::int) = 1  as had_bundled_capsules_trial
    from {{ ref('stg_machine_orders') }} o
    join identity i on i.customer_id = o.customer_id
    group by 1

),

trial_conversions as (

    select
        customer_key,
        max(is_trial_conversion::int) = 1   as is_machine_trial_conversion,
        min(conversion_lag_days)            as trial_conversion_lag_days
    from {{ ref('int_machine_trial_conversions') }}
    group by 1

),

shop as (

    select
        customer_key,
        count(distinct order_id)            as shop_orders_total,
        round(sum(line_amount_eur), 2)      as shop_revenue_eur,
        sum(quantity)                       as shop_units,
        min(order_date)                     as first_shop_order_date,
        max(order_date)                     as last_shop_order_date
    from {{ ref('fct_shop_orders') }}
    where customer_key is not null
    group by 1

),

-- Fecha de corte para la recencia del RFM: el último día con actividad.
as_of as (

    select max(order_date) as as_of_date from {{ ref('fct_shop_orders') }}

),

stores as (

    select store_id, city from {{ ref('stg_stores') }}

)

select
    ir.customer_key,
    ir.first_signup_date,
    cast(date_trunc('month', ir.first_signup_date) as date)     as signup_month,
    ir.source_records,
    ir.has_duplicate_identity,

    sr.acquisition_channel,
    sr.has_unknown_acquisition_channel,
    sr.home_store_id,
    st.city                                                     as home_store_city,

    -- Suscripción
    coalesce(s.subscriptions_total, 0)                          as subscriptions_total,
    s.subscriptions_total is not null                           as is_subscriber,
    s.first_subscription_date,
    s.subscription_cohort_month,
    coalesce(s.has_active_subscription, false)                  as has_active_subscription,
    coalesce(s.had_welcome_discount_ever, false)                as had_welcome_discount_ever,
    coalesce(s.has_gifted_subscription, false)                  as has_gifted_subscription,
    coalesce(s.had_involuntary_churn, false)                    as had_involuntary_churn,
    coalesce(sv.subscription_collected_eur, 0)                  as subscription_collected_eur,
    coalesce(sv.subscription_recognized_eur, 0)                 as subscription_recognized_eur,
    coalesce(sv.active_months, 0)                               as active_months,
    coalesce(sv.paused_months, 0)                               as paused_months,

    -- Máquina
    coalesce(m.machine_orders_total, 0)                         as machine_orders_total,
    m.machine_orders_total is not null                          as is_machine_buyer,
    coalesce(m.machine_revenue_eur, 0)                          as machine_revenue_eur,
    m.first_machine_order_date,
    coalesce(m.had_bundled_capsules_trial, false)               as had_bundled_capsules_trial,
    coalesce(tc.is_machine_trial_conversion, false)             as is_machine_trial_conversion,
    tc.trial_conversion_lag_days,

    -- Tienda (base del RFM)
    coalesce(sh.shop_orders_total, 0)                           as shop_orders_total,
    coalesce(sh.shop_revenue_eur, 0)                            as shop_revenue_eur,
    coalesce(sh.shop_units, 0)                                  as shop_units,
    sh.first_shop_order_date,
    sh.last_shop_order_date,
    date_diff('day', sh.last_shop_order_date, a.as_of_date)     as days_since_last_shop_order,
    a.as_of_date,

    round(coalesce(sv.subscription_collected_eur, 0)
        + coalesce(m.machine_revenue_eur, 0)
        + coalesce(sh.shop_revenue_eur, 0), 2)                  as lifetime_revenue_eur
from identity_rollup ir
cross join as_of a
left join surviving_record sr on sr.customer_key = ir.customer_key
left join subscriptions s     on s.customer_key  = ir.customer_key
left join subscription_revenue sv on sv.customer_key = ir.customer_key
left join machine_orders m    on m.customer_key  = ir.customer_key
left join trial_conversions tc on tc.customer_key = ir.customer_key
left join shop sh             on sh.customer_key = ir.customer_key
left join stores st           on st.store_id     = sr.home_store_id
