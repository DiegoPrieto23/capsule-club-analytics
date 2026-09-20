"""
Capsule Club Analytics — constructores de figuras del informe.

Cada función devuelve un `go.Figure` para un modo (`light` o `dark`); el
constructor la llama dos veces y guarda las dos especificaciones en el HTML, de
modo que cambiar de tema no sea un volteo de colores sino elegir la versión ya
construida con los pasos de la paleta de ese fondo.

Reglas que se respetan en todas ellas, de la skill `dataviz`:

  - nunca dos ejes verticales en un mismo panel: si hay dos magnitudes, hay dos
    paneles (`censoring_panels` es el caso claro);
  - con dos o más series siempre hay leyenda, y con cuatro o menos además
    etiqueta directa, para que la identidad no dependa sólo del color;
  - cuando la historia es "una serie importa y el resto es contexto" se usa
    énfasis (una en color, el resto en gris) en vez de repartir ocho colores;
  - las categorías nominales no llevan rampa de valor: un color por serie;
  - rejilla sólida de un tono sobre el fondo, marcas finas, sin borde alrededor
    de las marcas.
"""

from __future__ import annotations

import plotly.graph_objects as go

import theme as T

LINE = 2          # grosor de línea estándar
MARKER = 8        # tamaño mínimo de marcador


# ---------------------------------------------------------------- utilidades

def _dates(rows, key="date"):
    return [r[key] for r in rows]


def _vals(rows, key):
    return [r[key] for r in rows]


def _eur(value, decimals=0):
    return f"{value:,.{decimals}f} €".replace(",", " ")


def _num(value, decimals=0):
    return f"{value:,.{decimals}f}".replace(",", " ")


def _es(text: str) -> str:
    """Coma decimal. Plotly aplica `separators` a lo que formatea él, no a esto."""
    return text.replace(".", ",")


def _fig(mode, height=380, **layout_kw):
    return go.Figure(layout=T.layout(mode, height=height, **layout_kw))


def _endpoint_label(fig, x, y, text, color, mode, dy=0):
    """Etiqueta directa en el extremo de una serie, en tinta y no en el color de la serie."""
    fig.add_annotation(x=x, y=y, text=text, showarrow=False, xanchor="left",
                       xshift=8, yshift=dy, font=dict(size=11, color=T.tokens(mode)["ink"]),
                       bgcolor="rgba(0,0,0,0)")


# ---------------------------------------------------------------- portada

def revenue_stack(ingresos, mode):
    """Part-to-whole en el tiempo: área apilada, cuatro series categóricas."""
    fig = _fig(mode, height=400)
    order = ["suscripcion", "online", "tienda", "maquina"]
    labels = {"suscripcion": "Suscripción", "online": "Tienda online",
              "tienda": "Boutique", "maquina": "Máquinas"}
    for slot, key in enumerate(order):
        rows = ingresos["series"][key]
        fig.add_trace(go.Scatter(
            x=_dates(rows), y=_vals(rows, "eur"), name=labels[key],
            mode="lines", stackgroup="uno",
            line=dict(width=0.5, color=T.series(slot, mode)),
            fillcolor=T.series(slot, mode),
            hovertemplate="%{y:,.0f} €<extra>" + labels[key] + "</extra>"))
    fig.update_layout(yaxis_title="€ por mes")
    return fig


