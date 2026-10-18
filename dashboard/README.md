# Datos del dashboard

CSV planos para montar el dashboard ejecutivo de Capsule Club en claude.ai (tipo
Dashboard). Los genera `export_dashboard_data.py` a partir de los JSON de
`analysis/outputs/`, y en el DAG es la última tarea, detrás de `build_report`:

```
python dashboard/export_dashboard_data.py
```

El informe HTML sigue siendo el entregable principal; esto es un complemento
ejecutivo con las mismas cifras.

## Reglas que cumplen todos los ficheros

- **Un dataset, un fichero.** El id del dataset es el nombre del fichero sin
  `.csv` (`[A-Za-z0-9_-]`, 64 caracteres como mucho). Todos son planos y pesan
  menos de 8 MB; el script lo comprueba antes de escribir.
- **Números sin formato**: punto decimal, sin símbolo de € ni separador de
  miles, redondeados a diez cifras significativas. Celda vacía = sin valor.
- **Fechas ISO** `YYYY-MM-DD`. Los meses van por su primer día (`2026-08-01` es
  agosto de 2026), igual que en las series de los notebooks.
- **Booleanos** como `true` / `false`.
- **Toda clave lleva su etiqueta y sus colores.** Junto a `channel` o `flavor`
  van `*_label` en castellano, `color` (modo claro) y `color_dark` (modo
  oscuro), sacados de `report/theme.py`. La paleta de canales está validada
  para daltonismo con la combinación de ranuras concreta que usa el informe:
  no se reasigna. `direct_unknown` va en gris porque no es un canal, y de los
  doce sabores sólo los dos de temporada llevan color; los diez de base van en
  gris, como en el gráfico del informe.
- **Ninguna cifra escrita a mano.** Los KPI y las recomendaciones no se
  recalculan aquí: `report/content.py` guarda junto a cada texto del informe su
  cifra sin formatear, y el script la exporta tal cual. Por eso el dashboard
  no puede discrepar del informe.

### Unidades

La columna `unit` (en `kpis`) y `metric_unit` (en `recommendations`) usan este
vocabulario:

| Unidad | Significa | Ejemplo de lectura |
|---|---|---|
| `eur` | euros | `14.53` → 14,53 € |
| `pct` | porcentaje ya multiplicado por 100 | `57.96` → 58% |
| `pp` | puntos porcentuales | `64.7` → 64,7 pp |
| `count` | número de suscriptores, clientes, altas o eventos | |
| `units` | cápsulas | |
| `months` | meses | |
| `ratio` | veces (LTV / CAC) | `32.8` → 32,8× |
| `index` | índice adimensional de 0 a 1 | |

Las columnas con sufijo `_eur`, `_pct`, `_pp` o `_months` siguen la misma
convención.

## Los datasets

| Dataset | Grano | Filas | Para qué |
|---|---|---:|---|
| `kpis` | página × indicador | 35 | Las cifras de cabecera de las siete páginas; la portada, marcada |
| `subscribers_monthly` | mes | 36 | Suscriptores activos y en pausa |
| `revenue_by_channel` | mes × canal de venta | 144 | Ingreso mensual y mix |
| `payment_gap` | mes | 36 | La semana de cobros perdida, vista donde se ve |
| `capsule_demand` | mes × sabor | 432 | Demanda real y observada, con las roturas |
| `capsule_seasonality` | mes del año × sabor | 144 | El calendario de compras (mapa de calor) |
| `stockouts` | rotura de stock | 6 | Las seis roturas y su venta perdida |
| `retention_by_channel` | edad × canal | 216 | Curvas de retención |
| `cac_ltv` | canal | 6 | El cruce de cierre |
| `cac_ltv_scenarios` | escenario × canal | 32 | Si el orden aguanta con otro método o con margen |
| `attribution_by_model` | canal × modelo | 20 | Crédito y CAC en los cuatro modelos |
| `attribution_gap` | canal | 6 | El gasto sin cliente y cuánto encarece cada canal |
| `recommendations` | recomendación | 23 | El plan de acción, con su cifra |

