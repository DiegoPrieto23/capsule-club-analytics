"""
Capsule Club Analytics — datos del dashboard de Claude.

Lee los seis JSON de `analysis/outputs/` y escribe en `dashboard/data/` los CSV
planos con los que se monta el dashboard ejecutivo en claude.ai (tipo
Dashboard). El diccionario de datos está en `dashboard/README.md`.

    python dashboard/export_dashboard_data.py

Reglas del tipo Dashboard que se cumplen aquí, y que el propio script comprueba
antes de dar la exportación por buena:

  - un CSV plano por dataset, de menos de 8 MB, y el id del dataset es el nombre
    del fichero (`[A-Za-z0-9_-]`, 64 caracteres como mucho);
  - números sin formatear (punto decimal, sin €), fechas ISO `YYYY-MM-DD` y,
    junto a cada clave (`paid_social`), su etiqueta en castellano y sus dos
    colores, sacados de `report/theme.py` como en el informe;
  - **ninguna cifra se escribe a mano.** Los KPI y las recomendaciones no se
    recalculan: salen de `report/content.py`, que los guarda junto al texto
    formateado del informe, así que dashboard e informe no pueden discrepar.

Lee los JSON con `build_report.load_data()`, que los redondea a diez cifras
significativas: las sumas de DuckDB no garantizan el orden y, sin eso, dos
ejecuciones con los mismos datos cambiarían el último decimal de los CSV.
"""

from __future__ import annotations

import csv
import math
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT / "report"))

import build_report as B      # noqa: E402  load_data, formateadores y month_es
import content                # noqa: E402
import theme as T             # noqa: E402
from glossary import GLOSSARY  # noqa: E402

OUT = HERE / "data"
MAX_BYTES = 8 * 1024 * 1024
DATASET_ID = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


# ---------------------------------------------------------------- escritura

