# CLAUDE.md — Capsule Club Analytics

## Qué es este proyecto

Side project de portfolio para demostrar competencias de **Analytics Engineering / Data Analytics / BI Engineering**, más allá del perfil de Data Engineering.

Simula el negocio de una marca de cápsulas de café con modelo de suscripción tipo Nespresso: club de suscripción de cápsulas, tienda online + boutiques físicas, y venta puntual de máquinas de cápsulas.

El objetivo **no** es solo construir un pipeline de datos: es demostrar sensibilidad analítica y de negocio a través de cuatro técnicas que se combinan en una sola historia — análisis de series temporales, forecasting, cohortes/RFM y atribución de marketing — que terminan cruzándose en un único insight de cierre: CAC por canal vs LTV real observado por canal.

## Decisiones de alcance ya tomadas

No reabrir estas decisiones sin confirmar antes con Diego:

- Se incluye la venta de máquinas de cápsulas como compra puntual de alto valor, además de la suscripción recurrente.
- Hay tres series temporales protagonistas, cada una con su propia página en el informe final: **suscriptores activos**, **ingresos totales** (online + tienda) y **demanda por sabor de cápsula** (a nivel SKU).
- Stack: Python + pandas + DuckDB + dbt (adaptador `dbt-duckdb`). Nada de Snowflake ni Databricks — todo debe correr en local, sin servicios cloud de pago.
- Los datos son 100% sintéticos y **deliberadamente imperfectos** (ver `docs/data_imperfections.md`). Tratar esas imperfecciones con criterio es una parte central del valor del proyecto, no un problema a esconder — deben mencionarse explícitamente en el informe final, no solo corregirse en silencio.
- Entregable final: informe HTML estático multipágina, interactivo (gráficos Plotly), navegable sin necesidad de levantar un servidor.

## Documentos de referencia

Leer antes de generar cualquier código:

- `docs/data_schema.md` — esquema relacional completo de las tablas a simular
- `docs/data_imperfections.md` — catálogo de las imperfecciones a inyectar, por qué, y qué deben forzar a analizar
- `docs/report_structure.md` — estructura de páginas del informe final y qué debe contener cada una
- `PROMPTS.md` — la secuencia de prompts con la que se va a construir el proyecto, fase a fase

## Estructura de carpetas objetivo

```
capsule-club-analytics/
├── CLAUDE.md
├── README.md
├── PROMPTS.md
├── requirements.txt
├── .gitignore
├── docs/
│   ├── data_schema.md
│   ├── data_imperfections.md
│   └── report_structure.md
├── venv/                          # no versionar
├── data/
│   ├── raw/                       # parquet generado por el script de datos
│   │   └── _imperfections_manifest.json   # ground truth de QA, no se carga en DuckDB
│   └── warehouse.duckdb           # no versionar
├── data_generation/
│   └── generate_synthetic_data.py
├── dbt_project/
│   ├── README.md                  # cómo ejecutarlo y decisiones de los marts
│   ├── dbt_project.yml
│   ├── profiles.yml               # vive aquí: usar --profiles-dir .
│   ├── macros/                    # normalización de canal y de email
│   ├── tests/generic/             # tests propios, para no depender de dbt_utils
│   └── models/
│       ├── staging/
│       ├── intermediate/
│       └── marts/
├── analysis/
│   ├── utils_timeseries.py
│   ├── utils_subscriptions.py     # modelo de cohortes, compartido por 01 y 02
│   ├── 01_time_series_suscriptores.ipynb
│   ├── 02_time_series_ingresos.ipynb
│   ├── 03_time_series_capsulas.ipynb
│   ├── 04_cohorts_rfm.ipynb
│   ├── 05_attribution.ipynb
│   ├── 06_cac_ltv_crossover.ipynb
│   └── outputs/                   # json/parquet intermedios, no versionar
└── report/
    ├── build_report.py
    └── templates/
```

## Convenciones

