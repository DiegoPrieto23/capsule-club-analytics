# Prompts secuenciales para Claude Code

Pégalos en orden, uno por uno, dejando que Claude Code termine y revisando el resultado antes de pasar al siguiente. Todos asumen que Claude Code ya ha leído `CLAUDE.md` (lo hace automáticamente al abrir el proyecto).

---

### Prompt 1 — Estructura y entorno

Lee CLAUDE.md y todo docs/. Crea la estructura de carpetas del proyecto tal como se describe en CLAUDE.md. Inicializa un entorno virtual de Python y crea requirements.txt con las dependencias necesarias: pandas, duckdb, dbt-duckdb, statsmodels, prophet (o el equivalente que consideres más adecuado), scikit-learn, lightgbm, plotly, jinja2, faker. Crea también un .gitignore adecuado (venv, *.duckdb, __pycache__, analysis/outputs/).

---

### Prompt 2 — Generación de datos sintéticos

Implementa data_generation/generate_synthetic_data.py siguiendo exactamente docs/data_schema.md para el esquema de tablas y docs/data_imperfections.md para las imperfecciones a inyectar — todas, no solo algunas. Usa una semilla fija para que el dataset sea reproducible. Parametriza al principio del script el rango de fechas (usa 3 años de histórico), el número de clientes, tiendas y sabores de cápsula. El script debe guardar cada tabla en data/raw/ como parquet y cargarlas todas en un DuckDB en data/warehouse.duckdb como tablas raw_*. Al final, imprime un resumen de filas generadas por tabla y de cuántos registros de cada imperfección se inyectaron, para poder verificar que están presentes.

---

### Prompt 3 — Proyecto dbt

Inicializa dbt en dbt_project/ con el adaptador dbt-duckdb apuntando a data/warehouse.duckdb. Crea modelos de staging (uno por tabla raw_*, con tipado correcto y normalización básica de nombres de canal). Crea modelos intermedios que resuelvan la duplicidad de customer_id por variantes de email, y que unan machine_orders con subscriptions para detectar conversiones de comprador de máquina a suscriptor semanas después. Crea los marts finales: dim_customers, fct_subscriptions_monthly, fct_shop_orders, fct_shipments, fct_marketing_attribution. Añade tests dbt (unique, not_null, relationships) en cada mart y documenta cada modelo en su schema.yml.

---

### Prompt 4 — Utilidades compartidas de series temporales

Crea analysis/utils_timeseries.py con funciones reutilizables para descomposición STL, test de estacionariedad (ADF), y una función de backtesting walk-forward genérica, para no repetir esta lógica en los tres notebooks de serie temporal.

---

### Prompt 5 — Serie temporal: suscriptores

Crea analysis/01_time_series_suscriptores.ipynb: carga fct_subscriptions_monthly desde el DuckDB, calcula la serie de suscriptores activos por mes, aplica descomposición y tests de estacionariedad usando utils_timeseries.py, y compara al menos dos modelos de forecast: uno clásico (Prophet o SARIMA) y uno basado en curvas de retención por cohorte histórica. Guarda los resultados en analysis/outputs/suscriptores.json (serie histórica, forecast e intervalos de confianza).

---

### Prompt 6 — Serie temporal: ingresos

Igual que el prompt anterior pero para fct_shop_orders + fct_subscriptions_monthly combinados en ingresos totales (online + tienda), desglosando también por canal. Guarda en analysis/outputs/ingresos.json.

---

### Prompt 7 — Serie temporal: demanda por sabor

Crea analysis/03_time_series_capsulas.ipynb a nivel de SKU de cápsula (fct_shipments + fct_shop_orders), tratando explícitamente la demanda censurada por rotura de stock y la discontinuidad de SKUs relanzados (ver docs/data_imperfections.md). Guarda en analysis/outputs/capsulas.json.

---

### Prompt 8 — Cohortes & RFM

Crea analysis/04_cohorts_rfm.ipynb: curvas de retención por cohorte mensual de alta de suscripción, aislando el efecto del descuento de bienvenida en el mes 0, y tratando explícitamente las suscripciones regaladas y los downgrades. Añade RFM clásico sobre fct_shop_orders. Guarda resultados en analysis/outputs/cohorts_rfm.json.

---

### Prompt 9 — Atribución