def cac_ltv_scatter(cac_ltv, mode):
    """
    El cruce de cierre. Es una forma de "todos los pares", así que sólo entran
    los cuatro canales con coste y con la combinación de ranuras que valida.
    """
    rows = cac_ltv["crossover"]
    t = T.tokens(mode)
    fig = _fig(mode, height=460, hovermode="closest", showlegend=False)
    x_max = max(r["cac_loaded_eur"] for r in rows) * 1.3
    y_max = max(r["ltv_projected_eur"] for r in rows) * 1.2
    for ratio in (3, 10, 30):
        fig.add_trace(go.Scatter(
            x=[0, x_max], y=[0, x_max * ratio], mode="lines", hoverinfo="skip",
            line=dict(color=t["grid"], width=1)))
        if x_max * ratio > y_max:
            fig.add_annotation(x=y_max / ratio, y=y_max, text=f"{ratio}x", showarrow=False,
                               yshift=9, font=dict(size=10, color=t["ink_muted"]))
        else:
            fig.add_annotation(x=x_max, y=x_max * ratio, text=f"{ratio}x", showarrow=False,
                               xshift=-6, yshift=9, font=dict(size=10, color=t["ink_muted"]))
    # Con cuatro burbujas la etiqueta encima colisiona cuando dos canales tienen
    # un CAC parecido: la de abajo se coloca debajo. Y no vale `markers+text`,
    # porque su desplazamiento no conoce el radio de la burbuja y la etiqueta
    # acaba dentro del círculo: hay que apartarla a mano en píxeles.
    def goes_below(row):
        near = [o for o in rows
                if o is not row
                and abs(o["cac_loaded_eur"] - row["cac_loaded_eur"])
                < 0.18 * max(r["cac_loaded_eur"] for r in rows)]
        return any(o["ltv_projected_eur"] > row["ltv_projected_eur"] for o in near)

    for row in rows:
        color = T.channel_color(row["channel"], mode)
        size = max(MARKER * 2, (row["conversions"] ** 0.5) * 1.5)
        below = goes_below(row)
        fig.add_annotation(
            x=row["cac_loaded_eur"], y=row["ltv_projected_eur"], text=row["label"],
            showarrow=False, yshift=(-1 if below else 1) * (size / 2 + 11),
            yanchor="top" if below else "bottom",
            font=dict(size=12, color=t["ink"]))
        fig.add_trace(go.Scatter(
            x=[row["cac_loaded_eur"]], y=[row["ltv_projected_eur"]],
            mode="markers",
            marker=dict(size=size, color=color, line=dict(width=2, color=t["surface"])),
            hovertemplate=(f"<b>{row['label']}</b><br>CAC {row['cac_loaded_eur']:.2f} €"
                           f"<br>LTV {row['ltv_projected_eur']:.0f} €"
                           f"<br>ratio {row['ratio']:.1f}x"
                           f"<br>{row['conversions']:.0f} conversiones<extra></extra>")))
    fig.update_layout(xaxis_title="CAC cargado (€ por suscriptor)",
                      yaxis_title="LTV proyectado a 36 meses (€)",
                      xaxis=dict(range=[0, x_max]), yaxis=dict(range=[0, y_max]))
    return fig


# ---------------------------------------------------------------- suscriptores

def subscribers_forecast(subs, mode):
    """Histórico y previsión: una serie, banda de incertidumbre, sin leyenda de color."""
    t = T.tokens(mode)
    hist = subs["series"]["active_net"]
    fc = subs["forecast"]
    months = fc["months"]
    # El notebook 01 publica dos modelos; el de cohortes es el que la pagina defiende.
    model = fc["models"].get("cohortes") or next(iter(fc["models"].values()))
    fig = _fig(mode, height=400)
    fig.add_trace(go.Scatter(
        x=months + months[::-1],
        y=model["yhat_upper"] + model["yhat_lower"][::-1],
        fill="toself", fillcolor=t["band"], line=dict(width=0), hoverinfo="skip",
        name="Banda 80%"))
    fig.add_trace(go.Scatter(
        x=_dates(hist), y=_vals(hist, "suscriptores"), name="Histórico", mode="lines",
        line=dict(color=T.series(0, mode), width=LINE + 0.5),
        hovertemplate="%{y:,.0f} suscriptores<extra></extra>"))
    bridge_x = [hist[-1]["date"]] + months
    bridge_y = [hist[-1]["suscriptores"]] + model["yhat"]
    fig.add_trace(go.Scatter(
        x=bridge_x, y=bridge_y, name="Previsión", mode="lines+markers",
        line=dict(color=T.series(0, mode), width=LINE, dash="dash"),
        marker=dict(size=MARKER),
        hovertemplate="%{y:,.0f} previstos<extra></extra>"))
    _endpoint_label(fig, months[-1], model["yhat"][-1], _num(model["yhat"][-1]),
                    T.series(0, mode), mode)
    fig.update_layout(yaxis_title="suscriptores activos")
    return fig


def signup_weekday(subs, mode):
    """Perfil semanal del flujo de altas. Una serie nominal: un solo color."""
    rows = subs["weekly_seasonality"]["by_weekday"]
    t = T.tokens(mode)
    fig = _fig(mode, height=320, showlegend=False, hovermode="closest")
    values = [r["mstl_component"] for r in rows]
    fig.add_trace(go.Bar(
        x=[r["label"] for r in rows], y=values,
        marker=dict(color=T.series(0, mode), line=dict(width=0)),
        text=[_es(f"{v:+.1f}") for v in values], textposition="outside",
        textfont=dict(size=11, color=t["ink_secondary"]),
        hovertemplate="%{x}: %{y:+.2f} altas<extra></extra>"))
    fig.add_hline(y=0, line=dict(color=t["grid"], width=1))
    fig.update_layout(yaxis_title="altas sobre la media del día")
    return fig


