{#
    Touchpoints listos para atribución. Grano: touchpoint_id.

    Conserva TODOS los touchpoints, también los que no resuelven a cliente: el
    attribution gap se mide, no se hace desaparecer con un inner join.

    `claim_weight` reparte la conversión entre los creadores que reclaman el
    mismo código el mismo día. Sumar cost_eur sin más duplica el coste de ese
    canal; sumar cost_eur * claim_weight no. La decisión de cuál usar es del
    análisis — el mart deja las dos disponibles y visibles.
#}

with journeys as (

    select * from {{ ref('int_marketing_journeys') }}

),

duplicate_claims as (

    select
        customer_key,
        touchpoint_date,
        influencer_code,
        count(distinct influencer_creator) as creators_claiming
    from journeys
    where is_shared_code_duplicate_claim
    group by 1, 2, 3

)

select
    j.touchpoint_id,
    j.customer_id,
    j.customer_key,
    j.channel,
    j.campaign_id,
    j.influencer_code,
    j.influencer_creator,
    j.touchpoint_at,
    j.touchpoint_date,
    j.touchpoint_month,

    j.cost_eur,
    coalesce(d.creators_claiming, 1)                        as creators_claiming,
    round(j.cost_eur / coalesce(d.creators_claiming, 1), 4) as weighted_cost_eur,
    round(1.0 / coalesce(d.creators_claiming, 1), 4)        as claim_weight,
    j.is_shared_code_duplicate_claim,

    -- Posición en el recorrido: base de first / last / linear touch.
    j.journey_rank,
    j.journey_size,
    j.is_first_touch,
    j.is_last_touch,
    round(case when j.journey_size > 0 then 1.0 / j.journey_size end, 6) as linear_credit,

    -- Conversión
    j.converted_to_subscription,
    j.first_subscription_date,
    j.days_to_conversion,
    j.is_pre_conversion,
    j.is_resolved_to_conversion,

    -- Attribution gap: el touchpoint existe pero no se puede colgar de nadie.
    j.is_identified_customer,
    not j.is_identified_customer                            as is_attribution_gap,
    case
        when not j.is_identified_customer          then 'unattributable'
        when j.is_shared_code_duplicate_claim      then 'ambiguous_shared_code'
        when j.channel = 'direct_unknown'          then 'unattributable'
        else 'attributable'
    end as attribution_status
from journeys j
left join duplicate_claims d
    on  d.customer_key    = j.customer_key
    and d.touchpoint_date = j.touchpoint_date
    and d.influencer_code = j.influencer_code
