{#
    Normalizaciones compartidas por staging.
    Viven en macros (y no copiadas en cada modelo) porque la misma regla tiene
    que aplicarse igual en clientes, pedidos y touchpoints: si la normalización
    de canal diverge entre tablas, la atribución deja de cuadrar.
#}

{% macro normalize_marketing_channel(column_name) -%}
    case
        when {{ column_name }} is null or trim({{ column_name }}) = ''
            then 'direct_unknown'
        else replace(replace(lower(trim({{ column_name }})), '-', '_'), ' ', '_')
    end
{%- endmacro %}


{% macro normalize_sales_channel(column_name) -%}
    case replace(lower(trim(coalesce({{ column_name }}, ''))), '-', '_')
        when 'online'   then 'online'
        when 'web'      then 'online'
        when 'ecommerce' then 'online'
        when 'store'    then 'store'
        when 'boutique' then 'store'
        when 'retail'   then 'store'
        else 'unknown'
    end
{%- endmacro %}


{#
    Clave de identidad a partir del email en crudo.

    Tres reglas, de menos a más agresiva:
      1. minúsculas y espacios  -> siempre segura
      2. alias '+tag' y puntos del local part -> Gmail los ignora de verdad;
         en otros proveedores es heurística, pero el falso positivo exige que
         dos personas distintas compartan local part exacto Y grupo de dominio
      3. grupos de dominio del mismo proveedor (gmail/googlemail, icloud/me,
         hotmail/outlook, yahoo.es/yahoo.com)

    La regla 3 es una decisión de negocio, no técnica: asume que el mismo
    local part en dos dominios del mismo proveedor es la misma persona.
    Se documenta en el schema.yml de int_customer_identity.
#}
{% macro email_identity_key(column_name) -%}
    replace(
        regexp_replace(split_part(lower(trim({{ column_name }})), '@', 1), '\+.*$', ''),
        '.', ''
    )
    || '@' ||
    case split_part(lower(trim({{ column_name }})), '@', 2)
        when 'googlemail.com' then 'gmail.com'
        when 'me.com'         then 'icloud.com'
        when 'outlook.com'    then 'hotmail.com'
        when 'yahoo.es'       then 'yahoo.com'
        else split_part(lower(trim({{ column_name }})), '@', 2)
    end
{%- endmacro %}


{#  Mes natural como DATE (primer día). Usado en todos los granos mensuales.  #}
{% macro to_month(column_name) -%}
    cast(date_trunc('month', {{ column_name }}) as date)
{%- endmacro %}