def retention_curve(cohorts, mode):
    """Con descuento frente a sin descuento: dos series, leyenda y etiqueta directa."""
    t = T.tokens(mode)
    fig = _fig(mode, height=400)
    for slot, (key, label) in enumerate((("without_discount", "Sin descuento"),
                                         ("with_discount", "Con descuento"))):
        rows = [r for r in cohorts["retention"][key] if r["age"] <= 24]
        color = T.series(0 if slot == 0 else 1, mode)
        fig.add_trace(go.Scatter(
            x=[r["age"] for r in rows], y=[r["retention"] * 100 for r in rows],
            name=label, mode="lines", line=dict(color=color, width=LINE + 0.5),
            hovertemplate="mes %{x}: %{y:.1f}%<extra>" + label + "</extra>"))
        _endpoint_label(fig, rows[-1]["age"], rows[-1]["retention"] * 100,
                        f"{rows[-1]['retention'] * 100:.0f}%", color, mode)
    fig.update_layout(xaxis_title="meses desde el alta", yaxis_title="% retenido",
                      yaxis=dict(range=[0, 102]))
    return fig


# ---------------------------------------------------------------- cápsulas

def flavour_emphasis(capsulas, mode):
    """
    Doce sabores no son doce colores. La historia es "dos de temporada se
    comportan distinto", así que van en color y los diez de base en gris.
    """
    t = T.tokens(mode)
    fig = _fig(mode, height=420)
    seasonal = [f["flavor"] for f in capsulas["flavors"] if f["is_seasonal"]]
    base = [f["flavor"] for f in capsulas["flavors"] if not f["is_seasonal"]]
    for i, flavour in enumerate(base):
        rows = capsulas["series"]["by_flavor"][flavour]
        fig.add_trace(go.Scatter(
            x=_dates(rows), y=_vals(rows, "units"), mode="lines",
            line=dict(color=t["ink_muted"], width=1),
            opacity=0.45, showlegend=i == 0,
            name="Diez sabores de base",
            hovertemplate="%{y:,.0f} unidades<extra>base</extra>"))
    for slot, flavour in enumerate(seasonal):
        rows = capsulas["series"]["by_flavor"][flavour]
        label = next(f["label"] for f in capsulas["flavors"] if f["flavor"] == flavour)
        color = T.series(slot, mode)
        fig.add_trace(go.Scatter(
            x=_dates(rows), y=_vals(rows, "units"), name=label, mode="lines",
            line=dict(color=color, width=LINE + 0.5),
            hovertemplate="%{y:,.0f} unidades<extra>" + label + "</extra>"))
    fig.update_layout(yaxis_title="unidades por mes")
    return fig


def seasonal_heatmap(capsulas, mode):
    """
    Índice demanda/tendencia. Es una razón, no una diferencia: 0,5 y 2,0 están
    a la misma distancia de 1,0. En escala lineal con el punto medio en 1 el
    brazo de abajo vale 1 y el de arriba 2,5, así que los sabores de base salen
    teñidos de azul estando casi en su tendencia. Se pinta el log2 del índice,
    que deja el gris neutro donde corresponde, y la barra se etiqueta en las
    unidades originales para que el lector no tenga que pensar en logaritmos.
    """
    import math
    rows = capsulas["seasonal_profile"]["by_month"]
    z, y = [], []
    for f in capsulas["flavors"]:
        series = [rows[m].get(f["flavor"]) for m in range(12)]
        if all(v is None for v in series):
            continue
        z.append([None if v is None else math.log2(max(v, 0.05)) for v in series])
        y.append(f["label"])
    ticks = [0.25, 0.5, 1, 2, 4]
    fig = _fig(mode, height=430, hovermode="closest", showlegend=False,
               margin={"l": 150, "r": 24, "t": 16, "b": 48})
    fig.add_trace(go.Heatmap(
        z=z, x=T.MONTHS_ES, y=y, colorscale=T.diverging(mode),
        zmid=0, zmin=-2, zmax=2, xgap=2, ygap=2,
        customdata=[[None if v is None else 2 ** v for v in row] for row in z],
        colorbar=dict(title=dict(text="índice", font=dict(size=11)), thickness=12,
                      tickvals=[math.log2(t) for t in ticks],
                      ticktext=[_es(f"{t:g}×") for t in ticks], tickfont=dict(size=10)),
        hovertemplate="%{y} · %{x}: %{customdata:.2f}× la tendencia<extra></extra>"))
    return fig


def stockout_detail(capsulas, mode, flavour="decaf_vanilla"):
    """Dos canales, dos series categóricas, con las ventanas marcadas."""
    t = T.tokens(mode)
    detail = [d for d in capsulas["censored_demand"]["daily_detail"]
              if d["flavor"] == flavour]
    fig = _fig(mode, height=360)
    window = detail[-1]
    fig.add_trace(go.Scatter(
        x=_dates(window["shop_units_observed"]), y=_vals(window["shop_units_observed"], "units"),
        name="Tienda (observado)", mode="lines",
        line=dict(color=T.series(0, mode), width=LINE),
        hovertemplate="%{y:.0f} unidades<extra>tienda</extra>"))
    fig.add_trace(go.Scatter(
        x=_dates(window["club_units"]), y=_vals(window["club_units"], "units"),
        name="Club (no se censura)", mode="lines",
        line=dict(color=T.series(2, mode), width=LINE),
        hovertemplate="%{y:.0f} unidades<extra>club</extra>"))
    fig.add_vrect(x0=window["start"], x1=window["end"], fillcolor=T.series(1, mode),
                  opacity=0.14, line_width=0,
                  annotation_text="rotura de stock", annotation_position="top left",
                  annotation=dict(font=dict(size=11, color=t["ink_secondary"])))
    fig.update_layout(yaxis_title="unidades por día")
    return fig