- Código y nombres de columnas/variables en inglés (snake_case). El copy del informe final y los comentarios narrativos, en español.
- La limpieza y el modelado de negocio viven en **dbt**, no en los notebooks. Los notebooks solo consumen los marts ya limpios para análisis, modelado estadístico y visualización — no deben re-implementar lógica de transformación que ya debería estar en dbt.
- Cada mart de dbt lleva tests (`unique`, `not_null`, `relationships` como mínimo) y está documentado en su `schema.yml`.
- Cada notebook de análisis guarda su resultado final en `analysis/outputs/*.json` para que `report/build_report.py` los consuma sin tener que re-ejecutar notebooks.
- No usar Faker/generación aleatoria sin semilla fija — el dataset debe ser reproducible (`random_state`/`seed` fijado al principio del script de generación).

## Estado actual

El dataset se regeneró el 2026-09-19 tras corregir un bug del generador que
apilaba sobre el último día del histórico los eventos programados para después
(ver `docs/data_imperfections.md`). Cualquier número anterior a esa fecha está
obsoleto; dbt pasa 220/220 tests y el notebook 01 está reejecutado sobre los
datos nuevos.

Ejecutados los prompts 1 a 11 de `PROMPTS.md`, más una ronda de saneamiento de
deuda técnica: entorno, generador de datos sintéticos, pipeline dbt (25 modelos
y 220 tests: `dbt build` deja 245/245 nodos en verde), las seis páginas de
análisis y el informe HTML. El siguiente es el prompt 12, la revisión final.

El informe se genera con `python report/build_report.py` y sale en
`report/dist/` (7 páginas, 23 gráficos, 25 recomendaciones, 1,1 MB de HTML más
Plotly vendorizado). Se abre con `file://` y no hace ni una petición remota.

Dos marts nuevos salidos de esa ronda, que los prompts siguientes deberían
usar: `fct_machine_orders` (grano de pedido; la máquina es el 21,5% del ingreso y
antes no tenía serie temporal) y `dim_subscriptions` (grano de suscripción, con
`start_date` diario, para analizar el flujo de altas y hacer supervivencia sin
reconstruirla desde el estado mensual).

El modelo de cohortes de `analysis/utils_subscriptions.py` se instancia con
`calibrate=True` para descontar su propio sesgo con un backtesting interno al
entrenamiento. Conviene saber que **calibrar cuesta precisión a horizontes
cortos**: a seis meses mejora todo (MASE 0,115 → 0,087), a tres meses baja el
sesgo de 33 a 8 pero sube el MASE de 0,067 a 0,092. Para horizonte corto,
desactivarla.

Regla que las páginas 6 y 7 tienen que respetar: **los touchpoints de los últimos
~70 días del histórico están censurados por construcción**. Cada recorrido de
marketing se genera hacia atrás desde la fecha de alta con una ventana de
consideración de unos 70 días, así que quien se dé de alta después del cierre no
aporta ninguno. Cualquier métrica de volumen o de coste por touchpoint debe
excluir ese tramo o comparar sólo periodos completos.

El notebook 01 deja tres piezas reutilizables para los notebooks 02 y 03:

- el patrón de `forecast_fn(train, horizon)` con backtesting walk-forward comparado
  siempre contra un naive estacional como suelo;
- en series de 36 puntos hay que acotar el `maxlag` del ADF (la regla por defecto
  pide 10 retardos y el contraste llega a mentir);
- la estacionalidad semanal va sobre **flujos**, nunca sobre stocks, y se separa de
  la anual con `mstl_decompose`. `docs/report_structure.md` ya lo recoge así.

Del notebook 02, dos cosas que el 03 necesitó: para detectar una imperfección
en una serie que crece, lo que importa es elegir un denominador que no crezca (el
hueco de pasarela sólo se aísla dividiendo la caja entre el MRR contratado); y los
perfiles estacionales en % sobre tendencia hay que calcularlos sobre el tramo maduro
y con mediana, porque en el año de arranque la tendencia es tan pequeña que el
porcentaje se dispara.

Del notebook 03, cuatro cosas que conviene arrastrar a las páginas siguientes:

