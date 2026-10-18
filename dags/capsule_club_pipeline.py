"""Pipeline de Capsule Club orquestado con Airflow + Cosmos.

    generate_data >> dbt >> analysis >> build_report >> export_dashboard_data

Se lanza a mano (sin schedule). Cada paso usa el venv que le toca dentro de la
imagen (ver Dockerfile): el generador, los notebooks y el informe, el de análisis;
dbt, el suyo, a través de Cosmos. Lo que escriben llega al repo del host por los
volúmenes de docker-compose.override.yml.

Tres decisiones de Cosmos que conviene no deshacer sin querer:

- **ExecutionMode.WATCHER.** DuckDB admite un único proceso escritor, así que el
  modo por defecto (un `dbt run` por modelo, en paralelo) choca con "Could not set
  lock on file". En el modo watcher un solo productor lanza un único `dbt build`
  con los 4 threads de profiles.yml (el mismo comando que en local), y cada modelo
  y sus tests tienen una tarea que se limita a observarlo vía XCom: un solo
  escritor por construcción, sin pool que serialice nada.
- **TestBehavior.AFTER_EACH.** Los 220 tests corren dentro del `dbt build` (que ya
  salta los hijos de un modelo cuyo test falla) y cada modelo tiene una tarea
  `.test` que falla si falla cualquiera de los suyos; los tests con varios padres
  (relationships) cuentan en todos ellos. Si el productor falla, la puerta
  `producer_watcher_done` del grupo queda en upstream_failed, así que lo que vaya
  detrás del grupo no arranca. BUILD no existe en este modo y AFTER_ALL volvería
  a lanzar los tests en un segundo proceso.
- **LoadMode.DBT_MANIFEST.** El manifest se genera con `dbt parse` al construir
  la imagen (ver Dockerfile), así que parsear el DAG es leer un JSON: el
  dag-processor no lanza dbt (12 s por `dbt ls` sin caché) cada vez que relee la
  carpeta. No puede quedarse desfasado porque dbt_project/ también va horneado en
  la imagen: cualquier cambio en dbt exige `astro dev restart`, que lo regenera.

Reintentos, sólo donde un fallo puede ser pasajero:

- `generate_data` y los notebooks: el fallo transitorio realista es encontrarse
  el DuckDB bloqueado (un notebook o una sesión abiertos contra el mismo fichero
  desde el host) o quedarse sin memoria.

Los notebooks comparten el pool `analysis_notebooks` (3 huecos, definido en
airflow_settings.yaml): con los cinco primeros a la vez, DuckDB llegó a fallar
con "Cannot allocate memory" dentro de la VM de Docker Desktop.
- dbt, ninguno: el productor no repite el `dbt build` al reintentarse, y un
  sensor reintentado lanza su propio `dbt run`, que competiría por el bloqueo.
- `build_report` y `export_dashboard_data`, ninguno: sólo leen JSON y escriben
  HTML o CSV; si fallan, es un bug.
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta
from pathlib import Path

from airflow.providers.standard.operators.bash import BashOperator
from airflow.sdk import DAG, TaskGroup
from cosmos import DbtTaskGroup, ExecutionConfig, ProfileConfig, ProjectConfig, RenderConfig
from cosmos.constants import ExecutionMode, LoadMode, TestBehavior

AIRFLOW_HOME = Path(os.environ.get("AIRFLOW_HOME", "/usr/local/airflow"))
DBT_PROJECT_DIR = AIRFLOW_HOME / "dbt_project"
# venvs de la imagen (Dockerfile); Airflow no tiene dbt ni el stack de análisis.
DBT_EXECUTABLE = Path(os.environ.get("DBT_VENV", "/opt/venvs/dbt")) / "bin" / "dbt"
ANALYSIS_BIN = Path(os.environ.get("ANALYSIS_VENV", "/opt/venvs/analysis")) / "bin"

# Qué otros notebooks tiene que esperar cada uno: los JSON de analysis/outputs/
# que lee, no el número de orden. Del 01 al 05 sólo leen marts de DuckDB (con
# read_only=True, así que pueden ir a la vez; el 03 lee además el manifiesto de
# imperfecciones que escribe el generador); el 06 no abre DuckDB y cruza
# attribution.json (05) con cohorts_rfm.json (04).
NOTEBOOKS: dict[str, list[str]] = {
    "01_time_series_suscriptores": [],  # -> suscriptores.json
    "02_time_series_ingresos": [],      # -> ingresos.json
    "03_time_series_capsulas": [],      # -> capsulas.json
    "04_cohorts_rfm": [],               # -> cohorts_rfm.json
    "05_attribution": [],               # -> attribution.json
    "06_cac_ltv_crossover": ["04_cohorts_rfm", "05_attribution"],  # -> cac_ltv.json
}

# El notebook ejecutado se guarda junto al log de su tarea, como artefacto; el
# original de analysis/ no se toca. papermill corre desde analysis/ porque los
# notebooks resuelven la raíz del proyecto y sus utils_*.py desde el cwd.
PAPERMILL_CMD = (
    f'out="{AIRFLOW_HOME}/logs/dag_id={{{{ dag.dag_id }}}}'
    '/run_id={{ run_id }}/task_id={{ ti.task_id }}"; '
    'mkdir -p "$out" && '
    f'"{ANALYSIS_BIN}/papermill" "analysis/{{nb}}.ipynb" "$out/{{nb}}.ipynb" '
    "--cwd analysis --kernel capsule-analysis --log-output --no-progress-bar"
)

with DAG(
    dag_id="capsule_club_pipeline",
    schedule=None,
    start_date=datetime(2026, 1, 1),
    catchup=False,
    default_args={"retries": 0},
    tags=["capsule_club"],
    doc_md=__doc__,
) as dag:
    # El generador escribe en staging y publica el DuckDB de una vez al final, así
    # que reejecutarlo sobre un warehouse existente no lo deja a medias.
    generate_data = BashOperator(
        task_id="generate_data",
        bash_command=f'"{ANALYSIS_BIN}/python" data_generation/generate_synthetic_data.py',
        cwd=str(AIRFLOW_HOME),
        retries=2,
        retry_delay=timedelta(minutes=1),
        execution_timeout=timedelta(minutes=15),
    )

    dbt = DbtTaskGroup(
        group_id="dbt",
        project_config=ProjectConfig(
            dbt_project_path=DBT_PROJECT_DIR,
            manifest_path=DBT_PROJECT_DIR / "target" / "manifest.json",
        ),
        # El profiles.yml del proyecto, tal cual: la ruta de DuckDB llega por
        # CAPSULE_DUCKDB_PATH (docker-compose.override.yml).
        profile_config=ProfileConfig(
            profile_name="capsule_club",
            target_name="dev",
            profiles_yml_filepath=DBT_PROJECT_DIR / "profiles.yml",
        ),
        execution_config=ExecutionConfig(
            execution_mode=ExecutionMode.WATCHER,
            dbt_executable_path=DBT_EXECUTABLE,
        ),
        render_config=RenderConfig(
            load_method=LoadMode.DBT_MANIFEST,
            test_behavior=TestBehavior.AFTER_EACH,
            # models/staging, models/intermediate y models/marts -> un grupo por capa
            group_nodes_by_folder=True,
        ),
    )

    with TaskGroup(group_id="analysis") as analysis:
        notebooks = {
            nb: BashOperator(
                task_id=nb,
                bash_command=PAPERMILL_CMD.replace("{nb}", nb),
                cwd=str(AIRFLOW_HOME),
                pool="analysis_notebooks",
                retries=1,
                retry_delay=timedelta(minutes=2),
                execution_timeout=timedelta(minutes=15),
            )
            for nb in NOTEBOOKS
        }
        for nb, upstream in NOTEBOOKS.items():
            for dep in upstream:
                notebooks[dep] >> notebooks[nb]

    build_report = BashOperator(
        task_id="build_report",
        bash_command=f'"{ANALYSIS_BIN}/python" report/build_report.py',
        cwd=str(AIRFLOW_HOME),
        execution_timeout=timedelta(minutes=10),
    )

    # Los CSV del dashboard de Claude salen de los mismos JSON y las cifras de los
    # KPI y las recomendaciones, de report/content.py. Va detrás del informe para
    # que el dashboard nunca publique una cifra que el informe no haya publicado.
    export_dashboard_data = BashOperator(
        task_id="export_dashboard_data",
        bash_command=f'"{ANALYSIS_BIN}/python" dashboard/export_dashboard_data.py',
        cwd=str(AIRFLOW_HOME),
        execution_timeout=timedelta(minutes=5),
    )

    generate_data >> dbt >> analysis >> build_report >> export_dashboard_data
