{#
    Continuidad de SKU entre relanzamientos.

    Cuando un sabor cambia de packaging o precio se descataloga su SKU y se
    relanza con código nuevo. Si la serie de demanda se agrega por product_sku,
    el sabor "muere" y "nace" el mismo mes: dos series cortas en vez de una.

    Este modelo recorre la cadena replaced_by_sku y asigna a cada SKU su
    `canonical_sku` (la primera versión), que es el eje correcto de la serie.
#}

with recursive

products as (

    select * from {{ ref('stg_products') }}

),

-- Raíz de cada cadena: el SKU al que no sustituye ningún otro.
roots as (

    select product_sku as canonical_sku
    from products p
    where not exists (
        select 1 from products q where q.replaced_by_sku = p.product_sku
    )

),

walk as (

    select
        canonical_sku,
        canonical_sku as product_sku,
        1             as version_number
    from roots

    union all

    select
        w.canonical_sku,
        p.replaced_by_sku,
        w.version_number + 1
    from walk w
    join products p on p.product_sku = w.product_sku
    where p.replaced_by_sku is not null

)

select
    w.canonical_sku,
    w.product_sku,
    w.version_number,
    w.version_number > 1                        as is_relaunch_version,
    p.product_type,
    p.flavor,
    p.launch_date,
    p.discontinue_date,
    p.replaced_by_sku,
    p.list_unit_price_eur,
    max(w.version_number) over (partition by w.canonical_sku) > 1 as flavor_was_relaunched
from walk w
join products p on p.product_sku = w.product_sku