### `kpis`

Una fila por indicador de cabecera de cada página del informe: la cifra grande
(`is_hero`) y la fila de indicadores debajo. La vista ejecutiva filtra
`is_cover = true`, que son exactamente los siete de la portada. Un mismo
`kpi_id` puede salir en varias páginas con el mismo valor (el CAC cargado está
en la portada y en la página 7); la clave es `page` + `kpi_id`.

Sale de `report/content.py`, que a su vez lee los seis JSON.

| Columna | Tipo | Unidad | Descripción |
|---|---|---|---|
| `page` | string | | Slug de la página: `index`, `suscriptores`, `ingresos`, `capsulas`, `cohortes`, `atribucion`, `cac-ltv` |
| `page_title` | string | | Título de la página |
| `is_cover` | boolean | | Es de la portada |
| `is_hero` | boolean | | Es la cifra grande de la página |
| `position` | integer | | Orden dentro de la página (el hero es el 1) |
| `kpi_id` | string | | Id estable del indicador |
| `label` | string | | Etiqueta, tal como la pone el informe |
| `value` | number | `unit` | La cifra, sin formatear |
| `unit` | string | | Ver el vocabulario de unidades |
| `value_display` | string | | La cifra como la formatea el informe (coma decimal, €). Sólo de referencia: el dashboard debería formatear `value` |
| `period_start` | date | | Primer mes del periodo que cubre la cifra |
| `period_end` | date | | Último mes del periodo |
| `period_label` | string | | El periodo en castellano: `Ago 2026`, `Sep 2023 – May 2026` |
| `note` | string | | La nota del informe bajo la cifra |

Los periodos son de cuatro tipos: el último mes (`Ago 2026`), los últimos doce
meses, el histórico completo y la ventana de coste, que termina en el **corte
de censura del 31 de mayo de 2026**: los contactos de marketing de los últimos
~70 días están incompletos por construcción y todo lo que divide coste entre
altas se corta ahí.

Los siete de la portada:

| `kpi_id` | Qué es |
|---|---|
| `revenue_total` | Ingreso acumulado de los cuatro canales en el histórico (hero) |
| `active_subscribers` | Suscriptores activos netos de pausas en el último mes |
| `subscribers_yoy` | Crecimiento de esos activos frente al mismo mes del año anterior |
| `cac_loaded` | CAC cargado: todo el gasto, también el que no se puede asignar, entre todas las altas |
| `ltv_projected` | LTV de suscripción proyectado a 36 meses, medio ponderado |
| `payback_slowest` | Meses que tarda el canal más lento en devolver el CAC; el objetivo habitual son 12 |
| `recoverable_value_year` | Valor al año de los dos primeros puntos del plan (rescate de cobros + roturas de stock) |

### `subscribers_monthly`

Un mes por fila, de septiembre de 2023 a agosto de 2026. Sale de
`suscriptores.json` (`series` y `outlier_months`), que a su vez lee el mart
`fct_subscriptions_monthly`.

| Columna | Tipo | Unidad | Descripción |
|---|---|---|---|
| `month` | date | | Mes |
| `active_net_of_pauses` | integer | suscriptores | Activos al cierre del mes y sin pausa (`is_active_net_of_pauses`). Es la serie del informe: la única donde se ve el valle de verano |
| `paused_subscriptions` | integer | suscripciones | En pausa ese mes. No son bajas: vuelven en otoño |
| `active_eom` | integer | suscriptores | Activos al cierre del mes contando las pausas (`is_active_eom`). Cumple `active_eom = active_net_of_pauses + paused_subscriptions` |
| `signups` | integer | altas | Suscripciones nuevas del mes |
| `is_outlier` | boolean | | Mes atípico en el residuo del STL (agosto de 2025 y 2026, por debajo: la pausa de verano crece cada año) |
| `outlier_sigmas` | number | desviaciones | Cuántas desviaciones robustas se aparta; vacío si no es atípico |

