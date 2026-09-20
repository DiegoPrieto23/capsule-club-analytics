{#
    Hechos mensuales de suscripción. Grano: (subscription_id, month_start).

    Es el mart que alimenta las páginas de suscriptores activos, de ingresos y
    las curvas de retención por cohorte.

    Dos medidas de ingreso, a propósito:
      - contracted_mrr_eur : tarifa vigente x estado activo. Señal limpia, no
        la afecta el hueco de la migración de pasarela.
      - collected_eur      : caja realmente cobrada ese mes. Sí lo acusa.
      - recognized_revenue_eur : el cobro repartido entre los meses del ciclo,
        para que los planes anual y trimestral no metan picos artificiales.
    La divergencia entre las tres es justamente lo que hay que explicar en el
    informe, no algo que haya que esconder.
#}

with state as (

    select * from {{ ref('int_subscription_monthly_state') }}

),

identity as (

    select customer_id, customer_key, acquisition_channel, has_unknown_acquisition_channel
    from {{ ref('int_customer_identity') }}

),

prices as (

    select tier, plan, plan_months, monthly_price_eur
    from {{ ref('int_plan_price_list') }}

),

payments as (

    select * from {{ ref('stg_payments') }}

),

collected_by_month as (

    select
        subscription_id,
        payment_month,
        sum(amount_eur) filter (where is_collected)         as collected_eur,
        sum(amount_eur) filter (where not is_collected)      as failed_amount_eur,
        count(*)        filter (where is_collected)          as payments_collected,
        count(*)        filter (where not is_collected)      as payments_failed
    from payments
    group by 1, 2

),

-- Reconocimiento de ingreso: cada cobro se reparte entre los meses del ciclo.
amortization_base as (

    select
        p.subscription_id,
        p.payment_month,
        p.amount_eur,
        coalesce(pr.plan_months, 1) as plan_months
    from payments p
    left join state s
        on s.subscription_id = p.subscription_id and s.month_start = p.payment_month
    left join prices pr
        on pr.tier = s.tier and pr.plan = s.plan_at_month
    where p.is_collected

),

amortized as (

    select
        subscription_id,
        payment_month,
        amount_eur / plan_months as monthly_amount_eur,
        unnest(generate_series(0, plan_months - 1)) as month_offset
    from amortization_base

),

recognized_by_month as (

    select
        subscription_id,
        cast(payment_month + to_months(cast(month_offset as integer)) as date) as revenue_month,
        sum(monthly_amount_eur) as recognized_revenue_eur
    from amortized
    group by 1, 2

),

shipments_by_month as (

    select
        subscription_id,
        ship_month,
        count(*)                                        as shipments,
        sum(quantity)                                   as capsule_sleeves_shipped,
        sum(shipment_value_eur)                         as shipment_value_eur,
        count(*) filter (where not is_on_time)          as shipments_late
    from {{ ref('stg_shipments') }}
    group by 1, 2

)

select
    s.subscription_id,
    i.customer_key,
    s.month_start,
    s.month_end,

    -- Atributos de cohorte
    s.cohort_month,
    s.months_since_start,
    s.tier,
    s.plan_at_month,
    i.acquisition_channel,
    i.has_unknown_acquisition_channel,
    s.had_welcome_discount,
    s.is_gifted,

    -- Estado
    s.is_live,
    s.is_active_eom,
    s.is_paused,
    s.is_active_net_of_pauses,
    s.is_churn_month,
    s.is_dunning_month,
    s.cancel_reason,
    s.is_involuntary_churn,
    s.is_churn_month and not s.is_involuntary_churn     as is_voluntary_churn_month,
    s.downgrade_events > 0                              as is_downgrade_month,
    s.upgrade_events > 0                                as is_upgrade_month,

    -- Ingreso
    round(case when s.is_active_net_of_pauses
               then coalesce(pr.monthly_price_eur, 0) else 0 end, 2) as contracted_mrr_eur,
    round(case when s.is_paused
               then coalesce(pr.monthly_price_eur, 0) else 0 end, 2) as paused_mrr_eur,
    round(coalesce(c.collected_eur, 0), 2)              as collected_eur,
    round(coalesce(c.failed_amount_eur, 0), 2)          as failed_amount_eur,
    round(coalesce(r.recognized_revenue_eur, 0), 2)     as recognized_revenue_eur,
    coalesce(c.payments_collected, 0)                   as payments_collected,
    coalesce(c.payments_failed, 0)                      as payments_failed,

    -- Envíos
    coalesce(sh.shipments, 0)                           as shipments,
    coalesce(sh.capsule_sleeves_shipped, 0)             as capsule_sleeves_shipped,
    round(coalesce(sh.shipment_value_eur, 0), 2)        as shipment_value_eur,
    coalesce(sh.shipments_late, 0)                      as shipments_late
from state s
left join identity i on i.customer_id = s.customer_id
left join prices   pr on pr.tier = s.tier and pr.plan = s.plan_at_month
left join collected_by_month  c  on c.subscription_id  = s.subscription_id and c.payment_month = s.month_start
left join recognized_by_month r  on r.subscription_id  = s.subscription_id and r.revenue_month = s.month_start
left join shipments_by_month  sh on sh.subscription_id = s.subscription_id and sh.ship_month   = s.month_start
