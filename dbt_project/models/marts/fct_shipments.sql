{#
    Envíos de cápsulas a suscriptores. Grano: shipment_id.

    Junto con fct_shop_orders forma la demanda total por sabor: la tienda es el
    69% de las unidades y el club el 31%. Separarlas es lo que permite tratar la
    demanda censurada, porque una rotura de stock censura la demanda de tienda
    y no la del club, que se sirve igual.
#}

with shipments as (

    select * from {{ ref('stg_shipments') }}

),

subscriptions as (

    select
        subscription_id,
        customer_id,
        tier,
        cohort_month,
        is_gifted
    from {{ ref('stg_subscriptions') }}

),

identity as (

    select customer_id, customer_key, acquisition_channel
    from {{ ref('int_customer_identity') }}

),

products as (

    select * from {{ ref('int_product_sku_continuity') }}

)

select
    s.shipment_id,
    s.subscription_id,
    i.customer_key,
    i.acquisition_channel,
    sub.tier,
    sub.cohort_month,
    sub.is_gifted,

    s.ship_date,
    s.ship_month,

    s.capsule_sku,
    p.canonical_sku,
    p.flavor,
    p.version_number            as sku_version_number,
    p.is_relaunch_version,
    p.flavor_was_relaunched,
    p.launch_date               as sku_launch_date,
    p.discontinue_date          as sku_discontinue_date,

    s.quantity,
    s.shipment_value_eur,
    s.is_on_time
from shipments s
join subscriptions sub on sub.subscription_id = s.subscription_id
join products p        on p.product_sku       = s.capsule_sku
left join identity i   on i.customer_id       = sub.customer_id
