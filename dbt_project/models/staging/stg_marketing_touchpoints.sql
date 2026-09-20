with source as (select * from {{ source('raw', 'raw_marketing_touchpoints') }})

select
    cast(touchpoint_id as varchar)              as touchpoint_id,
    cast(customer_id as varchar)                as customer_id,
    {{ normalize_marketing_channel('channel') }} as channel,
    cast(campaign_id as varchar)                as campaign_id,
    cast(cost as double)                        as cost_eur,
    -- El origen trae instante, no día: se conservan los dos. La hora es lo que
    -- desempata el orden de los touchpoints dentro de una misma jornada, y de
    -- ahí depende qué toque cuenta como "último" en la atribución.
    cast(timestamp as timestamp)                as touchpoint_at,
    cast(timestamp as date)                     as touchpoint_date,
    {{ to_month('timestamp') }}                 as touchpoint_month,
    cast(resolved_to_conversion as boolean)     as is_resolved_to_conversion,
    customer_id is not null                     as is_identified_customer,

    -- Los campaign_id de influencer siguen el patrón INFL-<CÓDIGO>-<CREADOR>.
    -- Separarlos permite detectar el mismo código promocionado por dos
    -- creadores a la vez (doble conteo de conversiones y de CAC).
    case when campaign_id like 'INFL-%'
         then split_part(campaign_id, '-', 2) end as influencer_code,
    case when campaign_id like 'INFL-%'
         then split_part(campaign_id, '-', 3) end as influencer_creator
from source
