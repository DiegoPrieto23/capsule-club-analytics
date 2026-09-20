{#
    Venta puntual de máquinas de cápsulas. Grano: machine_order_id.

    Existe porque la máquina es la tercera pata del negocio (un 18% del ingreso
    del histórico) y hasta ahora sólo estaba disponible agregada por cliente en
    dim_customers, lo que impedía construir una serie temporal de ingreso de
    máquina. La página de ingresos la necesita como cuarto canal y la de
    CAC x LTV la necesita para el valor de vida completo.

    Dos advertencias de uso:

    - customer_key es NULL en la venta de boutique sin fidelización, igual que
      en fct_shop_orders. Es imperfección documentada, no error: el ingreso
      total no cuadra con el ingreso atribuible a cliente.
    - is_trial_conversion marca al comprador que venía con cápsulas de regalo y
      acabó suscribiéndose semanas después. La lógica vive en
      int_machine_trial_conversions; aquí sólo se desnormaliza.
#}

with orders as (

    select * from {{ ref('stg_machine_orders') }}

),

identity as (

    select customer_id, customer_key from {{ ref('int_customer_identity') }}

),

machines as (

    select
        machine_model_id,
        machine_name,
        list_price_eur,
        launch_date,
        discontinue_date
    from {{ ref('stg_machines') }}

),

stores as (

    select store_id, city from {{ ref('stg_stores') }}

),

conversions as (

    select
        machine_order_id,
        subscription_id,
        subscription_start_date,
        conversion_lag_days,
        is_trial_conversion,
        was_already_subscriber,
        would_match_naive_same_day_join
    from {{ ref('int_machine_trial_conversions') }}

),

final as (

    select
        orders.machine_order_id,
        orders.customer_id,
        identity.customer_key,
        orders.is_identified_customer,

        orders.order_date,
        orders.order_month,
        orders.channel,
        orders.store_id,
        stores.city as store_city,

        orders.machine_model_id,
        machines.machine_name,
        machines.list_price_eur,
        orders.price_paid_eur,
        -- Descuento efectivo sobre tarifa. Útil para separar precio de volumen
        -- cuando la serie de ingreso de máquina se mueva.
        case
            when machines.list_price_eur > 0
                then 1 - (orders.price_paid_eur / machines.list_price_eur)
            else 0
        end as discount_rate,

        orders.has_bundled_capsules_trial,
        coalesce(conversions.is_trial_conversion, false) as is_trial_conversion,
        coalesce(conversions.was_already_subscriber, false) as was_already_subscriber,
        coalesce(conversions.would_match_naive_same_day_join, false)
            as would_match_naive_same_day_join,
        conversions.subscription_id as converted_subscription_id,
        conversions.subscription_start_date as converted_subscription_start_date,
        conversions.conversion_lag_days

    from orders
    left join identity on orders.customer_id = identity.customer_id
    left join machines on orders.machine_model_id = machines.machine_model_id
    left join stores on orders.store_id = stores.store_id
    left join conversions on orders.machine_order_id = conversions.machine_order_id

)

select * from final
