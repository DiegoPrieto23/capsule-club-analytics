# dbt_project — Capsule Club Analytics

Pipeline dbt sobre DuckDB local. No necesita red ni `dbt deps`: no hay paquetes
externos (el único test no nativo, `unique_combination_of_columns`, está escrito
en `tests/generic/`).

## Cómo ejecutarlo

`profiles.yml` vive aquí, no en `~/.dbt`, así que hay que indicarlo:

```bash
cd dbt_project
../venv/Scripts/dbt run   --profiles-dir .     # o: dbt build --profiles-dir .
../venv/Scripts/dbt test  --profiles-dir .
../venv/Scripts/dbt docs generate --profiles-dir .
```

Requisito previo: `python data_generation/generate_synthetic_data.py`, que crea
`data/warehouse.duckdb` con las tablas `raw_*`.

DuckDB bloquea el fichero: cierra cualquier notebook o sesión de Python que lo
tenga abierto antes de lanzar dbt.

## Capas

| Capa | Materialización | Qué hace |
|---|---|---|
| `staging/` | vista | Una por tabla `raw_*`. Tipado, renombrado y normalización de canales. Sin lógica de negocio. |
| `intermediate/` | vista | Resolución de identidad, continuidad de SKU, estado mensual de suscripción, tarifa derivada, conversión máquina→suscripción, recorridos de marketing. |
| `marts/` | tabla | Lo único que consumen los notebooks. |

## Decisiones que conviene conocer antes de usar los marts

- **Identidad**: `customer_key` es el humano; `customer_id` es el registro de
  alta. La deduplicación usa una heurística de email documentada en
  `int_customer_identity` y resuelve 490 registros secundarios de 12.480.
- **Activos**: `fct_subscriptions_monthly` ofrece tres definiciones
  (`is_live`, `is_active_eom`, `is_active_net_of_pauses`). La estacionalidad de
  verano sólo es visible en la tercera.
- **Ingresos**: `contracted_mrr_eur` (señal limpia), `collected_eur` (caja, con
  el hueco de la migración de pasarela) y `recognized_revenue_eur` (cobro
  repartido por ciclo). No son intercambiables.
- **Clientes nulos**: las ventas de boutique sin fidelización tienen
  `customer_key` NULL en los hechos y no aparecen en `dim_customers`. Los
  ingresos totales no cuadran con los ingresos por cliente, y es correcto.
- **SKU relanzados**: agregar por `canonical_sku`, no por `product_sku`, salvo
  que se quiera ver la discontinuidad a propósito.
