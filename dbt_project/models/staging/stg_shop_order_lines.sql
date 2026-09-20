with source as (select * from {{ source('raw', 'raw_shop_order_lines') }}),

-- Un mismo SKU puede aparecer en más de una línea del mismo pedido (la misma
-- referencia añadida dos veces a la cesta, a veces con precio distinto por una
-- promoción). El grano útil aguas abajo es (pedido, SKU), así que se consolida
-- aquí en vez de tocar el origen: se suman unidades e importe y el precio
-- unitario pasa a ser el efectivamente pagado.
consolidated as (

    select
        cast(order_id as varchar)       as order_id,
        cast(product_sku as varchar)    as product_sku,
        sum(cast(quantity as integer))  as quantity,
        sum(cast(quantity as integer) * cast(unit_price as double)) as line_amount_eur,
        count(*)                        as source_line_count
    from source
    group by 1, 2

)

select
    order_id || '::' || product_sku                 as order_line_id,
    order_id,
    product_sku,
    quantity,
    round(line_amount_eur / nullif(quantity, 0), 4) as unit_price_eur,
    round(line_amount_eur, 2)                       as line_amount_eur,
    source_line_count > 1                           as was_consolidated
from consolidated