# ---------------------------------------------------------------- cohortes

def cohort_matrix(cohorts, mode):
    """Magnitud sobre una rejilla: rampa secuencial de un solo tono."""
    rows = cohorts["cohort_matrix"]["retention_pct"]
    ages = [str(a) for a in range(0, 25)]
    z = [[row.get(a) for a in ages] for row in rows]
    y = [row["cohort"][:7] for row in rows]
    fig = _fig(mode, height=560, hovermode="closest", showlegend=False,
               margin={"l": 74, "r": 24, "t": 16, "b": 48})
    fig.add_trace(go.Heatmap(
        z=z, x=[int(a) for a in ages], y=y, colorscale=T.sequential(mode),
        xgap=1, ygap=1, zmin=0, zmax=100,
        colorbar=dict(title=dict(text="% vivo", font=dict(size=11)), thickness=12,
                      tickfont=dict(size=10)),
        hovertemplate="cohorte %{y} · mes %{x}: %{z:.0f}%<extra></extra>"))
    fig.update_layout(xaxis_title="meses desde el alta", yaxis_title="cohorte de alta")
    return fig


def logo_vs_revenue(cohorts, mode):
    """
    Tres curvas sobre la misma base; la distancia entre ellas es la métrica.

    El eje arranca en 40 y no en 0 a propósito: el hueco que la página analiza
    son 2-4 puntos y desde cero no se ve ninguno. La escala completa está en la
    tabla y el gráfico de al lado mide el hueco en sus propias unidades, así
    que truncar aquí no exagera nada que no se pueda comprobar.

    Las curvas de clientes y de tarifa se solapan tanto que sólo se etiqueta
    una: que sean indistinguibles es justo la conclusión.
    """
    rows = cohorts["plan_changes"]["logo_vs_revenue_retention"]
    fig = _fig(mode, height=340, margin={"l": 62, "r": 88, "t": 16, "b": 46})
    spec = (("logo", "Clientes que siguen", 0, True),
            ("mrr_tarifa", "Cuota contratada", 2, False),
            ("mrr_cobrable", "Cuota que se cobra", 1, True))
    for key, label, slot, labelled in spec:
        color = T.series(slot, mode)
        fig.add_trace(go.Scatter(
            x=[r["months_since_start"] for r in rows], y=[r[key] for r in rows],
            name=label, mode="lines", line=dict(color=color, width=LINE + 0.5),
            hovertemplate="mes %{x}: %{y:.1f}%<extra>" + label + "</extra>"))
        if labelled:
            last = rows[-1]
            _endpoint_label(fig, last["months_since_start"], last[key],
                            f"{last[key]:.0f}%", color, mode,
                            dy=9 if key == "logo" else -9)
    fig.update_layout(xaxis_title="meses desde el alta", yaxis_title="% retenido",
                      yaxis=dict(range=[40, 102]))
    return fig


def gap_decomposition(cohorts, mode):
    """
    El hueco entre clientes retenidos e ingreso retenido, repartido entre sus
    dos causas posibles. Enseñar que el mix de plan *se mueve* no demostraba que
    *pesara*: medido en puntos, no pesa nada y la pausa se lo lleva entero.
    """
    rows = cohorts["plan_changes"]["logo_vs_revenue_retention"][1:]
    x = [r["months_since_start"] for r in rows]
    fig = _fig(mode, height=340, margin={"l": 62, "r": 88, "t": 16, "b": 46})
    for key, label, slot in (("efecto_pausa_pp", "Suscripciones en pausa", 1),
                             ("efecto_mix_pp", "Cambio de plan", 2)):
        fig.add_trace(go.Bar(
            x=x, y=[r[key] for r in rows], name=label,
            marker=dict(color=T.series(slot, mode),
                        line=dict(width=2, color=T.tokens(mode)["surface"])),
            hovertemplate="mes %{x}: %{y:.2f} pp<extra>" + label + "</extra>"))
    fig.add_trace(go.Scatter(
        x=x, y=[r["gap_total_pp"] for r in rows], name="Hueco total",
        mode="lines", line=dict(color=T.tokens(mode)["ink_secondary"],
                                width=LINE, dash="dot"),
        hovertemplate="mes %{x}: %{y:.2f} pp<extra>Hueco total</extra>"))
    last = rows[-1]
    _endpoint_label(fig, last["months_since_start"], last["gap_total_pp"],
                    _es(f"{last['gap_total_pp']:.1f}") + " pp", T.tokens(mode)["ink"], mode)
    fig.update_layout(barmode="relative", bargap=0.25,
                      xaxis_title="meses desde el alta",
                      yaxis_title="puntos de retención perdidos")
    return fig


