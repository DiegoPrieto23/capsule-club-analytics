{#
    Recorrido de marketing por cliente resuelto.

    Grano: un touchpoint.

    Prepara el terreno para los modelos de atribución (first/last/linear touch y
    Markov) añadiendo la posición dentro del recorrido, y marca los dos agujeros
    que impiden atribuir con confianza:
      - touchpoints sin customer_id (anónimos y la caída de paid_social)
      - el mismo código de influencer reclamado por dos creadores el mismo día
#}

with touchpoints as (

    select * from {{ ref('stg_marketing_touchpoints') }}

),

identity as (

    select customer_id, customer_key from {{ ref('int_customer_identity') }}

),

mapped as (

    select
        t.*,
        i.customer_key
    from touchpoints t
    left join identity i on i.customer_id = t.customer_id

),

-- La conversión relevante para CAC/LTV es hacerse suscriptor, no registrarse.
conversions as (

    select
        i.customer_key,
        min(s.start_date) as first_subscription_date
    from {{ ref('stg_subscriptions') }} s
    join identity i on i.customer_id = s.customer_id
    group by 1

),

-- Doble conteo: mismo cliente, mismo día, mismo código, dos creadores.
shared_code_claims as (

    select
        customer_key,
        touchpoint_date,
        influencer_code
    from mapped
    where influencer_code is not null and customer_key is not null
    group by 1, 2, 3
    having count(distinct influencer_creator) > 1

),

ranked as (

    select
        touchpoint_id,
        row_number() over (
            partition by customer_key order by touchpoint_at, touchpoint_id
        ) as journey_rank,
        count(*) over (partition by customer_key) as journey_size
    from mapped
    where customer_key is not null

)

select
    m.touchpoint_id,
    m.customer_id,
    m.customer_key,
    m.channel,
    m.campaign_id,
    m.influencer_code,
    m.influencer_creator,
    m.cost_eur,
    m.touchpoint_at,
    m.touchpoint_date,
    m.touchpoint_month,
    m.is_resolved_to_conversion,
    m.is_identified_customer,

    r.journey_rank,
    r.journey_size,
    r.journey_rank = 1              as is_first_touch,
    r.journey_rank = r.journey_size as is_last_touch,

    c.first_subscription_date,
    c.customer_key is not null      as converted_to_subscription,
    case
        when c.first_subscription_date is not null
        then date_diff('day', m.touchpoint_date, c.first_subscription_date)
    end as days_to_conversion,
    coalesce(m.touchpoint_date <= c.first_subscription_date, false) as is_pre_conversion,

    -- Si no se deduplica, este touchpoint infla el CAC del canal influencer:
    -- dos creadores facturan la misma conversión.
    s.customer_key is not null      as is_shared_code_duplicate_claim
from mapped m
left join ranked r on r.touchpoint_id = m.touchpoint_id
left join conversions c on c.customer_key = m.customer_key
left join shared_code_claims s
    on  s.customer_key     = m.customer_key
    and s.touchpoint_date  = m.touchpoint_date
    and s.influencer_code  = m.influencer_code
