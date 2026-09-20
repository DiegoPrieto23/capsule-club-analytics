# Capsule Club Analytics

### 👉 **[Ver el informe interactivo en vivo](https://diegoprieto23.github.io/capsule-club-analytics/)**

[![El informe](img/portada.png)](https://diegoprieto23.github.io/capsule-club-analytics/)

---

## De qué va esto

Capsule Club es una marca de café en cápsulas que no existe. Vende de cuatro
formas a la vez: un club por suscripción que manda cápsulas cada mes, una tienda
online, unas cuantas boutiques físicas y máquinas de café como compra puntual.

El negocio está simulado entero —tres años de historia, 280.000 filas— para
poder hacer con él lo que se hace con los datos de un negocio real: entender qué
está pasando, predecir qué va a pasar y decir qué habría que cambiar.

El resultado es **un informe de siete páginas** que empieza por un resumen
ejecutivo y termina en un plan de acción. Cada página cuenta un hallazgo, lo
demuestra con un gráfico y acaba en recomendaciones concretas: qué hacer, por
qué, cuánto vale y con qué métrica se sabrá si funcionó.

## Qué pretende demostrar

La parte que no es montar el *pipeline*: mirar los datos, encontrar lo que
importa, comprobar que es verdad y contarlo de forma que alguien pueda decidir
con ello.

Un informe bonito lo hace cualquiera. La diferencia está en tres cosas:

- **Los datos están rotos a propósito.** Hay roturas de stock que parecen falta
  de demanda, una semana de cobros perdida por una migración, suscripciones
  regaladas mezcladas con las de verdad, un canal de marketing que dejó de ser
  medible durante medio año y clientes duplicados por escribir el mismo email de
  dos maneras. Nada de eso viene avisado. Detectarlo, medirlo y contarlo en el
  informe —en vez de taparlo— es la mitad del trabajo.
- **Cada conclusión se comprueba.** Las predicciones se ponen a prueba contra el
  pasado antes de publicarlas, y se dice cuánto se equivocan. Los rankings se
  recalculan cambiando los criterios para ver si aguantan.
- **Todo termina en una decisión.** 25 recomendaciones repartidas por las siete
  páginas, cada una con el número que la justifica.

## Qué hay dentro del informe

| Página | Qué responde |
|---|---|
| **Resumen ejecutivo** | Las cinco cosas que más dinero mueven, ordenadas por lo que devuelven frente a lo que cuestan |
| **Suscriptores activos** | Cuántos hay, cuántos habrá dentro de seis meses y con cuánto margen de error |
| **Ingresos totales** | De dónde sale el dinero, cómo cambia el reparto entre canales y dónde se escondía una semana de cobros perdida |
| **Demanda por sabor** | Cuántas cápsulas de cada sabor comprar, con las roturas de stock descontadas |
| **Cohortes y RFM** | Cuánto dura un cliente, qué le hace irse y qué grupos de compradores merecen un trato distinto |
| **Atribución** | A qué canal hay que darle el mérito de cada alta, y cuánto marketing no se puede atribuir a nadie |
| **CAC × LTV** | Lo que cuesta captar un cliente contra lo que acaba dejando, canal por canal |

Algunos de los hallazgos:

- **El canal más barato no es el mejor.** El podcast capta suscriptores por
  13,52 € y *paid social* por 14,44 €, pero el segundo retiene diez puntos mejor
  al año y acaba valiendo más. Un cuadro de mando ordenado por coste recomienda
  justo lo contrario de lo que conviene.
- **El 39,4% del marketing no se puede atribuir a nadie.** No es gasto perdido:
  es gasto que no se puede optimizar porque no se sabe a quién fue. Repartir
  sólo lo atribuible abarata el coste real un 24%.
- **Seis roturas de stock** dejaron sin vender 17.119 € de cápsulas, y tres de
  ellas cayeron en los últimos siete meses. Si no se corrigen, la previsión
  aprende de un cero que no era falta de interés y pide menos stock del necesario.
- **El descuento de bienvenida cuesta 5,1 meses de vida del cliente.** No
  fideliza: criba. Separa a quien iba a quedarse de quien venía por el descuento.
- **274 cancelaciones fueron por un cobro fallido**, no por decisión del cliente.
  Nadie intentó recuperarlas.

## Los datos

280.841 filas repartidas en doce tablas, desde septiembre de 2023 hasta agosto
de 2026. Las genera un script con semilla fija, así que dos ejecuciones producen
exactamente lo mismo.

| Tabla | Filas | Qué es |
|---|---:|---|
| `customers` | 12.305 | Clientes, sean suscriptores, compradores o ambos |
| `subscriptions` | 5.110 | Suscripciones al club, con su plan y su estado |
| `subscription_events` | 12.385 | Altas, pausas, cambios de plan, fallos de cobro y bajas |
| `shipments` | 45.508 | Envíos del club, con el sabor de cada cápsula |
| `shop_orders` / `shop_order_lines` | 39.888 / 82.925 | Pedidos de tienda online y boutique |
| `machine_orders` | 3.417 | Ventas de máquinas |
| `payments` | 32.726 | Cobros de las suscripciones |
| `marketing_touchpoints` | 46.541 | Cada contacto de marketing antes de un alta |
| `products` · `machines` · `stores` | 23 · 5 · 8 | Catálogo y tiendas |

### El modelo

Los datos entran en bruto y salen en siete tablas listas para analizar. En medio
hay una capa que limpia (`staging`) y otra que resuelve la lógica de negocio
difícil (`intermediate`): unificar clientes duplicados, reconstruir el recorrido
de marketing de cada alta, calcular el estado de cada suscripción mes a mes.

Así entran, tal y como los deja el generador:

```mermaid
erDiagram
    customers {
        string customer_id PK
        date   signup_date
        string acquisition_channel
        string home_store_id FK "nullable"
        string email_raw
    }
    subscriptions {
        string subscription_id PK
        string customer_id FK
        string plan "monthly / quarterly / annual"
        string tier "classic / intense / decaf / explorer"
        date   start_date
        string status "active / paused / cancelled"
        string cancel_reason "nullable"
        bool   had_welcome_discount
        bool   gifted
    }
    subscription_events {
        string event_id PK
        string subscription_id FK
        string event_type "alta, pausa, cambio de plan, fallo de cobro, baja"
        date   event_date
    }
    shipments {
        string shipment_id PK
        string subscription_id FK
        string capsule_sku FK
        date   ship_date
        int    quantity
        bool   on_time
    }
    payments {
        string payment_id PK
        string subscription_id FK
        date   payment_date
        float  amount
        string status "success / failed / retried_success"
    }
    shop_orders {
        string order_id PK
        string customer_id FK "nullable"
        date   order_date
        string channel "online / store"
        string store_id FK "nullable"
    }
    shop_order_lines {
        string order_id PK "FK a shop_orders"
        string product_sku PK "FK a products"
        int    quantity
        float  unit_price
    }
    machine_orders {
        string order_id PK
        string customer_id FK "nullable"
        string machine_model_id FK
        string store_id FK "nullable"
        date   order_date
        bool   bundled_capsules_trial
    }
    products {
        string product_sku PK
        string product_type "capsule / merch"
        string flavor
        date   launch_date
        date   discontinue_date "nullable"
        string replaced_by_sku "nullable"
    }
    machines {
        string machine_model_id PK
        string name
        float  price
    }
    stores {
        string store_id PK
        string city
        date   opening_date
    }
    marketing_touchpoints {
        string touchpoint_id PK
        string customer_id FK "nullable"
        string channel "paid_social / podcast / influencer / referral / organic"
        string campaign_id
        float  cost
        datetime timestamp
        bool   resolved_to_conversion
    }

    customers            ||--o{ subscriptions         : "se suscribe"
    customers            |o--o{ shop_orders           : "compra en tienda"
    customers            |o--o{ machine_orders        : "compra máquina"
    customers            |o--o{ marketing_touchpoints : "recibe impactos"
    customers            }o--o| stores                : "tienda de alta"
    subscriptions        ||--o{ subscription_events   : "registra"
    subscriptions        ||--o{ shipments             : "genera envíos"
    subscriptions        ||--o{ payments              : "se cobra en"
    shipments            }o--|| products              : "envía el SKU"
    shop_orders          ||--|{ shop_order_lines      : "se desglosa en"
    shop_order_lines     }o--|| products              : "referencia"
    shop_orders          }o--o| stores                : "se hace en"
    machine_orders       }o--|| machines              : "modelo"
    machine_orders       }o--o| stores                : "se hace en"
```

Los extremos opcionales del diagrama son deliberados y son los que dan trabajo:
un pedido puede no tener cliente (compra en boutique sin fidelización, el 27,4%
de los pedidos de tienda), un impacto de marketing puede no resolverse a nadie
—el 39,4%— y un cliente puede no tener tienda de alta porque entró por internet.
Cada uno de esos huecos obliga a decidir algo antes de poder medir.

Las siete tablas finales que consumen los análisis:

| Tabla | Grano | Para qué |
|---|---|---|
| `dim_customers` | Cliente | Quién es, por dónde entró, cuánto ha gastado |
| `dim_subscriptions` | Suscripción | Cuándo empezó, qué plan, si sigue viva |
| `fct_subscriptions_monthly` | Suscripción × mes | La foto mensual: activo, en pausa o de baja, y cuánta cuota |
| `fct_shipments` | Envío × sabor | Qué cápsulas salieron y cuándo |
| `fct_shop_orders` | Pedido | Compras de tienda online y boutique |
| `fct_machine_orders` | Pedido | Ventas de máquinas |
| `fct_marketing_attribution` | Alta | El recorrido de contactos que llevó a cada suscripción |

Cada tabla tiene sus comprobaciones automáticas: que no haya duplicados, que no
falten campos obligatorios, que ninguna referencia apunte al vacío, que los
importes cuadren. **220 comprobaciones en total**, y todas pasan en cada
ejecución. Es lo que permite fiarse de que una anomalía en los datos es una
anomalía de verdad y no un error del proceso.

## Qué se ha medido

**Series temporales.** Tres series —suscriptores, ingresos y cápsulas por
sabor— separadas en tendencia, estacionalidad y ruido. Resulta que el negocio
tiene dos calendarios distintos: uno anual (agosto flojo, marzo fuerte) y otro
semanal que sólo aparece en las altas, no en el número de clientes. Y que los
dos sabores de temporada, que son el 9% del volumen, son los que deciden el
calendario de compras del año.

**Predicción.** Previsión a seis meses de las tres series, cada una con su banda
de incertidumbre. Ninguna se publica sin haberla puesto antes a prueba contra el
pasado: se tapa el último tramo del histórico, se predice a ciegas y se compara
con lo que de verdad pasó. La de suscriptores se equivoca un 3,2% de media,
trece veces menos que limitarse a repetir el año anterior. La demanda de
cápsulas se predice sabor a sabor y se agrega, agrupando los sabores por cómo se
comportan y no por cómo están en el catálogo.

**Cohortes y retención.** Se sigue a cada grupo de altas mes a mes para ver
cuántos siguen y cuándo se van. Dos cosas que sólo se ven así: que los canales
de captación parecen idénticos a los tres meses y no se separan hasta pasado el
año, y que el hueco entre "clientes que siguen" y "dinero que sigue entrando" no
lo abre el cambio de plan —que no pesa nada— sino las pausas.

**Segmentación RFM.** Los compradores de tienda agrupados por cuándo compraron
por última vez, cuántas veces y cuánto se gastaron. Los campeones son uno de
cada seis clientes y casi un tercio del ingreso, y la mayoría no tiene
suscripción.

**Atribución de marketing.** Cuatro formas de repartir el mérito entre canales:
darle todo al primer contacto, todo al último, a partes iguales, y un modelo de
Markov que mide cuánto caería la conversión si un canal desapareciera. La
conclusión útil no es cuál gana, sino que los cuatro dan casi lo mismo mientras
que el 39,4% del gasto no se puede asignar a nadie: elegir bien el modelo
importa mucho menos que arreglar la medición.

**Coste contra valor.** El cierre: lo que cuesta captar un cliente por cada
canal frente a lo que ese cliente acaba dejando. Con dos avisos incómodos —los
ratios salen demasiado buenos porque faltan costes en la cuenta, y el podio
cambia según qué criterio se use— porque publicar un número sin sus límites es
peor que no publicarlo.

## Cómo está hecho

Python, DuckDB y dbt para los datos; pandas y statsmodels para el análisis;
Plotly para los gráficos. Todo corre en un portátil, sin servicios de pago.

El informe es HTML estático: se abre con doble clic, no necesita servidor y no
hace ni una petición a internet. Tiene modo claro y oscuro, cada gráfico lleva
su tabla de datos debajo para que el color nunca sea la única forma de leer un
valor, y los colores están elegidos con un validador que comprueba que se
distinguen también con daltonismo.

Ninguna cifra del texto está escrita a mano: todas se leen de los resultados de
los análisis, así que el informe no puede quedarse desfasado respecto a los
datos.

### Ejecutarlo en local

Necesita Python 3.13.

```bash
python -m venv venv
venv\Scripts\pip install -r requirements.txt

# 1. Generar el dataset (~2 min)
venv\Scripts\python data_generation\generate_synthetic_data.py

# 2. Construir las tablas y pasar las comprobaciones
cd dbt_project
..\venv\Scripts\dbt build --profiles-dir .

# 3. Reconstruir el informe (los análisis ya dejan sus resultados guardados)
cd ..
venv\Scripts\python report\build_report.py
```

El informe queda en `report/dist/index.html`.

### Dónde está cada cosa

```
data_generation/   el script que inventa el negocio
dbt_project/       las transformaciones y sus comprobaciones
analysis/          seis cuadernos, uno por análisis
report/            el generador del informe HTML
docs/              esquema de datos, catálogo de imperfecciones y estructura del informe
```