def rfm_segments(cohorts, mode):
    """
    Ocho segmentos nominales: ni rampa de valor ni ocho colores. Dos medidas
    comparables en porcentaje, dos ranuras categóricas.
    """
    rows = sorted(cohorts["rfm"]["segments"], key=lambda r: -r["pct_ingreso"])
    t = T.tokens(mode)
    fig = _fig(mode, height=420, hovermode="closest",
               margin={"l": 170, "r": 40, "t": 16, "b": 48})
    fig.add_trace(go.Bar(
        y=[r["segmento"] for r in rows], x=[r["pct_clientes"] for r in rows],
        name="% de clientes", orientation="h",
        marker=dict(color=t["ink_muted"], line=dict(width=0)),
        hovertemplate="%{y}: %{x:.1f}% de los clientes<extra></extra>"))
    fig.add_trace(go.Bar(
        y=[r["segmento"] for r in rows], x=[r["pct_ingreso"] for r in rows],
        name="% del ingreso de tienda", orientation="h",
        marker=dict(color=T.series(0, mode), line=dict(width=0)),
        hovertemplate="%{y}: %{x:.1f}% del ingreso<extra></extra>"))
    fig.update_layout(barmode="group", bargap=0.24, bargroupgap=0.12,
                      xaxis_title="%", yaxis=dict(autorange="reversed"))
    return fig


# ---------------------------------------------------------------- atribución

def censoring_panels(attribution, mode):
    """
    Dos magnitudes de escala distinta: dos paneles, nunca dos ejes verticales.
    Un eje doble aquí inventaría una relación entre huella y coste por alta.
    """
    from plotly.subplots import make_subplots
    rows = attribution["censoring"]["apparent_cac_by_month"]
    t = T.tokens(mode)
    cutoff = attribution["censoring"]["cutoff"]
    fig = make_subplots(rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.09,
                        subplot_titles=("Touchpoints y altas por mes",
                                        "CAC aparente (€ por alta)"))
    fig.add_trace(go.Bar(
        x=[r["month"] for r in rows], y=[r["touchpoints"] for r in rows],
        name="Touchpoints", marker=dict(color=t["grid"], line=dict(width=0)),
        hovertemplate="%{y:,.0f} touchpoints<extra></extra>"), row=1, col=1)
    fig.add_trace(go.Scatter(
        x=[r["month"] for r in rows], y=[r["signups"] for r in rows],
        name="Altas", mode="lines", line=dict(color=T.series(2, mode), width=LINE),
        hovertemplate="%{y:,.0f} altas<extra></extra>"), row=1, col=1)
    fig.add_trace(go.Scatter(
        x=[r["month"] for r in rows], y=[r["apparent_cac_eur"] for r in rows],
        name="CAC aparente", mode="lines+markers",
        line=dict(color=T.series(1, mode), width=LINE + 0.5), marker=dict(size=MARKER - 2),
        hovertemplate="%{y:.2f} € por alta<extra></extra>"), row=2, col=1)
    fig.update_layout(**T.layout(mode, height=540, hovermode="x unified",
                                 margin={"l": 64, "r": 24, "t": 78, "b": 48},
                                 legend={"y": 1.10}))
    for row in (1, 2):
        fig.add_vrect(x0=cutoff, x1=rows[-1]["month"], fillcolor=T.series(1, mode),
                      opacity=0.10, line_width=0, row=row, col=1)
    # Anclada a la derecha del corte: a la izquierda se salía del lienzo, porque
    # la franja censurada es el último tramo del eje y no queda sitio detrás.
    fig.add_annotation(x=cutoff, y=1.0, yref="paper", text="tramo censurado →",
                       showarrow=False, xanchor="right", xshift=-6,
                       font=dict(size=11, color=t["ink_secondary"]))
    # Sin acotar, el eje se estira hasta enero del año siguiente por el sombreado.
    fig.update_xaxes(range=[rows[0]["month"], rows[-1]["month"]])
    for axis in fig.layout:
        if axis.startswith("xaxis") or axis.startswith("yaxis"):
            fig.layout[axis].update(gridcolor=t["grid"], zeroline=False,
                                    linecolor=t["grid"], tickcolor=t["grid"])
    for note in fig.layout.annotations[:2]:
        note.font = dict(size=12, color=T.tokens(mode)["ink_secondary"])
    return fig


