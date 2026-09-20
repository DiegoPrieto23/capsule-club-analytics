# Imperfecciones a inyectar (y por qué)

La calidad narrativa de este proyecto depende de que estas imperfecciones existan de verdad en los datos generados, y de que el análisis las reconozca y trate explícitamente en vez de ignorarlas. No son bugs a esconder — son la parte del proyecto que demuestra criterio analítico real frente a un dataset de Kaggle ya limpio.

## Forecasting / series temporales

- **Pausas estacionales masivas** en verano y en torno a Navidad — no son cancelación, pero rompen la continuidad de "activos" si se cuentan igual que un churn real.
- **Fallos de cobro (dunning)**: un suscriptor "desaparece" temporalmente de las métricas hasta que se reintenta el cobro con éxito, generando ruido en la serie diaria que no es churn real.
- **Migración de pasarela de pago** a mitad del histórico: un hueco de aproximadamente una semana sin datos de pagos. Afecta sólo a la tabla `payments`: los eventos de cobro de `subscription_events` siguen ahí, así que el hueco es detectable cruzando ambas — y la serie de MRR contratado no lo acusa mientras la de caja sí.
- **SKUs de cápsula descatalogados y relanzados** con nuevo código cuando cambia el packaging o el precio, rompiendo la continuidad de la serie de demanda de ese sabor si no se resuelve el `replaced_by_sku`.
- **Roturas de stock que generan demanda censurada**: en `shop_orders` puede parecer demanda=0 de un sabor cuando en realidad no había stock disponible ese día — muy distinto de que nadie lo quisiera comprar. Las ventanas se colocan dentro de la vida de catálogo del sabor y se exige que censuren demanda real (mínimo 20 líneas): una rotura sobre un sabor sin ventas no deja rastro y no se podría detectar ni tratar. Afecta a la tienda, **no** a los envíos del club: la demanda del suscriptor no se pierde, se sirve igual.

## Cohortes

- **Descuento de bienvenida** el primer mes, que genera un pico de cancelación previsible en el mes 2 cuando se empieza a cobrar el precio completo — la cohorte de mes 0 no es comparable en ingreso con las siguientes si no se ajusta por `had_welcome_discount`.
- **Suscripciones regaladas** (`gifted=true`): no siguen el patrón normal de reactivación/cancelación del titular real del pago.
- **Downgrades de plan** que reducen el **compromiso**, no la tarifa: el plan se mueve por el eje del ciclo (`annual → quarterly → monthly`), y como el ciclo largo lleva descuento, acortarlo sube el MRR mensual un 6% y baja el compromiso de 6,7 a 1,8 meses. No son churn y hay que decidir explícitamente cómo tratarlos en la curva de retención. El `tier` (decaf/classic/intense/explorer), que es el eje con precio de verdad, no se mueve nunca.
- **Pausas que retiran ingreso sin retirar cliente**: durante una pausa el mart lleva la tarifa a `paused_mrr_eur` y deja `contracted_mrr_eur` a cero. Son 57.510 € de MRR retirado (el 3,9% del de tarifa) sobre 1.105 suscripciones —55.360 € y 1.064 si se dejan fuera las regaladas, que es como lo mide la página 5— y son el caso que obliga a separar retención de logo de retención de ingreso — no los downgrades.
- **Compradores de máquina con `bundled_capsules_trial=true`** que se convierten en suscriptores varias semanas después, no inmediatamente — un join ingenuo por fecha exacta los perdería.

## Atribución

- **Un mismo código de influencer** promocionado por dos creadores a la vez — problema real de tracking en marketing de afiliados.
- **Caída de atribución fiable de `paid_social`** en un periodo concreto del histórico, simulando el efecto de cambios de privacidad tipo iOS ATT: de repente ese canal "pierde" conversiones que en realidad sí ocurrieron.
- **Touchpoints sin `customer_id` resuelto**, que se acumulan como `direct_unknown`.
- **Compras en tienda física sin fidelización** (`customer_id` nulo en `shop_orders`/`machine_orders` con `channel=store`) — no toda venta offline es atribuible a un cliente ni a un canal de marketing.

## Identidad de cliente (transversal)

- **`customer_id` duplicado por variantes del email** (mayúsculas, alias con "+", dominios distintos) en un pequeño porcentaje de altas — para forzar una etapa explícita de resolución de identidad en dbt antes de poder hacer cohortes fiables.


---

## Qué NO es una imperfección

Importante para el análisis: este catálogo es **cerrado**. El dataset es
deliberadamente imperfecto en lo que aparece arriba y consistente en todo lo
demás, así que cualquier otra anomalía que aparezca en el análisis es un error
de interpretación o un bug del pipeline, no una trampa plantada a propósito.

En particular, están garantizados y verificados en cada generación:

- integridad referencial completa entre todas las tablas;
- orden temporal coherente: nada le ocurre a una suscripción después de su
  `cancel_date`, ninguna suscripción empieza antes del alta de su cliente,
  ningún touchpoint es posterior al alta;
- ningún SKU se vende o se envía fuera de su vida de catálogo, y ninguna tienda
  vende antes de abrir;
- grano `(order_id, product_sku)` único: la cesta se agrega por referencia.

La lista completa de invariantes está en `data_schema.md`.

## Cambios sobre versiones anteriores del generador

- Las **roturas de stock** ya no se colocan al azar: se exige que censuren
  demanda real, porque varias caían sobre sabores sin ventas en esa fecha.
- Los **sabores de temporada** entran en el catálogo por defecto (antes el corte
  a 12 sabores los dejaba fuera) y cada suscripción tiene un **sabor favorito**
  estable. Sin eso, la demanda por SKU era ruido uniforme: no había
  estacionalidad de sabor ni persistencia que modelar en la página 4.
- Se corrigieron incoherencias que **no** estaban en este catálogo y por tanto
  no debían existir: envíos y cobros con fecha posterior a la baja, pedidos sin
  líneas, y líneas repetidas del mismo SKU dentro de un pedido.
- **Vertido de eventos sobre el último día del histórico.** `clamp()` aplastaba
  contra `END_DATE` cualquier evento programado para después del corte en vez de
  descartarlo, apilando 1.025 envíos el 2026-08-31 frente a una media de 75/día
  (y ×13 en pagos, ×18 en cancelaciones, ×6 en compras de máquina). Se detectó
  analizando la serie de ingresos, porque inflaba un 15% el último mes, que es
  justo el origen de los forecasts. Ahora `event_day()` descarta lo que cae
  fuera de la ventana de observación. Esto **no** era una imperfección del
  catálogo: era un bug.
