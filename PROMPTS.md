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