def resolution_by_channel(attribution, mode):
    """Énfasis: un canal es la historia, los demás son el contraste que la prueba."""
    # Se corta en el mismo sitio que el análisis. En el tramo final sólo quedan
    # touchpoints de quien acaba convirtiendo, así que la tasa de resolución se
    # dispara: dibujarla sería enseñar el artefacto que esta página denuncia.
    cutoff = attribution["meta"]["censoring_cutoff"]
    rows = [r for r in attribution["ios_att"]["resolution_by_month"] if r["month"] <= cutoff]
    t = T.tokens(mode)
    window = attribution["ios_att"]["window"]
    fig = _fig(mode, height=400)
    others = ["organic", "podcast_ads", "referral", "influencer_code"]
    for i, channel in enumerate(others):
        fig.add_trace(go.Scatter(
            x=[r["month"] for r in rows], y=[r.get(channel) for r in rows],
            mode="lines", line=dict(color=t["ink_muted"], width=1), opacity=0.5,
            name="Resto de canales", showlegend=i == 0,
            hovertemplate="%{y:.1f}%<extra>" + T.CHANNEL_LABEL[channel] + "</extra>"))
    fig.add_trace(go.Scatter(
        x=[r["month"] for r in rows], y=[r.get("paid_social") for r in rows],
        name="Paid social", mode="lines",
        line=dict(color=T.channel_color("paid_social", mode), width=LINE + 1),
        hovertemplate="%{y:.1f}%<extra>paid social</extra>"))
    fig.add_vrect(x0=window[0], x1=window[1], fillcolor=T.series(1, mode), opacity=0.12,
                  line_width=0, annotation_text="ventana tipo iOS ATT",
                  annotation_position="top left",
                  annotation=dict(font=dict(size=11, color=t["ink_secondary"])))
    fig.update_layout(yaxis_title="% de touchpoints resueltos")
    return fig


def credit_by_model(attribution, mode):
    """Cuatro modelos sobre cinco canales: el color sigue al canal, no al modelo."""
    rows = attribution["models"]["credit_pct"]
    models = ["first_touch", "last_touch", "linear", "markov"]
    t = T.tokens(mode)
    fig = _fig(mode, height=400, hovermode="closest")
    for row in rows:
        color = T.channel_color(row["channel"], mode)
        fig.add_trace(go.Scatter(
            x=[T.MODEL_LABEL[m] for m in models], y=[row[m] for m in models],
            name=row["label"], mode="lines+markers",
            line=dict(color=color, width=LINE), marker=dict(size=MARKER + 1),
            hovertemplate="%{y:.1f}% del crédito<extra>" + row["label"] + "</extra>"))
        _endpoint_label(fig, T.MODEL_LABEL[models[-1]], row[models[-1]],
                        f"{row[models[-1]]:.0f}%", color, mode)
    fig.update_layout(yaxis_title="% del crédito", margin={"r": 96})
    return fig


def cac_by_channel(attribution, mode):
    """CAC del reparto frente al cargado con el gap: el salto es la historia."""
    rows = sorted(attribution["cac"]["by_channel"], key=lambda r: r["markov"])
    rows = [r for r in rows if r["markov"] is not None and r["markov"] > 0]
    t = T.tokens(mode)
    fig = _fig(mode, height=380, hovermode="closest")
    fig.add_trace(go.Bar(
        x=[r["label"] for r in rows], y=[r["markov"] for r in rows],
        name="CAC del reparto", marker=dict(color=T.series(0, mode), line=dict(width=0)),
        hovertemplate="%{x}: %{y:.2f} €<extra>reparto</extra>"))
    fig.add_trace(go.Scatter(
        x=[r["label"] for r in rows], y=[r["cac_cargado_markov"] for r in rows],
        name="Cargado con el gasto huérfano", mode="markers",
        marker=dict(symbol="diamond", size=MARKER + 5, color=T.series(1, mode),
                    line=dict(width=2, color=t["surface"])),
        hovertemplate="%{x}: %{y:.2f} €<extra>cargado</extra>"))
    fig.update_layout(yaxis_title="€ por conversión")
    return fig


# ---------------------------------------------------------------- cierre

def robustness_lines(cac_ltv, mode):
    """El mismo cruce con las cuatro combinaciones: el color sigue al canal."""
    rows = cac_ltv["robustness"]["ratios"]
    combos = [k for k in rows[0] if k not in ("channel", "label")]
    t = T.tokens(mode)
    fig = _fig(mode, height=400, hovermode="closest")
    for row in rows:
        color = T.channel_color(row["channel"], mode)
        fig.add_trace(go.Scatter(
            x=combos, y=[row[c] for c in combos], name=row["label"],
            mode="lines+markers", line=dict(color=color, width=LINE),
            marker=dict(size=MARKER + 1),
            hovertemplate="%{y:.1f}×<extra>" + row["label"] + "</extra>"))
        _endpoint_label(fig, combos[-1], row[combos[-1]], f"{row[combos[-1]]:.0f}×", color, mode)
    fig.add_hline(y=cac_ltv["meta"]["healthy_ratio"],
                  line=dict(color=t["ink_muted"], width=1),
                  annotation_text="regla del pulgar 3x", annotation_position="bottom left",
                  annotation=dict(font=dict(size=11, color=t["ink_muted"])))
    fig.update_layout(yaxis_title="ratio LTV:CAC", margin={"r": 88})
    return fig