- **La demanda de cápsulas se reparte 69% tienda / 31% club**, no al revés. El
  comentario de cabecera de `fct_shipments` decía lo contrario y se ha corregido.
- Las **seis roturas de stock** se detectan contrastando la demanda esperada dentro
  de cada racha de ceros (Poisson + Bonferroni + umbral de materialidad de 20
  líneas), usando el club como grupo de control porque no se censura. 6/6 sin
  falsos positivos y la censura estimada se desvía un +0,7% de la real. El
  manifiesto sólo se abre después, para validar.
- **Una imperfección pequeña en el agregado puede ser grande en el origen del
  forecast**: la censura vale el 1,35% de la facturación de cápsulas en tienda,
  pero tres de las seis ventanas caen en los últimos siete meses y corregirlas sube
  un 15,3% la previsión de Intenso 10. El backtesting no llega a verlo porque esa
  ventana cae fuera de sus pliegues de entrenamiento.
- **`ts.empirical_interval` no vale para series muy estacionales.** Su corrección
  por sesgo relativo pide multiplicar por más de dos la previsión de los dos sabores
  de temporada (amplitudes de 12 a 1 y de 27 a 1): un sesgo relativo medio no
  significa nada cuando se promedian meses cuyo nivel se diferencia en un orden de
  magnitud. En el notebook 03 el punto se publica sin corregir y la banda se mide
  **sin centrar** y en logaritmos (`log_band`). Para las páginas 5 a 7, que
  trabajan sobre agregados, la función original sigue siendo la correcta.

Del notebook 04, lo que las páginas 6 y 7 tienen que heredar:

- **El LTV por canal que hay que cruzar con el CAC es el proyectado**, no el
  observado. `cohorts_rfm.json` publica los dos: el observado sobre
  suscripciones maduras ordena los canales al revés (el podcast pasa del primer
  puesto al cuarto) porque sólo promedia a los supervivientes. El proyectado va
  de 411 € (código de influencer) a 539 € (paid social).
- **Los canales no se separan hasta que pasa un año**: 4 puntos de dispersión de
  retención al mes 3 y 15 al mes 18. Cualquier lectura de calidad de canal a tres
  meses los declara equivalentes.
- **El descuento de bienvenida cuesta 5,1 meses de vida esperada** (16,7 frente a
  21,8) y unos 128 € de LTV por alta. Es el lado del coste que hay que meter en
  el cruce de la página 7, además del propio descuento.
- **`direct_unknown` no es un canal**: es el 29% de las altas y el cajón de las
  conversiones sin touchpoint resuelto. La página 6 tiene que cuantificarlo, no
  repartirlo en silencio.
- **`ts.empirical_interval` no es lo único de `utils_` que hay que mirar con
  lupa**: el `tail_hazard` de `utils_subscriptions.build_retention_curve` se
  estima sobre las últimas edades de la curva, que las escriben 1-4 cohortes, y
  **sale negativo en dos canales** (retención que crecería con la edad). Para el
  forecast a 6 meses de la página 2 da igual; para un LTV a 36 meses no. El
  notebook 04 define un `reliable_curve()` local que corta el tramo observado
  donde deja de haber cohortes suficientes, impone monotonía y reestima el
  hazard. `utils_subscriptions.py` **no** se ha tocado.

Decisión ya tomada sobre los downgrades (era la única pendiente): **se corrigió el
catálogo, no el generador**. El downgrade mueve el plan hacia el ciclo corto, que
es el más caro por mes, así que **sube** el MRR un 6,3%, acorta el compromiso de
6,7 a 1,8 meses y no adelanta la cancelación; `docs/data_imperfections.md` ya lo
describe así. El `tier`, que es el eje con precio real (23,49 € a 36,69 €), no se
mueve nunca en todo el histórico.

