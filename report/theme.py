"""
Capsule Club Analytics — tema visual del informe.

Un único sitio donde viven la paleta, los tokens de superficie y el layout de
Plotly, en sus dos modos. El resto del informe se escribe contra *roles*
(`series(1)`, `INK`, `GRID`) y nunca contra un hex suelto.

Sobre la paleta: son las ocho ranuras categóricas de la paleta de referencia de
la skill `dataviz`, con sus pasos de modo oscuro. El orden de ranura **es** el
mecanismo de seguridad para daltonismo, así que no se reordena ni se genera una
novena: pasado el octavo canal se pliega en "Otros" o se facetea.

La asignación canal -> ranura no es estética. Se eligió ejecutando
`scripts/validate_palette.py` sobre todas las combinaciones posibles:

  - los cuatro canales **con coste** (paid social, podcast, influencer, referido)
    aparecen juntos en un diagrama de dispersión, que es un caso `--pairs all`:
    ahí sólo dos combinaciones de cuatro ranuras pasan las seis comprobaciones en
    los dos modos, y se tomó la que conserva el azul para paid social;
  - los cinco canales reales juntos pasan `--pairs adjacent` (barras y líneas) en
    los dos modos;
  - `direct_unknown` no es un canal sino el cajón de lo no resuelto, así que va en
    gris de texto y siempre lleva etiqueta directa.

La combinación por defecto (azul, naranja, aqua, amarillo) **falla**: amarillo y
naranja quedan a ΔE 13,7 en visión normal, por debajo del suelo de 15.
"""

from __future__ import annotations

# --- superficies y tinta -----------------------------------------------------
LIGHT = {
    "surface": "#fcfcfb",
    "surface_sunken": "#f4f4f2",
    "ink": "#0b0b0b",
    "ink_secondary": "#52514e",
    "ink_muted": "#83827c",
    "grid": "#e6e6e3",
    "border": "#e0dfdb",
    "band": "rgba(42,120,214,0.14)",
}
DARK = {
    "surface": "#1a1a19",
    "surface_sunken": "#232321",
    "ink": "#ffffff",
    "ink_secondary": "#c3c2b7",
    "ink_muted": "#8f8e86",
    "grid": "#383835",
    "border": "#383835",
    "band": "rgba(57,135,229,0.20)",
}

# --- ranuras categóricas (orden fijo, no se cicla) ---------------------------
SLOTS_LIGHT = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100",
               "#e87ba4", "#008300", "#4a3aa7", "#e34948"]
SLOTS_DARK = ["#3987e5", "#d95926", "#199e70", "#c98500",
              "#d55181", "#008300", "#9085e9", "#e66767"]

# --- rampa secuencial (azul) y par divergente (azul <-> rojo) ---------------
SEQUENTIAL_LIGHT = ["#cde2fb", "#9ec5f4", "#6da7ec", "#3987e5", "#256abf", "#184f95", "#0d366b"]
SEQUENTIAL_DARK = ["#0d366b", "#184f95", "#256abf", "#3987e5", "#6da7ec", "#9ec5f4", "#cde2fb"]
DIVERGING = {
    "light": [[0.0, "#2a78d6"], [0.5, "#f0efec"], [1.0, "#e34948"]],
    "dark": [[0.0, "#3987e5"], [0.5, "#383835"], [1.0, "#e66767"]],
}

# --- asignación de entidades a ranuras ---------------------------------------
# El color sigue a la entidad: un filtro que cambie el número de series no
# repinta a los supervivientes.
CHANNEL_SLOT = {
    "paid_social": 0,        # azul
    "influencer_code": 4,    # magenta
    "podcast_ads": 3,        # amarillo
    "referral": 5,           # verde
    "organic": 6,            # violeta
}
CHANNEL_LABEL = {
    "paid_social": "Paid social",
    "organic": "Orgánico",
    "influencer_code": "Código influencer",
    "referral": "Referido",
    "podcast_ads": "Podcast",
    "direct_unknown": "Directo / sin resolver",
}
MODEL_LABEL = {"first_touch": "First touch", "last_touch": "Last touch",
               "linear": "Linear", "markov": "Markov"}
MONTHS_ES = ["Ene", "Feb", "Mar", "Abr", "May", "Jun",
             "Jul", "Ago", "Sep", "Oct", "Nov", "Dic"]
WEEKDAYS_ES = ["Lun", "Mar", "Mié", "Jue", "Vie", "Sáb", "Dom"]


def tokens(mode: str) -> dict:
    return LIGHT if mode == "light" else DARK


def series(slot: int, mode: str = "light") -> str:
    """Color de una ranura categórica. Pasado el octavo se pliega, no se genera."""
    palette = SLOTS_LIGHT if mode == "light" else SLOTS_DARK
    if slot >= len(palette):
        raise ValueError(
            f"ranura {slot}: la paleta tiene {len(palette)}. Pliega la cola en "
            "'Otros' o facetea en múltiplos pequeños; no se generan hues nuevos."
        )
    return palette[slot]


def channel_color(channel: str, mode: str = "light") -> str:
    """`direct_unknown` va en gris a propósito: no es un canal."""
    if channel not in CHANNEL_SLOT:
        return tokens(mode)["ink_muted"]
    return series(CHANNEL_SLOT[channel], mode)


def sequential(mode: str = "light") -> list[list]:
    ramp = SEQUENTIAL_LIGHT if mode == "light" else SEQUENTIAL_DARK
    return [[i / (len(ramp) - 1), c] for i, c in enumerate(ramp)]


def diverging(mode: str = "light") -> list[list]:
    return DIVERGING[mode]


def layout(mode: str = "light", height: int = 380, **overrides) -> dict:
    """
    Layout base: rejilla de un tono sobre la superficie, sólida (nunca discontinua),
    ejes recesivos y sin fondo de plot propio.
    """
    t = tokens(mode)
    base = {
        "height": height,
        # Plotly formatea sus ejes y sus hovers por su cuenta: sin decírselo
        # salen con punto decimal mientras la prosa del informe usa coma.
        "separators": ", ",
        "paper_bgcolor": "rgba(0,0,0,0)",
        "plot_bgcolor": "rgba(0,0,0,0)",
        "font": {"family": "Inter, 'Segoe UI', system-ui, sans-serif",
                 "size": 13, "color": t["ink_secondary"]},
        "margin": {"l": 64, "r": 24, "t": 16, "b": 48},
        "xaxis": {"gridcolor": t["grid"], "griddash": "solid", "zeroline": False,
                  "linecolor": t["grid"], "tickcolor": t["grid"],
                  "title": {"font": {"size": 12, "color": t["ink_muted"]}}},
        "yaxis": {"gridcolor": t["grid"], "griddash": "solid", "zeroline": False,
                  "linecolor": t["grid"], "tickcolor": t["grid"],
                  "title": {"font": {"size": 12, "color": t["ink_muted"]}}},
        "legend": {"orientation": "h", "yanchor": "bottom", "y": 1.02, "x": 0,
                   "font": {"size": 12, "color": t["ink_secondary"]},
                   "bgcolor": "rgba(0,0,0,0)"},
        "hoverlabel": {"bgcolor": t["surface"], "bordercolor": t["border"],
                       "font": {"size": 12, "color": t["ink"]}},
        "hovermode": "x unified",
        "colorway": SLOTS_LIGHT if mode == "light" else SLOTS_DARK,
        "showlegend": True,
    }
    for key, value in overrides.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            base[key] = {**base[key], **value}
        else:
            base[key] = value
    return base
