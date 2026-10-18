# Imagen de Airflow para orquestar el pipeline con Astro CLI (astro dev start).
#
# Se parte de la variante -base porque la imagen normal trae instrucciones ONBUILD
# que instalan el requirements.txt de la raíz en el entorno de Airflow, y ese
# fichero es el de la instalación local (dbt + todo el stack de análisis). Aquí se
# repiten a mano los mismos pasos, pero con tres entornos separados, como
# recomienda Cosmos:
#
#   entorno de Airflow   requirements/airflow.txt   sólo astronomer-cosmos
#   /opt/venvs/dbt       requirements/dbt.txt       dbt_executable_path de Cosmos
#   /opt/venvs/analysis  requirements/analysis.txt  generador, notebooks (papermill) e informe
#
# Los venvs viven en /opt y no en AIRFLOW_HOME para que los volúmenes de
# docker-compose.override.yml no puedan taparlos.
#
# Python 3.13, igual que el venv local. Runtime 3.3 = Airflow 3.3.
FROM astrocrpublic.azurecr.io/runtime:3.3-9-python-3.13-base

ENV DBT_VENV=/opt/venvs/dbt \
    ANALYSIS_VENV=/opt/venvs/analysis

USER root

# Paquetes de sistema (lo mismo que haría ONBUILD).
COPY packages.txt .
RUN /usr/local/bin/install-system-packages

COPY requirements/ requirements/

# Entorno de Airflow, con las restricciones de la propia imagen.
RUN uv pip install --system --no-cache -r requirements/airflow.txt -c /etc/pip-constraints.txt

# venv de dbt. Las versiones se fijan contra requirements/constraints.txt (el freeze
# del venv local) para que dbt sea el mismo dentro y fuera del contenedor.
RUN uv venv --python /usr/local/bin/python "$DBT_VENV" \
 && UV_SYSTEM_PYTHON=false uv pip install --no-cache --python "$DBT_VENV/bin/python" \
        -r requirements/dbt.txt -c requirements/constraints.txt

# venv de análisis, con un kernel registrado para que papermill lo encuentre por
# nombre en vez de depender del "python3" genérico.
RUN uv venv --python /usr/local/bin/python "$ANALYSIS_VENV" \
 && UV_SYSTEM_PYTHON=false uv pip install --no-cache --python "$ANALYSIS_VENV/bin/python" \
        -r requirements/analysis.txt -c requirements/constraints.txt \
 && "$ANALYSIS_VENV/bin/python" -m ipykernel install --prefix "$ANALYSIS_VENV" \
        --name capsule-analysis --display-name "Python 3 (capsule-analysis)"

USER astro

# El proyecto entero, igual que el último paso de ONBUILD. Lo que el DAG escribe
# (data/, analysis/outputs/, report/dist/, dashboard/data/) no se hornea: lo montan
# los volúmenes de docker-compose.override.yml desde el repo del host.
COPY --chown=astro:0 . .

# Manifest de dbt para Cosmos (LoadMode.DBT_MANIFEST): el DAG se parsea leyendo
# este JSON en vez de lanzar `dbt ls`. `dbt parse` no abre DuckDB (data/ no está
# en la imagen), pero CAPSULE_DUCKDB_PATH tiene que valer lo mismo que en
# docker-compose.override.yml: dbt invalida el partial_parse.msgpack que deja aquí
# si el perfil cambia, y entonces el `dbt build` del DAG vuelve a parsear entero.
RUN cd dbt_project \
 && CAPSULE_DUCKDB_PATH=/usr/local/airflow/data/warehouse.duckdb "$DBT_VENV/bin/dbt" parse --profiles-dir . \
 && rm -rf logs
