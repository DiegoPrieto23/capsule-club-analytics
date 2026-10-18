"""
Capsule Club Analytics — utilidades compartidas de serie temporal.

Lógica común a las tres páginas de serie temporal del informe (suscriptores,
ingresos y demanda por sabor), para no reimplementarla en cada notebook:

  1. Preparación    — pasar un mart a una serie regular, sin huecos de calendario.
  2. Descomposición — STL y MSTL, con fuerza de tendencia y de estacionalidad.

Lo que este módulo NO hace, a propósito:

  - No limpia ni modela negocio: eso vive en dbt (ver CLAUDE.md). Aquí se asume
    que la entrada ya viene de un mart.
  - No escribe ficheros. Cada resultado expone `to_dict()` con tipos nativos de
    Python, listo para `json.dump` en `analysis/outputs/`.

Convenio de frecuencias: se usan los alias de pandas ("D" diario, "W" semanal,
"MS" inicio de mes). El histórico del proyecto son 3 años (2023-09 a 2026-08),
así que la serie mensual tiene 36 puntos: suficiente para STL anual, que
necesita 2 periodos completos.
"""

from __future__ import annotations

import warnings
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd
from statsmodels.tsa.seasonal import MSTL, STL

__all__ = [
    # preparación
    "build_series",
    "infer_season_length",
    "infer_seasonal_periods",
    "series_to_records",
    # descomposición
    "DecompositionResult",
    "stl_decompose",
    "mstl_decompose",
]


# =============================================================================
# 1. PREPARACIÓN DE SERIES
# =============================================================================

# Ciclo corto dominante de cada frecuencia. Para datos diarios el ciclo corto es
# la semana: el patrón anual se trata aparte (ver ANNUAL_PERIODS), porque STL
# sólo admite una estacionalidad a la vez.
SEASON_LENGTHS: dict[str, int] = {
    "h": 24, "H": 24,
    "D": 7,
    "B": 5,
    "W": 52,
    "MS": 12, "ME": 12, "M": 12,
    "QS": 4, "QE": 4, "Q": 4,
    "YS": 1, "YE": 1, "Y": 1, "A": 1,
}

# Longitud del ciclo anual en cada frecuencia. 365 (no 365.25) porque STL y MSTL
# exigen un periodo entero; el desfase de los bisiestos es despreciable en un
# histórico de 3 años.
ANNUAL_PERIODS: dict[str, int] = {
    "h": 8766, "H": 8766,
    "D": 365,
    "B": 261,
    "W": 52,
    "MS": 12, "ME": 12, "M": 12,
    "QS": 4, "QE": 4, "Q": 4,
}


def _base_freq(freq: str) -> str:
    """Normaliza un alias de pandas a su base: "2W-SUN" -> "W"."""
    base = str(freq).split("-", 1)[0]
    return base.lstrip("0123456789") or base


def _freq_of(series: pd.Series) -> str | None:
    """Frecuencia de la serie, tomada del índice o inferida de sus fechas."""
    freq = getattr(series.index, "freqstr", None) or getattr(series.index, "freq", None)
    if freq is None and len(series) >= 3:
        try:
            freq = pd.infer_freq(series.index)
        except (ValueError, TypeError):
            freq = None
    return str(freq) if freq is not None else None


def infer_season_length(source: str | pd.Series) -> int:
    """
    Longitud del ciclo estacional corto de una frecuencia o de una serie.

    Devuelve 1 (= sin estacionalidad) cuando la frecuencia no se reconoce, para
    que las métricas escaladas (MASE) degraden a naive en vez de romper.
    """
    freq = source if isinstance(source, str) else _freq_of(source)
    if freq is None:
        return 1
    return SEASON_LENGTHS.get(_base_freq(freq), 1)


def infer_seasonal_periods(source: str | pd.Series) -> tuple[int, ...]:
    """
    Periodos estacionales a modelar juntos con MSTL, de más corto a más largo.

    Para datos diarios devuelve (7, 365): la página 2 del informe pide enseñar
    estacionalidad semanal *y* anual, y STL sola no puede con las dos.
    """
    freq = source if isinstance(source, str) else _freq_of(source)
    if freq is None:
        return ()
    base = _base_freq(freq)
    periods = [p for p in (SEASON_LENGTHS.get(base), ANNUAL_PERIODS.get(base)) if p and p > 1]
    return tuple(sorted(set(periods)))