Crea analysis/05_attribution.ipynb: implementa al menos tres modelos heurísticos (first/last/linear touch) y un modelo de Markov chain sobre fct_marketing_attribution, calculando el CAC por canal. Cuantifica y muestra explícitamente el attribution gap (porcentaje de conversiones sin touchpoint resuelto). Guarda resultados en analysis/outputs/attribution.json.

---

### Prompt 10 — Cruce CAC × LTV

Crea analysis/06_cac_ltv_crossover.ipynb que cruce el CAC por canal de attribution.json con el LTV real observado por canal de adquisición en cohorts_rfm.json, y genere la tabla/gráfico final de este cruce. Guarda en analysis/outputs/cac_ltv.json.

---

### Prompt 11 — Informe HTML final

Crea report/build_report.py que lea todos los JSON de analysis/outputs/ y genere un informe HTML estático multipágina siguiendo exactamente docs/report_structure.md, con gráficos Plotly embebidos y navegación entre páginas sin necesidad de servidor. Usa plantillas Jinja2 en report/templates/ para mantener consistencia visual entre páginas.

---

### Prompt 12 — Revisión final

Repasa todo el proyecto: comprueba que los tests de dbt pasan, que cada notebook corre de principio a fin sin errores, y que el informe HTML se abre correctamente y navega bien entre sus 7 páginas. Haz una lista de cualquier deuda técnica o simplificación que hayas tenido que asumir, para que Diego la revise.

---

## Fase 2 — Orquestación con Airflow + Cosmos, datos para dashboard y README

Decisiones ya tomadas por Diego (no reabrirlas sin preguntar):

- **Airflow con Astro CLI** sobre Docker Desktop, en local. La regla "todo en local, sin servicios de pago" se mantiene.
- **El DAG orquesta el pipeline completo**: generar datos → dbt con Cosmos → seis notebooks → informe HTML → exportación de datos para el dashboard.
- **El informe HTML sigue siendo el entregable principal** (GitHub Pages no cambia). El dashboard de Claude es un complemento ejecutivo que se construye fuera del repo, en claude.ai, a partir de CSV planos que genera el repo.
- **La ejecución sin Airflow tiene que seguir funcionando** (los tres comandos actuales del README), para quien no tenga Docker.
- **Sin previsión** (decidido durante el prompt 15): los notebooks y el informe no incluyen modelos de forecast, backtesting ni contrastes de estacionariedad. Las páginas de serie temporal son descriptivas. El LTV proyectado a 36 meses se mantiene.

Trabajar en la rama `feature/airflow-cosmos`. Sin push, y sin commit hasta que Diego revise cada prompt.

---

### Prompt 13 — Proyecto Astro y entorno

Lee CLAUDE.md, este bloque de PROMPTS.md y `dbt_project/README.md`. Antes de escribir nada, comprueba en la documentación oficial las versiones actuales y su compatibilidad: Astro Runtime (que traiga Airflow 3.x), `astronomer-cosmos` (≥1.15) y `dbt-duckdb`. Si algo choca con lo que se dice aquí, pregúntame.

1. Integra un proyecto Astro en la raíz del repo sin romper la estructura actual (`astro dev init` sólo si no pisa nada; si no, crea a mano `Dockerfile`, `dags/`, `include/`, `packages.txt`, `airflow_settings.yaml`, `.astro/`). Añade un `.dockerignore` que excluya `venv/`, `.git/`, `dbt_project/target/`, `dbt_project/logs/` y los `__pycache__`.
2. Dentro de la imagen, separa los entornos para que las dependencias de Airflow no choquen con las del proyecto, como recomienda Cosmos:
   - un venv para dbt (`dbt-core` + `dbt-duckdb`, con las mismas versiones mayores que el `venv` local), que Cosmos usará con `dbt_executable_path`;
   - un venv de análisis con lo que necesitan el generador, los notebooks y el informe (el `requirements.txt` actual más `papermill` y un kernel registrado);
   - en el entorno de Airflow, sólo `astronomer-cosmos` y lo mínimo imprescindible.
   Si hace falta partir `requirements.txt`, hazlo de forma que la instalación local de Windows siga siendo un único `pip install -r requirements.txt`.
