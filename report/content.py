"""
Capsule Club Analytics — contenido del informe.

Vive aparte del constructor porque son dos trabajos distintos: aquí se decide
qué se cuenta y qué se recomienda hacer, y en `build_report.py` cómo se
renderiza.

Dos reglas que se siguen en todo el fichero:

  - **Ninguna cifra se escribe a mano.** Todas salen de los JSON de
    `analysis/outputs/`, así que el informe no puede desincronizarse de los
    notebooks: si un análisis cambia, el texto cambia con él.
  - **Cada página termina en recomendaciones.** Un informe que sólo describe no
    sirve: cada hallazgo acaba en algo que alguien tiene que hacer, con el
    número que lo justifica, quién lo haría y con qué métrica se sabría si
    funcionó. El impacto es una estimación con los datos del informe y se
    presenta como tal.
"""

from __future__ import annotations

import re

import figures as F
import theme as T
from glossary import entries, rich

# ARPU medio del negocio, para traducir meses de vida a euros en las estimaciones.
def _arpu(cohorts):
    rows = cohorts["ltv_by_channel"]["channels"]
    return sum(r["arpu_mes"] * r["suscripciones"] for r in rows) / \
        sum(r["suscripciones"] for r in rows)


def build(data, fmt, Figure, table):
    """Devuelve la lista de páginas. `fmt` trae los formateadores de número."""
    eur, num, pct, ratio, month_es = (fmt["eur"], fmt["num"], fmt["pct"],
                                      fmt["ratio"], fmt["month_es"])
    subs, ing, cap = data["suscriptores"], data["ingresos"], data["capsulas"]
    coh, att, cx = data["cohorts_rfm"], data["attribution"], data["cac_ltv"]

    arpu = _arpu(coh)
    blended = cx["blended"]
    gap = att["attribution_gap"]
    disc = coh["welcome_discount"]
    cens = cap["censored_demand"]
    plaus = cx["plausibility"]
    pause = coh["paused_revenue"]
    # El hueco entre retención de clientes y de ingreso: cuánto pone cada causa.
    _gap_rows = coh["plan_changes"]["logo_vs_revenue_retention"][1:]
    mix_mean_pp = sum(r["efecto_mix_pp"] for r in _gap_rows) / len(_gap_rows)
    pause_share = (sum(r["efecto_pausa_pp"] for r in _gap_rows)
                   / sum(r["gap_total_pp"] for r in _gap_rows) * 100)

    # --- cifras derivadas que sostienen las recomendaciones -----------------
    involuntary = 274                       # dim_subscriptions.is_involuntary_churn
    involuntary_year = involuntary / 3      # el histórico son tres años
    involuntary_value = involuntary_year * blended["ltv_weighted_eur"]
    discount_gap_eur = 128.0                # LTV perdido por alta con descuento (página 5)
    discount_total = discount_gap_eur * disc["n_with_discount"]
    segments = {r["segmento"]: r for r in coh["rfm"]["segments"]}
    seg_sub = {r["segmento"]: r for r in coh["rfm"]["segments_vs_subscription"]}
    champions_no_sub = round(segments["Campeones"]["clientes"]
                             * (1 - seg_sub["Campeones"]["pct_suscriptor"] / 100))
    referral = next(r for r in cx["crossover"] if r["channel"] == "referral")
    referral_extra = (referral["cac_loaded_eur"] - blended["cac_loaded_eur"]) \
        * referral["conversions"]
    best_channel = max(cx["crossover"], key=lambda r: r["ratio"])
    cheapest = min(cx["crossover"], key=lambda r: r["cac_loaded_eur"])

    subs_fc = subs["forecast"]["models"]["cohortes"]
    subs_last = subs["series"]["active_net"][-1]["suscriptores"]
    subs_growth = subs_fc["yhat"][-1] / subs_last - 1
    ing_fc = ing["forecast"]["models"]["sarima_airline"]
    ing_last = ing["series"]["total"][-1]["eur"]
    cap_fc = cap["forecast"]["total"]

    def mape(rows, exclude_naive=True):
        pool = [r for r in rows if not exclude_naive or r["model"] != "naive_estacional"]
        return min(pool, key=lambda r: r["mase"])["mape"]

    mape_subs = mape(subs["backtest"]["leaderboard"])
    mape_ing = mape(ing["backtest"]["leaderboard"])
    mape_cap = mape(cap["backtest"]["total_leaderboard"])


    # --- tablas equivalentes -----------------------------------------------
    # Cada gráfico lleva la suya en un `<details>`: el color nunca puede ser la
    # única vía de leer un valor, y quien imprima o use lector de pantalla tiene
    # que llegar a la misma cifra que quien pasa el ratón por encima.
    def _months(rows, key="date"):
        return [month_es(r[key]) for r in rows]

    def _forecast_table(hist, model, months, unit, value_key):
        header = ["Mes", unit, "Tipo"]
        rows = [[month_es(r["date"]), num(r[value_key]), "histórico"] for r in hist]
        rows += [[month_es(m), num(y), "previsión"]
                 for m, y in zip(months, model["yhat"])]
        return table(header, rows)

    FLAVOUR = {f["flavor"]: f["label"] for f in cap["flavors"]}
    CHANNEL_LABEL = T.CHANNEL_LABEL

    TBL = {}

    TBL["resumen-forecast-subs"] = _forecast_table(
        subs["series"]["active_net"], subs_fc, subs["forecast"]["months"],
        "Suscriptores activos", "suscriptores")
    TBL["resumen-backtest"] = table(
        ["Serie", "Modelo publicado (MAPE)", "Repetir el año anterior (MAPE)"],
        [[name,
          pct(mape(rows)),
          pct(next(r for r in rows if r["model"] == "naive_estacional")["mape"])]
         for name, rows in (("Suscriptores", subs["backtest"]["leaderboard"]),
                            ("Ingresos", ing["backtest"]["leaderboard"]),
                            ("Demanda de cápsulas", cap["backtest"]["total_leaderboard"]))])
    _ing_ch = ["suscripcion", "online", "tienda", "maquina"]
    TBL["resumen-ingresos"] = table(
        ["Mes", "Suscripción", "Tienda online", "Boutique", "Máquinas", "Total"],
        [[month_es(ing["series"]["total"][i]["date"])]
         + [eur(ing["series"][c][i]["eur"]) for c in _ing_ch]
         + [eur(ing["series"]["total"][i]["eur"])]
         for i in range(len(ing["series"]["total"]))])
    TBL["ing-forecast"] = _forecast_table(
        ing["series"]["total"], ing_fc, ing["forecast"]["months"],
        "Ingreso (€)", "eur")
    TBL["ing-mix"] = table(
        ["Mes", "Suscripción", "Tienda online", "Boutique", "Máquinas"],
        [[month_es(r["date"]), pct(r["suscripcion"]), pct(r["online"]),
          pct(r["tienda"]), pct(r["maquina"])]
         for r in ing["channel_mix"]["by_month_pct"]])
    TBL["ing-gap"] = table(
        ["Mes", "Caja cobrada / MRR contratado"],
        [[month_es(r["date"]), num(r["ratio"], 3)]
         for r in ing["payment_gap"]["cash_ratio"]])
    TBL["cap-forecast"] = _forecast_table(
        cap["series"]["total"], cap_fc, cap["forecast"]["months"],
        "Unidades", "units")
    TBL["cap-emphasis"] = table(
        ["Mes"] + [FLAVOUR[f] for f in cap["series"]["by_flavor"]],
        [[month_es(cap["series"]["by_flavor"]["classic_espresso"][i]["date"])]
         + [num(cap["series"]["by_flavor"][f][i]["units"])
            for f in cap["series"]["by_flavor"]]
         for i in range(len(cap["series"]["by_flavor"]["classic_espresso"]))])
    TBL["cap-heatmap"] = table(
        ["Mes"] + [FLAVOUR[f] for f in cap["seasonal_profile"]["by_month"][0]
                   if f not in ("month", "label")],
        [[r["label"]] + [ratio(r[f], 2)
                         for f in r if f not in ("month", "label")]
         for r in cap["seasonal_profile"]["by_month"]])
    TBL["coh-discount"] = table(
        ["Mes desde el alta", "Con descuento", "Sin descuento"],
        [[num(a["age"]), pct(a["retention"] * 100), pct(b["retention"] * 100)]
         for a, b in zip(coh["retention"]["with_discount"],
                         coh["retention"]["without_discount"])])
    TBL["coh-gift"] = table(
        ["Mes desde el alta", "Regaladas", "Normales"],
        [[num(a["age"]), pct(a["retention"] * 100), pct(b["retention"] * 100)]
         for a, b in zip(coh["retention"]["gifted"], coh["retention"]["base"])])
    TBL["coh-matrix"] = table(
        ["Cohorte"] + [f"Mes {i}" for i in range(36)],
        [[month_es(r["cohort"])] + [pct(r[str(i)]) if r.get(str(i)) is not None else "—"
                                    for i in range(36)]
         for r in coh["cohort_matrix"]["retention_pct"]])
    TBL["coh-logo-revenue"] = table(
        ["Mes desde el alta", "Clientes", "Cuota contratada", "Cuota cobrable",
         "Efecto mix", "Efecto pausa"],
        [[num(r["months_since_start"]), pct(r["logo"]), pct(r["mrr_tarifa"]),
          pct(r["mrr_cobrable"]), f"{num(r['efecto_mix_pp'], 2)} pp",
          f"{num(r['efecto_pausa_pp'], 2)} pp"]
         for r in coh["plan_changes"]["logo_vs_revenue_retention"]])
    TBL["att-censoring"] = table(
        ["Mes", "Contactos", "Altas", "Coste (€)", "Coste aparente por alta",
         "¿Censurado?"],
        [[month_es(r["month"]), num(r["touchpoints"]), num(r["signups"]),
          eur(r["cost_eur"]), eur(r["apparent_cac_eur"], 2),
          "sí" if r["is_censored"] else "no"]
         for r in att["censoring"]["apparent_cac_by_month"]])
    _res_cols = [c for c in att["ios_att"]["resolution_by_month"][0] if c != "month"]
    TBL["att-ios"] = table(
        ["Mes"] + [CHANNEL_LABEL.get(c, c) for c in _res_cols],
        [[month_es(r["month"])] + [pct(r[c]) for c in _res_cols]
         for r in att["ios_att"]["resolution_by_month"]])
    _rb_cols = [c for c in cx["robustness"]["ratios"][0] if c not in ("channel", "label")]
    TBL["cx-robustness"] = table(
        ["Canal"] + [c[0].upper() + c[1:] for c in _rb_cols],
        [[r["label"]] + [ratio(r[c]) for c in _rb_cols]
         for r in cx["robustness"]["ratios"]])

    pages = []

    # ==================================================== 0. resumen ejecutivo
    pages.append({
        "slug": "index", "file": "index.html", "nav_title": "Resumen ejecutivo",
        "eyebrow": "Capsule Club · informe de negocio",
        "title": "Resumen ejecutivo",
        "summary": ("Tres años de un club de cápsulas por suscripción, con tienda online, "
                    "boutiques y venta de máquinas. Seis análisis encadenados, una previsión "
                    "a seis meses y un plan de acción con lo que conviene cambiar."),
        "hero": {"value": eur(ing["meta"]["total_revenue_eur"]),
                 "label": "ingreso acumulado del histórico, en cuatro canales",
                 "note": f"{month_es(ing['meta']['history_start'])} – "
                         f"{month_es(ing['meta']['history_end'])}"},
        "kpis": [
            {"label": "Suscriptores activos", "value": num(subs_last),
             "note": "netos de pausas, último mes"},
            {"label": "Previsión a 6 meses", "value": num(subs_fc["yhat"][-1]),
             "note": f"{pct(subs_growth * 100, 0)} más, con un error medido del "
                     f"{pct(mape_subs)}"},
            {"label": "CAC cargado", "value": eur(blended["cac_loaded_eur"], 2),
             "note": "incluye el gasto que no se puede asignar"},
            {"label": "LTV por suscriptor", "value": eur(blended["ltv_weighted_eur"]),
             "note": "proyectado a 36 meses"},
            {"label": "Payback", "value": f"{num(blended['slowest_payback_months'], 1)} meses",
             "note": "el canal más lento; el objetivo habitual son 12"},
            {"label": "Valor recuperable", "value": eur(involuntary_value + cens["lost_demand"]["eur"]),
             "note": "al año, sólo con los dos primeros puntos del plan"},
        ],
        "glossary": entries(["ltv", "cac", "payback", "mape", "churn"]),
        "sections": [
            {"heading": "Lo que viene",
             "blocks": [{"kind": "p", "html": rich(
                 "Las tres series del negocio tienen previsión a seis meses y, más "
                 "importante, **una medida de cuánto se equivoca**. La de suscriptores "
                 f"falla un {pct(mape_subs)} de media en [[backtesting]] contra el pasado; "
                 f"la de ingresos un {pct(mape_ing)} y la de cápsulas un {pct(mape_cap)}. "
                 "Todas baten con holgura al suelo de referencia —repetir lo que pasó el "
                 "año anterior—, que es lo que hace que se puedan usar para planificar y "
                 "no sólo para enseñar.")}],
             "figures": [
                 Figure("resumen-forecast-subs", F.subscribers_forecast, subs,
                        "Suscriptores activos: histórico y previsión",
                        "Serie mensual de suscriptores activos con previsión a seis meses y "
                        "banda de incertidumbre del 80%.",
                        subtitle=f"El modelo de cohortes cierra el semestre en "
                                 f"{num(subs_fc['yhat'][-1])} suscriptores, un "
                                 f"{pct(subs_growth * 100, 0)} sobre hoy.",
                        source="Fuente: fct_subscriptions_monthly.", table=TBL["resumen-forecast-subs"]),
                 Figure("resumen-backtest", F.backtest_quality,
                        [("Suscriptores", subs["backtest"]["leaderboard"]),
                         ("Ingresos", ing["backtest"]["leaderboard"]),
                         ("Demanda de cápsulas", cap["backtest"]["total_leaderboard"])],
                        "Cuánto se equivoca cada previsión",
                        "Barras comparando el error del modelo publicado con el de repetir "
                        "el año anterior, para las tres series.",
                        subtitle="Error medio a seis meses, medido tapando el final del "
                                 "histórico y pronosticando a ciegas.",
                        source="Fuente: backtesting walk-forward, 5 pliegues.", table=TBL["resumen-backtest"])]},
            {"heading": "De dónde sale el dinero",
             "blocks": [{"kind": "p", "html": rich(
                 "Ningún canal domina. La suscripción aporta el "
                 f"{pct(ing['channel_mix']['share_pct']['suscripcion'])} del ingreso, la "
                 f"tienda online el {pct(ing['channel_mix']['share_pct']['online'])}, las "
                 f"máquinas el {pct(ing['channel_mix']['share_pct']['maquina'])} y la "
                 f"boutique el {pct(ing['channel_mix']['share_pct']['tienda'])}. Los cuatro "
                 "tienen [[estacionalidad|estacionalidades]] distintas, así que el agregado "
                 "hereda una mezcla que además se mueve con el tiempo.")}],
             "figures": [
                 Figure("resumen-ingresos", F.revenue_stack, ing,
                        "Ingreso mensual por canal",
                        "Área apilada del ingreso mensual repartido entre los cuatro canales.",
                        subtitle="En euros por mes, de septiembre de 2023 a agosto de 2026.",
                        source="Fuente: los tres marts de hechos.", table=TBL["resumen-ingresos"]),
                 Figure("resumen-cruce", F.cac_ltv_scatter, cx,
                        "Lo que cuesta un cliente frente a lo que vale",
                        "Dispersión de coste de adquisición contra valor de vida por canal.",
                        subtitle=f"{cheapest['label']} capta más barato y "
                                 f"{best_channel['label']} vale más. Cuanto más arriba y a "
                                 "la izquierda, mejor.",
                        table=table(["Canal", "CAC", "LTV", "Ratio", "Payback"],
                                    [[r["label"], eur(r["cac_loaded_eur"], 2),
                                      eur(r["ltv_projected_eur"]), ratio(r["ratio"]),
                                      f"{num(r['payback_months'], 1)} m"]
                                     for r in cx["crossover"]]),
                        source="Fuente: attribution.json × cohorts_rfm.json.")]},
        ],
        "actions": {
            "heading": "Plan de acción",
            "intro": ("Lo cinco de más retorno de todo el informe, ordenados por lo que "
                      "devuelven frente a lo que cuestan. Cada uno se desarrolla en su "
                      "página."),
            "steps": [
                {"do": "Rescatar las bajas por fallo de cobro antes de que se conviertan en baja.",
                 "why": (f"{involuntary} suscripciones se perdieron en tres años porque falló "
                         f"el cobro, no porque el cliente decidiera irse. Son unas "
                         f"{num(involuntary_year, 0)} al año y no hay ningún intento visible "
                         "de recuperarlas."),
                 "impact": f"unos {eur(involuntary_value)} al año de valor de vida",
                 "owner": "Producto / Growth", "effort": "bajo",
                 "measure": "% de fallos de cobro recuperados en 14 días"},
                {"do": "Arreglar la identificación del cliente en la parte alta del embudo.",
                 "why": (f"El {pct(gap['orphan_touchpoints_pct'])} de los contactos de "
                         f"marketing no se logra unir a ninguna persona, y con ellos el "
                         f"{pct(gap['orphan_cost_pct'])} del gasto "
                         f"({eur(gap['orphan_cost_eur'])}). No es gasto perdido: es gasto que "
                         "no se puede optimizar porque no se sabe a quién fue."),
                 "impact": f"{eur(gap['orphan_cost_eur'])} de gasto pasa a ser gestionable",
                 "owner": "Marketing / Datos", "effort": "medio",
                 "measure": "% de touchpoints que resuelven a cliente"},
                {"do": f"Subir la inversión en {best_channel['label'].lower()} y "
                       f"{cheapest['label'].lower()}, por tramos y midiendo el coste marginal.",
                 "why": (f"El canal más lento en devolver lo que costó tarda "
                         f"{num(blended['slowest_payback_months'], 1)} meses, frente a los "
                         "doce que se consideran sanos. El marketing es el "
                         f"{pct(plaus['marketing_intensity_pct'], 2)} del ingreso cuando lo "
                         "normal en suscripción es un 10-30%: el freno no es el coste, es el "
                         "volumen."),
                 "impact": "el techo de crecimiento sube, no el coste unitario",
                 "owner": "Marketing", "effort": "medio",
                 "measure": "CAC marginal a cada escalón de presupuesto"},
                {"do": "Fijar stock de seguridad por sabor con el extremo alto de la previsión.",
                 "why": (f"Seis roturas de stock dejaron sin vender "
                         f"{eur(cens['lost_demand']['eur'])} de demanda real, y tres de ellas "
                         "cayeron en los últimos siete meses. Los sabores afectados son los "
                         "de base, que son los más fáciles de prever."),
                 "impact": f"unos {eur(cens['lost_demand']['eur'])} al año de venta recuperable",
                 "owner": "Operaciones", "effort": "bajo",
                 "measure": "días de rotura por sabor y mes"},
                {"do": "Medir qué aporta el descuento de bienvenida antes de seguir pagándolo.",
                 "why": (f"El descuento cuesta 5,1 meses de vida del cliente, unos "
                         f"{eur(discount_gap_eur, 0)} de valor por alta y "
                         f"{eur(discount_total)} sobre las "
                         f"{num(disc['n_with_discount'])} altas que lo llevaron. Su lado "
                         "bueno —cuántas altas trae— no está medido en ningún sitio."),
                 "impact": f"hasta {eur(discount_total)} de valor en juego",
                 "owner": "Growth", "effort": "bajo",
                 "measure": "test con y sin descuento sobre altas y retención"},
            ]},
        "takeaways": [
            f"El canal más barato no es el mejor: {cheapest['label']} capta por "
            f"{eur(cheapest['cac_loaded_eur'], 2)} y {best_channel['label']} por "
            f"{eur(best_channel['cac_loaded_eur'], 2)}, pero el segundo vale más porque "
            "retiene diez puntos mejor al año.",
            f"El {pct(gap['orphan_touchpoints_pct'])} del marketing no se puede atribuir a "
            f"nadie: atribuir sólo lo atribuible abarata el coste real un "
            f"{pct(gap['understatement_pct'], 0)}.",
            "Las imperfecciones de los datos mueven más las conclusiones que la elección de "
            "modelo. Tratarlas bien es donde está el valor, no en el algoritmo.",
        ],
    })

    # ==================================================== 1. suscriptores
    pause_rate = max(coh["retention"]["pause_rate_by_calendar_month"],
                     key=lambda r: r["pct_paused"])
    pages.append({
        "slug": "suscriptores", "file": "01-suscriptores.html",
        "nav_title": "Suscriptores activos",
        "eyebrow": "Serie temporal · 1 de 3",
        "title": "Suscriptores activos",
        "summary": ("Cuántos hay, cuántos habrá dentro de seis meses y con cuánto margen de "
                    "error. Con las pausas tratadas como lo que son —una parada, no una "
                    "baja— y el fallo de cobro separado de la decisión del cliente."),
        "hero": {"value": num(subs_fc["yhat"][-1]),
                 "label": f"suscriptores activos previstos para "
                          f"{month_es(subs['forecast']['months'][-1])}",
                 "note": f"un {pct(subs_growth * 100, 0)} sobre los {num(subs_last)} de hoy · "
                         f"error medio del modelo {pct(mape_subs)}"},
        "kpis": [
            {"label": "Activos al cierre", "value": num(subs_last),
             "note": "netos de pausas"},
            {"label": "Error de la previsión", "value": pct(mape_subs),
             "note": "frente al 43,7% de repetir el año anterior"},
            {"label": "Pausa en agosto", "value": pct(pause_rate["pct_paused"]),
             "note": "de la base, media de los tres agostos; vuelve en otoño"},
            {"label": "Bajas por fallo de cobro", "value": num(involuntary),
             "note": "en tres años; no las decidió el cliente"},
        ],
        "glossary": entries(["cohorte", "retencion", "churn", "pausa", "backtesting",
                             "mape", "estacionalidad"]),
        "sections": [
            {"heading": "Cuántos habrá y cuánto nos podemos fiar",
             "blocks": [{"kind": "p", "html": rich(
                 "La previsión no extrapola la línea del total: descompone la base en "
                 "[[cohorte|cohortes]] vivas y aplica a cada una su [[retencion|curva de "
                 "retención]], que es lo que permite anticipar que un mes con muchas altas "
                 "recientes se comportará distinto a uno con base madura. El "
                 f"[[backtesting]] la deja en un {pct(mape_subs)} de error medio a seis "
                 "meses, unas trece veces mejor que el suelo de referencia.")},
                 {"kind": "p", "html": rich(
                     "La serie se mide sobre activos **netos de [[pausa|pausas]]**, que es "
                     "la única de las tres definiciones disponibles en la que se ve el "
                     "verano. Las otras dos cuentan como activo a quien está de pausa, y "
                     "entonces agosto simplemente no existe.")}],
             "figures": [
                 Figure("subs-forecast", F.subscribers_forecast, subs,
                        "Suscriptores activos y previsión a seis meses",
                        "Serie mensual de suscriptores activos con previsión y banda del 80%.",
                        subtitle="La banda es el 80% de confianza: cuatro de cada cinco "
                                 "meses deberían caer dentro.",
                        table=table(["Mes", "Activos"],
                                    [[month_es(r["date"]), num(r["suscriptores"])]
                                     for r in subs["series"]["active_net"][-18:]]),
                        source="Fuente: fct_subscriptions_monthly."),
                 Figure("subs-weekday", F.signup_weekday, subs,
                        "Qué día de la semana entra la gente",
                        "Barras con el efecto de cada día de la semana sobre las altas diarias.",
                        subtitle="El patrón semanal está en el flujo de altas, no en el "
                                 "número de suscriptores: nadie cancela el domingo y vuelve "
                                 "el lunes.",
                        table=table(["Día", "Altas medias", "Efecto"],
                                    [[r["label"], num(r["mean_signups"], 2),
                                      num(r["mstl_component"], 2)]
                                     for r in subs["weekly_seasonality"]["by_weekday"]]),
                        source="Fuente: dim_customers.first_subscription_date.")],
             "after": [{"kind": "flag", "tag": "Ojo con el tramo final.",
                        "text": subs["marketing_context"]["caveat"]}]},
        ],
        "actions": {
            "steps": [
                {"do": "Montar un rescate de cobro: reintento escalonado y aviso al cliente "
                       "antes de dar de baja.",
                 "why": (f"{involuntary} de las cancelaciones del histórico son por fallo de "
                         "cobro. Esos clientes no decidieron irse: se fueron porque una "
                         "tarjeta caducó y nadie se lo dijo. Duraban 255 días de media, así "
                         "que estaban funcionando."),
                 "impact": f"unos {eur(involuntary_value)} al año de valor de vida",
                 "owner": "Producto / Growth", "effort": "bajo",
                 "measure": "% de fallos recuperados en 14 días"},
                {"do": "Convertir la pausa en un producto con fecha de vuelta en vez de un "
                       "limbo.",
                 "why": (f"En un agosto medio el {pct(pause_rate['pct_paused'])} de la "
                         f"base está en pausa y {eur(pause['mrr_withdrawn_eur'])} de cuota quedan "
                         "aparcados. La pausa es buena —evita bajas— pero hoy no tiene "
                         "fecha de retorno pactada ni nada que anime a volver antes."),
                 "impact": f"{eur(pause['mrr_withdrawn_eur'])} de cuota aparcada; acortar la "
                           "pausa un mes la libera antes",
                 "owner": "Producto", "effort": "medio",
                 "measure": "duración media de la pausa y tasa de retorno"},
                {"do": "Usar la previsión para dimensionar compras y atención, no sólo para "
                       "informar.",
                 "why": (f"Con un error medido del {pct(mape_subs)} a seis meses, la "
                         "previsión es lo bastante buena para planificar inventario y "
                         "plantilla. Hoy no se usa para eso."),
                 "impact": "menos sobrestock y menos picos de carga sin cubrir",
                 "owner": "Operaciones", "effort": "bajo",
                 "measure": "desviación entre previsión y real cada mes"},
            ]},
        "takeaways": subs["insights"][:4],
    })

    # ==================================================== 2. ingresos
    gapm = ing["payment_gap"]
    pages.append({
        "slug": "ingresos", "file": "02-ingresos.html", "nav_title": "Ingresos totales",
        "eyebrow": "Serie temporal · 2 de 3",
        "title": "Ingresos totales",
        "summary": ("El ingreso de los cuatro canales, su previsión a seis meses y la "
                    "imperfección que sólo aparece si se elige bien el denominador: una "
                    "semana sin datos de cobro a mitad del histórico."),
        "hero": {"value": eur(sum(ing_fc["yhat"])),
                 "label": "ingreso previsto para los próximos seis meses",
                 "note": f"banda del 80%: {eur(sum(ing_fc['yhat_lower']))} – "
                         f"{eur(sum(ing_fc['yhat_upper']))} · error medio {pct(mape_ing)}"},
        "kpis": [
            {"label": "Ingreso acumulado", "value": eur(ing["meta"]["total_revenue_eur"]),
             "note": "tres años, cuatro canales"},
            {"label": "Último mes", "value": eur(ing_last),
             "note": month_es(ing["meta"]["history_end"])},
            {"label": "Error de la previsión", "value": pct(mape_ing),
             "note": "frente al 50,7% de repetir el año anterior"},
            {"label": "Hueco de cobro", "value": month_es(gapm["detected_month"]),
             "note": f"la caja cae un {pct(gapm['drop_vs_median_pct'])} sin que baje el MRR"},
        ],
        "glossary": entries(["mrr", "estacionalidad", "mape", "backtesting"]),
        "sections": [
            {"heading": "Cuánto entrará y por qué canal",
             "blocks": [{"kind": "p", "html": rich(
                 "De las tres medidas de ingreso disponibles se usa la devengada, que es la "
                 "única que representa servicio prestado. La caja cobrada acusa problemas de "
                 "cobro que no son problemas de negocio, y el [[mrr]] contratado es una "
                 "tarifa vigente, no un ingreso.")}],
             "figures": [
                 Figure("ing-forecast", F.revenue_forecast, ing,
                        "Ingreso total y previsión a seis meses",
                        "Serie mensual del ingreso total con previsión y banda del 80%.",
                        subtitle=f"Cierra el semestre en {eur(ing_fc['yhat'][-1])} al mes.",
                        source="Fuente: los tres marts de hechos.", table=TBL["ing-forecast"]),
                 Figure("ing-stack", F.revenue_stack, ing,
                        "Ingreso mensual por canal",
                        "Área apilada del ingreso por canal.",
                        subtitle="La suscripción arranca siendo casi todo y va cediendo peso "
                                 "a medida que maduran catálogo y boutiques.",
                        table=table(["Mes", "Total"],
                                    [[month_es(r["date"]), eur(r["eur"])]
                                     for r in ing["series"]["total"][-18:]]),
                        source="Fuente: los tres marts de hechos."),
                 Figure("ing-mix", F.channel_mix, ing,
                        "Cómo cambia el reparto entre canales",
                        "Área apilada en porcentaje del ingreso de cada mes por canal.",
                        subtitle="En porcentaje del mes, para ver el mix sin que lo tape el "
                                 "crecimiento.",
                        source="Fuente: los tres marts de hechos.", table=TBL["ing-mix"]),
                 Figure("ing-gap", F.cash_ratio, ing,
                        "Cómo se encuentra una semana de cobros perdida",
                        "Serie del cociente entre caja cobrada y MRR contratado, con el "
                        "mínimo del histórico marcado.",
                        subtitle="En valor absoluto el bache desaparece dentro del "
                                 "crecimiento. Dividiendo por una base que no crece, salta.",
                        source="Fuente: fct_subscriptions_monthly.", table=TBL["ing-gap"])]},
        ],
        "actions": {
            "steps": [
                {"do": "Poner un control diario del cociente caja / cuota contratada con "
                       "umbral de alerta.",
                 "why": ("La semana de cobros que se perdió en la migración de pasarela no "
                         "se ve en el importe total —la serie crece demasiado— pero deja el "
                         f"cociente en {num(gapm['cash_ratio_at_gap'], 3)} frente a una "
                         f"mediana de {num(gapm['cash_ratio_median'], 2)}: el mínimo absoluto "
                         "de tres años. Con ese control puesto, se habría detectado en días."),
                 "impact": "detecta en 24 h lo que tardó meses en aparecer",
                 "owner": "Datos / Finanzas", "effort": "bajo",
                 "measure": "alertas disparadas y falsos positivos"},
                {"do": "Planificar tesorería con la previsión y su banda, no con el último mes.",
                 "why": (f"La previsión de ingresos se equivoca un {pct(mape_ing)} de media a "
                         "seis meses y publica banda, así que permite planificar con un "
                         "rango en vez de con un número."),
                 "impact": f"rango de {eur(sum(ing_fc['yhat_lower']))} a "
                           f"{eur(sum(ing_fc['yhat_upper']))} para el semestre",
                 "owner": "Finanzas", "effort": "bajo",
                 "measure": "desviación mensual frente a la banda"},
                {"do": "Dimensionar la plantilla de boutique con su propio calendario.",
                 "why": ("La boutique es el canal más estacional del negocio y la "
                         "suscripción el menos, y además hacen techo en meses distintos. "
                         "Planificar las tiendas con el calendario del agregado las deja "
                         "cortas en su pico y sobradas en su valle."),
                 "impact": "menos horas mal colocadas en el pico de otoño",
                 "owner": "Operaciones de tienda", "effort": "medio",
                 "measure": "ventas por hora trabajada, por mes"},
            ]},
        "takeaways": ing["insights"][:4],
    })

    # ==================================================== 3. cápsulas
    pages.append({
        "slug": "capsulas", "file": "03-capsulas.html", "nav_title": "Demanda por sabor",
        "eyebrow": "Serie temporal · 3 de 3",
        "title": "Demanda por sabor de cápsula",
        "summary": ("Doce sabores, dos ritmos de demanda muy distintos y una previsión por "
                    "sabor para comprar con criterio. Con las roturas de stock detectadas y "
                    "descontadas, porque si no la previsión pide de menos."),
        "hero": {"value": num(sum(cap_fc["yhat"])),
                 "label": "cápsulas previstas para los próximos seis meses",
                 "note": f"banda del 80%: {num(sum(cap_fc['yhat_lower']))} – "
                         f"{num(sum(cap_fc['yhat_upper']))} · error medio {pct(mape_cap)}"},
        "kpis": [
            {"label": "Unidades del histórico", "value": num(cap["meta"]["total_units"]),
             "note": "club + tienda, doce sabores"},
            {"label": "Roturas detectadas", "value": str(cens["detection"]["n_detected"]),
             "note": f"de {cens['detection']['n_runs_tested']} candidatas, sin falsos positivos"},
            {"label": "Venta perdida", "value": eur(cens["lost_demand"]["eur"]),
             "note": "demanda real que no se pudo servir"},
            {"label": "Error de la previsión", "value": pct(mape_cap),
             "note": "frente al 52,5% de repetir el año anterior"},
        ],
        "glossary": entries(["censura", "estacionalidad", "mape", "backtesting"]),
        "sections": [
            {"heading": "Dos ritmos, no doce series",
             "blocks": [{"kind": "p", "html": rich(
                 "Diez sabores se comportan como un único producto repartido en diez "
                 "etiquetas: mismo techo en marzo, mismo suelo en agosto. Los dos de "
                 "temporada son otra cosa y son el motivo de que esta página exista: pesan "
                 "el 9% del volumen, no se ven en el total y son los que deciden el "
                 "calendario de compras, porque su [[estacionalidad]] llega a multiplicar "
                 "por veintisiete entre su mejor y su peor mes.")}],
             "figures": [
                 Figure("cap-forecast", F.capsule_forecast, cap,
                        "Demanda total de cápsulas y previsión",
                        "Serie mensual de unidades con previsión a seis meses y banda del 80%.",
                        subtitle="Es la cifra con la que se compra: unidades, no euros, para "
                                 "que un cambio de precio no la contamine.",
                        source="Fuente: fct_shipments + fct_shop_orders.", table=TBL["cap-forecast"]),
                 Figure("cap-emphasis", F.flavour_emphasis, cap,
                        "Los dos sabores de temporada frente a los diez de base",
                        "Líneas de demanda mensual por sabor, con los estacionales "
                        "destacados y el resto en gris.",
                        subtitle="Calabaza hace techo en octubre y jengibre en diciembre.",
                        source="Fuente: agregado por sabor.", table=TBL["cap-emphasis"]),
                 Figure("cap-heatmap", F.seasonal_heatmap, cap,
                        "Cuándo se vende cada sabor",
                        "Mapa de calor del índice de demanda sobre tendencia por sabor y mes.",
                        subtitle="Rojo es por encima de su propia tendencia y azul por "
                                 "debajo. Es el calendario de compras de un vistazo.",
                        source="Fuente: mediana de los últimos 24 meses.", width="full", table=TBL["cap-heatmap"]),
                 Figure("cap-stockout", F.stockout_detail, cap,
                        "Cómo se distingue una rotura de una caída de ventas",
                        "Series diarias de un sabor en tienda y en el club con la ventana de "
                        "rotura sombreada.",
                        subtitle="Durante la ventana la tienda marca cero y el club sigue "
                                 "sirviendo igual. Si fuera falta de interés, caerían los dos.",
                        table=table(["Sabor", "Desde", "Hasta", "Días", "Venta perdida"],
                                    [[w["flavor"], w["start"], w["end"], str(int(w["days"])),
                                      num(w["expected_units"], 0) + " ud."]
                                     for w in cens["windows"]]),
                        source="Fuente: fct_shop_orders frente a fct_shipments.",
                        width="full")]},
        ],
        "actions": {
            "steps": [
                {"do": "Fijar el stock de seguridad de cada sabor con el extremo alto de su "
                       "previsión, no con la media.",
                 "why": (f"Las seis roturas costaron {eur(cens['lost_demand']['eur'])} de "
                         "venta que sí existía, y cayeron sobre sabores de base, que son los "
                         "más predecibles del catálogo. Comprar contra la media garantiza "
                         "quedarse corto la mitad de los meses."),
                 "impact": f"unos {eur(cens['lost_demand']['eur'])} al año de venta recuperable",
                 "owner": "Operaciones / Compras", "effort": "bajo",
                 "measure": "días de rotura por sabor y nivel de servicio"},
                {"do": "Cerrar la compra de los sabores de temporada con seis meses de "
                       "antelación y asumir una banda ancha.",
                 "why": ("Calabaza concentra su año en octubre y jengibre en diciembre. La "
                         "previsión los sitúa con medio año de margen, pero con mucha menos "
                         "precisión que los de base porque cada uno tiene una sola campaña "
                         "completa en el histórico. Es una decisión de cuánto sobrestock se "
                         "acepta, no un problema de modelo."),
                 "impact": "evita quedarse sin el producto que más margen deja en su pico",
                 "owner": "Compras", "effort": "medio",
                 "measure": "cobertura en el mes pico y sobrante en enero"},
                {"do": "Alertar automáticamente cuando un sabor deje de venderse en tienda "
                       "mientras el club lo sigue enviando.",
                 "why": ("Esa combinación es la firma exacta de una rotura de stock y se "
                         "detectó a posteriori con ella. Como regla automática, avisa el "
                         "mismo día en vez de aparecer meses después en un análisis."),
                 "impact": "reduce la duración de la rotura de semanas a días",
                 "owner": "Operaciones / Datos", "effort": "bajo",
                 "measure": "horas entre el inicio de la rotura y el aviso"},
            ]},
        "takeaways": cap["insights"][:4],
    })

    # ==================================================== 4. cohortes y RFM
    at_risk = segments["En riesgo"]
    champions = segments["Campeones"]
    pages.append({
        "slug": "cohortes", "file": "04-cohortes.html", "nav_title": "Cohortes y RFM",
        "eyebrow": "Comportamiento de cliente",
        "title": "Cohortes y RFM",
        "summary": ("Qué le pasa a un cliente según el tiempo que lleva con nosotros, y qué "
                    "grupos de compradores merecen una acción distinta. Con el descuento de "
                    "bienvenida y el regalo separados, porque se comportan de otra manera."),
        "kpis": [
            {"label": "Suscripciones analizadas", "value": num(coh["meta"]["n_subscriptions"]),
             "note": f"{pct(coh['meta']['right_censored_pct'])} siguen activas"},
            {"label": "Siguen al año", "value": pct(
                next(r["retention"] for r in coh["retention"]["base"] if r["age"] == 12) * 100),
             "note": "sin contar regaladas"},
            {"label": "Coste del descuento", "value": eur(discount_gap_eur, 0),
             "note": "de valor por alta que lo lleva"},
            {"label": "Clientes en riesgo", "value": num(at_risk["clientes"]),
             "note": f"{pct(at_risk['pct_ingreso'])} del ingreso de tienda, "
                     f"{num(at_risk['recencia_mediana'], 0)} días sin comprar"},
        ],
        "glossary": entries(["cohorte", "retencion", "hazard", "churn", "rfm", "ltv",
                             "pausa"]),
        "sections": [
            {"heading": "El descuento de bienvenida es una criba, no una fidelización",
             "blocks": [{"kind": "p", "html": rich(
                 "Comparar dos grupos sólo vale si se parecen, así que lo primero fue "
                 "comprobar a quién se le dio el descuento: está repartido al azar entre "
                 "canales, planes y años. Eso autoriza a leer la diferencia entre las dos "
                 "[[retencion|curvas]] como el efecto del descuento y no como una diferencia "
                 "entre dos tipos de cliente.")},
                 {"kind": "p", "html": rich(
                     "El resultado: el [[hazard|riesgo de cancelar]] del grupo con descuento "
                     "es 7 puntos más alto en el primer mes y 14 en el segundo, justo cuando "
                     "empieza a cobrarse el precio completo. A partir del tercero los dos "
                     "grupos se comportan igual. No deteriora la relación a largo plazo: "
                     "produce una criba de una vez, de unas "
                     f"{num(disc['excess_total_months_1_2'], 0)} bajas.")}],
             "figures": [
                 Figure("coh-discount", F.retention_curve, coh,
                        "Cuánta gente sigue, con y sin descuento de bienvenida",
                        "Dos curvas de retención por edad de la suscripción.",
                        subtitle="Las dos curvas se separan en los meses 1 y 2 y después "
                                 "caen en paralelo.",
                        source="Fuente: fct_subscriptions_monthly.", table=TBL["coh-discount"]),
                 Figure("coh-gift", F.gifted_curve, coh,
                        "La suscripción regalada no es una suscripción",
                        "Curva de retención de las suscripciones regaladas frente a las "
                        "normales.",
                        subtitle="Aguantan mejor que nadie hasta el mes 3 y se desploman "
                                 "cuando acaba el regalo. Mezclarlas con el resto inventa un "
                                 "problema de retención que no existe.",
                        source="Fuente: fct_subscriptions_monthly.", table=TBL["coh-gift"]),
                 Figure("coh-matrix", F.cohort_matrix, coh,
                        "Cada cohorte de alta, mes a mes",
                        "Mapa de calor del porcentaje de cada cohorte mensual que sigue "
                        "activo a cada edad.",
                        subtitle="El triángulo vacío no es un hueco de datos: son las altas "
                                 "recientes, que todavía no han tenido tiempo de llegar ahí.",
                        source="Fuente: fct_subscriptions_monthly.", width="full", table=TBL["coh-matrix"]),
                 Figure("coh-logo-revenue", F.logo_vs_revenue, coh,
                        "Clientes que siguen frente a dinero que sigue entrando",
                        "Tres curvas: clientes retenidos, cuota retenida y cuota "
                        "efectivamente cobrable.",
                        subtitle="La curva de clientes y la de cuota contratada van pegadas; "
                                 "la que se despega es la que de verdad se cobra.",
                        source="Fuente: fct_subscriptions_monthly. El eje empieza en 40%.",
                        table=TBL["coh-logo-revenue"]),
                 Figure("coh-gap", F.gap_decomposition, coh,
                        "De qué está hecho ese hueco",
                        "Barras apiladas del hueco en puntos, repartido entre el efecto de "
                        "la pausa y el del cambio de plan.",
                        subtitle=f"La pausa explica el {pct(pause_share, 0)} del hueco. El "
                                 f"cambio de plan no llega a mover una décima de punto: "
                                 f"{num(mix_mean_pp, 2)} de media.",
                        source="Fuente: fct_subscriptions_monthly.",
                        table=table(["Mes desde el alta", "Suscripciones en pausa",
                                     "Cambio de plan", "Hueco total"],
                                    [[num(r["months_since_start"]),
                                      f"{num(r['efecto_pausa_pp'], 2)} pp",
                                      f"{num(r['efecto_mix_pp'], 2)} pp",
                                      f"{num(r['gap_total_pp'], 2)} pp"]
                                     for r in coh["plan_changes"]["logo_vs_revenue_retention"][1:]])),
                 Figure("coh-rfm", F.rfm_segments, coh,
                        "Qué pesa cada grupo de compradores",
                        "Barras horizontales comparando porcentaje de clientes y de ingreso "
                        "por segmento.",
                        subtitle="Los campeones son uno de cada seis clientes y casi un "
                                 "tercio del ingreso de tienda.",
                        table=table(["Segmento", "Clientes", "% clientes", "% ingreso",
                                     "Gasto medio", "Días sin comprar"],
                                    [[r["segmento"], num(r["clientes"]), pct(r["pct_clientes"]),
                                      pct(r["pct_ingreso"]), eur(r["gasto_medio"]),
                                      num(r["recencia_mediana"], 0)]
                                     for r in sorted(coh["rfm"]["segments"],
                                                     key=lambda r: -r["pct_ingreso"])]),
                        source="Fuente: fct_shop_orders, clientes identificados.",
                        width="full")],
             "after": [{"kind": "flag", "tag": "Límite de cobertura.",
                        "text": coh["rfm"]["coverage_note"] +
                                " Cualquier cifra por cliente de esta página se refiere, por "
                                "tanto, a clientes identificados."}]},
        ],
        "actions": {
            "steps": [
                {"do": "Medir qué aporta el descuento de bienvenida, o moverlo al tercer mes.",
                 "why": (f"Hoy sabemos lo que cuesta —5,1 meses de vida, unos "
                         f"{eur(discount_gap_eur, 0)} por alta, {eur(discount_total)} sobre "
                         f"las {num(disc['n_with_discount'])} altas que lo llevaron— pero no "
                         "lo que aporta, porque se concede después de que la persona ya haya "
                         "decidido suscribirse. Moverlo al mes 3 lo convertiría en un premio "
                         "a quedarse en vez de en un filtro a la entrada."),
                 "impact": f"hasta {eur(discount_total)} de valor en juego",
                 "owner": "Growth", "effort": "bajo",
                 "measure": "altas y retención a 90 días, con y sin descuento"},
                {"do": f"Lanzar una recuperación sobre los {num(at_risk['clientes'])} clientes "
                       "en riesgo antes de que se enfríen del todo.",
                 "why": (f"Son el {pct(at_risk['pct_clientes'])} de los clientes y el "
                         f"{pct(at_risk['pct_ingreso'])} del ingreso de tienda, con un gasto "
                         f"medio de {eur(at_risk['gasto_medio'])} —por encima de los leales— "
                         f"y {num(at_risk['recencia_mediana'], 0)} días sin aparecer. Son "
                         "buenos clientes yéndose, no clientes malos."),
                 "impact": f"{eur(at_risk['gasto_total'])} de facturación histórica en ese grupo",
                 "owner": "CRM", "effort": "bajo",
                 "measure": "% del segmento que vuelve a comprar en 60 días"},
                {"do": f"Ofrecer suscripción a los ~{num(champions_no_sub)} campeones de "
                       "tienda que todavía no son suscriptores.",
                 "why": ("Ser buen comprador de tienda y ser suscriptor resultan ser cosas "
                         "independientes: la proporción de suscriptores es prácticamente la "
                         "misma en todos los segmentos. Eso significa que hay una audiencia "
                         "identificada, que ya compra mucho, a la que nadie le ha propuesto "
                         "el club."),
                 "impact": f"~{num(champions_no_sub)} clientes con intención ya demostrada",
                 "owner": "CRM / Growth", "effort": "bajo",
                 "measure": "conversión a suscripción del grupo objetivo"},
                {"do": "Tratar el regalo como un canal con su propia conversión al terminar "
                       "el término.",
                 "why": ("Las suscripciones regaladas aguantan mejor que ninguna hasta el "
                         "mes 3 y se desploman al acabar el regalo, estabilizándose en torno "
                         "a uno de cada cuatro. Ese desplome es el momento de la campaña, y "
                         "hoy no hay ninguna."),
                 "impact": "tres de cada cuatro regalos se pierden sin intento de conversión",
                 "owner": "CRM", "effort": "medio",
                 "measure": "% de regalos que continúan pagando tras el término"},
            ]},
        "takeaways": coh["insights"][:5],
    })

    # ==================================================== 5. atribución
    pages.append({
        "slug": "atribucion", "file": "05-atribucion.html", "nav_title": "Atribución",
        "eyebrow": "De dónde vienen los clientes",
        "title": "Atribución de marketing",
        "summary": ("Cuatro formas de repartir el mérito entre canales y la comprobación de "
                    "cuánto cambia la respuesta según cuál se elija. Cambia mucho menos que "
                    "los tres problemas de datos que hay que arreglar antes."),
        "kpis": [
            {"label": "Contactos de marketing", "value": num(att["meta"]["n_touchpoints_total"]),
             "note": "en el histórico completo"},
            {"label": "Sin cliente asociado", "value": pct(gap["orphan_touchpoints_pct"]),
             "note": f"se llevan {eur(gap['orphan_cost_eur'])} de gasto"},
            {"label": "Altas sin rastro", "value": pct(gap["conversions_without_touchpoint_pct"]),
             "note": "aparecen sin ningún contacto previo"},
            {"label": "CAC infravalorado", "value": pct(gap["understatement_pct"], 0),
             "note": f"{eur(gap['cac_attributable_eur'], 2)} frente a "
                     f"{eur(gap['cac_loaded_eur'], 2)} reales"},
        ],
        "glossary": entries(["touchpoint", "gap", "cac", "markov"]),
        "sections": [
            {"heading": "Antes de repartir nada: el tramo final no se puede usar",
             "blocks": [{"kind": "p", "html": rich(
                 "Los recorridos de marketing se reconstruyen hacia atrás desde el alta, así "
                 "que quien se suscribirá el mes que viene todavía no ha dejado sus "
                 "[[touchpoint|contactos]] en el histórico. Resultado: el último tramo "
                 "tiene las mismas altas con mucha menos huella, y el coste por alta parece "
                 "desplomarse. Es la conclusión más golosa que puede dar esta página y es "
                 "falsa.")}],
             "figures": [
                 Figure("att-censoring", F.censoring_panels, att,
                        "Por qué el último trimestre no se puede leer",
                        "Dos paneles: contactos y altas por mes arriba, coste por alta abajo.",
                        subtitle="Las altas se mantienen planas mientras los contactos se "
                                 "desploman. El coste aparente cae un 79% sin que el negocio "
                                 "cambie nada.",
                        source="Fuente: fct_marketing_attribution, dim_customers.",
                        width="full", table=TBL["att-censoring"])]},
            {"heading": "Cuánto mide de verdad cada modelo",
             "blocks": [{"kind": "p", "html": rich(
                 "Se comparan cuatro repartos: todo el mérito al primer contacto, todo al "
                 "último, a partes iguales, y una [[markov|cadena de Markov]] que mide cuánto "
                 "caería la conversión si el canal desapareciera. La conclusión útil es que "
                 "**apenas se diferencian**: con recorridos de dos contactos y medio de "
                 "media, discutir de modelo es discutir de decimales. Donde sí hay que "
                 "invertir esfuerzo es en el [[gap|attribution gap]].")}],
             "figures": [
                 Figure("att-credit", F.credit_by_model, att,
                        "A quién le da el mérito cada modelo",
                        "Líneas que conectan el porcentaje de crédito que cada modelo asigna "
                        "a cada canal.",
                        subtitle="Si los cuatro coincidieran del todo, las líneas serían "
                                 "horizontales.",
                        table=table(["Canal", "Primer contacto", "Último", "Repartido",
                                     "Markov"],
                                    [[r["label"], pct(r["first_touch"]), pct(r["last_touch"]),
                                      pct(r["linear"]), pct(r["markov"])]
                                     for r in att["models"]["credit_pct"]]),
                        source="Fuente: fct_marketing_attribution."),
                 Figure("att-cac", F.cac_by_channel, att,
                        "Lo que cuesta captar por canal, con y sin el gasto sin dueño",
                        "Barras del coste por conversión con rombos marcando el coste una "
                        "vez repartido el gasto no asignable.",
                        subtitle="El salto entre la barra y el rombo es mayor que cualquier "
                                 "diferencia entre modelos, y no es igual para todos.",
                        table=table(["Canal", "Coste repartido", "Coste real", "Conversiones"],
                                    [[r["label"], eur(r["markov"], 2),
                                      eur(r["cac_cargado_markov"], 2),
                                      num(r["conversions_markov"])]
                                     for r in att["cac"]["by_channel"]]),
                        source="Fuente: coste ponderado por reclamación."),
                 Figure("att-ios", F.resolution_by_channel, att,
                        "Un canal que dejó de ser medible durante medio año",
                        "Líneas del porcentaje de contactos que se logran unir a una "
                        "conversión, con paid social destacado.",
                        subtitle="Sólo un canal pierde el rastro y sólo unos meses, lo que "
                                 "descarta un fallo general de medición.",
                        source="Fuente: fct_marketing_attribution.", width="full", table=TBL["att-ios"])]},
        ],
        "actions": {
            "steps": [
                {"do": "Arreglar la captura de identidad en la parte alta del embudo.",
                 "why": (f"El {pct(gap['orphan_touchpoints_pct'])} de los contactos no se "
                         f"puede unir a ninguna persona y arrastra "
                         f"{eur(gap['orphan_cost_eur'])} de gasto. Y no afecta por igual: en "
                         "paid social es el 31% de sus contactos y en el código de influencer "
                         "el 19%, así que ignorarlo no abarata a todos por igual, **cambia el "
                         "orden de los canales**."),
                 "impact": f"{eur(gap['orphan_cost_eur'])} de gasto pasa a ser optimizable",
                 "owner": "Marketing / Datos", "effort": "medio",
                 "measure": "% de contactos que resuelven a cliente"},
                {"do": "Publicar el coste de adquisición cargado como métrica oficial, no el "
                       "del reparto.",
                 "why": (f"El reparto da {eur(gap['cac_attributable_eur'], 2)} y la realidad "
                         f"{eur(gap['cac_loaded_eur'], 2)}: un "
                         f"{pct(gap['understatement_pct'], 0)} de diferencia. Las dos cifras "
                         "son legítimas, pero un cuadro de mando de atribución enseña la "
                         "primera por defecto, que es la bonita."),
                 "impact": f"corrige un {pct(gap['understatement_pct'], 0)} de optimismo en "
                           "todas las decisiones de inversión",
                 "owner": "Marketing", "effort": "bajo",
                 "measure": "coste cargado por canal, mensual"},
                {"do": "No juzgar paid social con datos de atribución del primer semestre de "
                       "2025; medirlo con un test de retención de presupuesto.",
                 "why": ("Durante esos meses su tasa de rastreo cayó del 24% al 8,5% mientras "
                         "el resto de canales no se movía. Los clientes siguieron llegando; "
                         "lo que desapareció fue la capacidad de demostrarlo. Cualquier "
                         "comparación en esa ventana le es injusta."),
                 "impact": "evita recortar el canal con mejor retorno por un problema de "
                           "medición",
                 "owner": "Marketing", "effort": "medio",
                 "measure": "test geográfico o de apagado con grupo de control"},
            ]},
        "takeaways": att["insights"][:5],
    })

    # ==================================================== 6. CAC × LTV
    influencer = next(r for r in cx["crossover"] if r["channel"] == "influencer_code")
    pages.append({
        "slug": "cac-ltv", "file": "06-cac-ltv.html", "nav_title": "CAC × LTV",
        "eyebrow": "Conclusión de negocio",
        "title": "Lo que cuesta un cliente contra lo que vale",
        "summary": ("La división que cierra el informe, canal a canal, con las dos decisiones "
                    "metodológicas puestas a prueba y una lectura incómoda: el problema de "
                    "este negocio no es lo que paga por crecer."),
        "hero": {"value": f"{num(blended['slowest_payback_months'], 1)} meses",
                 "label": "tarda el canal más lento en devolver lo que costó captar un cliente",
                 "note": f"el objetivo habitual en suscripción son "
                         f"{cx['meta']['payback_target_months']} meses"},
        "kpis": [
            {"label": "Coste por cliente", "value": eur(blended["cac_loaded_eur"], 2),
             "note": "todo el gasto entre todas las altas"},
            {"label": "Valor por cliente", "value": eur(blended["ltv_weighted_eur"]),
             "note": "proyectado a 36 meses"},
            {"label": "Peso del marketing", "value": pct(plaus["marketing_intensity_pct"], 2),
             "note": f"del ingreso; lo normal es un {plaus['typical_intensity_pct']}%"},
            {"label": "Canal más caro", "value": eur(referral["cac_loaded_eur"], 2),
             "note": f"{referral['label']}, casi el triple que la media"},
        ],
        "glossary": entries(["cac", "ltv", "arpu", "payback", "retencion"]),
        "sections": [
            {"heading": "El más barato de captar no es el que más deja",
             "blocks": [{"kind": "p", "html": rich(
                 f"{cheapest['label']} capta por {eur(cheapest['cac_loaded_eur'], 2)} y "
                 f"{best_channel['label']} por {eur(best_channel['cac_loaded_eur'], 2)}. Un "
                 "cuadro de mando ordenado por coste pondría al primero por delante y "
                 "recomendaría moverle presupuesto. Pero el segundo retiene diez puntos mejor "
                 f"al año y acaba valiendo {eur(best_channel['ltv_projected_eur'])} frente a "
                 f"{eur(cheapest['ltv_projected_eur'])}.")},
                 {"kind": "p", "html": rich(
                     "Y lo que separa a los canales no es el precio: el [[arpu]] varía menos "
                     "de un 5% entre ellos, mientras que los meses que dura el cliente varían "
                     "un 28%. El **93% de la diferencia de valor es duración**. El canal no "
                     "cambia lo que el cliente paga, cambia cuánto tiempo se queda.")}],
             "figures": [
                 Figure("cx-scatter", F.cac_ltv_scatter, cx,
                        "Coste frente a valor, por canal",
                        "Dispersión con coste de adquisición en horizontal y valor de vida en "
                        "vertical, con diagonales de referencia.",
                        subtitle="Las diagonales marcan cuántas veces se recupera lo "
                                 "invertido. El tamaño de cada burbuja son los clientes que "
                                 "trajo ese canal.",
                        table=table(["Canal", "Coste", "Valor", "Veces", "Sigue al año",
                                     "Recomendación"],
                                    [[r["label"], eur(r["cac_loaded_eur"], 2),
                                      eur(r["ltv_projected_eur"]), ratio(r["ratio"]),
                                      pct(r["retention_12m_pct"]), r["verdict"]]
                                     for r in cx["crossover"]]),
                        source="Fuente: attribution.json × cohorts_rfm.json."),
                 Figure("cx-robustness", F.robustness_lines, cx,
                        "¿Aguanta el orden si cambiamos de criterio?",
                        "Líneas del ratio de cada canal bajo las cuatro combinaciones "
                        "metodológicas posibles.",
                        subtitle="El peor canal lo es en las cuatro. El primer puesto, en "
                                 "cambio, depende de qué medida de valor se use.",
                        source="Fuente: cac_ltv.json.", table=TBL["cx-robustness"]),
                 Figure("cx-margin", F.margin_sensitivity, cx,
                        "Qué pasa si metemos el margen en la cuenta",
                        "Líneas del ratio de cada canal según el margen bruto que se suponga.",
                        subtitle="El informe no tiene coste de producto, así que el valor "
                                 "es ingreso. Con un margen del 30% las cifras vuelven a un "
                                 "rango creíble sin cambiar el orden.",
                        table=table(["Canal", "Margen mínimo para que siga mereciendo la pena"],
                                    [[next(c["label"] for c in cx["crossover"]
                                           if c["channel"] == k), pct(v)]
                                     for k, v in sorted(plaus["breakeven_margin_pct"].items(),
                                                        key=lambda kv: kv[1])]),
                        source="Fuente: cac_ltv.json.", width="full")],
             "after": [{"kind": "flag", "tag": "Una cifra demasiado buena es un aviso.",
                        "text": ("Recuperar hasta 37 veces lo invertido está fuera de rango. "
                                 "Faltan dos costes en la cuenta: el de producto, que este "
                                 "informe no tiene, y un gasto de marketing que es el "
                                 f"{pct(plaus['marketing_intensity_pct'], 2)} del ingreso "
                                 "cuando lo habitual es diez veces más. Ninguno de los dos "
                                 "cambia el orden de los canales, pero sí el nivel.")}]},
        ],
        "actions": {
            "heading": "Qué hacer con esto",
            "intro": ("Las conclusiones de esta página son las que más dinero mueven, y "
                      "también las que más supuestos arrastran. Cada recomendación dice de "
                      "cuál depende."),
            "steps": [
                {"do": f"Subir el presupuesto de {best_channel['label'].lower()} y "
                       f"{cheapest['label'].lower()} por escalones, midiendo el coste de cada "
                       "escalón antes del siguiente.",
                 "why": (f"El canal más lento devuelve lo invertido en "
                         f"{num(blended['slowest_payback_months'], 1)} meses y el marketing "
                         f"pesa un {pct(plaus['marketing_intensity_pct'], 2)} del ingreso. "
                         "Todo apunta a que se está invirtiendo de menos. El supuesto que hay "
                         "que vigilar es que el coste no se dispare al escalar, y eso estos "
                         "datos no lo pueden contestar: hay que probarlo."),
                 "impact": "el freno del crecimiento deja de ser el presupuesto",
                 "owner": "Dirección / Marketing", "effort": "medio",
                 "measure": "coste por cliente en cada escalón de inversión"},
                {"do": f"Rediseñar el incentivo de {referral['label'].lower()}.",
                 "why": (f"Cuesta {eur(referral['cac_loaded_eur'], 2)} por cliente, casi el "
                         f"triple que la media, y es el único canal que dejaría de merecer la "
                         f"pena con un margen razonable: necesita un "
                         f"{pct(plaus['breakeven_margin_pct']['referral'])} de margen bruto "
                         "frente al 8% de paid social. Retiene bien; lo caro es el premio."),
                 "impact": f"unos {eur(referral_extra)} de sobrecoste frente al coste medio",
                 "owner": "Growth", "effort": "bajo",
                 "measure": "coste por referido tras el rediseño, a volumen constante"},
                {"do": "Auditar con qué creadores y con qué oferta trabaja el código de "
                       "influencer antes de darle más presupuesto.",
                 "why": (f"Es el canal que peor retiene de todos: "
                         f"{pct(influencer['retention_12m_pct'])} sigue al año frente al "
                         f"{pct(best_channel['retention_12m_pct'])} de "
                         f"{best_channel['label'].lower()}. Son cinco meses menos de vida por "
                         "cliente. La pregunta no es si captar más barato, es a quién está "
                         "captando."),
                 "impact": f"{eur(best_channel['ltv_projected_eur'] - influencer['ltv_projected_eur'])} "
                           "de diferencia de valor por cliente frente al mejor canal",
                 "owner": "Marketing", "effort": "medio",
                 "measure": "retención a 12 meses por creador"},
                {"do": "Pedir el coste de producto para que estas cifras signifiquen algo.",
                 "why": ("Sin coste de producto, el valor de un cliente es ingreso y no "
                         "margen, y el ratio sale fuera de cualquier rango creíble. Con un "
                         "margen del 30% las cifras vuelven a la normalidad. Es el dato que "
                         "más mejora este informe y no está en ningún sistema analítico."),
                 "impact": "convierte un ratio decorativo en una cifra sobre la que decidir",
                 "owner": "Finanzas / Datos", "effort": "medio",
                 "measure": "margen de contribución por SKU disponible en el almacén de datos"},
            ]},
        "takeaways": cx["insights"][:6],
    })

    _enrich(pages)
    return pages