def build_series(
    frame: pd.DataFrame,
    date_col: str,
    value_col: str,
    freq: str = "MS",
    agg: str | Callable[..., Any] = "sum",
    fill_value: float | None = 0.0,
    start: str | pd.Timestamp | None = None,
    end: str | pd.Timestamp | None = None,
) -> pd.Series:
    """
    Agrega un mart a una serie temporal regular y sin huecos de calendario.

    El reindexado sobre el calendario completo es deliberado: un día sin filas en
    `fct_shop_orders` no debe desaparecer de la serie, porque ese cero de demanda
    es justo la señal que hay que interpretar — rotura de stock frente a "nadie
    lo quiso comprar" (ver docs/data_imperfections.md). Con `fill_value=None` los
    huecos se quedan como NaN, que es lo correcto cuando el cero no es un valor
    legítimo: el hueco de la migración de pasarela en la serie de caja no es un
    mes sin ingresos, es un mes sin dato.

    `start`/`end` fuerzan el rango cuando la serie no debe empezar en su primera
    fila (sabores lanzados a mitad del histórico) o debe llegar hasta el cierre
    del histórico aunque el SKU esté ya descatalogado.
    """
    if date_col not in frame.columns:
        raise KeyError(f"No existe la columna de fecha {date_col!r} en el DataFrame.")
    if value_col not in frame.columns:
        raise KeyError(f"No existe la columna de valor {value_col!r} en el DataFrame.")

    dates = pd.to_datetime(frame[date_col])
    values = pd.to_numeric(frame[value_col], errors="coerce")
    tidy = pd.Series(np.asarray(values), index=pd.DatetimeIndex(dates), name=value_col)
    tidy = tidy[tidy.index.notna()].sort_index()

    series = tidy.resample(freq).agg(agg)

    lo = pd.Timestamp(start) if start is not None else None
    hi = pd.Timestamp(end) if end is not None else None
    if lo is not None or hi is not None:
        # Se reconstruye el calendario completo para respetar el rango pedido,
        # que puede ser más ancho que el de los datos observados.
        first = lo if lo is not None else (series.index[0] if len(series) else None)
        last = hi if hi is not None else (series.index[-1] if len(series) else None)
        if first is None or last is None:
            raise ValueError("Serie vacía: hay que indicar `start` y `end` explícitos.")
        series = series.reindex(pd.date_range(first, last, freq=freq))

    if fill_value is not None:
        series = series.fillna(fill_value)

    series.name = value_col
    series.index.name = date_col
    return series.asfreq(freq)


def series_to_records(series: pd.Series, value_key: str = "value") -> list[dict[str, Any]]:
    """Serie -> lista de {"date": "YYYY-MM-DD", value_key: float|None} para JSON."""
    return [
        {"date": ts.strftime("%Y-%m-%d"), value_key: _jsonable_number(v)}
        for ts, v in series.items()
    ]


def _jsonable_number(value: Any) -> float | None:
    """NaN/inf -> None (JSON no los admite); numpy -> float nativo."""
    if value is None:
        return None
    number = float(value)
    return None if not np.isfinite(number) else number


def _as_clean_series(series: pd.Series, what: str) -> pd.Series:
    """Valida que la entrada es una serie numérica con índice temporal ordenado."""
    if not isinstance(series, pd.Series):
        raise TypeError(f"{what} espera un pd.Series, no {type(series).__name__}.")
    if not isinstance(series.index, pd.DatetimeIndex):
        raise TypeError(f"{what} espera un índice DatetimeIndex.")
    if not series.index.is_monotonic_increasing:
        series = series.sort_index()
    return series.astype(float)


# =============================================================================
# 2. DESCOMPOSICIÓN (STL / MSTL)
# =============================================================================

