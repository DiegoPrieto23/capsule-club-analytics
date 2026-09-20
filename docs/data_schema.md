# Esquema de datos — Capsule Club Analytics

Todas las tablas son sintéticas. Ver `data_imperfections.md` para qué imperfección concreta debe llevar cada una.

## customers
Cliente único, sea suscriptor, comprador puntual, o ambos.
- `customer_id` (PK)
- `signup_date` — primera vez que aparece en cualquier sistema (online, tienda o compra de máquina)
- `acquisition_channel` — canal del primer touchpoint atribuible; puede ser nulo → tratar como "unknown/direct"
- `home_store_id` — nullable, solo si su alta fue en tienda física
- `email_raw` — email tal cual se registró (para poder simular variantes/duplicados)

## subscriptions
- `subscription_id` (PK)
- `customer_id` (FK)
- `plan` — monthly / quarterly / annual. **Es el plan vigente hoy**, ya con upgrades y downgrades aplicados; el plan de alta está en el evento `created` de `subscription_events`.
- `tier` — classic / intense / decaf / explorer
- `start_date`
- `status` — active / paused / cancelled
- `cancel_date` — nullable
- `cancel_reason` — nullable: price / taste / moved / no_reason / involuntary_payment_failure
- `had_welcome_discount` — bool
- `gifted` — bool, regalo de un tercero

## subscription_events
Log de eventos de la suscripción.
- `event_id` (PK)
- `subscription_id` (FK)
- `event_type` — created / paused / resumed / upgraded / downgraded / payment_failed / payment_retried_ok / cancelled
- `event_date`
- `previous_plan`, `new_plan` — solo si aplica a upgrade/downgrade

## shipments
Envío mensual de cápsulas a un suscriptor activo.
- `shipment_id` (PK)
- `subscription_id` (FK)
- `ship_date`
- `capsule_sku` (FK a products)
- `quantity`
- `cost` — valor del envío a precio de catálogo (unidades × precio del SKU). No es coste de mercancía.
- `on_time` — bool

## machines
Catálogo de modelos de cafetera.
- `machine_model_id` (PK)
- `name`
- `launch_date`
- `discontinue_date` — nullable
- `price`

## machine_orders
Compra puntual de una máquina (online o en tienda).
- `order_id` (PK)
- `customer_id` (FK, nullable — compra en tienda sin fidelización)
- `machine_model_id` (FK)
- `order_date`
- `channel` — online / store
- `store_id` — nullable
- `price_paid`
- `bundled_capsules_trial` — bool; si vino con cápsulas de regalo, lo cual puede empujar a suscripción semanas después

## shop_orders / shop_order_lines
Compras puntuales de cápsulas sueltas o merchandising, no ligadas a una suscripción activa. Es la base del RFM clásico.
- `order_id` (PK)
- `customer_id` (FK, nullable en tienda física sin fidelización)
- `order_date`
- `channel` — online / store
- `store_id` — nullable
- order_lines: `product_sku`, `quantity`, `unit_price`. Grano **(order_id, product_sku)**: la cesta se agrega por referencia, nunca hay dos líneas del mismo SKU en un pedido.

## products
- `product_sku` (PK)
- `product_type` — capsule / merch
- `flavor` — solo si es cápsula (p.ej. origin_colombia, intense_8, decaf_vanilla...)
- `launch_date`
- `discontinue_date` — nullable
- `replaced_by_sku` — nullable, para roturas de continuidad de serie por relanzamiento
- `unit_price` — **añadido sobre la especificación original**: las líneas de pedido y el valor de los envíos necesitan un precio de referencia por SKU, y sin él habría que inventarlo en cada consumidor

## marketing_touchpoints
- `touchpoint_id` (PK)
- `customer_id` — nullable, no todos los touchpoints se resuelven a un cliente
- `channel` — paid_social / influencer_code / podcast_ads / referral / organic / direct_unknown
- `campaign_id`
- `cost`
- `timestamp` — instante con hora real, no sólo el día: es lo que ordena los touchpoints dentro de una misma jornada y decide cuál es el "último toque".
- `resolved_to_conversion` — bool

## stores
- `store_id` (PK)
- `city`
- `opening_date`

## payments
- `payment_id` (PK)
- `subscription_id` (FK)
- `payment_date`
- `amount`
- `status` — success / failed / retried_success


---

## Notas de implementación

Decisiones tomadas al generar los datos que no estaban cerradas en la
especificación de arriba. Se documentan aquí porque cambian cómo hay que leer
las tablas, no sólo cómo se construyeron.

- **`products.unit_price`** es la única columna añadida sobre el esquema
  original. Todo lo demás se corresponde uno a uno.
- **`subscriptions.plan` es el plan actual, no el de alta.** Reconstruir el
  plan histórico mes a mes exige recorrer `subscription_events` (`created` trae
  el plan inicial; `upgraded`/`downgraded` traen el resultante). En dbt eso lo
  resuelve `int_subscription_monthly_state`.
- **`subscriptions.status` es la foto final**, no el estado en un momento dado.
  Contar activos con `cancel_date is null` produce una serie que crece de forma
  monótona y esconde la estacionalidad: el estado real vive en los eventos.
- **Los sabores de temporada** (`seasonal_*`) se lanzan dentro del histórico y
  tienen estacionalidad propia muy marcada; el resto de sabores existen desde
  antes del primer día. Cada suscripción tiene además un sabor favorito estable,
  así que la demanda por SKU tiene persistencia y no es ruido blanco.
- **La tarifa no está en ninguna tabla.** El precio por gama y plan se deduce de
  los cobros reales (`int_plan_price_list`), no de una lista de precios: así
  ninguna constante del generador viaja al warehouse.

### Garantías de coherencia interna

El dataset es imperfecto **sólo** en lo que recoge `data_imperfections.md`.
Todo lo demás es consistente, y estas invariantes se comprueban en cada
generación:

| Invariante | Estado |
|---|---|
| Integridad referencial en las 8 relaciones FK | 0 huérfanos |
| Nada (envío, cobro o evento) con fecha posterior a `cancel_date` | 0 |
| Ningún pedido sin líneas | 0 |
| Ningún SKU vendido o enviado fuera de su vida de catálogo | 0 |
| Ningún pedido en una tienda aún no abierta | 0 |
| Ningún touchpoint posterior al alta del cliente | 0 |
| Ninguna suscripción anterior al alta de su cliente | 0 |
| Grano `(order_id, product_sku)` único | 0 duplicados |

Los `customer_id` nulos en `shop_orders` y `machine_orders`, en cambio, **sí**
son intencionados: son la venta de boutique sin fidelización.