Lo que salió de revisar esa decisión y **corrige lo que la página 5 publicaba
antes**: el hueco de 2-4 puntos entre retención de logo y de ingreso **no lo abre
el mix de plan** (−0,06 puntos de media, pese a que el mix sí se desplaza cinco
puntos entre el mes 0 y el 14) **sino la pausa**, que explica el 102% del hueco.
`contracted_mrr_eur` vale 0 durante la pausa y la tarifa se va a
`paused_mrr_eur`: son 55.360 € de MRR aparcado sobre 1.064 suscripciones no
regaladas. La pausa es el único evento del catálogo que retira ingreso sin
retirar cliente, así que es la que responde a la pregunta que el catálogo dejaba
abierta. Método a recordar: un gráfico que enseña que algo *se mueve* no
demuestra que *pese*; hay que descomponer y medir la contribución.

Del notebook 05, lo que la página 7 necesita saber antes de cruzar nada:

- **El CAC por canal ya está calculado y hay dos versiones.** `attribution.json`
  publica el del reparto (coste asignable / conversiones atribuidas: 11,71 € de
  media) y el **cargado** con el gasto huérfano y las altas sin recorrido
  (14,53 €). El cruce con LTV debería usar el **cargado**, que es lo que cuesta
  de verdad captar, y decir que lo hace.
- **El gap no encarece a todos por igual.** Cargarlo sube el CAC de
  `paid_social` un 44% y el de `referral` un 29%: **reordena** el ranking de
  canales, que es justo lo que la página 7 pretende leer.
- **`organic` sale a 0 €** porque no lleva coste de medios en el dataset. En el
  cruce CAC×LTV saldrá con ratio infinito; hay que tratarlo aparte y no dejar
  que la conclusión sea "invertirlo todo en orgánico".
- **`paid_social` está penalizado** por la ventana tipo iOS ATT de enero a junio
  de 2025 (su tasa de resolución cae del 24,0% al 8,5%). Su CAC real es algo
  mejor que el publicado, y eso juega a su favor en el cruce.
- **La elección de modelo de atribución casi no importa aquí**: dispersión
  máxima de 3,6 puntos de crédito y mismo orden de canales en los cuatro. No
  merece la pena montar sensibilidad al modelo en la página 7; sí merece la pena
  montarla al gap.
- **El corte de censura es el 31 de mayo de 2026** y la página 7 tiene que usar
  el mismo si compara CAC con LTV por cohorte.

Del notebook 06 (cierre), lo que el informe tiene que contar bien:

- **La tesis del proyecto se cumple**: el podcast capta más barato (13,52 €) que
  paid social (14,44 €) y aun así vale menos (33,7x contra 37,3x), porque retiene
  diez puntos peor a 12 meses. Ordenar canales por CAC recomienda lo contrario
  que ordenarlos por valor.
- **El 93% de la diferencia de LTV entre canales es duración, no tarifa.** El
  ARPU varía un 4,8% entre canales y los meses de vida un 28%.
- **El podio depende de las dos decisiones metodológicas** de las páginas 5 y 6:
  con LTV observado sobre maduras gana el podcast y con el proyectado gana paid
  social. El ratio de un mismo canal se mueve hasta un 66% según la combinación.
- **Los ratios (12x-37x) son implausibles y hay que decirlo**: el dataset no
  tiene COGS (el LTV es ingreso, no margen) y el marketing es el 1,81% del
  ingreso frente al 10-30% habitual. Con un margen del 30% los ratios vuelven a
  3,5x-11,2x sin cambiar el orden.
- **El payback máximo es de 1,6 meses** frente a un objetivo habitual de 12: la
  conclusión de negocio es que el cuello de botella no es el CAC, es el volumen.

Del informe (`report/`), las decisiones que no hay que deshacer sin querer:

- **La paleta de canales no es estética.** Sale de correr
  `scripts/validate_palette.py` de la skill `dataviz` sobre todas las
  combinaciones: el scatter CAC×LTV es un caso "todos los pares" y sólo **dos**
  combinaciones de cuatro ranuras pasan las seis comprobaciones en los dos
  modos. La combinación obvia (azul, naranja, aqua, amarillo) **falla**: amarillo
  y naranja quedan a ΔE 13,7 en visión normal, por debajo del suelo de 15. El
  mapeo vive en `report/theme.py` y cambiarlo exige volver a validar.