@dataclass
class DecompositionResult:
    """
    Resultado de una descomposición, con una o varias estacionalidades.

    `seasonal` va siempre indexado por periodo: {7: Series, 365: Series}. Así el
    notebook trata igual el caso STL (un periodo) y el MSTL (varios), y la
    plantilla del informe puede iterar sin saber cuál de los dos se usó.
    """

    method: str
    observed: pd.Series
    trend: pd.Series
    seasonal: dict[int, pd.Series]
    resid: pd.Series
    periods: tuple[int, ...]
    trend_strength: float
    seasonal_strength: dict[int, float]
    robust: bool = True

    @property
    def seasonal_total(self) -> pd.Series:
        """Suma de todas las componentes estacionales."""
        if not self.seasonal:
            return pd.Series(0.0, index=self.observed.index)
        return sum(self.seasonal.values())

    @property
    def seasonally_adjusted(self) -> pd.Series:
        """Serie desestacionalizada (observado - estacionalidad)."""
        return self.observed - self.seasonal_total

    def to_frame(self) -> pd.DataFrame:
        """Componentes en un DataFrame, para graficar de un tirón."""
        data = {"observed": self.observed, "trend": self.trend}
        for period, component in self.seasonal.items():
            data[f"seasonal_{period}"] = component
        data["resid"] = self.resid
        return pd.DataFrame(data)

    def to_dict(self) -> dict[str, Any]:
        """Estructura JSON-safe para analysis/outputs/*.json."""
        return {
            "method": self.method,
            "periods": list(self.periods),
            "robust": self.robust,
            "trend_strength": _jsonable_number(self.trend_strength),
            "seasonal_strength": {
                str(p): _jsonable_number(v) for p, v in self.seasonal_strength.items()
            },
            "dates": [ts.strftime("%Y-%m-%d") for ts in self.observed.index],
            "observed": [_jsonable_number(v) for v in self.observed],
            "trend": [_jsonable_number(v) for v in self.trend],
            "seasonal": {
                str(p): [_jsonable_number(v) for v in comp]
                for p, comp in self.seasonal.items()
            },
            "resid": [_jsonable_number(v) for v in self.resid],
        }


def _variance(values: pd.Series | np.ndarray) -> float:
    arr = np.asarray(values, dtype=float)
    arr = arr[np.isfinite(arr)]
    return float(np.var(arr, ddof=1)) if arr.size > 1 else 0.0


def _component_strength(component: pd.Series, resid: pd.Series) -> float:
    """
    Fuerza de una componente (Hyndman & Athanasopoulos, FPP3 §4.3):
    1 - Var(R) / Var(componente + R), acotada a [0, 1].

    Sirve para decidir con un número, y no a ojo, si merece la pena modelar la
    estacionalidad de un SKU o si lo que se ve en el gráfico es ruido.
    """
    denom = _variance(component + resid)
    if denom <= 0:
        return 0.0
    return float(np.clip(1.0 - _variance(resid) / denom, 0.0, 1.0))


def _require_no_nan(series: pd.Series, what: str) -> None:
    n_missing = int(series.isna().sum())
    if n_missing:
        raise ValueError(
            f"{what} no admite huecos: la serie tiene {n_missing} NaN. "
            "Rellénalos al construirla (`build_series(..., fill_value=...)`) o "
            "interpólalos explícitamente, dejando constancia de la decisión."
        )


def _check_length(series: pd.Series, period: int, what: str) -> None:
    if period < 2:
        raise ValueError(f"{what} necesita un periodo >= 2; recibido {period}.")
    if len(series) < 2 * period:
        raise ValueError(
            f"{what} necesita al menos 2 ciclos completos: {2 * period} "
            f"observaciones para period={period}, y la serie tiene {len(series)}. "
            "Baja la frecuencia de agregación o usa un periodo más corto."
        )


