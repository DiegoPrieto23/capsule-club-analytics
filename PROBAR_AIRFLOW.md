# Trying the pipeline with Airflow

Steps to start the project's Docker setup, open Airflow, trigger the
`capsule_club_pipeline` DAG and view the HTML report. The commands are for
PowerShell and are run from the repository root.

## 1. Prepare

1. Open **Docker Desktop** and wait until it says *Engine running*.
2. Open PowerShell at the root of the repository.
3. If `astro` is not found and you installed it with winget, create an alias
   for this session:

   ```powershell
   Set-Alias astro "$env:LOCALAPPDATA\Microsoft\WinGet\Packages\Astronomer.Astro_Microsoft.Winget.Source_8wekyb3d8bbwe\astro.exe"
   ```

## 2. Start Airflow

```powershell
astro dev start
```

The first time it builds the image and takes a few minutes; after that it
starts in seconds. It ends by printing `➤ Airflow UI: http://localhost:8080`.

- If it was already running, or code outside `dags/` has changed:
  `astro dev restart`.
- To see which containers are running: `astro dev ps`.

## 3. Open Airflow

Open <http://localhost:8080> in the browser. Locally it normally lets you in
without asking for a user.

## 4. Find the DAG

1. In the left-hand menu, **Dags** → `capsule_club_pipeline`.
2. Check that the DAG toggle is **on**. If it is paused, runs stay queued.
3. Useful tabs:
   - **Graph:** the drawing of the pipeline. The `dbt` and `analysis` groups
     expand with a click.
   - **Grid:** each run in columns and each task in rows, colour-coded
     (green = success, red = failed).

## 5. Trigger it

**First:** close any Jupyter notebook or Python session that has
`data/warehouse.duckdb` open. Otherwise the generator or dbt will fail on
DuckDB's lock.

- **From the UI:** the **Trigger** button (top right) → confirm **Trigger**.
- **From PowerShell:**

  ```powershell
  astro dev run dags trigger capsule_club_pipeline
  ```

It takes about 2 minutes and should end with **all 61 tasks green**.

- To see what a task does: click it in **Grid** → **Logs** tab.
- The full `dbt build` is in the log of `dbt.dbt_producer_watcher`. At the end
  it should read `PASS=245 ... TOTAL=245`.

## 6. View the report

The DAG writes the report into the project folder:

```powershell
start report\dist\index.html
```

It can also be opened with a double click. It works without a server or
internet access. The "Generado el …" date in the header confirms it comes
from this run.

## 7. Shut it down

```powershell
astro dev stop
```

It stops the containers without deleting anything. If something fails on
startup, `astro dev logs` shows the Airflow logs.