- **El modo oscuro no es un volteo.** Cada figura se construye dos veces en
  Python con los pasos de la paleta de cada fondo y las dos especificaciones
  viajan en el HTML; el botón sólo elige cuál se pinta.
- **Cada gráfico lleva su tabla** en un `<details>`, para que el color nunca sea
  la única vía de leer un valor.
- **Ninguna cifra de la prosa del informe está escrita a mano**: todas se
  formatean desde los JSON, así que el informe no puede desincronizarse de los
  notebooks.
- Tres cosas que se arreglaron *después* de mirar el render, y que conviene
  volver a mirar si se toca algo: `select_autoescape` sólo mira la extensión, y
  con plantillas `.j2` el escapado queda apagado y la primera comilla simple de
  una especificación de Plotly parte el atributo; el mapa de calor estacional es
  una razón y va en **log2**, porque en lineal con el centro en 1 los sabores de
  base salen teñidos; y la serie de resolución por canal se corta en el corte de
  censura, porque si no se dispara justo en el tramo que la página denuncia.

Lo que salió de la ronda de revisión del informe contra el render (prompt 11,
segunda pasada). Cinco reglas que conviene no deshacer:

- **Todo el texto del informe pasa por `rich()`**, que entiende `**negrita**` y
  `[[término]]`. Escribir `**` en un campo que Jinja escapa publica los
  asteriscos: `_enrich()` en `content.py` se encarga de recomendaciones,
  conclusiones, viñetas y avisos para que no haya que acordarse.
- **Las conclusiones vienen de los notebooks y hablan como el almacén.**
  `_relabel()` traduce claves de canal (`paid_social`) y nombres de columna
  (`is_active_eom`) a prosa antes de publicarlas. Se traduce la etiqueta, nunca
  la cifra: reescribir la frase a mano volvería a meter números escritos por
  una persona.
- **Plotly formatea sus ejes y sus hovers por su cuenta** y lo hace en inglés.
  `theme.layout` fija `separators` a coma decimal; lo que se formatea desde
  Python pasa por `_es()` en `figures.py`. Si un número sale con punto, se ha
  escapado uno de los dos caminos.
- **Los 22 gráficos llevan tabla.** Era el punto que fallaba: catorce no la
  tenían. Las construye el bloque `TBL` de `content.py` desde los mismos JSON
  que alimentan la figura, así que no pueden discrepar.
- **Ninguna fila de la rejilla se queda coja.** Un gráfico `half` suelto deja
  media pantalla en blanco; o se empareja o se pone `width="full"`. Fue lo que
  llevó a partir el gráfico de logo vs ingreso en dos: las curvas por un lado y
  la descomposición del hueco (`gap_decomposition`) por otro, que además es la
  que demuestra el 102% de la pausa en vez de sólo insinuarlo.

Y una corrección de dato: la intensidad de marketing es el **1,81%**, no el
1,84%. El notebook 06 la tenía escrita a mano en una conclusión; ahora se
interpola y el notebook está reejecutado.

Dos cosas que conviene saber antes de tocar nada:

- El dataset es imperfecto **sólo** en lo que cataloga `docs/data_imperfections.md`.
  El resto de invariantes (integridad referencial, orden temporal, vida de
  catálogo) están garantizadas y verificadas en cada generación. Si aparece otra
  anomalía, es un bug, no una trampa.
- Los notebooks consumen **marts**, no tablas `raw_*` ni modelos intermedios.
  `dbt_project/README.md` recoge las decisiones que hay que conocer antes de
  usarlos (tres definiciones de activo, tres medidas de ingreso, clientes nulos).

## Cómo trabajar en este repo

Sigue `PROMPTS.md` en orden. Cada prompt asume que los anteriores ya se han ejecutado y sus outputs existen. Si algo de `docs/` queda ambiguo al implementarlo, pregunta a Diego antes de asumir — este proyecto es para portfolio, y las decisiones de diseño importan tanto como el código.