def stl_decompose(
    series: pd.Series,
    period: int | None = None,
    seasonal: int | None = None,
    robust: bool = True,
    seasonal_deg: int = 0,
) -> DecompositionResult:
    """
    Descomposición STL en tendencia + estacionalidad + residuo.

    `period` se infiere de la frecuencia del índice si no se indica (12 para
    mensual, 7 para diario). `robust=True` por defecto a propósito: el histórico
    tiene picos de campaña y meses de dunning que, sin ponderación robusta, se
    reparten entre tendencia y estacionalidad y contaminan las dos.

    `seasonal_deg=0` (estacional localmente constante, no una recta) es lo que hace
    que la robustez funcione con pocos ciclos. Con 36 meses cada mes del año tiene
    tres valores, la recta del suavizado estacional casi pasa por ellos, el residuo
    queda en ~1e-16 y la escala robusta (6 × mediana del residuo) se hunde: los
    pesos salen 0 durante un año entero y la tendencia pasa a depender del último
    bit (multiplicar la serie por 1 + 2·eps la movía un 2%), así que Windows y
    Linux publicaban cifras distintas. Con grado 0 sólo se descartan los meses
    raros de verdad y la descomposición es estable al redondeo.
    """
    series = _as_clean_series(series, "stl_decompose")
    _require_no_nan(series, "STL")

    if period is None:
        period = infer_season_length(series)
        if period < 2:
            raise ValueError(
                "No se pudo inferir el periodo estacional del índice. "
                "Pásalo explícito: stl_decompose(serie, period=12)."
            )
    _check_length(series, period, "STL")

    kwargs: dict[str, Any] = {"period": int(period), "robust": robust, "seasonal_deg": int(seasonal_deg)}
    if seasonal is not None:
        if seasonal < 7 or seasonal % 2 == 0:
            raise ValueError(f"`seasonal` debe ser impar y >= 7; recibido {seasonal}.")
        kwargs["seasonal"] = int(seasonal)

    fitted = STL(series, **kwargs).fit()
    trend = pd.Series(np.asarray(fitted.trend, dtype=float), index=series.index, name="trend")
    seas = pd.Series(
        np.asarray(fitted.seasonal, dtype=float), index=series.index, name=f"seasonal_{period}"
    )
    resid = pd.Series(np.asarray(fitted.resid, dtype=float), index=series.index, name="resid")

    return DecompositionResult(
        method="STL",
        observed=series,
        trend=trend,
        seasonal={int(period): seas},
        resid=resid,
        periods=(int(period),),
        trend_strength=_component_strength(trend, resid),
        seasonal_strength={int(period): _component_strength(seas, resid)},
        robust=robust,
    )


def mstl_decompose(
    series: pd.Series,
    periods: Sequence[int] | None = None,
    robust: bool = True,
    **stl_kwargs: Any,
) -> DecompositionResult:
    """
    Descomposición con varias estacionalidades a la vez (MSTL).

    Pensada para las series diarias, donde conviven el patrón semanal y el anual.
    Los periodos que no caben en el histórico (hacen falta 2 ciclos completos) se
    descartan con un aviso en vez de reventar: con 3 años de datos el ciclo anual
    entra justo, y en cuanto se recorta la ventana deja de entrar.
    """
    series = _as_clean_series(series, "mstl_decompose")
    _require_no_nan(series, "MSTL")

    if periods is None:
        periods = infer_seasonal_periods(series)
    requested = sorted({int(p) for p in periods if p and int(p) >= 2})
    if not requested:
        raise ValueError(
            "No hay periodos estacionales que modelar. Indícalos explícitos: "
            "mstl_decompose(serie, periods=(7, 365))."
        )

    too_long = [p for p in requested if len(series) < 2 * p]
    usable = [p for p in requested if p not in too_long]
    if too_long:
        warnings.warn(
            f"Periodos descartados por serie corta ({len(series)} obs.): {too_long}. "
            "Hacen falta 2 ciclos completos de cada periodo.",
            stacklevel=2,
        )
    if not usable:
        raise ValueError(
            f"La serie tiene {len(series)} observaciones: no admite ninguno de los "
            f"periodos pedidos {requested}."
        )

    if len(usable) == 1:
        # Con una sola estacionalidad, MSTL es STL con más indirección.
        return stl_decompose(series, period=usable[0], robust=robust, **stl_kwargs)

    fitted = MSTL(series, periods=usable, stl_kwargs={"robust": robust, **stl_kwargs}).fit()

    seasonal_frame = fitted.seasonal
    if isinstance(seasonal_frame, pd.Series):
        seasonal_frame = seasonal_frame.to_frame()
    seasonal = {
        int(period): pd.Series(
            np.asarray(seasonal_frame.iloc[:, i], dtype=float),
            index=series.index,
            name=f"seasonal_{period}",
        )
        for i, period in enumerate(usable)
    }
    trend = pd.Series(np.asarray(fitted.trend, dtype=float), index=series.index, name="trend")
    resid = pd.Series(np.asarray(fitted.resid, dtype=float), index=series.index, name="resid")

    return DecompositionResult(
        method="MSTL",
        observed=series,
        trend=trend,
        seasonal=seasonal,
        resid=resid,
        periods=tuple(usable),
        trend_strength=_component_strength(trend, resid),
        seasonal_strength={p: _component_strength(s, resid) for p, s in seasonal.items()},
        robust=robust,
    )