### `revenue_by_channel`

Mes × canal de **venta** (no de captación): suscripción, tienda online, boutique
y máquinas. Sale de `ingresos.json` (`series`, `channel_mix.by_month_pct` y
`payment_gap.detected_month`).

| Columna | Tipo | Unidad | Descripción |
|---|---|---|---|
| `month` | date | | Mes |
| `channel` | string | | `suscripcion`, `online`, `tienda`, `maquina` |
| `channel_label` | string | | Suscripción, Tienda online, Boutique, Máquinas |
| `color`, `color_dark` | string | hex | Ranuras 1-4 de la paleta, en el orden de apilado del informe |
| `revenue_eur` | number | € | Ingreso reconocido (devengado) del canal en el mes |
| `share_pct` | number | % | Peso del canal en el ingreso del mes; los cuatro suman 100 |
| `is_payment_gap_month` | boolean | | Mes de la migración de pasarela (marzo de 2025) |

**Ojo con el hueco de cobros.** El ingreso es el devengado, que es la única
medida que representa servicio prestado, y por eso **no** cae en el mes del
hueco: la semana perdida es de caja, no de ingreso. La marca
`is_payment_gap_month` sirve para anotar el mes en el gráfico de ingresos, pero
la evidencia está en `payment_gap`.

### `payment_gap`

Un mes por fila. Sale de `ingresos.json` (`payment_gap`).

| Columna | Tipo | Unidad | Descripción |
|---|---|---|---|
| `month` | date | | Mes |
| `cash_ratio` | number | cociente | Caja cobrada / MRR contratado. Es el denominador que no crece con el negocio, y por eso el hueco salta |
| `cash_ratio_median` | number | cociente | Mediana del histórico, la misma en todas las filas: línea de referencia |
| `collected_per_active_eur` | number | € | Caja cobrada por suscriptor activo |
| `mrr_per_active_eur` | number | € | MRR contratado por suscriptor activo |
| `is_payment_gap_month` | boolean | | Mes del hueco, el mínimo del histórico |

Los tres primeros meses salen muy por encima de 1 (hasta 1,64) con una base de
pocas decenas de suscriptores; conviene recortar el eje o empezar el gráfico en
diciembre de 2023. El KPI `payment_gap_cash_drop` (página `ingresos`) da la
caída del mes del hueco frente a la mediana.

### `capsule_demand`

Mes × sabor, doce sabores. Sale de `capsulas.json` (`series.by_flavor`, que ya
trae la demanda corregida, y `series.by_flavor_censored`, que guarda lo
observado de los cuatro sabores con rotura).

| Columna | Tipo | Unidad | Descripción |
|---|---|---|---|
| `month` | date | | Mes |
| `flavor` | string | | Sabor canónico (`canonical_sku`): los relanzados ya van unidos |
| `flavor_label` | string | | Nombre del sabor |
| `is_seasonal` | boolean | | Calabaza y jengibre |
| `color`, `color_dark` | string | hex | Color sólo en los dos de temporada; gris en los diez de base |
| `units` | number | cápsulas | Demanda corregida: club + tienda, con las ventanas de rotura imputadas. Tiene decimales en los meses con rotura |
| `units_observed` | number | cápsulas | Lo que se vendió de verdad |
| `units_lost` | number | cápsulas | `units - units_observed`: demanda que no se pudo servir |
| `has_stockout` | boolean | | El mes tiene unidades perdidas |

Se mide en unidades y no en euros a propósito: el relanzamiento de tres SKU
sube el precio y contaminaría la serie.

### `capsule_seasonality`

Mes del año × sabor: el índice de demanda sobre la tendencia, mediana de los
últimos 24 meses. Sale de `capsulas.json` (`seasonal_profile.by_month`).

