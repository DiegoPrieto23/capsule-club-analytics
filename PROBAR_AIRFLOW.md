# Probar el pipeline con Airflow

Pasos para levantar el Docker del proyecto, abrir Airflow, lanzar el DAG
`capsule_club_pipeline` y ver el informe HTML. Los comandos son de PowerShell y
se ejecutan desde la carpeta del proyecto.

## 1. Preparar

1. Abrir **Docker Desktop** y esperar a que diga *Engine running*.
2. Abrir PowerShell en el proyecto:

   ```powershell
   cd "C:\Users\Diego Prieto\Documents\Claude Code\capsule-club-analytics\capsule-club-analytics"
   ```

3. Si `astro` no se encuentra, crear un alias para esta sesión:

   ```powershell
   Set-Alias astro "$env:LOCALAPPDATA\Microsoft\WinGet\Packages\Astronomer.Astro_Microsoft.Winget.Source_8wekyb3d8bbwe\astro.exe"
   ```

## 2. Levantar Airflow

```powershell
astro dev start
```

La primera vez construye la imagen y tarda unos minutos; después arranca en
segundos. Termina mostrando `➤ Airflow UI: http://localhost:8080`.

- Si ya estaba arrancado, o se ha cambiado código fuera de `dags/`:
  `astro dev restart`.
- Para ver qué contenedores están en marcha: `astro dev ps`.

## 3. Abrir Airflow

Abrir <http://localhost:8080> en el navegador. En local normalmente entra sin
pedir usuario.

## 4. Ver el DAG

1. En el menú de la izquierda, **Dags** → `capsule_club_pipeline`.
2. Comprobar que el interruptor del DAG está **activado**. Si está en pausa, las
   ejecuciones se quedan en cola.
3. Pestañas útiles:
   - **Graph:** el dibujo del pipeline. Los grupos `dbt` y `analysis` se
     despliegan con un clic.
   - **Grid:** cada ejecución en columnas y cada tarea en filas, con colores
     (verde = bien, rojo = falló).

## 5. Lanzarlo

**Antes:** cerrar cualquier cuaderno de Jupyter o sesión de Python que tenga
abierto `data/warehouse.duckdb`. Si no, el generador o dbt fallan por el
bloqueo de DuckDB.

- **Desde la interfaz:** botón **Trigger** (arriba a la derecha) → confirmar
  **Trigger**.
- **Desde PowerShell:**

  ```powershell
  astro dev run dags trigger capsule_club_pipeline
  ```

Tarda unos 2 minutos y deberían quedar las **61 tareas en verde**.

- Para ver qué hace una tarea: clic en ella dentro de **Grid** → pestaña
  **Logs**.
- El `dbt build` completo está en el log de `dbt.dbt_producer_watcher`. Al
  final debe decir `PASS=245 ... TOTAL=245`.

## 6. Ver el informe

El DAG escribe el informe en la carpeta del proyecto:

```powershell
start report\dist\index.html
```

También se puede abrir con doble clic. Funciona sin servidor ni internet. La
fecha "Generado el …" de la cabecera confirma que es el de esta ejecución.

## 7. Apagarlo

```powershell
astro dev stop
```

Para los contenedores sin borrar nada. Si algo falla al arrancar,
`astro dev logs` muestra los logs de Airflow.