def margin_sensitivity(cac_ltv, mode):
    rows = cac_ltv["plausibility"]["ratio_by_margin"]
    channels = [c["channel"] for c in cac_ltv["crossover"]]
    t = T.tokens(mode)
    fig = _fig(mode, height=380, hovermode="x unified")
    for channel in channels:
        label = next(c["label"] for c in cac_ltv["crossover"] if c["channel"] == channel)
        fig.add_trace(go.Scatter(
            x=[r["margin_pct"] for r in rows], y=[r[channel] for r in rows],
            name=label, mode="lines+markers",
            line=dict(color=T.channel_color(channel, mode), width=LINE),
            marker=dict(size=MARKER),
            hovertemplate="%{y:.1f}×<extra>" + label + "</extra>"))
    fig.add_hline(y=cac_ltv["meta"]["healthy_ratio"],
                  line=dict(color=t["ink_muted"], width=1),
                  annotation_text="umbral 3x", annotation_position="top left",
                  annotation=dict(font=dict(size=11, color=t["ink_muted"])))
    fig.update_layout(xaxis_title="margen bruto supuesto (%)", yaxis_title="ratio LTV:CAC")
    return fig


# ---------------------------------------------------------------- previsión

def _forecast_figure(mode, hist_x, hist_y, months, model, y_title, unit,
                     slot=0, height=380):
    """
    Histórico, previsión y banda, con el mismo aspecto en las tres páginas.

    Una sola serie, así que el color no identifica nada: identifica el *estado*
    —observado frente a previsto— y por eso la previsión es la misma tinta con
    trazo discontinuo, no un segundo color categórico.
    """
    t = T.tokens(mode)
    color = T.series(slot, mode)
    fig = _fig(mode, height=height)
    fig.add_trace(go.Scatter(
        x=list(months) + list(months)[::-1],
        y=list(model["yhat_upper"]) + list(model["yhat_lower"])[::-1],
        fill="toself", fillcolor=t["band"], line=dict(width=0), hoverinfo="skip",
        name="Banda 80%"))
    fig.add_trace(go.Scatter(
        x=hist_x, y=hist_y, name="Observado", mode="lines",
        line=dict(color=color, width=LINE + 0.5),
        hovertemplate="%{y:,.0f} " + unit + "<extra></extra>"))
    fig.add_trace(go.Scatter(
        x=[hist_x[-1]] + list(months), y=[hist_y[-1]] + list(model["yhat"]),
        name="Previsión", mode="lines+markers",
        line=dict(color=color, width=LINE, dash="dash"), marker=dict(size=MARKER),
        hovertemplate="%{y:,.0f} " + unit + " previstos<extra></extra>"))
    _endpoint_label(fig, months[-1], model["yhat"][-1], _num(model["yhat"][-1]), color, mode)
    fig.update_layout(yaxis_title=y_title, margin={"r": 72})
    return fig


def revenue_forecast(ingresos, mode):
    hist = ingresos["series"]["total"]
    fc = ingresos["forecast"]
    return _forecast_figure(mode, _dates(hist), _vals(hist, "eur"), fc["months"],
                            fc["models"]["sarima_airline"], "€ por mes", "€")


def capsule_forecast(capsulas, mode):
    hist = capsulas["series"]["total"]
    fc = capsulas["forecast"]
    return _forecast_figure(mode, _dates(hist), _vals(hist, "units"), fc["months"],
                            fc["total"], "unidades por mes", "unidades")


def backtest_quality(leaderboards, mode):
    """
    Lo que hace creíble una previsión no es la línea, es el error medido fuera
    de muestra. Tres series temporales, cada una contra el suelo de repetir el
    año anterior: es una comparación de magnitud, así que barras horizontales.
    """
    t = T.tokens(mode)
    labels, model_mape, naive_mape = [], [], []
    for label, rows in leaderboards:
        best = min((r for r in rows if r["model"] != "naive_estacional"),
                   key=lambda r: r["mase"])
        naive = next(r for r in rows if r["model"] == "naive_estacional")
        labels.append(label)
        model_mape.append(best["mape"])
        naive_mape.append(naive["mape"])
    fig = _fig(mode, height=330, hovermode="closest",
               margin={"l": 158, "r": 84, "t": 16, "b": 44})
    fig.add_trace(go.Bar(
        y=labels, x=naive_mape, orientation="h", name="Repetir el año anterior",
        marker=dict(color=t["ink_muted"], line=dict(width=0)),
        text=[_es(f"{v:.1f}%") for v in naive_mape], textposition="outside",
        textfont=dict(size=11, color=t["ink_secondary"]),
        hovertemplate="%{y}: %{x:.1f}% de error<extra>naive</extra>"))
    fig.add_trace(go.Bar(
        y=labels, x=model_mape, orientation="h", name="Modelo publicado",
        marker=dict(color=T.series(0, mode), line=dict(width=0)),
        text=[_es(f"{v:.1f}%") for v in model_mape], textposition="outside",
        textfont=dict(size=11, color=t["ink_secondary"]),
        hovertemplate="%{y}: %{x:.1f}% de error<extra>modelo</extra>"))
    # Sin holgura a la derecha, la etiqueta del naive se sale del lienzo.
    fig.update_layout(barmode="group", bargap=0.3, bargroupgap=0.1,
                      xaxis_title="error medio del pronóstico a 6 meses (MAPE, %)",
                      xaxis=dict(range=[0, max(naive_mape) * 1.18]))
    return fig


