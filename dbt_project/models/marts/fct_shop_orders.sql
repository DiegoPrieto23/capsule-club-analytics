{#
    Compras puntuales (cápsulas sueltas y merch). Grano: línea de pedido,
    es decir (order_id, product_sku).

    Es el grano que necesitan las dos páginas que lo consumen: la demanda por
    SKU de cápsula trabaja a nivel línea, y el RFM agrega por order_id (para lo
    cual lleva order_total_eur repetido en cada línea del pedido).

    Los atributos de producto y tienda vienen desnormalizados a propósito: los
    notebooks sólo consumen marts, y no debería hacerles falta un join extra
    para saber a qué sabor pertenece un SKU relanzado.
#}

with lines as (

    select * from {{ ref('stg_shop_order_lines') }}

),

orders as (

    select * from {{ ref('stg_shop_orders') }}

),

identity as (

    select customer_id, customer_key from {{ ref('int_customer_identity') }}

),

products as (

    select * from {{ ref('int_product_sku_continuity') }}

),

stores as (

    select store_id, city from {{ ref('stg_stores') }}

),

order_totals as (

    select
        order_id,
        sum(line_amount_eur)    as order_total_eur,
        sum(quantity)           as order_units,
        count(*)                as order_line_count
    from lines
    group by 1

)

select
    l.order_line_id,
    l.order_id,
    o.customer_id,
    i.customer_key,
    o.order_date,
    o.order_month,
    o.channel,
    o.store_id,
    st.city                                 as store_city,
    o.is_identified_customer,

    l.product_sku,
    p.canonical_sku,
    p.flavor,
    p.product_type,
    p.version_number                        as sku_version_number,
    p.is_relaunch_version,
    p.flavor_was_relaunched,
    p.launch_date                           as sku_launch_date,
    p.discontinue_date                      as sku_discontinue_date,
    p.product_type = 'capsule'              as is_capsule,

    l.quantity,
    l.unit_price_eur,
    l.line_amount_eur,
    l.was_consolidated,

    round(t.order_total_eur, 2)             as order_total_eur,
    t.order_units,
    t.order_line_count
from lines l
join orders o        on o.order_id      = l.order_id
join order_totals t  on t.order_id      = l.order_id
join products p      on p.product_sku   = l.product_sku
left join identity i on i.customer_id   = o.customer_id
left join stores st  on st.store_id     = o.store_id