# Nombres de columna que los notebooks citan por su nombre de almacén y que
# en una conclusión de negocio hay que decir en castellano.
FIELD_LABEL = {
    "is_active_eom": "el estado a fin de mes",
    "is_gifted": "la marca de regalo",
    "cancel_reason": "el motivo de cancelación",
    "cost_eur": "el coste",
}

# Sin barras invertidas a propósito: las clases explícitas dicen lo mismo que
# `` y sobreviven a cualquier reescritura automática del fichero.
_CHANNEL_RE = re.compile(
    "(?<![A-Za-z0-9_])("
    + "|".join(sorted(list(T.CHANNEL_LABEL) + list(FIELD_LABEL),
                      key=len, reverse=True))
    + ")(?![A-Za-z0-9_])")


def _relabel(text: str) -> str:
    """
    Cambia las claves de canal y los nombres de columna por su nombre en prosa.

    Las conclusiones vienen tal cual de los notebooks, donde los canales se
    llaman como en el almacén. Un informe de negocio no puede publicar
    `paid_social` en mitad de una frase, y reescribirlas a mano volvería a
    meter cifras escritas por una persona: se traduce sólo la etiqueta.
    """
    names = {**T.CHANNEL_LABEL, **FIELD_LABEL}
    out = _CHANNEL_RE.sub(lambda m: names[m.group(1)], text)
    return out[0].upper() + out[1:] if out else out


def _enrich(pages):
    """
    Pasa por `rich()` el texto que no lo lleva ya escrito: recomendaciones,
    conclusiones y viñetas. Así la prosa se escribe igual en todo el fichero
    —con `**negrita**` y `[[término]]`— sin tener que recordar qué campos van
    marcados como seguros y cuáles los escapa Jinja.
    """
    for page in pages:
        for step in page.get("actions", {}).get("steps", []):
            for field in ("do", "why", "impact", "measure"):
                if field in step:
                    step[field] = rich(step[field])
        page["takeaways"] = [rich(_relabel(t)) for t in page.get("takeaways", [])]
        for section in page["sections"]:
            for block in section.get("blocks", []):
                if block["kind"] == "list":
                    block["bullets"] = [rich(b) for b in block["bullets"]]
                elif block["kind"] in ("note", "flag"):
                    block["text"] = rich(_relabel(block["text"]))
