{#
    Resolución de identidad de cliente.

    Grano: un registro de alta (customer_id de origen).
    Añade `customer_key`: el identificador del HUMANO, no de la fila.

    Sin este paso las cohortes están sesgadas: un cliente que se reregistra con
    un email variante cuenta como alta nueva en su mes, infla la captación y
    contamina la curva de retención con una cohorte falsa.

    Regla de supervivencia: gana el registro con alta más antigua (el primer
    contacto real del cliente con la marca), desempatando por customer_id.
#}

with customers as (

    select * from {{ ref('stg_customers') }}

),

keyed as (

    select
        *,
        {{ email_identity_key('email_raw') }} as email_identity_key
    from customers

),

resolved as (

    select
        *,
        first_value(customer_id) over (
            partition by email_identity_key order by signup_date, customer_id
        ) as customer_key,
        min(signup_date) over (partition by email_identity_key) as first_signup_date,
        count(*)         over (partition by email_identity_key) as records_sharing_identity,
        row_number()     over (
            partition by email_identity_key order by signup_date, customer_id
        ) as identity_record_rank
    from keyed

)

select
    customer_id,
    customer_key,
    email_identity_key,
    email_raw,
    signup_date,
    first_signup_date,
    acquisition_channel,
    has_unknown_acquisition_channel,
    home_store_id,
    records_sharing_identity,
    identity_record_rank,
    records_sharing_identity > 1    as is_duplicate_identity,
    identity_record_rank > 1        as is_secondary_record,
    -- Qué regla hizo falta para unir este registro con su gemelo: útil para
    -- auditar cuánta deduplicación se apoya en heurística y cuánta es segura.
    case
        when records_sharing_identity = 1 then 'no_match'
        when lower(trim(email_raw)) <> email_identity_key then 'normalized_match'
        else 'exact_match'
    end as identity_match_rule
from resolved