3. Lo que el DAG escribe tiene que aparecer en el repo del host, no quedarse dentro del contenedor: `data/raw/`, `data/warehouse.duckdb`, `analysis/outputs/`, `report/dist/` y la carpeta de datos del dashboard (prompt 16). Resuélvelo con un `docker-compose.override.yml` de Astro que monte esas rutas, y define la ruta de DuckDB en el contenedor con `CAPSULE_DUCKDB_PATH`, que `profiles.yml` ya sabe leer.
4. Verifica: `astro dev start` levanta Airflow, y dentro del contenedor el venv de dbt ejecuta `dbt debug --profiles-dir .` contra el DuckDB montado.
5. Actualiza CLAUDE.md: añade Airflow + Cosmos a las decisiones de alcance (stack) y la nueva carpeta al árbol de estructura.

Cuando termines, dime qué decisiones has tomado que no estuvieran aquí.

---

### Prompt 14 — dbt con Cosmos

Crea en `dags/` el DAG `capsule_club_pipeline` (de momento sólo la parte de dbt) con un `DbtTaskGroup` de Cosmos sobre `dbt_project/`, usando `ProfileConfig` con el `profiles.yml` del proyecto (no generes un perfil desde una conexión de Airflow) y el venv de dbt del prompt 13.

La restricción que manda es que **DuckDB sólo admite un proceso escritor**. Con el modo por defecto de Cosmos (un `dbt run` por modelo), las tareas en paralelo fallan con "Could not set lock on file". Evalúa dos opciones y elige justificándolo:

- `ExecutionMode.WATCHER`: un único `dbt build` (que puede usar los 4 threads de `profiles.yml`) y una tarea por modelo que lo observa. Comprueba en la documentación de Cosmos que esté soportado con la versión de Airflow de la imagen.
- `ExecutionMode.LOCAL` con un pool de Airflow de un solo hueco para el grupo dbt.

Más requisitos:
- Los 220 tests tienen que seguir ejecutándose y bloquear lo que va detrás si fallan (elige el `TestBehavior` que lo garantice).
- Agrupa las tareas por capa (staging / intermediate / marts) si Cosmos lo permite sin forzarlo.
- Elige el `LoadMode` (manifest o `dbt ls`) pensando en el tiempo de parseo del DAG, y explica por qué.

Verifica: lanza el DAG desde la UI o con `astro dev run dags test` y confirma que quedan 245/245 nodos en verde, igual que con `dbt build` en local. Apunta cuánto tarda frente a la ejecución local.

---

### Prompt 15 — Pipeline completo en el DAG

Amplía `capsule_club_pipeline` para que cubra todo el recorrido:

1. `generate_data`: ejecuta `data_generation/generate_synthetic_data.py` con el venv de análisis. Tiene que poder reejecutarse: si el DuckDB existe, el generador lo reconstruye sin dejarlo a medias.
2. El grupo dbt del prompt 14.
3. Un grupo `analysis` que ejecute los seis notebooks con papermill, guardando el notebook ejecutado como artefacto de log, no encima del original. Saca las dependencias reales de qué JSON lee cada notebook (por ejemplo, el 06 lee `attribution.json` y `cohorts_rfm.json`), no del número de orden, y paraleliza lo que sea independiente: los notebooks abren DuckDB con `read_only=True`. Comprueba que el 06 también lo haga.
4. `build_report`: ejecuta `report/build_report.py`.

Sin `schedule` (se lanza a mano), con `catchup=False` y reintentos razonables sólo en las tareas donde tenga sentido.

Verifica: una ejecución completa desde cero (borrando `data/warehouse.duckdb` y `analysis/outputs/*.json`) termina en verde y `git diff report/dist` no muestra cambios en ninguna cifra. Como la semilla es fija, cualquier diferencia que no sea una marca de tiempo es un bug y hay que investigarlo antes de seguir.

---

### Prompt 16 — Exportación de datos para el dashboard de Claude

El dashboard se construirá después en claude.ai con el tipo Dashboard. Ese tipo tiene estas reglas, que la exportación tiene que cumplir:

- Cada dataset es un fichero CSV (o JSON con un array de filas) **plano**, de hasta 8 MB. Nada de objetos anidados.
- El id de cada dataset sólo puede llevar `[A-Za-z0-9_-]` y un máximo de 64 caracteres. Usa ese id como nombre de fichero.
- **Ninguna cifra se escribe en el HTML del dashboard**: todas salen de un dataset, así que cualquier KPI o número que haya que enseñar necesita una fila en algún dataset.
- Números sin formatear (punto decimal, sin símbolo de €), fechas ISO `YYYY-MM-DD` y una columna de etiqueta en español cuando el valor sea una clave (`paid_social` → "Paid social"), reutilizando las etiquetas y colores que ya están en `report/theme.py` y `_relabel()`.