| Columna | Tipo | Unidad | Descripción |
|---|---|---|---|
| `month_of_year` | integer | | 1 a 12 |
| `month_label` | string | | Ene … Dic |
| `flavor`, `flavor_label`, `is_seasonal`, `color`, `color_dark` | | | Como en `capsule_demand` |
| `demand_index` | number | cociente | Demanda / tendencia. 1 = mes en línea con la tendencia |
| `demand_index_log2` | number | log2 | El mismo índice en log2, centrado en 0 |

Para un mapa de calor, usar `demand_index_log2` con una escala divergente
centrada en 0: el índice es una razón, y en lineal con el centro en 1 los
sabores de base salen teñidos (es la misma decisión que tomó el informe).

### `stockouts`

Una fila por rotura de stock detectada: son seis. Sale de `capsulas.json`
(`censored_demand.windows`, `.lost_demand.by_flavor` y `.validation.by_window`).

| Columna | Tipo | Unidad | Descripción |
|---|---|---|---|
| `stockout_id` | string | | `sabor_fechainicio` |
| `flavor`, `flavor_label`, `is_seasonal`, `color`, `color_dark` | | | Como en `capsule_demand` |
| `start_date`, `end_date` | date | | Primer y último día sin venta en tienda |
| `days` | integer | días | Duración |
| `lost_units` | number | cápsulas | Demanda esperada que no se sirvió |
| `avg_price_eur` | number | € | Precio medio por cápsula del sabor |
| `lost_eur` | number | € | `lost_units × avg_price_eur`. Las seis suman la venta perdida del KPI `stockout_lost_sales` (el script lo comprueba) |
| `club_ratio` | number | cociente | Envíos del club observados / esperados durante la ventana. Cerca de 1 = el club siguió sirviendo: era falta de stock, no de interés |
| `lines_estimated` | number | líneas | Líneas de pedido que el análisis estima perdidas |
| `lines_real` | integer | líneas | Las que de verdad se perdieron, según el manifiesto del generador. Se abre después de detectar, sólo para validar |
| `estimation_error_pct` | number | % | Error de la estimación en esa ventana |

### `retention_by_channel`

Edad (0 a 35 meses) × canal de captación, seis canales. Sale de
`cohorts_rfm.json` (`ltv_by_channel.retention_by_channel` y
`.channels[].ultima_edad_fiable`).

| Columna | Tipo | Unidad | Descripción |
|---|---|---|---|
| `age_months` | integer | meses | Meses desde el alta; 0 = mes de alta |
| `channel` | string | | `paid_social`, `podcast_ads`, `influencer_code`, `referral`, `organic`, `direct_unknown` |
| `channel_label` | string | | Paid social, Podcast, Código influencer, Referido, Orgánico, Directo / sin resolver |
| `color`, `color_dark` | string | hex | Color del canal |
| `retention_pct` | number | % | Porcentaje de las suscripciones del canal que sigue activo a esa edad. Es la curva con la que se proyecta el LTV |
| `is_extrapolated` | boolean | | La edad está más allá de la última que escriben cohortes suficientes; desde ahí la curva es proyección. Conviene pintar ese tramo discontinuo |

Los canales no se separan hasta pasado un año (unos 4 puntos de dispersión al
mes 3 y 15 al mes 18): un gráfico recortado a los primeros meses los hace
parecer equivalentes.

### `cac_ltv`

Un canal por fila: los cuatro con coste (`is_priced = true`) y los dos que no
se pueden cruzar. Sale de `cac_ltv.json` (`crossover`, `unpriced_channels`,
`plausibility.breakeven_margin_pct` y `meta`) y, para las suscripciones, de
`cohorts_rfm.json` (`ltv_by_channel.channels`).