def _cell(value):
    """Un valor escalar, sin formato: el dashboard decide cómo enseñarlo."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, float):
        if math.isnan(value) or math.isinf(value):
            return ""
        value = float(f"{value:.10g}")
        return str(int(value)) if value.is_integer() else repr(value)
    if isinstance(value, (int, str)):
        return str(value)
    raise TypeError(f"valor no plano: {value!r}")


def write(dataset_id, columns, rows):
    if not DATASET_ID.match(dataset_id):
        raise ValueError(f"id de dataset no válido: {dataset_id!r}")
    path = OUT / f"{dataset_id}.csv"
    with path.open("w", encoding="utf-8", newline="") as fh:
        out = csv.writer(fh, lineterminator="\n")
        out.writerow(columns)
        for row in rows:
            extra = set(row) - set(columns)
            if extra:
                raise KeyError(f"{dataset_id}: columnas sin declarar {sorted(extra)}")
            out.writerow([_cell(row.get(c)) for c in columns])
    size = path.stat().st_size
    if size > MAX_BYTES:
        raise ValueError(f"{dataset_id}: {size} bytes, por encima de 8 MB")
    return dataset_id, len(rows), size


# ---------------------------------------------------------------- etiquetas

def _cap(text):
    return text[:1].upper() + text[1:] if text else text


def _plain(text):
    """Quita el marcado de `rich()`: `[[clave|texto]]` deja el texto y `**` se va."""
    text = re.sub(r"\[\[([^\]|]+)(?:\|([^\]]+))?\]\]",
                  lambda m: m.group(2) or GLOSSARY[m.group(1)]["name"].lower(), text)
    return text.replace("**", "")


def _period_label(start, end):
    if start == end:
        return B.month_es(start)
    return f"{B.month_es(start)} – {B.month_es(end)}"


def channel(key):
    """Canal de captación. `direct_unknown` sale en gris, como en el informe."""
    return {"channel": key, "channel_label": T.CHANNEL_LABEL[key],
            "color": T.channel_color(key, "light"),
            "color_dark": T.channel_color(key, "dark")}


def revenue_channel(key):
    slot = T.REVENUE_CHANNEL_SLOT[key]
    return {"channel": key, "channel_label": T.REVENUE_CHANNEL_LABEL[key],
            "color": T.series(slot, "light"), "color_dark": T.series(slot, "dark")}


def flavour_lookup(cap):
    """
    Lo mismo que `figures.flavour_emphasis`: doce sabores no son doce colores.
    Los de temporada van en las primeras ranuras y los diez de base en gris.
    """
    seasonal = [f["flavor"] for f in cap["flavors"] if f["is_seasonal"]]
    out = {}
    for f in cap["flavors"]:
        if f["is_seasonal"]:
            slot = seasonal.index(f["flavor"])
            light, dark = T.series(slot, "light"), T.series(slot, "dark")
        else:
            light, dark = T.tokens("light")["ink_muted"], T.tokens("dark")["ink_muted"]
        out[f["flavor"]] = {"flavor": f["flavor"], "flavor_label": f["label"],
                            "is_seasonal": f["is_seasonal"],
                            "color": light, "color_dark": dark}
    return out


COLOR_COLS = ["color", "color_dark"]
CHANNEL_COLS = ["channel", "channel_label"] + COLOR_COLS
FLAVOUR_COLS = ["flavor", "flavor_label", "is_seasonal"] + COLOR_COLS


# ---------------------------------------------------------------- datasets

def kpis(pages):
    """Los indicadores de cabecera de las siete páginas; la portada, marcada."""
    rows = []
    for page in pages:
        tiles = ([(True, page["hero"])] if page.get("hero") else []) \
            + [(False, k) for k in page.get("kpis", [])]
        for position, (is_hero, tile) in enumerate(tiles, start=1):
            start, end = tile["period"]
            rows.append({
                "page": page["slug"], "page_title": page["title"],
                "is_cover": page["slug"] == "index", "is_hero": is_hero,
                "position": position, "kpi_id": tile["id"],
                "label": _cap(tile["label"]), "value": tile["raw"], "unit": tile["unit"],
                "value_display": tile["value"],
                "period_start": start, "period_end": end,
                "period_label": _period_label(start, end),
                "note": tile.get("note")})
    cols = ["page", "page_title", "is_cover", "is_hero", "position", "kpi_id", "label",
            "value", "unit", "value_display", "period_start", "period_end",
            "period_label", "note"]
    return write("kpis", cols, rows)


def recommendations(pages):
    rows = []
    for page in pages:
        for position, step in enumerate(page.get("actions", {}).get("steps", []), start=1):
            rows.append({
                "rec_id": step["id"], "page": page["slug"], "page_title": page["title"],
                "position": position, "is_cover_plan": page["slug"] == "index",
                "same_as": step.get("same_as"),
                "action": _plain(step["do"]), "why": _plain(step["why"]),
                "impact": _plain(step["impact"]), "owner": step["owner"],
                "effort": step["effort"], "measure": _plain(step["measure"]),
                "metric_value": step["metric"], "metric_unit": step["metric_unit"],
                "metric_label": _cap(step["metric_label"])})
    ids = [r["rec_id"] for r in rows]
    assert len(ids) == len(set(ids)), "rec_id repetido"
    assert all(r["same_as"] in ids for r in rows if r["same_as"]), "same_as sin destino"
    cols = ["rec_id", "page", "page_title", "position", "is_cover_plan", "same_as",
            "action", "why", "impact", "owner", "effort", "measure",
            "metric_value", "metric_unit", "metric_label"]
    return write("recommendations", cols, rows)


def subscribers_monthly(subs):
    s = subs["series"]
    outliers = {o["date"]: o["sigmas"] for o in subs["outlier_months"]}
    rows = [{"month": net["date"],
             "active_net_of_pauses": net["suscriptores"],
             "paused_subscriptions": paused["suscripciones"],
             "active_eom": eom["suscriptores"],
             "signups": new["altas"],
             "is_outlier": net["date"] in outliers,
             "outlier_sigmas": outliers.get(net["date"])}
            for net, paused, eom, new in zip(s["active_net"], s["paused"],
                                             s["active_eom"], s["signups"])]
    cols = ["month", "active_net_of_pauses", "paused_subscriptions", "active_eom",
            "signups", "is_outlier", "outlier_sigmas"]
    return write("subscribers_monthly", cols, rows)


def revenue_by_channel(ing):
    gap_month = ing["payment_gap"]["detected_month"]
    share = {r["date"]: r for r in ing["channel_mix"]["by_month_pct"]}
    rows = []
    for key in T.REVENUE_CHANNEL_SLOT:
        for r in ing["series"][key]:
            rows.append({"month": r["date"], **revenue_channel(key),
                         "revenue_eur": r["eur"], "share_pct": share[r["date"]][key],
                         "is_payment_gap_month": r["date"] == gap_month})
    rows.sort(key=lambda r: r["month"])
    cols = ["month"] + CHANNEL_COLS + ["revenue_eur", "share_pct", "is_payment_gap_month"]
    return write("revenue_by_channel", cols, rows)


def payment_gap(ing):
    """
    El hueco de cobros no se ve en el ingreso devengado, que es la medida de
    `revenue_by_channel`: sólo aparece en la caja dividida por el MRR contratado.
    """
    g = ing["payment_gap"]
    rows = [{"month": r["date"], "cash_ratio": r["ratio"],
             "cash_ratio_median": g["cash_ratio_median"],
             "collected_per_active_eur": c["eur"], "mrr_per_active_eur": m["eur"],
             "is_payment_gap_month": r["date"] == g["detected_month"]}
            for r, c, m in zip(g["cash_ratio"], g["collected_per_active"], g["mrr_per_active"])]
    cols = ["month", "cash_ratio", "cash_ratio_median", "collected_per_active_eur",
            "mrr_per_active_eur", "is_payment_gap_month"]
    return write("payment_gap", cols, rows)


def capsule_demand(cap, flavours):
    """
    `by_flavor` ya lleva la demanda corregida (las ventanas de rotura imputadas);
    `by_flavor_censored` guarda lo observado de los cuatro sabores afectados.
    """
    rows = []
    for key, series in cap["series"]["by_flavor"].items():
        observed = {r["date"]: r["units"]
                    for r in cap["series"]["by_flavor_censored"].get(key, series)}
        for r in series:
            lost = r["units"] - observed[r["date"]]
            rows.append({"month": r["date"], **flavours[key], "units": r["units"],
                         "units_observed": observed[r["date"]], "units_lost": lost,
                         "has_stockout": lost > 0})
    rows.sort(key=lambda r: (r["month"], r["flavor"]))
    cols = ["month"] + FLAVOUR_COLS + ["units", "units_observed", "units_lost",
                                       "has_stockout"]
    return write("capsule_demand", cols, rows)


def capsule_seasonality(cap, flavours):
    rows = []
    for r in cap["seasonal_profile"]["by_month"]:
        for key in flavours:
            rows.append({"month_of_year": r["month"], "month_label": T.MONTHS_ES[r["month"] - 1],
                         **flavours[key], "demand_index": r[key],
                         "demand_index_log2": math.log2(r[key])})
    cols = ["month_of_year", "month_label"] + FLAVOUR_COLS + ["demand_index",
                                                               "demand_index_log2"]
    return write("capsule_seasonality", cols, rows)


def stockouts(cap, flavours):
    cens = cap["censored_demand"]
    price = {f["flavor"]: f["precio_medio_eur"] for f in cens["lost_demand"]["by_flavor"]}
    check = {(v["flavor"], v["start"]): v for v in cens["validation"]["by_window"]}
    rows = []
    for w in sorted(cens["windows"], key=lambda w: w["start"]):
        v = check[(w["flavor"], w["start"])]
        rows.append({"stockout_id": f"{w['flavor']}_{w['start']}", **flavours[w["flavor"]],
                     "start_date": w["start"], "end_date": w["end"], "days": w["days"],
                     "lost_units": w["expected_units"],
                     "avg_price_eur": price[w["flavor"]],
                     "lost_eur": w["expected_units"] * price[w["flavor"]],
                     "club_ratio": w["club_ratio"],
                     "lines_estimated": v["lineas_estimadas"], "lines_real": v["lineas_reales"],
                     "estimation_error_pct": v["error_pct"]})
    total = sum(r["lost_eur"] for r in rows)
    assert abs(total - cens["lost_demand"]["eur"]) < 0.01, (total, cens["lost_demand"]["eur"])
    cols = ["stockout_id"] + FLAVOUR_COLS + [
        "start_date", "end_date", "days", "lost_units", "avg_price_eur", "lost_eur",
        "club_ratio", "lines_estimated", "lines_real", "estimation_error_pct"]
    return write("stockouts", cols, rows)


def retention_by_channel(coh):
    ltv = coh["ltv_by_channel"]
    reliable = {c["canal"]: c["ultima_edad_fiable"] for c in ltv["channels"]}
    rows = []
    for key in reliable:
        for r in ltv["retention_by_channel"]:
            rows.append({"age_months": r["age"], **channel(key),
                         "retention_pct": r[key],
                         "is_extrapolated": r["age"] > reliable[key]})
    cols = ["age_months"] + CHANNEL_COLS + ["retention_pct", "is_extrapolated"]
    return write("retention_by_channel", cols, rows)


def cac_ltv(cx, coh):
    subs = {c["canal"]: c["suscripciones"] for c in coh["ltv_by_channel"]["channels"]}
    breakeven = cx["plausibility"]["breakeven_margin_pct"]
    base = {"target_ratio": cx["meta"]["healthy_ratio"],
            "target_payback_months": cx["meta"]["payback_target_months"]}
    rows = []
    for r in cx["crossover"]:
        rows.append({**channel(r["channel"]), "is_priced": True,
                     "cac_loaded_eur": r["cac_loaded_eur"],
                     "cac_attributed_eur": r["cac_attributed_eur"],
                     "ltv_projected_eur": r["ltv_projected_eur"],
                     "ltv_observed_mature_eur": r["ltv_observed_mature_eur"],
                     "ratio": r["ratio"], "payback_months": r["payback_months"],
                     "arpu_month_eur": r["arpu_month_eur"],
                     "expected_months": r["expected_months"],
                     "retention_12m_pct": r["retention_12m_pct"],
                     "subscriptions": subs[r["channel"]],
                     "conversions_attributed": r["conversions"],
                     "breakeven_margin_pct": breakeven[r["channel"]],
                     "verdict": _cap(r["verdict"]), **base})
    for r in cx["unpriced_channels"]:
        rows.append({**channel(r["channel"]), "is_priced": False,
                     "ltv_projected_eur": r["ltv_projected_eur"],
                     "retention_12m_pct": r["retention_12m_pct"],
                     "subscriptions": r["subscriptions"],
                     "unpriced_reason": r["reason"], **base})
    cols = CHANNEL_COLS + [
        "is_priced", "cac_loaded_eur", "cac_attributed_eur", "ltv_projected_eur",
        "ltv_observed_mature_eur", "ratio", "payback_months", "arpu_month_eur",
        "expected_months", "retention_12m_pct", "subscriptions", "conversions_attributed",
        "breakeven_margin_pct", "verdict", "unpriced_reason", "target_ratio",
        "target_payback_months"]
    return write("cac_ltv", cols, rows)


# Las cuatro combinaciones metodológicas de la página 7. Las claves del JSON ya
# son etiquetas; aquí se les da un id estable.
SCENARIO_ID = {"cargado × proyectado": "loaded_projected",
               "reparto × proyectado": "attributed_projected",
               "cargado × obs. maduras": "loaded_observed_mature",
               "reparto × obs. maduras": "attributed_observed_mature"}


def cac_ltv_scenarios(cx):
    """
    Las dos sensibilidades del cruce, en el mismo grano (canal × escenario):
    las cuatro combinaciones de método, que mueven el podio, y el margen bruto
    supuesto, que devuelve los ratios a un rango creíble sin cambiar el orden.
    """
    ranks = {r["channel"]: r for r in cx["robustness"]["ranks"]}
    rows = []
    for r in cx["robustness"]["ratios"]:
        for label, sid in SCENARIO_ID.items():
            rows.append({"scenario_group": "method", "scenario_id": sid,
                         "scenario_label": _cap(label), **channel(r["channel"]),
                         "ratio": r[label], "rank": ranks[r["channel"]][label],
                         "is_reference": sid == "loaded_projected"})
    for m in cx["plausibility"]["ratio_by_margin"]:
        for key in (k for k in m if k != "margin_pct"):
            rows.append({"scenario_group": "margin",
                         "scenario_id": f"margin_{m['margin_pct']:g}",
                         "scenario_label": f"Margen del {m['margin_pct']:g}%",
                         **channel(key), "margin_pct": m["margin_pct"], "ratio": m[key],
                         "is_reference": False})
    cols = ["scenario_group", "scenario_id", "scenario_label"] + CHANNEL_COLS + [
        "ratio", "rank", "margin_pct", "is_reference"]
    return write("cac_ltv_scenarios", cols, rows)


def attribution_by_model(att):
    paid = {c["channel"]: c["is_paid"] for c in att["channels"]}
    cac = {r["channel"]: r for r in att["cac"]["by_channel"]}
    spread = att["models"]["spread_by_channel_pp"]
    rows = []
    for r in att["models"]["credit_pct"]:
        for model, label in T.MODEL_LABEL.items():
            rows.append({**channel(r["channel"]), "model": model, "model_label": label,
                         "credit_pct": r[model],
                         # sin coste de medios no hay CAC: un 0 invitaría a leerlo gratis
                         "cac_eur": cac[r["channel"]][model] if paid[r["channel"]] else None,
                         "is_paid": paid[r["channel"]],
                         "credit_spread_pp": spread[r["channel"]]})
    cols = CHANNEL_COLS + ["model", "model_label", "credit_pct", "cac_eur", "is_paid",
                           "credit_spread_pp"]
    return write("attribution_by_model", cols, rows)


def attribution_gap(att):
    """El gap por canal: lo que pesa el gasto sin cliente y cuánto encarece el CAC."""
    orphan = {r["channel"]: r for r in att["attribution_gap"]["by_channel"]}
    cac = {r["channel"]: r for r in att["cac"]["by_channel"]}
    rows = []
    for c in att["channels"]:
        key, o = c["channel"], orphan[c["channel"]]
        row = {**channel(key), "is_paid": c["is_paid"], "touchpoints": c["touchpoints"],
               "orphan_touchpoints": o["touchpoints"], "orphan_touchpoints_pct": o["pct_del_canal"],
               "attributable_cost_eur": c["attributable_cost_eur"],
               "orphan_cost_eur": c["orphan_cost_eur"], "total_cost_eur": c["total_cost_eur"]}
        if c["is_paid"]:
            attributed, loaded = cac[key]["markov"], cac[key]["cac_cargado_markov"]
            row.update(cac_attributed_eur=attributed, cac_loaded_eur=loaded,
                       cac_uplift_pct=(loaded / attributed - 1) * 100)
        rows.append(row)
    cols = CHANNEL_COLS + [
        "is_paid", "touchpoints", "orphan_touchpoints", "orphan_touchpoints_pct",
        "attributable_cost_eur", "orphan_cost_eur", "total_cost_eur",
        "cac_attributed_eur", "cac_loaded_eur", "cac_uplift_pct"]
    return write("attribution_gap", cols, rows)


# ---------------------------------------------------------------- main

def _no_figure(*args, **kwargs):
    """El dashboard no necesita las figuras de Plotly del informe."""
    return None


def main():
    data = B.load_data()
    pages = content.build(data, B.FORMATTERS, _no_figure, B.table, enrich=False)
    cap, flavours = data["capsulas"], flavour_lookup(data["capsulas"])

    OUT.mkdir(parents=True, exist_ok=True)
    written = [
        kpis(pages),
        subscribers_monthly(data["suscriptores"]),
        revenue_by_channel(data["ingresos"]),
        payment_gap(data["ingresos"]),
        capsule_demand(cap, flavours),
        capsule_seasonality(cap, flavours),
        stockouts(cap, flavours),
        retention_by_channel(data["cohorts_rfm"]),
        cac_ltv(data["cac_ltv"], data["cohorts_rfm"]),
        cac_ltv_scenarios(data["cac_ltv"]),
        attribution_by_model(data["attribution"]),
        attribution_gap(data["attribution"]),
        recommendations(pages),
    ]
    # Un dataset que ya no se exporta no puede quedarse publicado con datos viejos.
    current = {f"{name}.csv" for name, _, _ in written}
    for stale in OUT.glob("*.csv"):
        if stale.name not in current:
            stale.unlink()
            print(f"  borrado {stale.name}: ya no se exporta")

    print(f"datos del dashboard en {OUT.relative_to(ROOT)}/")
    for name, n, size in written:
        print(f"  {name + '.csv':26s} {n:6d} filas {size / 1024:8.1f} KB")


if __name__ == "__main__":
    main()
