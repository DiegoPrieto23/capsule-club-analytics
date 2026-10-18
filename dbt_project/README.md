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

## Cómo se ejecuta en Airflow (Cosmos)

En el DAG `capsule_club_pipeline` (`dags/capsule_club_pipeline.py`) este
proyecto es el `DbtTaskGroup` `dbt`, entre `generate_data` y los notebooks. No
hace falta lanzar nada a mano: `astro dev start` y lanzar el DAG.

- **Modo `ExecutionMode.WATCHER`.** DuckDB admite un único proceso escritor, y
  el modo por defecto de Cosmos (un `dbt run` por modelo, en paralelo) choca con
  `Could not set lock on file`. En el modo watcher la tarea
  `dbt_producer_watcher` lanza un único `dbt build` —el mismo comando que en
  local, con los 4 threads de `profiles.yml`— y el resto de tareas del grupo lo
  observan vía XCom. Un solo escritor por construcción.
- **Dos tareas por modelo**, `<modelo>.run` y `<modelo>.test`
  (`TestBehavior.AFTER_EACH`), agrupadas por carpeta: `models.staging`,
  `models.intermediate` y `models.marts`. Los 220 tests corren dentro del mismo
  `dbt build`; la tarea `.test` de un modelo falla si falla cualquiera de los
  suyos, y un test con varios padres (`relationships`) cuenta en todos.
- **Si el `dbt build` falla**, la puerta `dbt_producer_watcher_done` queda en
  `upstream_failed` y los notebooks no arrancan. Las tareas de dbt no tienen
  reintentos: el productor no repite el `dbt build`, y un sensor reintentado
  lanzaría su propio `dbt run`, que competiría por el bloqueo.
- **El DAG se parsea desde `target/manifest.json`** (`LoadMode.DBT_MANIFEST`),
  que genera `dbt parse` al construir la imagen (ver `Dockerfile`). Este
  directorio va horneado en la imagen, así que **cualquier cambio en dbt exige
  `astro dev restart`**, que reconstruye la imagen y regenera el manifest.
- **Mismo `profiles.yml`.** Cosmos lo usa tal cual (`profiles_yml_filepath`).
  La ruta del warehouse llega por `CAPSULE_DUCKDB_PATH`
  (`/usr/local/airflow/data/warehouse.duckdb`, definida en
  `docker-compose.override.yml`); sin ella, el perfil usa la ruta relativa
  `../data/warehouse.duckdb` de la ejecución local.
- **dbt vive en su propio venv** dentro de la imagen (`/opt/venvs/dbt`, el
  `dbt_executable_path` de Cosmos), con las versiones fijadas contra
  `requirements/constraints.txt`: el mismo dbt dentro y fuera del contenedor.

El bloqueo también aplica aquí: un notebook o una sesión de Python abiertos
desde el host contra `data/warehouse.duckdb` hacen fallar el `dbt build` del
contenedor.

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