| Columna | Tipo | Unidad | Descripción |
|---|---|---|---|
| `channel`, `channel_label`, `color`, `color_dark` | | | Como en `retention_by_channel` |
| `is_priced` | boolean | | Tiene coste de medios y entra en el cruce |
| `cac_loaded_eur` | number | € | **CAC cargado**: coste del canal más su parte del gasto huérfano, entre sus conversiones (Markov). Es el que usa el cruce |
| `cac_attributed_eur` | number | € | CAC del reparto, sin el gasto huérfano |
| `ltv_projected_eur` | number | € | **LTV proyectado** a 36 meses con la curva del canal. Es el que usa el cruce |
| `ltv_observed_mature_eur` | number | € | LTV observado sobre suscripciones de 12 meses o más. Sólo promedia supervivientes: no usar para ordenar |
| `ratio` | number | veces | `ltv_projected_eur / cac_loaded_eur` |
| `payback_months` | number | meses | Meses de ARPU que cuesta recuperar el CAC cargado |
| `arpu_month_eur` | number | € | Ingreso medio mensual por suscripción del canal |
| `expected_months` | number | meses | Vida esperada a 36 meses: la suma de `retention_by_channel` del canal, en tanto por uno |
| `retention_12m_pct` | number | % | Sigue activa al año |
| `subscriptions` | integer | suscripciones | Suscripciones del canal en la curva de retención |
| `conversions_attributed` | number | conversiones | Conversiones que el modelo de Markov da al canal (fraccionarias) |
| `breakeven_margin_pct` | number | % | Margen bruto mínimo para que el ratio llegue a 3 |
| `verdict` | string | | Escalar / Mantener y vigilar la retención / Revisar el coste |
| `unpriced_reason` | string | | Por qué no se cruza (sólo `is_priced = false`) |
| `target_ratio` | number | veces | Ratio sano de referencia (3), igual en todas las filas |
| `target_payback_months` | number | meses | Payback objetivo de referencia (12), igual en todas las filas |

`organic` no tiene CAC porque no lleva coste de medios en el dataset, no porque
sea gratis; `direct_unknown` no es un canal sino el cajón de las altas sin
recorrido. Ninguno de los dos debe aparecer en un ranking de ratio. Y los ratios
de 12× a 37× son ingreso, no margen (no hay coste de producto): `cac_ltv_scenarios`
los pone en contexto.

### `cac_ltv_scenarios`

Escenario × canal con coste. Dos grupos de escenarios en el mismo grano, porque
los dos responden a si la conclusión aguanta. Sale de `cac_ltv.json`
(`robustness.ratios`, `robustness.ranks` y `plausibility.ratio_by_margin`).

| Columna | Tipo | Unidad | Descripción |
|---|---|---|---|
| `scenario_group` | string | | `method`: las cuatro combinaciones de CAC (cargado / reparto) × LTV (proyectado / observado). `margin`: el ratio si el LTV se multiplica por un margen bruto |
| `scenario_id` | string | | `loaded_projected`, `attributed_projected`, `loaded_observed_mature`, `attributed_observed_mature`, `margin_10`, `margin_30`, `margin_50`, `margin_70` |
| `scenario_label` | string | | Etiqueta del escenario |
| `channel`, `channel_label`, `color`, `color_dark` | | | Como en `cac_ltv` |
| `ratio` | number | veces | LTV / CAC en ese escenario |
| `rank` | integer | | Puesto del canal (1 = mejor). Sólo en `method` |
| `margin_pct` | number | % | Margen supuesto. Sólo en `margin` |
| `is_reference` | boolean | | El escenario del informe (cargado × proyectado) |

### `attribution_by_model`

Canal × modelo de atribución: cinco canales (sin `direct_unknown`, que no tiene
recorrido que repartir) por cuatro modelos. Sale de `attribution.json`
(`models.credit_pct`, `models.spread_by_channel_pp`, `cac.by_channel` y
`channels[].is_paid`).