Crea `dashboard/export_dashboard_data.py`, que lea `analysis/outputs/*.json` (y los marts, sólo cuando un dato no esté en los JSON) y escriba `dashboard/data/*.csv`. Como mínimo, una vista ejecutiva con:

- `kpis`: una fila por KPI de la portada (id, etiqueta, valor, unidad, periodo, nota);
- `subscribers_monthly`: activos netos de pausas y suscripciones en pausa, por mes;
- `revenue_by_channel`: ingresos mensuales por canal, con la semana de cobros perdida identificable;
- `capsule_demand` y `stockouts`: demanda por sabor y las seis roturas con su venta perdida;
- `retention_by_channel`: curvas de retención por canal;
- `cac_ltv`: el cruce por canal (CAC cargado, LTV proyectado, ratio, payback, veredicto);
- `attribution_by_model`: crédito por canal en los cuatro modelos, más el gap;
- `recommendations`: las 25 recomendaciones, con la cifra que las sostiene en una columna numérica aparte.

Ajusta la lista si al mirar los JSON ves que otra partición cuenta mejor la historia, y explícamelo. Escribe también `dashboard/README.md` con un diccionario de datos: por cada dataset, el grano, las columnas con su tipo y unidad, y de qué JSON o mart sale. Me servirá para montar el dashboard.

Añade `export_dashboard_data` como última tarea del DAG, después de `build_report`. Versiona `dashboard/data/` (revisa que `.gitignore` no lo excluya), igual que `report/dist/`.

---

### Prompt 17 — README y documentación

Reescribe `README.md` con estos cambios:

1. **Elimina la sección "Qué pretende demostrar"** y cualquier frase del mismo tipo que hable de intenciones u objetivos de portfolio en vez de describir el proyecto. Por ejemplo: "El foco no está en montar el pipeline, sino en…", "para poder hacer con él lo que se hace con los datos de un negocio real…", y cualquier "pretende", "demuestra", "sirve para mostrar". Los hechos que contenía esa sección (las anomalías no vienen señaladas y se documentan en vez de corregirse en silencio; los rankings se recalculan con otros criterios; 23 recomendaciones con su cifra) no se pierden: pásalos a "Los datos" y "Qué se ha medido" en tono descriptivo. Quita también toda mención a previsión, forecasting o backtesting: el proyecto ya no los tiene.
2. Actualiza el stack, "Cómo está hecho", "Ejecutarlo en local" y "Dónde está cada cosa" con Airflow + Cosmos y la carpeta `dashboard/`. Añade un diagrama Mermaid del DAG (tareas y grupos) y una nota de por qué se eligió el modo de ejecución de Cosmos (el bloqueo de escritura de DuckDB).
3. "Ejecutarlo en local" con dos caminos: con Airflow (Docker Desktop + Astro CLI: `astro dev start` y lanzar el DAG) y sin Airflow (los tres comandos actuales, que tienen que seguir funcionando).
4. No menciones el dashboard de Claude todavía: lo añadiré yo cuando exista el enlace.

Mantén el estilo actual: sin primera persona, en español, frases directas y las cifras tal como están. Revisa que ninguna cifra cambie. Actualiza también `dbt_project/README.md` (cómo se ejecuta con Cosmos) y, si hace falta, `docs/`.

---

### Prompt 18 — Revisión final de la fase 2

Repasa todo:
- una ejecución completa del DAG desde cero termina en verde;
- `dbt build` en local (sin Airflow) sigue dejando 245/245;
- el informe es idéntico en cifras;
- los CSV de `dashboard/data/` cumplen las reglas del prompt 16 (plano, menos de 8 MB, ids válidos, números sin formatear);
- el README se lee de principio a fin sin restos de la sección eliminada.

Actualiza la sección "Estado actual" de CLAUDE.md con lo que conviene saber de esta fase (modo de Cosmos elegido y por qué, cómo se montan los volúmenes, tiempos). Termina con una lista de deuda técnica o simplificaciones asumidas para que Diego la revise.
