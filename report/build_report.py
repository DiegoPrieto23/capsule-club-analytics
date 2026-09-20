"""
Capsule Club Analytics — generador del informe HTML.

Lee los seis JSON de `analysis/outputs/` y escribe un informe estático de siete
páginas en `report/dist/`, navegable con `file://` y sin servidor: Plotly va
vendorizado junto al HTML y no hay una sola petición remota.

    python report/build_report.py

Reparto de responsabilidades:

  - `theme.py`     la paleta validada, los tokens de superficie y el layout;
  - `figures.py`   una función por gráfico, que se llama dos veces (claro y
                   oscuro) y deja las dos especificaciones en el HTML, de modo
                   que el botón de tema elija en vez de recolorear;
  - `glossary.py`  las definiciones de los términos técnicos del informe;
  - `content.py`   qué se cuenta en cada página y qué se recomienda hacer;
  - este fichero   formato de números, montaje y render.

Ninguna cifra de la prosa se escribe a mano: todas se formatean desde el JSON,
para que el informe no pueda desincronizarse de los notebooks.
"""

from __future__ import annotations

import json
import shutil
import sys
from datetime import datetime
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import content                # noqa: E402
import theme as T             # noqa: E402

ROOT = HERE.parent
OUTPUTS = ROOT / "analysis" / "outputs"
DIST = HERE / "dist"
TEMPLATES = HERE / "templates"

MODES = ("light", "dark")
NBSP = " "      # espacio fino, para los miles


# ---------------------------------------------------------------- formato
# Todo en convención española: coma decimal y espacio fino como separador de
# miles. Se hace aquí y no dentro de las figuras porque Plotly formatea sus ejes
# por su cuenta y sólo estos números llegan a la prosa.

def _es(text: str) -> str:
    return text.replace(",", "\x00").replace(".", ",").replace("\x00", NBSP)


def num(value, decimals=0):
    return _es(f"{value:,.{decimals}f}")


def eur(value, decimals=0):
    return f"{num(value, decimals)}{NBSP}€"


def pct(value, decimals=1):
    return f"{num(value, decimals)}%"


def ratio(value, decimals=1):
    return f"{num(value, decimals)}×"


def month_es(iso):
    year, month, _ = iso.split("-")
    return f"{T.MONTHS_ES[int(month) - 1]} {year}"


FORMATTERS = {"eur": eur, "num": num, "pct": pct, "ratio": ratio, "month_es": month_es}


# ---------------------------------------------------------------- figuras

class Figure:
    """Una figura con sus dos especificaciones, su tabla y su ancho en la rejilla."""

    def __init__(self, fid, builder, data, title, alt, subtitle=None,
                 table=None, source=None, width="half"):
        self.id = fid
        self.title = title
        self.subtitle = subtitle
        self.alt = alt
        self.table = table
        self.source = source
        self.width = width
        self.specs = {}
        for mode in MODES:
            spec = builder(data, mode).to_plotly_json()
            self.specs[mode] = json.dumps(
                {"data": spec["data"], "layout": spec["layout"]},
                default=str, separators=(",", ":"))

    @property
    def light(self):
        return self.specs["light"]

    @property
    def dark(self):
        return self.specs["dark"]


def table(header, rows):
    return {"header": header, "rows": rows}


# ---------------------------------------------------------------- render

def load_data():
    data = {}
    for name in ("suscriptores", "ingresos", "capsulas", "cohorts_rfm",
                 "attribution", "cac_ltv"):
        path = OUTPUTS / f"{name}.json"
        if not path.exists():
            raise SystemExit(
                f"falta {path.relative_to(ROOT)}. Ejecuta antes los notebooks de analysis/."
            )
        data[name] = json.loads(path.read_text(encoding="utf-8"))
    return data


def main():
    data = load_data()
    pages = content.build(data, FORMATTERS, Figure, table)
    nav = [{"slug": p["slug"], "file": p["file"], "nav_title": p["nav_title"]} for p in pages]
    meta = {
        "history": f"{data['ingresos']['meta']['history_start'][:7]} … "
                   f"{data['ingresos']['meta']['history_end'][:7]}",
        "generated": datetime.now().strftime("%d/%m/%Y"),
    }

    # `select_autoescape` decide por la extensión del fichero, y estas plantillas
    # son `.j2`: sin nombrarla explícitamente el escapado queda apagado y la
    # primera comilla simple de una especificación de Plotly parte el atributo.
    env = Environment(
        loader=FileSystemLoader(str(TEMPLATES)),
        autoescape=select_autoescape(enabled_extensions=("html", "j2", "xml"),
                                     default_for_string=True, default=True),
        trim_blocks=True, lstrip_blocks=True)
    template = env.get_template("page.html.j2")

    DIST.mkdir(parents=True, exist_ok=True)
    assets = DIST / "assets"
    assets.mkdir(exist_ok=True)
    shutil.copyfile(TEMPLATES / "report.css", assets / "report.css")
    shutil.copyfile(TEMPLATES / "report.js", assets / "report.js")

    import plotly
    shutil.copyfile(Path(plotly.__file__).parent / "package_data" / "plotly.min.js",
                    assets / "plotly.min.js")

    for index, page in enumerate(pages):
        html = template.render(
            page=page, nav=nav, meta=meta, rel="",
            prev=pages[index - 1] if index else None,
            next=pages[index + 1] if index + 1 < len(pages) else None)
        (DIST / page["file"]).write_text(html, encoding="utf-8")

    total = sum((DIST / p["file"]).stat().st_size for p in pages)
    print(f"informe escrito en {DIST.relative_to(ROOT)}/")
    for page in pages:
        size = (DIST / page["file"]).stat().st_size / 1024
        figs = sum(len(s.get("figures", [])) for s in page["sections"])
        acts = len(page.get("actions", {}).get("steps", []))
        terms = len(page.get("glossary", []))
        print(f"  {page['file']:22s} {size:6.0f} KB · {figs} gráficos · "
              f"{acts} recomendaciones · {terms} términos")
    print(f"  assets/plotly.min.js   "
          f"{(assets / 'plotly.min.js').stat().st_size / 1024 / 1024:6.1f} MB (vendorizado)")
    print(f"total HTML: {total / 1024:.0f} KB · abre {DIST / 'index.html'}")


if __name__ == "__main__":
    main()
