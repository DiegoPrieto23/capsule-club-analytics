{#
    Dimensión de suscripción. Grano: subscription_id.

    Existe por una razón concreta de análisis: fct_subscriptions_monthly tiene
    grano mensual, así que no permite estudiar el FLUJO de altas y de bajas a
    nivel diario. La página de suscriptores estaba usando
    dim_customers.first_subscription_date como sustituto, que cuenta primeras
    suscripciones por cliente (5.047) y no altas de suscripción (5.110): se
    dejaba fuera la resuscripción de un cliente que ya lo había sido.

    Con este mart, la estacionalidad semanal de las altas se mide sobre el
    evento correcto.

    Incluye la duración observada en días para poder hacer supervivencia sin
    reconstruirla desde el estado mensual, y marca explícitamente la censura por
    derecha: una suscripción viva al cierre del histórico no es una suscripción
    que haya durado ese tiempo, es una que todavía no ha terminado.
#}

with subscriptions as (

    select * from {{ ref('stg_subscriptions') }}

),

identity as (

    select customer_id, customer_key from {{ ref('int_customer_identity') }}

),

customers as (

    select customer_id, acquisition_channel, home_store_id
    from {{ ref('stg_customers') }}

),

history as (

    select max(month_end) as history_end from {{ ref('int_subscription_monthly_state') }}

),

final as (

    select
        subscriptions.subscription_id,
        subscriptions.customer_id,
        identity.customer_key,

        subscriptions.start_date,
        date_trunc('month', subscriptions.start_date)::date as cohort_month,
        subscriptions.cancel_date,
        subscriptions.status,
        subscriptions.cancel_reason,
        subscriptions.is_involuntary_churn,

        subscriptions.current_plan,
        subscriptions.tier,
        subscriptions.had_welcome_discount,
        subscriptions.is_gifted,

        customers.acquisition_channel,
        customers.home_store_id,

        -- Días observados de vida. Si no ha cancelado, se mide hasta el cierre
        -- del histórico y la observación queda censurada por la derecha.
        date_diff(
            'day',
            subscriptions.start_date,
            coalesce(subscriptions.cancel_date, history.history_end)
        ) as observed_days,
        subscriptions.cancel_date is null as is_right_censored

    from subscriptions
    cross join history
    left join identity on subscriptions.customer_id = identity.customer_id
    left join customers on subscriptions.customer_id = customers.customer_id

)

select * from final