| Columna | Tipo | Unidad | Descripción |
|---|---|---|---|
| `channel`, `channel_label`, `color`, `color_dark` | | | Como en `retention_by_channel` |
| `model` | string | | `first_touch`, `last_touch`, `linear`, `markov` |
| `model_label` | string | | First touch, Last touch, Linear, Markov |
| `credit_pct` | number | % | Parte de las conversiones que el modelo da al canal; los cinco canales suman 100 en cada modelo |
| `cac_eur` | number | € | Coste asignable del canal entre las conversiones que le da ese modelo. Vacío en `organic`, que no tiene coste de medios |
| `is_paid` | boolean | | Tiene coste de medios |
| `credit_spread_pp` | number | pp | Distancia entre el modelo que más y el que menos crédito le da; igual en las cuatro filas del canal |

La lectura es que el modelo casi no importa (dispersión máxima de 3,6 puntos y
el mismo orden en los cuatro); lo que sí mueve el CAC es el gap, en
`attribution_gap`.

### `attribution_gap`

Un canal por fila, los seis. Todo dentro de la ventana de coste, hasta el corte
de censura. Sale de `attribution.json` (`channels`, `attribution_gap.by_channel`
y `cac.by_channel`). Los totales del gap (39,4% de contactos sin cliente, CAC
infravalorado un 24%) están en `kpis`, página `atribucion`.

| Columna | Tipo | Unidad | Descripción |
|---|---|---|---|
| `channel`, `channel_label`, `color`, `color_dark` | | | Como en `retention_by_channel` |
| `is_paid` | boolean | | Tiene coste de medios |
| `touchpoints` | integer | contactos | Contactos de marketing del canal |
| `orphan_touchpoints` | integer | contactos | Los que no se pueden unir a ningún cliente |
| `orphan_touchpoints_pct` | number | % | `orphan_touchpoints / touchpoints` |
| `attributable_cost_eur` | number | € | Coste de los contactos con cliente |
| `orphan_cost_eur` | number | € | Coste de los contactos sin cliente |
| `total_cost_eur` | number | € | La suma de los dos |
| `cac_attributed_eur` | number | € | CAC del reparto (Markov). Vacío si no tiene coste |
| `cac_loaded_eur` | number | € | CAC cargado con el gasto huérfano. Vacío si no tiene coste |
| `cac_uplift_pct` | number | % | Cuánto sube el CAC al cargarlo: `cac_loaded / cac_attributed - 1`. No es igual para todos (paid social +44%, código de influencer +27%), y por eso reordena el ranking |

Paid social está penalizado además por la ventana tipo iOS ATT de enero a junio
de 2025: su CAC real es algo mejor que el publicado.

### `recommendations`

Una fila por recomendación del informe: 23. Sale de `report/content.py`, que
guarda junto a cada una la cifra que la sostiene.

| Columna | Tipo | Unidad | Descripción |
|---|---|---|---|
| `rec_id` | string | | Id estable |
| `page`, `page_title` | string | | Página del informe donde está |
| `position` | integer | | Orden dentro de la página |
| `is_cover_plan` | boolean | | Es uno de los cinco puntos del plan de acción de la portada |
| `same_as` | string | | En los cinco de la portada, el `rec_id` de la misma recomendación en su página. Para listar las 18 distintas, filtrar `same_as` vacío |
| `action` | string | | Qué hacer |
| `why` | string | | Por qué, con las cifras del hallazgo ya redactadas |
| `impact` | string | | Impacto estimado, en texto |
| `owner` | string | | Quién lo haría |
| `effort` | string | | bajo / medio |
| `measure` | string | | Con qué métrica se sabría si funcionó |
| `metric_value` | number | `metric_unit` | **La cifra que sostiene la recomendación**, sin formatear |
| `metric_unit` | string | | Ver el vocabulario de unidades |
| `metric_label` | string | | Qué es esa cifra |

Los textos (`why`, `impact`) llevan cifras redactadas en castellano porque son
prosa; para pintar, ordenar o sumar, usar `metric_value`.
