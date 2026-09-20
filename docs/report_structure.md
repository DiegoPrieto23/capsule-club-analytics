# Estructura del informe final (HTML multipágina)

Páginas, en este orden:

1. **Resumen ejecutivo** — KPIs de negocio clave (suscriptores activos, MRR, ingresos totales, tasa de cancelación, CAC medio, LTV medio) y las 2-3 conclusiones más importantes del proyecto en un vistazo.

2. **Serie temporal: Suscriptores activos** — descomposición (tendencia/estacionalidad/residuo) del stock mensual de activos, y forecast a N meses con backtesting walk-forward. Debe mostrar también el enfoque de forecasting basado en curvas de retención por cohorte, no solo un modelo clásico ciego sobre el agregado.

   La **estacionalidad semanal y anual** se analiza sobre el *flujo* de altas diarias, no sobre el stock: un stock de suscriptores no puede oscilar por día de la semana, porque nadie cancela el domingo y se reactiva el lunes. El flujo sale de `dim_customers.first_subscription_date` y se descompone con MSTL para separar las dos estacionalidades a la vez.

   El **efecto de campañas y lanzamientos** se muestra como contexto temporal —presión de marketing por mes y aperturas de boutique superpuestas a las altas— y se etiqueta explícitamente como correlación, no como atribución. El reparto de mérito entre canales es de la página 6.

3. **Serie temporal: Ingresos totales** — mismo tratamiento que la página anterior, para ingresos online + tienda combinados, desglosados también por canal.

4. **Serie temporal: Demanda por sabor de cápsula** — análisis y forecast a nivel SKU. Debe mostrar explícitamente cómo se trató la demanda censurada por rotura de stock y la discontinuidad de SKUs relanzados.

   La serie se mide en **unidades, no en euros**, y se agrega por `canonical_sku`: el relanzamiento de un SKU sube el precio entre un 9% y un 11%, así que en euros hay un escalón real de precio que se confundiría con un cambio de demanda. La discontinuidad hay que arreglarla en unidades y dejarla intacta en euros.

   La **detección de la censura** se enseña como procedimiento, no como resultado: el ranking ingenuo por longitud de la racha de ceros falla, y lo que funciona es contrastar la demanda esperada dentro de la ventana usando el club —que no se censura— como grupo de control. La validación contra el manifiesto del generador va después, explicando que no se usó para detectar.

   El **forecast se publica con reparto middle-out**: los diez sabores de base como un bloque repartido por cuota y los dos de temporada con modelo propio, porque el agregado mezcla dos calendarios incompatibles. Las partes suman el total por construcción. La banda es empírica y **sin centrar**, para que los dos SKUs de temporada —con una sola temporada completa de histórico— salgan con la incertidumbre que de verdad tienen (veinte a uno frente al 1,5 a 1 del total) en vez de con un punto reescalado.

5. **Cohortes & RFM** — curvas de retención por cohorte de alta de suscripción, con el efecto del descuento de bienvenida aislado explícitamente, y segmentación RFM de compradores puntuales (tienda + online).

   La retención se mide sobre `is_active_eom` y **no** sobre los activos netos de pausas: la pausa es un fenómeno de mes natural y entraría en la curva como churn a una edad distinta en cada cohorte. Las suscripciones regaladas se excluyen de la curva principal y se publican aparte, porque su caída es el fin del término del regalo y no una decisión de consumo.

   El efecto del **descuento de bienvenida** se presenta después de comprobar que está repartido al azar: esa comprobación es lo que autoriza a leer la diferencia entre curvas como efecto y no como selección. La conclusión es que es una criba única en los meses 1 y 2, no un deterioro de la retención.

   El **LTV por canal** que se lleva a la página 7 es el **proyectado** (ARPU × suma de la curva del canal), no el observado sobre suscripciones maduras, que ordena los canales al revés porque sólo mide supervivientes. La curva se corta en la última edad con cohortes suficientes detrás y se le impone monotonía antes de sumarla.

   El **RFM** sólo cubre a los clientes identificados: el 27% de los pedidos de tienda no tiene cliente y queda fuera por construcción. Hay que decirlo en la página, no esconderlo en una nota al pie.

6. **Atribución de marketing** — comparación de modelos heurísticos (first/last/linear touch) frente a un modelo de Markov chain, con el attribution gap explicado (qué porcentaje de conversiones no se puede atribuir con confianza a ningún canal).

   El histórico se **corta el 31 de mayo de 2026**, el último mes completo anterior a `cierre − 70 días`. Los recorridos se generan hacia atrás desde el alta, así que el tramo final tiene touchpoints a medias y el CAC aparente del último mes sale un 79% por debajo del de enero. Es la conclusión más golosa que puede dar la página y es falsa.

   El **attribution gap son dos huecos y hay que enseñar los dos**: el 6,2% de altas sin ningún touchpoint (el que se suele citar) y el 39,4% de touchpoints sin cliente, que se lleva el 24,5% del gasto. Juntos hacen que el CAC atribuible infravalore el real un 24%, y no afectan por igual a todos los canales.

   El coste va **ponderado por reclamación** (`weighted_cost_eur`): el código CREMA20 lo reclaman dos creadores y sumar el bruto mete 1.152 € inexistentes en el canal de influencer.

   La página debe decir que **`organic` sale a 0 € porque no tiene coste de medios, no porque sea gratis**, y que **`paid_social` está penalizado** por la ventana de pérdida de trazabilidad de 2025: su CAC real es mejor que el publicado.

7. **CAC × LTV por canal** — página de cierre: cruza el CAC de la página de atribución con el LTV real observado en las cohortes de la página 5, canal a canal. Este cruce es la conclusión de negocio central del proyecto — un canal puede parecer barato por suscriptor captado y ser carísimo en términos reales si su cohorte cancela rápido.

Las tres páginas de serie temporal (2, 3, 4) deben compartir la misma plantilla visual para que el informe se sienta consistente, aunque el contenido analítico de cada una sea distinto.