def gifted_curve(cohorts, mode):
    """Énfasis: la curva regalada es la historia y la normal es la referencia."""
    t = T.tokens(mode)
    fig = _fig(mode, height=340)
    base = [r for r in cohorts["retention"]["base"] if r["age"] <= 18]
    gift = [r for r in cohorts["retention"]["gifted"] if r["age"] <= 18]
    fig.add_trace(go.Scatter(
        x=[r["age"] for r in base], y=[r["retention"] * 100 for r in base],
        name="Suscripción normal", mode="lines",
        line=dict(color=t["ink_muted"], width=LINE),
        hovertemplate="mes %{x}: %{y:.1f}%<extra>normal</extra>"))
    fig.add_trace(go.Scatter(
        x=[r["age"] for r in gift], y=[r["retention"] * 100 for r in gift],
        name="Regalada", mode="lines",
        line=dict(color=T.series(1, mode), width=LINE + 1),
        hovertemplate="mes %{x}: %{y:.1f}%<extra>regalada</extra>"))
    fig.update_layout(xaxis_title="meses desde el alta", yaxis_title="% retenido",
                      yaxis=dict(range=[0, 102]))
    return fig


def cash_ratio(ingresos, mode):
    """Énfasis con una línea de referencia: el mínimo del histórico es el punto."""
    t = T.tokens(mode)
    rows = ingresos["payment_gap"]["cash_ratio"]
    median = ingresos["payment_gap"]["cash_ratio_median"]
    detected = ingresos["payment_gap"]["detected_month"]
    fig = _fig(mode, height=340, showlegend=False)
    fig.add_trace(go.Scatter(
        x=_dates(rows), y=_vals(rows, "ratio"), mode="lines",
        line=dict(color=T.series(0, mode), width=LINE + 0.5),
        hovertemplate="%{y:.3f}<extra>caja / MRR</extra>"))
    # "top left" la pega al eje y la recorta: se ancla dentro del lienzo.
    fig.add_hline(y=median, line=dict(color=t["ink_muted"], width=1),
                  annotation_text=_es(f"mediana {median:.2f}"),
                  annotation_position="top right",
                  annotation=dict(font=dict(size=11, color=t["ink_muted"]), xshift=-4))
    hit = next(r for r in rows if r["date"] == detected)
    fig.add_trace(go.Scatter(
        x=[hit["date"]], y=[hit["ratio"]], mode="markers",
        marker=dict(size=MARKER + 5, color=T.series(1, mode),
                    line=dict(width=2, color=t["surface"])),
        hovertemplate="mínimo del histórico: %{y:.3f}<extra></extra>"))
    fig.add_annotation(x=hit["date"], y=hit["ratio"], text="migración de pasarela",
                       showarrow=True, arrowhead=0, arrowwidth=1,
                       arrowcolor=t["ink_muted"], ax=0, ay=34,
                       font=dict(size=11, color=t["ink"]))
    fig.update_layout(yaxis_title="caja cobrada / MRR contratado")
    return fig


def channel_mix(ingresos, mode):
    """Part-to-whole en el tiempo, en porcentaje: el mix, no el nivel."""
    fig = _fig(mode, height=340)
    order = ["suscripcion", "online", "tienda", "maquina"]
    labels = {"suscripcion": "Suscripción", "online": "Tienda online",
              "tienda": "Boutique", "maquina": "Máquinas"}
    rows = ingresos["channel_mix"]["by_month_pct"]
    for slot, key in enumerate(order):
        fig.add_trace(go.Scatter(
            x=_dates(rows), y=[r[key] for r in rows], name=labels[key],
            mode="lines", stackgroup="uno", groupnorm="percent",
            line=dict(width=0.5, color=T.series(slot, mode)),
            fillcolor=T.series(slot, mode),
            hovertemplate="%{y:.1f}%<extra>" + labels[key] + "</extra>"))
    fig.update_layout(yaxis_title="% del ingreso del mes",
                      yaxis=dict(range=[0, 100]))
    return fig
